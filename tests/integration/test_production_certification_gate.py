"""Production evidence is revalidated at each physical request boundary."""

import asyncio
from datetime import timedelta
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
import yaml
from requests import ConnectionError as ProviderConnectionError
from sqlalchemy import func, select, text
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _write_configuration_and_evidence,
)
from test_live_pipeline_acceptance import (
    _sample_plan as _historical_sample_plan,
)
from test_notification_delivery import _payload
from tests.integration.current_activation_fixture import current_sample_plan, seed_current

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.market_data.models import ProviderCapabilityStatus
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.production import (
    PermissionMaintenanceResult,
    ReferenceDependenciesChangedError,
)
from trade_plan_monitor.runtime.provider_contract import (
    import_index_semantic_contract,
    import_stock_semantic_contract,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
    create_live_tushare_request_controller,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    AlertEvent,
    MarketIndexSnapshot,
    RuntimeLiveness,
    TradingCalendar,
)
from trade_plan_monitor.state.runtime_recovery import (
    ProviderRecoveryRepository,
    RecoveryCheckpoint,
    RecoveryCheckpointError,
)
from trade_plan_monitor.web.monitor_composition import (
    _provider_recovery_identity,
    create_monitor_composition,
)


def _minute_count(session):
    # The startup recovery may persist a daily snapshot. Count the immutable
    # minute decisions, excluding their mutable symbol head.
    return session.scalar(
        select(func.count())
        .select_from(DailyRecord)
        .where(
            DailyRecord.kind == "EVALUATION",
            ~DailyRecord.id.like("evaluation-head-%"),
            func.json_extract(DailyRecord.payload_json, "$.minute_target").is_not(None),
        )
    )


def _current_ledger(session):
    return tuple(
        (row.id, row.revision, row.payload_json)
        for row in session.scalars(select(DailyRecord).order_by(DailyRecord.id))
    )


def _composition(
    tmp_path,
    monkeypatch,
    *,
    invalidate_during_request=None,
    fail_realtime_once=False,
    rate_limit_realtime_once=False,
    active_plan=True,
    include_index=False,
    stock_certification=True,
    persisted_calendar=False,
    plan=None,
):
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as monitor_composition

    database = tmp_path / "monitor.sqlite3"
    clock = ControlledClock(NOW.replace(hour=9, minute=0))
    plan = plan or current_sample_plan()
    _activate_plans(database, clock, ())
    if active_plan:
        seed_current(tmp_path, plan=plan, clock=clock)
    seeded_engine = create_sqlite_engine(database)
    try:
        with create_session_factory(seeded_engine).begin() as session:
            session.add(
                RuntimeLiveness(
                    id=1,
                    schema_version=1,
                    revision=0,
                    last_alive_at=clock.now().isoformat(),
                )
            )
            if persisted_calendar:
                session.add(
                    TradingCalendar(
                        exchange="SSE",
                        cal_date=NOW.date(),
                        is_open=True,
                        previous_trade_date=NOW.date() - timedelta(days=1),
                    )
                )
    finally:
        seeded_engine.dispose()
    clock.current = NOW
    config = _write_configuration_and_evidence(
        tmp_path, observed_at=NOW, include_index=include_index
    )
    certification = tmp_path / "data/live-certification/tushare-stock-live.json"
    if not stock_certification:
        certification.unlink()
    semantic_contract = certification.parent / "stock-semantic.json"

    class InvalidatingSDK(OfflineSDK):
        def __getattr__(self, name):
            request = super().__getattr__(name)

            def call(**kwargs):
                result = request(**kwargs)
                if (
                    fail_realtime_once
                    and name == "rt_min"
                    and sum(item == "rt_min" for item, _ in self.calls) == 1
                ):
                    raise ProviderConnectionError("offline transport interruption")
                if (
                    rate_limit_realtime_once
                    and name == "rt_min"
                    and sum(item == "rt_min" for item, _ in self.calls) == 1
                ):
                    raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "rt_min")
                if len(self.calls) == 1:
                    if invalidate_during_request == "remove_semantic":
                        semantic_contract.unlink()
                    elif invalidate_during_request == "corrupt_semantic":
                        semantic_contract.write_text("{}", encoding="utf-8")
                    elif invalidate_during_request == "change_config":
                        config.write_text(
                            config.read_text(encoding="utf-8").replace(
                                "offline-test-token", "offline-new-token"
                            ),
                            encoding="utf-8",
                        )
                return result

            return call

    sdk = InvalidatingSDK(clock, (plan.symbol,))

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return create_live_tushare_request_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
            require_repository_binding=require_repository_binding,
        )

    monkeypatch.setattr(monitor_composition, "SystemClock", lambda: clock)
    monkeypatch.setattr(
        monitor_composition, "create_live_tushare_request_controller", controller_factory
    )
    monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
    return (
        create_monitor_composition(config_path=config, database_path=database),
        sdk,
        certification,
    )


@pytest.mark.parametrize("active_plan", (False, True))
def test_production_index_runs_without_stock_semantics_or_certification(
    tmp_path,
    monkeypatch,
    active_plan,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=active_plan,
            include_index=True,
            stock_certification=False,
            persisted_calendar=True,
        )
        try:
            startup = await composition.start()
            state = composition._runtime._probe_capabilities.__self__
            assert state._pipeline is not None
            assert startup.status is RuntimeServiceStatus.RUNNING
            assert state._liveness_revision is not None
            owner_revision = state._liveness_revision
            await state.heartbeat()
            assert state._liveness_revision == owner_revision + 1
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=NOW.date(),
                due_at=NOW,
                bar_end=NOW.replace(second=0),
            )
            await state.run_deadline(deadline)
            assert any(name in {"idx_mins", "rt_idx_min_daily"} for name, _ in sdk.calls)
            assert not any(
                name in {"trade_cal", "stk_limit", "daily", "rt_min", "stk_mins"}
                for name, _ in sdk.calls
            )
            with state._session_factory() as session:
                assert session.scalar(select(func.count()).select_from(MarketIndexSnapshot)) > 0
                assert _minute_count(session) == 0
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
            stock = next(
                item
                for item in state.health_details().providers
                if item.capability == "realtime_minutes"
            )
            assert stock.status is ProviderCapabilityStatus.ERROR
            assert stock.error_code == "STOCK_SEMANTICS_UNAVAILABLE"
        finally:
            await composition.stop()
        assert composition.health().status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_production_index_only_cold_start_waits_for_trusted_calendar(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            include_index=True,
            stock_certification=False,
            persisted_calendar=False,
        )
        try:
            startup = await composition.start()
            state = composition._runtime._probe_capabilities.__self__
            assert startup.status is RuntimeServiceStatus.DEGRADED
            assert state._pipeline is not None
            assert state._liveness_revision is not None
            owner_revision = state._liveness_revision
            await state.heartbeat()
            assert state._liveness_revision == owner_revision + 1
            assert sdk.calls == []
            with state._session_factory() as session:
                assert session.scalar(select(func.count()).select_from(MarketIndexSnapshot)) == 0
        finally:
            await composition.stop()
        assert composition.health().status is RuntimeServiceStatus.STOPPED

    asyncio.run(scenario())


def test_index_only_deadline_never_delivers_old_stock_alert(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=True,
            include_index=True,
            stock_certification=False,
            persisted_calendar=True,
        )
        delivered = []

        class Channel:
            channel = DeliveryChannel.IN_APP
            enabled = True

            async def deliver(self, event):
                delivered.append(event.event_id)
                return ChannelDeliveryResult(
                    channel=self.channel,
                    delivered=True,
                    retryable=False,
                )

        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            with state.unit_of_work_factory() as work:
                work.alerts.enqueue_recoverable(_payload(992))
                work.commit()
            state._dispatcher._channels = (Channel(),)
            monkeypatch.setattr(CurrentDeliveryAdmission, "__call__", lambda *_: True)
            await state.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=NOW.date(),
                    due_at=NOW,
                    bar_end=NOW.replace(second=0),
                )
            )
            assert any(name in {"idx_mins", "rt_idx_min_daily"} for name, _ in sdk.calls)
            assert delivered == []
            await state._dispatcher.dispatch_pending()
            assert delivered == []
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_late_stock_semantic_latches_index_only_process(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, certification = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            include_index=True,
            stock_certification=False,
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            _write_configuration_and_evidence(
                tmp_path,
                observed_at=NOW,
                include_index=True,
            )
            endpoint = str(load_application_config(tmp_path / "config/app.yaml").tushare.api_url)
            assert (
                import_stock_semantic_contract(
                    certification,
                    certification.parent / "stock-semantic.json",
                    now=NOW,
                    endpoint_url=endpoint,
                    installed_sdk_version=lambda: "1.4.29",
                )
                is not None
            )
            before = tuple(sdk.calls)
            assert state.configuration_restart_required()
            assert state._process_baseline.revoked.is_set()
            with pytest.raises(RuntimeError, match="safe restart required"):
                await state.run_deadline(
                    MarketDeadline(
                        kind=DeadlineKind.REALTIME_MINUTE,
                        trade_date=NOW.date(),
                        due_at=NOW,
                        bar_end=NOW.replace(second=0),
                    )
                )
            (certification.parent / "stock-semantic.json").unlink()
            assert state.configuration_restart_required()
            assert tuple(sdk.calls) == before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_index_only_restart_restores_pending_index_retries(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=True,
            include_index=True,
            stock_certification=False,
            persisted_calendar=True,
        )
        failed_calls = []

        def fail_index(**kwargs):
            failed_calls.append(kwargs)
            raise ProviderConnectionError("offline index interruption")

        sdk.idx_mins = fail_index
        sdk.rt_idx_min_daily = fail_index
        sdk.index_daily = fail_index
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            await state.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=NOW.date(),
                    due_at=NOW,
                    bar_end=NOW.replace(second=0),
                )
            )
            with state.unit_of_work_factory() as work:
                records = work.projections.list_market_index_recoveries()
            assert len(records) == 5
            expected_due = min(record[4] for record in records)
            assert state.next_index_recovery_at() == expected_due
            assert failed_calls
        finally:
            await composition.stop()

        del sdk.idx_mins
        del sdk.rt_idx_min_daily
        del sdk.index_daily
        replacement = create_monitor_composition(
            config_path=tmp_path / "config/app.yaml",
            database_path=tmp_path / "monitor.sqlite3",
        )
        try:
            assert (await replacement.start()).status is RuntimeServiceStatus.RUNNING
            state = replacement._runtime._probe_capabilities.__self__
            assert state.next_index_recovery_at() == expected_due
            sdk.clock.current = expected_due
            before = len(sdk.calls)
            await state.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.INDEX_RECOVERY,
                    trade_date=NOW.date(),
                    due_at=expected_due,
                )
            )
            assert state.next_index_recovery_at() != expected_due
            assert len(sdk.calls) > before
            assert all(
                name in {"idx_mins", "rt_idx_min_daily", "index_daily"}
                for name, _ in sdk.calls[before:]
            )
            with state._session_factory() as session:
                assert _minute_count(session) == 0
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
        finally:
            await replacement.stop()

    asyncio.run(scenario())


def test_index_only_health_keeps_semantic_reason_with_old_permission_blocks(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=False,
            include_index=True,
            stock_certification=False,
            persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            control = composition._runtime._request_controller
            for operation in (
                TushareOperation.CURRENT_DAY_MINUTES,
                TushareOperation.DAILY_BARS,
                TushareOperation.DAILY_LIMITS,
                TushareOperation.REALTIME_MINUTES,
                TushareOperation.TRADING_CALENDAR,
            ):

                def denied(operation=operation):
                    raise TushareProviderError(
                        TushareErrorCode.BLOCKED_PERMISSION,
                        operation.value,
                    )

                with pytest.raises(RequestControlError):
                    await control.execute(operation, denied, work_key=f"blocked:{operation.value}")
            state = composition._runtime._probe_capabilities.__self__
            providers = state.health_details().providers
            assert len(providers) == 5
            assert all(
                item.status is ProviderCapabilityStatus.BLOCKED_PERMISSION for item in providers
            )
            assert all(item.next_retry_at is not None for item in providers)
            assert all(item.error_code == "STOCK_SEMANTICS_UNAVAILABLE" for item in providers)
            assert not any(
                name in {"trade_cal", "stk_limit", "daily", "rt_min", "stk_mins"}
                for name, _ in sdk.calls
            )
        finally:
            await composition.stop()

        replacement = create_monitor_composition(
            config_path=tmp_path / "config/app.yaml",
            database_path=tmp_path / "monitor.sqlite3",
        )
        delivered = []

        class Channel:
            channel = DeliveryChannel.IN_APP
            enabled = True

            async def deliver(self, event):
                delivered.append(event.event_id)
                return ChannelDeliveryResult(
                    channel=self.channel,
                    delivered=True,
                    retryable=False,
                )

        try:
            assert (await replacement.start()).status is RuntimeServiceStatus.RUNNING
            state = replacement._runtime._probe_capabilities.__self__
            providers = state.health_details().providers
            assert all(
                item.status is ProviderCapabilityStatus.BLOCKED_PERMISSION for item in providers
            )
            assert all(item.next_retry_at is not None for item in providers)
            assert all(item.error_code == "STOCK_SEMANTICS_UNAVAILABLE" for item in providers)
            with state.unit_of_work_factory() as work:
                work.alerts.enqueue_recoverable(_payload(993))
                work.commit()
            state._dispatcher._channels = (Channel(),)
            monkeypatch.setattr(CurrentDeliveryAdmission, "__call__", lambda *_: True)
            await state.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=NOW.date(),
                    due_at=NOW,
                    bar_end=NOW.replace(second=0),
                )
            )
            await state._dispatcher.dispatch_pending()
            assert delivered == []
            assert not any(
                name in {"trade_cal", "stk_limit", "daily", "rt_min", "stk_mins"}
                for name, _ in sdk.calls
            )
        finally:
            await replacement.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("invalidated_by", ("remove_semantic", "corrupt_semantic", "change_config"))
def test_startup_stops_physical_stock_calls_when_semantics_become_invalid(
    tmp_path, monkeypatch, invalidated_by
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, invalidate_during_request=invalidated_by
        )
        try:
            with pytest.raises(ReferenceDependenciesChangedError):
                await composition.start()
            assert [name for name, _ in sdk.calls] == ["trade_cal"]
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_repeated_capability_probe_discards_the_previous_ready_pipeline(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, certification = _composition(tmp_path, monkeypatch)
        state = composition._runtime._probe_capabilities.__self__
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            assert state.probe_capabilities().realtime_minutes is ProviderCapabilityStatus.READY
            assert state._pipeline is not None
            original_pipeline = state._pipeline
            state.probe_capabilities()
            assert state._pipeline is original_pipeline
            calls = tuple(sdk.calls)
            (certification.parent / "stock-semantic.json").write_text("{}", encoding="utf-8")
            assert (
                state.probe_capabilities().realtime_minutes is ProviderCapabilityStatus.UNVERIFIED
            )
            assert state._pipeline is None
            assert (
                state.probe_capabilities().realtime_minutes is ProviderCapabilityStatus.UNVERIFIED
            )
            assert state._pipeline is None
            assert tuple(sdk.calls) == calls
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_cold_reference_cache_does_not_repeat_a_committed_deadline(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._run_deadline.__self__
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=NOW.date(),
                due_at=NOW,
                bar_end=NOW.replace(second=0),
            )
            results = await state.run_deadline(deadline)
            assert len(results) == 1 and not results[0].duplicate
            assert results[0].snapshot["minute_target"] == deadline.bar_end.isoformat()
            assert results[0].snapshot["activation_revision"] == 1
            calls = tuple(sdk.calls)
            with state._session_factory() as session:
                before = (
                    _minute_count(session),
                    session.scalar(select(func.count()).select_from(AlertEvent)),
                )
            state._pipeline._reference_key = None
            duplicate = await state.run_deadline(deadline)
            assert len(duplicate) == 1 and duplicate[0].duplicate
            assert duplicate[0].snapshot == results[0].snapshot
            assert sum(name == "rt_min" for name, _ in sdk.calls) == sum(
                name == "rt_min" for name, _ in calls
            )
            with state._session_factory() as session:
                assert before == (
                    _minute_count(session),
                    session.scalar(select(func.count()).select_from(AlertEvent)),
                )
        finally:
            await composition.stop()

    asyncio.run(scenario())


def _release_actual_scheduler_until(monkeypatch, clock, through):
    """Release bounded real duties through a target, not a fixed sleep ordinal."""
    released = []

    async def sleep_until(deadline):
        clock.sleep_calls.append(deadline)
        if deadline <= through:
            assert len(released) < 8, "too many scheduler wakes before the market target"
            released.append(deadline)
            clock.current = max(clock.current, deadline)
            await asyncio.sleep(0)
            return
        await asyncio.Event().wait()

    monkeypatch.setattr(clock, "sleep_until", sleep_until)
    return released


def test_production_composition_resumes_after_one_runtime_transport_failure(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            fail_realtime_once=True,
        )
        runtime = composition._runtime
        controller = runtime._request_controller
        state = runtime._run_deadline.__self__
        through = NOW.replace(minute=2, second=12, microsecond=0)
        released = _release_actual_scheduler_until(monkeypatch, state._clock, through)
        controller._backoff = (timedelta(milliseconds=10),)
        runtime._retry_interval_seconds = 0.01
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            for _ in range(200):
                if state._clock.sleep_calls and state._clock.sleep_calls[-1] > through:
                    break
                await asyncio.sleep(0.01)
            assert state._clock.sleep_calls[-1] > through
            assert through in released and state._clock.now() == through
            assert sum(name == "rt_min" for name, _ in sdk.calls) >= 2
            assert composition._runtime is runtime
            assert runtime._request_controller is controller
            assert runtime.status is RuntimeServiceStatus.RUNNING
            assert not controller._closed
        finally:
            await composition.stop()
        assert controller._closed

    asyncio.run(scenario())


def test_next_minute_cannot_bypass_realtime_transport_backoff(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            fail_realtime_once=True,
        )
        runtime = composition._runtime
        controller = runtime._request_controller
        state = runtime._run_deadline.__self__
        through = NOW.replace(minute=2, second=12, microsecond=0)
        released = _release_actual_scheduler_until(monkeypatch, state._clock, through)
        controller._backoff = (timedelta(minutes=5),)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            for _ in range(200):
                if state._clock.sleep_calls and state._clock.sleep_calls[-1] > through:
                    break
                await asyncio.sleep(0.01)
            # The next wait proves the second market duty has returned; observing
            # its sleep entry alone would not prove the backoff was enforced.
            assert state._clock.sleep_calls[-1] > through
            assert through in released and state._clock.now() == through
            assert sum(name == "rt_min" for name, _ in sdk.calls) == 1
            assert runtime.status is RuntimeServiceStatus.RUNNING
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_production_429_cooldown_restores_before_provider_work_after_restart(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            rate_limit_realtime_once=True,
        )
        first = composition._runtime
        clock = first._run_deadline.__self__._clock
        through = NOW.replace(minute=1, second=12, microsecond=0)
        released = _release_actual_scheduler_until(monkeypatch, clock, through)
        assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
        try:
            for _ in range(200):
                if first._request_controller.cooldown_until is not None:
                    break
                await asyncio.sleep(0.01)
            cooldown = first._request_controller.cooldown_until
            assert through in released and clock.now() == through
            assert cooldown == clock.now() + timedelta(seconds=300)
            assert first._request_controller.repository_bound
        finally:
            await composition.stop()

        calls = tuple(sdk.calls)
        config_path = tmp_path / "config/app.yaml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                "offline-test-token", "offline-new-token"
            ),
            encoding="utf-8",
        )
        replacement = create_monitor_composition(
            config_path=config_path,
            database_path=tmp_path / "monitor.sqlite3",
        )
        try:
            health = await replacement.start()
            assert health.status is RuntimeServiceStatus.DEGRADED
            assert replacement._runtime._request_controller.cooldown_until == cooldown
            assert tuple(sdk.calls) == calls
        finally:
            await replacement.stop()

    asyncio.run(scenario())


def test_configuration_edit_between_validation_and_binding_blocks_provider_work(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        runtime = composition._runtime
        state = runtime._liveness_owner
        original_admit = state.admit

        async def edit_after_admission():
            await original_admit()
            config_path = tmp_path / "config/app.yaml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    "offline-test-token", "offline-new-token"
                ),
                encoding="utf-8",
            )

        state.admit = edit_after_admission
        with pytest.raises(RuntimeError, match="configuration changed"):
            await composition.start()
        assert not sdk.calls
        assert not runtime._request_controller.repository_bound
        await composition.stop()

    asyncio.run(scenario())


def test_corrupt_production_checkpoint_blocks_start_and_releases_owner(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        database = tmp_path / "monitor.sqlite3"
        engine = create_sqlite_engine(database)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity=_provider_recovery_identity("https://example.test"),
        )
        repository.save((RecoveryCheckpoint("cooldown", "shared", NOW + timedelta(minutes=5), 0),))
        with engine.begin() as connection:
            connection.execute(text("UPDATE provider_recovery_checkpoint SET retry_at = 'corrupt'"))
        engine.dispose()

        with pytest.raises(RecoveryCheckpointError):
            await composition.start()
        assert not sdk.calls
        assert not composition._runtime._request_controller.repository_bound

        repair_engine = create_sqlite_engine(database)
        ProviderRecoveryRepository(
            create_session_factory(repair_engine),
            provider_identity=_provider_recovery_identity("https://example.test"),
        ).save(())
        repair_engine.dispose()
        replacement = create_monitor_composition(
            config_path=tmp_path / "config/app.yaml",
            database_path=database,
        )
        try:
            assert (await replacement.start()).status is RuntimeServiceStatus.RUNNING
            assert replacement._runtime._request_controller.repository_bound
        finally:
            await replacement.stop()

    asyncio.run(scenario())


def test_calendar_permission_probe_uses_persisted_anchor_without_business_writes(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        runtime = composition._runtime
        assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
        control = runtime._request_controller
        state = runtime._probe_capabilities.__self__
        pipeline = state._pipeline
        assert pipeline is not None
        try:

            def denied():
                raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "trade_cal")

            with pytest.raises(RequestControlError):
                await control.execute(
                    TushareOperation.TRADING_CALENDAR,
                    denied,
                    work_key="calendar:fault",
                )
            state._clock.current += timedelta(seconds=300)
            with create_session_factory(state._engine)() as session:
                before = session.scalar(select(func.count()).select_from(TradingCalendar))
            calls = len(sdk.calls)
            await pipeline._maybe_recheck_calendar_permission()
            assert not control.is_permission_blocked(TushareOperation.TRADING_CALENDAR)
            assert len(sdk.calls) == calls + 1
            name, kwargs = sdk.calls[-1]
            assert name == "trade_cal"
            assert kwargs["exchange"] == "SSE"
            assert kwargs["start_date"] == kwargs["end_date"]
            with create_session_factory(state._engine)() as session:
                after = session.scalar(select(func.count()).select_from(TradingCalendar))
            assert after == before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_calendar_permission_without_anchor_never_probes_and_remains_blocked(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        runtime = composition._runtime
        assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
        control = runtime._request_controller
        state = runtime._probe_capabilities.__self__
        pipeline = state._pipeline
        assert pipeline is not None
        try:

            def denied():
                raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "trade_cal")

            with pytest.raises(RequestControlError):
                await control.execute(
                    TushareOperation.TRADING_CALENDAR,
                    denied,
                    work_key="calendar:fault",
                )
            state._clock.current += timedelta(seconds=300)
            with state._engine.begin() as connection:
                connection.execute(text("DELETE FROM trading_calendar"))
            calls = len(sdk.calls)
            await pipeline._maybe_recheck_calendar_permission()
            assert len(sdk.calls) == calls
            assert control.is_permission_blocked(TushareOperation.TRADING_CALENDAR)
            with pytest.raises(RequestControlError) as caught:
                await pipeline._request(
                    TushareOperation.TRADING_CALENDAR,
                    lambda: None,
                    "calendar:retry",
                )
            assert caught.value.code is RequestControlErrorCode.BLOCKED_PERMISSION
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ("empty", "rate_limit", "config_change", "generation_change"))
def test_calendar_permission_probe_failure_preserves_latch_and_reservation(
    tmp_path,
    monkeypatch,
    outcome,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        runtime = composition._runtime
        assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
        control = runtime._request_controller
        state = runtime._probe_capabilities.__self__
        pipeline = state._pipeline
        assert pipeline is not None
        try:

            def denied():
                raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "trade_cal")

            with pytest.raises(RequestControlError):
                await control.execute(
                    TushareOperation.TRADING_CALENDAR,
                    denied,
                    work_key="calendar:fault",
                )
            state._clock.current += timedelta(seconds=300)
            original_calendar = sdk._calendar

            def probe_response(kwargs):
                if outcome == "empty":
                    return pd.DataFrame(
                        columns=(
                            "exchange",
                            "cal_date",
                            "is_open",
                            "pretrade_date",
                        )
                    )
                if outcome == "rate_limit":
                    raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "trade_cal")
                result = original_calendar(kwargs)
                if outcome == "config_change":
                    config = tmp_path / "config/app.yaml"
                    config.write_text(
                        config.read_text(encoding="utf-8").replace(
                            "offline-test-token", "offline-new-token"
                        ),
                        encoding="utf-8",
                    )
                else:
                    state._runtime_generation = uuid4
                return result

            sdk._calendar = probe_response
            calls = len(sdk.calls)
            original_recheck = control.recheck_permission
            failures = []

            async def capture_failure(*args, **kwargs):
                try:
                    return await original_recheck(*args, **kwargs)
                except RequestControlError as error:
                    failures.append(error)
                    raise

            monkeypatch.setattr(
                type(control),
                "recheck_permission",
                lambda _self, *args, **kwargs: capture_failure(*args, **kwargs),
            )
            tables = (
                "trading_calendar",
                "minute_bar",
                "latest_quote",
                "market_index_snapshot",
                "evaluation_ledger",
                "alert_event",
                "delivery_attempt",
            )

            def business_rows():
                with state._session_factory() as session:
                    return tuple(
                        tuple(session.execute(text(f"SELECT * FROM {table}"))) for table in tables
                    )

            before = business_rows()
            assert await pipeline._maybe_recheck_calendar_permission() is (
                PermissionMaintenanceResult.FAILED
            )
            assert len(failures) == 1
            assert failures[0].code is (
                RequestControlErrorCode.RATE_LIMITED
                if outcome == "rate_limit"
                else RequestControlErrorCode.INVALID_RESPONSE
            )
            assert len(sdk.calls) == calls + 1
            assert control.is_permission_blocked(TushareOperation.TRADING_CALENDAR)
            assert control.permission_retry_at(
                TushareOperation.TRADING_CALENDAR
            ) == state._clock.now() + timedelta(seconds=300)
            await pipeline._maybe_recheck_calendar_permission()
            assert len(sdk.calls) == calls + 1
            assert business_rows() == before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_calendar_permission_without_anchor_stays_visible_during_runtime_retry(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        runtime = composition._runtime

        def denied(_kwargs):
            raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "trade_cal")

        sdk._calendar = denied
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.DEGRADED
            state = runtime._probe_capabilities.__self__
            calendar = next(
                item
                for item in state.health_details().providers
                if item.capability == "trading_calendar"
            )
            assert calendar.status is ProviderCapabilityStatus.BLOCKED_PERMISSION
            assert calendar.error_code == "BLOCKED_PERMISSION"
            physical_calls = len(sdk.calls)
            state._clock.current += timedelta(seconds=301)
            await runtime._recheck_degraded_startup()
            assert len(sdk.calls) == physical_calls
            assert runtime.health().status is RuntimeServiceStatus.DEGRADED
            refreshed = next(
                item
                for item in state.health_details().providers
                if item.capability == "trading_calendar"
            )
            assert refreshed.next_retry_at == state._clock.now()
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_reference_result_cannot_commit_after_configuration_changes_mid_request(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            invalidate_during_request="change_config",
        )
        with pytest.raises(RuntimeError):
            await composition.start()
        engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
        try:
            with create_session_factory(engine)() as session:
                count = session.scalar(select(func.count()).select_from(TradingCalendar))
            assert count == 0
            assert len(sdk.calls) == 1
        finally:
            engine.dispose()

    asyncio.run(scenario())


def test_web_only_configuration_edit_preserves_current_provider_pipeline(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
        state = composition._runtime._probe_capabilities.__self__
        pipeline = state._pipeline
        calls = tuple(sdk.calls)
        try:
            config = tmp_path / "config/app.yaml"
            config.write_text(
                config.read_text(encoding="utf-8") + "web:\n  port: 8766\n",
                encoding="utf-8",
            )
            assert state.configuration_is_current()
            await state.validate_configuration()
            state.probe_capabilities()
            assert state._pipeline is pipeline
            assert tuple(sdk.calls) == calls
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_running_token_drift_latches_restart_without_new_provider_or_alert_work(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
        original_runtime = composition._runtime
        state = original_runtime._probe_capabilities.__self__
        config = tmp_path / "config/app.yaml"
        original = config.read_text(encoding="utf-8")
        calls = tuple(sdk.calls)
        try:
            config.write_text(
                original.replace("offline-test-token", "offline-new-token"),
                encoding="utf-8",
            )
            blocked = composition.health()
            assert blocked.status is RuntimeServiceStatus.BLOCKED
            assert blocked.block_reason == "NEEDS_RESTART"
            assert not state.configuration_is_current()
            config.write_text(original, encoding="utf-8")
            assert not state.configuration_is_current()
            assert composition._runtime is original_runtime
            with pytest.raises(RuntimeError, match="safe restart required"):
                state.probe_capabilities()
            assert tuple(sdk.calls) == calls
            engine = create_sqlite_engine(tmp_path / "monitor.sqlite3")
            try:
                with create_session_factory(engine)() as session:
                    assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
            finally:
                engine.dispose()
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_invalid_new_configuration_fails_before_provider_and_can_be_fixed_for_new_start(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        config = tmp_path / "config/app.yaml"
        original = config.read_text(encoding="utf-8")
        config.write_text("tushare: [\n", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            await composition.start()
        assert sdk.calls == []
        config.write_text(original, encoding="utf-8")
        replacement = create_monitor_composition(
            config_path=config, database_path=tmp_path / "monitor.sqlite3"
        )
        try:
            assert (await replacement.start()).status is RuntimeServiceStatus.RUNNING
        finally:
            await replacement.stop()

    asyncio.run(scenario())


def test_current_decision_rolls_back_when_token_changes_after_result_staging(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, _, _ = _composition(tmp_path, monkeypatch)
        config = tmp_path / "config/app.yaml"
        original_persist = DailyRepository.save
        changed = False

        def drift_after_result(self, *args, **kwargs):
            nonlocal changed
            value = original_persist(self, *args, **kwargs)
            if (
                kwargs["kind"] == "EVALUATION"
                and kwargs["payload"]["minute_target"] is not None
                and not changed
            ):
                changed = True
                config.write_text(
                    config.read_text(encoding="utf-8").replace(
                        "offline-test-token", "offline-new-token"
                    ),
                    encoding="utf-8",
                )
            return value

        monkeypatch.setattr(DailyRepository, "save", drift_after_result)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._run_deadline.__self__
            with state._session_factory() as session:
                before = _current_ledger(session)
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=NOW.date(),
                due_at=NOW,
                bar_end=NOW.replace(second=0),
            )
            with pytest.raises(RuntimeError):
                await state.run_deadline(deadline)
            assert changed
            with state._session_factory() as session:
                assert _minute_count(session) == 0
                assert _current_ledger(session) == before
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutation",
    (
        "unchanged",
        "token",
        "invalid_yaml",
        "stock_semantic",
        "new_index_semantic",
        "candidate_start_semantic",
    ),
)
def test_supervisor_replacement_cannot_adopt_configuration_changed_inside_factory(
    tmp_path,
    monkeypatch,
    mutation,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        original_runtime = composition._runtime
        original_factory = composition._runtime_factory
        assert original_factory is not None
        release_failure = asyncio.Event()
        config = tmp_path / "config/app.yaml"
        replacements = []
        factory_errors = []

        def install_index_semantic():
            _write_configuration_and_evidence(tmp_path, observed_at=NOW, include_index=True)
            directory = tmp_path / "data/live-certification"
            assert (
                import_index_semantic_contract(
                    directory / "tushare-board-index-live.json",
                    directory / "index-semantic.json",
                    now=NOW,
                    endpoint_url=str(load_application_config(config).tushare.api_url),
                )
                is not None
            )

        async def fail_after_start():
            await release_failure.wait()
            raise RuntimeError("offline runner failure")

        def change_between_check_and_factory():
            try:
                if mutation == "token":
                    config.write_text(
                        config.read_text(encoding="utf-8").replace(
                            "offline-test-token", "offline-new-token"
                        ),
                        encoding="utf-8",
                    )
                elif mutation == "invalid_yaml":
                    config.write_text("tushare: [\n", encoding="utf-8")
                elif mutation == "stock_semantic":
                    (tmp_path / "data/live-certification/stock-semantic.json").write_text(
                        "{}", encoding="utf-8"
                    )
                elif mutation == "new_index_semantic":
                    install_index_semantic()
                replacement = original_factory()
                if mutation == "candidate_start_semantic":
                    original_open = replacement._open_database

                    async def edit_before_database_open():
                        install_index_semantic()
                        await original_open()

                    replacement._open_database = edit_before_database_open
                replacements.append(replacement)
                return replacement
            except Exception as error:
                factory_errors.append(error)
                raise

        original_runtime.run = fail_after_start
        composition._runtime_factory = change_between_check_and_factory
        composition._restart_sleep = lambda _delay: asyncio.sleep(0)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            release_failure.set()
            for _ in range(200):
                if replacements and (
                    composition._runtime is replacements[0] or composition._runner_task.done()
                ):
                    break
                await asyncio.sleep(0.01)
            assert factory_errors == []
            assert len(replacements) == 1
            if mutation == "unchanged":
                assert composition._runtime is replacements[0]
                assert composition.health().status is RuntimeServiceStatus.RUNNING
            else:
                assert composition.health().status is RuntimeServiceStatus.BLOCKED
                assert composition.health().block_reason == "NEEDS_RESTART"
                candidate_state = replacements[0]._probe_capabilities.__self__
                assert candidate_state._pipeline is None
                assert candidate_state._liveness_revision is None
            assert sdk.calls
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_worker_thread_latch_before_current_commit_rejects_staged_decision(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        config = tmp_path / "config/app.yaml"
        original_persist = DailyRepository.save
        staged = False
        worker_latched = False

        def stage_result(self, *args, **kwargs):
            nonlocal staged
            value = original_persist(self, *args, **kwargs)
            if kwargs["kind"] == "EVALUATION" and kwargs["payload"]["minute_target"] is not None:
                staged = True
            return value

        monkeypatch.setattr(DailyRepository, "save", stage_result)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            with state._session_factory() as session:
                before = _current_ledger(session)
            pipeline = state._pipeline
            assert pipeline is not None
            original_generation_current = pipeline._generation_current

            def interleave_worker_revocation():
                nonlocal worker_latched
                if staged and not worker_latched:

                    def worker():
                        nonlocal worker_latched
                        original = config.read_text(encoding="utf-8")
                        config.write_text(
                            original.replace("offline-test-token", "offline-new-token"),
                            encoding="utf-8",
                        )
                        worker_latched = not state.configuration_is_current()
                        config.write_text(original, encoding="utf-8")

                    thread = Thread(target=worker)
                    thread.start()
                    thread.join(timeout=2)
                    assert not thread.is_alive()
                    assert worker_latched
                return original_generation_current()

            pipeline._generation_current = interleave_worker_revocation
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=NOW.date(),
                due_at=NOW,
                bar_end=NOW.replace(second=0),
            )
            with pytest.raises(RuntimeError):
                await state.run_deadline(deadline)
            assert staged and worker_latched
            calls = tuple(sdk.calls)
            with pytest.raises(RequestControlError) as blocked:
                await state._request_controller.execute(
                    TushareOperation.REALTIME_MINUTES,
                    lambda: pytest.fail("revoked provider call became physical"),
                    work_key="post-revocation",
                )
            assert blocked.value.code is RequestControlErrorCode.CLOSED
            assert tuple(sdk.calls) == calls
            assert composition.health().block_reason == "NEEDS_RESTART"
            with state._session_factory() as session:
                assert _minute_count(session) == 0
                assert _current_ledger(session) == before
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_revocation_after_final_permit_finishes_one_inflight_decision(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, _, _ = _composition(tmp_path, monkeypatch)
        config = tmp_path / "config/app.yaml"
        original_persist = DailyRepository.save
        staged = False
        revoked_after_permit = False

        def stage_result(self, *args, **kwargs):
            nonlocal staged
            value = original_persist(self, *args, **kwargs)
            if kwargs["kind"] == "EVALUATION" and kwargs["payload"]["minute_target"] is not None:
                staged = True
            return value

        monkeypatch.setattr(DailyRepository, "save", stage_result)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            pipeline = state._pipeline
            assert pipeline is not None
            original_admission = pipeline._decision_commit_current

            def admit_then_revoke():
                nonlocal revoked_after_permit
                allowed = original_admission()
                if staged and allowed and not revoked_after_permit:

                    def worker():
                        original = config.read_text(encoding="utf-8")
                        config.write_text(
                            original.replace("offline-test-token", "offline-new-token"),
                            encoding="utf-8",
                        )
                        assert not state.configuration_is_current()
                        config.write_text(original, encoding="utf-8")

                    thread = Thread(target=worker)
                    thread.start()
                    thread.join(timeout=2)
                    assert not thread.is_alive()
                    assert state._process_baseline.revoked.is_set()
                    assert not state._configuration_restart_required
                    revoked_after_permit = True
                return allowed

            pipeline._decision_commit_current = admit_then_revoke
            pipeline.daily_evaluations._admission = admit_then_revoke
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=NOW.date(),
                due_at=NOW,
                bar_end=NOW.replace(second=0),
            )
            with pytest.raises(RuntimeError, match="runtime index commit admission revoked"):
                await state.run_deadline(deadline)
            assert revoked_after_permit
            with state._session_factory() as session:
                assert _minute_count(session) == 1
            assert composition.health().block_reason == "NEEDS_RESTART"
            assert not pipeline._decision_commit_current()
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_stop_before_final_decision_permit_rolls_back_staged_result(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, _, _ = _composition(tmp_path, monkeypatch)
        original_persist = DailyRepository.save
        stop_started = False

        def stop_after_staging(self, *args, **kwargs):
            nonlocal stop_started
            value = original_persist(self, *args, **kwargs)
            if (
                kwargs["kind"] == "EVALUATION"
                and kwargs["payload"]["minute_target"] is not None
                and not stop_started
            ):
                stop_started = True
                composition._runtime.begin_shutdown()
            return value

        monkeypatch.setattr(DailyRepository, "save", stop_after_staging)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            with state._session_factory() as session:
                before = _current_ledger(session)
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=NOW.date(),
                due_at=NOW,
                bar_end=NOW.replace(second=0),
            )
            with pytest.raises(RuntimeError, match="commit admission changed"):
                await state.run_deadline(deadline)
            assert stop_started
            with state._session_factory() as session:
                assert _minute_count(session) == 0
                assert _current_ledger(session) == before
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 0
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_stop_revokes_unpublished_candidate_during_replacement_start(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch)
        original_runtime = composition._runtime
        original_factory = composition._runtime_factory
        assert original_factory is not None
        release_failure = asyncio.Event()
        candidate_entered = asyncio.Event()
        release_candidate = asyncio.Event()
        candidates = []

        async def fail_after_start():
            await release_failure.wait()
            raise RuntimeError("offline runner failure")

        def delayed_factory():
            candidate = original_factory()
            probe = candidate._probe_capabilities

            async def wait_before_probe():
                candidate_entered.set()
                await release_candidate.wait()
                return probe()

            candidate._probe_capabilities = wait_before_probe
            candidates.append(candidate)
            return candidate

        original_runtime.run = fail_after_start
        composition._runtime_factory = delayed_factory
        composition._restart_sleep = lambda _delay: asyncio.sleep(0)
        stop_task = None
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            initial_calls = tuple(sdk.calls)
            release_failure.set()
            await asyncio.wait_for(candidate_entered.wait(), timeout=2)
            assert len(candidates) == 1
            candidate = candidates[0]
            assert candidate.business_commit_admission_open
            stop_task = asyncio.create_task(composition.stop())
            await asyncio.sleep(0)
            assert composition._stopping
            assert not candidate.business_commit_admission_open
            assert candidate._request_controller._closed
            release_candidate.set()
            await asyncio.wait_for(stop_task, timeout=2)
            assert tuple(sdk.calls) == initial_calls
        finally:
            release_candidate.set()
            if stop_task is not None:
                await asyncio.gather(stop_task, return_exceptions=True)
            else:
                await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("recover_drain", (False, True))
def test_failed_candidate_drain_remains_owned_for_stop_retry(
    tmp_path,
    monkeypatch,
    recover_drain,
):
    async def scenario():
        composition, _, _ = _composition(tmp_path, monkeypatch)
        original_runtime = composition._runtime
        original_factory = composition._runtime_factory
        assert original_factory is not None
        release_failure = asyncio.Event()
        candidate_entered = asyncio.Event()
        release_candidate = asyncio.Event()
        drain_fails = [True]
        candidates = []

        async def fail_after_start():
            await release_failure.wait()
            raise RuntimeError("offline runner failure")

        def delayed_factory():
            candidate = original_factory()
            refresh = candidate._refresh_references
            drain = candidate._dispatcher.aclose

            async def wait_before_refresh(trade_date):
                candidate_entered.set()
                await release_candidate.wait()
                return await refresh(trade_date)

            async def fail_drain_until_recovered():
                if drain_fails[0]:
                    raise RuntimeError("offline candidate drain failure")
                await drain()

            candidate._refresh_references = wait_before_refresh
            candidate._dispatcher.aclose = fail_drain_until_recovered
            candidates.append(candidate)
            return candidate

        original_runtime.run = fail_after_start
        composition._runtime_factory = delayed_factory
        composition._restart_sleep = lambda _delay: asyncio.sleep(0)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            release_failure.set()
            await asyncio.wait_for(candidate_entered.wait(), timeout=2)
            candidate = candidates[0]
            assert candidate._database_opened
            release_candidate.set()
            with pytest.raises(RuntimeError, match="offline candidate drain failure"):
                await composition.stop()
            assert not candidate._cleanup_complete
            assert candidate._database_opened
            assert composition._candidate_runtime is candidate
            repository = candidate._request_controller._recovery_repository
            assert repository is not None
            repository.assert_owner(candidate._request_controller)

            drain_fails[0] = not recover_drain
            if recover_drain:
                await composition.stop()
                assert candidate._cleanup_complete
                assert not candidate._database_opened
                assert candidate._request_controller_closed
                assert composition._candidate_runtime is None
                with pytest.raises(RecoveryCheckpointError):
                    repository.assert_owner(candidate._request_controller)
            else:
                with pytest.raises(RuntimeError, match="offline candidate drain failure"):
                    await composition.stop()
                assert composition._candidate_runtime is candidate
                assert candidate._database_opened
                repository.assert_owner(candidate._request_controller)
        finally:
            release_candidate.set()
            drain_fails[0] = False
            if not composition._stopped:
                await composition.stop()

    asyncio.run(scenario())


def test_delivery_revoked_during_final_db_admission_never_enters_channel(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        composition, _, _ = _composition(tmp_path, monkeypatch)
        config = tmp_path / "config/app.yaml"
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            with state.unit_of_work_factory() as work:
                work.alerts.enqueue_recoverable(_payload(991))
                work.commit()
            entered = []

            class Channel:
                channel = DeliveryChannel.IN_APP
                enabled = True

                async def deliver(self, event):
                    entered.append((event.event_id, state._process_baseline.revoked.is_set()))
                    return ChannelDeliveryResult(
                        channel=self.channel,
                        delivered=True,
                        retryable=False,
                    )

            state._dispatcher._channels = (Channel(),)
            admission_calls = 0

            def revoke_during_final_admission(_self, _event, _now):
                nonlocal admission_calls
                admission_calls += 1
                if admission_calls == 2:

                    def worker():
                        original = config.read_text(encoding="utf-8")
                        config.write_text(
                            original.replace("offline-test-token", "offline-new-token"),
                            encoding="utf-8",
                        )
                        assert not state.configuration_is_current()
                        config.write_text(original, encoding="utf-8")

                    thread = Thread(target=worker)
                    thread.start()
                    thread.join(timeout=2)
                    assert not thread.is_alive()
                return True

            monkeypatch.setattr(CurrentDeliveryAdmission, "__call__", revoke_during_final_admission)
            await state._dispatcher.dispatch_pending()
            assert admission_calls == 2
            assert state._process_baseline.revoked.is_set()
            assert entered == []
        finally:
            await composition.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("pending_present", (False, True))
def test_completed_close_pending_clear_without_health_event_still_requires_commit_admission(
    pending_present: bool,
):
    async def scenario():
        commits = []

        class Work:
            evaluations = SimpleNamespace(has_claim=lambda **_kwargs: True)
            projections = SimpleNamespace(
                get_pending_official_close=lambda **_kwargs: object() if pending_present else None
            )

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def commit(self):
                commits.append(True)

        service = object.__new__(RuntimeEvaluationService)
        service._unit_of_work_factory = Work
        service._runtime_generation = uuid4()
        service._progress_unit = None
        service._commit_admission = lambda: False
        service._require_evaluated_plan_active = lambda *_args, **_kwargs: None
        service._clear_close_pending = lambda *_args, **_kwargs: None

        async def publish(_events):
            pass

        service._publish_committed_events = publish

        def call():
            return service._official_close_completed(
                plan=_historical_sample_plan(),
                trade_date=NOW.date(),
                evaluated_at=NOW,
                activation_revision=1,
            )

        if pending_present:
            with pytest.raises(RuntimeError, match="commit admission revoked"):
                await call()
            assert commits == []
        else:
            assert await call() is True
            assert commits == [True]

    asyncio.run(scenario())
