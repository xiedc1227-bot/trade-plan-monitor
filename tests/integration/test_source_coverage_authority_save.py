"""Saving inspectable drafts persists independent current coverage and private inputs.

Only migrated disposable databases and deterministic local fixtures are used.
No provider, user database, confirmation, activation or trade is involved.
"""

from copy import deepcopy
from datetime import datetime
from itertools import count
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from tests.integration.test_source_coverage_migration import _seed_legacy
from tests.unit.test_ai_plan_extraction_v4 import _PROVIDER_ID, _REQUEST_ID
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.ai.extraction import _blocking_warning
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionResult
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, CoverageIssue
from trade_plan_monitor.ai.source_normalization import capture_normalization, validate_normalization
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.state.daily_review_store import record_daily_extraction, save_daily_draft
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.source_coverage_models import CoverageReviewRow
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

_NOW = datetime(2026, 10, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture
def state(tmp_path):
    engine = create_sqlite_engine(tmp_path / "authority-save.sqlite3")
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    identities = count(1)

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: _NOW,
            id_factory=lambda: str(UUID(int=next(identities))))

    try:
        yield SimpleNamespace(engine=engine, sessions=sessions, work=work)
    finally:
        engine.dispose()


def _ai_result(draft, source, mapping, *, with_normalization=True, raw_name=None):
    before = draft.model_dump(mode="json")
    if raw_name is not None:
        before["name"] = raw_name
    trace = (capture_normalization(before, draft.model_dump(mode="json"), source)
             if with_normalization else None)
    assessment = assess_source_coverage(
        draft, mapping, source, normalization=trace, origin="AI_NEW")
    return CurrentPlanExtractionResult(
        request_id=_REQUEST_ID, provider_id=_PROVIDER_ID, model="offline-local-fixture",
        prompt_version="plan-extract-v12", source_text_sha256=scope_hash(source), draft=draft,
        daily_mapping=mapping, assumptions=(), warnings=(), usage=None,
        validation_issues=tuple(_blocking_warning(i.code, i.path, i.message)
                                for i in assessment.issues),
        coverage=assessment, normalization_trace=trace, status=PlanExtractionStatus.SUCCEEDED,
    )


def _save(state, draft, source, mapping, *, extraction=None, recorded=False):
    with state.work() as work:
        if extraction is not None and not recorded:
            record_daily_extraction(work, extraction, clock=lambda: _NOW)
        version_id = save_daily_draft(work, draft, mapping=mapping, source_text=source,
            clock=lambda: _NOW,
            extraction_id=None if extraction is None else str(extraction.request_id))
        work.commit()
    return version_id


def _stored(state, version_id):
    with state.sessions() as session:
        result = SourceCoverageStore(session).latest(version_id)
        assert result is not None
        return result


def _assert_draft_without_receipt(state, version_id, draft, source, mapping):
    expected = build_daily_review(draft, mapping, source)
    with state.work() as work:
        details = work.plans.get_version_details(version_id)
        assert details.status == "DRAFT" and details.review_id is None
        assert details.review_confirmed_at is None
        assert details.daily_mapping == mapping
        assert details.daily_issues == expected.issues
        assert details.review_evidence_hash == expected.evidence_hash
        assert work.daily.session.scalar(select(func.count()).select_from(CoverageReviewRow)) == 0
        assert work.daily.session.execute(text("SELECT COUNT(*) FROM active_plan")).scalar() == 0


def test_saving_a_complete_human_draft_persists_current_coverage_without_a_review_receipt(state):
    draft, source, mapping = _baseline()
    with state.work() as work:
        version_id = save_daily_draft(work, draft, mapping=mapping, source_text=source,
                                     clock=lambda: _NOW)
        work.commit()

    with state.sessions() as session:
        stored = SourceCoverageStore(session).latest(version_id)
        assert stored is not None
        assert stored.assessment.origin == "HUMAN"
        assert stored.assessment.status == "COMPLETE"
        assert stored.assessment.automatic_fidelity_verified is False
        assert stored.authority_granted is False
    _assert_draft_without_receipt(state, version_id, draft, source, mapping)


def test_new_ai_extraction_persists_original_private_normalization_and_current_proof(state):
    draft, source, mapping = _baseline()
    extraction = _ai_result(draft, source, mapping)

    version_id = _save(state, draft, source, mapping, extraction=extraction)

    stored = _stored(state, version_id)
    assert stored.assessment.origin == "AI_NEW"
    assert stored.assessment.coverage_complete is True
    assert stored.assessment.automatic_fidelity_verified is True
    assert stored.inputs.normalization == extraction.normalization_trace
    assert stored.inputs.initial_coverage == extraction.coverage
    with state.sessions() as session:
        original = SourceCoverageStore(session).input(str(extraction.request_id))
        assert original.normalization == extraction.normalization_trace
        assert original.initial_coverage == extraction.coverage
        assert original.authority_granted is False
    _assert_draft_without_receipt(state, version_id, draft, source, mapping)


@pytest.mark.parametrize("has_initial_coverage", [False, True])
def test_new_extraction_identity_without_normalization_remains_new_ai_and_blocked(
    state, has_initial_coverage,
):
    draft, source, mapping = _baseline()
    extraction = _ai_result(draft, source, mapping, with_normalization=False)
    if not has_initial_coverage:
        extraction = extraction.model_copy(update={"coverage": None})

    version_id = _save(state, draft, source, mapping, extraction=extraction)

    stored = _stored(state, version_id)
    assert stored.assessment.origin == "AI_NEW"
    assert stored.assessment.status == "BLOCKED"
    assert stored.assessment.automatic_fidelity_verified is False
    assert any(i.code == "SOURCE_NORMALIZATION_LOSS" for i in stored.assessment.issues)
    assert stored.inputs.normalization is None
    _assert_draft_without_receipt(state, version_id, draft, source, mapping)


def test_retry_compares_private_proof_even_when_old_serialized_extraction_is_identical(state):
    draft, source, mapping = _baseline()
    original = _ai_result(draft, source, mapping)
    altered = _ai_result(draft, source, mapping, raw_name="A different original AI display name")
    assert altered.model_dump(mode="json") == original.model_dump(mode="json")
    assert altered.normalization_trace != original.normalization_trace
    with state.work() as work:
        record_daily_extraction(work, original, clock=lambda: _NOW)
        work.commit()

    with pytest.raises(ValueError):
        with state.work() as work:
            record_daily_extraction(work, altered, clock=lambda: _NOW)
            work.commit()

    with state.sessions() as session:
        inputs = SourceCoverageStore(session).input(str(original.request_id))
        assert inputs.normalization == original.normalization_trace
        assert inputs.initial_coverage == original.coverage


def test_exact_extraction_retry_keeps_one_private_input_without_extra_audit_writes(state):
    draft, source, mapping = _baseline()
    extraction = _ai_result(draft, source, mapping)
    with state.work() as work:
        record_daily_extraction(work, extraction, clock=lambda: _NOW)
        work.commit()
    with state.sessions() as session:
        before = session.execute(text("SELECT COUNT(*) FROM audit_log")).scalar()
        original = SourceCoverageStore(session).input(str(extraction.request_id))
        assert original is not None

    with state.work() as work:
        record_daily_extraction(work, extraction, clock=lambda: _NOW)
        work.commit()

    with state.sessions() as session:
        assert SourceCoverageStore(session).input(str(extraction.request_id)) == original
        assert session.execute(text("SELECT COUNT(*) FROM source_coverage_input")).scalar() == 1
        assert session.execute(text("SELECT COUNT(*) FROM audit_log")).scalar() == before


@pytest.mark.parametrize("origin", ["HUMAN", "AI_NEW"])
def test_mandatory_as_background_stays_a_saved_draft_with_current_blockers_and_old_zero_issues(
    state, origin,
):
    draft, source, mapping = _baseline()
    source, mapping = _append_as_context(source, mapping,
        "仅当换手率超过3%时才允许买入。", semantic_role="COMMENTARY",
        misclassification=dict(disposition="CONTEXT", paths=[], reason="Background commentary"))
    assert build_daily_review(draft, mapping, source).issues == ()
    extraction = _ai_result(draft, source, mapping) if origin == "AI_NEW" else None

    version_id = _save(state, draft, source, mapping, extraction=extraction)

    stored = _stored(state, version_id)
    assert stored.assessment.origin == origin and stored.assessment.status == "BLOCKED"
    assert stored.assessment.automatic_fidelity_verified is False
    assert stored.assessment.issues and stored.assessment.authority_granted is False
    assert any(o.excerpt == "仅当换手率超过3%时才允许买入。"
               and o.state not in {"MAPPED", "CONTEXT_VERIFIED"}
               for o in stored.assessment.obligations)
    _assert_draft_without_receipt(state, version_id, draft, source, mapping)


def test_saving_unchanged_candidate_keeps_the_actual_original_normalization_trace(state):
    draft, source, mapping = _baseline()
    extraction = _ai_result(draft, source, mapping, raw_name="  Original AI display  ")
    assert extraction.normalization_trace.before_hash != extraction.normalization_trace.after_hash

    version_id = _save(state, draft, source, mapping, extraction=extraction)

    stored = _stored(state, version_id)
    assert stored.inputs.normalization == extraction.normalization_trace
    assert stored.assessment.automatic_fidelity_verified is True
    assert validate_normalization(stored.inputs.normalization, draft, source)["name"] == (
        "  Original AI display  "
    )


def test_explicit_human_policy_edit_is_reassessed_without_claiming_original_automatic_fidelity(
    state,
):
    draft, source, mapping = _baseline()
    extraction = _ai_result(draft, source, mapping)
    with state.work() as work:
        record_daily_extraction(work, extraction, clock=lambda: _NOW)
        work.commit()
    edited = deepcopy(draft.model_dump(mode="json"))
    edited["position"]["limit"]["capital_policy"]["cap_fen"] += 10000
    edited = type(draft).model_validate(edited)
    path = "position.limit.capital_policy.cap_fen"
    edited_mapping = mapping.model_copy(update={
        "candidate_content_hash": daily_draft_content_sha256(edited),
        "bindings": tuple(binding for binding in mapping.bindings if binding.path != path),
    })
    # Preserve the unsupported source conflict and missing evidence. The edit is
    # explicit human work, not permission to override a non-null source value.

    version_id = _save(state, edited, source, edited_mapping, extraction=extraction, recorded=True)

    stored = _stored(state, version_id)
    assert stored.assessment.origin == "HUMAN"
    assert stored.assessment.status == "BLOCKED"
    assert stored.assessment.automatic_fidelity_verified is False
    assert stored.assessment.normalization_hash is None
    with state.sessions() as session:
        assert SourceCoverageStore(session).input(str(extraction.request_id)).normalization == (
            extraction.normalization_trace
        )
    _assert_draft_without_receipt(state, version_id, edited, source, edited_mapping)


def test_server_assigned_version_rebuilds_full_trace_from_the_original_provider_preimage(state):
    draft, source, mapping = _baseline()
    extraction = _ai_result(draft, source, mapping, raw_name="  Actual original AI name  ")
    assigned = draft.model_copy(update={"version": draft.version + 1})
    assert daily_draft_content_sha256(assigned) == daily_draft_content_sha256(draft)

    version_id = _save(state, assigned, source, mapping, extraction=extraction)

    stored = _stored(state, version_id)
    assert stored.assessment.origin == "AI_NEW"
    assert stored.assessment.coverage_complete is True
    assert stored.assessment.automatic_fidelity_verified is True
    trace = stored.inputs.normalization
    assert trace.before_hash == extraction.normalization_trace.before_hash
    assert trace.after_hash != extraction.normalization_trace.after_hash
    before = validate_normalization(trace, assigned, source)
    assert before["version"] == draft.version and before["name"] == "  Actual original AI name  "
    assert {change.path for change in trace.changes} >= {"version", "name"}
    with state.sessions() as session:
        assert SourceCoverageStore(session).input(str(extraction.request_id)).normalization == (
            extraction.normalization_trace
        )
    _assert_draft_without_receipt(state, version_id, assigned, source, mapping)


@pytest.mark.parametrize("version_increment", [0, 1], ids=["original_version", "assigned_version"])
def test_valid_candidate_with_mismatched_trace_stays_inspectable_after_version_assignment(
    state, version_increment,
):
    draft, source, mapping = _baseline()
    wrong_image = draft.model_dump(mode="json")
    wrong_image["name"] = "A different candidate after-image"
    trace = capture_normalization(wrong_image, wrong_image, source)
    assert type(trace).model_validate_json(trace.model_dump_json()) == trace
    with pytest.raises(ValueError, match="after-image mismatch"):
        validate_normalization(trace, draft, source)
    blocked = assess_source_coverage(draft, mapping, source, normalization=trace, origin="AI_NEW")
    assert blocked.status == "BLOCKED"
    assert any(issue.code == "SOURCE_NORMALIZATION_LOSS" for issue in blocked.issues)
    extraction = _ai_result(draft, source, mapping).model_copy(update={
        "normalization_trace": trace, "coverage": blocked,
        "validation_issues": tuple(_blocking_warning(issue.code, issue.path, issue.message)
                                   for issue in blocked.issues),
    })
    assigned = draft.model_copy(update={"version": draft.version + version_increment})
    assert draft.to_executable() is not None
    assert build_daily_review(assigned, mapping, source).issues == ()

    version_id = _save(state, assigned, source, mapping, extraction=extraction)

    stored = _stored(state, version_id)
    assert stored.assessment.origin == "AI_NEW" and stored.assessment.status == "BLOCKED"
    assert stored.assessment.automatic_fidelity_verified is False
    assert stored.assessment.normalization_hash is None
    assert any(issue.code == "SOURCE_NORMALIZATION_LOSS" for issue in stored.assessment.issues)
    assert stored.inputs.normalization == trace  # Retain the unproven original, without repair.
    with state.sessions() as session:
        original = SourceCoverageStore(session).input(str(extraction.request_id))
        assert original.normalization == trace
        assert original.initial_coverage == blocked
    _assert_draft_without_receipt(state, version_id, assigned, source, mapping)


def test_read_version_coverage_rederives_exact_proof_without_business_writes(state):
    from trade_plan_monitor.state.source_coverage_authority import read_version_coverage

    draft, source, mapping = _baseline()
    extraction = _ai_result(draft, source, mapping)
    version_id = _save(state, draft, source, mapping, extraction=extraction)
    expected = _stored(state, version_id)

    with state.work() as work:
        details = work.plans.get_version_details(version_id)
        connection = work.daily.session.connection()
        before = connection.exec_driver_sql("SELECT total_changes()").scalar()

        result = read_version_coverage(work, details)

        assert result == expected
        assert connection.exec_driver_sql("SELECT total_changes()").scalar() == before
        assert SourceCoverageStore(work.daily.session).latest(version_id) == expected
    _assert_draft_without_receipt(state, version_id, draft, source, mapping)


def test_read_of_a_version_without_current_proof_never_invents_or_persists_one(state):
    from trade_plan_monitor.state.source_coverage_authority import read_version_coverage

    # This is an old-verifier-consistent fixture inserted directly, bypassing
    # new save orchestration. Absence must remain explicit rather than repaired.
    legacy = _seed_legacy(state.engine)
    with state.work() as work:
        details = work.plans.get_version_details(legacy.id)
        connection = work.daily.session.connection()
        before = connection.exec_driver_sql("SELECT total_changes()").scalar()

        result = read_version_coverage(work, details)

        assert result is None
        assert connection.exec_driver_sql("SELECT total_changes()").scalar() == before
        assert SourceCoverageStore(work.daily.session).latest(legacy.id) is None
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM source_coverage_assessment").scalar() == 0


def test_read_detects_a_changed_valid_reassessment_as_stale_without_replacing_saved_proof(
    state, monkeypatch,
):
    import trade_plan_monitor.state.source_coverage_authority as authority

    draft, source, mapping = _baseline()
    version_id = _save(state, draft, source, mapping)
    stored = _stored(state, version_id)
    values = stored.assessment.model_dump(mode="python", exclude={"status", "evidence_hash"})
    values["obligations"] = stored.assessment.obligations
    values["issues"] = (CoverageIssue(code="SOURCE_COVERAGE_REQUIRED",
                                     message="The current registered assessment is unresolved."),)
    reassessed = CoverageAssessment.build(**values)
    assert reassessed.evidence_hash != stored.assessment.evidence_hash
    monkeypatch.setattr(authority, "assess_source_coverage", lambda *args, **kwargs: reassessed)

    with state.work() as work:
        details = work.plans.get_version_details(version_id)
        connection = work.daily.session.connection()
        before = connection.exec_driver_sql("SELECT total_changes()").scalar()

        with pytest.raises(authority.SourceCoverageAuthorityError, match="SOURCE_COVERAGE_STALE"):
            authority.read_version_coverage(work, details)

        assert connection.exec_driver_sql("SELECT total_changes()").scalar() == before
        assert SourceCoverageStore(work.daily.session).latest(version_id) == stored
