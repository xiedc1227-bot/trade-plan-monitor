from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.runtime.explicit_service import (
    ExplicitRuntimeCycleStatus,
    ExplicitRuntimeEvaluationService,
    StaleExplicitDecisionError,
)
from trade_plan_monitor.runtime.production import create_explicit_runtime_evaluation_service
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import (
    ActivePlan,
    PlanActivationState,
    PlanSource,
    PlanVersion,
)
from trade_plan_monitor.state.repositories import ManualEventRiskStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = datetime(2026, 9, 14, 10, 5, tzinfo=SHANGHAI)
TARGET_DATE = TARGET.date()
PREPARED_AT = TARGET - timedelta(minutes=10)
NOW = TARGET + timedelta(seconds=2)


def _plan(*, safety: bool = False, active_date: date = TARGET_DATE) -> ExplicitTradePlan:
    return ExplicitTradePlan.model_validate(
        {
            "schema_version": 3,
            "execution_mode": "EXPLICIT_RULES",
            "execution_version": "explicit-rules-v1",
            "plan_id": "isolated-r09-buy",
            "version": 1,
            "symbol": "003043.SZ",
            "name": "ISOLATED R09 BUY SUBSET",
            "market": "SZSE",
            "metadata": {},
            "activation": {"mode": "TRADING_DAY", "trading_day": active_date.isoformat()},
            "position": {
                "inventory_scope": "ALL_REGISTERED",
                "lot_size": 100,
                "max_qty": 300,
            },
            "monitoring": {
                "timeframe_minutes": 5,
                "indicator_formula_version": "ta-v1",
            },
            "rules": [
                {
                    "rule_id": "buy-100",
                    "condition": {
                        "type": "ALL",
                        "conditions": [
                            {
                                "type": "COMPLETED_CLOSE_IN_RANGE",
                                "low_fen": 980,
                                "high_fen": 1000,
                                "include_low": True,
                                "include_high": True,
                            },
                            {
                                "type": "VOLUME_TO_MEAN_GTE",
                                "window_bars": 5,
                                "minimum_ratio": "1.5",
                                "history_scope": "CONTIGUOUS_TRADING_BARS",
                            },
                        ],
                    },
                    "action": {"type": "BUY", "quantity": 100},
                    "confirmation": {
                        "kind": "COMPLETED_BAR_CLOSE",
                        "timeframe_minutes": 5,
                    },
                    "repeat_policy": {"mode": "ONCE_PER_ACTIVATION"},
                    "safety_conditions": (
                        {"type": "MANUAL_EVENT_RISK_CLEAR"} if safety else None
                    ),
                }
            ],
            "conflict_policy": {
                "trade_conflict": "BLOCK_BOTH",
                "risk_conflict": "RISK_ONLY",
            },
        }
    )


def _work(engine, *, now: datetime = NOW):
    return SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: now)


def _seed_active(engine, plan: ExplicitTradePlan) -> None:
    source_id = str(uuid4())
    version_id = str(uuid4())
    source_text = "isolated trusted R09 fixture; not public review"
    with create_session_factory(engine)() as session, session.begin():
        session.add(
            PlanSource(
                id=source_id,
                source_text=source_text,
                source_hash=sha256(source_text.encode()).hexdigest(),
                created_at=PREPARED_AT.isoformat(),
            )
        )
        session.flush()
        session.add(
            PlanVersion(
                id=version_id,
                plan_id=plan.plan_id,
                version=plan.version,
                symbol=plan.symbol,
                plan_hash=plan_sha256(plan),
                status="ACTIVE",
                payload_json=dump_plan_json(plan),
                source_id=source_id,
                revision=1,
                created_at=PREPARED_AT.isoformat(),
            )
        )
        session.flush()
        session.add_all(
            (
                PlanActivationState(
                    symbol=plan.symbol,
                    plan_version_id=version_id,
                    revision=1,
                    changed_at=PREPARED_AT.isoformat(),
                ),
                ActivePlan(
                    symbol=plan.symbol,
                    plan_version_id=version_id,
                    activated_at=PREPARED_AT.isoformat(),
                    revision=1,
                ),
            )
        )


def _seed_facts(engine, plan: ExplicitTradePlan, *, current_volume: int = 300) -> None:
    first = TARGET - timedelta(minutes=25)
    volumes = (100, 100, 100, 100, 600, current_volume)
    with _work(engine, now=PREPARED_AT) as work:
        work.references.upsert_trading_days(
            (
                TradingDay(
                    exchange="SZSE",
                    cal_date=TARGET.date(),
                    is_open=True,
                    previous_trade_date=date(2026, 9, 11),
                ),
            )
        )
        for index, volume in enumerate(volumes):
            work.history.upsert_five_minute(
                **FiveMinuteBar(
                    symbol=plan.symbol,
                    bar_end=first + timedelta(minutes=index * 5),
                    open_fen=990,
                    high_fen=990,
                    low_fen=990,
                    close_fen=990,
                    volume_shares=volume,
                    amount_yuan=Decimal("0"),
                ).model_dump()
            )
        work.positions.confirm_inventory(
            symbol=plan.symbol,
            as_of_trade_date=TARGET.date(),
            total_quantity=100,
            sellable_quantity=100,
            included_lot_ids=(),
            complete_registration=True,
            expected_revision=0,
        )
        if plan.rules[0].safety_conditions is not None:
            work.manual_event_risk.upsert(
                symbol=plan.symbol,
                plan_hash=plan_sha256(plan),
                status=ManualEventRiskStatus.CLEAR,
                expires_on=TARGET.date(),
                expected_revision=0,
            )
        work.commit()


def _database(tmp_path: Path, name: str, *, current_volume: int = 300, safety=False):
    engine = create_sqlite_engine(tmp_path / name)
    upgrade_database(engine)
    plan = _plan(safety=safety)
    _seed_active(engine, plan)
    _seed_facts(engine, plan, current_volume=current_volume)
    return engine, plan


def test_production_sqlite_dispatch_requires_price_and_mean_volume_then_deduplicates(
    tmp_path: Path,
) -> None:
    false_engine, false_plan = _database(
        tmp_path, "explicit-price-only.sqlite3", current_volume=299
    )
    true_engine, true_plan = _database(tmp_path, "explicit-qualified.sqlite3")
    try:
        false_service = create_explicit_runtime_evaluation_service(
            lambda: _work(false_engine)
        )
        false_cycle = false_service.run_intraday(
            plan=false_plan, target_bucket_end=TARGET, evaluated_at=NOW
        )
        assert false_cycle.committed_events == ()

        true_service = create_explicit_runtime_evaluation_service(lambda: _work(true_engine))
        first = true_service.run_intraday(
            plan=true_plan, target_bucket_end=TARGET, evaluated_at=NOW
        )
        replay = true_service.run_intraday(
            plan=true_plan, target_bucket_end=TARGET, evaluated_at=NOW
        )
        assert first.status is ExplicitRuntimeCycleStatus.COMMITTED
        assert first.committed_events[0].quantity == 100
        assert replay.status is ExplicitRuntimeCycleStatus.DUPLICATE
        assert replay.committed_events == ()
    finally:
        false_engine.dispose()
        true_engine.dispose()


def test_expired_explicit_plan_commits_evidence_but_never_a_new_buy_alert(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "explicit-expired.sqlite3")
    upgrade_database(engine)
    plan = _plan(active_date=date(2026, 9, 11))
    _seed_active(engine, plan)
    _seed_facts(engine, plan)
    try:
        cycle = create_explicit_runtime_evaluation_service(lambda: _work(engine)).run_intraday(
            plan=plan,
            target_bucket_end=TARGET,
            evaluated_at=NOW,
        )
        assert cycle.status is ExplicitRuntimeCycleStatus.COMMITTED
        assert cycle.committed_events == ()
        assert "PLAN_INACTIVE" in cycle.evaluation_result.rule_results[0].blockers
    finally:
        engine.dispose()


@pytest.mark.parametrize("mutation", ["activation", "inventory", "manual-risk"])
def test_commit_guard_rejects_concurrent_consumed_revision_changes(
    tmp_path: Path,
    mutation: str,
) -> None:
    engine, plan = _database(tmp_path, f"explicit-stale-{mutation}.sqlite3", safety=True)

    def mutate(_result) -> None:
        with _work(engine) as work:
            if mutation == "activation":
                work.plans.deactivate(plan.symbol, expected_revision=1)
            elif mutation == "inventory":
                work.positions.confirm_inventory(
                    symbol=plan.symbol,
                    as_of_trade_date=TARGET.date(),
                    total_quantity=100,
                    sellable_quantity=100,
                    included_lot_ids=(),
                    complete_registration=True,
                    expected_revision=1,
                )
            else:
                work.manual_event_risk.upsert(
                    symbol=plan.symbol,
                    plan_hash=plan_sha256(plan),
                    status=ManualEventRiskStatus.RISK_PRESENT,
                    expires_on=TARGET.date(),
                    expected_revision=1,
                )
            work.commit()

    try:
        service = ExplicitRuntimeEvaluationService(lambda: _work(engine), after_evaluate=mutate)
        with pytest.raises(StaleExplicitDecisionError):
            service.run_intraday(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
        with _work(engine) as work:
            assert work.explicit_rules.states(
                plan_hash=plan_sha256(plan), symbol=plan.symbol, activation_revision=1
            ) == ()
            listed, total = work.alerts.list_events(
                symbol=plan.symbol,
                signal_type="BUY",
                acknowledged=None,
                start_at=None,
                end_at=None,
                offset=0,
                limit=10,
            )
            assert listed == () and total == 0
    finally:
        engine.dispose()
