"""Offline, read-only DAILY_BARS preparation in one owner SQLite snapshot."""

import asyncio
from contextlib import ExitStack, contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _sample_plan,
    _write_configuration_and_evidence,
)
from test_permission_candidate_selection import _block, _seed_official_bar, _seed_open_day
from test_production_certification_gate import _composition

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.domain.plan_models import DateRangeActivation
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.live_profiles import load_stock_certification
from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    TushareOperation,
    create_live_tushare_request_controller,
)
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

OP = TushareOperation.DAILY_BARS


@contextmanager
def harness(tmp_path, monkeypatch, *, count=1, days=40, today=False, calendar=False,
            anchor=True, source="permission"):
    first = NOW.date() - timedelta(days=days + 2)
    activation_at = datetime.combine(first, time(9), NOW.tzinfo)
    plans = tuple(_sample_plan().model_copy(update={
        "symbol": f"{3043 + i:06d}.SZ", "plan_id": f"demand-{i}",
        **({} if today else {"activation": DateRangeActivation(
            start_date=first, end_date=first + timedelta(days=days - 1),
        )}),
    }) for i in range(count))
    database = tmp_path / "monitor.sqlite3"
    _activate_plans(database, ControlledClock(activation_at), plans)
    config = _write_configuration_and_evidence(tmp_path, observed_at=NOW, include_index=False)
    engine = create_sqlite_engine(database)
    sessions = create_session_factory(engine)
    with sessions.begin() as session:
        if calendar is not None:
            session.add_all(TradingCalendar(exchange="SSE", cal_date=first + timedelta(days=i),
                                           is_open=calendar,
                                           previous_trade_date=first + timedelta(days=i - 1))
                            for i in range(days))
        if anchor:
            session.add(TradingCalendar(exchange="SSE", cal_date=NOW.date() - timedelta(days=1),
                                       is_open=True,
                                       previous_trade_date=NOW.date() - timedelta(days=4)))
    clock = ControlledClock(NOW)
    sdk = OfflineSDK(clock, tuple(plan.symbol for plan in plans))
    monkeypatch.setattr("trade_plan_monitor.runtime.production.create_tushare_client",
                        lambda config: sdk)
    pace = VirtualPace()
    controller = create_live_tushare_request_controller(
        clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
    )

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

    pipeline = ProductionMonitorPipeline(
        configuration=load_application_config(config).tushare,
        certification_directory=tmp_path / "data/live-certification",
        stock_certification=load_stock_certification(
            tmp_path / "data/live-certification/tushare-stock-live.json", now=NOW,
            endpoint_url="https://example.test",
        ),
        clock=clock, request_controller=controller, unit_of_work_factory=work,
        runtime_generation=uuid4(), publisher=lambda _event: None,
        **({"permission_session_factory": sessions} if source == "permission" else
           {"recovery_session_factory": sessions} if source == "recovery" else {}),
    )
    try:
        yield SimpleNamespace(pipeline=pipeline, clock=clock, controller=controller,
                              sessions=sessions, sdk=sdk, engine=engine, plans=plans,
                              first=first, activation_at=activation_at,
                              work=work, database=database)
    finally:
        controller.close()
        engine.dispose()


@pytest.fixture
def make_env(tmp_path, monkeypatch):
    with ExitStack() as stack:
        yield lambda **kwargs: stack.enter_context(harness(tmp_path, monkeypatch, **kwargs))


def ready(env):
    asyncio.run(_block(env.controller, OP))
    env.clock.current += timedelta(seconds=301)


def prepare(env):
    return asyncio.run(env.pipeline._prepare_daily_bar_permission())


def observe_inspections(env, monkeypatch):
    reader = env.pipeline._permission_demand_reader
    original = reader.inspect_permission_demand_in_session
    calls = []

    def inspect(session, symbol, now, cursor=None):
        calls.append((symbol, cursor, session))
        return original(session, symbol, now, cursor)

    monkeypatch.setattr(reader, "inspect_permission_demand_in_session", inspect)
    return calls


def test_real_composition_has_independent_safe_permission_reader(tmp_path, monkeypatch):
    async def scenario():
        composition, sdk, _ = _composition(tmp_path, monkeypatch, persisted_calendar=True)
        try:
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            runtime = composition._runtime
            pipeline = runtime._probe_capabilities.__self__._pipeline
            _seed_open_day(tmp_path / "monitor.sqlite3", NOW.date() - timedelta(days=1))
            await _block(runtime._request_controller, OP)
            runtime._clock.current += timedelta(seconds=301)
            before = tuple(sdk.calls)
            assert pipeline._permission_demand_reader is not pipeline._historical_reader
            result = await pipeline._prepare_daily_bar_permission()
            assert result.status == "PREPARED" and result.receipt.kind == "TODAY_REFERENCE"
            assert tuple(sdk.calls) == before
        finally:
            await composition.stop()
    asyncio.run(scenario())


def test_permission_only_factory_does_not_enable_business_recovery(make_env):
    env = make_env(today=True)
    assert env.pipeline._historical_reader is None
    ready(env)
    result = prepare(env)
    assert result.status == "PREPARED" and result.candidate.symbol == env.plans[0].symbol
    assert env.pipeline._historical_reader is None
    with pytest.raises(FrozenInstanceError):
        result.captured_at = NOW


def test_no_factory_is_unknown_with_fixed_local_defer(make_env):
    env = make_env(source="none", today=True)
    ready(env)
    result = prepare(env)
    assert result.status == "UNKNOWN" and result.reason == "no_safe_session"
    due = env.clock.now() + timedelta(seconds=30)
    assert env.pipeline._permission_probe_deferred_until[OP] == due
    env.clock.current += timedelta(seconds=10)
    assert prepare(env).status == "SKIPPED"
    assert env.pipeline._permission_probe_deferred_until[OP] == due


@pytest.mark.parametrize("gate", ["not_due", "429", "other_scope", "peek"])
def test_gates_and_pure_peek_do_not_inspect_demand(make_env, monkeypatch, gate):
    env = make_env(today=True)
    if gate == "other_scope":
        asyncio.run(_block(env.controller, TushareOperation.TRADING_CALENDAR))
    asyncio.run(_block(env.controller, OP))
    if gate != "not_due":
        env.clock.current += timedelta(seconds=301)
    if gate == "429":
        def limited():
            raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "rt_min")
        with pytest.raises(RequestControlError):
            asyncio.run(env.controller.execute(TushareOperation.CURRENT_DAY_MINUTES, limited,
                                               work_key="offline:429"))
    calls = observe_inspections(env, monkeypatch)
    if gate == "peek":
        env.pipeline.permission_probe_candidates()
        env.pipeline.select_due_permission_probe()
        env.pipeline.next_permission_probe_due_at()
    else:
        assert prepare(env).status == "SKIPPED"
    assert not calls


def test_earlier_raw_but_future_effective_scope_does_not_block(make_env):
    env = make_env(today=True)
    other = TushareOperation.TRADING_CALENDAR
    asyncio.run(_block(env.controller, other))
    env.clock.current += timedelta(seconds=1)
    ready(env)
    env.pipeline._permission_probe_deferred_until[other] = env.clock.now() + timedelta(seconds=60)
    assert prepare(env).status == "PREPARED"


def test_no_anchor_sets_fixed_defer_even_without_broad_candidate(make_env, monkeypatch):
    env = make_env(today=True, anchor=False)
    ready(env)
    calls = observe_inspections(env, monkeypatch)
    assert not env.pipeline.permission_probe_candidates()
    assert prepare(env).status == "UNKNOWN"
    count = len(calls)
    due = env.pipeline._permission_probe_deferred_until[OP]
    assert due == env.clock.now() + timedelta(seconds=30)
    for _ in range(3):
        env.clock.current += timedelta(seconds=1)
        assert prepare(env).status == "SKIPPED"
    assert len(calls) == count and env.pipeline._permission_probe_deferred_until[OP] == due


def test_ten_historical_symbols_rotate_including_unknown_and_none(make_env, monkeypatch):
    env = make_env(count=10, days=10, calendar=None)
    ready(env)
    calls = observe_inspections(env, monkeypatch)
    for _ in range(20):
        previous = len(calls)
        assert prepare(env).status == "UNKNOWN"
        assert len(calls) == previous + 1
        env.clock.current += timedelta(seconds=31)
    expected = [plan.symbol for plan in env.plans] * 2
    assert [symbol for symbol, _, _ in calls] == expected
    with env.sessions.begin() as session:
        session.add_all(TradingCalendar(exchange="SSE", cal_date=env.first + timedelta(days=i),
                                       is_open=False,
                                       previous_trade_date=env.first + timedelta(days=i - 1))
                        for i in range(10))
    for _ in range(10):
        assert prepare(env).status == "UNKNOWN"
        env.clock.current += timedelta(seconds=31)
    _seed_open_day(env.database, env.first)
    assert prepare(env).status == "PREPARED"
    assert calls[-1][0] == env.plans[0].symbol
    assert len(env.pipeline._daily_bar_demand_cursors) <= 10
    assert len(env.pipeline._daily_bar_demand_receipts) <= 10


@pytest.mark.parametrize("offset", [32, 370])
def test_paging_reaches_deep_gaps_and_continues_across_day(make_env, monkeypatch, offset):
    env = make_env(days=400)
    ready(env)
    _seed_open_day(env.database, env.first + timedelta(days=offset))
    calls = observe_inspections(env, monkeypatch)
    for index in range(offset // 32):
        assert prepare(env).status == "UNKNOWN"
        env.clock.current += timedelta(seconds=31)
        if index == 0:
            env.clock.current += timedelta(days=1)
    result = prepare(env)
    assert result.status == "PREPARED"
    assert result.receipt.d_need == env.first + timedelta(days=offset)
    assert calls[-1][1].next_date == env.first + timedelta(days=32 * (offset // 32))


def test_only_valid_receipt_symbols_enter_existing_official_fallback_order(make_env):
    env = make_env(count=2, calendar=True)
    ready(env)
    second = env.plans[1].symbol
    anchor = NOW.date() - timedelta(days=1)
    _seed_official_bar(env.database, second, anchor, NOW)
    first = prepare(env)
    assert first.status == "PREPARED" and first.candidate.symbol == env.plans[0].symbol
    assert first.candidate.daily_bar_pool == "F"
    next_result = prepare(env)
    assert next_result.status == "PREPARED" and next_result.candidate.symbol == second
    assert next_result.candidate.daily_bar_pool == "O"
    assert next_result.receipt is env.pipeline._daily_bar_demand_receipts[second]


def test_single_snapshot_receipt_budget_and_zero_writes_or_reservations(make_env, monkeypatch):
    env = make_env(count=10, today=True)
    ready(env)
    rotation = env.pipeline._permission_rotation_state
    raw = env.controller.raw_permission_retry_at(OP)
    statements, sessions = [], []
    reader = env.pipeline._permission_demand_reader
    original = reader.validate_permission_demand_in_session

    def validate(session, receipt, now):
        sessions.append(session)
        return original(session, receipt, now)

    monkeypatch.setattr(reader, "validate_permission_demand_in_session", validate)
    monkeypatch.setattr(env.pipeline, "_work", lambda: pytest.fail("second UnitOfWork snapshot"))
    event.listen(env.engine, "before_cursor_execute",
                 lambda conn, cursor, sql, params, context, many: statements.append(sql))
    assert prepare(env).status == "PREPARED"
    assert len(sessions) == 10 and len({id(session) for session in sessions}) == 1
    assert sum(sql == "BEGIN" for sql in statements) == 1
    assert all(sql.lstrip().upper().startswith(("SELECT", "BEGIN")) for sql in statements)
    assert env.pipeline._permission_rotation_state is rotation
    assert env.controller.raw_permission_retry_at(OP) == raw
    assert env.controller.is_permission_blocked(OP) and env.sdk.calls == []


def test_normal_pending_keeps_independent_demand(make_env):
    env = make_env(days=1, calendar=True)
    ready(env)
    with env.work() as work:
        RuntimeEvaluationService._mark_close_pending(
            work, plan=env.plans[0], symbol=env.plans[0].symbol, trade_date=env.first,
            evaluated_at=env.clock.now(), activation_revision=1,
        )
        work.commit()
    assert prepare(env).status == "PREPARED"


def test_missing_evidence_keeps_cursor_and_reader_change_invalidates_it(make_env):
    env = make_env(days=80)
    ready(env)
    assert prepare(env).status == "UNKNOWN"
    symbol = env.plans[0].symbol
    cursor = env.pipeline._daily_bar_demand_cursors[symbol]
    with env.sessions.begin() as session:
        audit = session.execute(text("SELECT * FROM audit_log WHERE action='PLAN_ACTIVATED'"))
        row = dict(audit.mappings().one())
        session.execute(text("DELETE FROM audit_log WHERE action='PLAN_ACTIVATED'"))
    env.clock.current += timedelta(seconds=31)
    assert prepare(env).status == "UNKNOWN"
    assert env.pipeline._daily_bar_demand_cursors[symbol] is cursor
    with env.sessions.begin() as session:
        columns = ','.join(row)
        parameters = ','.join(':' + key for key in row)
        session.execute(text(f"INSERT INTO audit_log ({columns}) VALUES ({parameters})"), row)
    env.pipeline._permission_demand_reader = LegacyHistoricalCloseReader(env.sessions)
    env.clock.current += timedelta(seconds=31)
    assert prepare(env).status == "UNKNOWN"
    assert symbol not in env.pipeline._daily_bar_demand_cursors


def test_sql_read_failures_propagate(make_env):
    env = make_env(today=True)
    ready(env)

    def fail(conn, cursor, sql, parameters, context, many):
        if "FROM trading_calendar" in sql:
            raise OperationalError(sql, parameters, RuntimeError("offline read error"))

    event.listen(env.engine, "before_cursor_execute", fail)
    with pytest.raises(OperationalError):
        prepare(env)


def test_authority_revocation_defers_without_demand_page(make_env, monkeypatch):
    env = make_env(today=True)
    ready(env)
    calls = observe_inspections(env, monkeypatch)
    monkeypatch.setattr(env.pipeline, "_configuration_current", lambda: False)
    assert prepare(env).status == "UNKNOWN"
    assert not calls and env.pipeline._permission_probe_deferred_until[OP] == (
        env.clock.now() + timedelta(seconds=30)
    )


def test_disappeared_symbol_is_pruned_and_new_symbol_is_investigated(make_env):
    env = make_env(count=2, calendar=True)
    ready(env)
    assert prepare(env).status == "PREPARED"
    assert prepare(env).status == "PREPARED"
    with env.work() as work:
        work.plans.deactivate(env.plans[0].symbol, expected_revision=1)
        work.commit()
    new = env.plans[0].model_copy(update={"symbol": "003045.SZ", "plan_id": "new"})
    _activate_plans(env.database, ControlledClock(env.activation_at), (new,))
    assert prepare(env).status == "PREPARED"
    assert env.plans[0].symbol not in env.pipeline._daily_bar_demand_receipts
    assert env.plans[0].symbol not in env.pipeline._daily_bar_demand_cursors
    assert new.symbol in env.pipeline._daily_bar_demand_receipts


def test_expired_receipts_are_point_checked_even_when_another_symbol_gets_page(make_env):
    env = make_env(count=2, calendar=True)
    ready(env)
    assert prepare(env).status == "PREPARED"
    assert prepare(env).status == "PREPARED"
    first, second = (plan.symbol for plan in env.plans)
    stale = env.pipeline._daily_bar_demand_receipts[second]
    env.pipeline._daily_bar_demand_receipts[second] = replace(
        stale, captured_at=stale.captured_at - timedelta(days=1),
    )
    assert prepare(env).candidate.symbol == first
    assert second not in env.pipeline._daily_bar_demand_receipts


def test_identity_aba_excludes_unrechecked_symbol_receipt(make_env):
    env = make_env(count=2, calendar=True)
    ready(env)
    prepare(env)
    prepare(env)
    second = env.plans[1]
    with env.work() as work:
        work.plans.deactivate(second.symbol, expected_revision=1)
        work.plans.activate(second, expected_revision=2, validation=validate_trade_plan(
            second, available_market_evidence=ALL_MARKET_EVIDENCE,
        ))
        work.commit()
    assert prepare(env).candidate.symbol == env.plans[0].symbol
    assert second.symbol not in env.pipeline._daily_bar_demand_receipts


def test_clock_rollback_excludes_receipts_and_invalidates_cursor(make_env):
    env = make_env(calendar=True)
    ready(env)
    env.clock.current += timedelta(seconds=10)
    assert prepare(env).status == "PREPARED"
    env.clock.current -= timedelta(seconds=1)
    assert prepare(env).status == "UNKNOWN"
    assert not env.pipeline._daily_bar_demand_receipts
    assert not env.pipeline._daily_bar_demand_cursors


def test_shared_maintenance_lock_serializes_investigation(make_env, monkeypatch):
    env = make_env(calendar=True)
    ready(env)
    calls = observe_inspections(env, monkeypatch)

    async def scenario():
        lock = env.pipeline._permission_maintenance_lock
        await lock.acquire()
        pending = asyncio.create_task(env.pipeline._prepare_daily_bar_permission())
        await asyncio.sleep(0)
        assert not pending.done() and not calls
        lock.release()
        assert (await pending).status == "PREPARED"
        assert len(calls) == 1
    asyncio.run(scenario())


def test_snapshot_remains_coherent_across_concurrent_activation_write(make_env, monkeypatch):
    env = make_env(calendar=True)
    ready(env)
    reader = env.pipeline._permission_demand_reader
    original = reader.inspect_permission_demand_in_session

    def inspect_then_write(session, symbol, now, cursor=None):
        result = original(session, symbol, now, cursor)
        with env.work() as work:
            work.plans.deactivate(symbol, expected_revision=1)
            work.commit()
        return result

    monkeypatch.setattr(reader, "inspect_permission_demand_in_session", inspect_then_write)
    result = prepare(env)
    assert result.status == "PREPARED"
    with env.sessions() as session:
        assert not reader.validate_permission_demand_in_session(session, result.receipt,
                                                                env.clock.now())
    assert prepare(env).status == "UNKNOWN"
    assert not env.pipeline._daily_bar_demand_receipts


def test_calendar_refresh_and_unrelated_event_preserve_page_progress(make_env, monkeypatch):
    from trade_plan_monitor.market_data.models import TradingDay

    env = make_env(days=80)
    ready(env)
    calls = observe_inspections(env, monkeypatch)
    assert prepare(env).status == "UNKNOWN"
    symbol = env.plans[0].symbol
    previous = env.pipeline._daily_bar_demand_cursors[symbol]
    day = TradingDay(exchange="SSE", cal_date=env.first, is_open=False,
                     previous_trade_date=env.first - timedelta(days=1))
    key = env.pipeline._reference_dependency_key(
        env.clock.now().date(), env.pipeline.active_plans(),
    )
    env.pipeline._commit_trading_days((day,), trade_date=env.clock.now().date(), captured_key=key)
    with env.work() as work:
        work.events.append(MonitorEventDraft(
            event_id=monitor_event_id(MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                                      "600000.SH", "unrelated"),
            event_type=MonitorEventType.SYMBOL_SNAPSHOT_UPDATED, aggregate_id="600000.SH",
            payload=MonitorEventPayload(entity_id="600000.SH", symbol="600000.SH",
                                       result_hash="a" * 64),
            occurred_at=env.clock.now(),
        ))
        work.commit()
    env.clock.current += timedelta(seconds=31)
    assert prepare(env).status == "UNKNOWN"
    assert calls[-1][1] is previous
    assert env.pipeline._daily_bar_demand_cursors[symbol].next_date == (
        env.first + timedelta(days=64)
    )


def test_successful_repeat_keeps_one_history_page_and_ten_receipt_budget(make_env, monkeypatch):
    env = make_env(count=10, calendar=True)
    ready(env)
    for _ in range(10):
        assert prepare(env).status == "PREPARED"
    reader = env.pipeline._permission_demand_reader
    calls = observe_inspections(env, monkeypatch)
    checked = []
    original = reader.validate_permission_demand_in_session

    def validate(session, receipt, now):
        checked.append(receipt.identity.symbol)
        return original(session, receipt, now)

    monkeypatch.setattr(reader, "validate_permission_demand_in_session", validate)
    assert prepare(env).status == "PREPARED"
    assert len(calls) == 1 and len(checked) == 10
    assert len(set(checked)) == 10


def test_borrowed_session_is_not_closed_or_used_for_permission_reads(make_env, monkeypatch):
    env = make_env(today=True)
    ready(env)
    with env.sessions() as borrowed:
        borrowed.execute(text("SELECT 1"))
        transaction = borrowed.get_transaction()
        monkeypatch.setattr(env.pipeline, "_permission_session_factory", lambda: borrowed)
        result = prepare(env)
        assert result.status == "UNKNOWN" and result.reason == "no_safe_session"
        assert borrowed.get_transaction() is transaction
        assert borrowed.scalar(text("SELECT 1")) == 1


def test_reader_replacement_excludes_all_old_receipts(make_env):
    env = make_env(count=2, calendar=True)
    ready(env)
    prepare(env)
    prepare(env)
    env.pipeline._permission_demand_reader = LegacyHistoricalCloseReader(env.sessions)
    assert prepare(env).status == "UNKNOWN"
    assert not env.pipeline._daily_bar_demand_receipts
