"""Frozen capture has its own exact observation owner and cannot grant live delivery."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import event as sql_events
from sqlalchemy import select, update
from tests.integration.test_market_exception_replay import exception_loop_input
from tests.integration.test_market_exception_runtime import (
    exception_chain as exception_chain,
)
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_monitor_loop_reminders import inputs
from tests.unit.test_monitor_loop_input import account, frozen, lot
from tests.unit.test_monitor_loop_schedule import at, calendar, row, version
from tests.unit.test_unified_plan_domain import unified_payload
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.plan_schedule import LoopSchedule
from trade_plan_monitor.backtest.reminder_capture import CAPTURE_TABLE, ReminderCapture
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.notifications.daily_models import (
    DailyAlertPayload,
    daily_alert_key,
    render_daily_alert,
)
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.market_exception_models import (
    ExceptionCandidate,
    transition_candidate,
)
from trade_plan_monitor.state.models import ActivePlan, PlanSource, PlanVersion
from trade_plan_monitor.state.models import AlertEvent as AlertEventRow
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_store import SourceCoverageIntegrityError


def _event(loop):
    result = loop.evaluate(inputs())
    event_id, = result.event_ids
    with loop.work() as work:
        return work.alerts.get(UUID(event_id))


def _capture(work, loop, event, *, reader=None):
    return ReminderCapture(work, limit=loop.run_input.limits.max_reminders,
        _source_authority_reader=loop._source_authority_reader if reader is None else reader
    ).capture(event, loop.now)


def _count(work):
    return len(work.daily.session.execute(select(CAPTURE_TABLE.c.sequence)).all())


def _changed_event(event, **changes):
    value = event.model_dump(mode="python", exclude={
        "sequence", "message_text", "created_at", "acknowledged_at"}) | changes
    value["dedup_key"] = daily_alert_key(value["cause_id"], value["plan_hash"],
        value["signal_type"], value["simulated_qty"], value["quantity"], value["risk_scope"],
        value["confirmed_trade_date"])
    payload = DailyAlertPayload.model_validate(value)
    return type(event).model_validate(payload.model_dump(mode="python") | dict(
        sequence=event.sequence, message_text=render_daily_alert(payload),
        created_at=event.created_at, acknowledged_at=event.acknowledged_at))


def test_real_loop_capture_uses_frozen_observation_without_live_source_provenance(tmp_path):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        before = loop.inventory()
        captured, = loop.capture((str(event.event_id),))
        assert captured.status == "CAPTURED" and captured.execution_candidate
        assert captured.event == event and captured.event.quantity == 100
        assert loop.inventory() == before
        with loop.work() as work:
            basis = loop._source_authority_reader(work, loop.details.id)
            assert basis.basis == "REPLAY_OBSERVATION"
            assert not hasattr(basis, "coverage_complete") and not hasattr(basis, "status")


def test_default_capture_still_uses_the_strict_live_source_reader(tmp_path):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        with loop.work() as work:
            with pytest.raises(SourceCoverageIntegrityError):
                ReminderCapture(work, limit=10).capture(event, loop.now)
            assert _count(work) == 0


@pytest.mark.parametrize("reader", [lambda *_a, **_kw: True,
    SimpleNamespace(basis="REPLAY_OBSERVATION", delivery_allowed=lambda *_a: True),
    SimpleNamespace(basis="CURRENT", coverage_complete=True)])
def test_a_counterfeit_reader_or_context_is_not_a_frozen_capture_owner(tmp_path, reader):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        with loop.work() as work:
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                _capture(work, loop, event, reader=reader)
            assert _count(work) == 0


def test_observation_capability_cannot_move_between_identical_private_engines(tmp_path):
    with LoopSession(tmp_path / "first", frozen(), calendar()) as first:
        with LoopSession(tmp_path / "second", frozen(), calendar()) as second:
            event = _event(second)
            with second.work() as work:
                with pytest.raises(SourceCoverageAuthorityError,
                                   match="SOURCE_COVERAGE_INTEGRITY"):
                    _capture(work, second, event, reader=first._source_authority_reader)
                assert _count(work) == 0


@pytest.mark.parametrize("mutation", ["input-clone", "closed", "view"])
def test_capture_retains_exact_decoded_input_and_session_lifecycle(tmp_path, mutation):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        if mutation == "input-clone":
            loop.run_input = type(loop.run_input).model_validate_json(
                loop.run_input.model_dump_json())
        elif mutation == "closed":
            loop._closed = True
        else:
            loop.details = replace(loop.details, content_hash="f" * 64)
        with loop.work() as work:
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                _capture(work, loop, event)
            assert _count(work) == 0


@pytest.mark.parametrize("changes", [dict(quantity=200), dict(rule_id="another-rule"),
    dict(plan_id="another-plan"), dict(review_id="another-review")])
def test_self_consistent_event_rendering_cannot_replace_the_persisted_event(tmp_path, changes):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        changed = _changed_event(event, **changes)
        with loop.work() as work:
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                _capture(work, loop, changed)
            assert _count(work) == 0


@pytest.mark.parametrize("owner", ["manifest", "message"])
def test_capture_reads_actual_persistent_source_and_message_owners(tmp_path, owner):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        with loop.work() as work:
            sql = work.daily.session
            if owner == "manifest":
                version = sql.get(PlanVersion, loop.details.id)
                held = sql.get(PlanSource, version.source_id)
                statement = update(PlanSource).where(PlanSource.id == held.id).values(
                    source_text='{"forged":true}')
            else:
                held = sql.get(AlertEventRow, str(event.event_id))
                statement = update(AlertEventRow).where(AlertEventRow.id == held.id).values(
                    message_text=held.message_text + " corrupt")
            sql.execute(statement.execution_options(synchronize_session=False))
            assert held is not None
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                _capture(work, loop, event)
            assert _count(work) == 0


@pytest.mark.parametrize("owner", ["plan", "active", "event", "head", "unrelated",
                                   "unrelated-dirty"])
def test_capture_source_check_does_not_flush_or_discard_pending_owners(tmp_path, owner):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        with loop.work() as work:
            sql = work.daily.session
            if owner == "plan":
                held = sql.get(PlanVersion, loop.details.id)
                held.payload_json += " "
            elif owner == "active":
                held = sql.get(ActivePlan, event.symbol)
                held.revision += 1
            elif owner == "event":
                held = sql.get(AlertEventRow, str(event.event_id))
                held.message_text += " pending"
            elif owner == "head":
                held = sql.get(DailyRecord, "evaluation-head-" + event.symbol)
                held.payload_json += " "
            elif owner == "unrelated":
                held = DailyRecord(id="unrelated", kind="DRAFT", symbol="000001.SZ",
                    lineage="000001.SZ", revision=0, payload_json="{}",
                    created_at=loop.now.isoformat(), updated_at=loop.now.isoformat())
                sql.add(held)
            else:
                held = PlanSource(id=str(UUID(int=9988)), source_text="Unrelated stored source",
                    source_hash="f" * 64, created_at=loop.now.isoformat())
                sql.add(held)
                sql.flush()
                held.source_text += " pending"
            driver = sql.connection().connection.driver_connection
            before = driver.total_changes
            if owner in {"unrelated", "unrelated-dirty"}:
                assert _capture(work, loop, event).status == "CAPTURED"
                assert driver.total_changes == before + 1  # Only the intended capture row.
                assert held in (sql.new if owner == "unrelated" else sql.dirty)
            else:
                with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                    _capture(work, loop, event)
                assert driver.total_changes == before and held in sql.dirty


def test_actual_current_signal_changes_are_suppressed_without_resizing_the_message(tmp_path):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        with loop.work() as work:
            held = work.daily.session.get(DailyRecord, event.cause_id)
            payload = work.daily.get(event.cause_id)["payload"] | dict(executable_qty=0)
            work.daily.session.execute(update(DailyRecord).where(DailyRecord.id == held.id)
                .values(payload_json=canonical(payload)).execution_options(synchronize_session=False))
            value = _capture(work, loop, event)
            assert value.status == "SUPPRESSED" and value.event.quantity == 100
            assert held.payload_json == canonical(payload)


def test_completed_capture_receipt_is_returned_before_any_new_observation_check(tmp_path):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        original, = loop.capture((str(event.event_id),))
        with loop.work() as work:
            impossible = SimpleNamespace(delivery_allowed=lambda *_a: pytest.fail(
                "reopened capture"))
            assert _capture(work, loop, event, reader=impossible) == original
            assert _count(work) == 1


def test_an_instance_method_override_cannot_replace_the_issued_owner_check(tmp_path, monkeypatch):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        loop._closed = True
        monkeypatch.setattr(loop._source_authority_reader, "delivery_allowed", lambda *_a: True)
        with loop.work() as work:
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                _capture(work, loop, event)
            assert _count(work) == 0


def test_completed_receipt_does_not_flush_pending_data_or_reopen_source(tmp_path):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        original, = loop.capture((str(event.event_id),))
        with loop.work() as work:
            held = work.daily.session.get(ActivePlan, event.symbol)
            held.revision += 1
            driver = work.daily.session.connection().connection.driver_connection
            before = driver.total_changes
            assert _capture(work, loop, event, reader=object()) == original
            assert driver.total_changes == before and held in work.daily.session.dirty


def test_private_delivery_refresh_uses_bounded_primary_key_pages_without_skipping(tmp_path):
    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        event = _event(loop)
        with loop.work() as work:
            work.daily.session.execute(DailyRecord.__table__.insert(), [dict(
                id=f"capture-history-{number:04d}", symbol=event.symbol, kind="DRAFT",
                lineage=event.symbol, revision=1, payload_json="{}",
                created_at=loop.now.isoformat(), updated_at=loop.now.isoformat())
                for number in range(600)])
            pages = []

            def trace(_connection, _cursor, statement, parameters, _context, _many):
                if statement.startswith("SELECT daily_plan_record.id \nFROM"):
                    pages.append((statement, parameters))

            sql_events.listen(loop.engine, "before_cursor_execute", trace)
            try:
                assert _capture(work, loop, event).status == "CAPTURED"
            finally:
                sql_events.remove(loop.engine, "before_cursor_execute", trace)
            assert len(pages) == 2
            assert all(parameters[-2:] == (500, 0) for _, parameters in pages)
            assert "daily_plan_record.id >" in pages[1][0]


def test_actual_exception_candidate_after_review_request_can_only_suppress_capture(
    exception_chain, tmp_path,
):
    chain = exception_chain
    market = exception_inputs(chain)
    days = tuple(TradingDay(exchange="SSE", cal_date=day, is_open=True,
        previous_trade_date=market.session_dates[index - 1] if index else day - timedelta(days=1))
        for index, day in enumerate(market.session_dates))
    with LoopSession(tmp_path, exception_loop_input(chain), days) as loop:
        result = loop.evaluate(market.model_copy(update={"trading_calendar": days}))
        with loop.work() as work:
            event, = (work.alerts.get(UUID(identity)) for identity in result.event_ids)
            assert event.alert_kind == "EXCEPTION_REVIEW" and event.signal_type == "REMINDER"
            assert loop._source_authority_reader.delivery_allowed(work, event, loop.now)
            held = work.daily.session.get(DailyRecord, event.cause_id)
            original = held.payload_json
            candidate = ExceptionCandidate.model_validate_json(original)
            rejected, decision = transition_candidate(candidate, to_state="REJECTED",
                command_id="frozen-capture-rejection", expected_revision=held.revision,
                now=loop.now, reason="Deterministic removal of this test occurrence permission")
            # Persist both native transition owners while retaining the clean old ORM view.
            work.daily.session.execute(DailyRecord.__table__.insert().values(
                id=decision.event_id, kind="EXCEPTION_EVENT", symbol=event.symbol,
                lineage=candidate.binding.lineage, revision=1,
                payload_json=canonical(decision.model_dump(mode="json")),
                created_at=loop.now.isoformat(), updated_at=loop.now.isoformat()))
            work.daily.session.execute(update(DailyRecord).where(DailyRecord.id == held.id)
                .values(payload_json=canonical(rejected.model_dump(mode="json")),
                        revision=held.revision + 1, updated_at=loop.now.isoformat())
                .execution_options(synchronize_session=False))
            assert held.payload_json == original
            captured = _capture(work, loop, event)
            assert captured.status == "SUPPRESSED" and captured.event == event
            assert held.payload_json == canonical(rejected.model_dump(mode="json"))


def test_actual_latched_risk_scope_is_recomputed_from_fresh_owned_rows(tmp_path):
    raw = unified_payload()
    branch = next(value for value in raw["risk_branches"] if value["kind"] == "ORDINARY_TECHNICAL")
    plan = research_plan().model_copy(update=dict(levels=raw["levels"],
        risk_branches=(branch,), ordinary_rules=()))
    run = frozen(schedule=LoopSchedule(entries=(row(value=version(plan=plan)),)),
        initial_account=account(lots=(lot(sellable_quantity=100),)))
    with LoopSession(tmp_path, run, calendar()) as loop:
        identity = daily_hash("daily-risk-obligation-v1", dict(symbol=plan.symbol,
                                                               kind="ORDINARY_TECHNICAL"))
        payload = dict(kind=branch["kind"], priority=branch["priority"], status="CONFIRMED",
            involves_core=branch["involves_core"], scope_evidence=branch["scope_evidence"],
            target_core_qty=0, target_tactical_qty=0, evidence_ids=[], blockers=[],
            risk_id=identity,
            confirmed_trade_date=str(at(19).date()), earliest_execution_date=str(at(20).date()),
            breach_trade_date=str(at(18).date()), second_close_date=str(at(19).date()),
            risk_line_fen=plan.levels.risk_line_fen, risk_comparison=plan.levels.risk_comparison,
            suspension_confirmation_policy=branch["suspension_confirmation_policy"])
        with loop.work() as work:
            work.daily.save(identity, kind="RISK", symbol=plan.symbol, lineage=plan.symbol,
                payload=payload, expected_revision=0)
            work.commit()
        result = loop.evaluate(inputs())
        with loop.work() as work:
            event, = (work.alerts.get(UUID(identity)) for identity in result.event_ids)
            assert event.signal_type == "RISK_EXIT" and event.quantity == 100
            assert loop._source_authority_reader.delivery_allowed(work, event, loop.now)
            held = work.daily.session.get(DailyRecord, event.cause_id)
            original = held.payload_json
            changed = work.daily.get(held.id)["payload"] | dict(target_core_qty=100)
            work.daily.session.execute(update(DailyRecord).where(DailyRecord.id == held.id)
                .values(payload_json=canonical(changed)).execution_options(synchronize_session=False))
            assert held.payload_json == original
            captured = _capture(work, loop, event)
            assert captured.status == "SUPPRESSED" and captured.event.risk_scope == event.risk_scope
            assert captured.event.quantity == 100 and not captured.execution_candidate
