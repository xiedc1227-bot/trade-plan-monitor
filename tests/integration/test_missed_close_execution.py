"""Real offline discovery/state/evaluator execution across a two-close outage."""

import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_ten_symbol_runtime import _daily_bar, _runtime_context, _runtime_plan

from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.notifications.outbox import AlertOutbox
from trade_plan_monitor.runtime.historical_close_context import (
    HistoricalCloseUnavailableError,
    HistoricalOfficialContextBuilder,
)
from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
from trade_plan_monitor.runtime.market_indexes import RuntimeMarketIndexService
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.projections import ProjectionRepository
from trade_plan_monitor.state.repositories import EvaluationRepository
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

D1 = date(2026, 8, 24)
D2 = date(2026, 8, 25)
ZONE = ZoneInfo("Asia/Shanghai")
OBSERVED = datetime(2026, 8, 25, 17, tzinfo=ZONE)


@pytest.fixture
def recovery(tmp_path):
    engine = create_sqlite_engine(tmp_path / "missed-closes.db")
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    plan = _runtime_plan()
    clock = [datetime(2026, 8, 24, 9, tzinfo=ZONE)]

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: clock[0])

    with work() as unit:
        unit.plans.save_draft(plan, source_text="offline missed-close fixture")
        unit.plans.activate(plan, expected_revision=0, validation=validate_trade_plan(
            plan, available_market_evidence=ALL_MARKET_EVIDENCE,
        ))
        lot = unit.positions.record_buy(
            symbol=plan.symbol, bucket="CORE", quantity=200, acquired_trade_date=date(2026, 8, 21),
            cost_fen=6300, board_lot=100, max_position_qty=200,
        )
        unit.references.upsert_trading_days(tuple(
            TradingDay(exchange=exchange, cal_date=day, is_open=True, previous_trade_date=prior)
            for exchange in ("SSE", "SZSE")
            for day, prior in ((date(2026, 8, 21), date(2026, 8, 20)),
                               (D1, date(2026, 8, 21)), (D2, D1))
        ))
        unit.history.upsert_daily_bars((_daily_bar(
            trade_date=date(2026, 8, 21), close_fen=6200, is_official=True,
        ),))
        unit.commit()
    clock[0] = datetime(2026, 8, 25, 9, tzinfo=ZONE)
    with work() as unit:
        unit.positions.reduce_lot(lot.id, quantity=100, trade_date=D1)
        unit.commit()
    clock[0] = OBSERVED + timedelta(seconds=1)
    prices = {D1: 6000, D2: 5950}
    published = []

    async def daily(symbol, day, attempt):
        return (_daily_bar(trade_date=day, close_fen=prices[day], is_official=True),)

    async def forbidden_minutes(*_args):
        pytest.fail("historical close must not request minute data")

    def service(*, evaluator=evaluate, delivery=True, publisher=published.append,
                index_service=None):
        return RuntimeEvaluationService(
            fetch_minutes=forbidden_minutes, fetch_official_daily=daily,
            official_observed_at=lambda value: value, unit_of_work_factory=work,
            context_builder=_runtime_context,
            official_context_builder=HistoricalOfficialContextBuilder(
                LegacyHistoricalCloseReader(sessions),
            ),
            evaluator=evaluator, recovery_delivery=delivery,
            committed_event_publisher=publisher,
            market_index_service=index_service,
        )

    def run(day, **options):
        clock[0] += timedelta(seconds=2)
        return asyncio.run(service(**options).run_official_close(
            plan=plan, trade_date=day, evaluated_at=clock[0] - timedelta(seconds=1),
            close_attempt=1,
        ))

    yield SimpleNamespace(engine=engine, sessions=sessions, work=work, plan=plan, lot=lot,
                          clock=clock, prices=prices, run=run, published=published,
                          service=service)
    engine.dispose()


def _counts(recovery):
    with recovery.engine.connect() as connection:
        return tuple(connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in (
            "evaluation_ledger", "evaluation_result", "risk_state", "alert_event",
        ))


def test_two_missed_closes_use_historical_holdings_and_source_risk_time_after_reopen(recovery):
    first = recovery.run(D1)
    assert first.status == "COMMITTED"
    assert first.evaluation_result.snapshot.signal_type == "RISK_BREACH"
    assert first.evaluation_result.snapshot.position.total_quantity == 200
    recovery.engine.dispose()
    second = recovery.run(D2)
    assert second.status == "COMMITTED"
    assert second.evaluation_result.snapshot.signal_type == "RISK_EXIT_READY"
    assert second.evaluation_result.snapshot.position.total_quantity == 100
    assert second.evaluation_result.snapshot.risk.updated_at == datetime(
        2026, 8, 24, 15, tzinfo=ZONE,
    )
    assert second.evaluation_result.signal_intent.quantity == 100
    with recovery.engine.connect() as connection:
        saved = connection.execute(text(
            "SELECT position_lots_json FROM evaluation_result ORDER BY target_value"
        )).scalars().all()
        assert [json.loads(item)[0]["remaining_qty"] for item in saved] == [200, 100]
        assert connection.scalar(text("SELECT remaining_qty FROM position_lot")) == 100
        assert connection.execute(text(
            "SELECT status FROM alert_delivery_eligibility"
        )).scalars().all() == ["HOLD", "HOLD"]
    before = _counts(recovery)
    recovery.engine.dispose()
    assert recovery.run(D1).status == recovery.run(D2).status == "DUPLICATE"
    assert _counts(recovery) == before == (2, 2, 1, 2)


def test_cannot_skip_an_earlier_missing_close(recovery):
    with pytest.raises(HistoricalCloseUnavailableError):
        recovery.run(D2)
    assert _counts(recovery) == (0, 0, 0, 0)
    with recovery.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM pending_official_close")) == 0
    assert recovery.run(D1).status == "COMMITTED"


def test_failure_before_result_save_rolls_back_then_retry_commits_once(recovery, monkeypatch):
    original = ProjectionRepository.add_evaluation_result

    def crash(*_args, **_kwargs):
        raise RuntimeError("simulated exit before result save")

    monkeypatch.setattr(ProjectionRepository, "add_evaluation_result", crash)
    with pytest.raises(RuntimeError, match="simulated exit"):
        recovery.run(D1)
    assert _counts(recovery) == (0, 0, 0, 0)
    recovery.engine.dispose()
    monkeypatch.setattr(ProjectionRepository, "add_evaluation_result", original)
    assert recovery.run(D1).status == "COMMITTED"
    assert recovery.run(D1).status == "DUPLICATE"
    assert _counts(recovery) == (1, 1, 1, 1)


def test_concurrent_manual_sale_rejects_even_wait_result(recovery):
    recovery.prices[D1] = 6200

    def changed_inventory(context):
        with recovery.work() as unit:
            unit.positions.reduce_lot(recovery.lot.id, quantity=100, trade_date=D1)
            unit.commit()
        return evaluate(context)

    with pytest.raises(RuntimeError, match="Historical close inputs changed"):
        recovery.run(D1, evaluator=changed_inventory)
    assert _counts(recovery) == (0, 0, 0, 0)


def test_historical_path_requires_hold_delivery(recovery):
    with pytest.raises(ValueError, match="recovery_delivery"):
        recovery.run(D1, delivery=False)
    assert _counts(recovery) == (0, 0, 0, 0)


def test_missing_inventory_evidence_does_not_commit_a_blocked_result(recovery):
    with recovery.engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_log WHERE action='POSITION_INVENTORY_CHANGED'"))
    with pytest.raises(HistoricalCloseUnavailableError):
        recovery.run(D1)
    assert _counts(recovery) == (0, 0, 0, 0)


def test_risk_write_without_publication_rejects_even_wait_result(recovery):
    recovery.prices[D1] = 6200

    def changed_risk(context):
        with recovery.work() as unit:
            unit.risk.upsert(
                symbol=context.plan.symbol, plan_hash=context.plan_hash, status="CLEAR",
                breach_trade_date=None, prior_close_fen=6200, expected_revision=0,
            )
            unit.commit()
        return evaluate(context)

    with pytest.raises(RuntimeError, match="Historical close inputs changed"):
        recovery.run(D1, evaluator=changed_risk)
    assert _counts(recovery) == (0, 0, 1, 0)


def test_write_after_fences_cannot_upgrade_old_snapshot_and_retry_rebuilds(recovery, monkeypatch):
    original = EvaluationRepository.claim

    def interleaved_claim(repository, **kwargs):
        with recovery.work() as unit:
            unit.positions.reduce_lot(recovery.lot.id, quantity=100, trade_date=D1)
            unit.commit()
        return original(repository, **kwargs)

    monkeypatch.setattr(EvaluationRepository, "claim", interleaved_claim)
    with pytest.raises(OperationalError, match="locked"):
        recovery.run(D1)
    assert _counts(recovery) == (0, 0, 0, 0)
    recovery.engine.dispose()
    monkeypatch.setattr(EvaluationRepository, "claim", original)
    retried = recovery.run(D1)
    assert retried.status == "COMMITTED"
    assert retried.evaluation_result.snapshot.position.total_quantity == 200
    with recovery.engine.connect() as connection:
        assert connection.scalar(text("SELECT remaining_qty FROM position_lot")) == 0
    assert recovery.run(D1).status == "DUPLICATE"


def test_exit_after_outbox_insert_rolls_back_result_risk_and_hold_together(recovery, monkeypatch):
    original = AlertOutbox.enqueue_recoverable

    def interrupted_enqueue(outbox, payload):
        original(outbox, payload)
        raise RuntimeError("simulated exit after outbox insert")

    monkeypatch.setattr(AlertOutbox, "enqueue_recoverable", interrupted_enqueue)
    with pytest.raises(RuntimeError, match="simulated exit"):
        recovery.run(D1)
    assert _counts(recovery) == (0, 0, 0, 0)
    with recovery.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM alert_delivery_eligibility")) == 0
    recovery.engine.dispose()
    monkeypatch.setattr(AlertOutbox, "enqueue_recoverable", original)
    assert recovery.run(D1).status == "COMMITTED"
    assert recovery.run(D1).status == "DUPLICATE"
    assert _counts(recovery) == (1, 1, 1, 1)


def test_reading_missing_inventory_revision_does_not_create_inventory(recovery):
    with recovery.work() as unit:
        assert unit.positions.get_inventory_revision("000001.SZ") is None
        unit.commit()
    with recovery.engine.connect() as connection:
        assert connection.scalar(text(
            "SELECT count(*) FROM position_inventory_state WHERE symbol='000001.SZ'"
        )) == 0


def test_opening_balance_is_not_silently_omitted_from_historical_evaluation(recovery):
    recovery.clock[0] = datetime(2026, 8, 25, 10, tzinfo=ZONE)
    with recovery.work() as unit:
        unit.positions.confirm_inventory(
            symbol=recovery.plan.symbol, as_of_trade_date=D2, total_quantity=200,
            sellable_quantity=200, included_lot_ids=(recovery.lot.id,),
            complete_registration=True, expected_revision=2,
        )
        unit.commit()
    recovery.clock[0] = OBSERVED
    assert recovery.run(D1).status == "COMMITTED"
    with pytest.raises(HistoricalCloseUnavailableError, match="opening balances"):
        recovery.run(D2)
    assert _counts(recovery) == (1, 1, 1, 1)


def test_concurrent_other_symbol_publication_invalidates_prepared_snapshot(recovery):
    recovery.prices[D1] = 6200

    def other_symbol_changed(context):
        with recovery.work() as unit:
            unit.positions.record_buy(
                symbol="000001.SZ", bucket="CORE", quantity=100, acquired_trade_date=D2,
                cost_fen=1000, board_lot=100, max_position_qty=100,
            )
            unit.commit()
        return evaluate(context)

    with pytest.raises(RuntimeError, match="Historical close inputs changed"):
        recovery.run(D1, evaluator=other_symbol_changed)
    assert _counts(recovery) == (0, 0, 0, 0)
    assert recovery.run(D1).status == "COMMITTED"


def test_stale_activation_cannot_commit_prepared_historical_result(recovery):
    def deactivate(context):
        with recovery.work() as unit:
            active = unit.plans.get_active(context.plan.symbol)
            unit.plans.deactivate(context.plan.symbol, expected_revision=active.revision)
            unit.commit()
        return evaluate(context)

    with pytest.raises(RuntimeError):
        recovery.run(D1, evaluator=deactivate)
    assert _counts(recovery) == (0, 0, 0, 0)


def test_publication_failure_after_commit_keeps_one_durable_result_on_reopen(recovery):
    def interrupted_publication(event):
        if event.event_type == "alert.created":
            raise RuntimeError("simulated exit after commit")

    with pytest.raises(RuntimeError, match="simulated exit after commit"):
        recovery.run(D1, publisher=interrupted_publication)
    assert _counts(recovery) == (1, 1, 1, 1)
    recovery.engine.dispose()
    assert recovery.run(D1).status == "DUPLICATE"
    assert _counts(recovery) == (1, 1, 1, 1)


def test_missing_plan_calendar_does_not_permanently_claim_blocked_close(recovery):
    with recovery.engine.begin() as connection:
        connection.execute(text(
            "DELETE FROM trading_calendar WHERE exchange='SZSE' AND cal_date=:day"
        ), {"day": D1.isoformat()})
    with pytest.raises(HistoricalCloseUnavailableError):
        recovery.run(D1)
    assert _counts(recovery) == (0, 0, 0, 0)
    with recovery.work() as unit:
        unit.references.upsert_trading_days((TradingDay(
            exchange="SZSE", cal_date=D1, is_open=True, previous_trade_date=date(2026, 8, 21),
        ),))
        unit.commit()
    assert recovery.run(D1).status == "COMMITTED"


def test_out_of_order_target_is_rejected_before_shared_index_preparation(
    recovery, monkeypatch,
):
    calls = []

    async def index_prepare(_service, **_kwargs):
        calls.append(True)
        raise AssertionError("index preparation must not run for an invalid target")

    monkeypatch.setattr(RuntimeMarketIndexService, "prepare", index_prepare)
    with pytest.raises(HistoricalCloseUnavailableError):
        asyncio.run(recovery.service(index_service=object.__new__(RuntimeMarketIndexService))
                    .run_official_close(
                        plan=recovery.plan, trade_date=D2, evaluated_at=OBSERVED,
                        close_attempt=1,
                    ))
    assert calls == []
    assert _counts(recovery) == (0, 0, 0, 0)


def test_duplicate_target_can_reach_existing_shared_index_path(recovery, monkeypatch):
    assert recovery.run(D1).status == "COMMITTED"
    calls = []

    async def index_prepare(_service, **_kwargs):
        calls.append(True)
        raise RuntimeError("existing index path reached")

    monkeypatch.setattr(RuntimeMarketIndexService, "prepare", index_prepare)
    with pytest.raises(RuntimeError, match="existing index path reached"):
        asyncio.run(recovery.service(index_service=object.__new__(RuntimeMarketIndexService))
                    .run_official_close(
                        plan=recovery.plan, trade_date=D1, evaluated_at=OBSERVED,
                        close_attempt=1,
                    ))
    assert calls == [True]
    assert _counts(recovery) == (1, 1, 1, 1)
