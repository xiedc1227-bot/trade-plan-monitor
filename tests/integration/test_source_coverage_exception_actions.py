"""Actual exception grants need the current source receipt at each new boundary."""

from datetime import datetime, time
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from tests.integration import test_market_exception_runtime as runtime_fixture
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_market_exception_runtime import exception_inputs

from trade_plan_monitor.runtime.market_exceptions import (
    apply_exception_decision,
    current_exception_authority,
)
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
from trade_plan_monitor.state.market_exception_repository import ExceptionRepository
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityError,
    ExceptionDecisionCommand,
    ExceptionPreviewCommand,
    ExceptionRevocationCommand,
    preview_exception,
    revoke_exception,
    terminate_exception,
)
from trade_plan_monitor.state.simulation import (
    SimulationAuthorityError,
    SimulationCommand,
    simulate_inventory,
)
from trade_plan_monitor.state.source_action_authority import require_source_action_authority
from trade_plan_monitor.state.source_coverage_models import (
    COVERAGE_TRIGGER_SQL,
    CoverageAssessmentRow,
)
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore

exception_chain = runtime_fixture.exception_chain


def _expected(chain):
    return 100 if chain.route == "WEAK_MINIMUM" else 300


def _candidate(chain):
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert not result.snapshot["signals"]
    row, = result.snapshot["exception_candidates"]
    return ExceptionCandidate.model_validate(row["candidate"])


def _preview(chain, candidate):
    with chain.plans._unit_of_work() as work:
        result = preview_exception(work.daily, ExceptionPreviewCommand(
            candidate_id=candidate.candidate_id, expected_revision=1,
            proposed_quantity=None if chain.route == "WEAK_MINIMUM" else 300),
            current=lambda c: current_exception_authority(work, c, chain.now), now=chain.now)
        work.commit()
    return result


def _approval_command(preview, *, command_id="source-exception-approve"):
    return ExceptionDecisionCommand(command_id=command_id, candidate_id=preview.candidate_id,
        expected_revision=1, decision="APPROVE", reason="Review the complete frozen quantity",
        preview_id=preview.preview_id, preview_hash=preview.preview_hash)


def _approved(chain):
    candidate = _candidate(chain)
    shown = _preview(chain, candidate)
    command = _approval_command(shown)
    with chain.plans._unit_of_work() as work:
        receipt = apply_exception_decision(work, command, now=chain.now)
        work.commit()
    assert receipt.candidate.frozen_quantity == _expected(chain)
    return shown, command, receipt


def _append_bundle(work, chain, *, command_id="source-exception-reassessment"):
    store = SourceCoverageStore(work.daily.session)
    current = store.latest(chain.version["id"])
    assert current is not None and current.assessment.coverage_complete
    return store.append(chain.version["id"], current.assessment, inputs=current.inputs,
        expected_revision=current.revision, command_id=command_id, now=chain.now)


def _stale_source(chain):
    with chain.plans._unit_of_work() as work:
        result = _append_bundle(work, chain)
        work.commit()
    return result


def _ledger(chain):
    with chain.plans._unit_of_work() as work:
        return work.daily.session.execute(select(DailyRecord.__table__).where(
            DailyRecord.symbol == chain.plan.symbol).order_by(DailyRecord.id)).all()


def test_complete_fixture_has_real_current_source_review_before_any_exception_grant(
    exception_chain,
):
    chain = exception_chain
    candidate = _candidate(chain)
    with chain.plans._unit_of_work() as work:
        basis = require_source_action_authority(work, candidate.binding.plan_version_id)
        assert basis.basis == "CURRENT" and basis.coverage_evidence_hash
        assert not work.daily.list(symbol=chain.plan.symbol, kind="SIGNAL")
    shown = _preview(chain, candidate)
    assert shown.quantity == _expected(chain)


def test_stale_source_blocks_preview_without_creating_a_new_permission(exception_chain):
    chain = exception_chain
    candidate = _candidate(chain)
    _stale_source(chain)
    before = _ledger(chain)
    with pytest.raises(ExceptionAuthorityError, match="SOURCE_COVERAGE_STALE"):
        _preview(chain, candidate)
    assert _ledger(chain) == before


def test_stale_source_blocks_approval_without_freezing_quantity_or_creating_a_signal(
    exception_chain,
):
    chain = exception_chain
    shown = _preview(chain, _candidate(chain))
    _stale_source(chain)
    before = _ledger(chain)
    with pytest.raises(ExceptionAuthorityError, match="SOURCE_COVERAGE_STALE"):
        with chain.plans._unit_of_work() as work:
            apply_exception_decision(work, _approval_command(shown), now=chain.now)
            work.commit()
    assert _ledger(chain) == before


def test_approved_exception_cannot_consume_after_its_current_source_receipt_changes(
    exception_chain,
):
    chain = exception_chain
    _, _, approved = _approved(chain)
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    ready = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    signal, = ready.snapshot["signals"]
    assert signal["planned_qty"] == signal["executable_qty"] == _expected(chain)
    _stale_source(chain)
    before = _ledger(chain)
    with pytest.raises(SimulationAuthorityError, match="SOURCE_COVERAGE_STALE"):
        with chain.plans._unit_of_work() as work:
            simulate_inventory(work, SimulationCommand(plan_version_id=UUID(chain.version["id"]),
                cause_id=signal["signal_id"], expected_cause_revision=signal["revision"],
                expected_inventory_revision=1, quantity=_expected(chain)), chain.now)
            work.commit()
    assert _ledger(chain) == before
    with chain.plans._unit_of_work() as work:
        current = ExceptionRepository(work.daily).get(approved.candidate.candidate_id)
        assert current["payload"]["state"] == "APPROVED"
        assert current["payload"]["frozen_quantity"] == _expected(chain)


@pytest.mark.parametrize("revoke_first", [False, True])
def test_completed_approval_replay_is_historical_and_never_reopens_a_permission(
    exception_chain, revoke_first,
):
    chain = exception_chain
    _, command, original = _approved(chain)
    _stale_source(chain)
    if revoke_first:
        with chain.plans._unit_of_work() as work:
            revoke_exception(work.daily, ExceptionRevocationCommand(command_id="source-withdraw",
                approval_id=original.event.event_id, expected_revision=2,
                reason="Remove the exact occurrence permission"), now=chain.now)
            work.commit()
    before = _ledger(chain)
    with chain.plans._unit_of_work() as work:
        replay = apply_exception_decision(work, command, now=chain.now)
        work.commit()
    assert replay == original
    assert replay.candidate.frozen_quantity == _expected(chain)
    assert _ledger(chain) == before
    with chain.plans._unit_of_work() as work:
        live = ExceptionRepository(work.daily).get(original.candidate.candidate_id)
        assert live["payload"]["state"] == ("REVOKED" if revoke_first else "APPROVED")


@pytest.mark.parametrize("state", ["REVOKED", "INVALIDATED", "EXPIRED"])
def test_removing_exception_permission_does_not_require_a_new_source_receipt(
    exception_chain, state,
):
    chain = exception_chain
    _, _, approved = _approved(chain)
    _stale_source(chain)
    if state == "EXPIRED":
        chain.now = approved.candidate.binding.expires_at
    with chain.plans._unit_of_work() as work:
        if state == "REVOKED":
            result = revoke_exception(work.daily, ExceptionRevocationCommand(
                command_id="source-revoke", approval_id=approved.event.event_id,
                expected_revision=2, reason="Withdraw without granting anything"), now=chain.now)
            assert result.candidate.state == state
        else:
            row = terminate_exception(work.daily, approved.candidate.candidate_id, state=state,
                reason="End the original permission without replacement", now=chain.now)
            assert row["payload"]["state"] == state
        work.commit()
    with chain.plans._unit_of_work() as work:
        row = ExceptionRepository(work.daily).get(approved.candidate.candidate_id)
        assert row["payload"]["state"] == state
        assert row["payload"]["frozen_quantity"] == _expected(chain)
        assert not work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")


def _corrupt_source_receipt_record(chain):
    trigger = "pma_seal_source_coverage_assessment_update"
    with chain.plans._unit_of_work() as work:
        row = work.daily.session.scalar(select(CoverageAssessmentRow).where(
            CoverageAssessmentRow.plan_version_id == chain.version["id"],
            CoverageAssessmentRow.revision == 1))
        assert row is not None
        work.daily.session.execute(text("DROP TRIGGER " + trigger))
        work.daily.session.execute(update(CoverageAssessmentRow).where(
            CoverageAssessmentRow.plan_version_id == chain.version["id"],
            CoverageAssessmentRow.revision == 1).values(payload_json=row.payload_json + " "))
        work.daily.session.execute(text(COVERAGE_TRIGGER_SQL[trigger]))
        work.commit()


@pytest.mark.parametrize("stage", ["preview", "approve"])
def test_corrupt_source_evidence_keeps_the_sanitized_http_integrity_classification(
    exception_chain, monkeypatch, stage,
):
    chain = exception_chain
    candidate = _candidate(chain)
    shown = _preview(chain, candidate) if stage == "approve" else None
    _corrupt_source_receipt_record(chain)
    before = _ledger(chain)
    monkeypatch.setattr(chain.client._transport, "raise_server_exceptions", False)
    if shown is None:
        body = dict(candidateId=candidate.candidate_id, expectedRevision=1,
            proposedQuantity=None if chain.route == "WEAK_MINIMUM" else 300)
        path = "plan-exception-previews"
    else:
        command = _approval_command(shown)
        body = dict(commandId=command.command_id, candidateId=command.candidate_id,
            expectedRevision=command.expected_revision, decision=command.decision,
            reason=command.reason, previewId=command.preview_id, previewHash=command.preview_hash)
        path = "plan-exception-decisions"
    response = chain.client.post("/api/v1/" + path, json=body,
                                 headers={"Idempotency-Key": "corrupt-exception-" + stage})
    assert response.status_code == 500, response.text
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "source_coverage_assessment" not in response.text
    assert _ledger(chain) == before
