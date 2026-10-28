"""Actual SQL changes cannot be hidden by held ORM owners in a live action reader."""

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import delete, select, update
from tests.integration.test_daily_simulation import command as ordinary_command
from tests.integration.test_source_action_cutover import _current_version, _install_severe, _resolve
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_authority_save import _NOW
from tests.integration.test_source_coverage_authority_save import state as state

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_json,
    daily_draft_sha256,
    load_daily_draft_json,
)
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import (
    ActivePlan,
    PlanActivationState,
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    PlanVersionReview,
)
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.simulation import SimulationCommand
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_models import CoverageAssessmentRow
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

_AT = _NOW + timedelta(minutes=3)


def _hold(work, identity, symbol):
    session = work.daily.session
    version = session.get(PlanVersion, identity)
    return dict(version=version, source=session.get(PlanSource, version.source_id),
        version_review=session.get(PlanVersionReview, identity),
        provenance=session.get(PlanReviewProvenance, identity),
        active=session.get(ActivePlan, symbol), state=session.get(PlanActivationState, symbol),
        review=session.get(DailyRecord, "review-" + identity))


def _actual_update(work, held, mutation):
    session = work.daily.session
    identity = held["version"].id

    def execute(statement):
        session.execute(statement.execution_options(synchronize_session=False))

    if mutation == "policy":
        old_json, old_hash = held["version"].payload_json, held["version"].plan_hash
        old = load_daily_draft_json(old_json)
        raw = old.model_dump(mode="json")
        raw["position"]["max_qty"] += 100
        changed = type(old).model_validate(raw)
        assert changed.to_executable() is not None
        execute(update(PlanVersion).where(PlanVersion.id == identity).values(
            payload_json=daily_draft_json(changed), plan_hash=daily_draft_sha256(changed)))
        actual = session.execute(select(PlanVersion.payload_json, PlanVersion.plan_hash).where(
            PlanVersion.id == identity)).one()
        assert actual != (old_json, old_hash)
        assert daily_draft_sha256(load_daily_draft_json(actual.payload_json)) == actual.plan_hash
        assert held["version"].payload_json == old_json and held["version"].plan_hash == old_hash
    elif mutation == "activation":
        revision = held["active"].revision
        execute(update(ActivePlan).where(ActivePlan.symbol == held["active"].symbol).values(
            revision=revision + 1))
        execute(update(PlanActivationState).where(
            PlanActivationState.symbol == held["state"].symbol).values(revision=revision + 1))
        assert session.scalar(select(ActivePlan.revision)) == revision + 1
        assert held["active"].revision == held["state"].revision == revision
    else:
        assert mutation == "review"
        original = json.loads(held["review"].payload_json)
        changed = original | dict(confirmed=False, review_id=None, review_revision=0)
        execute(update(DailyRecord).where(DailyRecord.id == held["review"].id).values(
            payload_json=canonical(changed)))
        execute(update(PlanReviewProvenance).where(
            PlanReviewProvenance.plan_version_id == identity).values(
                confirmed_at=None, review_id=None, review_revision=0))
        actual = session.scalar(select(DailyRecord.payload_json).where(
            DailyRecord.id == held["review"].id))
        assert json.loads(actual)["confirmed"] is False
        assert json.loads(held["review"].payload_json)["confirmed"] is True
        assert held["provenance"].confirmed_at is not None


def _ordinary_command(chain, signal):
    raw = ordinary_command(chain, signal)
    return SimulationCommand(plan_version_id=UUID(raw["planVersionId"]), cause_id=raw["causeId"],
        expected_cause_revision=raw["expectedCauseRevision"],
        expected_inventory_revision=raw["expectedInventoryRevision"], quantity=raw["quantity"])


@pytest.mark.parametrize("basis", ["current", "cutover"])
@pytest.mark.parametrize("mutation", ["policy", "activation", "review"])
def test_source_helper_reads_actual_sql_instead_of_held_orm_owner(basis, mutation, state, legacy):
    if basis == "cutover":
        case = legacy()
    else:
        identity, cause = _current_version(state, "RISK")
        case = SimpleNamespace(id=identity, cause_id=cause,
            work=lambda: SqlAlchemyUnitOfWork(state.sessions, clock=lambda: _AT))
    with case.work() as work:
        original = _resolve(work, case.id, case.cause_id)
        held = _hold(work, case.id, work.plans.get_version_details(case.id).symbol)
        assert all(value is not None for value in held.values())
        _actual_update(work, held, mutation)
        if basis == "current" and mutation == "activation":
            # A coherent current activation has no supplied expected binding here.
            # Its actual new revision must be returned, rather than the cached one.
            fresh = _resolve(work, case.id, case.cause_id)
            assert fresh.activation_revision == original.activation_revision + 1
        else:
            with pytest.raises(SourceCoverageAuthorityError):
                _resolve(work, case.id, case.cause_id)
        assert original.basis in {"CURRENT", "HISTORICAL_TECHNICAL_RISK"}


@pytest.mark.parametrize("owner", ["risk", "fact", "historical-plan"])
def test_actual_latched_risk_and_historical_fact_owners_are_read_again(legacy, owner):
    case = legacy(historical_fact_owner=True)
    risk_id, risk = _install_severe(case)
    with case.work() as work:
        assert _resolve(work, case.id, risk_id).basis == "HISTORICAL_TECHNICAL_RISK"
        session = work.daily.session
        if owner == "historical-plan":
            held = session.get(PlanVersion, case.fact_owner_id)
            _actual_update(work, {"version": held}, "policy")
        else:
            identity = risk_id if owner == "risk" else risk["evidence_ids"][0]
            held = session.get(DailyRecord, identity)
            before = held.payload_json
            changed = json.loads(before) | (
                dict(status="FULFILLED") if owner == "risk" else dict(verified=False))
            session.execute(update(DailyRecord).where(DailyRecord.id == identity).values(
                payload_json=canonical(changed)).execution_options(synchronize_session=False))
            assert held.payload_json == before
            assert session.scalar(select(DailyRecord.payload_json).where(
                DailyRecord.id == identity)) == canonical(changed)
        with pytest.raises(SourceCoverageAuthorityError):
            _resolve(work, case.id, risk_id)


@pytest.mark.parametrize("owner", ["plan", "risk", "fact", "risk-delete", "risk-new"])
def test_pending_actual_owners_are_rejected_without_flush_or_discard(legacy, owner):
    case = legacy(historical_fact_owner=True)
    risk_id, risk = _install_severe(case)
    with case.work() as work:
        session = work.daily.session
        assert _resolve(work, case.id, risk_id).basis == "HISTORICAL_TECHNICAL_RISK"
        if owner == "plan":
            held = session.get(PlanVersion, case.id)
            before = held.payload_json
            held.payload_json = before + " "
        else:
            identity = risk["evidence_ids"][0] if owner == "fact" else risk_id
            held = session.get(DailyRecord, identity)
            before = held.payload_json
            if owner == "risk-delete":
                session.delete(held)
            elif owner == "risk-new":
                held = DailyRecord(id=identity, kind="RISK", symbol=case.draft.symbol,
                    lineage=case.draft.symbol, revision=1, payload_json=before,
                    created_at=_AT.isoformat(), updated_at=_AT.isoformat())
                session.add(held)
            else:
                held.payload_json = before + " "
        driver = session.connection().connection.driver_connection
        before_changes = driver.total_changes
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _resolve(work, case.id, risk_id)
        assert driver.total_changes == before_changes
        assert held in (session.new if owner == "risk-new" else
                        session.deleted if owner == "risk-delete" else session.dirty)
        if owner not in {"risk-new", "risk-delete"}:
            assert held.payload_json == before + " "
        table = PlanVersion.__table__ if owner == "plan" else DailyRecord.__table__
        identity = case.id if owner == "plan" else held.id
        assert session.scalar(select(table.c.payload_json).where(table.c.id == identity)) == before


@pytest.mark.parametrize("pending", ["dirty", "new", "deleted"])
def test_pending_current_coverage_cannot_be_flushed_or_ignored(state, pending):
    identity, cause = _current_version(state, "RISK")
    with SqlAlchemyUnitOfWork(state.sessions, clock=lambda: _AT) as work:
        session = work.daily.session
        assert _resolve(work, identity, cause).basis == "CURRENT"
        held = session.get(CoverageAssessmentRow, (identity, 1))
        before = held.payload_json
        if pending == "dirty":
            held.payload_json += " "
        elif pending == "deleted":
            session.delete(held)
        else:
            held = CoverageAssessmentRow(plan_version_id=identity, revision=2,
                command_id="pending-assessment", request_hash=held.request_hash,
                payload_json=before, evidence_hash=held.evidence_hash, created_at=held.created_at)
            session.add(held)
        driver = session.connection().connection.driver_connection
        before_changes = driver.total_changes
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _resolve(work, identity, cause)
        assert driver.total_changes == before_changes
        assert held in (session.new if pending == "new" else
                        session.deleted if pending == "deleted" else session.dirty)


def test_reading_authority_does_not_flush_unrelated_pending_data(legacy):
    case = legacy()
    with case.work() as work:
        session = work.daily.session
        pending = DailyRecord(id="unrelated-pending", kind="DRAFT", symbol="000001.SZ",
            lineage="000001.SZ", revision=0, payload_json="{}", created_at=_AT.isoformat(),
            updated_at=_AT.isoformat())
        session.add(pending)
        driver = session.connection().connection.driver_connection
        before_changes = driver.total_changes
        assert _resolve(work, case.id, case.cause_id).basis == "HISTORICAL_TECHNICAL_RISK"
        assert driver.total_changes == before_changes
        assert pending in session.new
        assert session.scalar(select(DailyRecord.__table__.c.id).where(
            DailyRecord.__table__.c.id == pending.id)) is None


@pytest.mark.parametrize("model", [PlanVersionReview, PlanReviewProvenance])
def test_missing_persisted_related_owner_keeps_native_integrity_classification(legacy, model):
    case = legacy()
    with case.work() as work:
        held = _hold(work, case.id, case.draft.symbol)
        work.daily.session.execute(delete(model).where(model.plan_version_id == case.id)
            .execution_options(synchronize_session=False))
        assert held["version_review"] is not None and held["provenance"] is not None
        with pytest.raises(RepositoryError, match="Stored plan version details are invalid"):
            work.plans.get_version_details(case.id)
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _resolve(work, case.id, case.cause_id)
