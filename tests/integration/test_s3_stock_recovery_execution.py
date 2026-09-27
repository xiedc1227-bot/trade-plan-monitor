"""F3-B direct single-unit execution; not autonomous scheduler acceptance."""

import asyncio
from datetime import timedelta
from threading import Event

import pytest
import requests
from sqlalchemy import delete
from sqlalchemy.exc import OperationalError
from test_live_pipeline_acceptance import NOW, _sample_plan
from test_permission_candidate_selection import _seed_open_day
from test_production_semantic_gate import _pipeline
from test_recovery_activation_fences import replace_or_reactivate
from test_s3_frozen_startup_recovery import _bar, _running
from test_s3_stock_recovery_owner import _seed_many

from trade_plan_monitor.runtime.reconciliation import RecoveryDisposition
from trade_plan_monitor.runtime.recovery import RecoveryAdmissionChangedError
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.state.models import TradingCalendar


def _prepare(tmp_path, pipeline, sdk):
    _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
    pipeline._calendar[NOW.date()] = True
    sdk.stock_symbols = (_sample_plan().symbol,)
    pipeline._permission_market_window = lambda now, horizon: ()


def test_one_unit_fetches_and_commits_exact_prefix(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            await pipeline.run_stock_recovery_unit()
            assert [name for name, _ in sdk.calls] == ["rt_min_daily"]
            (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
            assert snapshot.disposition is RecoveryDisposition.READY
            with work() as transaction:
                rows = transaction.history.list_minutes(
                    _sample_plan().symbol,
                    start=NOW.replace(hour=9, minute=31, second=0),
                    end=NOW.replace(second=0),
                )
            assert len(rows) == 30
            await pipeline.run_stock_recovery_unit()
            assert len(sdk.calls) == 1

    asyncio.run(scenario())


def test_committed_complete_prefix_never_fetches(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            with work() as transaction:
                transaction.history.upsert_minutes(
                    tuple(_bar(capture, end) for end in capture.required_ends)
                )
                transaction.commit()
            await pipeline.run_stock_recovery_unit()
            assert not sdk.calls
            assert (
                pipeline._stock_recovery_schedule.snapshot()[0].disposition
                is RecoveryDisposition.READY
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("count", [0, 7])
def test_empty_partial_is_fixed_completion_retry_not_immediate_pending(
    tmp_path, monkeypatch, count
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            original = sdk._stock_minutes
            monkeypatch.setattr(
                sdk, "_stock_minutes", lambda name, kwargs: original(name, kwargs).iloc[:count]
            )
            await pipeline.run_stock_recovery_unit()
            (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
            assert snapshot.disposition is RecoveryDisposition.RETRY
            assert snapshot.next_retry_at == NOW + timedelta(seconds=30)
            assert len(sdk.calls) == 1
            with work() as transaction:
                rows = transaction.history.list_minutes(
                    _sample_plan().symbol,
                    start=NOW.replace(hour=9, minute=31, second=0),
                    end=NOW.replace(second=0),
                )
            assert len(rows) == count
            pipeline._clock.current += timedelta(seconds=29)
            await pipeline.run_stock_recovery_unit()
            assert len(sdk.calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("offset_us,expected_calls", [(-1, 1), (0, 0), (1, 0)])
def test_maintenance_reserve_exact_boundary(tmp_path, monkeypatch, offset_us, expected_calls):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            due = NOW + timedelta(seconds=31.25)
            pipeline._clock.current = NOW + timedelta(microseconds=offset_us)
            pipeline._permission_market_window = lambda now, horizon: ((due, True),)
            await pipeline.run_stock_recovery_unit()
            assert len(sdk.calls) == expected_calls
            if not expected_calls:
                (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
                assert snapshot.next_retry_at == due + timedelta(microseconds=1)
                assert not pipeline._controller.is_permission_blocked(
                    TushareOperation.CURRENT_DAY_MINUTES,
                )

    asyncio.run(scenario())


def test_wrapper_preparation_crosses_reserve_and_actual_sdk_is_zero(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            due = NOW + timedelta(seconds=40)
            pipeline._permission_market_window = lambda now, horizon: ((due, True),)
            client = pipeline.provider._client
            original = client._current
            wrappers = []

            def crossing():
                valid = original()
                wrappers.append(True)
                pipeline._clock.current = NOW + timedelta(seconds=10)
                return valid

            monkeypatch.setattr(client, "_current", crossing)
            await pipeline.run_stock_recovery_unit()
            assert wrappers == [True]
            assert not sdk.calls
            (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
            assert snapshot.next_retry_at == due + timedelta(microseconds=1)
            with work() as transaction:
                assert transaction.history.get_latest_quote(_sample_plan().symbol) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("code", ["ERROR", "QUEUE_FULL", "CLOSED", "INVALID_RESPONSE"])
@pytest.mark.parametrize("retarget", [False, True])
def test_fatal_controller_error_preserves_original_identity_attempts_and_cause(
    tmp_path,
    monkeypatch,
    code,
    retarget,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            cause = ValueError("offline cause must not be rewritten")
            failure = RequestControlError(
                RequestControlErrorCode(code),
                TushareOperation.CURRENT_DAY_MINUTES,
                attempts=2,
            )
            failure.__cause__ = cause

            async def fail(self, *args, **kwargs):
                if retarget:
                    pipeline._clock.current += timedelta(days=1)
                raise failure

            monkeypatch.setattr(type(pipeline._controller), "execute", fail)
            with pytest.raises(RequestControlError) as caught:
                await pipeline.run_stock_recovery_unit()
            assert caught.value is failure
            assert caught.value.attempts == 2 and caught.value.__cause__ is cause
            assert not pipeline._stock_recovery_schedule.snapshot()[0].in_progress
            assert pipeline.next_stock_recovery_at() is None
            assert not sdk.calls

    asyncio.run(scenario())


@pytest.mark.parametrize("code", ["RATE_LIMITED", "TRANSIENT", "TIMEOUT"])
@pytest.mark.parametrize("retarget", [False, True])
def test_retryable_error_keeps_later_provider_floor_even_with_retarget(
    tmp_path,
    monkeypatch,
    code,
    retarget,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            completed = NOW + (timedelta(days=1) if retarget else timedelta(seconds=2))
            retry_at = completed + timedelta(minutes=5)
            failure = RequestControlError(
                RequestControlErrorCode(code),
                TushareOperation.CURRENT_DAY_MINUTES,
                attempts=1,
                next_retry_at=retry_at,
            )

            async def fail(self, *args, **kwargs):
                pipeline._clock.current = completed
                raise failure

            monkeypatch.setattr(type(pipeline._controller), "execute", fail)
            result = await pipeline.run_stock_recovery_unit()
            assert result.request_error is failure
            assert result.retarget_required is retarget
            (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
            assert snapshot.disposition is RecoveryDisposition.RETRY
            assert snapshot.next_retry_at == retry_at
            assert not sdk.calls

    asyncio.run(scenario())


def test_local_malformed_result_raises_without_fabricating_request_attempts(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            monkeypatch.setattr(type(pipeline.provider), "current_day_minutes", lambda *a, **k: ())
            with pytest.raises(RuntimeError, match="INVALID_RESPONSE") as caught:
                await pipeline.run_stock_recovery_unit()
            assert not isinstance(caught.value, RequestControlError)
            assert not sdk.calls

    asyncio.run(scenario())


def test_ten_scope_rotation_failure_does_not_starve_healthy_siblings(tmp_path, monkeypatch):
    plans = _seed_many(tmp_path, 10)

    async def scenario():
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            original = sdk._stock_minutes
            physical_starts = []

            def fail_first(name, kwargs):
                physical_starts.append(pipeline._controller._monotonic())
                if kwargs["ts_code"] == plans[0].symbol:
                    raise requests.exceptions.ConnectionError("offline temporary failure")
                return original(name, kwargs)

            monkeypatch.setattr(sdk, "_stock_minutes", fail_first)
            for count in range(10):
                await pipeline.run_stock_recovery_unit()
                assert len(sdk.calls) == count + 1
            assert [kwargs["ts_code"] for _, kwargs in sdk.calls] == [p.symbol for p in plans]
            snapshots = pipeline._stock_recovery_schedule.snapshot()
            assert snapshots[0].disposition is RecoveryDisposition.RETRY
            assert all(item.disposition is RecoveryDisposition.READY for item in snapshots[1:])
            assert all(
                b - a >= 1.25
                for a, b in zip(
                    physical_starts,
                    physical_starts[1:],
                    strict=False,
                )
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["activation", "target"])
def test_fresh_capture_cannot_transfer_old_ticket_to_replacement_identity(
    tmp_path,
    monkeypatch,
    change,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            original = pipeline._capture_recovery_scope

            def changed(symbol):
                if change == "activation":
                    replace_or_reactivate(work, pipeline, _sample_plan())
                else:
                    pipeline._clock.current += timedelta(minutes=1)
                return original(symbol)

            monkeypatch.setattr(pipeline, "_capture_recovery_scope", changed)
            await pipeline.run_stock_recovery_unit()
            assert not sdk.calls
            assert not pipeline._stock_recovery_schedule.snapshot()[0].in_progress
            assert pipeline.next_stock_recovery_at() == pipeline._clock.now() + timedelta(
                seconds=30
            )
            with work() as transaction:
                assert transaction.history.get_latest_quote(_sample_plan().symbol) is None

    asyncio.run(scenario())


def test_reactivation_during_real_sdk_wait_rejects_old_rows_then_fresh_scope_recovers(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            entered, release = Event(), Event()
            original = sdk._stock_minutes

            def wait(name, kwargs):
                entered.set()
                assert release.wait(5)
                return original(name, kwargs)

            monkeypatch.setattr(sdk, "_stock_minutes", wait)
            task = asyncio.create_task(pipeline.run_stock_recovery_unit())
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                replacement = replace_or_reactivate(work, pipeline, _sample_plan())
                release.set()
                result = await task
                assert result.retarget_required
                with work() as transaction:
                    assert transaction.history.get_latest_quote(_sample_plan().symbol) is None
                    assert (
                        transaction.plans.get_active(_sample_plan().symbol).revision
                        == replacement.revision
                    )
                pipeline._clock.current += timedelta(seconds=30)
                await pipeline.run_stock_recovery_unit()
                assert len(sdk.calls) == 2
                assert (
                    pipeline._stock_recovery_schedule.snapshot()[0].disposition
                    is RecoveryDisposition.READY
                )
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["storage", "program", "protocol"])
def test_persistence_exceptions_propagate_original_object(tmp_path, monkeypatch, kind):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            failure = (
                OperationalError("offline", {}, RuntimeError("original storage cause"))
                if kind == "storage"
                else RuntimeError("program sentinel")
                if kind == "program"
                else ValueError("protocol sentinel")
            )

            def fail(*args, **kwargs):
                raise failure

            monkeypatch.setattr(pipeline, "_persist_recovery_capture", fail)
            with pytest.raises(type(failure)) as caught:
                await pipeline.run_stock_recovery_unit()
            assert caught.value is failure
            assert pipeline.next_stock_recovery_at() is None
            with work() as transaction:
                assert transaction.history.get_latest_quote(_sample_plan().symbol) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("at_wrapper", [True, False])
@pytest.mark.parametrize("late_failure", [False, True])
def test_unit_cancellation_keeps_ticket_token_and_slot_until_physical_drain(
    tmp_path,
    monkeypatch,
    at_wrapper,
    late_failure,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            entered, release = Event(), Event()
            client = pipeline.provider._client
            validation, original = client._current, sdk._stock_minutes

            def pause():
                entered.set()
                assert release.wait(5)

            def wrapper():
                valid = validation()
                pause()
                return valid

            def endpoint(name, kwargs):
                pause()
                if late_failure:
                    raise RuntimeError("offline permission denied after cancellation")
                return original(name, kwargs)

            if at_wrapper:
                monkeypatch.setattr(client, "_current", wrapper)
            else:
                monkeypatch.setattr(sdk, "_stock_minutes", endpoint)
            task = asyncio.create_task(pipeline.run_stock_recovery_unit())
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                (token,) = pipeline._active_recovery_attempts
                task.cancel()
                await asyncio.sleep(0)
                assert token.is_set() and not task.done()
                assert pipeline._controller.active_count == 1
                assert pipeline._stock_recovery_schedule.snapshot()[0].in_progress
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert len(sdk.calls) == (0 if at_wrapper else 1)
                assert not pipeline._active_recovery_attempts
                assert pipeline._controller.active_count == 0
                assert not pipeline._stock_recovery_schedule.snapshot()[0].in_progress
                assert pipeline.next_stock_recovery_at() is None
                assert pipeline._controller.is_permission_blocked(
                    TushareOperation.CURRENT_DAY_MINUTES,
                ) is (late_failure and not at_wrapper)
                with work() as transaction:
                    assert transaction.history.get_latest_quote(_sample_plan().symbol) is None
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_same_minute_clock_rewind_between_ticket_and_fresh_capture_is_not_erased(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            original = pipeline._capture_recovery_scope

            def rewind(symbol):
                pipeline._clock.current -= timedelta(seconds=1)
                return original(symbol)

            monkeypatch.setattr(pipeline, "_capture_recovery_scope", rewind)
            await pipeline.run_stock_recovery_unit()
            assert not sdk.calls
            assert (
                pipeline._stock_recovery_schedule.snapshot()[0].disposition
                is RecoveryDisposition.RETRY
            )

    asyncio.run(scenario())


def test_obsolete_owner_entry_terminates_without_new_capture_or_request(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            pipeline._generation_current = lambda: False
            monkeypatch.setattr(pipeline, "_work", lambda: pytest.fail("retired owner queried SQL"))
            assert await pipeline.run_stock_recovery_unit() is None
            assert pipeline.next_stock_recovery_at() is None
            assert not sdk.calls

    asyncio.run(scenario())


@pytest.mark.parametrize("at_wrapper", [True, False])
def test_stop_retires_owner_only_after_real_worker_drain_without_new_retry(
    tmp_path,
    monkeypatch,
    at_wrapper,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            entered, release = Event(), Event()
            client = pipeline.provider._client
            validation, original = client._current, sdk._stock_minutes

            def pause():
                entered.set()
                assert release.wait(5)

            def wrapper():
                valid = validation()
                pause()
                return valid

            def endpoint(name, kwargs):
                pause()
                return original(name, kwargs)

            if at_wrapper:
                monkeypatch.setattr(client, "_current", wrapper)
            else:
                monkeypatch.setattr(sdk, "_stock_minutes", endpoint)
            task = asyncio.create_task(pipeline.run_stock_recovery_unit())
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                pipeline._generation_current = lambda: False
                pipeline.revoke_active_recovery_attempts()
                assert all(token.is_set() for token in pipeline._active_recovery_attempts)
                assert not task.done() and pipeline._controller.active_count == 1
                release.set()
                assert await task is None
                (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
                assert not snapshot.in_progress and snapshot.next_retry_at is None
                assert snapshot.disposition is not RecoveryDisposition.READY
                assert pipeline.next_stock_recovery_at() is None
                assert len(sdk.calls) == (0 if at_wrapper else 1)
                with work() as transaction:
                    assert transaction.history.get_latest_quote(_sample_plan().symbol) is None
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("at_wrapper", [True, False])
def test_real_composition_shutdown_sets_unit_token_before_cancel_and_keeps_database(
    tmp_path,
    monkeypatch,
    at_wrapper,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            lifecycle = run.composition._runtime
            state = lifecycle._liveness_owner
            pipeline = state._pipeline
            client = pipeline.provider._client
            sdk = client._client
            initial_calls = len(sdk.calls)
            validation, original = client._current, sdk._stock_minutes
            entered, release = Event(), Event()

            def pause():
                entered.set()
                assert release.wait(5)

            def wrapper():
                valid = validation()
                pause()
                return valid

            def endpoint(name, kwargs):
                pause()
                return original(name, kwargs)

            if at_wrapper:
                monkeypatch.setattr(client, "_current", wrapper)
            else:
                monkeypatch.setattr(sdk, "_stock_minutes", endpoint)
            task = asyncio.create_task(pipeline.run_stock_recovery_unit())
            lifecycle._work_tasks.add(task)
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                (token,) = pipeline._active_recovery_attempts
                lifecycle.begin_shutdown()
                assert token.is_set() and task.cancelling() == 0 and not task.done()
                assert pipeline._controller.active_count == 1
                assert state._database_status.value == "READY" and lifecycle._database_opened
                assert pipeline._stock_recovery_schedule.snapshot()[0].in_progress
                release.set()
                assert await task is None
                assert len(sdk.calls) - initial_calls == (0 if at_wrapper else 1)
                assert run.state()["minutes"] == ()
                assert pipeline.next_stock_recovery_at() is None
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
                lifecycle._work_tasks.discard(task)

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["event", "epoch", "source", "configuration", "semantics"])
def test_retirement_never_hides_authority_failure(tmp_path, monkeypatch, mutation):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            pipeline._synchronize_stock_recovery()
            pipeline._generation_current = lambda: False
            if mutation == "event":
                pipeline._recovery_authority_revoked.set()
            elif mutation == "epoch":
                pipeline._recovery_authority_epoch = lambda: 1
            elif mutation == "source":
                pipeline.provider._client = object()
            elif mutation == "configuration":
                pipeline._configuration_current = lambda: False
            else:
                pipeline._stock_certification_current = lambda: False
            with pytest.raises(RecoveryAdmissionChangedError):
                await pipeline.run_stock_recovery_unit()
            assert not sdk.calls
            assert pipeline.next_stock_recovery_at() is None

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["storage", "controller", "retry"])
def test_retirement_does_not_hide_recorded_fault_or_retry_floor(tmp_path, monkeypatch, kind):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            if kind == "storage":
                failure = OperationalError("offline", {}, ValueError("cause"))

                def fail(*args, **kwargs):
                    pipeline._generation_current = lambda: False
                    raise failure

                monkeypatch.setattr(pipeline, "_persist_recovery_capture", fail)
            else:
                failure = RequestControlError(
                    RequestControlErrorCode.TRANSIENT
                    if kind == "retry"
                    else RequestControlErrorCode.ERROR,
                    TushareOperation.CURRENT_DAY_MINUTES,
                    attempts=1,
                    next_retry_at=NOW + timedelta(minutes=5) if kind == "retry" else None,
                )

                async def fail(self, *args, **kwargs):
                    pipeline._generation_current = lambda: False
                    raise failure

                monkeypatch.setattr(type(pipeline._controller), "execute", fail)
            if kind == "retry":
                assert await pipeline.run_stock_recovery_unit() is None
                assert (
                    pipeline._stock_recovery_schedule.snapshot()[0].next_retry_at
                    == failure.next_retry_at
                )
            else:
                with pytest.raises(type(failure)) as caught:
                    await pipeline.run_stock_recovery_unit()
                assert caught.value is failure
            assert pipeline.next_stock_recovery_at() is None
            assert not pipeline._stock_recovery_schedule.snapshot()[0].in_progress

    asyncio.run(scenario())


def test_actual_429_shares_controller_cooldown_with_sibling_and_index(tmp_path, monkeypatch):
    _seed_many(tmp_path, 2)

    async def scenario():
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            response = requests.Response()
            response.status_code = 429

            def limited(name, kwargs):
                raise requests.exceptions.HTTPError(response=response)

            monkeypatch.setattr(sdk, "_stock_minutes", limited)
            await pipeline.run_stock_recovery_unit()
            assert pipeline._controller.cooldown_until > NOW
            await pipeline.run_stock_recovery_unit()
            assert len(sdk.calls) == 1
            with pytest.raises(RequestControlError) as caught:
                await pipeline._controller.execute(
                    TushareOperation.INDEX_DAILY,
                    lambda: pytest.fail("shared cooldown was bypassed"),
                    work_key="index-cooldown-control",
                )
            assert caught.value.code is RequestControlErrorCode.RATE_LIMITED
            assert all(
                item.next_retry_at >= pipeline._controller.cooldown_until
                for item in pipeline._stock_recovery_schedule.snapshot()
            )

    asyncio.run(scenario())


def test_actual_permission_block_remains_frozen_and_business_never_probes(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)

            def denied(name, kwargs):
                raise RuntimeError("offline permission denied")

            monkeypatch.setattr(sdk, "_stock_minutes", denied)
            monkeypatch.setattr(
                type(pipeline._controller),
                "recheck_permission",
                lambda *a, **k: pytest.fail("business owner probed permission"),
            )
            result = await pipeline.run_stock_recovery_unit()
            assert result.error_code.value == "BLOCKED_PERMISSION"
            (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
            assert snapshot.disposition is RecoveryDisposition.BLOCKED
            pipeline._clock.current += timedelta(minutes=6)
            await pipeline.run_stock_recovery_unit()
            assert pipeline._stock_recovery_schedule.snapshot() == (snapshot,)
            assert len(sdk.calls) == 1

    asyncio.run(scenario())


def test_unknown_persisted_calendar_has_zero_fetch_despite_old_memory_cache(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            with work() as transaction:
                transaction._session.execute(delete(TradingCalendar))
                transaction.commit()
            assert pipeline._calendar[NOW.date()] is True
            await pipeline.run_stock_recovery_unit()
            assert not sdk.calls
            assert pipeline.next_stock_recovery_at() == NOW + timedelta(seconds=30)

    asyncio.run(scenario())


@pytest.mark.parametrize("elapsed_us,expected_calls", [(15_000_000, 1), (15_000_001, 0)])
def test_wrapper_rechecks_frozen_latest_start_inclusively(
    tmp_path,
    monkeypatch,
    elapsed_us,
    expected_calls,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            client = pipeline.provider._client
            original = client._current

            def slow():
                valid = original()
                pipeline._clock.current = NOW + timedelta(microseconds=elapsed_us)
                return valid

            monkeypatch.setattr(client, "_current", slow)
            await pipeline.run_stock_recovery_unit()
            assert len(sdk.calls) == expected_calls

    asyncio.run(scenario())


def test_real_controller_queue_rechecks_market_reserve_before_wrapper(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            due = NOW + timedelta(seconds=40)
            pipeline._permission_market_window = lambda now, horizon: ((due, True),)
            entered, release = Event(), Event()
            original_execute = type(pipeline._controller).execute
            competitors = []

            def competitor():
                entered.set()
                assert release.wait(5)

            async def interleave(self, operation, call, **kwargs):
                if operation is TushareOperation.CURRENT_DAY_MINUTES:
                    competitors.append(
                        asyncio.create_task(
                            original_execute(
                                self,
                                TushareOperation.INDEX_DAILY,
                                competitor,
                                work_key="queue-owner",
                            )
                        )
                    )
                    assert await asyncio.to_thread(entered.wait, 2)
                return await original_execute(self, operation, call, **kwargs)

            monkeypatch.setattr(type(pipeline._controller), "execute", interleave)
            task = asyncio.create_task(pipeline.run_stock_recovery_unit())
            try:
                async with asyncio.timeout(3):
                    while pipeline._controller.waiting_count == 0:
                        await asyncio.sleep(0)
                pipeline._clock.current = NOW + timedelta(seconds=10)
                release.set()
                await task
                await asyncio.gather(*competitors)
                assert not sdk.calls
                assert pipeline._stock_recovery_schedule.snapshot()[0].next_retry_at == (
                    due + timedelta(microseconds=1)
                )
                assert pipeline._controller.cooldown_until is None
            finally:
                release.set()
                await asyncio.gather(task, *competitors, return_exceptions=True)

    asyncio.run(scenario())


def test_partial_committed_facts_survive_owner_restart_and_only_missing_rows_are_added(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            original = sdk._stock_minutes
            monkeypatch.setattr(sdk, "_stock_minutes", lambda name, kw: original(name, kw).iloc[:7])
            await pipeline.run_stock_recovery_unit()
            with work() as transaction:
                before = transaction.history.list_minutes(
                    _sample_plan().symbol,
                    start=NOW.replace(hour=9, minute=31, second=0),
                    end=NOW.replace(second=0),
                )
            assert len(before) == 7
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, work):
            _prepare(tmp_path, pipeline, sdk)
            await pipeline.run_stock_recovery_unit()
            with work() as transaction:
                after = transaction.history.list_minutes(
                    _sample_plan().symbol,
                    start=NOW.replace(hour=9, minute=31, second=0),
                    end=NOW.replace(second=0),
                )
            assert len(after) == 30 and after[:7] == before
            assert len(sdk.calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("failed", [False, True])
def test_late_completion_keeps_retry_floor_after_latest_target_synchronizes(
    tmp_path,
    monkeypatch,
    failed,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _prepare(tmp_path, pipeline, sdk)
            entered, release = Event(), Event()
            original = sdk._stock_minutes

            def delayed(name, kwargs):
                entered.set()
                assert release.wait(5)
                if failed:
                    raise requests.exceptions.Timeout("offline late timeout")
                return original(name, kwargs).iloc[:0]

            monkeypatch.setattr(sdk, "_stock_minutes", delayed)
            task = asyncio.create_task(pipeline.run_stock_recovery_unit())
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                original_requirement = pipeline._stock_recovery_schedule.snapshot()[0].requirement
                pipeline._clock.current += timedelta(minutes=1)
                pipeline._synchronize_stock_recovery()
                assert (
                    pipeline._stock_recovery_schedule.snapshot()[0].requirement
                    != original_requirement
                )
                release.set()
                result = await task
                (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
                assert snapshot.disposition is RecoveryDisposition.RETRY
                assert snapshot.next_retry_at >= pipeline._clock.now() + timedelta(seconds=30)
                if failed:
                    assert snapshot.next_retry_at >= result.next_retry_at
                assert not snapshot.in_progress and len(sdk.calls) == 1
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_unknown_scope_retry_expiring_between_sync_and_claim_stays_zero_fetch(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            synchronize = pipeline._synchronize_stock_recovery

            def delayed_observation():
                synchronize()
                pipeline._clock.current += timedelta(seconds=31)

            monkeypatch.setattr(pipeline, "_synchronize_stock_recovery", delayed_observation)
            await pipeline.run_stock_recovery_unit()
            assert not sdk.calls
            assert not pipeline._stock_recovery_schedule.snapshot()[0].in_progress

    asyncio.run(scenario())
