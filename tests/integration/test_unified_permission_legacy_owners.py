"""UPD-S2 direct named owners share arbitration and physical-entry authority."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from threading import Event, current_thread, main_thread

import pytest
from sqlalchemy import delete, event, text, update
from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
from test_production_certification_gate import _composition
from test_production_index_historical_permission_probe import _complete_index_day

from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.production import (
    PermissionMaintenanceResult,
    _CertifiedTushareClient,
)
from trade_plan_monitor.runtime.request_control import (
    PermissionReservationCallbackError,
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.runtime_recovery import (
    ProviderRecoveryRepository,
    RecoveryCheckpointError,
)

OWNERS = (
    (TushareOperation.TRADING_CALENDAR, "_maybe_recheck_calendar_permission"),
    (TushareOperation.INDEX_HISTORICAL_MINUTES, "_maybe_recheck_historical_index_permission"),
    (TushareOperation.INDEX_REALTIME_MINUTES, "_maybe_recheck_realtime_index_permission"),
)


def _valid_sdk_response(sdk, operation):
    if operation is TushareOperation.INDEX_HISTORICAL_MINUTES:
        return "_historical_index_minutes", lambda _kwargs: _complete_index_day(
            MarketIndexCode.SSE_COMPOSITE,
            ANCHOR,
        )
    attribute = "_calendar" if operation is TushareOperation.TRADING_CALENDAR else "_index_minutes"
    return attribute, getattr(sdk, attribute)


@asynccontextmanager
async def _case(tmp_path, monkeypatch, operation, *, winner=None, checkpoint_failure=False):
    composition, sdk, _ = _composition(
        tmp_path,
        monkeypatch,
        active_plan=False,
        include_index=True,
        stock_certification=True,
        persisted_calendar=True,
    )
    try:
        assert (await composition.start()).status.value == "RUNNING"
        runtime = composition._runtime
        pipeline = runtime._probe_capabilities.__self__._pipeline
        control = runtime._request_controller
        _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
        if winner is not None:
            await _block(control, winner)
            runtime._clock.current += timedelta(seconds=1)
        await _block(control, operation)
        runtime._clock.current += timedelta(seconds=301)
        yield composition, pipeline, control, sdk
    finally:
        if checkpoint_failure:
            with pytest.raises(RecoveryCheckpointError, match="could not be checkpointed"):
                await composition.stop()
        else:
            await composition.stop()


@pytest.mark.parametrize("operation,name", OWNERS)
def test_named_nonwinner_cannot_reserve_or_probe(tmp_path, monkeypatch, operation, name):
    async def scenario():
        winner = (
            TushareOperation.INDEX_DAILY
            if operation is TushareOperation.TRADING_CALENDAR
            else TushareOperation.TRADING_CALENDAR
        )
        async with _case(tmp_path, monkeypatch, operation, winner=winner) as case:
            _, pipe, control, sdk = case
            assert pipe.select_due_permission_probe().operation is winner
            raw = control.raw_permission_retry_at(operation)
            calls, rotation = tuple(sdk.calls), pipe._permission_rotation_state
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.SKIPPED
            assert control.raw_permission_retry_at(operation) == raw
            assert tuple(sdk.calls) == calls
            assert pipe._permission_rotation_state is rotation

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_checkpoint_save_failure_propagates_without_ack(tmp_path, monkeypatch, operation, name):
    async def scenario():
        async with _case(
            tmp_path,
            monkeypatch,
            operation,
            checkpoint_failure=True,
        ) as (_, pipe, control, sdk):
            failure = RecoveryCheckpointError("offline checkpoint failure")
            calls, rotation = tuple(sdk.calls), pipe._permission_rotation_state

            def fail(*_args):
                raise failure

            with monkeypatch.context() as local:
                local.setattr(ProviderRecoveryRepository, "save", fail)
                with pytest.raises(RecoveryCheckpointError) as caught:
                    await getattr(pipe, name)()
            assert caught.value is failure
            assert pipe._permission_rotation_state is rotation
            assert tuple(sdk.calls) == calls
            assert control.is_permission_blocked(operation)

    asyncio.run(scenario())


def test_calendar_preserves_original_work_key_backoff(tmp_path, monkeypatch):
    async def scenario():
        operation, name = OWNERS[0]
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            control._backoff = (timedelta(seconds=300),)

            def late_failure():
                pipe._clock.current += timedelta(seconds=1)
                raise TushareProviderError(TushareErrorCode.TRANSIENT, "trade_cal")

            with pytest.raises(RequestControlError) as caught:
                await control.recheck_permission(
                    operation,
                    late_failure,
                    work_key="permission:trade_cal:SSE",
                )
            assert caught.value.code is RequestControlErrorCode.TRANSIENT
            raw = control.raw_permission_retry_at(operation)
            floor = control.backoff_until("permission:trade_cal:SSE")
            assert floor == raw + timedelta(seconds=1)
            pipe._clock.current = raw
            calls = len(sdk.calls)
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.FAILED
            assert len(sdk.calls) == calls
            assert control.is_permission_blocked(operation)
            assert control.backoff_until("permission:trade_cal:SSE") == floor
            # A new durable reservation may add its own later 300-second floor.
            next_due = control.permission_retry_at(operation)
            assert next_due >= floor
            assert pipe._permission_rotation_state.last_operation is operation
            pipe._clock.current = next_due
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.PROBED
            assert len(sdk.calls) == calls + 1
            assert not control.is_permission_blocked(operation)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_missing_market_window_defers_without_reservation(tmp_path, monkeypatch, operation, name):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            pipe._permission_market_window = None
            calls, raw = tuple(sdk.calls), control.raw_permission_retry_at(operation)
            expected = pipe._clock.now() + timedelta(seconds=30)
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.DEFERRED
            assert control.raw_permission_retry_at(operation) == raw
            assert tuple(sdk.calls) == calls
            assert pipe.next_permission_probe_due_at() == expected
            if operation is TushareOperation.INDEX_HISTORICAL_MINUTES:
                assert pipe.next_historical_index_permission_due_at() == expected
            elif operation is TushareOperation.INDEX_REALTIME_MINUTES:
                assert pipe.next_realtime_index_permission_due_at() == expected
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.SKIPPED
            assert pipe.next_permission_probe_due_at() == expected

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
@pytest.mark.parametrize("mutation", ["late", "revoked", "inner_source"])
def test_actual_wrapper_final_boundary_rejects_after_resolver(
    tmp_path,
    monkeypatch,
    operation,
    name,
    mutation,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            calls = tuple(sdk.calls)
            provider = (
                pipe.provider
                if operation is TushareOperation.TRADING_CALENDAR
                else (pipe.index_provider)
            )
            wrapper = provider._client
            original = _CertifiedTushareClient.prepare_permission_endpoint

            def prepare(client, endpoint):
                resolved = original(client, endpoint)
                if client is wrapper:
                    if mutation == "late":
                        pipe._clock.current += timedelta(seconds=15, microseconds=1)
                    elif mutation == "revoked":
                        pipe._calendar_revoked.set()
                    else:
                        client._client = object()
                return resolved

            monkeypatch.setattr(_CertifiedTushareClient, "prepare_permission_endpoint", prepare)
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.DEFERRED
            assert tuple(sdk.calls) == calls
            assert control.is_permission_blocked(operation)
            assert control.raw_permission_retry_at(operation) > pipe._clock.now()
            assert pipe._permission_rotation_state.last_operation is operation

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
@pytest.mark.parametrize("code", ["ERROR", "CLOSED", "QUEUE_FULL"])
def test_fatal_controller_errors_keep_original_identity(
    tmp_path,
    monkeypatch,
    operation,
    name,
    code,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, _control, sdk):
            calls = tuple(sdk.calls)
            failure = RequestControlError(RequestControlErrorCode(code), operation, attempts=2)
            cause = ValueError("offline original cause")
            failure.__cause__ = cause

            async def fail(*_args, **_kwargs):
                raise failure

            monkeypatch.setattr(TushareRequestController, "recheck_permission", fail)
            with pytest.raises(RequestControlError) as caught:
                await getattr(pipe, name)()
            assert caught.value is failure
            assert caught.value.attempts == 2 and caught.value.__cause__ is cause
            assert tuple(sdk.calls) == calls

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
@pytest.mark.parametrize("elapsed", [0, 15])
def test_real_final_entry_accepts_equality_and_never_reads_worker_sql(
    tmp_path,
    monkeypatch,
    operation,
    name,
    elapsed,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (composition, pipe, control, sdk):
            state = composition._runtime._probe_capabilities.__self__
            attribute, valid = _valid_sdk_response(sdk, operation)
            monkeypatch.setattr(sdk, attribute, valid)
            calls = len(sdk.calls)
            original = _CertifiedTushareClient.prepare_permission_endpoint

            def prepare(client, endpoint):
                resolved = original(client, endpoint)
                pipe._clock.current += timedelta(seconds=elapsed)
                return resolved

            monkeypatch.setattr(_CertifiedTushareClient, "prepare_permission_endpoint", prepare)

            def sql_owner(*_args):
                assert current_thread() is main_thread(), "permission SDK worker accessed SQL"

            event.listen(state._engine, "before_cursor_execute", sql_owner)
            original_task = asyncio.current_task

            def current_task(*args, **kwargs):
                assert current_thread() is main_thread(), "worker accessed Task API"
                return original_task(*args, **kwargs)

            monkeypatch.setattr(asyncio, "current_task", current_task)
            try:
                assert await getattr(pipe, name)() is PermissionMaintenanceResult.PROBED
            finally:
                event.remove(state._engine, "before_cursor_execute", sql_owner)
            assert len(sdk.calls) == calls + 1
            assert not control.is_permission_blocked(operation)
            assert pipe._permission_rotation_state.last_operation is operation

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
@pytest.mark.parametrize("offset", [31.25, 31.250001])
def test_market_reserve_equality_precedes_permission_reservation(
    tmp_path,
    monkeypatch,
    operation,
    name,
    offset,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            captured = pipe._clock.now()
            pipe._permission_market_window = lambda _now, _horizon: (
                (captured + timedelta(seconds=offset), True),
            )
            attribute, valid = _valid_sdk_response(sdk, operation)
            monkeypatch.setattr(sdk, attribute, valid)
            raw, calls = control.raw_permission_retry_at(operation), len(sdk.calls)
            admitted = offset > 31.25
            assert await getattr(pipe, name)() is (
                PermissionMaintenanceResult.PROBED
                if admitted
                else PermissionMaintenanceResult.DEFERRED
            )
            assert len(sdk.calls) == calls + int(admitted)
            if not admitted:
                assert control.raw_permission_retry_at(operation) == raw
                assert pipe._permission_rotation_state.last_operation is None
                assert control.is_permission_blocked(operation)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
@pytest.mark.parametrize("late", [False, True])
def test_final_authority_io_precedes_single_sample_and_actual_sdk(
    tmp_path,
    monkeypatch,
    operation,
    name,
    late,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            resolved, final_io, entered = Event(), Event(), Event()
            samples = []
            authority_name = (
                "_stock_certification_current"
                if operation is TushareOperation.TRADING_CALENDAR
                else "_index_certification_current"
            )
            original_authority = getattr(pipe, authority_name)
            original_prepare = _CertifiedTushareClient.prepare_permission_endpoint
            original_now = type(pipe._clock).now
            attribute, valid = _valid_sdk_response(sdk, operation)

            def prepare(client, endpoint):
                method = original_prepare(client, endpoint)
                resolved.set()
                return method

            def authority():
                current = original_authority()
                if resolved.is_set() and not final_io.is_set():
                    if late:
                        pipe._clock.current += timedelta(seconds=15, microseconds=1)
                    final_io.set()
                return current

            def now(clock):
                value = original_now(clock)
                if final_io.is_set() and not entered.is_set():
                    samples.append(value)
                return value

            def response(kwargs):
                assert final_io.is_set()
                assert samples == [pipe._clock.current]
                entered.set()
                return valid(kwargs)

            monkeypatch.setattr(_CertifiedTushareClient, "prepare_permission_endpoint", prepare)
            monkeypatch.setattr(pipe, authority_name, authority)
            monkeypatch.setattr(type(pipe._clock), "now", now)
            monkeypatch.setattr(sdk, attribute, response)
            calls = len(sdk.calls)
            assert await getattr(pipe, name)() is (
                PermissionMaintenanceResult.DEFERRED if late else PermissionMaintenanceResult.PROBED
            )
            assert final_io.is_set() and entered.is_set() is not late
            assert len(sdk.calls) == calls + int(not late)
            assert control.is_permission_blocked(operation) is late

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_real_resolver_consumes_reserve_before_final_sdk_entry(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            captured = pipe._clock.now()
            market = captured + timedelta(seconds=32)
            pipe._permission_market_window = lambda _now, _horizon: ((market, True),)
            original = _CertifiedTushareClient.prepare_permission_endpoint
            calls, raw = tuple(sdk.calls), control.raw_permission_retry_at(operation)

            def prepare(client, endpoint):
                resolved = original(client, endpoint)
                pipe._clock.current += timedelta(seconds=1)
                return resolved

            monkeypatch.setattr(_CertifiedTushareClient, "prepare_permission_endpoint", prepare)
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.DEFERRED
            assert tuple(sdk.calls) == calls
            assert control.raw_permission_retry_at(operation) > raw
            assert pipe._permission_rotation_state.last_operation is operation
            assert pipe._permission_probe_deferred_until[operation] == market + timedelta(
                microseconds=1
            )
            assert control.is_permission_blocked(operation)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_revoked_calendar_token_is_replaced_only_after_fresh_evidence(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            old = pipe._calendar_revoked
            old.set()
            attribute, valid = _valid_sdk_response(sdk, operation)
            monkeypatch.setattr(sdk, attribute, valid)
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.PROBED
            assert old.is_set()
            assert pipe._calendar_revoked is not old
            assert not pipe._calendar_revoked.is_set()
            assert not control.is_permission_blocked(operation)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_response_sql_failure_propagates_without_permission_clear(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (composition, pipe, control, sdk):
            engine = composition._runtime._probe_capabilities.__self__._engine
            attribute, valid = _valid_sdk_response(sdk, operation)
            returned = Event()
            failure = RuntimeError("offline response SQL failure")

            def response(kwargs):
                result = valid(kwargs)
                returned.set()
                return result

            def fail_sql(_conn, _cursor, sql, *_args):
                if returned.is_set() and "FROM trading_calendar" in sql:
                    raise failure

            monkeypatch.setattr(sdk, attribute, response)
            event.listen(engine, "before_cursor_execute", fail_sql)
            try:
                with pytest.raises(RuntimeError) as caught:
                    await getattr(pipe, name)()
                assert caught.value is failure
                assert control.is_permission_blocked(operation)
                assert pipe._permission_rotation_state.last_operation is operation
            finally:
                event.remove(engine, "before_cursor_execute", fail_sql)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_response_exact_original_anchor_cannot_be_replaced_by_another_valid_day(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            candidate = pipe.select_due_permission_probe()
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR - timedelta(days=3))
            attribute, valid = _valid_sdk_response(sdk, operation)
            entered, release = Event(), Event()

            def held(kwargs):
                entered.set()
                assert release.wait(5)
                return valid(kwargs)

            monkeypatch.setattr(sdk, attribute, held)
            task = asyncio.create_task(getattr(pipe, name)())
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                with pipe._permission_session_factory.begin() as session:
                    session.execute(
                        delete(TradingCalendar).where(
                            TradingCalendar.exchange == "SSE",
                            TradingCalendar.cal_date == candidate.anchor_date,
                        )
                    )
                release.set()
                assert await task is PermissionMaintenanceResult.FAILED
                assert control.is_permission_blocked(operation)
                assert pipe._permission_rotation_state.last_operation is operation
            finally:
                release.set()
                if not task.done():
                    await task

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
@pytest.mark.parametrize("change", ["epoch", "event"])
def test_calendar_token_changed_during_evidence_read_cannot_rearm(
    tmp_path,
    monkeypatch,
    operation,
    name,
    change,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            old = pipe._calendar_revoked
            old.set()
            original = pipe._permission_probe_state
            calls, raw = tuple(sdk.calls), control.raw_permission_retry_at(operation)

            def read(**kwargs):
                result = original(**kwargs)
                if change == "epoch":
                    pipe._calendar_epoch += 1
                else:
                    pipe._calendar_revoked = Event()
                return result

            monkeypatch.setattr(pipe, "_permission_probe_state", read)
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.DEFERRED
            assert old.is_set()
            assert tuple(sdk.calls) == calls
            assert control.raw_permission_retry_at(operation) == raw

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
@pytest.mark.parametrize("window", ["sdk", "resolver"])
def test_cancelled_sdk_late_success_keeps_block_and_physical_slot(
    tmp_path,
    monkeypatch,
    operation,
    name,
    window,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            attribute, valid = _valid_sdk_response(sdk, operation)
            entered, release = Event(), Event()

            def held(kwargs):
                entered.set()
                assert release.wait(5)
                return valid(kwargs)

            calls = len(sdk.calls)
            if window == "sdk":
                monkeypatch.setattr(sdk, attribute, held)
            else:
                monkeypatch.setattr(sdk, attribute, valid)
                original = _CertifiedTushareClient.prepare_permission_endpoint

                def held_resolver(client, endpoint):
                    result = original(client, endpoint)
                    entered.set()
                    assert release.wait(5)
                    return result

                monkeypatch.setattr(
                    _CertifiedTushareClient,
                    "prepare_permission_endpoint",
                    held_resolver,
                )
            task = asyncio.create_task(getattr(pipe, name)())
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert not pipe._permission_maintenance_lock.locked()
                assert control.active_count == 1
                assert control.is_permission_blocked(operation)
                release.set()
                async with asyncio.timeout(5):
                    while control.active_count:
                        await asyncio.sleep(0.001)
                assert control.is_permission_blocked(operation)
                assert pipe._permission_rotation_state.last_operation is operation
                assert len(sdk.calls) == calls + (1 if window == "sdk" else 0)
            finally:
                release.set()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
@pytest.mark.parametrize(
    "code",
    [
        "BLOCKED_PERMISSION",
        "RATE_LIMITED",
        "TRANSIENT",
        "TIMEOUT",
        "INVALID_RESPONSE",
    ],
)
def test_real_known_provider_failure_is_scoped_without_business_writes(
    tmp_path,
    monkeypatch,
    operation,
    name,
    code,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            factory = pipe._permission_session_factory

            def rows():
                with factory() as session:
                    return {
                        table: tuple(session.execute(text(f"SELECT * FROM {table}")))
                        for table in (
                            "trading_calendar",
                            "minute_bar",
                            "latest_quote",
                            "market_index_snapshot",
                            "evaluation_ledger",
                            "alert_event",
                            "delivery_attempt",
                        )
                    }

            before = rows()
            attribute, _ = _valid_sdk_response(sdk, operation)

            def fail(_kwargs):
                raise TushareProviderError(TushareErrorCode(code), operation.value)

            monkeypatch.setattr(sdk, attribute, fail)
            count = len(sdk.calls)
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.FAILED
            assert len(sdk.calls) == count + 1
            assert control.is_permission_blocked(operation)
            assert control.permission_retry_at(operation) >= pipe._clock.now() + timedelta(
                seconds=300,
            )
            assert pipe._permission_rotation_state.last_operation is operation
            assert rows() == before

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_callback_failure_retains_reservation_and_propagates(
    tmp_path, monkeypatch, operation, name
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            raw, calls = control.raw_permission_retry_at(operation), tuple(sdk.calls)

            def callback(_candidate):
                assert pipe._permission_maintenance_lock.locked()

                def fail():
                    raise RuntimeError("offline callback")

                return fail

            monkeypatch.setattr(pipe, "_permission_probe_reservation_callback", callback)
            with pytest.raises(PermissionReservationCallbackError):
                await getattr(pipe, name)()
            assert control.raw_permission_retry_at(operation) > raw
            assert tuple(sdk.calls) == calls
            assert pipe._permission_rotation_state.last_operation is None

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_requested_cancellation_during_response_snapshot_cannot_clear(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (composition, pipe, control, sdk):
            engine = composition._runtime._probe_capabilities.__self__._engine
            attribute, valid = _valid_sdk_response(sdk, operation)
            returned = Event()
            owner = None

            def response(kwargs):
                result = valid(kwargs)
                returned.set()
                return result

            def after_sql(_conn, _cursor, sql, *_args):
                if returned.is_set() and "FROM trading_calendar" in sql:
                    owner.cancel()
                    assert owner.cancelling() and not owner.done()

            monkeypatch.setattr(sdk, attribute, response)
            event.listen(engine, "after_cursor_execute", after_sql)
            try:
                owner = asyncio.create_task(getattr(pipe, name)())
                with pytest.raises(asyncio.CancelledError):
                    await owner
                assert control.is_permission_blocked(operation)
            finally:
                event.remove(engine, "after_cursor_execute", after_sql)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_requested_cancellation_in_final_authority_io_cannot_clear(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (composition, pipe, control, sdk):
            engine = composition._runtime._probe_capabilities.__self__._engine
            attribute, valid = _valid_sdk_response(sdk, operation)
            returned, anchor_read, cancelled = Event(), Event(), Event()
            authority_name = (
                "_stock_certification_current"
                if operation is TushareOperation.TRADING_CALENDAR
                else "_index_certification_current"
            )
            original_authority = getattr(pipe, authority_name)
            calls, raw = len(sdk.calls), control.raw_permission_retry_at(operation)
            owner = None

            def response(kwargs):
                result = valid(kwargs)
                returned.set()
                return result

            def after_sql(_conn, _cursor, sql, *_args):
                if returned.is_set() and "FROM trading_calendar" in sql:
                    anchor_read.set()

            def authority():
                current = original_authority()
                if anchor_read.is_set() and not cancelled.is_set():
                    assert current_thread() is main_thread()
                    cancelled.set()
                    owner.cancel()
                    assert owner.cancelling() and not owner.done()
                return current

            monkeypatch.setattr(sdk, attribute, response)
            monkeypatch.setattr(pipe, authority_name, authority)
            event.listen(engine, "after_cursor_execute", after_sql)
            try:
                owner = asyncio.create_task(getattr(pipe, name)())
                with pytest.raises(asyncio.CancelledError):
                    await owner
                assert cancelled.is_set()
                assert control.is_permission_blocked(operation)
                assert control.raw_permission_retry_at(operation) > raw
                assert pipe._permission_rotation_state.last_operation is operation
                assert len(sdk.calls) == calls + 1
                assert control.active_count == 0
            finally:
                event.remove(engine, "after_cursor_execute", after_sql)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_response_borrowed_session_is_not_closed_or_rolled_back(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            original = pipe._permission_session_factory
            attribute, valid = _valid_sdk_response(sdk, operation)
            returned = Event()

            def response(kwargs):
                result = valid(kwargs)
                returned.set()
                return result

            monkeypatch.setattr(sdk, attribute, response)
            with original() as borrowed:
                borrowed.execute(text("SELECT 1"))
                transaction = borrowed.get_transaction()
                pipe._permission_session_factory = lambda: (
                    borrowed if returned.is_set() else original()
                )
                with pytest.raises(ValueError, match="fresh session"):
                    await getattr(pipe, name)()
                assert borrowed.get_transaction() is transaction
                assert borrowed.scalar(text("SELECT 1")) == 1
                assert control.is_permission_blocked(operation)

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_response_uses_one_new_explicit_begin_snapshot(tmp_path, monkeypatch, operation, name):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (composition, pipe, _control, sdk):
            engine = composition._runtime._probe_capabilities.__self__._engine
            attribute, valid = _valid_sdk_response(sdk, operation)
            returned, statements = Event(), []

            def response(kwargs):
                result = valid(kwargs)
                returned.set()
                return result

            def record(_conn, _cursor, sql, *_args):
                if returned.is_set():
                    statements.append(sql)

            monkeypatch.setattr(sdk, attribute, response)
            event.listen(engine, "before_cursor_execute", record)
            try:
                assert await getattr(pipe, name)() is PermissionMaintenanceResult.PROBED
            finally:
                event.remove(engine, "before_cursor_execute", record)
            anchor_queries = [
                i for i, sql in enumerate(statements) if "FROM trading_calendar" in sql
            ]
            assert len(anchor_queries) == 1
            assert statements[anchor_queries[0] - 1] == "BEGIN"

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS[:2])
def test_calendar_closed_anchor_is_not_an_open_history_anchor(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            with pipe._permission_session_factory.begin() as session:
                session.execute(delete(TradingCalendar).where(TradingCalendar.cal_date != ANCHOR))
                session.execute(update(TradingCalendar).values(is_open=False))
            calls = len(sdk.calls)
            result = await getattr(pipe, name)()
            calendar = operation is TushareOperation.TRADING_CALENDAR
            assert result is (
                PermissionMaintenanceResult.PROBED
                if calendar
                else PermissionMaintenanceResult.DEFERRED
            )
            assert len(sdk.calls) == calls + int(calendar)
            assert control.is_permission_blocked(operation) is not calendar

    asyncio.run(scenario())


def test_concurrent_named_owners_serialize_real_reservations_and_keep_other_cursors(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, OWNERS[0][0]) as (_, pipe, control, sdk):
            for operation, _ in OWNERS[1:]:
                await _block(control, operation)
            pipe._clock.current += timedelta(seconds=301)
            pipe._permission_rotation_state = replace(
                pipe._permission_rotation_state,
                official_pair=("003043.SZ", ANCHOR),
                fallback_pair=("003044.SZ", ANCHOR),
                next_daily_bar_pool="F",
                current_day_minute_symbol="003045.SZ",
                realtime_minute_symbol="003046.SZ",
            )
            before = pipe._permission_rotation_state
            attribute, valid = _valid_sdk_response(sdk, OWNERS[1][0])
            monkeypatch.setattr(sdk, attribute, valid)
            start = len(sdk.calls)
            results = await asyncio.gather(*(getattr(pipe, name)() for _, name in OWNERS))
            assert results == [PermissionMaintenanceResult.PROBED] * 3
            assert [name for name, _ in sdk.calls[start:]] == [
                "trade_cal",
                "idx_mins",
                "rt_idx_min_daily",
            ]
            current = pipe._permission_rotation_state
            assert current.last_operation is OWNERS[-1][0]
            assert replace(current, last_operation=before.last_operation) == before

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_named_owner_waits_for_shared_lock_before_any_reservation(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            raw, calls = control.raw_permission_retry_at(operation), tuple(sdk.calls)
            async with pipe._permission_maintenance_lock:
                task = asyncio.create_task(getattr(pipe, name)())
                await asyncio.sleep(0)
                assert not task.done()
                assert control.raw_permission_retry_at(operation) == raw
                assert tuple(sdk.calls) == calls
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

    asyncio.run(scenario())


@pytest.mark.parametrize("operation,name", OWNERS)
def test_durable_queue_veto_acknowledges_once_without_moving_other_cursors(
    tmp_path,
    monkeypatch,
    operation,
    name,
):
    async def scenario():
        async with _case(tmp_path, monkeypatch, operation) as (_, pipe, control, sdk):
            prior = pipe._permission_rotation_state
            calls = tuple(sdk.calls)
            raw = control.raw_permission_retry_at(operation)
            original = TushareRequestController.recheck_permission
            acknowledgements = []

            async def queue_veto(controller, op, function, **kwargs):
                callback = kwargs.get("on_reserved")

                def ack():
                    assert control.raw_permission_retry_at(operation) > raw
                    acknowledgements.append(op)
                    if callback is not None:
                        callback()

                kwargs.update(can_start=lambda: False, on_reserved=ack)
                return await original(controller, op, function, **kwargs)

            monkeypatch.setattr(TushareRequestController, "recheck_permission", queue_veto)
            assert await getattr(pipe, name)() is PermissionMaintenanceResult.DEFERRED
            assert acknowledgements == [operation]
            current = pipe._permission_rotation_state
            assert current.last_operation is operation
            for field in (
                "next_daily_bar_pool",
                "official_pair",
                "fallback_pair",
                "current_day_minute_symbol",
                "realtime_minute_symbol",
            ):
                assert getattr(current, field) == getattr(prior, field)
            assert tuple(sdk.calls) == calls
            assert control.is_permission_blocked(operation)

    asyncio.run(scenario())
