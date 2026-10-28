"""Current channel admission and alert projection recheck real source owners."""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import insert, select, text, update
from tests.integration.test_alert_only_legacy_storage import _legacy_layout, _price_alert_plan
from tests.integration.test_daily_plan_chain import FRIDAY, Chain
from tests.integration.test_market_exception_runtime import exception_chain as exception_chain
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_source_action_cutover import _daily
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_risk_simulation import (
    _AT,
    _ready,
    _retained_core_case,
)
from tests.integration.test_source_coverage_simulation_actions import _stale
from tests.integration.test_source_coverage_simulation_actions import current as current

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.notifications.daily_models import (
    DailyAlertPayload,
    daily_alert_key,
    render_daily_alert,
)
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import (
    ActivePlan,
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
)
from trade_plan_monitor.state.source_coverage_models import (
    COVERAGE_TRIGGER_SQL,
    CoverageAssessmentRow,
    CoverageReviewRow,
)
from trade_plan_monitor.state.source_coverage_store import SourceCoverageIntegrityError
from trade_plan_monitor.web.alert_service import PersistentAlertOperationService

_GENERATION = UUID(int=7109)


def _event(chain, cause_id):
    with chain.plans._unit_of_work() as work:
        rows, _ = work.alerts.list_events(symbol=chain.plan.symbol, signal_type=None,
            acknowledged=None, start_at=None, end_at=None, offset=0, limit=100)
        event, = (row for row in rows if row.cause_id == cause_id
                  and row.evaluated_at == chain.now)
        return event


def _admission(chain, *, generation=lambda: _GENERATION):
    return CurrentDeliveryAdmission(chain.plans._session_factory, runtime_generation=generation)


def _alert_service(chain):
    chain.app.state.alert_operation_service = PersistentAlertOperationService(
        unit_of_work_factory=chain.plans._unit_of_work, clock=lambda: chain.now)


def _message_with_metadata(event, **changes):
    value = event.model_dump(mode="python", exclude={
        "sequence", "message_text", "created_at", "acknowledged_at"}) | changes
    value["dedup_key"] = daily_alert_key(value["cause_id"], value["plan_hash"],
        value["signal_type"], value["simulated_qty"], value["quantity"], value["risk_scope"],
        value["confirmed_trade_date"])
    payload = DailyAlertPayload.model_validate(value)
    return type(event).model_validate(payload.model_dump(mode="python") | dict(
        sequence=event.sequence, message_text=render_daily_alert(payload),
        created_at=event.created_at, acknowledged_at=event.acknowledged_at))


def test_fresh_real_source_and_current_signal_remain_deliverable(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
        assert work.alerts.is_current_actionable(event, market_date=chain.now.date())
        assert work.alerts.is_delivery_allowed(event, market_date=chain.now.date())
    assert _admission(chain)(event, chain.now)


def test_queued_ordinary_event_cannot_keep_old_source_review_after_a_new_assessment(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    assert _admission(chain)(event, chain.now)
    _stale(chain)
    assert not _admission(chain)(event, chain.now)
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)
        assert work.alerts.get(event.event_id) == event


def test_alert_center_keeps_stale_message_but_revokes_its_current_action_label(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    _stale(chain)
    _alert_service(chain)
    response = chain.client.get("/api/v1/alerts", params={"symbol": chain.plan.symbol})
    assert response.status_code == 200
    actual, = (row for row in response.json()["items"] if row["eventId"] == str(event.event_id))
    assert actual["currentActionable"] is False
    with chain.plans._unit_of_work() as work:
        assert not work.alerts.is_current_actionable(event, market_date=chain.now.date())
        assert not work.alerts.is_delivery_allowed(event, market_date=chain.now.date())
        assert work.alerts.get(event.event_id) == event


def test_original_daily_review_is_not_a_missing_current_source_review_receipt(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    trigger = "pma_seal_source_coverage_review_delete"
    with chain.plans._unit_of_work() as work:
        work.daily.session.execute(text("DROP TRIGGER " + trigger))
        work.daily.session.query(CoverageReviewRow).filter_by(
            plan_version_id=chain.version["id"]).delete()
        work.daily.session.execute(text(COVERAGE_TRIGGER_SQL[trigger]))
        old = work.daily.get("review-" + chain.version["id"])
        assert old["payload"]["confirmed"] and old["payload"]["review_id"] == event.review_id
        work.commit()
    assert not _admission(chain)(event, chain.now)


def _corrupt_source(chain):
    trigger = "pma_seal_source_coverage_assessment_update"
    with chain.plans._unit_of_work() as work:
        work.daily.session.execute(text("DROP TRIGGER " + trigger))
        row = work.daily.session.query(CoverageAssessmentRow).filter_by(
            plan_version_id=chain.version["id"], revision=1).one()
        work.daily.session.execute(update(CoverageAssessmentRow).where(
            CoverageAssessmentRow.plan_version_id == chain.version["id"]
        ).values(payload_json=row.payload_json + " "))
        work.daily.session.execute(text(COVERAGE_TRIGGER_SQL[trigger]))
        work.commit()


def test_corrupt_source_is_an_alert_read_integrity_error_not_a_current_action(current,
                                                                          monkeypatch):
    chain, _ = current
    _corrupt_source(chain)
    _alert_service(chain)
    monkeypatch.setattr(chain.client._transport, "raise_server_exceptions", False)
    response = chain.client.get("/api/v1/alerts", params={"symbol": chain.plan.symbol})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "source_coverage_assessment" not in response.text


def test_pure_price_reminder_keeps_old_storage_and_inventory_independence(tmp_path):
    chain = Chain(tmp_path)
    raw = _price_alert_plan().model_dump(mode="json")
    raw["alert_rules"][0]["condition"]["reference"]["source"] = "Exact synthetic fixed threshold"
    chain.plan = type(chain.plan).model_validate(raw)
    with chain.client:
        _legacy_layout(chain)
        chain.activate()
        result = chain.evaluate(series=chain.series(), official=FRIDAY)
        assert len(result.event_ids) == 1
        with chain.plans._unit_of_work() as work:
            event = work.alerts.get(UUID(result.event_ids[0]))
            assert event.signal_type == "REMINDER" and event.quantity is None
            assert event.alert_kind == "RISK_ALERT" and event.next_step == "REVIEW_ALERT"
            assert not result.snapshot["inventory"]["known"]
            assert daily_delivery_allowed(work.daily.session, event, chain.now)
        _stale(chain)
        assert _admission(chain)(event, chain.now)


def _risk_event(case):
    _ready(case)
    with case.work() as work:
        rows, _ = work.alerts.list_events(symbol=case.draft.symbol, signal_type="RISK_EXIT",
            acknowledged=None, start_at=None, end_at=None, offset=0, limit=100)
        event, = (row for row in rows if row.cause_id == case.cause_id)
        return event


@pytest.mark.parametrize("options", [{}, {"buy_only_failure": True}, {"expired": True}])
def test_real_cutover_risk_message_keeps_its_independent_source_basis(legacy, options):
    case = legacy(**options)
    event = _risk_event(case)
    assert event.signal_type == "RISK_EXIT" and event.quantity == 300
    with case.work() as work:
        assert daily_delivery_allowed(work.daily.session, event, _AT)
    admission = CurrentDeliveryAdmission(case.sessions, runtime_generation=lambda: _GENERATION)
    assert admission(event, _AT)


def test_unowned_risk_sibling_cannot_veto_or_resize_the_actual_risk_message(legacy):
    case = _retained_core_case(legacy)
    event = _risk_event(case)
    assert event.quantity == 200
    ghost = deepcopy(case.risk) | dict(rule_id="removed-risk", risk_id="unowned-sibling",
                                     target_core_qty=0)
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord),
                           _daily("unowned-sibling", "RISK", case.draft, ghost))
    with case.work() as work:
        assert daily_delivery_allowed(work.daily.session, event, _AT)
        assert work.alerts.get(event.event_id) == event


def test_changed_risk_policy_cannot_keep_a_queued_risk_exit_just_by_confirmed_status(legacy):
    case = legacy()
    event = _risk_event(case)
    with case.work() as work:
        risk = work.daily.get(case.cause_id)
        work.daily.save(case.cause_id, kind="RISK", symbol=case.draft.symbol,
            lineage=risk["lineage"], expected_revision=risk["revision"],
            payload=risk["payload"] | dict(risk_line_fen=risk["payload"]["risk_line_fen"] + 1))
        work.commit()
    with case.work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, _AT)


def test_retained_risk_message_does_not_downgrade_an_unknown_global_source_requirement(legacy):
    # A genuine old-format message can outlive its producer. It carries no new
    # source-coverage permission, even when all its old owner IDs still match.
    original = legacy()
    event = _risk_event(original)
    unknown = legacy(extra="Every exit also depends on the blue lantern approval.")
    assert unknown.id == event.plan_version_id
    _ready(unknown, expected_status="NONE")
    payload = DailyAlertPayload.model_validate(event.model_dump(mode="python", exclude={
        "sequence", "message_text", "created_at", "acknowledged_at"}))
    with unknown.work() as work:
        assert work.plans.get_version_details(unknown.id).daily_issues == ()
        retained = work.alerts.enqueue_daily(payload)
        work.commit()
    admission = CurrentDeliveryAdmission(unknown.sessions, runtime_generation=lambda: _GENERATION)
    assert not admission(retained, _AT)


@pytest.mark.parametrize("owner", ["active", "version", "source", "provenance"])
def test_held_orm_owner_does_not_hide_actual_sql_changes_before_delivery(current, owner):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        version = session.get(PlanVersion, event.plan_version_id)
        model, identity, attribute = {
            "active": (ActivePlan, event.symbol, "revision"),
            "version": (PlanVersion, event.plan_version_id, "payload_json"),
            "source": (PlanSource, version.source_id, "source_text"),
            "provenance": (PlanReviewProvenance, event.plan_version_id, "mapping_json"),
        }[owner]
        held = session.get(model, identity)
        before = getattr(held, attribute)
        changed = {attribute: before + 1 if owner == "active" else before + " "}
        primary_key, = model.__table__.primary_key.columns
        session.execute(update(model).where(primary_key == identity).values(**changed),
                        execution_options={"synchronize_session": False})
        assert getattr(held, attribute) == before
        if owner == "active":
            assert not daily_delivery_allowed(session, event, chain.now)
        else:
            with pytest.raises(SourceCoverageIntegrityError):
                daily_delivery_allowed(session, event, chain.now)


def test_delivery_rejects_relevant_dirty_owner_without_flushing_or_discarding_it(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        held = session.get(PlanVersion, event.plan_version_id)
        original = held.payload_json
        held.payload_json += " "
        with pytest.raises(SourceCoverageIntegrityError):
            daily_delivery_allowed(session, event, chain.now)
        assert held in session.dirty and held.payload_json == original + " "
        with session.no_autoflush:
            stored = session.scalar(select(PlanVersion.payload_json).where(
                PlanVersion.id == held.id))
        assert stored == original


def test_delivery_does_not_flush_or_discard_an_unrelated_dirty_source(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        other = PlanSource(id=str(UUID(int=710910)), source_text="Unrelated persisted source",
            source_hash=sha256(b"Unrelated persisted source").hexdigest(),
            created_at=chain.now.isoformat())
        session.add(other)
        session.flush()
        original = other.source_text
        other.source_text = "Unrelated pending edit"
        assert daily_delivery_allowed(session, event, chain.now)
        assert other in session.dirty and other.source_text == "Unrelated pending edit"
        with session.no_autoflush:
            stored = session.scalar(select(PlanSource.source_text).where(PlanSource.id == other.id))
        assert stored == original


def test_exception_review_reminder_requires_current_source_at_send_time(exception_chain):
    chain = exception_chain
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    candidate, = result.snapshot["exception_candidates"]
    event = _event(chain, candidate["candidate"]["candidate_id"])
    assert event.signal_type == "REMINDER" and event.alert_kind == "EXCEPTION_REVIEW"
    assert event.quantity is None and _admission(chain)(event, chain.now)
    _stale(chain)
    assert not _admission(chain)(event, chain.now)
    with chain.plans._unit_of_work() as work:
        assert not work.alerts.is_current_actionable(event, market_date=chain.now.date())
        assert work.alerts.get(event.event_id) == event


def test_held_risk_orm_cannot_hide_changed_actual_risk_policy(legacy):
    case = legacy()
    event = _risk_event(case)
    with case.work() as work:
        session = work.daily.session
        held = session.get(DailyRecord, case.cause_id)
        before = held.payload_json
        payload = work.daily.get(case.cause_id)["payload"]
        session.execute(update(DailyRecord).where(DailyRecord.id == held.id).values(
            payload_json=canonical(payload | dict(risk_line_fen=payload["risk_line_fen"] + 1))),
            execution_options={"synchronize_session": False})
        assert held.payload_json == before
        assert not daily_delivery_allowed(session, event, _AT)


@pytest.mark.parametrize("field,value", [
    ("activation_revision", 999),
    ("plan_id", "different-plan"),
    ("plan_version", 99),
    ("review_id", str(UUID(int=710911))),
])
def test_actual_source_basis_cannot_authorize_a_different_message_binding(current, field, value):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    changed = event.model_copy(update={field: value})
    assert not _admission(chain)(changed, chain.now)
    with chain.plans._unit_of_work() as work:
        assert work.alerts.get(event.event_id) == event


@pytest.mark.parametrize("field", ["side", "rule", "confirmed", "execution"])
def test_source_grant_cannot_authorize_different_actual_signal_fields(current, field):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    changes = {
        "side": {"signal_type": "SELL" if event.signal_type == "BUY" else "BUY"},
        "rule": {"rule_id": "unowned-other-rule"},
        "confirmed": {"confirmed_trade_date": event.confirmed_trade_date + timedelta(days=1)},
        "execution": {"execution_date": event.execution_date + timedelta(days=1)},
    }[field]
    changed = _message_with_metadata(event, **changes)
    assert not _admission(chain)(changed, chain.now)
    with chain.plans._unit_of_work() as work:
        assert work.alerts.get(event.event_id) == event


def test_optional_ordinary_message_metadata_remains_optional(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    changed = _message_with_metadata(event, rule_id=None, confirmed_trade_date=None,
                                     execution_date=None)
    assert _admission(chain)(changed, chain.now)


def test_actual_signal_cannot_authorize_a_risk_message_role(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    changed = _message_with_metadata(event, signal_type="RISK_EXIT", severity="RISK",
                                     next_step="REVIEW_RISK_EXIT", risk_scope=None)
    assert not _admission(chain)(changed, chain.now)


def test_independent_historical_risk_basis_cannot_authorize_an_ordinary_message_role(legacy):
    case = legacy()
    event = _risk_event(case)
    changed = _message_with_metadata(event, signal_type="SELL", severity="ACTION",
                                     next_step="CONFIRM_SIMULATED_TRADE", risk_scope=None)
    admission = CurrentDeliveryAdmission(case.sessions, runtime_generation=lambda: _GENERATION)
    assert not admission(changed, _AT)
