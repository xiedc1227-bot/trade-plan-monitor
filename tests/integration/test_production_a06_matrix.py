"""Offline mixed-family dependency isolation through the installed composition."""

import asyncio
from datetime import timedelta

import pytest
import test_explicit_runtime_production as explicit_fixture
from requests import ConnectionError as ProviderConnectionError
from sqlalchemy import func, select
from test_live_pipeline_acceptance import (
    NOW,
    _activate_plans,
    _index_condition_evidence,
)
from test_live_pipeline_acceptance import (
    _plan as legacy_plan,
)
from test_production_certification_gate import _composition

from trade_plan_monitor.decision.models import ConditionOutcome, SignalType
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import MarketIndexHealth, MarketIndexIssueCode
from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeCycleStatus
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    EvaluationResult,
    ExplicitEvaluationLedger,
    MarketIndexSnapshot,
)
from trade_plan_monitor.state.repositories import ManualEventRiskStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


@pytest.mark.parametrize("failed_family", ("legacy", "explicit"))
def test_one_malformed_stock_row_does_not_block_other_plan_family_or_indexes(
    tmp_path, monkeypatch, failed_family,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=True, include_index=True,
            persisted_calendar=True,
        )
        legacy_symbol = "003043.SZ"
        payload = explicit_fixture._plan(active_date=NOW.date()).model_dump(
            mode="python", round_trip=True,
        )
        payload.update(
            plan_id="offline-a06-explicit", symbol="300001.SZ",
            name="OFFLINE A06 EXPLICIT",
        )
        explicit_plan = ExplicitTradePlan.model_validate(payload)
        monkeypatch.setattr(explicit_fixture, "PREPARED_AT", NOW - timedelta(minutes=30))
        engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
        try:
            explicit_fixture._seed_active(engine, explicit_plan)
        finally:
            engine.dispose()
        failed_symbol = (
            legacy_symbol if failed_family == "legacy" else explicit_plan.symbol
        )
        original_minutes = sdk._stock_minutes

        def one_bad_row(name, kwargs):
            frame = original_minutes(name, kwargs)
            if name == "rt_min":
                frame.loc[frame["ts_code"] == failed_symbol, "close"] = "malformed"
            return frame

        sdk._stock_minutes = one_bad_row
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=NOW.date(),
                due_at=NOW, bar_end=NOW.replace(second=0),
            ))
            with state._session_factory() as session:
                legacy_results = session.scalar(
                    select(func.count()).select_from(EvaluationResult)
                    .where(EvaluationResult.symbol == legacy_symbol)
                )
                explicit_results = session.scalar(
                    select(func.count()).select_from(ExplicitEvaluationLedger)
                    .where(ExplicitEvaluationLedger.symbol == explicit_plan.symbol)
                )
                index_rows = session.scalar(
                    select(func.count()).select_from(MarketIndexSnapshot)
                )
            assert (legacy_results, explicit_results) == (
                (0, 1) if failed_family == "legacy" else (1, 0)
            )
            assert index_rows >= 5
            assert sum(name == "rt_min" for name, _ in sdk.calls) == 1
        finally:
            await composition.stop()

        sdk._stock_minutes = original_minutes
        sdk.clock.current = NOW + timedelta(minutes=5)
        replacement = create_monitor_composition(
            config_path=tmp_path / "config/app.yaml",
            database_path=tmp_path / "monitor.sqlite3",
        )
        try:
            assert (await replacement.start()).status is RuntimeServiceStatus.RUNNING
            state = replacement._runtime._probe_capabilities.__self__
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=NOW.date(),
                due_at=sdk.clock.now(),
                bar_end=NOW.replace(second=0) + timedelta(minutes=5),
            ))
            with state._session_factory() as session:
                assert session.scalar(
                    select(func.count()).select_from(EvaluationResult)
                    .where(EvaluationResult.symbol == legacy_symbol)
                ) >= 1
                assert session.scalar(
                    select(func.count()).select_from(ExplicitEvaluationLedger)
                    .where(ExplicitEvaluationLedger.symbol == explicit_plan.symbol)
                ) >= 1
            assert sum(name == "rt_min" for name, _ in sdk.calls) == 2
        finally:
            await replacement.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("requires_index", (False, True))
def test_required_index_failure_isolates_mixed_family_deadline(
    tmp_path, monkeypatch, requires_index,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            persisted_calendar=True,
        )
        condition = (
            {"type": "INDEX_CLOSE_GTE_MA", "index_role": "BOARD_REFERENCE", "period": 2}
            if requires_index else {"type": "NON_DECREASING_CLOSE"}
        )
        dependent = legacy_plan(
            plan_id="offline-a06-index-dependency", symbol="003043.SZ",
            market="SZSE", condition=condition,
        )
        sdk.clock.current = NOW.replace(hour=9, minute=0)
        _activate_plans(tmp_path / "monitor.sqlite3", sdk.clock, (dependent,))
        sdk.clock.current = NOW
        payload = explicit_fixture._plan(active_date=NOW.date()).model_dump(
            mode="python", round_trip=True,
        )
        payload.update(
            plan_id="offline-a06-independent", symbol="300001.SZ",
            name="OFFLINE A06 INDEPENDENT",
        )
        payload["rules"][0]["condition"] = {
            "type": "COMPLETED_CLOSE_IN_RANGE", "low_fen": 6000,
            "high_fen": 6500, "include_low": True, "include_high": True,
        }
        independent = ExplicitTradePlan.model_validate(payload)
        monkeypatch.setattr(explicit_fixture, "PREPARED_AT", NOW - timedelta(minutes=30))
        engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
        try:
            explicit_fixture._seed_active(engine, independent)
            with SqlAlchemyUnitOfWork(
                create_session_factory(engine),
                clock=lambda: NOW - timedelta(minutes=30),
            ) as work:
                work.references.upsert_trading_days((TradingDay(
                    exchange=independent.market, cal_date=NOW.date(), is_open=True,
                    previous_trade_date=NOW.date() - timedelta(days=1),
                ),))
                work.manual_event_risk.upsert(
                    symbol=dependent.symbol, plan_hash=plan_sha256(dependent),
                    status=ManualEventRiskStatus.CLEAR, expires_on=NOW.date(),
                    expected_revision=0,
                )
                work.positions.confirm_inventory(
                    symbol=independent.symbol, as_of_trade_date=NOW.date(),
                    total_quantity=100, sellable_quantity=100,
                    included_lot_ids=(), complete_registration=True,
                    expected_revision=0,
                )
                work.commit()
        finally:
            engine.dispose()

        required_code = dependent.reference_market.index_code.value
        original_index_minutes = sdk._index_minutes

        def fail_one_index(kwargs):
            if kwargs["ts_code"] == required_code:
                raise ProviderConnectionError("offline required-index interruption")
            return original_index_minutes(kwargs)

        sdk._index_minutes = fail_one_index
        delivered = []

        class Channel:
            channel = DeliveryChannel.IN_APP
            enabled = True

            async def deliver(self, event):
                delivered.append(event.symbol)
                return ChannelDeliveryResult(
                    channel=self.channel, delivered=True, retryable=False,
                )

        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            state._dispatcher._channels = (Channel(),)
            results = await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=NOW.date(),
                due_at=NOW, bar_end=NOW.replace(second=0),
            ))
            assert len(results) == 2
            explicit_result = next(
                item for item in results
                if hasattr(item, "committed_events")
            )
            assert explicit_result.status is ExplicitRuntimeCycleStatus.COMMITTED
            assert len(explicit_result.committed_events) == 1
            assert independent.symbol in delivered
            if requires_index:
                assert dependent.symbol not in delivered
            legacy = next(
                item.evaluation_result for item in results
                if getattr(item, "evaluation_result", None) is not None
                and item.evaluation_result.snapshot.symbol == dependent.symbol
            )
            if requires_index:
                assert legacy.snapshot.reference_market is not None
                assert legacy.snapshot.reference_market.health is MarketIndexHealth.BLOCKED
                failed_snapshot = state._pipeline.index_service.latest_snapshots()[
                    MarketIndexCode(required_code)
                ]
                assert MarketIndexIssueCode.PROVIDER_UNAVAILABLE in failed_snapshot.issues
                evidence = tuple(
                    item for root in legacy.snapshot.condition_evidence
                    for item in _index_condition_evidence(root)
                )
                assert len(evidence) == 1
                assert evidence[0].outcome is ConditionOutcome.MISSING_INPUT
                assert legacy.signal_intent is None
                assert legacy.snapshot.signal_type is SignalType.BLOCKED_DATA
                retry_at = state.next_index_recovery_at()
                assert retry_at is not None
            else:
                assert legacy.snapshot.reference_market is None
                assert legacy.snapshot.signal_type is not SignalType.BLOCKED_DATA
            snapshots = state._pipeline.index_service.latest_snapshots()
            assert len(snapshots) == 5
            assert all(
                snapshot.health is MarketIndexHealth.LIVE
                for code, snapshot in snapshots.items()
                if code.value != required_code
            )
            with state._session_factory() as session:
                assert session.scalar(
                    select(func.count()).select_from(ExplicitEvaluationLedger)
                    .where(ExplicitEvaluationLedger.symbol == independent.symbol)
                ) == 1
                assert session.scalar(select(func.count()).select_from(MarketIndexSnapshot)) >= 5
        finally:
            await composition.stop()

        if requires_index:
            sdk._index_minutes = original_index_minutes
            sdk.clock.current = NOW + timedelta(minutes=4)
            replacement = create_monitor_composition(
                config_path=tmp_path / "config/app.yaml",
                database_path=tmp_path / "monitor.sqlite3",
            )
            try:
                assert (await replacement.start()).status is RuntimeServiceStatus.RUNNING
                state = replacement._runtime._probe_capabilities.__self__
                state._dispatcher._channels = (Channel(),)
                assert state.next_index_recovery_at() == retry_at
                before = len(sdk.calls)
                await state.run_deadline(MarketDeadline(
                    kind=DeadlineKind.INDEX_RECOVERY,
                    trade_date=NOW.date(), due_at=retry_at,
                ))
                assert all(
                    name in {"idx_mins", "rt_idx_min_daily", "index_daily"}
                    for name, _ in sdk.calls[before:]
                )
                assert state.next_index_recovery_at() is None
                sdk.clock.current = NOW + timedelta(minutes=5)
                results = await state.run_deadline(MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE, trade_date=NOW.date(),
                    due_at=sdk.clock.now(),
                    bar_end=NOW.replace(second=0) + timedelta(minutes=5),
                ))
                legacy = next(
                    item.evaluation_result for item in results
                    if getattr(item, "evaluation_result", None) is not None
                    and item.evaluation_result.snapshot.symbol == dependent.symbol
                )
                assert legacy.snapshot.reference_market is not None
                assert legacy.snapshot.reference_market.health is MarketIndexHealth.LIVE
                assert delivered.count(independent.symbol) == 1
            finally:
                await replacement.stop()

    asyncio.run(scenario())
