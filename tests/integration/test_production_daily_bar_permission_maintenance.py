"""Offline original-receipt DAILY_BARS rechecks through the physical request seam."""

import asyncio
from datetime import timedelta
from threading import Event, current_thread, main_thread
from types import SimpleNamespace

import pandas as pd
import pytest
from requests import ConnectionError as ProviderConnectionError
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_historical_close_evidence import publish
from test_permission_candidate_selection import _block, _seed_official_bar, _seed_open_day
from test_production_daily_bar_permission_preparation import NOW, OP, ready
from test_production_daily_bar_permission_preparation import make_env as make_env
from test_recovery_alert_provenance import _result

from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)
from trade_plan_monitor.runtime.production import PermissionMaintenanceResult
from trade_plan_monitor.runtime.request_control import (
    PermissionReservationCallbackError,
    RequestControlError,
    RequestControlErrorCode,
    RequestNotStartedError,
    TushareOperation,
    TushareRequestController,
)
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import DailyBar as StoredDailyBar
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.runtime_recovery import (
    ProviderRecoveryRepository,
    RecoveryCheckpointError,
)


@pytest.fixture
def wired_env(make_env, monkeypatch):
    controls = []

    def build(*, timeout=15, **kwargs):
        env = make_env(**kwargs)
        repository = ProviderRecoveryRepository(env.sessions, provider_identity="d" * 64)
        control = TushareRequestController(
            clock=env.clock, executor_workers=1, max_concurrency=1,
            min_interval=timedelta(0), jitter=timedelta(0), in_cycle_retries=0,
            timeout_seconds=timeout, recovery_repository=repository,
        )
        controls.append((control, repository))
        env.controller = control
        env.pipeline._controller = control
        env.pipeline._permission_market_window = lambda now, horizon: ()
        env.repository = repository
        env.probe_calls = []
        env.entered, env.release = Event(), Event()
        env.release.set()
        env.before_physical = lambda: None
        env.after_physical = lambda: None

        def probe(symbol, anchor, *, _physical_start=None):
            assert current_thread() is not main_thread()
            env.before_physical()
            assert _physical_start is not None
            _physical_start()
            env.probe_calls.append((symbol, anchor))
            env.entered.set()
            assert env.release.wait(3)
            env.after_physical()

        env.real_probe = env.pipeline.provider.probe_daily_bars_permission
        monkeypatch.setattr(type(env.pipeline.provider), "probe_daily_bars_permission",
                            lambda self, *args, **kwargs: probe(*args, **kwargs))
        return env

    yield build
    for control, repository in controls:
        control.close()
        repository.release_owner(control)


def recheck(env):
    return asyncio.run(env.pipeline._maybe_recheck_daily_bars_permission())


def persisted_due(env):
    engine = create_sqlite_engine(env.database)
    try:
        repository = ProviderRecoveryRepository(create_session_factory(engine),
                                                provider_identity="d" * 64)
        return next((row.retry_at for row in repository.load()
                     if row.kind == "permission" and row.scope_key == OP.value), None)
    finally:
        engine.dispose()


@pytest.mark.parametrize("today", [True, False])
@pytest.mark.parametrize("pool", ["O", "F"])
def test_original_today_or_history_candidate_proves_only_own_scope(wired_env, today, pool):
    env = wired_env(today=today, calendar=True)
    ready(env)
    asyncio.run(_block(env.controller, TushareOperation.INDEX_DAILY))
    anchor = NOW.date() - timedelta(days=1)
    if pool == "O":
        _seed_official_bar(env.database, env.plans[0].symbol, anchor, NOW)
    statements = []

    def record(conn, cursor, sql, parameters, context, many):
        assert current_thread() is main_thread(), "worker must not query SQLite"
        statements.append(sql)

    event.listen(env.engine, "before_cursor_execute", record)
    assert recheck(env) is PermissionMaintenanceResult.PROBED
    assert env.probe_calls == [(env.plans[0].symbol, anchor)]
    assert not env.controller.is_permission_blocked(OP)
    assert env.controller.is_permission_blocked(TushareOperation.INDEX_DAILY)
    state = env.pipeline._permission_rotation_state
    assert state.last_operation is OP
    assert getattr(state, "official_pair" if pool == "O" else "fallback_pair") == (
        env.plans[0].symbol, anchor,
    )
    assert state.next_daily_bar_pool == ("F" if pool == "O" else "O")
    receipt = env.pipeline._daily_bar_demand_receipts[env.plans[0].symbol]
    assert receipt.d_need is None if today else receipt.d_need != anchor
    assert OP not in env.pipeline._permission_probe_deferred_until
    assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN"))
               or "provider_recovery_checkpoint" in sql for sql in statements)


def test_lock_wrapper_prepares_fresh_once_without_deadlock(wired_env, monkeypatch):
    env = wired_env(calendar=True)
    ready(env)
    reader = env.pipeline._permission_demand_reader
    original = reader.inspect_permission_demand_in_session
    calls = []

    def inspect(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(reader, "inspect_permission_demand_in_session", inspect)
    async def scenario():
        lock = env.pipeline._permission_maintenance_lock
        await lock.acquire()
        pending = asyncio.create_task(env.pipeline._maybe_recheck_daily_bars_permission())
        await asyncio.sleep(0)
        assert not pending.done() and not calls
        lock.release()
        assert await asyncio.wait_for(pending, 2) is PermissionMaintenanceResult.PROBED
        assert calls == [1]
    asyncio.run(scenario())


def test_unknown_keeps_original_fixed_defer_and_skips_repeat(wired_env):
    env = wired_env(anchor=False, calendar=False)
    ready(env)
    assert recheck(env) is PermissionMaintenanceResult.DEFERRED
    deadline = env.pipeline._permission_probe_deferred_until[OP]
    cursor = dict(env.pipeline._daily_bar_demand_cursors)
    env.clock.current += timedelta(seconds=1)
    assert recheck(env) is PermissionMaintenanceResult.SKIPPED
    assert env.pipeline._permission_probe_deferred_until[OP] == deadline
    assert env.pipeline._daily_bar_demand_cursors == cursor
    assert not env.probe_calls


@pytest.mark.parametrize("gate", ["not_due", "429", "other_scope"])
def test_entry_gates_skip_without_inspecting_or_reserving(wired_env, monkeypatch, gate):
    env = wired_env(today=True)
    if gate == "other_scope":
        asyncio.run(_block(env.controller, TushareOperation.TRADING_CALENDAR))
    asyncio.run(_block(env.controller, OP))
    if gate != "not_due":
        env.clock.current += timedelta(seconds=301)
    if gate == "429":
        def limited():
            raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "rt_min")
        with pytest.raises(RequestControlError):
            asyncio.run(env.controller.execute(
                TushareOperation.CURRENT_DAY_MINUTES, limited, work_key="offline:429",
            ))
    before_due = persisted_due(env)
    before_rotation = env.pipeline._permission_rotation_state
    def unexpected_inspection(*args, **kwargs):
        pytest.fail("gated recheck must not inspect demand")
    monkeypatch.setattr(env.pipeline._permission_demand_reader,
                        "inspect_permission_demand_in_session", unexpected_inspection)
    assert recheck(env) is PermissionMaintenanceResult.SKIPPED
    assert persisted_due(env) == before_due
    assert env.pipeline._permission_rotation_state is before_rotation
    assert not env.probe_calls


@pytest.mark.parametrize("change", ["pending", "identity_aba"])
def test_inflight_pending_preserves_demand_but_identity_aba_rejects_it(wired_env, change):
    env = wired_env(days=1, calendar=True)
    ready(env)
    env.release.clear()
    async def scenario():
        attempt = asyncio.create_task(env.pipeline._maybe_recheck_daily_bars_permission())
        assert await asyncio.to_thread(env.entered.wait, 1)
        plan = env.plans[0]
        with env.work() as work:
            if change == "pending":
                RuntimeEvaluationService._mark_close_pending(
                    work, plan=plan, symbol=plan.symbol, trade_date=env.first,
                    evaluated_at=env.clock.now(), activation_revision=1,
                )
            else:
                work.plans.deactivate(plan.symbol, expected_revision=1)
                work.plans.activate(plan, expected_revision=2, validation=validate_trade_plan(
                    plan, available_market_evidence=ALL_MARKET_EVIDENCE,
                ))
            work.commit()
        env.release.set()
        expected = (PermissionMaintenanceResult.PROBED if change == "pending"
                    else PermissionMaintenanceResult.FAILED)
        assert await attempt is expected
        assert env.controller.is_permission_blocked(OP) == (change == "identity_aba")
    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["reservation", "queue", "worker", "physical"])
def test_authority_revocation_at_each_start_boundary(wired_env, monkeypatch, boundary):
    env = wired_env(today=True)
    ready(env)
    initial_due = persisted_due(env)
    before = env.pipeline._permission_rotation_state
    def revoke():
        monkeypatch.setattr(env.pipeline, "_configuration_current", lambda: False)
    if boundary == "reservation":
        original = env.pipeline._prepare_daily_bar_permission_locked
        def prepare_then_revoke():
            result = original()
            revoke()
            return result
        monkeypatch.setattr(env.pipeline, "_prepare_daily_bar_permission_locked",
                            prepare_then_revoke)
    elif boundary == "queue":
        original = env.pipeline._permission_probe_reservation_callback
        def callback(candidate):
            advance = original(candidate)
            def reserved():
                advance()
                revoke()
            return reserved
        monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback", callback)
    elif boundary == "worker":
        original = TushareRequestController.recheck_permission
        async def recheck_after_admission(self, operation, call, **kwargs):
            admission = kwargs["can_start"]
            def admit_then_revoke():
                result = admission()
                revoke()
                return result
            kwargs["can_start"] = admit_then_revoke
            return await original(self, operation, call, **kwargs)
        monkeypatch.setattr(TushareRequestController, "recheck_permission", recheck_after_admission)
    else:
        env.before_physical = revoke
    assert recheck(env) is PermissionMaintenanceResult.DEFERRED
    assert not env.probe_calls and env.controller.is_permission_blocked(OP)
    if boundary == "reservation":
        assert env.pipeline._permission_rotation_state is before
        assert persisted_due(env) == initial_due
    else:
        assert env.pipeline._permission_rotation_state.last_operation is OP
        assert persisted_due(env) == env.clock.now() + timedelta(seconds=300)


def test_market_blocker_before_reservation_uses_frozen_yield_deadline(wired_env, monkeypatch):
    env = wired_env(today=True)
    ready(env)
    captured = env.clock.now()
    before_due = persisted_due(env)
    before_rotation = env.pipeline._permission_rotation_state
    env.pipeline._permission_market_window = lambda now, horizon: (
        (captured + timedelta(seconds=32), True),
    )
    original = env.pipeline._permission_probe_reservation_callback
    def prepare_callback(candidate):
        env.clock.current += timedelta(seconds=5)
        return original(candidate)
    monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback", prepare_callback)
    assert recheck(env) is PermissionMaintenanceResult.DEFERRED
    assert env.pipeline._permission_probe_deferred_until[OP] == (
        captured + timedelta(seconds=32, microseconds=1)
    )
    assert persisted_due(env) == before_due
    assert env.pipeline._permission_rotation_state is before_rotation
    assert not env.probe_calls


@pytest.mark.parametrize("change", ["receipt", "anchor", "reader", "factory", "epoch"])
def test_original_response_facts_cannot_borrow_replacements(wired_env, change):
    env = wired_env(calendar=True)
    ready(env)
    env.release.clear()
    async def scenario():
        attempt = asyncio.create_task(env.pipeline._maybe_recheck_daily_bars_permission())
        assert await asyncio.to_thread(env.entered.wait, 1)
        if change == "receipt":
            symbol = env.plans[0].symbol
            old = env.pipeline._daily_bar_demand_receipts[symbol]
            with env.sessions.begin() as session:
                row = session.get(TradingCalendar, ("SSE", old.d_need))
                row.is_open = False
            with env.sessions() as session:
                reader = env.pipeline._permission_demand_reader
                replacement = reader.inspect_permission_demand_in_session(
                    session, symbol, env.clock.now(),
                ).receipt
            assert replacement is not None and replacement.d_need != old.d_need
            env.pipeline._daily_bar_demand_receipts[symbol] = replacement
        elif change == "anchor":
            with env.sessions.begin() as session:
                row = session.get(TradingCalendar, ("SSE", NOW.date() - timedelta(days=1)))
                row.is_open = False
            _seed_open_day(env.database, NOW.date() - timedelta(days=4))
        elif change == "reader":
            env.pipeline._permission_demand_reader = type(env.pipeline._permission_demand_reader)(
                env.sessions,
            )
        elif change == "factory":
            env.pipeline._permission_session_factory = lambda: env.sessions()
        else:
            with env.pipeline._calendar_epoch_lock:
                env.pipeline._calendar_epoch += 1
                env.pipeline._calendar_revoked.set()
        env.release.set()
        assert await attempt is PermissionMaintenanceResult.FAILED
        assert env.controller.is_permission_blocked(OP)
        assert persisted_due(env) >= env.clock.now() + timedelta(seconds=300)
    asyncio.run(scenario())


@pytest.mark.parametrize("pool", ["O", "F"])
def test_response_allows_original_pool_membership_to_move(wired_env, pool):
    env = wired_env(today=True)
    ready(env)
    anchor = NOW.date() - timedelta(days=1)
    symbol = env.plans[0].symbol
    if pool == "O":
        _seed_official_bar(env.database, symbol, anchor, NOW)
    env.release.clear()
    async def scenario():
        task = asyncio.create_task(env.pipeline._maybe_recheck_daily_bars_permission())
        assert await asyncio.to_thread(env.entered.wait, 1)
        reserved = env.pipeline._permission_rotation_state
        if pool == "O":
            with env.sessions.begin() as session:
                row = session.get(StoredDailyBar, (symbol, anchor, True))
                row.is_official = False
        else:
            _seed_official_bar(env.database, symbol, anchor, NOW)
        env.release.set()
        assert await task is PermissionMaintenanceResult.PROBED
        assert env.pipeline._permission_rotation_state is reserved
    asyncio.run(scenario())


@pytest.mark.parametrize("code", [TushareErrorCode.BLOCKED_PERMISSION,
                                 TushareErrorCode.RATE_LIMITED,
                                 TushareErrorCode.INVALID_RESPONSE])
def test_known_failures_keep_durable_reservation(wired_env, code):
    env = wired_env(today=True)
    ready(env)
    def fail():
        raise TushareProviderError(code, "daily")
    env.after_physical = fail
    assert recheck(env) is PermissionMaintenanceResult.FAILED
    assert env.controller.is_permission_blocked(OP)
    assert persisted_due(env) == env.clock.now() + timedelta(seconds=300)


def test_unknown_worker_error_is_propagated_as_controller_error(wired_env):
    env = wired_env(today=True)
    ready(env)
    def fail():
        raise RuntimeError("offline unexpected worker error")
    env.after_physical = fail
    with pytest.raises(RequestControlError) as caught:
        recheck(env)
    assert caught.value.code is RequestControlErrorCode.ERROR
    assert persisted_due(env) == env.clock.now() + timedelta(seconds=300)


@pytest.mark.parametrize("kind", ["save", "callback"])
def test_storage_and_callback_errors_propagate(wired_env, monkeypatch, kind):
    env = wired_env(today=True)
    ready(env)
    before = env.pipeline._permission_rotation_state
    initial_due = persisted_due(env)
    if kind == "save":
        def fail(rows):
            raise RecoveryCheckpointError("offline save failure")
        monkeypatch.setattr(env.repository, "save", fail)
        expected = RecoveryCheckpointError
    else:
        def fail():
            raise RuntimeError("offline callback failure")
        monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback",
                            lambda candidate: fail)
        expected = PermissionReservationCallbackError
    with pytest.raises(expected):
        recheck(env)
    assert not env.probe_calls and env.pipeline._permission_rotation_state is before
    assert persisted_due(env) == (initial_due if kind == "save" else
                                  env.clock.now() + timedelta(seconds=300))


def test_cancellation_requested_before_outer_catch_cannot_clear(wired_env, monkeypatch):
    env = wired_env(today=True)
    ready(env)
    original = TushareRequestController.recheck_permission
    observed = []
    async def cancel_before_validation(self, operation, call, **kwargs):
        owner = asyncio.current_task()
        validate = kwargs["validate_after"]
        def cancel_then_validate():
            owner.cancel()
            result = validate()
            observed.append(result)
            return result
        kwargs["validate_after"] = cancel_then_validate
        return await original(self, operation, call, **kwargs)
    monkeypatch.setattr(TushareRequestController, "recheck_permission", cancel_before_validation)
    async def scenario():
        task = asyncio.create_task(env.pipeline._maybe_recheck_daily_bars_permission())
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert observed == [False]
        assert env.controller.is_permission_blocked(OP)
    asyncio.run(scenario())


def test_started_cancellation_late_success_cannot_clear_and_next_call_waits_for_drain(wired_env):
    env = wired_env(today=True)
    ready(env)
    env.release.clear()
    next_started = Event()
    async def scenario():
        task = asyncio.create_task(env.pipeline._maybe_recheck_daily_bars_permission())
        assert await asyncio.to_thread(env.entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not env.pipeline._permission_maintenance_lock.locked()
        other = asyncio.create_task(env.controller.execute(
            TushareOperation.CURRENT_DAY_MINUTES, next_started.set, work_key="after:cancel",
        ))
        await asyncio.sleep(0)
        assert not next_started.is_set()
        env.release.set()
        await other
        assert next_started.is_set() and env.controller.is_permission_blocked(OP)
        assert persisted_due(env) == env.clock.now() + timedelta(seconds=300)
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["complete", "covered", "rollback", "corrupt"])
def test_original_historical_receipt_rejects_changed_checkpoint(wired_env, change):
    env = wired_env(calendar=True)
    bridge = SimpleNamespace(plan=env.plans[0], result=_result(env.plans[0]),
                             clock=[env.clock.now()], work=env.work)
    risk = bridge.result.snapshot.risk.model_copy(update={
        "updated_at": env.activation_at, "breach_trade_date": env.first,
    })
    if change in {"rollback", "corrupt"}:
        publish(bridge, day=env.first, transition=False, risk=risk)
    ready(env)
    env.release.clear()
    async def scenario():
        task = asyncio.create_task(env.pipeline._maybe_recheck_daily_bars_permission())
        assert await asyncio.to_thread(env.entered.wait, 1)
        receipt = env.pipeline._daily_bar_demand_receipts[env.plans[0].symbol]
        if change in {"complete", "covered"}:
            publish(bridge, day=receipt.d_need + timedelta(days=int(change == "covered")),
                    transition=False, risk=risk)
        else:
            with env.sessions.begin() as session:
                if change == "corrupt":
                    session.execute(text("UPDATE evaluation_result SET result_json='{}'"))
                else:
                    session.execute(text("DELETE FROM evaluation_result"))
                    session.execute(text("DELETE FROM evaluation_ledger"))
                    session.execute(text("DELETE FROM monitor_event "
                                         "WHERE event_type='symbol.snapshot.updated'"))
        env.release.set()
        assert await task is PermissionMaintenanceResult.FAILED
        assert env.controller.is_permission_blocked(OP)
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["rollback", "cross_day", "market_approaches"])
def test_response_uses_preparation_time_without_rechecking_start_window(wired_env, change):
    env = wired_env(count=2, calendar=True)
    ready(env)
    original = asyncio.run(env.pipeline._prepare_daily_bar_permission())
    env.clock.current += timedelta(seconds=5)
    captured = env.clock.now()
    window_calls = []
    def window(now, horizon):
        window_calls.append((now, horizon))
        return ((now + timedelta(seconds=32), True),)
    env.pipeline._permission_market_window = window
    def response_clock():
        env.clock.current = (
            captured - timedelta(seconds=1) if change == "rollback" else
            captured + timedelta(days=1) if change == "cross_day" else
            captured + timedelta(seconds=16)
        )
        if change == "rollback":
            assert env.clock.now() > original.receipt.captured_at
    env.after_physical = response_clock
    expected = PermissionMaintenanceResult.PROBED if change == "market_approaches" else (
        PermissionMaintenanceResult.FAILED
    )
    assert recheck(env) is expected
    assert window_calls == [(captured, captured + timedelta(seconds=46.25))]


def test_false_weekend_open_cannot_supply_anchor(wired_env):
    env = wired_env(today=True, anchor=False)
    ready(env)
    saturday = NOW.date() - timedelta(days=3)
    assert saturday.weekday() == 5
    _seed_open_day(env.database, saturday)
    assert recheck(env) is PermissionMaintenanceResult.DEFERRED
    assert not env.probe_calls and env.pipeline._permission_rotation_state.last_operation is None


def test_response_anchor_and_receipt_share_snapshot_across_writer(wired_env, monkeypatch):
    env = wired_env(today=True)
    ready(env)
    reader = env.pipeline._permission_demand_reader
    original = reader.validate_permission_demand_in_session
    response_sessions = []
    def validate_then_write(session, receipt, now):
        valid = original(session, receipt, now)
        if env.entered.is_set():
            response_sessions.append(session)
            with env.sessions.begin() as writer:
                row = writer.get(TradingCalendar, ("SSE", NOW.date() - timedelta(days=1)))
                row.is_open = False
        return valid
    monkeypatch.setattr(reader, "validate_permission_demand_in_session", validate_then_write)
    assert recheck(env) is PermissionMaintenanceResult.PROBED
    assert len(response_sessions) == 1
    with env.sessions() as session:
        row = session.get(TradingCalendar, ("SSE", NOW.date() - timedelta(days=1)))
        assert row.is_open is False


def test_response_sql_error_propagates_with_reservation_retained(wired_env):
    env = wired_env(today=True)
    ready(env)
    def fail(conn, cursor, sql, params, context, many):
        if env.entered.is_set() and "FROM trading_calendar" in sql:
            raise OperationalError(sql, params, RuntimeError("offline response read failed"))
    event.listen(env.engine, "before_cursor_execute", fail)
    with pytest.raises(OperationalError):
        recheck(env)
    assert persisted_due(env) == env.clock.now() + timedelta(seconds=300)


def test_transient_failure_is_failed_and_retains_reservation(wired_env):
    env = wired_env(today=True)
    ready(env)
    def fail():
        raise ProviderConnectionError("offline transient")
    env.after_physical = fail
    assert recheck(env) is PermissionMaintenanceResult.FAILED
    assert persisted_due(env) == env.clock.now() + timedelta(seconds=300)


def test_timeout_is_failed_and_late_success_does_not_clear(wired_env):
    env = wired_env(today=True, timeout=0.1)
    ready(env)
    env.release.clear()
    async def scenario():
        try:
            assert await env.pipeline._maybe_recheck_daily_bars_permission() is (
                PermissionMaintenanceResult.FAILED
            )
            assert env.entered.is_set() and env.controller.is_permission_blocked(OP)
        finally:
            env.release.set()
        await env.controller.execute(TushareOperation.CURRENT_DAY_MINUTES,
                                     lambda: None, work_key="after:timeout")
        assert env.controller.is_permission_blocked(OP)
        assert persisted_due(env) == env.clock.now() + timedelta(seconds=300)
    asyncio.run(scenario())


def test_closed_propagates_before_reservation(wired_env):
    env = wired_env(today=True)
    ready(env)
    before = persisted_due(env)
    env.controller.close()
    with pytest.raises(RequestControlError) as caught:
        recheck(env)
    assert caught.value.code is RequestControlErrorCode.CLOSED
    assert persisted_due(env) == before and not env.probe_calls


@pytest.mark.parametrize("outcome", [
    "cancel", "queue_full", "expired_window", "market_blocked", "start_floor",
])
def test_queued_outcomes_preserve_exactly_one_reservation(wired_env, monkeypatch, outcome):
    env = wired_env(today=True)
    ready(env)
    captured = env.clock.now()
    if outcome == "market_blocked":
        env.pipeline._permission_market_window = lambda now, horizon: (
            (captured + timedelta(seconds=32), True),
        )
    occupied, release = Event(), Event()
    reservations = []
    original = env.pipeline._permission_probe_reservation_callback
    def callback(candidate):
        advance = original(candidate)
        def reserved():
            reservations.append(candidate)
            advance()
        return reserved
    monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback", callback)
    def occupy():
        occupied.set()
        assert release.wait(3)
    async def scenario():
        blocker = asyncio.create_task(env.controller.execute(
            TushareOperation.CURRENT_DAY_MINUTES, occupy, work_key="hold:bars",
        ))
        assert await asyncio.to_thread(occupied.wait, 1)
        queued = None
        if outcome == "queue_full":
            monkeypatch.setattr(env.controller._admission, "_max_waiters", 1)
            queued = asyncio.create_task(env.controller.execute(
                TushareOperation.CURRENT_DAY_MINUTES, lambda: None, work_key="fill:queue",
            ))
            await asyncio.sleep(0)
            assert env.controller.waiting_count == 1
        attempt = asyncio.create_task(env.pipeline._maybe_recheck_daily_bars_permission())
        try:
            if outcome == "queue_full":
                with pytest.raises(RequestControlError) as caught:
                    await attempt
                assert caught.value.code is RequestControlErrorCode.QUEUE_FULL
            else:
                for _ in range(100):
                    if env.controller.waiting_count:
                        break
                    await asyncio.sleep(0)
                assert env.controller.waiting_count == 1
                probe = env.controller._permission_rechecks[OP]
                if outcome == "cancel":
                    attempt.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await attempt
                    assert not env.pipeline._permission_maintenance_lock.locked()
                else:
                    env.clock.current += timedelta(seconds=16 if outcome == "expired_window" else 5)
                release.set()
                await blocker
                if outcome == "cancel":
                    with pytest.raises(RequestNotStartedError):
                        await probe
                else:
                    expected = (PermissionMaintenanceResult.PROBED if outcome == "start_floor"
                                else PermissionMaintenanceResult.DEFERRED)
                    assert await attempt is expected
                    if outcome == "market_blocked":
                        assert env.pipeline._permission_probe_deferred_until[OP] == (
                            captured + timedelta(seconds=32, microseconds=1)
                        )
            assert len(reservations) == 1
            if outcome != "start_floor":
                assert not env.probe_calls and env.controller.is_permission_blocked(OP)
                assert persisted_due(env) == NOW + timedelta(seconds=601)
        finally:
            release.set()
            await blocker
            if queued is not None:
                await queued
    asyncio.run(scenario())


def daily_frame(symbol="003043.SZ", **changes):
    return pd.DataFrame([{
        "ts_code": symbol, "trade_date": "20260907", "open": "64", "high": "65",
        "low": "63", "close": "64", "vol": "100", "amount": "1000",
    } | changes])


def real_provider(frame):
    calls = []
    def daily(**kwargs):
        calls.append(kwargs)
        return frame
    sdk = SimpleNamespace(daily=daily)
    provider = TushareMarketDataProvider(sdk, now=lambda: NOW, is_open_on=lambda day: True)
    return provider, calls


def test_real_provider_seam_is_after_argument_construction_and_preserves_sentinel(monkeypatch):
    provider, calls = real_provider(daily_frame())
    events = []
    original = TushareMarketDataProvider._date_argument
    def date_argument(day):
        events.append("argument")
        return original(day)
    monkeypatch.setattr(TushareMarketDataProvider, "_date_argument", staticmethod(date_argument))
    sentinel = RequestNotStartedError("offline exact sentinel")
    def guard():
        events.append("guard")
        raise sentinel
    with pytest.raises(RequestNotStartedError) as caught:
        provider.probe_daily_bars_permission("003043.SZ", NOW.date() - timedelta(days=1),
                                             _physical_start=guard)
    assert caught.value is sentinel and calls == []
    assert events == ["argument", "argument", "guard"]


@pytest.mark.parametrize("response", ["exact", "empty", "duplicate", "other_symbol", "other_date"])
def test_real_provider_seam_keeps_exact_official_row_proof(response):
    frame = daily_frame()
    if response == "empty":
        frame = frame.iloc[:0]
    elif response == "duplicate":
        frame = pd.concat((frame, frame))
    elif response == "other_symbol":
        frame = daily_frame("600000.SH")
    elif response == "other_date":
        frame = daily_frame(trade_date="20260904")
    provider, calls = real_provider(frame)
    guards = []
    def probe():
        return provider.probe_daily_bars_permission(
            "003043.SZ", NOW.date() - timedelta(days=1), _physical_start=lambda: guards.append(1),
        )
    if response == "exact":
        assert probe() is None
    else:
        with pytest.raises(TushareProviderError) as caught:
            probe()
        assert caught.value.code is TushareErrorCode.INVALID_RESPONSE
    assert guards == [1]
    assert calls == [{
        "fields": "ts_code,trade_date,open,high,low,close,vol,amount", "ts_code": "003043.SZ",
        "start_date": "20260907", "end_date": "20260907",
    }]


def test_real_provider_rejects_invalid_arguments_before_physical_guard():
    provider, calls = real_provider(daily_frame())
    guards = []
    with pytest.raises(ValueError):
        provider.probe_daily_bars_permission(
            "bad", NOW.date() - timedelta(days=1), _physical_start=lambda: guards.append(1),
        )
    assert guards == [] and calls == []


def test_real_provider_normal_daily_and_historical_paths_remain_unchanged():
    provider, calls = real_provider(daily_frame())
    anchor = NOW.date() - timedelta(days=1)
    assert provider.daily_bars("003043.SZ", anchor, anchor)[0].is_official is True
    assert provider.historical_daily_bars("003043.SZ", anchor, anchor)[0].is_official is True
    assert len(calls) == 2 and calls[0] == calls[1]


def test_real_provider_end_to_end_recheck_uses_exact_sdk_request(wired_env, monkeypatch):
    env = wired_env(calendar=True)
    ready(env)
    monkeypatch.setattr(type(env.pipeline.provider), "probe_daily_bars_permission",
                        env.real_probe.__func__)
    assert recheck(env) is PermissionMaintenanceResult.PROBED
    assert env.sdk.calls == [("daily", {
        "fields": "ts_code,trade_date,open,high,low,close,vol,amount",
        "ts_code": env.plans[0].symbol, "start_date": "20260907", "end_date": "20260907",
    })]
    assert not env.controller.is_permission_blocked(OP)
