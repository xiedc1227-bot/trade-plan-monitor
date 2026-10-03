"""UPD-S3 common direct units; not automatic scheduler acceptance."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import delete, event, text
from sqlalchemy.exc import OperationalError
from test_live_pipeline_acceptance import ControlledClock, _activate_plans, _sample_plan
from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
from test_production_certification_gate import _composition
from test_production_daily_bar_permission_preparation import harness, ready
from test_production_index_daily_permission_maintenance import _one_official_index_day
from test_production_index_historical_permission_probe import _complete_index_day
from test_unified_permission_legacy_owners import OWNERS, _case
from tests.integration.current_activation_fixture import current_mixed_plan

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.production import (
    _PERMISSION_SCOPES,
    PermissionMaintenanceResult,
    _CertifiedTushareClient,
)
from trade_plan_monitor.runtime.recovery import RecoveryAdmissionChangedError
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.runtime_recovery import ProviderRecoveryRepository


@asynccontextmanager
async def _active_case(tmp_path, monkeypatch):
    composition, sdk, _ = _composition(
        tmp_path,
        monkeypatch,
        active_plan=True,
        include_index=True,
        stock_certification=True,
        persisted_calendar=True,
        plan=current_mixed_plan(),
    )
    try:
        assert (await composition.start()).status.value == "RUNNING"
        state = composition._runtime._probe_capabilities.__self__
        pipe, control = state._pipeline, composition._runtime._request_controller
        _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
        monkeypatch.setattr(
            sdk,
            "_historical_index_minutes",
            lambda _: _complete_index_day(
                MarketIndexCode.SSE_COMPOSITE,
                ANCHOR,
            ),
        )
        monkeypatch.setattr(
            sdk,
            "_index_daily",
            lambda kwargs: _one_official_index_day(
                MarketIndexCode(kwargs["ts_code"]),
                ANCHOR,
            ),
        )
        yield composition, pipe, control, sdk
    finally:
        await composition.stop()


CURRENT_SCOPES = tuple(
    operation for operation in _PERMISSION_SCOPES
    if operation is not TushareOperation.DAILY_LIMITS
)


def test_current_equal_due_scopes_get_one_real_proof_each(tmp_path, monkeypatch):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            for operation in CURRENT_SCOPES:
                await _block(control, operation)
            raw = {control.raw_permission_retry_at(op) for op in CURRENT_SCOPES}
            assert len(raw) == 1
            pipe._clock.current += timedelta(seconds=301)
            for i, operation in enumerate(CURRENT_SCOPES):
                before = len(sdk.calls)
                result = await pipe.run_permission_maintenance_unit()
                assert result is PermissionMaintenanceResult.PROBED, (operation, sdk.calls[-1])
                assert len(sdk.calls) == before + 1
                assert pipe._permission_rotation_state.last_operation is operation
                assert all(
                    control.is_permission_blocked(op) is (j > i)
                    for j, op in enumerate(CURRENT_SCOPES)
                )
            assert pipe.next_permission_probe_due_at() is None

    asyncio.run(scenario())


def test_current_plan_does_not_authorize_retired_daily_limits_probe(tmp_path, monkeypatch):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            operation = TushareOperation.DAILY_LIMITS
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            before = tuple(sdk.calls), pipe._permission_rotation_state
            raw = control.raw_permission_retry_at(operation)
            assert await pipe.run_permission_maintenance_unit() is (
                PermissionMaintenanceResult.DEFERRED
            )
            assert control.is_permission_blocked(operation)
            assert control.raw_permission_retry_at(operation) == raw
            assert (tuple(sdk.calls), pipe._permission_rotation_state) == before
            assert pipe._permission_probe_deferred_until[operation] == (
                pipe._clock.now() + timedelta(seconds=30)
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("moment", ["entry", "evidence"])
@pytest.mark.parametrize("revoked", [False, True])
def test_global_authority_loss_never_becomes_local_polling(
    tmp_path,
    monkeypatch,
    moment,
    revoked,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, OWNERS[0][0]) as (_, pipe, control, sdk):
            calls, raw = tuple(sdk.calls), control.raw_permission_retry_at(OWNERS[0][0])

            def retire():
                monkeypatch.setattr(pipe, "_admission_revoked", lambda: revoked)
                monkeypatch.setattr(pipe, "_generation_current", lambda: False)

            if moment == "entry":
                retire()
            else:
                original = pipe._permission_probe_state

                def changed(**kwargs):
                    result = original(**kwargs)
                    retire()
                    return result

                monkeypatch.setattr(pipe, "_permission_probe_state", changed)
            if revoked:
                with pytest.raises(RecoveryAdmissionChangedError):
                    await pipe.run_permission_maintenance_unit()
            else:
                assert (
                    await pipe.run_permission_maintenance_unit()
                    is PermissionMaintenanceResult.SKIPPED
                )
            assert pipe._permission_probe_deferred_until == {}
            assert control.raw_permission_retry_at(OWNERS[0][0]) == raw
            assert tuple(sdk.calls) == calls

    asyncio.run(scenario())


REMAINING = CURRENT_SCOPES[3:]


@pytest.mark.parametrize(
    "operation",
    (
        *CURRENT_SCOPES[:3],
        TushareOperation.INDEX_DAILY,
    ),
)
@pytest.mark.parametrize("revoked", [False, True])
def test_held_preparation_authority_loss_does_not_reserve_or_poll(
    tmp_path,
    monkeypatch,
    operation,
    revoked,
):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            original = pipe._permission_probe_state
            reads = []

            def read(*args, **kwargs):
                result = original(*args, **kwargs)
                reads.append(result)
                if len(reads) == 2:
                    monkeypatch.setattr(pipe, "_admission_revoked", lambda: revoked)
                    monkeypatch.setattr(pipe, "_generation_current", lambda: False)
                return result

            monkeypatch.setattr(pipe, "_permission_probe_state", read)
            calls, raw = tuple(sdk.calls), control.raw_permission_retry_at(operation)
            if revoked:
                with pytest.raises(RecoveryAdmissionChangedError):
                    await pipe.run_permission_maintenance_unit()
            else:
                assert await pipe.run_permission_maintenance_unit() is (
                    PermissionMaintenanceResult.SKIPPED
                )
                assert operation not in pipe._permission_probe_deferred_until
            assert len(reads) == 2
            assert tuple(sdk.calls) == calls
            assert control.raw_permission_retry_at(operation) == raw

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation",
    [
        TushareOperation.TRADING_CALENDAR,
        TushareOperation.INDEX_DAILY,
    ],
)
@pytest.mark.parametrize("revoked", [False, True])
def test_selected_real_anchor_read_rechecks_global_authority(
    tmp_path,
    monkeypatch,
    operation,
    revoked,
):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (composition, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            state = composition._runtime._probe_capabilities.__self__
            original = pipe._permission_probe_state
            reads, anchor_reads = [], []

            def selection(*args, **kwargs):
                result = original(*args, **kwargs)
                reads.append(result)
                return result

            def after_sql(_conn, _cursor, sql, *_args):
                if len(reads) == 2 and "FROM trading_calendar" in sql and not anchor_reads:
                    anchor_reads.append(sql)
                    monkeypatch.setattr(pipe, "_admission_revoked", lambda: revoked)
                    monkeypatch.setattr(pipe, "_generation_current", lambda: False)

            monkeypatch.setattr(pipe, "_permission_probe_state", selection)
            event.listen(state._engine, "after_cursor_execute", after_sql)
            calls, raw = tuple(sdk.calls), control.raw_permission_retry_at(operation)
            try:
                if revoked:
                    with pytest.raises(RecoveryAdmissionChangedError):
                        await pipe.run_permission_maintenance_unit()
                else:
                    assert await pipe.run_permission_maintenance_unit() is (
                        PermissionMaintenanceResult.SKIPPED
                    )
                    assert operation not in pipe._permission_probe_deferred_until
                assert len(anchor_reads) == 1
                assert tuple(sdk.calls) == calls
                assert control.raw_permission_retry_at(operation) == raw
            finally:
                event.remove(state._engine, "after_cursor_execute", after_sql)

    asyncio.run(scenario())


def test_preparation_sql_failure_is_not_masked_by_simultaneous_retirement(tmp_path, monkeypatch):
    async def scenario():
        async with _case(tmp_path, monkeypatch, OWNERS[0][0]) as (_, pipe, _control, _sdk):
            failure = OperationalError("offline read", {}, RuntimeError("offline SQL cause"))

            def fail(**_kwargs):
                monkeypatch.setattr(pipe, "_generation_current", lambda: False)
                raise failure

            monkeypatch.setattr(pipe, "_permission_probe_state", fail)
            with pytest.raises(OperationalError) as caught:
                await pipe.run_permission_maintenance_unit()
            assert caught.value is failure

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation,authority_call",
    [
        (TushareOperation.CURRENT_DAY_MINUTES, 1),
        (TushareOperation.REALTIME_MINUTES, 1),
        (TushareOperation.DAILY_BARS, 1),
        (TushareOperation.DAILY_BARS, 2),
    ],
)
@pytest.mark.parametrize("revoked", [False, True])
def test_prepared_owner_certification_io_rechecks_global_authority(
    tmp_path,
    monkeypatch,
    operation,
    authority_call,
    revoked,
):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            prepared = Event()
            method = (
                "_prepare_daily_bar_permission_locked"
                if operation is TushareOperation.DAILY_BARS
                else "_prepare_stock_minute_permission_locked"
            )
            original_prepare = getattr(pipe, method)
            original_authority = pipe._stock_certification_current
            checks, preparations = [], []

            def preparation(*args):
                value = original_prepare(*args)
                assert value.status == "PREPARED"
                preparations.append(value)
                prepared.set()
                return value

            def authority():
                valid = original_authority()
                if prepared.is_set():
                    checks.append(valid)
                    if len(checks) == authority_call:
                        monkeypatch.setattr(pipe, "_admission_revoked", lambda: revoked)
                        monkeypatch.setattr(pipe, "_generation_current", lambda: False)
                return valid

            monkeypatch.setattr(pipe, method, preparation)
            monkeypatch.setattr(pipe, "_stock_certification_current", authority)
            before, raw = tuple(sdk.calls), control.raw_permission_retry_at(operation)
            if revoked:
                with pytest.raises(RecoveryAdmissionChangedError):
                    await pipe.run_permission_maintenance_unit()
            else:
                assert await pipe.run_permission_maintenance_unit() is (
                    PermissionMaintenanceResult.SKIPPED
                )
                assert operation not in pipe._permission_probe_deferred_until
            assert len(checks) == authority_call
            assert len(preparations) == 1
            assert tuple(sdk.calls) == before and control.raw_permission_retry_at(operation) == raw
            assert pipe._permission_rotation_state.last_operation is None

    asyncio.run(scenario())


SDK_ATTRIBUTE = {
    TushareOperation.DAILY_BARS: "_stock_daily",
    TushareOperation.DAILY_LIMITS: "_limits",
    TushareOperation.INDEX_DAILY: "_index_daily",
    TushareOperation.CURRENT_DAY_MINUTES: "_stock_minutes",
    TushareOperation.REALTIME_MINUTES: "_stock_minutes",
}
NAMED_REMAINING = {
    TushareOperation.DAILY_BARS: "_maybe_recheck_daily_bars_permission",
    TushareOperation.DAILY_LIMITS: "_maybe_recheck_daily_limits_permission",
    TushareOperation.INDEX_DAILY: "_maybe_recheck_index_daily_permission",
    TushareOperation.CURRENT_DAY_MINUTES: "_maybe_recheck_current_day_minutes_permission",
    TushareOperation.REALTIME_MINUTES: "_maybe_recheck_realtime_minutes_permission",
}


@pytest.mark.parametrize("operation", REMAINING)
def test_remaining_named_nonwinner_never_prepares_or_reserves(tmp_path, monkeypatch, operation):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            await _block(control, TushareOperation.TRADING_CALENDAR)
            pipe._clock.current += timedelta(seconds=1)
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            raw = control.raw_permission_retry_at(operation)
            before = tuple(sdk.calls), pipe._permission_rotation_state

            def forbidden(*_args):
                pytest.fail("named nonwinner prepared or reserved a scope")

            monkeypatch.setattr(pipe, "_prepare_daily_bar_permission_locked", forbidden)
            monkeypatch.setattr(pipe, "_prepare_stock_minute_permission_locked", forbidden)
            monkeypatch.setattr(pipe, "_permission_probe_reservation_callback", forbidden)
            assert await getattr(pipe, NAMED_REMAINING[operation])() is (
                PermissionMaintenanceResult.SKIPPED
            )
            assert control.raw_permission_retry_at(operation) == raw
            assert (tuple(sdk.calls), pipe._permission_rotation_state) == before
            assert pipe.select_due_permission_probe().operation is TushareOperation.TRADING_CALENDAR

    asyncio.run(scenario())


def test_failed_reserved_scope_does_not_starve_equal_due_sibling(tmp_path, monkeypatch):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            for operation in _PERMISSION_SCOPES[:2]:
                await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)

            def fail(*_args):
                raise TushareProviderError(TushareErrorCode.TRANSIENT, "trade_cal")

            monkeypatch.setattr(sdk, "_calendar", fail)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.FAILED
            )
            assert pipe._permission_rotation_state.last_operation is _PERMISSION_SCOPES[0]
            assert control.is_permission_blocked(_PERMISSION_SCOPES[0])
            assert pipe.next_permission_probe_due_at() <= pipe._clock.now()
            count = len(sdk.calls)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.PROBED
            )
            assert len(sdk.calls) == count + 1
            assert pipe._permission_rotation_state.last_operation is _PERMISSION_SCOPES[1]
            assert control.is_permission_blocked(_PERMISSION_SCOPES[0])

    asyncio.run(scenario())


def _business_rows(pipe):
    with pipe._permission_session_factory() as session:
        return {
            table: tuple(session.execute(text(f"SELECT * FROM {table}")))
            for table in (
                "trading_calendar",
                "daily_bar",
                "minute_bar",
                "latest_quote",
                "market_index_snapshot",
                "evaluation_ledger",
                "alert_event",
                "delivery_attempt",
            )
        }


@pytest.mark.parametrize("operation", REMAINING)
@pytest.mark.parametrize("window", ["resolver", "sdk"])
def test_remaining_cancelled_physical_work_drains_without_late_clear(
    tmp_path,
    monkeypatch,
    operation,
    window,
):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            entered, release = Event(), Event()
            before, count = _business_rows(pipe), len(sdk.calls)
            attribute = SDK_ATTRIBUTE[operation]
            valid = getattr(sdk, attribute)

            def held(*args):
                entered.set()
                assert release.wait(5)
                return valid(*args)

            if window == "sdk":
                monkeypatch.setattr(sdk, attribute, held)
            else:
                original = _CertifiedTushareClient.prepare_permission_endpoint

                def resolve(client, endpoint):
                    value = original(client, endpoint)
                    entered.set()
                    assert release.wait(5)
                    return value

                monkeypatch.setattr(_CertifiedTushareClient, "prepare_permission_endpoint", resolve)
            task = asyncio.create_task(pipe.run_permission_maintenance_unit())
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert not pipe._permission_maintenance_lock.locked()
                assert control.active_count == 1 and control.is_permission_blocked(operation)
                release.set()
                async with asyncio.timeout(5):
                    while control.active_count:
                        await asyncio.sleep(0.001)
                assert control.is_permission_blocked(operation)
                assert len(sdk.calls) == count + (window == "sdk")
                assert pipe._permission_rotation_state.last_operation is operation
                assert _business_rows(pipe) == before
            finally:
                release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", REMAINING)
@pytest.mark.parametrize(
    "code", ["BLOCKED_PERMISSION", "RATE_LIMITED", "TRANSIENT", "TIMEOUT", "INVALID_RESPONSE"]
)
def test_remaining_real_provider_failures_are_scoped_without_business_writes(
    tmp_path,
    monkeypatch,
    operation,
    code,
):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            before, count = _business_rows(pipe), len(sdk.calls)

            def fail(*_args):
                raise TushareProviderError(TushareErrorCode(code), operation.value)

            monkeypatch.setattr(sdk, SDK_ATTRIBUTE[operation], fail)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.FAILED
            )
            assert len(sdk.calls) == count + 1 and control.is_permission_blocked(operation)
            assert control.permission_retry_at(operation) >= pipe._clock.now() + timedelta(
                seconds=300
            )
            assert pipe._permission_rotation_state.last_operation is operation
            assert _business_rows(pipe) == before

    asyncio.run(scenario())


def test_common_and_named_callers_share_lock_and_ack_each_reservation_once(tmp_path, monkeypatch):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            for operation in _PERMISSION_SCOPES:
                await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            callback = pipe._permission_probe_reservation_callback
            receipts, acknowledgements = [], []

            def reserve(candidate):
                assert pipe._permission_maintenance_lock.locked()
                receipts.append(candidate)
                acknowledge = callback(candidate)

                def once():
                    assert pipe._permission_maintenance_lock.locked()
                    acknowledgements.append(candidate)
                    return acknowledge()

                return once

            monkeypatch.setattr(pipe, "_permission_probe_reservation_callback", reserve)
            calls = len(sdk.calls)
            async with asyncio.timeout(5):
                results = await asyncio.gather(
                    pipe.run_permission_maintenance_unit(),
                    pipe._maybe_recheck_historical_index_permission(),
                    pipe.run_permission_maintenance_unit(),
                )
            assert results == [PermissionMaintenanceResult.PROBED] * 3
            assert len(sdk.calls) == calls + 3
            assert receipts == acknowledgements and len(receipts) == 3
            assert [item.operation for item in receipts] == list(_PERMISSION_SCOPES[:3])
            assert pipe._permission_rotation_state.current_day_minute_symbol is None
            assert pipe._permission_rotation_state.realtime_minute_symbol is None
            assert all(control.is_permission_blocked(op) for op in REMAINING)
            assert pipe.next_permission_probe_due_at() <= pipe._clock.now()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation", [TushareOperation.DAILY_BARS, TushareOperation.CURRENT_DAY_MINUTES]
)
@pytest.mark.parametrize("revoked", [False, True])
def test_selected_preparation_retires_before_reservation_without_its_new_defer(
    tmp_path,
    monkeypatch,
    operation,
    revoked,
):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            method = (
                "_prepare_daily_bar_permission_locked"
                if operation is TushareOperation.DAILY_BARS
                else "_prepare_stock_minute_permission_locked"
            )
            original = getattr(pipe, method)
            calls, raw = tuple(sdk.calls), control.raw_permission_retry_at(operation)
            preparations = []

            def prepare(*args):
                unavailable = (
                    "_permission_demand_reader"
                    if operation is TushareOperation.DAILY_BARS
                    else "_permission_session_factory"
                )
                with monkeypatch.context() as local:
                    local.setattr(pipe, unavailable, None)
                    result = original(*args)
                assert result.status == "UNKNOWN"
                preparations.append(result)
                monkeypatch.setattr(pipe, "_admission_revoked", lambda: revoked)
                monkeypatch.setattr(pipe, "_generation_current", lambda: False)
                return result

            monkeypatch.setattr(pipe, method, prepare)
            if revoked:
                with pytest.raises(RecoveryAdmissionChangedError):
                    await pipe.run_permission_maintenance_unit()
            else:
                assert (
                    await pipe.run_permission_maintenance_unit()
                    is PermissionMaintenanceResult.SKIPPED
                )
                assert operation not in pipe._permission_probe_deferred_until
            assert len(preparations) == 1
            assert control.raw_permission_retry_at(operation) == raw
            assert tuple(sdk.calls) == calls

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", REMAINING)
def test_remaining_owner_cancellation_during_final_authority_io_keeps_block(
    tmp_path,
    monkeypatch,
    operation,
):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (composition, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            state = composition._runtime._probe_capabilities.__self__
            response_read, cancelled = Event(), Event()
            calls = len(sdk.calls)
            authority_name = (
                "_index_certification_current"
                if operation is TushareOperation.INDEX_DAILY
                else "_stock_certification_current"
            )
            original = getattr(pipe, authority_name)
            owner = None

            def after_sql(_conn, _cursor, sql, *_args):
                if len(sdk.calls) > calls and "FROM trading_calendar" in sql:
                    response_read.set()

            def authority():
                valid = original()
                if response_read.is_set() and not cancelled.is_set():
                    cancelled.set()
                    owner.cancel()
                return valid

            monkeypatch.setattr(pipe, authority_name, authority)
            event.listen(state._engine, "after_cursor_execute", after_sql)
            try:
                owner = asyncio.create_task(pipe.run_permission_maintenance_unit())
                with pytest.raises(asyncio.CancelledError):
                    await owner
                assert cancelled.is_set()
                assert control.is_permission_blocked(operation)
                assert len(sdk.calls) == calls + 1
                assert pipe._permission_rotation_state.last_operation is operation
                assert control.raw_permission_retry_at(operation) > pipe._clock.now()
            finally:
                event.remove(state._engine, "after_cursor_execute", after_sql)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", REMAINING)
@pytest.mark.parametrize("code", ["ERROR", "CLOSED", "QUEUE_FULL"])
def test_remaining_owner_fatal_error_preserves_original_exception(
    tmp_path,
    monkeypatch,
    operation,
    code,
):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            failure = RequestControlError(RequestControlErrorCode(code), operation, attempts=2)
            cause = ValueError("offline cause")
            failure.__cause__ = cause
            calls = tuple(sdk.calls)

            async def fail(*_args, **_kwargs):
                raise failure

            monkeypatch.setattr(TushareRequestController, "recheck_permission", fail)
            with pytest.raises(RequestControlError) as caught:
                await pipe.run_permission_maintenance_unit()
            assert caught.value is failure and caught.value.__cause__ is cause
            assert caught.value.attempts == 2 and tuple(sdk.calls) == calls

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", REMAINING)
def test_remaining_owner_retains_concrete_error_retry_floor(tmp_path, monkeypatch, operation):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            retry_at = pipe._clock.now() + timedelta(seconds=601)
            failure = RequestControlError(
                RequestControlErrorCode.TRANSIENT,
                operation,
                attempts=1,
                next_retry_at=retry_at,
            )
            calls = tuple(sdk.calls)

            async def fail(*_args, **_kwargs):
                raise failure

            monkeypatch.setattr(TushareRequestController, "recheck_permission", fail)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.FAILED
            )
            assert pipe.next_permission_probe_due_at() == retry_at
            assert pipe._permission_probe_deferred_until[operation] == retry_at
            assert tuple(sdk.calls) == calls and control.is_permission_blocked(operation)

    asyncio.run(scenario())


def test_common_unit_dispatches_one_calendar_scope(tmp_path, monkeypatch):
    async def scenario():
        async with _case(tmp_path, monkeypatch, OWNERS[0][0]) as (_, pipe, control, sdk):
            calls = len(sdk.calls)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.PROBED
            )
            assert len(sdk.calls) == calls + 1
            assert not control.is_permission_blocked(OWNERS[0][0])
            assert pipe._permission_rotation_state.last_operation is OWNERS[0][0]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation,field",
    [
        (TushareOperation.INDEX_HISTORICAL_MINUTES, "_historical_probe_deferred_until"),
        (TushareOperation.INDEX_REALTIME_MINUTES, "_realtime_probe_deferred_until"),
    ],
)
def test_legacy_index_floor_blocks_common_evidence_io(tmp_path, monkeypatch, operation, field):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            future = pipe._clock.now() + timedelta(seconds=75)
            setattr(pipe, field, future)
            before = tuple(sdk.calls), pipe._permission_rotation_state
            assert pipe.next_permission_probe_due_at() == future

            def forbidden(**_kwargs):
                pytest.fail("future legacy floor must not cause fresh evidence I/O")

            monkeypatch.setattr(pipe, "_permission_probe_state", forbidden)
            for _ in range(3):
                assert (
                    await pipe.run_permission_maintenance_unit()
                    is PermissionMaintenanceResult.SKIPPED
                )
                pipe._clock.current += timedelta(seconds=1)
            assert getattr(pipe, field) == future
            assert pipe._permission_probe_deferred_until == {}
            assert (tuple(sdk.calls), pipe._permission_rotation_state) == before
            assert control.is_permission_blocked(operation)

    asyncio.run(scenario())


def test_rotation_starts_after_ack_but_earlier_raw_still_wins(tmp_path, monkeypatch):
    async def scenario():
        async with _active_case(tmp_path, monkeypatch) as (_, pipe, control, sdk):
            earlier, first, second = _PERMISSION_SCOPES[:3]
            await _block(control, earlier)
            pipe._clock.current += timedelta(seconds=1)
            await _block(control, first)
            await _block(control, second)
            pipe._permission_rotation_state = replace(
                pipe._permission_rotation_state,
                last_operation=first,
            )
            pipe._clock.current += timedelta(seconds=301)
            before = len(sdk.calls)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.PROBED
            )
            assert pipe._permission_rotation_state.last_operation is earlier
            assert len(sdk.calls) == before + 1
            # Pure peeks neither reserve nor consume the next equal-raw turn.
            for _ in range(3):
                assert pipe.select_due_permission_probe().operation is first
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.PROBED
            )
            assert pipe._permission_rotation_state.last_operation is first
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.PROBED
            )
            assert pipe._permission_rotation_state.last_operation is second

    asyncio.run(scenario())


@pytest.mark.parametrize("missing_anchor", [False, True])
def test_daily_bar_synthetic_rank_prepares_once_and_freezes_actual_receipt(
    tmp_path,
    monkeypatch,
    missing_anchor,
):
    with harness(tmp_path, monkeypatch, days=1, anchor=not missing_anchor) as env:
        env.controller.bind_recovery_repository(
            ProviderRecoveryRepository(env.sessions, provider_identity="d" * 64),
        )
        second = _sample_plan().model_copy(update={"symbol": "003044.SZ", "plan_id": "today-B"})
        _activate_plans(
            env.database, ControlledClock(env.clock.now() - timedelta(hours=1)), (second,)
        )
        ready(env)
        pipe = env.pipeline
        pipe._permission_market_window = lambda *_: ()
        broad = pipe.permission_probe_candidates()
        if missing_anchor:
            assert not broad
        else:
            assert broad[0].symbol == env.plans[0].symbol
        original = pipe._prepare_daily_bar_permission_locked
        held = pipe._recheck_daily_bars_permission_locked
        reader = pipe._permission_demand_reader
        inspect, validate = (
            reader.inspect_permission_demand_in_session,
            reader.validate_permission_demand_in_session,
        )
        prepared, received, pages, checks = [], [], [], []

        def preparation():
            value = original()
            assert len(checks) <= 10
            prepared.append(value)
            return value

        async def execute(owner, cancelled, value):
            assert pipe._permission_maintenance_lock.locked()
            received.append(value)
            return await held(owner, cancelled, value)

        def inspection(session, symbol, now, cursor=None):
            value = inspect(session, symbol, now, cursor)
            pages.append((symbol, value.status))
            return value

        def validation(*args):
            checks.append(args[1])
            return validate(*args)

        monkeypatch.setattr(pipe, "_prepare_daily_bar_permission_locked", preparation)
        monkeypatch.setattr(pipe, "_recheck_daily_bars_permission_locked", execute)
        monkeypatch.setattr(reader, "inspect_permission_demand_in_session", inspection)
        monkeypatch.setattr(reader, "validate_permission_demand_in_session", validation)
        result = asyncio.run(pipe.run_permission_maintenance_unit())
        assert len(prepared) == len(received) == 1 and received[0] is prepared[0]
        assert pages == [(second.symbol, "NEEDED"), (env.plans[0].symbol, "NONE")]
        assert len(checks) <= 10 + 1  # Preparation's <=10 checks plus response's one witness.
        if missing_anchor:
            assert result is PermissionMaintenanceResult.DEFERRED and not env.sdk.calls
            assert prepared[0].status == "UNKNOWN"
            assert pipe._permission_probe_deferred_until[TushareOperation.DAILY_BARS] == (
                env.clock.now() + timedelta(seconds=30)
            )
        else:
            assert result is PermissionMaintenanceResult.PROBED
            assert prepared[0].candidate.symbol == second.symbol
            assert prepared[0].receipt.identity.symbol == second.symbol
            assert len(env.sdk.calls) == 1 and env.sdk.calls[0][1]["ts_code"] == second.symbol


@pytest.mark.parametrize("stage", ["evidence", "preparation"])
def test_slow_unavailable_check_sets_future_fixed_wake_at_completion(tmp_path, monkeypatch, stage):
    async def scenario():
        operation = (
            TushareOperation.TRADING_CALENDAR
            if stage == "evidence"
            else TushareOperation.DAILY_BARS
        )
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            with pipe._permission_session_factory.begin() as session:
                session.execute(delete(TradingCalendar))
            method = (
                "_permission_probe_state"
                if stage == "evidence"
                else "_prepare_daily_bar_permission_locked"
            )
            original = getattr(pipe, method)
            observations = []

            def slow(*args, **kwargs):
                result = original(*args, **kwargs)
                pipe._clock.current += timedelta(seconds=31)
                observations.append(pipe._clock.now())
                return result

            monkeypatch.setattr(pipe, method, slow)
            before = tuple(sdk.calls), pipe._permission_rotation_state
            raw = control.raw_permission_retry_at(operation)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.DEFERRED
            )
            assert len(observations) == 1
            expected = observations[0] + timedelta(seconds=30)
            assert pipe.next_permission_probe_due_at() == expected
            assert pipe._permission_probe_deferred_until[operation] == expected
            for _ in range(3):
                pipe._clock.current += timedelta(seconds=1)
                assert pipe.next_permission_probe_due_at() == expected
                assert (
                    await pipe.run_permission_maintenance_unit()
                    is PermissionMaintenanceResult.SKIPPED
                )
            assert len(observations) == 1
            assert (tuple(sdk.calls), pipe._permission_rotation_state) == before
            assert control.raw_permission_retry_at(operation) == raw

    asyncio.run(scenario())


def test_all_due_unavailable_get_fixed_checks_without_reservation(tmp_path, monkeypatch):
    async def scenario():
        async with _case(tmp_path, monkeypatch, OWNERS[0][0]) as (_, pipe, control, sdk):
            for operation in _PERMISSION_SCOPES[1:]:
                await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            with pipe._permission_session_factory.begin() as session:
                session.execute(delete(TradingCalendar))
            before = {op: control.raw_permission_retry_at(op) for op in _PERMISSION_SCOPES}
            calls, rotation = tuple(sdk.calls), pipe._permission_rotation_state
            expected = pipe._clock.now() + timedelta(seconds=30)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.DEFERRED
            )
            assert pipe._permission_probe_deferred_until == dict.fromkeys(
                _PERMISSION_SCOPES, expected
            )
            assert pipe._historical_probe_deferred_until == expected
            assert pipe._realtime_probe_deferred_until == expected
            assert {op: control.raw_permission_retry_at(op) for op in _PERMISSION_SCOPES} == before
            assert tuple(sdk.calls) == calls and pipe._permission_rotation_state is rotation
            pipe._clock.current += timedelta(seconds=1)

            def forbidden(*_args, **_kwargs):
                pytest.fail("not-due entry/getter performed evidence or authority I/O")

            with monkeypatch.context() as guard:
                guard.setattr(pipe, "_permission_probe_state", forbidden)
                guard.setattr(pipe, "_stock_certification_current", forbidden)
                guard.setattr(pipe, "_index_certification_current", forbidden)
                assert (
                    await pipe.run_permission_maintenance_unit()
                    is PermissionMaintenanceResult.SKIPPED
                )
                guard.setattr(type(pipe._clock), "now", forbidden)
                for _ in range(3):
                    assert pipe.next_permission_probe_due_at() == expected
            assert pipe._permission_probe_deferred_until == dict.fromkeys(
                _PERMISSION_SCOPES, expected
            )

    asyncio.run(scenario())


def test_missing_consumers_do_not_starve_ready_calendar(tmp_path, monkeypatch):
    async def scenario():
        async with _case(tmp_path, monkeypatch, OWNERS[0][0]) as (_, pipe, control, sdk):
            for operation in _PERMISSION_SCOPES[-2:]:
                await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            expected = pipe._clock.now() + timedelta(seconds=30)
            calls = len(sdk.calls)
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.PROBED
            )
            assert len(sdk.calls) == calls + 1
            for operation in _PERMISSION_SCOPES[-2:]:
                assert control.is_permission_blocked(operation)
                assert pipe._permission_probe_deferred_until[operation] == expected
            assert pipe.next_permission_probe_due_at() == expected

    asyncio.run(scenario())


def test_ordinary_calendar_request_never_rechecks_inline(tmp_path, monkeypatch):
    async def scenario():
        operation = OWNERS[0][0]
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            raw, calls = control.raw_permission_retry_at(operation), tuple(sdk.calls)
            with pytest.raises(RequestControlError):
                await pipe._request(
                    operation, lambda: pytest.fail("ordinary SDK entered"), "ordinary"
                )
            assert control.raw_permission_retry_at(operation) == raw
            assert control.is_permission_blocked(operation)
            assert tuple(sdk.calls) == calls
            assert pipe._permission_rotation_state.last_operation is None
            assert (
                await pipe.run_permission_maintenance_unit() is PermissionMaintenanceResult.PROBED
            )

    asyncio.run(scenario())
