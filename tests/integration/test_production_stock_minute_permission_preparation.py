"""Offline stock-minute preparation: real activation, no provider execution."""

import asyncio
from contextlib import ExitStack
from dataclasses import FrozenInstanceError
from datetime import datetime, time, timedelta
from threading import Event

import pytest
from sqlalchemy import event, text
from test_explicit_runtime_production import _plan as explicit_plan
from test_explicit_runtime_production import _seed_active as seed_explicit
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    _activate_plans,
    _sample_plan,
    _write_configuration_and_evidence,
)
from test_permission_candidate_selection import _block, _seed_open_day
from test_production_daily_bar_permission_preparation import harness

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import DateRangeActivation
from trade_plan_monitor.live_profiles import load_stock_certification
from trade_plan_monitor.runtime.request_control import TushareOperation

MINUTE_SCOPES = (
    TushareOperation.CURRENT_DAY_MINUTES,
    TushareOperation.REALTIME_MINUTES,
)


@pytest.fixture
def minute_env(tmp_path, monkeypatch):
    with ExitStack() as stack:
        def build(*, family="legacy", count=1, calendar=True, **kwargs):
            env = stack.enter_context(harness(
                tmp_path, monkeypatch, today=True,
                count=0 if family == "explicit" else count, **kwargs,
            ))
            if family in ("explicit", "mixed"):
                plan = explicit_plan(active_date=NOW.date()).model_copy(update={
                    "symbol": "003042.SZ", "plan_id": "minute-explicit",
                })
                monkeypatch.setattr("test_explicit_runtime_production.PREPARED_AT",
                                    NOW.replace(hour=9, minute=0, second=0))
                seed_explicit(env.engine, plan)
                env.plans = (*env.plans, plan)
            if calendar:
                _seed_open_day(env.database, NOW.date())
            # Window cases legitimately predate NOW; certification must predate them too.
            _write_configuration_and_evidence(
                tmp_path, observed_at=NOW.replace(hour=8, minute=0), include_index=False,
            )
            env.pipeline._stock_evidence = load_stock_certification(
                tmp_path / "data/live-certification/tushare-stock-live.json",
                now=NOW, endpoint_url="https://example.test",
            )
            return env
        yield build


def ready(env, operation=MINUTE_SCOPES[0]):
    asyncio.run(_block(env.controller, operation))
    env.clock.current += timedelta(seconds=301)


def mutate(env, sql, params=None):
    with env.sessions.begin() as session:
        session.execute(text(sql), params or {})


def prepare(env, operation):
    async def under_owner_lock():
        async with env.pipeline._permission_maintenance_lock:
            return env.pipeline._prepare_stock_minute_permission_locked(operation)

    return asyncio.run(under_owner_lock())


@pytest.mark.parametrize("operation", MINUTE_SCOPES)
def test_today_consumer_prepares_in_one_read_snapshot_without_reservation(
    tmp_path, monkeypatch, operation,
):
    with harness(tmp_path, monkeypatch, today=True) as env:
        _seed_open_day(env.database, env.clock.now().date())
        asyncio.run(_block(env.controller, operation))
        env.clock.current += timedelta(seconds=301)
        raw_due = env.controller.raw_permission_retry_at(operation)
        rotation = env.pipeline._permission_rotation_state
        statements = []
        event.listen(env.engine, "before_cursor_execute",
                     lambda conn, cursor, sql, params, context, many: statements.append(sql))

        result = prepare(env, operation)

        assert result.status == "PREPARED"
        assert result.candidate.operation is operation
        assert result.candidate.symbol == env.plans[0].symbol
        assert result.candidate.anchor_date == env.clock.now().date()
        assert result.captured_at == env.clock.now()
        assert result.session_factory is env.sessions
        with pytest.raises(FrozenInstanceError):
            result.captured_at = env.clock.now() + timedelta(seconds=1)
        assert sum(sql == "BEGIN" for sql in statements) == 1
        assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN")) for sql in statements)
        assert not any("audit_log" in sql.lower() for sql in statements)
        assert env.pipeline._historical_reader is None
        assert env.pipeline._permission_rotation_state is rotation
        assert env.controller.raw_permission_retry_at(operation) == raw_due
        assert env.controller.is_permission_blocked(operation)
        assert env.sdk.calls == []


@pytest.mark.parametrize("family", ["legacy", "explicit", "mixed"])
def test_complete_today_families_freeze_original_identity(minute_env, family):
    env = minute_env(family=family)
    ready(env)
    result = prepare(env, MINUTE_SCOPES[0])
    assert result.status == "PREPARED"
    plan = min(env.plans, key=lambda plan: plan.symbol)
    consumer = result.consumer
    assert consumer.symbol == plan.symbol
    assert consumer.plan_hash == plan_sha256(plan)
    assert consumer.family == ("EXPLICIT_RULES" if family != "legacy" else "LEGACY")
    assert consumer.activation_revision == 1
    assert consumer.request_date == env.clock.now().date()
    with env.sessions() as session:
        active = session.execute(text("SELECT * FROM active_plan WHERE symbol=:symbol"),
                                 {"symbol": plan.symbol}).mappings().one()
    assert consumer.plan_version_id == active["plan_version_id"]
    assert consumer.activated_at.isoformat() == active["activated_at"]
    assert result.provider is env.pipeline.provider
    assert result.source is env.pipeline.provider._client
    assert result.source_time_label == env.pipeline.provider._source_time_label
    assert result.calendar_epoch == env.pipeline._calendar_epoch
    assert result.calendar_revoked is env.pipeline._calendar_revoked
    with pytest.raises(FrozenInstanceError):
        consumer.symbol = "003099.SZ"


@pytest.mark.parametrize("sql", [
    "UPDATE plan_activation_state SET plan_version_id=NULL",
    "UPDATE plan_activation_state SET symbol='003044.SZ'",
    "UPDATE active_plan SET symbol='003044.SZ'",
    "UPDATE plan_version SET symbol='003044.SZ'",
    "UPDATE plan_activation_state SET revision=2",
    "UPDATE active_plan SET revision=0",
    "UPDATE plan_activation_state SET changed_at='2026-09-08T09:00:00+08:00'",
    "UPDATE active_plan SET activated_at='2026-09-08T09:00:00'",
    "UPDATE plan_version SET plan_hash='bad'",
    "UPDATE plan_version SET plan_id='changed'",
    "UPDATE plan_version SET version=2",
    "UPDATE plan_version SET payload_json=payload_json || ' '",
    "UPDATE plan_version SET payload_json='{}'",
    "UPDATE plan_version SET status='DRAFT'",
    "DELETE FROM active_plan",
])
def test_inconsistent_persisted_identity_has_no_consumer(minute_env, sql):
    env = minute_env()
    ready(env)
    mutate(env, sql)
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"
    assert env.pipeline.permission_probe_candidates() == ()
    assert env.sdk.calls == []


@pytest.mark.parametrize("timestamp", [
    "2026-09-08T11:00:00+08:00", "2026-09-08T01:00:00+00:00",
    "2026-09-08T09:00:00", "not-a-timestamp",
])
def test_activation_time_must_be_canonical_and_not_future(minute_env, timestamp):
    env = minute_env()
    ready(env)
    mutate(env, "UPDATE active_plan SET activated_at=:value", {"value": timestamp})
    mutate(env, "UPDATE plan_activation_state SET changed_at=:value", {"value": timestamp})
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"


@pytest.mark.parametrize(("at", "expected", "defer_at"), [
    (time(9, 31, 11, 999999), "UNKNOWN", time(9, 31, 12)),
    (time(9, 31, 12), "PREPARED", None),
    (time(11, 30), "UNKNOWN", time(13)),
    (time(13), "PREPARED", None),
    (time(15), "UNKNOWN", time(15, 0, 30)),
])
def test_exact_start_windows_and_fixed_defer(minute_env, at, expected, defer_at):
    env = minute_env()
    env.clock.current = NOW.replace(hour=8, minute=0)
    ready(env)
    env.clock.current = datetime.combine(NOW.date(), at, NOW.tzinfo)
    result = prepare(env, MINUTE_SCOPES[0])
    assert result.status == expected
    if defer_at is not None:
        due = datetime.combine(NOW.date(), defer_at, NOW.tzinfo)
        assert env.pipeline.next_permission_probe_due_at() == due
        env.clock.current += timedelta(microseconds=1)
        assert env.pipeline.next_permission_probe_due_at() == due
        assert env.pipeline._permission_probe_deferred_until[MINUTE_SCOPES[0]] == due
    assert env.sdk.calls == []


@pytest.mark.parametrize("calendar", ["missing", "closed", "other_exchange", "weekend"])
def test_only_exact_sse_weekday_open_fact_authorizes_preparation(minute_env, calendar):
    env = minute_env(calendar=False)
    ready(env)
    if calendar == "weekend":
        env.clock.current = NOW.replace(day=12)
        _seed_open_day(env.database, env.clock.now().date())
    elif calendar == "closed":
        _seed_open_day(env.database, NOW.date())
        mutate(env, "UPDATE trading_calendar SET is_open=0 WHERE cal_date='2026-09-08'")
    elif calendar == "other_exchange":
        _seed_open_day(env.database, NOW.date())
        mutate(env, "UPDATE trading_calendar SET exchange='SZSE' WHERE cal_date='2026-09-08'")
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"
    assert env.pipeline.next_permission_probe_due_at() == env.clock.now() + timedelta(seconds=30)
    assert env.sdk.calls == []


def test_revoked_calendar_token_is_replaced_never_cleared(minute_env, monkeypatch):
    env = minute_env()
    ready(env)
    old = env.pipeline._calendar_revoked
    old.set()
    monkeypatch.setattr(old, "clear", lambda: pytest.fail("old token cannot be revived"))
    result = prepare(env, MINUTE_SCOPES[0])
    assert result.status == "PREPARED"
    assert old.is_set()
    assert result.calendar_revoked is not old
    assert result.calendar_revoked is env.pipeline._calendar_revoked
    assert not result.calendar_revoked.is_set()


@pytest.mark.parametrize("change", ["epoch", "event"])
def test_calendar_change_during_snapshot_prevents_rearm(minute_env, change):
    env = minute_env()
    ready(env)
    old = env.pipeline._calendar_revoked
    old.set()
    fired = []
    def change_calendar(conn, cursor, sql, params, context, many):
        if "FROM trading_calendar" in sql and not fired:
            fired.append(True)
            if change == "epoch":
                env.pipeline._calendar_epoch += 1
            else:
                env.pipeline._calendar_revoked = Event()
                env.pipeline._calendar_revoked.set()
    event.listen(env.engine, "after_cursor_execute", change_calendar)
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"
    assert old.is_set() and env.pipeline._calendar_revoked.is_set()


def test_borrowed_session_error_preserves_callers_transaction(minute_env, monkeypatch):
    env = minute_env()
    ready(env)
    with env.sessions() as borrowed:
        borrowed.execute(text("SELECT 1"))
        transaction = borrowed.get_transaction()
        monkeypatch.setattr(env.pipeline, "_permission_session_factory", lambda: borrowed)
        with pytest.raises(ValueError, match="fresh session"):
            prepare(env, MINUTE_SCOPES[0])
        assert borrowed.get_transaction() is transaction
        assert borrowed.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("family", ["legacy", "explicit"])
@pytest.mark.parametrize("gate", ["future", "expired", "service_missing"])
def test_today_demand_needs_eligible_activation_and_composed_service(
    minute_env, family, gate,
):
    env = minute_env(family=family)
    ready(env)
    if gate == "service_missing":
        setattr(env.pipeline, "evaluations" if family == "legacy" else "explicit_evaluations", None)
    else:
        offset = 1 if gate == "future" else -1
        plan = env.plans[0].model_copy(update={
            "activation": DateRangeActivation(
                start_date=NOW.date() + timedelta(days=offset),
                end_date=NOW.date() + timedelta(days=offset),
            ),
        })
        from trade_plan_monitor.domain.plan_codec import dump_plan_json
        mutate(env, "UPDATE plan_version SET payload_json=:payload, plan_hash=:hash", {
            "payload": dump_plan_json(plan), "hash": plan_sha256(plan),
        })
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"
    assert env.pipeline.permission_probe_candidates() == ()


def test_empty_consumer_set_fixed_defer_and_no_peek_write(minute_env):
    env = minute_env(count=0)
    ready(env)
    state = env.pipeline._permission_rotation_state
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"
    due = env.pipeline.next_permission_probe_due_at()
    for _ in range(3):
        env.clock.current += timedelta(seconds=1)
        assert prepare(env, MINUTE_SCOPES[0]).status == "SKIPPED"
        assert env.pipeline.next_permission_probe_due_at() == due
        assert env.pipeline.permission_probe_candidates() == ()
    assert env.pipeline._permission_rotation_state is state


def test_independent_symbol_successors_keep_daily_bar_pools_and_survive_empty_set(minute_env):
    from dataclasses import replace

    from trade_plan_monitor.runtime.production import PermissionProbeCandidate

    env = minute_env(count=3)
    for operation in MINUTE_SCOPES:
        asyncio.run(_block(env.controller, operation))
    env.clock.current += timedelta(seconds=301)
    initial = env.pipeline._permission_rotation_state
    original = replace(initial, official_pair=("600000.SH", NOW.date()),
                       fallback_pair=("600001.SH", NOW.date()), next_daily_bar_pool="F")
    env.pipeline._permission_rotation_state = original

    def candidates():
        return {item.operation: item for item in env.pipeline.permission_probe_candidates()}

    def acknowledge(candidate):
        # Simulate only the post-durable-reservation notification; no reservation or SDK work.
        async def transition():
            async with env.pipeline._permission_maintenance_lock:
                callback = env.pipeline._permission_probe_reservation_callback(candidate)
                before = env.pipeline._permission_rotation_state
                assert candidates()[candidate.operation] == candidate
                assert env.pipeline._permission_rotation_state is before
                callback()
        asyncio.run(transition())

    for expected in ("003043.SZ", "003044.SZ", "003045.SZ", "003043.SZ"):
        current = candidates()
        assert current[MINUTE_SCOPES[0]].symbol == expected
        assert current[MINUTE_SCOPES[1]].symbol == "003043.SZ"
        acknowledge(current[MINUTE_SCOPES[0]])
    acknowledge(candidates()[MINUTE_SCOPES[1]])
    assert candidates()[MINUTE_SCOPES[1]].symbol == "003044.SZ"
    snapshot = env.pipeline._permission_rotation_state
    assert (snapshot.official_pair, snapshot.fallback_pair, snapshot.next_daily_bar_pool) == (
        original.official_pair, original.fallback_pair, original.next_daily_bar_pool,
    )
    mutate(env, "DELETE FROM active_plan")
    assert candidates() == {}
    assert env.pipeline._permission_rotation_state is snapshot
    new = _sample_plan().model_copy(update={"symbol": "003046.SZ", "plan_id": "new-minute"})
    _activate_plans(env.database, ControlledClock(env.clock.now()), (new,))
    assert all(item.symbol == new.symbol for item in candidates().values())
    candidate = candidates()[MINUTE_SCOPES[0]]
    assert isinstance(candidate, PermissionProbeCandidate)


@pytest.mark.parametrize("mutation", ["configuration", "generation", "stop", "label"])
def test_authority_revocation_has_fixed_defer_and_no_read(minute_env, monkeypatch, mutation):
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel

    env = minute_env()
    ready(env)
    if mutation == "label":
        env.pipeline.provider._source_time_label = SourceTimeLabel.UNVERIFIED
    else:
        name = {"configuration": "_configuration_current", "generation": "_generation_current",
                "stop": "_admission_revoked"}[mutation]
        monkeypatch.setattr(env.pipeline, name, lambda: mutation == "stop")
    event.listen(env.engine, "before_cursor_execute",
                 lambda *args: pytest.fail("unavailable authority must not read demand"))
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"
    assert env.pipeline.next_permission_probe_due_at() == env.clock.now() + timedelta(seconds=30)


@pytest.mark.parametrize("gate", ["not_blocked", "not_due", "local_defer", "429"])
def test_preparation_gates_do_not_open_session(minute_env, monkeypatch, gate):
    from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
    from trade_plan_monitor.runtime.request_control import RequestControlError

    env = minute_env()
    if gate != "not_blocked":
        asyncio.run(_block(env.controller, MINUTE_SCOPES[0]))
    if gate in ("local_defer", "429"):
        env.clock.current += timedelta(seconds=301)
    if gate == "local_defer":
        env.pipeline._permission_probe_deferred_until[MINUTE_SCOPES[0]] = (
            env.clock.now() + timedelta(seconds=30)
        )
    if gate == "429":
        def limited():
            raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "rt_min")
        with pytest.raises(RequestControlError):
            asyncio.run(env.controller.execute(MINUTE_SCOPES[1], limited, work_key="minute:429"))
    monkeypatch.setattr(env.pipeline, "_permission_session_factory",
                        lambda: pytest.fail("gated preparation must not open a session"))
    assert prepare(env, MINUTE_SCOPES[0]).status == "SKIPPED"


def test_missing_factory_defers_without_enabling_business_recovery(minute_env):
    env = minute_env(source="none")
    ready(env)
    result = prepare(env, MINUTE_SCOPES[0])
    assert result.status == "UNKNOWN" and result.reason == "no_safe_session"
    assert env.pipeline._historical_reader is None


def test_minute_only_peek_without_factory_does_not_fall_back_to_business_uow(
    minute_env, monkeypatch,
):
    env = minute_env(source="none")
    ready(env)
    monkeypatch.setattr(env.pipeline, "_work", lambda: pytest.fail("no safe snapshot factory"))
    assert env.pipeline.permission_probe_candidates() == ()


def test_runnable_candidate_effective_due_does_not_slide_with_clock(minute_env):
    env = minute_env()
    ready(env)
    first = env.pipeline.select_due_permission_probe()
    assert first.next_due_at == first.raw_due_at
    env.clock.current += timedelta(seconds=5)
    assert env.pipeline.select_due_permission_probe() == first


def test_sql_errors_propagate(minute_env):
    from sqlalchemy.exc import OperationalError

    env = minute_env()
    ready(env)
    def fail(conn, cursor, sql, params, context, many):
        if "FROM trading_calendar" in sql:
            raise OperationalError(sql, params, RuntimeError("offline read failure"))
    event.listen(env.engine, "before_cursor_execute", fail)
    with pytest.raises(OperationalError):
        prepare(env, MINUTE_SCOPES[0])


def test_original_consumer_stays_frozen_across_same_hash_reactivation(minute_env):
    from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan

    env = minute_env()
    ready(env)
    original = prepare(env, MINUTE_SCOPES[0])
    env.clock.current += timedelta(seconds=1)
    with env.work() as work:
        plan = env.plans[0]
        work.plans.deactivate(plan.symbol, expected_revision=1)
        work.plans.activate(plan, expected_revision=2, validation=validate_trade_plan(
            plan, available_market_evidence=ALL_MARKET_EVIDENCE,
        ))
        work.commit()
    current = prepare(env, MINUTE_SCOPES[0])
    assert current.status == original.status == "PREPARED"
    assert original.consumer.plan_hash == current.consumer.plan_hash
    assert original.consumer.plan_version_id == current.consumer.plan_version_id
    assert original.consumer.activation_revision == 1
    assert current.consumer.activation_revision == 3
    assert current.consumer.activated_at > original.consumer.activated_at


def test_snapshot_reads_original_three_table_identity_across_concurrent_commit(minute_env):
    from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan

    env = minute_env()
    ready(env)
    fired, statements = [], []
    def after_read(conn, cursor, sql, params, context, many):
        statements.append(sql)
        if "FROM plan_version" in sql and not fired:
            fired.append(True)
            with env.work() as work:
                plan = env.plans[0]
                work.plans.deactivate(plan.symbol, expected_revision=1)
                work.plans.activate(plan, expected_revision=2, validation=validate_trade_plan(
                    plan, available_market_evidence=ALL_MARKET_EVIDENCE,
                ))
                work.commit()
    event.listen(env.engine, "after_cursor_execute", after_read)
    first = prepare(env, MINUTE_SCOPES[0])
    assert first.status == "PREPARED" and first.consumer.activation_revision == 1
    assert fired
    event.remove(env.engine, "after_cursor_execute", after_read)
    second = prepare(env, MINUTE_SCOPES[0])
    assert second.consumer.activation_revision == 3


def test_missing_historical_audit_does_not_remove_current_consumer(minute_env):
    env = minute_env()
    ready(env)
    mutate(env, "DELETE FROM audit_log")
    assert prepare(env, MINUTE_SCOPES[0]).status == "PREPARED"


def test_historical_pending_only_does_not_create_today_minute_demand(tmp_path, monkeypatch):
    from trade_plan_monitor.runtime.service import RuntimeEvaluationService

    with harness(tmp_path, monkeypatch, days=3, today=False) as env:
        _seed_open_day(env.database, NOW.date())
        with env.work() as work:
            plan = env.plans[0]
            RuntimeEvaluationService._mark_close_pending(
                work, plan=plan, symbol=plan.symbol, trade_date=env.first,
                evaluated_at=env.clock.now(), activation_revision=1,
            )
            work.commit()
        ready(env)
        assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"
        assert env.pipeline.permission_probe_candidates() == ()


def test_other_runnable_scope_wins_but_local_deferred_earlier_scope_does_not(minute_env):
    env = minute_env()
    other = TushareOperation.TRADING_CALENDAR
    asyncio.run(_block(env.controller, other))
    ready(env)
    assert prepare(env, MINUTE_SCOPES[0]).status == "SKIPPED"
    env.pipeline._permission_probe_deferred_until[other] = env.clock.now() + timedelta(seconds=30)
    assert prepare(env, MINUTE_SCOPES[0]).status == "PREPARED"


@pytest.mark.parametrize("limit", ["count", "payload"])
def test_bounded_active_plan_reads_reject_over_budget(minute_env, limit):
    env = minute_env(count=10)
    ready(env)
    if limit == "count":
        # Deliberately corrupt status count after ten valid repository activations.
        mutate(env, "INSERT INTO plan_version "
               "(id, plan_id, version, symbol, plan_hash, status, payload_json, source_id, "
               "revision, created_at) SELECT 'overflow', 'overflow', version, '003099.SZ', "
               "plan_hash, status, payload_json, source_id, revision, created_at "
               "FROM plan_version LIMIT 1")
        match = "at most ten"
    else:
        mutate(env, "UPDATE plan_version SET payload_json=:payload", {"payload": " " * 1_048_577})
        match = "payload exceeds"
    with pytest.raises(ValueError, match=match):
        prepare(env, MINUTE_SCOPES[0])


def test_all_eight_scopes_preserve_ties_and_getter_is_read_free(tmp_path, monkeypatch):
    from test_permission_candidate_selection import ANCHOR
    from test_production_certification_gate import _composition

    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch, include_index=True,
                                           persisted_calendar=True)
        try:
            await composition.start()
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            control = runtime._request_controller
            _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
            scopes = (
                TushareOperation.TRADING_CALENDAR,
                TushareOperation.INDEX_HISTORICAL_MINUTES,
                TushareOperation.INDEX_REALTIME_MINUTES,
                TushareOperation.DAILY_LIMITS,
                TushareOperation.DAILY_BARS,
                TushareOperation.INDEX_DAILY,
                *MINUTE_SCOPES,
            )
            for scope in scopes:
                await _block(control, scope)
            runtime._clock.current += timedelta(seconds=301)
            before_sdk = tuple(sdk.calls)
            candidates = pipeline.permission_probe_candidates()
            assert tuple(candidate.operation for candidate in candidates) == scopes
            assert pipeline.select_due_permission_probe() == candidates[0]
            pipeline._permission_probe_deferred_until[scopes[0]] = (
                runtime._clock.now() + timedelta(seconds=30)
            )
            assert pipeline.select_due_permission_probe() == candidates[1]
            pipeline._permission_probe_deferred_until.clear()
            async with pipeline._permission_maintenance_lock:
                pipeline._permission_probe_reservation_callback(candidates[5])()
            rotated = pipeline.permission_probe_candidates()
            assert tuple(candidate.operation for candidate in rotated) == (*scopes[6:], *scopes[:6])
            assert tuple(sdk.calls) == before_sdk
            monkeypatch.setattr(pipeline, "_read_stock_minute_permission_evidence",
                                lambda *_: pytest.fail("getter cannot query facts"))
            monkeypatch.setattr(pipeline, "_read_permission_evidence",
                                lambda *_a, **_k: pytest.fail("getter cannot query facts"))
            for scope in scopes:
                pipeline._permission_probe_deferred_until = {
                    other: runtime._clock.now() + timedelta(seconds=60)
                    for other in scopes if other != scope
                }
                assert pipeline.next_permission_probe_due_at() == control.raw_permission_retry_at(
                    scope,
                )
        finally:
            await composition.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["provider", "source", "factory", "clock", "next_day"])
def test_capture_rejects_authority_changes_during_owned_read(minute_env, change):
    env = minute_env()
    ready(env)
    original = env.pipeline.provider
    fired = []
    def invalidate(conn, cursor, sql, params, context, many):
        if "FROM trading_calendar" in sql and not fired:
            fired.append(True)
            if change == "provider":
                from copy import copy
                env.pipeline.provider = copy(original)
            elif change == "source":
                original._client = object()
            elif change == "factory":
                env.pipeline._permission_session_factory = lambda: env.sessions()
            elif change == "clock":
                env.clock.current -= timedelta(seconds=1)
            else:
                env.clock.current += timedelta(days=1)
    event.listen(env.engine, "after_cursor_execute", invalidate)
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"


def test_incorrect_bind_raises_without_closing_supplied_session(minute_env, monkeypatch):
    from sqlalchemy.orm import Session

    from trade_plan_monitor.state.database import create_sqlite_engine
    from trade_plan_monitor.state.models import ActivePlan

    env = minute_env()
    ready(env)
    other = create_sqlite_engine(env.database.parent / "wrong.sqlite3")
    try:
        with Session(bind=env.engine, binds={ActivePlan: other}) as supplied:
            monkeypatch.setattr(env.pipeline, "_permission_session_factory", lambda: supplied)
            monkeypatch.setattr(supplied, "close", lambda: pytest.fail("not our session"))
            monkeypatch.setattr(supplied, "rollback", lambda: pytest.fail("not our transaction"))
            with pytest.raises(ValueError, match="one engine"):
                prepare(env, MINUTE_SCOPES[0])
            assert supplied.scalar(text("SELECT 1")) == 1
            monkeypatch.undo()
    finally:
        other.dispose()


def test_semantic_mode_survives_old_cert_expiry_and_rebuilds_next_day(minute_env, tmp_path):
    from trade_plan_monitor.domain.plan_codec import dump_plan_json
    from trade_plan_monitor.runtime.production import (
        ProductionSemanticBindings,
        SemanticContractBinding,
    )
    from trade_plan_monitor.runtime.provider_contract import import_stock_semantic_contract

    env = minute_env()
    ready(env)
    plan = env.plans[0].model_copy(update={"activation": DateRangeActivation(
        start_date=NOW.date(), end_date=NOW.date() + timedelta(days=10),
    )})
    mutate(env, "UPDATE plan_version SET payload_json=:payload, plan_hash=:hash", {
        "payload": dump_plan_json(plan), "hash": plan_sha256(plan),
    })
    sidecar = tmp_path / "stock-semantic.json"
    semantic = import_stock_semantic_contract(
        tmp_path / "data/live-certification/tushare-stock-live.json", sidecar,
        now=NOW, endpoint_url="https://example.test", installed_sdk_version=lambda: "1.4.29",
    )
    assert semantic is not None
    env.pipeline._semantic_bindings = ProductionSemanticBindings(
        stock=SemanticContractBinding(sidecar, semantic.semantic_revision), index=None,
        installed_sdk_version=lambda: "1.4.29",
    )
    env.pipeline._stock_semantics = semantic
    first = prepare(env, MINUTE_SCOPES[0])
    assert first.status == "PREPARED"
    assert first.semantic_bound and first.semantic_revision == semantic.semantic_revision
    env.clock.current = semantic.provenance.valid_until + timedelta(days=1)
    while env.clock.now().weekday() >= 5:
        env.clock.current += timedelta(days=1)
    env.clock.current = env.clock.now().replace(hour=10, minute=0, second=0)
    _seed_open_day(env.database, env.clock.now().date())
    second = prepare(env, MINUTE_SCOPES[0])
    assert second.status == "PREPARED"
    assert second.consumer.request_date == env.clock.now().date()
    assert second.consumer.request_date != first.consumer.request_date
    assert first.candidate.anchor_date == NOW.date()
    env.pipeline._semantic_bindings = ProductionSemanticBindings(stock=None, index=None)
    assert prepare(env, MINUTE_SCOPES[0]).status == "UNKNOWN"


@pytest.mark.parametrize("operation", MINUTE_SCOPES)
def test_minute_scope_is_in_both_candidate_selector_and_cheap_due_getter(
    tmp_path, monkeypatch, operation,
):
    with harness(tmp_path, monkeypatch, today=True) as env:
        _seed_open_day(env.database, env.clock.now().date())
        asyncio.run(_block(env.controller, operation))
        env.clock.current += timedelta(seconds=301)
        raw_due = env.controller.raw_permission_retry_at(operation)
        assert env.pipeline.next_permission_probe_due_at() == raw_due
        candidates = env.pipeline.permission_probe_candidates()
        assert tuple(item.operation for item in candidates) == (operation,)
        assert env.pipeline.select_due_permission_probe() == candidates[0]
        assert env.pipeline.permission_probe_candidates() == candidates
        assert env.pipeline._permission_rotation_state.last_operation is None
        assert env.sdk.calls == []
