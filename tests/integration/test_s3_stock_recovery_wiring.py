"""F3-C startup accounting and the existing scheduler's stock maintenance wiring."""

import asyncio
from datetime import timedelta

import pytest
import requests
from test_live_pipeline_acceptance import NOW, _sample_plan
from test_permission_candidate_selection import _block, _seed_open_day
from test_production_certification_gate import _composition
from test_production_semantic_gate import _deadline, _pipeline
from test_runtime_lifecycle import _service
from test_s3_frozen_startup_recovery import _bar, _running
from test_s3_startup_outcome_association import _DeadlineClock
from test_s3_stock_recovery_owner import _seed_many

from trade_plan_monitor.runtime.reconciliation import RecoveryDisposition
from trade_plan_monitor.runtime.recovery import RecoveryAdmissionChangedError
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    TushareOperation,
)
from trade_plan_monitor.runtime.scheduler import (
    DeadlineKind,
    MarketDeadline,
    MarketSessionScheduler,
)


def test_startup_acquires_at_most_one_of_ten_stock_scopes(tmp_path, monkeypatch):
    async def scenario():
        plans = _seed_many(tmp_path, 10)
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, _work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            sdk.stock_symbols = tuple(plan.symbol for plan in plans)
            await pipeline.recover_startup(NOW.date())
            assert len([call for call in sdk.calls if call[0] == "rt_min_daily"]) == 1
            snapshots = pipeline._stock_recovery_schedule.snapshot()
            assert len(snapshots) == 10
            assert sum(item.disposition is RecoveryDisposition.READY for item in snapshots) == 1
            assert pipeline.next_stock_recovery_at() is not None

    asyncio.run(scenario())


def test_startup_date_rollover_during_close_recovery_skips_other_day_before_fetch(
    tmp_path, monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            tomorrow = NOW + timedelta(days=1)
            for trade_date in (NOW.date(), tomorrow.date()):
                _seed_open_day(tmp_path / "monitor.sqlite3", trade_date)
            sdk.stock_symbols = (_sample_plan().symbol,)
            original = pipeline._recover_pending_close_batches

            async def crossing(trade_date):
                await original(trade_date)
                pipeline._clock.current = tomorrow

            monkeypatch.setattr(pipeline, "_recover_pending_close_batches", crossing)
            await pipeline.recover_startup(NOW.date())
            assert pipeline._clock.now() == tomorrow
            assert not sdk.calls
            with work() as transaction:
                assert transaction.history.get_latest_quote(_sample_plan().symbol) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("count", [0, 7])
def test_startup_incomplete_completion_floor_survives_resync_and_repeated_startup(
    tmp_path, monkeypatch, count,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            sdk.stock_symbols = (_sample_plan().symbol,)
            original = sdk._stock_minutes
            completed_at = NOW + timedelta(seconds=40)

            def partial(name, kwargs):
                pipeline._clock.current = completed_at
                return original(name, kwargs).iloc[:count]

            monkeypatch.setattr(sdk, "_stock_minutes", partial)
            await pipeline.recover_startup(NOW.date())
            (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
            assert snapshot.disposition is RecoveryDisposition.RETRY
            assert snapshot.next_retry_at == completed_at + timedelta(seconds=30)
            with work() as transaction:
                rows = transaction.history.list_minutes(
                    _sample_plan().symbol, start=NOW.replace(hour=9, minute=31, second=0),
                    end=completed_at,
                )
            assert len(rows) == count
            pipeline._clock.current = NOW.replace(minute=1, second=0)
            pipeline._synchronize_stock_recovery()
            await pipeline.recover_startup(NOW.date())
            (retargeted,) = pipeline._stock_recovery_schedule.snapshot()
            assert retargeted.requirement != snapshot.requirement
            assert retargeted.next_retry_at == snapshot.next_retry_at
            assert len([call for call in sdk.calls if call[0] == "rt_min_daily"]) == 1

    asyncio.run(scenario())


def test_index_only_market_still_runs_and_accidental_stock_unit_is_inert(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True,
            stock_certification=False, persisted_calendar=True,
        )
        try:
            assert (await composition.start()).status.value == "RUNNING"
            state = composition._runtime._run_deadline.__self__
            assert state._pipeline._stock_semantics is None
            assert await state.run_deadline(_deadline()) == ()
            assert sdk.calls and all(
                name in {"idx_mins", "rt_idx_min_daily", "index_daily"} for name, _ in sdk.calls
            )
            before = tuple(sdk.calls)
            assert state.next_stock_recovery_at() is None
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.STOCK_RECOVERY, trade_date=NOW.date(), due_at=NOW,
            ))
            assert state.next_stock_recovery_at() is None
            assert tuple(sdk.calls) == before
        finally:
            await composition.stop()

    asyncio.run(scenario())


def test_stock_maintenance_scheduler_uses_cached_due_and_market_wins_tie():
    from test_live_pipeline_acceptance import ControlledClock

    due = NOW.replace(minute=1, second=12)
    clock = ControlledClock(due)
    scheduler = MarketSessionScheduler(
        clock=clock, is_open_on=lambda day: day == NOW.date(),
        next_stock_recovery_at=lambda: due,
    )
    first = scheduler.next_deadline()
    assert first.kind is DeadlineKind.REALTIME_MINUTE and first.due_at == due
    following = scheduler.next_deadline(after=due)
    assert following.kind is DeadlineKind.STOCK_RECOVERY
    assert following.due_at == due + timedelta(microseconds=1)


@pytest.mark.parametrize("complete", [False, True])
def test_preblocked_startup_missing_is_failure_but_complete_prefix_needs_no_fetch(
    tmp_path, monkeypatch, complete,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            if complete:
                capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
                with work() as transaction:
                    transaction.history.upsert_minutes(tuple(
                        _bar(capture, end) for end in capture.required_ends
                    ))
                    transaction.commit()
            await _block(pipeline._controller, TushareOperation.CURRENT_DAY_MINUTES)
            if complete:
                await pipeline.recover_startup(NOW.date())
            else:
                for _ in range(2):
                    with pytest.raises(RuntimeError, match="startup recovery failed"):
                        await pipeline.recover_startup(NOW.date())
            assert not sdk.calls

    asyncio.run(scenario())


def test_provider_retry_repeated_startup_keeps_failure_category_and_floor(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            sdk.stock_symbols = (_sample_plan().symbol,)

            def fail(_name, _kwargs):
                raise requests.ConnectionError("offline transient startup")

            monkeypatch.setattr(sdk, "_stock_minutes", fail)
            with pytest.raises(RequestControlError) as first:
                await pipeline.recover_startup(NOW.date())
            assert first.value.code is RequestControlErrorCode.TRANSIENT
            (snapshot,) = pipeline._stock_recovery_schedule.snapshot()
            assert snapshot.disposition is RecoveryDisposition.RETRY
            assert snapshot.next_retry_at >= NOW + timedelta(seconds=30)
            before = tuple(sdk.calls)
            with pytest.raises(RequestControlError) as repeated:
                await pipeline.recover_startup(NOW.date())
            assert repeated.value.code is first.value.code
            assert repeated.value.attempts == 0
            assert tuple(sdk.calls) == before
            assert pipeline._stock_recovery_schedule.snapshot()[0].next_retry_at == (
                snapshot.next_retry_at
            )

    asyncio.run(scenario())


def test_sibling_success_cannot_erase_startup_failure_but_own_legal_partial_can(
    tmp_path, monkeypatch,
):
    async def scenario():
        plans = _seed_many(tmp_path, 2)
        with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, _work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            sdk.stock_symbols = tuple(plan.symbol for plan in plans)
            original = sdk._stock_minutes
            fail_first = [True]

            def response(name, kwargs):
                if kwargs["ts_code"] == plans[0].symbol:
                    if fail_first[0]:
                        raise requests.ConnectionError("offline first scope")
                    return original(name, kwargs).iloc[:7]
                return original(name, kwargs)

            monkeypatch.setattr(sdk, "_stock_minutes", response)
            with pytest.raises(RequestControlError):
                await pipeline.recover_startup(NOW.date())
            assert len(sdk.calls) == 1
            first_snapshot = pipeline._stock_recovery_schedule.snapshot()[0]
            with pytest.raises(RequestControlError) as sibling:
                await pipeline.recover_startup(NOW.date())
            assert sibling.value.code is RequestControlErrorCode.TRANSIENT
            assert [kwargs["ts_code"] for _, kwargs in sdk.calls] == [
                plans[0].symbol, plans[1].symbol,
            ]
            fail_first[0] = False
            pipeline._clock.current = first_snapshot.next_retry_at
            await pipeline.recover_startup(NOW.date())
            first = pipeline._stock_recovery_schedule.snapshot()[0]
            assert first.disposition is RecoveryDisposition.RETRY
            assert first.next_retry_at >= pipeline._clock.now() + timedelta(seconds=30)
            before = tuple(sdk.calls)
            await pipeline.recover_startup(NOW.date())
            assert tuple(sdk.calls) == before

    asyncio.run(scenario())


def test_complete_prefix_does_not_clear_authoritative_block_for_a_growing_target(
    tmp_path, monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            await _block(pipeline._controller, TushareOperation.CURRENT_DAY_MINUTES)
            with pytest.raises(RuntimeError, match="startup recovery failed"):
                await pipeline.recover_startup(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            with work() as transaction:
                transaction.history.upsert_minutes(tuple(
                    _bar(capture, end) for end in capture.required_ends
                ))
                transaction.commit()
            await pipeline.recover_startup(NOW.date())
            assert pipeline._controller.is_permission_blocked(TushareOperation.CURRENT_DAY_MINUTES)
            pipeline._clock.current = NOW.replace(minute=1, second=15)
            with pytest.raises(RuntimeError, match="startup recovery failed"):
                await pipeline.recover_startup(NOW.date())
            assert not sdk.calls

    asyncio.run(scenario())


@pytest.mark.parametrize("guard", ["capture", "response"])
def test_startup_guard_invalidation_is_failure_without_provider_error_evidence(
    tmp_path, monkeypatch, guard,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            sdk.stock_symbols = (_sample_plan().symbol,)
            if guard == "capture":
                def invalid(_symbol):
                    raise RecoveryAdmissionChangedError("local original capture expired")
                monkeypatch.setattr(pipeline, "_capture_recovery_scope", invalid)
            else:
                original = sdk._stock_minutes

                def reversed_clock(name, kwargs):
                    rows = original(name, kwargs)
                    pipeline._clock.current = NOW - timedelta(seconds=1)
                    return rows

                monkeypatch.setattr(sdk, "_stock_minutes", reversed_clock)
            with pytest.raises(RuntimeError, match="startup recovery failed"):
                await pipeline.recover_startup(NOW.date())
            assert pipeline._stock_recovery_failures == {}
            assert not pipeline._controller.is_permission_blocked(
                TushareOperation.CURRENT_DAY_MINUTES,
            )
            assert len(sdk.calls) == (0 if guard == "capture" else 1)
            assert not pipeline._stock_recovery_schedule.snapshot()[0].in_progress

    asyncio.run(scenario())


@pytest.mark.parametrize("code", ["ERROR", "QUEUE_FULL", "CLOSED", "INVALID_RESPONSE"])
@pytest.mark.parametrize("concurrent_complete", [False, True])
def test_startup_retains_original_failure_policy_for_fatal_provider_results(
    tmp_path, monkeypatch, code, concurrent_complete,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            failure = RequestControlError(
                RequestControlErrorCode(code), TushareOperation.CURRENT_DAY_MINUTES, attempts=0,
            )

            async def fail(*_args, **_kwargs):
                if concurrent_complete:
                    capture = pipeline._stock_recovery_demands[
                        f"stock-prefix:{_sample_plan().symbol}"
                    ].capture

                    def commit_complete():
                        with work() as transaction:
                            transaction.history.upsert_minutes(tuple(
                                _bar(capture, end) for end in capture.required_ends
                            ))
                            transaction.commit()

                    await asyncio.to_thread(commit_complete)
                raise failure

            monkeypatch.setattr(type(pipeline._controller), "execute", fail)
            with pytest.raises(RuntimeError, match="startup recovery failed") as caught:
                await pipeline.recover_startup(NOW.date())
            assert caught.value is not failure
            assert not sdk.calls
            (evidence,) = pipeline._stock_recovery_failures.values()
            assert evidence.error_code.value == code
            assert not hasattr(evidence, "request_error")
            assert not pipeline._stock_recovery_schedule.snapshot()[0].in_progress
            if concurrent_complete:
                assert not next(iter(pipeline._stock_recovery_demands.values())).missing_ends

    asyncio.run(scenario())


def test_market_completion_does_not_call_legacy_multi_symbol_gap_repair(tmp_path, monkeypatch):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            runtime = run.composition._runtime
            state = runtime._run_deadline.__self__
            pipeline = state._pipeline
            calls = []
            original = pipeline.recovery.repair_detected_gaps

            async def observed(**kwargs):
                calls.append(kwargs)
                return await original(**kwargs)

            monkeypatch.setattr(pipeline.recovery, "repair_detected_gaps", observed)
            runtime._clock.current = NOW.replace(minute=5, second=12)
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=NOW.date(),
                due_at=runtime._clock.now(), bar_end=runtime._clock.now().replace(second=0),
            ))
            assert not calls
            assert pipeline._stock_recovery_schedule.snapshot()
            assert pipeline.next_stock_recovery_at() is not None

    asyncio.run(scenario())


@pytest.mark.parametrize("elapsed_minutes,expected_market", [(1, True), (3, False)])
def test_stock_maintenance_preserves_market_cursor_and_original_elapsed_review(
    elapsed_minutes, expected_market,
):
    async def scenario():
        clock = _DeadlineClock(NOW)
        market_cursor = NOW.replace(second=12)
        stock_due = NOW + timedelta(seconds=10)
        next_stock = [stock_due]
        reviews = []
        executed = []

        class RecordingScheduler(MarketSessionScheduler):
            def elapsed_market_deadlines(self, *, after, through):
                reviews.append((after, through))
                return super().elapsed_market_deadlines(after=after, through=through)

        scheduler = RecordingScheduler(
            clock=clock, is_open_on=lambda day: day == NOW.date(),
            next_stock_recovery_at=lambda: next_stock[0],
        )

        async def work(deadline):
            executed.append(deadline)
            if deadline.kind is DeadlineKind.STOCK_RECOVERY:
                assert runtime._last_deadline_at == market_cursor
                next_stock[0] = None
                clock.current = NOW.replace(minute=elapsed_minutes, second=13)

        runtime = _service(scheduler=scheduler, run_deadline=work)
        runtime._clock = clock
        runtime._last_deadline_at = market_cursor
        runner = asyncio.create_task(runtime.run())
        try:
            async with asyncio.timeout(5):
                await clock.park(failed=runner.done)
                assert clock.parked[0] == stock_due
                clock.current = stock_due
                clock.parked[1].set_result(None)
                assert await clock.park(failed=runner.done)
            assert reviews[0] == (market_cursor, NOW.replace(minute=elapsed_minutes, second=13))
            assert [item.kind for item in executed] == (
                [DeadlineKind.STOCK_RECOVERY, DeadlineKind.REALTIME_MINUTE]
                if expected_market else [DeadlineKind.STOCK_RECOVERY]
            )
            if expected_market:
                assert executed[1].bar_end == NOW.replace(minute=1, second=0)
                assert runtime._last_deadline_at == NOW.replace(minute=1, second=12)
            else:
                assert runtime._last_deadline_at == market_cursor
        finally:
            await runtime.stop()
            await runner

    asyncio.run(scenario())


def test_composition_stock_maintenance_never_dispatches_pending(tmp_path, monkeypatch):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            runtime = run.composition._runtime
            state = runtime._run_deadline.__self__
            pending_calls = []
            original = state._dispatcher.dispatch_pending

            async def observed():
                pending_calls.append(True)
                return await original()

            monkeypatch.setattr(state._dispatcher, "dispatch_pending", observed)
            await state.run_deadline(MarketDeadline(
                kind=DeadlineKind.STOCK_RECOVERY, trade_date=NOW.date(), due_at=NOW,
            ))
            assert pending_calls == []

    asyncio.run(scenario())


def test_real_scheduled_sdk_overrun_consumes_one_fresh_original_market_duty(
    tmp_path, monkeypatch,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            runtime = run.composition._runtime
            state = runtime._run_deadline.__self__
            pipeline = state._pipeline
            sdk = pipeline.provider._client._client
            clock = runtime._clock
            original_sdk = sdk._stock_minutes
            original_deadline = runtime._run_deadline
            physical_entries, executed, reviews = [], [], []
            original_review = type(runtime._scheduler).elapsed_market_deadlines

            def review(scheduler, *, after, through):
                reviews.append((after, through))
                return original_review(scheduler, after=after, through=through)

            def cross_after_entry(name, kwargs):
                if name == "rt_min_daily":
                    physical_entries.append(clock.now())
                    assert pipeline._controller.active_count == 1
                    assert pipeline._stock_recovery_schedule.snapshot()[0].in_progress
                    # The actual wrapper/final hook admitted the request before this
                    # SDK body; only its read-only response overruns the market duty.
                    clock.current = NOW.replace(minute=2, second=13)
                return original_sdk(name, kwargs)

            async def record(deadline):
                executed.append((deadline, clock.now()))
                return await original_deadline(deadline)

            monkeypatch.setattr(type(runtime._scheduler), "elapsed_market_deadlines", review)
            monkeypatch.setattr(sdk, "_stock_minutes", cross_after_entry)
            runtime._run_deadline = record
            generation = runtime.runtime_generation
            await clock.drive(
                NOW.replace(minute=2, second=13),
                failed=lambda: run.composition.health().degraded_reason == "RUNTIME_RUNNER_FAILED",
            )
            assert physical_entries == [NOW.replace(minute=1, second=12, microsecond=1)]
            target = NOW.replace(minute=2, second=0)
            elapsed = [(deadline, observed) for deadline, observed in executed
                       if deadline.kind is DeadlineKind.REALTIME_MINUTE
                       and deadline.bar_end == target]
            assert len(elapsed) == 1 and elapsed[0][1] == target + timedelta(seconds=13)
            assert (NOW.replace(minute=1, second=12), target + timedelta(seconds=13)) in reviews
            assert runtime._last_deadline_at == target + timedelta(seconds=12)
            assert runtime.runtime_generation == generation
            assert run.composition.health().degraded_reason != "RUNTIME_RUNNER_FAILED"

    asyncio.run(scenario())
