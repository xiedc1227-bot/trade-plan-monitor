"""Minute owner proofs through real provider/controller and temporary SQLite."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from threading import Event, current_thread, main_thread
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import event
from test_permission_candidate_selection import _block, _seed_open_day
from test_production_stock_minute_permission_preparation import MINUTE_SCOPES
from test_production_stock_minute_permission_preparation import minute_env as minute_env

from trade_plan_monitor.runtime.production import PermissionMaintenanceResult
from trade_plan_monitor.runtime.request_control import TushareRequestController
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.runtime_recovery import ProviderRecoveryRepository

ENDPOINTS = {MINUTE_SCOPES[0]: "rt_min_daily", MINUTE_SCOPES[1]: "rt_min"}
ENTRYPOINTS = {
    MINUTE_SCOPES[0]: "_maybe_recheck_current_day_minutes_permission",
    MINUTE_SCOPES[1]: "_maybe_recheck_realtime_minutes_permission",
}
FIELDS = ("ts_code", "time", "open", "close", "high", "low", "vol", "amount")


def row(env, at="09:30:00", day=None):
    return dict(zip(FIELDS, (
        min(plan.symbol for plan in env.plans), f"{day or env.clock.now().date()} {at}",
        "1", "1", "2", "0.50", 0, 0,
    ), strict=True))


@pytest.fixture
def execution_env(minute_env):
    controls = []
    def build(*, timeout=15, label=None, pacing=False, **kwargs):
        env = minute_env(**kwargs)
        if label is not None:
            from trade_plan_monitor.live_profiles import (
                create_stock_certification,
                write_live_certification,
            )

            original = env.pipeline._stock_evidence
            certificate = create_stock_certification(
                observed_at=original.observed_at, endpoint_url=original.endpoint_url,
                capabilities=original.capabilities, source_time_label=label,
            )
            write_live_certification(
                env.database.parent / "data/live-certification/tushare-stock-live.json",
                certificate,
            )
            env.pipeline._stock_evidence = certificate
            env.pipeline.provider._source_time_label = label
        repository = ProviderRecoveryRepository(env.sessions, provider_identity="e" * 64)
        from test_live_pipeline_acceptance import VirtualPace

        env.pace = VirtualPace()
        controller = TushareRequestController(
            clock=env.clock, executor_workers=1, max_concurrency=1,
            min_interval=timedelta(seconds=1.25 if pacing else 0),
            jitter=timedelta(0), in_cycle_retries=0,
            monotonic=env.pace.monotonic, pace_sleep=env.pace.sleep,
            timeout_seconds=timeout, recovery_repository=repository,
        )
        controls.append((controller, repository))
        env.controller = controller
        env.pipeline._controller = controller
        env.repository = repository
        env.pipeline._permission_market_window = lambda now, horizon: ()
        env.entered, env.release = Event(), Event()
        env.release.set()
        env.calls = []
        env.after_sdk = lambda: None
        env.rows = [row(env, "09:31:00" if label is not None else "09:30:00")]
        def sdk(endpoint):
            def call(**kwargs):
                assert current_thread() is not main_thread()
                response_rows = list(env.rows)
                env.calls.append((endpoint, kwargs, env.clock.now()))
                env.entered.set()
                assert env.release.wait(3)
                env.after_sdk()
                return pd.DataFrame(response_rows, columns=FIELDS, dtype=object)
            return call
        # Keep the real certification wrapper and real provider parser.
        env.pipeline.provider._client._client = SimpleNamespace(
            **{endpoint: sdk(endpoint) for endpoint in ENDPOINTS.values()},
        )
        return env
    yield build
    for controller, repository in controls:
        controller.close()
        repository.release_owner(controller)


def ready(env, operation):
    asyncio.run(_block(env.controller, operation))
    env.clock.current += timedelta(seconds=301)


def recheck(env, operation):
    return asyncio.run(getattr(env.pipeline, ENTRYPOINTS[operation])())


def persisted(env):
    engine = create_sqlite_engine(env.database)
    try:
        return ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity="e" * 64,
        ).load()
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", MINUTE_SCOPES)
def test_exact_endpoint_clears_only_own_scope_without_business_writes(execution_env, operation):
    env = execution_env()
    ready(env, operation)
    other = next(scope for scope in MINUTE_SCOPES if scope is not operation)
    asyncio.run(_block(env.controller, other))
    statements = []
    def on_sql(conn, cursor, sql, params, context, many):
        assert current_thread() is main_thread(), "worker cannot query SQLite"
        statements.append(sql)
    event.listen(env.engine, "before_cursor_execute", on_sql)
    assert recheck(env, operation) is PermissionMaintenanceResult.PROBED
    assert len(env.calls) == 1
    endpoint, request, _ = env.calls[0]
    assert endpoint == ENDPOINTS[operation]
    assert request["ts_code"] == env.plans[0].symbol and request["freq"] == "1MIN"
    assert set(request) == {"ts_code", "freq", "fields"}
    assert not env.controller.is_permission_blocked(operation)
    assert env.controller.is_permission_blocked(other)
    assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN"))
               or "provider_recovery_checkpoint" in sql for sql in statements)
    assert env.pipeline._permission_rotation_state.last_operation is operation
    assert operation not in env.pipeline._permission_probe_deferred_until
    assert any(item.scope_key == other.value for item in persisted(env))


@pytest.mark.parametrize("operation", MINUTE_SCOPES)
@pytest.mark.parametrize("kind", ["empty", "incomplete", "malformed"])
def test_no_positive_or_bad_response_retains_block_and_reservation(execution_env, operation, kind):
    env = execution_env()
    ready(env, operation)
    env.rows = [] if kind == "empty" else [row(env, "10:05:00")]
    if kind == "malformed":
        env.rows = [row(env) | {"close": "bad"}]
    captured = env.clock.now()
    assert recheck(env, operation) is PermissionMaintenanceResult.FAILED
    assert env.controller.is_permission_blocked(operation)
    assert env.controller.raw_permission_retry_at(operation) >= captured + timedelta(seconds=300)
    assert len(env.calls) == 1
    assert env.pipeline._permission_rotation_state.last_operation is operation


@pytest.mark.parametrize("offset", [31.25, 31.250001])
def test_market_guard_equality_is_reserved_for_market_work(execution_env, offset):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    before = env.controller.raw_permission_retry_at(operation)
    captured = env.clock.now()
    env.pipeline._permission_market_window = lambda now, horizon: (
        (captured + timedelta(seconds=offset), True),
    )
    expected = PermissionMaintenanceResult.DEFERRED if offset == 31.25 else (
        PermissionMaintenanceResult.PROBED
    )
    assert recheck(env, operation) is expected
    if offset == 31.25:
        assert env.calls == []
        assert env.controller.raw_permission_retry_at(operation) == before
        assert env.pipeline._permission_rotation_state.last_operation is None


@pytest.mark.parametrize("offset", [15, 15.000001])
def test_final_certification_io_precedes_unique_S_and_latest_start(
    execution_env, monkeypatch, offset,
):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    captured = env.clock.now()
    wrapper = env.pipeline.provider._client
    original = wrapper._current
    def certified():
        valid = original()
        env.clock.current = captured + timedelta(seconds=offset)
        return valid
    wrapper._current = certified
    assert recheck(env, operation) is (
        PermissionMaintenanceResult.PROBED if offset == 15 else PermissionMaintenanceResult.DEFERRED
    )
    if offset == 15:
        assert env.calls[0][2] == captured + timedelta(seconds=15)
    else:
        assert not env.calls


@pytest.mark.parametrize("field", ["started_at", "symbol", "operation", "source_label",
                                  "source_dates", "completed_count", "empty_slot"])
def test_owner_rejects_wrong_or_forged_immutable_evidence(execution_env, monkeypatch, field):
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    original = type(env.pipeline.provider).probe_current_day_minutes_permission
    def forged(provider, *args, **kwargs):
        evidence = original(provider, *args, **kwargs)
        if field == "empty_slot":
            return None
        values = {
            "started_at": evidence.started_at + timedelta(microseconds=1),
            "symbol": "003044.SZ", "operation": "rt_min",
            "source_label": SourceTimeLabel.END,
            "source_dates": (evidence.request_date,) * 1001,
            "completed_count": True,
        }
        return replace(evidence, **{field: values[field]})
    monkeypatch.setattr(type(env.pipeline.provider), "probe_current_day_minutes_permission", forged)
    assert recheck(env, operation) is PermissionMaintenanceResult.FAILED
    assert env.controller.is_permission_blocked(operation)


@pytest.mark.parametrize("change", ["identity", "calendar", "event", "event_identity", "epoch",
                                   "factory", "rollback"])
def test_response_original_identity_and_authority_are_revalidated(
    execution_env, monkeypatch, change,
):
    from test_production_stock_minute_permission_preparation import mutate

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    original = type(env.pipeline.provider).probe_current_day_minutes_permission
    def changed(provider, *args, **kwargs):
        evidence = original(provider, *args, **kwargs)
        if change == "identity":
            # The worker never queries SQLite: mutate during the next owner clock read instead.
            env.owner_change = lambda: mutate(env, "UPDATE active_plan SET revision=2")
        elif change == "calendar":
            env.owner_change = lambda: mutate(env, "DELETE FROM trading_calendar")
        elif change == "event":
            env.pipeline._calendar_revoked.set()
        elif change == "event_identity":
            old = env.pipeline._calendar_revoked
            old.set()
            env.pipeline._calendar_revoked = Event()
            assert old.is_set()
        elif change == "epoch":
            env.pipeline._calendar_epoch += 1
        elif change == "factory":
            env.pipeline._permission_session_factory = lambda: env.sessions()
        else:
            env.clock.current -= timedelta(microseconds=1)
        return evidence
    env.owner_change = None
    original_clock = env.clock.now
    def now():
        if current_thread() is main_thread() and env.owner_change is not None:
            change_once, env.owner_change = env.owner_change, None
            change_once()
        return original_clock()
    monkeypatch.setattr(env.clock, "now", now)
    monkeypatch.setattr(type(env.pipeline.provider),
                        "probe_current_day_minutes_permission", changed)
    assert recheck(env, operation) is PermissionMaintenanceResult.FAILED
    assert env.controller.is_permission_blocked(operation)


@pytest.mark.parametrize("closed_at", [11, 15])
def test_response_may_cross_lunch_or_close_without_future_capacity_recheck(
    execution_env, closed_at,
):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    if closed_at == 11:
        env.clock.current = env.clock.now().replace(hour=11, minute=29, second=59)
    else:
        env.clock.current = env.clock.now().replace(hour=14, minute=59, second=59)
    env.after_sdk = lambda: setattr(env.clock, "current", env.clock.now() + timedelta(seconds=2))
    assert recheck(env, operation) is PermissionMaintenanceResult.PROBED


@pytest.mark.parametrize("known", [True, False])
def test_all_sparse_source_dates_need_exact_persisted_facts(execution_env, known):
    env = execution_env()
    operation = MINUTE_SCOPES[1]
    ready(env, operation)
    old = env.clock.now().date() - timedelta(days=700)
    while old.weekday() >= 5:
        old -= timedelta(days=1)
    env.rows = [row(env), row(env, day=old)]
    if known:
        _seed_open_day(env.database, old)
    assert recheck(env, operation) is (
        PermissionMaintenanceResult.PROBED if known else PermissionMaintenanceResult.FAILED
    )


def test_owner_cancellation_does_not_clear_block_or_hold_lock_for_drain(execution_env):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    env.release.clear()
    async def scenario():
        attempt = asyncio.create_task(getattr(env.pipeline, ENTRYPOINTS[operation])())
        assert await asyncio.to_thread(env.entered.wait, 1)
        attempt.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attempt
        assert not env.pipeline._permission_maintenance_lock.locked()
        assert env.controller.active_count == 1
        env.release.set()
        for _ in range(100):
            if env.controller.active_count == 0:
                break
            await asyncio.sleep(0.01)
        assert env.controller.active_count == 0
        assert env.controller.is_permission_blocked(operation)
    asyncio.run(scenario())


def test_checkpoint_save_failure_leaves_rotation_unchanged(execution_env, monkeypatch):
    from trade_plan_monitor.state.runtime_recovery import RecoveryCheckpointError

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    state = env.pipeline._permission_rotation_state
    def fail(checkpoints):
        raise RecoveryCheckpointError("offline save failure")
    monkeypatch.setattr(env.repository, "save", fail)
    with pytest.raises(RecoveryCheckpointError):
        recheck(env, operation)
    assert env.pipeline._permission_rotation_state is state and not env.calls


@pytest.mark.parametrize("change", ["stop", "generation", "epoch", "event", "factory",
                                   "provider", "inner_source", "late"])
def test_final_authority_io_cannot_hide_memory_revocation(execution_env, monkeypatch, change):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    captured = env.clock.now()
    env.at_final_io = False
    original_io = env.pipeline._stock_certification_current
    original_probe = type(env.pipeline.provider).probe_current_day_minutes_permission
    def io():
        valid = original_io()
        if env.at_final_io:
            if change in ("stop", "generation"):
                monkeypatch.setattr(env.pipeline, "_admission_revoked" if change == "stop"
                                    else "_generation_current", lambda: change == "stop")
            elif change == "epoch":
                env.pipeline._calendar_epoch += 1
            elif change == "event":
                env.pipeline._calendar_revoked.set()
            elif change == "factory":
                env.pipeline._permission_session_factory = lambda: env.sessions()
            elif change == "provider":
                from copy import copy
                env.pipeline.provider = copy(env.pipeline.provider)
            elif change == "inner_source":
                env.pipeline.provider._client._client = object()
            else:
                env.clock.current = captured + timedelta(seconds=15, microseconds=1)
        return valid
    def traced(provider, *args, physical_start):
        def start():
            env.at_final_io = True
            return physical_start()
        return original_probe(provider, *args, physical_start=start)
    monkeypatch.setattr(env.pipeline, "_stock_certification_current", io)
    monkeypatch.setattr(type(env.pipeline.provider), "probe_current_day_minutes_permission", traced)
    assert recheck(env, operation) is PermissionMaintenanceResult.DEFERRED
    assert env.calls == []
    assert env.controller.is_permission_blocked(operation)
    assert env.controller.raw_permission_retry_at(operation) >= captured + timedelta(seconds=300)


def test_unique_S_has_no_following_authority_io_or_clock_resample(execution_env, monkeypatch):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    after_sample = Event()
    samples = []
    original_io = env.pipeline._stock_certification_current
    original_now = env.clock.now
    original_probe = type(env.pipeline.provider).probe_current_day_minutes_permission
    sdk = env.pipeline.provider._client._client
    original_sdk = sdk.rt_min_daily
    def io():
        assert not after_sample.is_set(), "authority I/O after S"
        return original_io()
    def now():
        assert not after_sample.is_set(), "clock resampled after S before SDK"
        return original_now()
    def traced(provider, *args, physical_start):
        def start():
            result = physical_start()
            samples.append(result)
            after_sample.set()
            return result
        return original_probe(provider, *args, physical_start=start)
    def endpoint(**kwargs):
        assert after_sample.is_set()
        after_sample.clear()
        return original_sdk(**kwargs)
    monkeypatch.setattr(env.clock, "now", now)
    monkeypatch.setattr(env.pipeline, "_stock_certification_current", io)
    monkeypatch.setattr(type(env.pipeline.provider), "probe_current_day_minutes_permission", traced)
    sdk.rt_min_daily = endpoint
    assert recheck(env, operation) is PermissionMaintenanceResult.PROBED
    assert len(samples) == 1 and samples[0] == env.calls[0][2]


@pytest.mark.parametrize("known", [True, False])
def test_unknown_B_only_source_date_cannot_borrow_A_proof(execution_env, known):
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel

    env = execution_env(label=SourceTimeLabel.END)
    operation = MINUTE_SCOPES[1]
    ready(env, operation)
    old = env.clock.now().date() - timedelta(days=700)
    env.rows = [row(env, "09:31:00"), row(env, "09:30:00", old), row(env, "10:06:00")]
    if known:
        _seed_open_day(env.database, old)
    assert recheck(env, operation) is (
        PermissionMaintenanceResult.PROBED if known else PermissionMaintenanceResult.FAILED
    )


def test_1000_sparse_dates_plus_request_day_share_one_response_transaction(
    execution_env, monkeypatch,
):
    from sqlalchemy.dialects.sqlite import insert

    from trade_plan_monitor.state.models import TradingCalendar

    env = execution_env()
    operation = MINUTE_SCOPES[1]
    ready(env, operation)
    day = env.clock.now().date()
    dates = tuple(day - timedelta(days=7 * (i + 1)) for i in range(1000))
    with env.sessions.begin() as session:
        statement = insert(TradingCalendar).on_conflict_do_update(
            index_elements=["exchange", "cal_date"], set_={"is_open": True},
        )
        session.execute(statement, [
            {"exchange": "SSE", "cal_date": source_day, "is_open": True} for source_day in dates
        ])
    env.rows = [row(env, day=source_day) for source_day in dates]
    sessions, chunks, begins = [], [], []
    phase = "selection"
    original_prepare = env.pipeline._prepare_stock_minute_permission_locked
    def prepare(operation):
        nonlocal phase
        phase = "execution"
        return original_prepare(operation)
    monkeypatch.setattr(env.pipeline, "_prepare_stock_minute_permission_locked", prepare)
    def factory():
        session = env.sessions()
        stage = "response" if env.calls else phase
        sessions.append((stage, session))
        event.listen(session, "after_begin", lambda s, tx, conn: begins.append((stage, s)))
        return session
    monkeypatch.setattr(env.pipeline, "_permission_session_factory", factory)
    monkeypatch.setattr(env.pipeline, "_work", lambda: pytest.fail("no second UnitOfWork"))
    def sql(conn, cursor, statement, params, context, many):
        if env.calls and "FROM trading_calendar" in statement:
            assert " IN (" in statement and " >= " not in statement
            chunks.append((statement, params))
    event.listen(env.engine, "before_cursor_execute", sql)
    assert recheck(env, operation) is PermissionMaintenanceResult.PROBED
    assert sessions == begins
    assert [stage for stage, _ in sessions] == ["selection", "execution", "response"]
    assert len({id(session) for _, session in sessions}) == 3
    execution_sessions = [session for stage, session in sessions if stage != "selection"]
    assert len(execution_sessions) == 2 and execution_sessions[0] is not execution_sessions[1]
    assert len(chunks) == 5
    queried = [date for _, params in chunks for date in params[1:-2]]
    assert set(queried) == {source_day.isoformat() for source_day in (*dates, day)}
    assert len(queried) == 1001


def test_cancel_requested_before_outer_catch_cannot_clear(execution_env, monkeypatch):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    original = env.controller.recheck_permission
    owner = None
    async def intercepted(controller, *args, validate_after, **kwargs):
        def cancel_before_validation():
            owner.cancel()
            assert owner.cancelling() and not owner.done()
            return validate_after()
        return await original(*args, validate_after=cancel_before_validation, **kwargs)
    monkeypatch.setattr(type(env.controller), "recheck_permission", intercepted)
    async def scenario():
        nonlocal owner
        owner = asyncio.create_task(getattr(env.pipeline, ENTRYPOINTS[operation])())
        with pytest.raises(asyncio.CancelledError):
            await owner
        assert env.controller.is_permission_blocked(operation)
    asyncio.run(scenario())


@pytest.mark.parametrize("code", ["ERROR", "CLOSED", "QUEUE_FULL"])
def test_unexpected_controller_errors_propagate_without_closing_it(
    execution_env, monkeypatch, code,
):
    from trade_plan_monitor.runtime.request_control import (
        RequestControlError,
        RequestControlErrorCode,
    )

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    error = RequestControlError(RequestControlErrorCode(code), operation, attempts=0)
    async def rejected(*args, **kwargs):
        raise error
    monkeypatch.setattr(type(env.controller), "recheck_permission", rejected)
    monkeypatch.setattr(type(env.controller), "close",
                        lambda self: pytest.fail("owner cannot close controller"))
    with pytest.raises(RequestControlError) as caught:
        recheck(env, operation)
    assert caught.value is error
    monkeypatch.undo()


def test_response_sql_and_callback_errors_propagate(execution_env, monkeypatch):
    from sqlalchemy.exc import OperationalError

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    def fail(conn, cursor, sql, params, context, many):
        if env.calls and "FROM trading_calendar" in sql:
            raise OperationalError(sql, params, RuntimeError("response SQL error"))
    event.listen(env.engine, "before_cursor_execute", fail)
    with pytest.raises(OperationalError):
        recheck(env, operation)
    assert env.controller.is_permission_blocked(operation)


def test_callback_failure_propagates_after_durable_reservation(execution_env, monkeypatch):
    from trade_plan_monitor.runtime.request_control import PermissionReservationCallbackError

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    state = env.pipeline._permission_rotation_state
    def fail():
        raise RuntimeError("offline callback failure")
    monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback", lambda c: fail)
    with pytest.raises(PermissionReservationCallbackError):
        recheck(env, operation)
    assert env.pipeline._permission_rotation_state is state and not env.calls
    assert any(item.retry_at >= env.clock.now() + timedelta(seconds=300) for item in persisted(env))


@pytest.mark.parametrize("family", ["explicit", "mixed"])
@pytest.mark.parametrize("operation", MINUTE_SCOPES)
def test_real_explicit_and_mixed_consumers_recover(execution_env, family, operation):
    env = execution_env(family=family)
    ready(env, operation)
    assert recheck(env, operation) is PermissionMaintenanceResult.PROBED
    assert env.calls[0][1]["ts_code"] == min(plan.symbol for plan in env.plans)


@pytest.mark.parametrize("change", ["aba", "same_hash_revision", "other_symbol"])
def test_response_cannot_substitute_another_complete_consumer(execution_env, monkeypatch, change):
    from test_production_stock_minute_permission_preparation import mutate

    env = execution_env(count=2)
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    original_now = env.clock.now
    changed = False
    def now():
        nonlocal changed
        if env.calls and current_thread() is main_thread() and not changed:
            changed = True
            symbol = min(plan.symbol for plan in env.plans)
            if change == "other_symbol":
                mutate(env, "DELETE FROM active_plan WHERE symbol=:symbol", {"symbol": symbol})
            else:
                # The final pointers/hash can return to the same values; activation revision cannot.
                for table in ("active_plan", "plan_activation_state"):
                    mutate(env, f"UPDATE {table} SET revision=revision+:delta WHERE symbol=:symbol",
                           {"symbol": symbol, "delta": 2 if change == "aba" else 1})
        return original_now()
    monkeypatch.setattr(env.clock, "now", now)
    assert recheck(env, operation) is PermissionMaintenanceResult.FAILED
    assert env.controller.is_permission_blocked(operation)


@pytest.mark.parametrize("outcome", ["success", "invalid", "queue_veto"])
def test_durable_callback_once_preserves_other_symbol_and_daily_bar_cursors(
    execution_env, monkeypatch, outcome,
):
    env = execution_env(count=2)
    operation = MINUTE_SCOPES[1]
    ready(env, operation)
    captured = env.clock.now()
    state = replace(env.pipeline._permission_rotation_state,
                    official_pair=("600000.SH", captured.date()),
                    fallback_pair=("600001.SH", captured.date()), next_daily_bar_pool="F",
                    current_day_minute_symbol="003044.SZ")
    env.pipeline._permission_rotation_state = state
    callbacks = []
    original = env.pipeline._permission_probe_reservation_callback
    def callback(candidate):
        acknowledge = original(candidate)
        def reserved():
            assert env.pipeline._permission_maintenance_lock.locked()
            assert any(item.scope_key == operation.value
                       and item.retry_at >= captured + timedelta(seconds=300)
                       for item in persisted(env))
            callbacks.append(candidate)
            acknowledge()
            if outcome == "queue_veto":
                env.pipeline._calendar_revoked.set()
            else:
                # Force a later physical floor extension, which must not acknowledge again.
                env.clock.current += timedelta(seconds=2)
        return reserved
    monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback", callback)
    if outcome == "invalid":
        env.rows = []
    assert recheck(env, operation) is {
        "success": PermissionMaintenanceResult.PROBED,
        "invalid": PermissionMaintenanceResult.FAILED,
        "queue_veto": PermissionMaintenanceResult.DEFERRED,
    }[outcome]
    assert len(callbacks) == 1
    current = env.pipeline._permission_rotation_state
    assert current.last_operation is operation and current.realtime_minute_symbol == "003043.SZ"
    assert (current.current_day_minute_symbol, current.official_pair,
            current.fallback_pair, current.next_daily_bar_pool) == (
        state.current_day_minute_symbol, state.official_pair,
        state.fallback_pair, state.next_daily_bar_pool,
    )
    if outcome != "success":
        assert any(item.scope_key == operation.value
                   and item.retry_at >= env.clock.now() + timedelta(seconds=300)
                   for item in persisted(env))


@pytest.mark.parametrize("kind", ["permission", "429", "transient", "invalid", "program"])
def test_real_provider_failures_keep_endpoint_block_and_shared_429(
    execution_env, kind,
):
    from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
    from trade_plan_monitor.runtime.request_control import RequestControlError

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    other = MINUTE_SCOPES[1]
    asyncio.run(_block(env.controller, other))
    env.clock.current += timedelta(seconds=301)
    def fail():
        if kind == "program":
            raise RuntimeError("local programming fault")
        raise TushareProviderError({
            "permission": TushareErrorCode.BLOCKED_PERMISSION,
            "429": TushareErrorCode.RATE_LIMITED,
            "transient": TushareErrorCode.TRANSIENT,
            "invalid": TushareErrorCode.INVALID_RESPONSE,
        }[kind], "rt_min_daily")
    env.after_sdk = fail
    if kind == "program":
        with pytest.raises(RequestControlError) as error:
            recheck(env, operation)
        assert error.value.code.value == "ERROR"
    else:
        assert recheck(env, operation) is PermissionMaintenanceResult.FAILED
    assert env.controller.is_permission_blocked(operation)
    assert env.controller.is_permission_blocked(other)
    assert len(env.calls) == 1
    if kind == "429":
        assert env.controller.cooldown_until > env.clock.now()
        state = env.pipeline._permission_rotation_state
        assert recheck(env, other) is PermissionMaintenanceResult.SKIPPED
        assert env.pipeline._permission_rotation_state is state and len(env.calls) == 1
        assert any(item.kind == "cooldown" and item.scope_key == "shared"
                   and item.retry_at == env.controller.cooldown_until for item in persisted(env))


def test_one_worker_pacing_is_shared_by_the_two_real_owner_endpoints(execution_env):
    env = execution_env(pacing=True)
    for operation in MINUTE_SCOPES:
        asyncio.run(_block(env.controller, operation))
    env.clock.current += timedelta(seconds=301)
    starts = []
    env.after_sdk = lambda: starts.append(env.pace.monotonic())
    for operation in MINUTE_SCOPES:
        assert recheck(env, operation) is PermissionMaintenanceResult.PROBED
    assert len(starts) == 2 and starts[1] - starts[0] >= 1.25


@pytest.mark.parametrize("action", ["cancel", "revocation"])
def test_queued_owner_cannot_start_after_cancel_or_revocation(execution_env, action):
    from trade_plan_monitor.runtime.request_control import TushareOperation

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    occupied, release = Event(), Event()
    def market():
        occupied.set()
        assert release.wait(3)
    async def scenario():
        busy = asyncio.create_task(env.controller.execute(
            TushareOperation.DAILY_LIMITS, market, work_key="market-work",
        ))
        assert await asyncio.to_thread(occupied.wait, 1)
        owner = asyncio.create_task(getattr(env.pipeline, ENTRYPOINTS[operation])())
        for _ in range(100):
            if env.pipeline._permission_rotation_state.last_operation is operation:
                break
            await asyncio.sleep(0.001)
        assert env.pipeline._permission_rotation_state.last_operation is operation
        if action == "cancel":
            owner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner
        else:
            env.pipeline._calendar_revoked.set()
        release.set()
        await busy
        if action == "revocation":
            assert await owner is PermissionMaintenanceResult.DEFERRED
        for _ in range(100):
            if not env.controller._permission_rechecks:
                break
            await asyncio.sleep(0.001)
        assert not env.controller._permission_rechecks
        assert not env.calls and env.controller.is_permission_blocked(operation)
        assert not env.pipeline._permission_maintenance_lock.locked()
    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_timeout_late_success_cannot_feed_next_owner_slot_or_release_worker_early(execution_env):
    env = execution_env(timeout=0.05)
    first, second = MINUTE_SCOPES
    for operation in MINUTE_SCOPES:
        asyncio.run(_block(env.controller, operation))
    env.clock.current += timedelta(seconds=301)
    env.release.clear()
    async def scenario():
        first_owner = asyncio.create_task(getattr(env.pipeline, ENTRYPOINTS[first])())
        assert await asyncio.to_thread(env.entered.wait, 1)
        assert await first_owner is PermissionMaintenanceResult.FAILED
        assert env.controller.active_count == 1
        second_owner = asyncio.create_task(getattr(env.pipeline, ENTRYPOINTS[second])())
        await asyncio.sleep(0.01)
        assert len(env.calls) == 1 and env.controller.active_count == 1
        # The old proof is positive; only the second request's empty result is authoritative there.
        env.rows = []
        env.release.set()
        assert await second_owner is PermissionMaintenanceResult.FAILED
        assert len(env.calls) == 2
        assert all(env.controller.is_permission_blocked(operation) for operation in MINUTE_SCOPES)
        assert not env.pipeline._permission_maintenance_lock.locked()
    try:
        asyncio.run(scenario())
    finally:
        env.release.set()


@pytest.mark.parametrize("boundary", ["reservation", "queue", "worker", "physical"])
def test_configuration_revocation_at_all_four_owner_start_gates(
    execution_env, monkeypatch, boundary,
):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    original_due = env.controller.raw_permission_retry_at(operation)
    original_state = env.pipeline._permission_rotation_state
    prepared_count = []
    prepare = env.pipeline._prepare_stock_minute_permission_locked
    def revoke():
        monkeypatch.setattr(env.pipeline, "_configuration_current", lambda: False)
    def prepared(scope):
        assert env.pipeline._permission_maintenance_lock.locked()
        prepared_count.append(scope)
        result = prepare(scope)
        if boundary == "reservation":
            revoke()
        return result
    monkeypatch.setattr(env.pipeline, "_prepare_stock_minute_permission_locked", prepared)
    if boundary == "queue":
        original_callback = env.pipeline._permission_probe_reservation_callback
        def callback(candidate):
            acknowledge = original_callback(candidate)
            def reserved():
                acknowledge()
                revoke()
            return reserved
        monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback", callback)
    elif boundary == "worker":
        original = type(env.controller).recheck_permission
        async def intercepted(controller, *args, can_start, **kwargs):
            def admission():
                result = can_start()
                revoke()
                return result
            return await original(controller, *args, can_start=admission, **kwargs)
        monkeypatch.setattr(type(env.controller), "recheck_permission", intercepted)
    elif boundary == "physical":
        original_probe = type(env.pipeline.provider).probe_current_day_minutes_permission
        def probe(provider, *args, **kwargs):
            revoke()
            return original_probe(provider, *args, **kwargs)
        monkeypatch.setattr(type(env.pipeline.provider),
                            "probe_current_day_minutes_permission", probe)
    assert recheck(env, operation) is PermissionMaintenanceResult.DEFERRED
    assert not env.calls and prepared_count == [operation]
    if boundary == "reservation":
        assert env.pipeline._permission_rotation_state is original_state
        assert env.controller.raw_permission_retry_at(operation) == original_due
    else:
        assert env.pipeline._permission_rotation_state.last_operation is operation
        assert env.controller.raw_permission_retry_at(operation) >= (
            env.clock.now() + timedelta(seconds=300)
        )


def test_response_future_capacity_not_rechecked_and_classification_stays_frozen(execution_env):
    env = execution_env()
    operation = MINUTE_SCOPES[1]
    ready(env, operation)
    captured = env.clock.now()
    env.rows = [row(env), row(env, "10:05:00")]
    env.pipeline._permission_market_window = lambda now, horizon: (
        (captured + timedelta(seconds=32), True),
    )
    env.after_sdk = lambda: setattr(env.clock, "current", captured + timedelta(seconds=10))
    assert recheck(env, operation) is PermissionMaintenanceResult.PROBED
    assert len(env.calls) == 1


def test_response_borrowed_factory_is_error_without_touching_callers_transaction(
    execution_env, monkeypatch,
):
    from sqlalchemy import text

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    with env.sessions() as borrowed:
        borrowed.execute(text("SELECT 1"))
        transaction = borrowed.get_transaction()
        def factory():
            return borrowed if env.calls else env.sessions()
        monkeypatch.setattr(env.pipeline, "_permission_session_factory", factory)
        with pytest.raises(ValueError, match="fresh session"):
            recheck(env, operation)
        assert borrowed.get_transaction() is transaction
        assert borrowed.scalar(text("SELECT 1")) == 1
        assert env.controller.is_permission_blocked(operation)


def test_owner_checks_requested_cancel_after_response_snapshot(execution_env):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    owner = None
    def after_sql(conn, cursor, sql, params, context, many):
        if env.calls and "FROM trading_calendar" in sql:
            owner.cancel()
            assert owner.cancelling() and not owner.done()
    event.listen(env.engine, "after_cursor_execute", after_sql)
    async def scenario():
        nonlocal owner
        owner = asyncio.create_task(getattr(env.pipeline, ENTRYPOINTS[operation])())
        with pytest.raises(asyncio.CancelledError):
            await owner
        assert env.controller.is_permission_blocked(operation)
    asyncio.run(scenario())


def test_worker_never_accesses_task_and_preserves_not_started_sentinel(
    execution_env, monkeypatch,
):
    from trade_plan_monitor.runtime.request_control import RequestNotStartedError

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    original_task = asyncio.current_task
    def task(*args, **kwargs):
        assert current_thread() is main_thread(), "worker cannot access Task objects"
        return original_task(*args, **kwargs)
    monkeypatch.setattr(asyncio, "current_task", task)
    sentinel = RequestNotStartedError("unchanged sentinel")
    env.pipeline.provider._client._current = lambda: (_ for _ in ()).throw(sentinel)
    original = type(env.controller).recheck_permission
    seen = []
    async def intercepted(controller, *args, **kwargs):
        try:
            return await original(controller, *args, **kwargs)
        except RequestNotStartedError as caught:
            seen.append(caught)
            raise
    monkeypatch.setattr(type(env.controller), "recheck_permission", intercepted)
    assert recheck(env, operation) is PermissionMaintenanceResult.DEFERRED
    assert seen == [sentinel] and not env.calls


@pytest.mark.parametrize("expiry_offset_us", [0, 1])
def test_original_legacy_expiry_preserves_real_loader_inclusive_boundary(
    execution_env, monkeypatch, expiry_offset_us,
):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    # Supply a valid certificate whose expiry occurs within this legal start window.
    from trade_plan_monitor.live_profiles import (
        create_stock_certification,
        load_stock_certification,
        write_live_certification,
    )
    certificate = env.pipeline._stock_evidence
    lifetime = certificate.valid_until - certificate.observed_at
    certificate = create_stock_certification(
        observed_at=env.clock.now() + timedelta(seconds=10) - lifetime,
        endpoint_url=certificate.endpoint_url, capabilities=certificate.capabilities,
        source_time_label=certificate.source_time_label,
    )
    env.pipeline._stock_evidence = certificate
    write_live_certification(
        env.database.parent / "data/live-certification/tushare-stock-live.json", certificate,
    )
    certificate_path = env.database.parent / "data/live-certification/tushare-stock-live.json"
    assert load_stock_certification(
        certificate_path, now=certificate.valid_until, endpoint_url=certificate.endpoint_url,
    ) == certificate
    assert load_stock_certification(
        certificate_path, now=certificate.valid_until + timedelta(microseconds=1),
        endpoint_url=certificate.endpoint_url,
    ) is None
    original_probe = type(env.pipeline.provider).probe_current_day_minutes_permission
    original_io = env.pipeline._stock_certification_current
    final = False
    def io():
        valid = original_io()
        if final:
            env.clock.current = certificate.valid_until + timedelta(microseconds=expiry_offset_us)
        return valid
    def probe(provider, *args, physical_start):
        def start():
            nonlocal final
            final = True
            return physical_start()
        return original_probe(provider, *args, physical_start=start)
    monkeypatch.setattr(env.pipeline, "_stock_certification_current", io)
    monkeypatch.setattr(type(env.pipeline.provider), "probe_current_day_minutes_permission", probe)
    assert recheck(env, operation) is (
        PermissionMaintenanceResult.PROBED if expiry_offset_us == 0
        else PermissionMaintenanceResult.DEFERRED
    )
    assert len(env.calls) == (1 if expiry_offset_us == 0 else 0)
    assert env.controller.is_permission_blocked(operation) is (expiry_offset_us != 0)


@pytest.mark.parametrize("change", ["none", "missing_binding", "revision", "mode"])
def test_semantic_owner_uses_original_authority_not_old_certification_expiry(
    execution_env, monkeypatch, change,
):
    from test_production_stock_minute_permission_preparation import mutate

    from trade_plan_monitor.domain.daily_plan_models import DailyRangeActivation
    from trade_plan_monitor.domain.plan_codec import dump_plan_json
    from trade_plan_monitor.domain.plan_hash import plan_sha256
    from trade_plan_monitor.runtime.production import (
        ProductionSemanticBindings,
        SemanticContractBinding,
    )
    from trade_plan_monitor.runtime.provider_contract import import_stock_semantic_contract

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    plan = env.plans[0].model_copy(update={"activation": DailyRangeActivation(mode="DATE_RANGE",
        start_date=env.clock.now().date(), end_date=env.clock.now().date() + timedelta(days=10),
    )})
    mutate(env, "UPDATE plan_version SET payload_json=:payload, plan_hash=:hash", {
        "payload": dump_plan_json(plan), "hash": plan_sha256(plan),
    })
    sidecar = env.database.parent / "stock-semantic.json"
    semantic = import_stock_semantic_contract(
        env.database.parent / "data/live-certification/tushare-stock-live.json", sidecar,
        now=env.clock.now(), endpoint_url="https://example.test",
        installed_sdk_version=lambda: "1.4.29",
    )
    assert semantic is not None
    env.pipeline._semantic_bindings = ProductionSemanticBindings(
        stock=SemanticContractBinding(sidecar, semantic.semantic_revision), index=None,
        installed_sdk_version=lambda: "1.4.29",
    )
    env.pipeline._stock_semantics = semantic
    env.clock.current = semantic.provenance.valid_until + timedelta(days=1)
    while env.clock.now().weekday() >= 5:
        env.clock.current += timedelta(days=1)
    env.clock.current = env.clock.now().replace(hour=10, minute=0, second=0)
    _seed_open_day(env.database, env.clock.now().date())
    env.rows = [row(env)]
    original_probe = type(env.pipeline.provider).probe_current_day_minutes_permission
    def probe(provider, *args, **kwargs):
        if change == "missing_binding":
            env.pipeline._semantic_bindings = ProductionSemanticBindings(stock=None, index=None)
        elif change == "revision":
            env.pipeline._stock_semantics = semantic.model_copy(
                update={"semantic_revision": "f" * 64},
            )
        elif change == "mode":
            env.pipeline._semantic_bindings = None
        return original_probe(provider, *args, **kwargs)
    monkeypatch.setattr(type(env.pipeline.provider), "probe_current_day_minutes_permission", probe)
    assert recheck(env, operation) is (
        PermissionMaintenanceResult.PROBED if change == "none"
        else PermissionMaintenanceResult.DEFERRED
    )
    assert len(env.calls) == (1 if change == "none" else 0)


def test_response_identity_and_calendar_share_explicit_snapshot_across_writer(execution_env):
    from sqlalchemy import text

    env = execution_env()
    operation = MINUTE_SCOPES[1]
    ready(env, operation)
    changed = []
    facts = []
    def after_read(conn, cursor, sql, params, context, many):
        if not env.calls or not sql.lstrip().upper().startswith("SELECT"):
            return
        if "FROM plan_version" in sql or "FROM trading_calendar" in sql:
            assert conn.connection.driver_connection.in_transaction
            facts.append(conn)
        if "FROM plan_version" in sql and not changed:
            changed.append(True)
            with env.sessions.begin() as writer:
                writer.execute(text("DELETE FROM trading_calendar"))
    event.listen(env.engine, "after_cursor_execute", after_read)
    assert recheck(env, operation) is PermissionMaintenanceResult.PROBED
    assert changed and len(facts) >= 2 and all(conn is facts[0] for conn in facts)
    event.remove(env.engine, "after_cursor_execute", after_read)
    ready(env, operation)
    assert recheck(env, operation) is PermissionMaintenanceResult.DEFERRED
    assert len(env.calls) == 1


def test_response_split_bound_session_is_error_and_remains_caller_owned(execution_env, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from trade_plan_monitor.state.models import TradingCalendar

    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    other = create_sqlite_engine(env.database.parent / "other-unused.sqlite")
    invalid = Session(bind=env.engine, binds={TradingCalendar: other})
    closed = []
    original_close = invalid.close
    monkeypatch.setattr(invalid, "close", lambda: closed.append(True))
    def factory():
        return invalid if env.calls else env.sessions()
    monkeypatch.setattr(env.pipeline, "_permission_session_factory", factory)
    try:
        with pytest.raises(ValueError, match="one engine"):
            recheck(env, operation)
        assert not closed and not invalid.in_transaction()
        assert invalid.scalar(text("SELECT 1")) == 1
    finally:
        original_close()
        other.dispose()


def test_coalesced_controller_waiter_does_not_advance_owner_cursor_twice(
    execution_env, monkeypatch,
):
    env = execution_env()
    operation = MINUTE_SCOPES[0]
    ready(env, operation)
    env.release.clear()
    callbacks = []
    original = env.pipeline._permission_probe_reservation_callback
    def callback(candidate):
        advance = original(candidate)
        def reserved():
            callbacks.append(candidate)
            advance()
        return reserved
    monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback", callback)
    async def scenario():
        owner = asyncio.create_task(getattr(env.pipeline, ENTRYPOINTS[operation])())
        assert await asyncio.to_thread(env.entered.wait, 1)
        waiter = asyncio.create_task(env.controller.recheck_permission(
            operation, lambda: pytest.fail("coalesced physical call"), work_key="coalesced",
            validate_after=lambda: pytest.fail("coalesced validator"),
            on_reserved=lambda: pytest.fail("coalesced reservation"),
        ))
        await asyncio.sleep(0)
        env.release.set()
        assert await owner is PermissionMaintenanceResult.PROBED
        await waiter
        assert len(callbacks) == len(env.calls) == 1
    try:
        asyncio.run(scenario())
    finally:
        env.release.set()


@pytest.mark.parametrize("kind", ["list_dates", "datetime_date", "future_date", "negative_count",
                                 "over_count", "wrong_request_date", "rollback_R", "late_R"])
def test_owner_rejects_malformed_proof_envelope_even_from_provider_replacement(
    execution_env, monkeypatch, kind,
):
    env = execution_env()
    operation = MINUTE_SCOPES[1]
    ready(env, operation)
    original = type(env.pipeline.provider).probe_realtime_minutes_permission
    def forged(provider, *args, **kwargs):
        proof = original(provider, *args, **kwargs)
        values = {
            "list_dates": {"source_dates": [proof.request_date]},
            "datetime_date": {"source_dates": (proof.started_at,)},
            "future_date": {"source_dates": (proof.request_date + timedelta(days=1),)},
            "negative_count": {"opening_count": -1},
            "over_count": {"completed_count": 1001},
            "wrong_request_date": {"request_date": proof.request_date + timedelta(days=1)},
            "rollback_R": {"received_at": proof.started_at - timedelta(microseconds=1)},
            "late_R": {"received_at": proof.started_at + timedelta(seconds=15, microseconds=1)},
        }
        return replace(proof, **values[kind])
    monkeypatch.setattr(type(env.pipeline.provider), "probe_realtime_minutes_permission", forged)
    assert recheck(env, operation) is PermissionMaintenanceResult.FAILED
    assert env.controller.is_permission_blocked(operation)


@pytest.mark.parametrize("mode", ["unknown", "closed", "weekend_open"])
def test_real_owner_rejects_bad_source_calendar_facts(execution_env, mode):
    from sqlalchemy import text

    env = execution_env()
    operation = MINUTE_SCOPES[1]
    ready(env, operation)
    old = env.clock.now().date() - timedelta(days=700)
    if mode == "weekend_open":
        while old.weekday() != 5:
            old -= timedelta(days=1)
    env.rows = [row(env), row(env, day=old)]
    if mode != "unknown":
        _seed_open_day(env.database, old)
        if mode == "closed":
            with env.sessions.begin() as session:
                session.execute(text("UPDATE trading_calendar SET is_open=0 WHERE cal_date=:day"),
                                {"day": old.isoformat()})
    assert recheck(env, operation) is PermissionMaintenanceResult.FAILED


def test_failure_fixed_defer_and_success_only_remove_own_local_defer(execution_env, monkeypatch):
    env = execution_env()
    operation, other = MINUTE_SCOPES
    ready(env, operation)
    captured = env.clock.now()
    original_probe = type(env.pipeline.provider).probe_current_day_minutes_permission
    from trade_plan_monitor.runtime.request_control import RequestNotStartedError
    def rejected(*args, **kwargs):
        raise RequestNotStartedError("local revocation")
    monkeypatch.setattr(type(env.pipeline.provider),
                        "probe_current_day_minutes_permission", rejected)
    assert recheck(env, operation) is PermissionMaintenanceResult.DEFERRED
    due = env.pipeline._permission_probe_deferred_until[operation]
    assert due == captured + timedelta(seconds=30)
    for _ in range(3):
        env.clock.current += timedelta(seconds=1)
        env.pipeline.next_permission_probe_due_at()
        assert env.pipeline._permission_probe_deferred_until[operation] == due
    monkeypatch.setattr(type(env.pipeline.provider), "probe_current_day_minutes_permission",
                        original_probe)
    env.clock.current = captured + timedelta(seconds=301)
    other_defer = env.clock.now() + timedelta(seconds=40)
    env.pipeline._permission_probe_deferred_until[other] = other_defer
    assert recheck(env, operation) is PermissionMaintenanceResult.PROBED
    assert operation not in env.pipeline._permission_probe_deferred_until
    assert env.pipeline._permission_probe_deferred_until[other] == other_defer


@pytest.mark.parametrize("kind", ["three_C", "START_B", "END_excess_B", "daily_excess_ordinary",
                                 "realtime_excess_ordinary", "C_without_request_date"])
def test_owner_retains_provider_category_count_bounds(execution_env, monkeypatch, kind):
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel

    env = execution_env(label=SourceTimeLabel.END if kind == "END_excess_B" else None)
    operation = MINUTE_SCOPES[0] if kind == "daily_excess_ordinary" else MINUTE_SCOPES[1]
    ready(env, operation)
    old = env.clock.now().date() - timedelta(days=700)
    _seed_open_day(env.database, old)
    method = ("probe_current_day_minutes_permission" if operation is MINUTE_SCOPES[0]
              else "probe_realtime_minutes_permission")
    original = getattr(type(env.pipeline.provider), method)
    def forged(provider, *args, **kwargs):
        proof = original(provider, *args, **kwargs)
        values = {
            "three_C": {"incomplete_count": 3},
            "START_B": {"opening_count": 1},
            "END_excess_B": {"opening_count": 2},
            "daily_excess_ordinary": {"completed_count": 241},
            "realtime_excess_ordinary": {"completed_count": 241},
            "C_without_request_date": {"source_dates": (old,), "incomplete_count": 1},
        }
        return replace(proof, **values[kind])
    monkeypatch.setattr(type(env.pipeline.provider), method, forged)
    assert recheck(env, operation) is PermissionMaintenanceResult.FAILED
    assert env.controller.is_permission_blocked(operation)
