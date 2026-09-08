"""Certified production wiring, exercised against the real SQLite boundary."""

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.live_profiles import create_stock_certification, write_live_certification
from trade_plan_monitor.market_data.models import ProviderCapabilities, ProviderCapabilityStatus
from trade_plan_monitor.market_data.sessions import SourceTimeLabel
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.web.monitor_composition import _ProductionRuntimeState

NOW = datetime(2026, 9, 8, 10, 0, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


class Clock:
    current = NOW

    def now(self):
        return self.current

    async def sleep_until(self, deadline):
        return None


@pytest.mark.parametrize("label", [SourceTimeLabel.START, SourceTimeLabel.UNVERIFIED])
def test_production_capability_gate_consumes_fresh_local_stock_evidence(tmp_path: Path, label):
    config = tmp_path / "config" / "app.yaml"
    config.parent.mkdir()
    config.write_text(
        "tushare:\n  api_url: https://example.test\n  token: test-token\n", encoding="utf-8"
    )
    capabilities = ProviderCapabilities(
        **{key: ProviderCapabilityStatus.READY for key in ProviderCapabilities.model_fields}
    )
    write_live_certification(
        tmp_path / "data" / "live-certification" / "tushare-stock-live.json",
        create_stock_certification(
            observed_at=NOW,
            endpoint_url="https://example.test",
            capabilities=capabilities,
            source_time_label=label,
        ),
    )
    engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
    controller = create_live_tushare_request_controller(clock=Clock())
    state = _ProductionRuntimeState(
        config_path=config,
        database_path=tmp_path / "monitor.sqlite3",
        engine=engine,
        session_factory=create_session_factory(engine),
        clock=Clock(),
        request_controller=controller,
    )
    try:
        actual = state.probe_capabilities()
        if label is SourceTimeLabel.START:
            assert actual == capabilities
        else:
            assert actual.realtime_minutes is ProviderCapabilityStatus.UNVERIFIED
    finally:
        controller.close()
        engine.dispose()


class SDK:
    """Only the remote SDK boundary is replaced; normalization and services are real."""

    def __init__(self, clock, engine):
        self.clock = clock
        self.engine = engine
        self.calls = []

    def __getattr__(self, name):
        def request(**kwargs):
            import pandas as pd

            # No connection can remain checked out while the provider worker runs.
            assert self.engine.pool.checkedout() == 0
            self.calls.append((name, kwargs))
            today = self.clock.now().date()
            base = dict(
                open="64.00", high="64.10", low="63.90", close="64.05", vol="1000", amount="64000"
            )
            if name == "trade_cal":
                start = date.fromisoformat(kwargs["start_date"])
                end = date.fromisoformat(kwargs["end_date"])
                rows = []
                prior = start - timedelta(days=1)
                while prior.weekday() > 4:
                    prior -= timedelta(days=1)
                current = start
                while current <= end:
                    rows.append(
                        dict(
                            exchange=kwargs["exchange"],
                            cal_date=current.strftime("%Y%m%d"),
                            is_open=int(current.weekday() < 5),
                            pretrade_date=prior.strftime("%Y%m%d"),
                        )
                    )
                    if current.weekday() < 5:
                        prior = current
                    current += timedelta(days=1)
                return pd.DataFrame(rows)
            if name == "stk_limit":
                return pd.DataFrame(
                    [
                        dict(
                            ts_code="003043.SZ",
                            trade_date=today.strftime("%Y%m%d"),
                            up_limit="75",
                            down_limit="55",
                        )
                    ]
                    + [
                        dict(
                            ts_code=f"{code:06d}.SZ",
                            trade_date=today.strftime("%Y%m%d"),
                            up_limit="75",
                            down_limit="55",
                        )
                        for code in range(1001)
                    ]
                )
            if name == "daily":
                start = date.fromisoformat(kwargs["start_date"])
                end = date.fromisoformat(kwargs["end_date"])
                return pd.DataFrame(
                    [
                        dict(
                            base,
                            ts_code=kwargs["ts_code"],
                            trade_date=(start + timedelta(days=i)).strftime("%Y%m%d"),
                        )
                        for i in range((end - start).days + 1)
                        if (start + timedelta(days=i)).weekday() < 5
                    ]
                )
            if name in {"rt_min", "rt_min_daily"}:
                start = self.clock.now().replace(hour=9, minute=30, second=0, microsecond=0)
                cutoff = self.clock.now().replace(second=0, microsecond=0)
                minutes = [
                    start + timedelta(minutes=i)
                    for i in range(int((cutoff - start).total_seconds() / 60))
                ]
                if name == "rt_min":
                    minutes = minutes[-1:]
                return pd.DataFrame(
                    [
                        dict(
                            base,
                            ts_code="003043.SZ",
                            freq="1MIN",
                            time=minute.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                        for minute in minutes
                    ]
                )
            raise AssertionError(name)

        return request


def test_certified_pipeline_recovers_evaluates_once_and_restarts(tmp_path, monkeypatch):
    import trade_plan_monitor.runtime.production as production
    from trade_plan_monitor.domain.plan_codec import load_plan_yaml
    from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
    from trade_plan_monitor.state.database import upgrade_database
    from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

    async def scenario():
        clock = Clock()
        clock.current = NOW.replace(hour=9, minute=0)
        engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
        upgrade_database(engine)
        sessions = create_session_factory(engine)

        def work():
            return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

        sample = Path(__file__).parents[2] / "config/plans/003043.SZ.sample.yaml"
        plan = load_plan_yaml(sample.read_text(encoding="utf-8"))
        with work() as transaction:
            transaction.plans.save_draft(plan, source_text="production wiring acceptance")
            transaction.plans.activate(
                plan,
                expected_revision=0,
                validation=validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE),
            )
            transaction.commit()
        clock.current = NOW
        config = tmp_path / "config/app.yaml"
        config.parent.mkdir()
        config.write_text("tushare:\n  api_url: https://example.test\n  token: test-token\n")
        capabilities = ProviderCapabilities(
            **{key: ProviderCapabilityStatus.READY for key in ProviderCapabilities.model_fields}
        )
        write_live_certification(
            tmp_path / "data/live-certification/tushare-stock-live.json",
            create_stock_certification(
                observed_at=NOW,
                endpoint_url="https://example.test",
                capabilities=capabilities,
                source_time_label=SourceTimeLabel.START,
            ),
        )
        sdk = SDK(clock, engine)
        monkeypatch.setattr(production, "create_tushare_client", lambda config: sdk)
        published = []
        controller = create_live_tushare_request_controller(clock=clock)

        def state():
            return _ProductionRuntimeState(
                config_path=config,
                database_path=tmp_path / "monitor.sqlite3",
                engine=engine,
                session_factory=sessions,
                clock=clock,
                request_controller=controller,
                runtime_generation=uuid4,
                publisher=published.append,
            )

        try:
            first = state()
            assert first.probe_capabilities() == capabilities
            await first.refresh_references(NOW.date())
            await first.recover_startup(NOW.date())
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=NOW.date(),
                due_at=NOW,
                bar_end=NOW.replace(second=0),
            )
            result = await first.run_deadline(deadline)
            assert [row.status.value for row in result] == ["COMMITTED"]
            with work() as transaction:
                before = transaction.projections.get_decision_head(plan.symbol)
            assert before is not None
            calls = len(sdk.calls)
            assert await first.run_deadline(deadline) == ()
            assert len(sdk.calls) == calls
            second = state()
            second.probe_capabilities()
            await second.recover_startup(NOW.date())
            with work() as transaction:
                after = transaction.projections.get_decision_head(plan.symbol)
            assert before == after
            assert sum(name == "rt_min" for name, _ in sdk.calls) == 1
            assert published
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("seconds_after_minute", "repair_expected"),
    ((15, True), (59, False)),
)
def test_production_deadline_repairs_only_detected_gaps_with_realtime_budget(
    tmp_path,
    monkeypatch,
    seconds_after_minute,
    repair_expected,
):
    import trade_plan_monitor.runtime.production as production
    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.domain.plan_codec import load_plan_yaml
    from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
    from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
    from trade_plan_monitor.state.database import upgrade_database
    from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

    class GapSDK(SDK):
        def __getattr__(self, name):
            request = super().__getattr__(name)
            if name != "rt_min_daily":
                return request

            def with_first_recovery_gap(**kwargs):
                frame = request(**kwargs)
                if sum(call_name == name for call_name, _ in self.calls) == 1:
                    missing = (
                        self.clock.now()
                        .replace(hour=9, minute=58, second=0, microsecond=0)
                        .strftime("%Y-%m-%d %H:%M:%S")
                    )
                    return frame.loc[frame["time"] != missing]
                return frame

            return with_first_recovery_gap

    async def scenario():
        clock = Clock()
        clock.current = NOW.replace(hour=9, minute=0)
        database = tmp_path / "monitor.sqlite3"
        engine = create_sqlite_engine(database)
        upgrade_database(engine)
        sessions = create_session_factory(engine)

        def work():
            return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

        sample = Path(__file__).parents[2] / "config/plans/003043.SZ.sample.yaml"
        plan = load_plan_yaml(sample.read_text(encoding="utf-8"))
        with work() as transaction:
            transaction.plans.save_draft(plan, source_text="gap repair wiring acceptance")
            transaction.plans.activate(
                plan,
                expected_revision=0,
                validation=validate_trade_plan(
                    plan,
                    available_market_evidence=ALL_MARKET_EVIDENCE,
                ),
            )
            transaction.commit()

        base_minute = NOW.replace(second=0, microsecond=0)
        clock.current = base_minute + timedelta(seconds=seconds_after_minute)
        config = tmp_path / "config/app.yaml"
        config.parent.mkdir()
        config.write_text("tushare:\n  api_url: https://example.test\n  token: test-token\n")
        capabilities = ProviderCapabilities(
            **{key: ProviderCapabilityStatus.READY for key in ProviderCapabilities.model_fields}
        )
        evidence = create_stock_certification(
            observed_at=clock.now(),
            endpoint_url="https://example.test",
            capabilities=capabilities,
            source_time_label=SourceTimeLabel.START,
        )
        write_live_certification(
            tmp_path / "data/live-certification/tushare-stock-live.json",
            evidence,
        )
        sdk = GapSDK(clock, engine)
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        controller = create_live_tushare_request_controller(clock=clock)
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data/live-certification",
            stock_certification=evidence,
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work,
            runtime_generation=uuid4(),
            publisher=lambda _event: None,
        )
        gap = base_minute.replace(hour=9, minute=59)
        try:
            await pipeline.refresh_references(base_minute.date())
            await pipeline.recover_startup(base_minute.date())
            with work() as transaction:
                assert transaction.history.list_minutes(plan.symbol, start=gap, end=gap) == ()

            tasks_before = set(asyncio.all_tasks())
            result = await pipeline.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=base_minute.date(),
                    due_at=base_minute + timedelta(seconds=15),
                    bar_end=base_minute,
                )
            )
            await asyncio.sleep(0)
            assert set(asyncio.all_tasks()) == tasks_before
            assert result == ()
            with work() as transaction:
                repaired = transaction.history.list_minutes(plan.symbol, start=gap, end=gap)
                assert transaction.projections.get_decision_head(plan.symbol) is None
            assert bool(repaired) is repair_expected
            assert sum(name == "rt_min_daily" for name, _ in sdk.calls) == (
                2 if repair_expected else 1
            )
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_production_context_does_not_rebind_risk_from_another_plan_hash():
    from trade_plan_monitor.market_data.models import DailyBar
    from trade_plan_monitor.runtime.production_context import _risk_snapshot_for_plan
    from trade_plan_monitor.state.repositories import RiskStateRecord

    prior = DailyBar(
        symbol="003043.SZ",
        trade_date=NOW.date() - timedelta(days=1),
        open_fen=6300,
        high_fen=6500,
        low_fen=6200,
        close_fen=6405,
        volume_shares=1_000,
        amount_yuan=Decimal("64000"),
        is_official=True,
        received_at=NOW - timedelta(days=1),
    )
    old_risk = RiskStateRecord(
        symbol=prior.symbol,
        plan_hash="a" * 64,
        status="BREACHED_PENDING_CONFIRMATION",
        breach_trade_date=prior.trade_date,
        prior_close_fen=6200,
        revision=7,
        updated_at=NOW - timedelta(days=1),
    )

    snapshot = _risk_snapshot_for_plan(
        risk=old_risk,
        plan_hash="b" * 64,
        history=(prior,),
        symbol=prior.symbol,
        cutoff=NOW,
    )

    assert snapshot.plan_hash == "b" * 64
    assert snapshot.status.value == "CLEAR"
    assert snapshot.breach_trade_date is None
    assert snapshot.prior_close_fen == prior.close_fen
    assert snapshot.revision == old_risk.revision

    restored = _risk_snapshot_for_plan(
        risk=old_risk,
        plan_hash=old_risk.plan_hash,
        history=(prior,),
        symbol=prior.symbol,
        cutoff=NOW,
    )
    assert restored.plan_hash == old_risk.plan_hash
    assert restored.status.value == old_risk.status
    assert restored.breach_trade_date == old_risk.breach_trade_date
    assert restored.revision == old_risk.revision


def test_unresolved_pending_close_makes_startup_recovery_fail_closed():
    from trade_plan_monitor.runtime.production import _ensure_recovery_complete
    from trade_plan_monitor.runtime.recovery import (
        PendingCloseRecoveryResult,
        RecoveryBatchResult,
        RecoveryErrorCode,
        RecoveryMode,
    )

    recovery = RecoveryBatchResult(
        mode=RecoveryMode.STARTUP,
        trade_date=NOW.date(),
        pending_close_results=(
            PendingCloseRecoveryResult(
                symbol="003043.SZ",
                trade_date=NOW.date() - timedelta(days=1),
                resolved=False,
                error_code=RecoveryErrorCode.ERROR,
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="startup recovery failed"):
        _ensure_recovery_complete(recovery)
