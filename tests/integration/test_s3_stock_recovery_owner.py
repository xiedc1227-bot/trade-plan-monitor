"""F3-A bounded stock recovery state, deliberately not wired to the scheduler."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import event
from test_live_pipeline_acceptance import NOW, ControlledClock, _activate_plans, _sample_plan
from test_permission_candidate_selection import _block, _seed_open_day
from test_production_semantic_gate import _pipeline, _replace_stock_contract
from test_recovery_activation_fences import replace_or_reactivate, seed_explicit
from test_s3_frozen_startup_recovery import _bar

from trade_plan_monitor.market_data.aggregation import (
    aggregate_five_minute_bar,
    expected_five_minute_ends,
    five_minute_bucket_end,
)
from trade_plan_monitor.runtime.reconciliation import RecoveryDisposition, RecoveryStepResult
from trade_plan_monitor.runtime.recovery import RecoveryAdmissionChangedError
from trade_plan_monitor.runtime.request_control import TushareOperation


def test_owner_is_dormant_until_explicit_synchronization(tmp_path, monkeypatch):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
        assert pipeline.next_stock_recovery_at() is None
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        snapshot, = pipeline._stock_recovery_schedule.snapshot()
        assert snapshot.requirement.scope_key == f"stock-prefix:{_sample_plan().symbol}"
        assert snapshot.disposition is RecoveryDisposition.PENDING
        assert pipeline.next_stock_recovery_at() == NOW
        assert not sdk.calls


def test_complete_committed_prefix_is_ready_without_fetch(tmp_path, monkeypatch):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
        with work() as transaction:
            transaction.history.upsert_minutes(tuple(
                _bar(capture, end) for end in capture.required_ends
            ))
            required = frozenset(capture.required_ends)
            aggregates = []
            for bucket in sorted({five_minute_bucket_end(end) for end in required}):
                if bucket > capture.target.completed_minute_end:
                    continue
                ends = expected_five_minute_ends(bucket)
                if not all(end in required for end in ends):
                    continue
                aggregate = aggregate_five_minute_bar(
                    tuple(_bar(capture, end) for end in ends), bucket_end=bucket, is_open=True,
                )
                assert aggregate is not None
                transaction.history.upsert_five_minute(**aggregate.model_dump())
                aggregates.append(aggregate)
            assert len(aggregates) == 6
            transaction.commit()
        pipeline._synchronize_stock_recovery()
        snapshot, = pipeline._stock_recovery_schedule.snapshot()
        assert snapshot.disposition is RecoveryDisposition.READY
        assert pipeline.next_stock_recovery_at() == NOW + timedelta(seconds=30)
        assert not sdk.calls


def test_unknown_calendar_has_bounded_observation_and_no_request(tmp_path, monkeypatch):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
        pipeline._synchronize_stock_recovery()
        assert pipeline.next_stock_recovery_at() == NOW + timedelta(seconds=30)
        assert not sdk.calls


def test_getter_does_not_touch_clock_sql_permissions_or_files(tmp_path, monkeypatch):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        schedule = pipeline._stock_recovery_schedule.snapshot()
        demands = pipeline._stock_recovery_demands.copy()

        def forbidden(*args, **kwargs):
            pytest.fail("getter performed observation")

        monkeypatch.setattr(pipeline._clock, "now", forbidden)
        monkeypatch.setattr(pipeline, "_work", forbidden)
        monkeypatch.setattr(pipeline, "_decision_commit_current", forbidden)
        monkeypatch.setattr(type(pipeline._controller), "is_permission_blocked", forbidden)
        for _ in range(5):
            assert pipeline.next_stock_recovery_at() == NOW
        assert pipeline._stock_recovery_schedule.snapshot() == schedule
        assert pipeline._stock_recovery_demands == demands
        assert not sdk.calls


@pytest.mark.parametrize("late", [False, True])
def test_fixed_retry_survives_target_change_and_late_completion(tmp_path, monkeypatch, late):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        schedule = pipeline._stock_recovery_schedule
        ticket = schedule.claim(now=NOW)
        retry_at = NOW + timedelta(minutes=5)
        if not late:
            assert schedule.complete(ticket, RecoveryStepResult.retry(retry_at))
        pipeline._clock.current += timedelta(minutes=1)
        pipeline._synchronize_stock_recovery()
        if late:
            assert not schedule.complete(ticket, RecoveryStepResult.retry(retry_at))
            pipeline._synchronize_stock_recovery()
        snapshot, = schedule.snapshot()
        assert snapshot.requirement != ticket.requirement
        assert snapshot.disposition is RecoveryDisposition.RETRY
        assert snapshot.next_retry_at == retry_at
        assert schedule.claim(now=pipeline._clock.now()) is None
        assert pipeline.next_stock_recovery_at() == pipeline._clock.now() + timedelta(seconds=30)
        assert not sdk.calls


def test_blocked_target_is_frozen_until_real_controller_clear(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            operation = TushareOperation.CURRENT_DAY_MINUTES
            await _block(pipeline._controller, operation)
            pipeline._synchronize_stock_recovery()
            original, = pipeline._stock_recovery_schedule.snapshot()
            assert original.disposition is RecoveryDisposition.BLOCKED
            pipeline._clock.current += timedelta(minutes=6)
            pipeline._synchronize_stock_recovery()
            frozen, = pipeline._stock_recovery_schedule.snapshot()
            demand, = pipeline._stock_recovery_demands.values()
            assert frozen == original
            assert demand.requirement != original.requirement
            assert demand.permission_epoch == 0
            assert pipeline._stock_recovery_schedule.claim(now=pipeline._clock.now()) is None
            # This is the independent permission owner's real controller transition,
            # not a business response or a patched is_permission_blocked getter.
            await pipeline._controller.recheck_permission(
                operation, lambda: True, work_key="separate-permission-owner",
            )
            assert not pipeline._controller.is_permission_blocked(operation)
            assert pipeline._stock_recovery_schedule.snapshot() == (original,)
            pipeline._synchronize_stock_recovery()
            rearmed, = pipeline._stock_recovery_schedule.snapshot()
            demand, = pipeline._stock_recovery_demands.values()
            assert rearmed.disposition is RecoveryDisposition.PENDING
            assert demand.permission_epoch == 1
            assert rearmed.requirement == demand.requirement != original.requirement
            pipeline._synchronize_stock_recovery()
            assert next(iter(pipeline._stock_recovery_demands.values())).permission_epoch == 1
            assert not sdk.calls
    asyncio.run(scenario())


@pytest.mark.parametrize("changed", ["source", "inner", "semantics", "authority_epoch"])
def test_changed_binding_cannot_rearm_previous_owner(tmp_path, monkeypatch, changed):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        if changed == "source":
            pipeline.provider._client = object()
        elif changed == "inner":
            pipeline.provider._client._client = object()
        elif changed == "semantics":
            pipeline._stock_semantics = pipeline._stock_semantics.model_copy(
                update={"semantic_revision": "0" * 64},
            )
        else:
            pipeline._recovery_authority_epoch = lambda: 1
        with pytest.raises(RecoveryAdmissionChangedError):
            pipeline._synchronize_stock_recovery()
        assert pipeline.next_stock_recovery_at() is None
        assert not sdk.calls


@pytest.mark.parametrize("state", ["pending", "blocked", "retry"])
def test_metadata_only_semantic_refresh_preserves_owner_state(tmp_path, monkeypatch, state):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (
            pipeline, sdk, directory, _, _work,
        ):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            if state == "blocked":
                await _block(pipeline._controller, TushareOperation.CURRENT_DAY_MINUTES)
            pipeline._synchronize_stock_recovery()
            schedule = pipeline._stock_recovery_schedule
            if state == "retry":
                ticket = schedule.claim(now=NOW)
                schedule.complete(ticket, RecoveryStepResult.retry(NOW + timedelta(minutes=5)))
            original = schedule.snapshot()
            _replace_stock_contract(directory)
            previous = pipeline._stock_semantics
            pipeline._stock_semantics = pipeline._load_semantic_binding("STOCK")
            assert pipeline._stock_semantics is not previous
            assert pipeline._stock_semantics.semantic_revision == previous.semantic_revision
            pipeline._synchronize_stock_recovery()
            assert schedule.snapshot() == original
            assert next(iter(pipeline._stock_recovery_demands.values())).permission_epoch == 0
            assert not sdk.calls
    asyncio.run(scenario())


def _seed_many(tmp_path, count):
    plans = tuple(_sample_plan().model_copy(update={
        "symbol": f"00000{index}.SZ", "plan_id": f"stock-owner-{index}",
    }) for index in range(count))
    _activate_plans(tmp_path / "monitor.sqlite3", ControlledClock(NOW.replace(hour=9)), plans)
    return plans


def test_synchronizing_local_facts_does_not_consume_round_robin_turns(tmp_path, monkeypatch):
    plans = _seed_many(tmp_path, 3)
    with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, _work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        schedule = pipeline._stock_recovery_schedule
        first = schedule.claim(now=NOW)
        schedule.complete(first, RecoveryStepResult(RecoveryDisposition.PENDING))
        middle = schedule.claim(now=NOW)
        assert middle.requirement.scope_key.endswith(plans[1].symbol)
        schedule.complete(middle, RecoveryStepResult.retry(NOW + timedelta(minutes=5)))
        last = schedule.claim(now=NOW)
        schedule.complete(last, RecoveryStepResult(RecoveryDisposition.PENDING))
        observed = []
        for _ in range(6):
            pipeline._synchronize_stock_recovery()
            ticket = schedule.claim(now=NOW)
            observed.append(ticket.requirement.scope_key)
            schedule.complete(ticket, RecoveryStepResult(RecoveryDisposition.PENDING))
        assert observed == [f"stock-prefix:{plan.symbol}" for plan in (plans[0], plans[2])] * 3
        assert not sdk.calls


def test_ten_active_scopes_are_bounded_to_240_exact_minute_identities(tmp_path, monkeypatch):
    _seed_many(tmp_path, 10)
    with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, _work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._clock.current = NOW.replace(hour=15, minute=0, second=0)
        pipeline._synchronize_stock_recovery()
        demands = tuple(pipeline._stock_recovery_demands.values())
        assert len(demands) == len(pipeline._stock_recovery_schedule.snapshot()) == 10
        for demand in demands:
            assert len(demand.capture.required_ends) == len(demand.missing_ends) == 240
            assert demand.capture.required_ends[119].strftime("%H:%M") == "11:30"
            assert demand.capture.required_ends[120].strftime("%H:%M") == "13:01"
        assert not sdk.calls


def test_exact_missing_identity_not_row_count_or_maximum(tmp_path, monkeypatch):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
        hole = capture.required_ends[7]
        rows = tuple(_bar(capture, end) for end in capture.required_ends if end != hole)
        rows += (_bar(capture, capture.required_ends[-1] + timedelta(minutes=1),
                      received_at=NOW + timedelta(minutes=1)),)
        with work() as transaction:
            transaction.history.upsert_minutes(rows)
            transaction.commit()
        pipeline._synchronize_stock_recovery()
        demand, = pipeline._stock_recovery_demands.values()
        assert demand.missing_ends == (hole,)
        snapshot, = pipeline._stock_recovery_schedule.snapshot()
        assert snapshot.disposition is RecoveryDisposition.PENDING
        assert not sdk.calls


def test_explicit_only_retains_current_day_prefetch(tmp_path, monkeypatch):
    with _pipeline(tmp_path, monkeypatch) as (pipeline, sdk, _, _, _work):
        plan = seed_explicit(tmp_path)
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        demand, = pipeline._stock_recovery_demands.values()
        assert demand.capture.symbol == plan.symbol
        assert len(demand.capture.required_ends) == 30
        assert all(end.date() == NOW.date() for end in demand.capture.required_ends)
        assert not sdk.calls


def test_reactivation_changes_exact_revision_and_deactivation_removes_scope(tmp_path, monkeypatch):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        before, = pipeline._stock_recovery_demands.values()
        replace_or_reactivate(work, pipeline, _sample_plan())
        pipeline._synchronize_stock_recovery()
        after, = pipeline._stock_recovery_demands.values()
        assert after.requirement != before.requirement
        assert after.capture.activation_revision == before.capture.activation_revision + 2
        with work() as transaction:
            active = transaction.plans.get_active(_sample_plan().symbol)
            transaction.plans.deactivate(active.symbol, expected_revision=active.revision)
            transaction.commit()
        pipeline._synchronize_stock_recovery()
        assert not pipeline._stock_recovery_schedule.snapshot()
        assert not pipeline._stock_recovery_demands
        assert pipeline.next_stock_recovery_at() is None
        assert not sdk.calls


def test_unknown_observation_retry_is_fixed_until_due(tmp_path, monkeypatch):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
        pipeline._synchronize_stock_recovery()
        original, = pipeline._stock_recovery_schedule.snapshot()
        for seconds in (1, 12, 29):
            pipeline._clock.current = NOW + timedelta(seconds=seconds)
            pipeline._synchronize_stock_recovery()
            assert pipeline._stock_recovery_schedule.snapshot() == (original,)
            assert pipeline.next_stock_recovery_at() == NOW + timedelta(seconds=30)
        pipeline._clock.current = NOW + timedelta(seconds=30)
        pipeline._synchronize_stock_recovery()
        assert pipeline.next_stock_recovery_at() == NOW + timedelta(seconds=60)
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        assert pipeline.next_stock_recovery_at() == NOW + timedelta(seconds=60)
        demand, = pipeline._stock_recovery_demands.values()
        assert demand.capture is not None
        assert not sdk.calls


@pytest.mark.parametrize("complete", [False, True])
def test_local_observations_cannot_erase_future_retry(tmp_path, monkeypatch, complete):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            pipeline._synchronize_stock_recovery()
            schedule = pipeline._stock_recovery_schedule
            ticket = schedule.claim(now=NOW)
            retry_at = NOW + timedelta(minutes=5)
            schedule.complete(ticket, RecoveryStepResult.retry(retry_at))
            pipeline._clock.current += timedelta(minutes=1)
            if complete:
                capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
                with work() as transaction:
                    transaction.history.upsert_minutes(tuple(
                        _bar(capture, end, received_at=pipeline._clock.now())
                        for end in capture.required_ends
                    ))
                    transaction.commit()
            else:
                await _block(pipeline._controller, TushareOperation.CURRENT_DAY_MINUTES)
            pipeline._synchronize_stock_recovery()
            current, = schedule.snapshot()
            assert current.disposition is RecoveryDisposition.RETRY
            assert current.next_retry_at == retry_at
            assert schedule.claim(now=pipeline._clock.now()) is None
            assert not sdk.calls
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["revoked", "generation", "admission"])
def test_revoked_owner_has_no_wake_and_no_rearm(tmp_path, monkeypatch, change):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._synchronize_stock_recovery()
        before = pipeline._stock_recovery_schedule.snapshot()
        if change == "revoked":
            pipeline._recovery_authority_revoked.set()
        elif change == "generation":
            pipeline._generation_current = lambda: False
        else:
            pipeline._admission_revoked = lambda: True
        with pytest.raises(RecoveryAdmissionChangedError):
            pipeline._synchronize_stock_recovery()
        assert pipeline.next_stock_recovery_at() is None
        assert pipeline._stock_recovery_schedule.snapshot() == before
        assert not sdk.calls


def test_same_minute_resync_keeps_revision_and_only_reads_bounded_facts(tmp_path, monkeypatch):
    from trade_plan_monitor.state.repositories import MarketHistoryRepository, PlanRepository

    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        reads, statements = [], []
        original_plans = PlanRepository.list_version_details
        original_minutes = MarketHistoryRepository.list_minutes

        def plans(self, *args, **kwargs):
            assert kwargs["limit"] == 10
            reads.append("plans")
            return original_plans(self, *args, **kwargs)

        def minutes(self, symbol, *args, **kwargs):
            assert kwargs["start"].date() == kwargs["end"].date() == NOW.date()
            reads.append("minutes")
            return original_minutes(self, symbol, *args, **kwargs)

        monkeypatch.setattr(PlanRepository, "list_version_details", plans)
        monkeypatch.setattr(MarketHistoryRepository, "list_minutes", minutes)
        with work() as transaction:
            engine = transaction._session.get_bind()
        def record_sql(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.strip().split()[0].upper())
        event.listen(engine, "before_cursor_execute", record_sql)
        try:
            pipeline._synchronize_stock_recovery()
            original, = pipeline._stock_recovery_demands.values()
            pipeline._clock.current += timedelta(seconds=1)
            pipeline._synchronize_stock_recovery()
        finally:
            event.remove(engine, "before_cursor_execute", record_sql)
        latest, = pipeline._stock_recovery_demands.values()
        assert latest.requirement == original.requirement
        assert latest.capture.target.observed_at != original.capture.target.observed_at
        assert reads == ["plans", "minutes", "plans", "minutes"]
        assert not ({"INSERT", "UPDATE", "DELETE", "REPLACE"} & set(statements))
        assert not sdk.calls


@pytest.mark.parametrize("hour,minute,count", [
    (9, 30, 0), (9, 31, 1), (11, 30, 120), (12, 30, 120), (13, 0, 120), (15, 0, 240),
])
def test_observed_target_never_invents_future_or_lunch_minutes(
    tmp_path, monkeypatch, hour, minute, count,
):
    with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
        _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
        pipeline._clock.current = NOW.replace(hour=hour, minute=minute, second=0)
        pipeline._synchronize_stock_recovery()
        demand, = pipeline._stock_recovery_demands.values()
        if count:
            assert len(demand.capture.required_ends) == count
            assert demand.capture.required_ends[-1] <= pipeline._clock.now()
        else:
            assert demand.capture is None
            expected_wake = pipeline._clock.now() + timedelta(seconds=30)
            assert pipeline.next_stock_recovery_at() == expected_wake
        assert not sdk.calls


@pytest.mark.parametrize("changed", ["source", "semantic_revision"])
def test_authoritative_clear_under_replaced_binding_does_not_advance_epoch(
    tmp_path, monkeypatch, changed,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            operation = TushareOperation.CURRENT_DAY_MINUTES
            await _block(pipeline._controller, operation)
            pipeline._synchronize_stock_recovery()
            original = pipeline._stock_recovery_schedule.snapshot()
            pipeline._clock.current += timedelta(minutes=6)
            await pipeline._controller.recheck_permission(
                operation, lambda: True, work_key="independent-proof",
            )
            if changed == "source":
                pipeline.provider._client = object()
            else:
                pipeline._stock_semantics = pipeline._stock_semantics.model_copy(
                    update={"semantic_revision": "0" * 64},
                )
            with pytest.raises(RecoveryAdmissionChangedError):
                pipeline._synchronize_stock_recovery()
            assert pipeline._stock_recovery_schedule.snapshot() == original
            assert next(iter(pipeline._stock_recovery_demands.values())).permission_epoch == 0
            assert pipeline.next_stock_recovery_at() is None
            assert not sdk.calls
    asyncio.run(scenario())


def test_index_permission_block_is_not_a_stock_scope_block(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _work):
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date())
            await _block(pipeline._controller, TushareOperation.INDEX_HISTORICAL_MINUTES)
            pipeline._synchronize_stock_recovery()
            snapshot, = pipeline._stock_recovery_schedule.snapshot()
            assert snapshot.disposition is RecoveryDisposition.PENDING
            assert pipeline._controller.is_permission_blocked(
                TushareOperation.INDEX_HISTORICAL_MINUTES,
            )
            assert not sdk.calls
    asyncio.run(scenario())
