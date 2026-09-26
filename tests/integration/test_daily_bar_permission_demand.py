"""Bounded permission demand in real snapshots; never historical execution."""

from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest
from sqlalchemy import event, text
from test_close_recovery_evidence import mutate
from test_historical_close_evidence import historical as historical
from test_historical_close_evidence import publish
from test_recovery_alert_provenance import NOW, _result
from test_recovery_alert_provenance import history as history

from trade_plan_monitor.domain.plan_models import DateRangeActivation
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.runtime import historical_close_evidence as module
from trade_plan_monitor.runtime.service import RuntimeEvaluationService
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)
from trade_plan_monitor.state.models import TradingCalendar


def setup(historical, days=40, *, calendar=False, policy_start=0, activated_offset=0):
    plan = historical.plan.model_copy(update={
        "version": 2,
        "activation": DateRangeActivation(
            start_date=NOW.date() + timedelta(days=policy_start),
            end_date=NOW.date() + timedelta(days=days - 1),
        ),
    })
    validation = validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE)
    historical.clock[0] = NOW + timedelta(days=activated_offset, minutes=-10)
    with historical.work() as uow:
        uow.plans.save_draft(plan, source_text="bounded demand fixture")
        uow.plans.activate(plan, expected_revision=1, validation=validation)
        uow.commit()
    historical.plan, historical.validation, historical.result = plan, validation, _result(plan)
    mutate(historical, "DELETE FROM trading_calendar")
    if calendar is not None:
        with historical.factory() as session:
            session.add_all(TradingCalendar(
                exchange="SSE", cal_date=NOW.date() + timedelta(days=i), is_open=calendar,
            ) for i in range(days))
            session.commit()
    return module.LegacyHistoricalCloseReader(historical.factory), NOW + timedelta(days=days)


def inspect(historical, reader, now, cursor=None):
    with historical.factory() as session:
        return reader.inspect_permission_demand_in_session(
            session, historical.plan.symbol, now, cursor,
        )


def valid(historical, reader, receipt, now):
    with historical.factory() as session:
        return reader.validate_permission_demand_in_session(session, receipt, now)


def open_day(historical, offset):
    with historical.factory() as session:
        day = NOW.date() + timedelta(days=offset)
        row = session.get(TradingCalendar, ("SSE", day))
        if row is None:
            session.add(TradingCalendar(exchange="SSE", cal_date=day, is_open=True))
        else:
            row.is_open = True
        session.commit()


def forbid(*args, **kwargs):
    raise AssertionError("unwanted historical/external call")


def test_today_short_circuits_history_with_complete_identity(historical, monkeypatch):
    reader, _ = setup(historical)
    monkeypatch.setattr(module, "_latest_completed_close", forbid)
    monkeypatch.setattr(module, "discover_missed_closes", forbid)
    monkeypatch.setattr(module, "_CompletionReader", forbid)
    monkeypatch.setattr(reader, "missing_targets_in_session", forbid)
    result = inspect(historical, reader, NOW)
    assert result.status == "NEEDED" and result.receipt.kind == "TODAY_REFERENCE"
    assert result.receipt.d_need is None
    assert result.identity == result.receipt.identity
    assert result.identity.symbol == historical.plan.symbol
    assert result.identity.activation_revision == 2
    assert result.identity.activated_at == NOW - timedelta(minutes=10)
    assert result.identity.plan_hash == historical.result.snapshot.plan_hash
    assert result.identity.formula_version == historical.plan.monitoring.indicator_formula_version
    assert result.identity.plan_version_id
    assert valid(historical, reader, result.receipt, NOW + timedelta(seconds=1))
    with pytest.raises(FrozenInstanceError):
        result.status = "NONE"


def test_day_33_gap_is_found_on_second_call(historical, monkeypatch):
    reader, now = setup(historical)
    monkeypatch.setattr(reader, "missing_targets_in_session", forbid)
    open_day(historical, 32)
    first = inspect(historical, reader, now)
    assert first.status == "UNKNOWN"
    assert first.next_cursor.next_date == NOW.date() + timedelta(days=32)
    second = inspect(historical, reader, now, first.next_cursor)
    assert second.status == "NEEDED"
    assert second.receipt.d_need == NOW.date() + timedelta(days=32)
    assert valid(historical, reader, second.receipt, now)


def test_history_older_than_366_days_is_retained(historical):
    reader, now = setup(historical, 400)
    open_day(historical, 0)
    result = inspect(historical, reader, now)
    assert result.status == "NEEDED" and result.receipt.d_need == NOW.date()


def test_unknown_page_advances_tail_cannot_prove_none_and_wrap_revisits(historical):
    reader, now = setup(historical, calendar=None)
    first = inspect(historical, reader, now)
    assert first.status == "UNKNOWN"
    with historical.factory() as session:
        session.add_all(TradingCalendar(exchange="SSE", cal_date=NOW.date() + timedelta(days=i),
                                       is_open=False) for i in range(32, 40))
        session.commit()
    second = inspect(historical, reader, now, first.next_cursor)
    assert second.status == "UNKNOWN" and second.next_cursor.next_date == NOW.date()
    open_day(historical, 0)
    third = inspect(historical, reader, now, second.next_cursor)
    assert third.status == "NEEDED" and third.receipt.d_need == NOW.date()


def test_absence_after_unknown_proves_demand_only(historical):
    reader, now = setup(historical, calendar=None)
    open_day(historical, 3)
    result = inspect(historical, reader, now)
    assert result.status == "NEEDED" and result.receipt.d_need == NOW.date() + timedelta(days=3)


def test_single_snapshot_full_closed_range_can_prove_none(historical):
    reader, now = setup(historical, 10)
    assert inspect(historical, reader, now).status == "NONE"


def test_historical_budget_32_dates_plus_one_verified_checkpoint(historical, monkeypatch):
    reader, now = setup(historical, 70, calendar=True)
    publish(historical, transition=False)
    calls, windows = [], []
    original_read = module._CompletionReader.read
    original_discover = module.discover_missed_closes

    def counted_read(self, identity):
        calls.append(identity.official_trade_date)
        return original_read(self, identity)

    def counted_discover(**kwargs):
        result = original_discover(**kwargs)
        windows.append(result)
        return result

    monkeypatch.setattr(module._CompletionReader, "read", counted_read)
    monkeypatch.setattr(module, "discover_missed_closes", counted_discover)
    assert inspect(historical, reader, now).status == "NEEDED"
    assert len(calls) == 33 and len(windows) == 1
    assert (windows[0].window_end - windows[0].window_start).days == 31


def test_unrelated_event_time_and_same_calendar_do_not_reset(historical):
    reader, now = setup(historical)
    first = inspect(historical, reader, now)
    open_day(historical, 32)
    with historical.work() as uow:
        uow.events.append(MonitorEventDraft(
            event_id=monitor_event_id(MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                                      "600000.SH", "other"),
            event_type=MonitorEventType.SYMBOL_SNAPSHOT_UPDATED, aggregate_id="600000.SH",
            payload=MonitorEventPayload(entity_id="600000.SH", symbol="600000.SH",
                                       result_hash="a" * 64),
            occurred_at=NOW,
        ))
        uow.commit()
    mutate(historical, "UPDATE trading_calendar SET is_open=is_open")
    result = inspect(historical, reader, now + timedelta(days=1), first.next_cursor)
    assert result.status == "NEEDED" and result.receipt.d_need == NOW.date() + timedelta(days=32)


def test_checkpoint_advance_skips_prefix_and_rollback_invalidates_cursor(historical):
    reader, now = setup(historical, 70)
    first = inspect(historical, reader, now)
    open_day(historical, 40)
    publish(historical, day=NOW.date() + timedelta(days=40), transition=False)
    open_day(historical, 41)
    second = inspect(historical, reader, now, first.next_cursor)
    assert second.status == "NEEDED" and second.receipt.d_need == NOW.date() + timedelta(days=41)
    mutate(historical, "DELETE FROM evaluation_result", "DELETE FROM evaluation_ledger",
           "DELETE FROM monitor_event WHERE event_type='symbol.snapshot.updated'")
    assert inspect(historical, reader, now, second.next_cursor).reason == "checkpoint_rollback"
    assert not valid(historical, reader, second.receipt, now)


def test_checkpoint_covers_end_proves_none(historical):
    reader, now = setup(historical, 40)
    open_day(historical, 39)
    publish(historical, day=NOW.date() + timedelta(days=39), transition=False)
    assert inspect(historical, reader, now).status == "NONE"


@pytest.mark.parametrize("damage", [
    "DELETE FROM evaluation_result",
    "DELETE FROM monitor_event WHERE event_type='symbol.snapshot.updated'",
    "UPDATE evaluation_result SET result_json='{}'",
])
def test_bare_or_corrupt_checkpoint_is_unknown(historical, damage):
    reader, now = setup(historical, 10, calendar=True)
    publish(historical, transition=False)
    mutate(historical, damage)
    assert inspect(historical, reader, now).status == "UNKNOWN"


def test_orphan_publication_is_unknown(historical):
    reader, now = setup(historical, 1, calendar=True)
    publish(historical, transition=False)
    mutate(historical, "DELETE FROM evaluation_result", "DELETE FROM evaluation_ledger")
    assert inspect(historical, reader, now).status == "UNKNOWN"


@pytest.mark.parametrize("offset", [0, 3])
def test_completed_or_checkpoint_covered_witness_invalidates_receipt(historical, offset):
    reader, now = setup(historical, 10, calendar=True)
    result = inspect(historical, reader, now)
    assert valid(historical, reader, result.receipt, now)
    publish(historical, day=NOW.date() + timedelta(days=offset), transition=False)
    assert not valid(historical, reader, result.receipt, now)


@pytest.mark.parametrize("today", [True, False])
@pytest.mark.parametrize("change", ["rollback", "cross_day", "new_reader", "aba"])
def test_receipt_invalidations(historical, today, change):
    reader, now = setup(historical, 10, calendar=True)
    now = NOW if today else now
    receipt = inspect(historical, reader, now).receipt
    if change == "rollback":
        now -= timedelta(seconds=1)
    elif change == "cross_day":
        now += timedelta(days=1)
    elif change == "new_reader":
        reader = module.LegacyHistoricalCloseReader(historical.factory)
    else:
        historical.clock[0] = NOW - timedelta(minutes=1)
        with historical.work() as uow:
            uow.plans.deactivate(historical.plan.symbol, expected_revision=2)
            uow.plans.activate(historical.plan, expected_revision=3,
                               validation=historical.validation)
            uow.commit()
    assert not valid(historical, reader, receipt, now)


def test_identity_aba_restarts_cursor_from_authoritative_start(historical):
    reader, now = setup(historical, calendar=None)
    first = inspect(historical, reader, now)
    historical.clock[0] = NOW - timedelta(minutes=6)
    with historical.work() as uow:
        uow.plans.deactivate(historical.plan.symbol, expected_revision=2)
        uow.plans.activate(historical.plan, expected_revision=3, validation=historical.validation)
        uow.commit()
    open_day(historical, 0)
    result = inspect(historical, reader, now, first.next_cursor)
    assert result.status == "NEEDED" and result.receipt.d_need == NOW.date()
    assert result.identity.activation_revision == 4


@pytest.mark.parametrize("damage", [
    "DELETE FROM audit_log WHERE action='PLAN_ACTIVATED'",
    "UPDATE active_plan SET activated_at='2026-08-06T14:55:00+08:00'",
    "UPDATE plan_version SET plan_hash='" + "a"*64 + "' WHERE status='ACTIVE'",
])
def test_full_identity_is_validated_even_today(historical, damage):
    reader, _ = setup(historical)
    mutate(historical, damage)
    result = inspect(historical, reader, NOW)
    assert result.status == "UNKNOWN" and result.next_cursor is None


def mark_pending(historical):
    historical.clock[0] = NOW
    with historical.work() as uow:
        RuntimeEvaluationService._mark_close_pending(
            uow, plan=historical.plan, symbol=historical.plan.symbol,
            trade_date=NOW.date(), evaluated_at=NOW, activation_revision=2,
        )
        assert uow.projections.get_pending_official_close(
            symbol=historical.plan.symbol, trade_date=NOW.date(),
        ) is not None
        uow.commit()


@pytest.mark.parametrize("operation", ["inspect", "validate"])
def test_normal_pending_preserves_independent_historical_evidence(historical, operation):
    reader, now = setup(historical, 1, calendar=True)
    before = inspect(historical, reader, now)
    assert before.status == "NEEDED" and before.receipt.d_need == NOW.date()
    assert valid(historical, reader, before.receipt, now)
    assert NOW.date() in reader.missing_targets(historical.plan.symbol, now)
    mark_pending(historical)
    assert NOW.date() in reader.missing_targets(historical.plan.symbol, now)
    if operation == "inspect":
        after = inspect(historical, reader, now)
        assert after.status == "NEEDED" and after.reason == "historical_absence"
        assert after.identity == before.identity and after.receipt.d_need == NOW.date()
        assert after.next_cursor is not None
    else:
        assert valid(historical, reader, before.receipt, now)


@pytest.mark.parametrize("missing_evidence", ["calendar", "activation", "completion"])
def test_pending_alone_cannot_authorize_historical_demand(historical, missing_evidence):
    reader, now = setup(historical, 1, calendar=True)
    mark_pending(historical)
    if missing_evidence == "calendar":
        mutate(historical, "DELETE FROM trading_calendar")
    elif missing_evidence == "activation":
        mutate(historical, "DELETE FROM audit_log WHERE action='PLAN_ACTIVATED'")
    else:
        publish(historical, transition=False)
        mutate(historical, "DELETE FROM evaluation_result")
    result = inspect(historical, reader, now)
    assert result.status == "UNKNOWN" and result.receipt is None


def test_zero_writes_and_no_external_calls_with_dirty_caller_session(historical, monkeypatch):
    reader, now = setup(historical, 10, calendar=True)
    import socket
    monkeypatch.setattr(socket, "create_connection", forbid)
    statements = []

    def record(connection, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(historical.engine, "before_cursor_execute", record)
    with historical.factory() as session:
        unsaved = TradingCalendar(exchange="SSE", cal_date=now.date(), is_open=True)
        session.add(unsaved)
        result = reader.inspect_permission_demand_in_session(session, historical.plan.symbol, now)
        transaction = session.get_transaction()
        assert reader.validate_permission_demand_in_session(session, result.receipt, now)
        assert session.get_transaction() is transaction and unsaved in session.new
        assert session.scalar(text("SELECT count(*) FROM trading_calendar")) == 10
    assert statements and all(sql.lstrip().upper().startswith(("SELECT", "BEGIN"))
                              for sql in statements)


@pytest.mark.parametrize("change", ["rollback", "new_reader"])
def test_cursor_instance_and_clock_invalidation(historical, change):
    reader, now = setup(historical)
    cursor = inspect(historical, reader, now).next_cursor
    if change == "rollback":
        now -= timedelta(seconds=1)
    else:
        reader = module.LegacyHistoricalCloseReader(historical.factory)
    result = inspect(historical, reader, now, cursor)
    assert result.status == "UNKNOWN" and result.reason == "invalid_cursor"
    assert result.next_cursor is None


def test_calendar_change_invalidates_historical_witness(historical):
    reader, now = setup(historical, 1, calendar=True)
    receipt = inspect(historical, reader, now).receipt
    mutate(historical, "DELETE FROM trading_calendar")
    assert not valid(historical, reader, receipt, now)


def test_checkpoint_corruption_invalidates_existing_receipt_and_cursor(historical):
    reader, now = setup(historical, 40, calendar=True)
    publish(historical, transition=False)
    result = inspect(historical, reader, now)
    mutate(historical, "UPDATE evaluation_result SET result_json='{}'")
    assert not valid(historical, reader, result.receipt, now)
    assert inspect(historical, reader, now, result.next_cursor).status == "UNKNOWN"


def test_orphan_publication_read_retains_1000_plus_one_cap(historical):
    reader, now = setup(historical, 1, calendar=True)
    with historical.work() as uow:
        for i in range(1001):
            uow.events.append(MonitorEventDraft(
                event_id=monitor_event_id(MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                                          historical.plan.symbol, str(i)),
                event_type=MonitorEventType.SYMBOL_SNAPSHOT_UPDATED,
                aggregate_id=historical.plan.symbol,
                payload=MonitorEventPayload(entity_id=historical.plan.symbol,
                                           symbol=historical.plan.symbol, result_hash="a" * 64),
                occurred_at=NOW,
            ))
        uow.commit()
    assert inspect(historical, reader, now).status == "UNKNOWN"


def test_paging_reaches_day_371_without_age_cutoff(historical):
    reader, now = setup(historical, 400)
    open_day(historical, 370)
    cursor = None
    for _ in range(11):
        result = inspect(historical, reader, now, cursor)
        assert result.status == "UNKNOWN"
        cursor = result.next_cursor
    result = inspect(historical, reader, now, cursor)
    assert result.status == "NEEDED"
    assert result.receipt.d_need == NOW.date() + timedelta(days=370)


@pytest.mark.parametrize("policy_start, activated_offset", [(5, 0), (0, 5)])
def test_authoritative_start_respects_policy_and_actual_activation(
    historical, policy_start, activated_offset,
):
    reader, now = setup(historical, 10, calendar=True, policy_start=policy_start,
                        activated_offset=activated_offset)
    result = inspect(historical, reader, now)
    assert result.status == "NEEDED"
    assert result.receipt.d_need == NOW.date() + timedelta(days=5)
