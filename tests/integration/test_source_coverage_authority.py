"""Current review and repository activation require exact server coverage.

All writes use the migrated disposable database supplied by the state fixture.
No application, provider, user database or real plan is accessed.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from tests.integration.test_source_coverage_authority_save import _NOW
from tests.integration.test_source_coverage_authority_save import state as state
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.state import source_coverage_authority
from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_models import CoverageReviewRow
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore

_OMIT = object()
_CONFIRMED_AT = _NOW + timedelta(minutes=1)


def _save(state, *, blocked=False):
    draft, source, mapping = _baseline()
    if blocked:
        source, mapping = _append_as_context(source, mapping,
            "Only buy when turnover exceeds 3 percent.", semantic_role="COMMENTARY",
            misclassification=dict(disposition="CONTEXT", paths=[], reason="Background"))
    assert build_daily_review(draft, mapping, source).issues == ()
    with state.work() as work:
        identity = save_daily_draft(work, draft, mapping=mapping, source_text=source,
                                    clock=lambda: _NOW)
        work.commit()
    return identity, draft


def _without_coverage(state, monkeypatch):
    # Simulate a trusted save path not yet wired to the new sidecar. No stored
    # seal or evidence is deleted, and the real guard is restored before use.
    with monkeypatch.context() as patch:
        patch.setattr(source_coverage_authority, "save_version_coverage", lambda *a, **kw: None)
        identity, draft = _save(state)
    return identity, draft


def _command(work, identity, **overrides):
    details = work.plans.get_version_details(identity)
    stored = SourceCoverageStore(work.daily.session).latest(identity)
    values = dict(plan_version_id=identity, content_hash=details.content_hash,
        source_hash=details.source_hash, review_evidence_hash=details.review_evidence_hash,
        expected_revision=details.review_revision, resolutions=(),
        coverage_evidence_hash="a" * 64 if stored is None else stored.assessment.evidence_hash,
        coverage_rules_version="source-coverage-rules-v1")
    values.update(overrides)
    return SimpleNamespace(**{key: value for key, value in values.items() if value is not _OMIT})


def _confirm(state, identity):
    with state.work() as work:
        result = confirm_daily_review(work, _command(work, identity), clock=lambda: _CONFIRMED_AT)
        work.commit()
    return result


def _assert_unconfirmed(state, identity):
    with state.work() as work:
        details = work.plans.get_version_details(identity)
        assert details.status == "DRAFT"
        assert details.review_id is None and details.review_confirmed_at is None
        assert details.review_revision == 0
        assert work.plans.get_active(details.symbol) is None
        assert work.daily.session.scalar(select(func.count()).select_from(CoverageReviewRow)) == 0


@pytest.mark.parametrize("field,value", [
    ("coverage_evidence_hash", _OMIT), ("coverage_evidence_hash", None),
    ("coverage_rules_version", _OMIT), ("coverage_rules_version", None),
])
def test_confirmation_without_explicit_current_coverage_binding_is_required(state, field, value):
    identity, _ = _save(state)

    with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_REQUIRED$"):
        with state.work() as work:
            command = _command(work, identity, **{field: value})
            confirm_daily_review(work, command, clock=lambda: _CONFIRMED_AT)
            work.commit()

    _assert_unconfirmed(state, identity)


@pytest.mark.parametrize("overrides", [
    dict(coverage_evidence_hash="0" * 64),
    dict(coverage_rules_version="source-coverage-rules-v0"),
])
def test_confirmation_with_changed_coverage_hash_or_rules_is_stale(state, overrides):
    identity, _ = _save(state)

    with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_STALE$"):
        with state.work() as work:
            confirm_daily_review(work, _command(work, identity, **overrides),
                                 clock=lambda: _CONFIRMED_AT)
            work.commit()

    _assert_unconfirmed(state, identity)


def test_old_zero_issue_review_cannot_confirm_blocked_current_source(state):
    identity, _ = _save(state, blocked=True)
    with state.work() as work:
        assert not work.plans.get_version_details(identity).daily_issues
        stored = SourceCoverageStore(work.daily.session).latest(identity)
        assert stored.assessment.status == "BLOCKED"

    with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_REQUIRED$"):
        _confirm(state, identity)

    _assert_unconfirmed(state, identity)


def test_absent_current_proof_cannot_confirm_an_otherwise_complete_draft(state, monkeypatch):
    identity, _ = _without_coverage(state, monkeypatch)

    with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_REQUIRED$"):
        _confirm(state, identity)

    _assert_unconfirmed(state, identity)


def test_first_confirmation_binds_exact_bundle_and_original_review_atomically(state):
    identity, _ = _save(state)
    with state.work() as work:
        before = work.plans.get_version_details(identity)
        stored = source_coverage_authority.require_current_coverage(work, before)
        with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_REQUIRED$"):
            source_coverage_authority.require_current_coverage(work, before, require_review=True)

    confirmed = _confirm(state, identity)

    with state.work() as work:
        details = work.plans.get_version_details(identity)
        receipt = SourceCoverageStore(work.daily.session).receipt(details.review_id)
        assert receipt is not None
        assert details.review_revision == 1
        assert details.review_confirmed_at == _CONFIRMED_AT
        assert receipt.plan_version_id == identity
        assert (receipt.review_id, receipt.review_revision, receipt.confirmed_at) == (
            details.review_id, details.review_revision, details.review_confirmed_at)
        assert receipt.original_review_evidence_hash == before.review_evidence_hash
        assert receipt.coverage_revision == stored.revision
        assert receipt.coverage_bundle_hash == stored.evidence_hash
        assert receipt.coverage_evidence_hash == stored.assessment.evidence_hash
        assert receipt.coverage_rules_version == stored.assessment.rules_version
        assert (receipt.source_hash, receipt.content_hash, receipt.mapping_hash) == (
            stored.assessment.source_hash, stored.assessment.content_hash,
            stored.assessment.mapping_hash)
        assert receipt.authority_granted is False
        assert source_coverage_authority.require_current_coverage(
            work, details, require_review=True) == stored
        assert source_coverage_authority.require_repository_review(work.plans, identity) == stored
        assert confirmed.review_id == details.review_id


def test_confirmed_version_cannot_overwrite_original_review_identity_or_time(state):
    identity, _ = _save(state)
    original = _confirm(state, identity)
    with state.work() as work:
        receipt = SourceCoverageStore(work.daily.session).receipt(original.review_id)

    with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_STALE$"):
        with state.work() as work:
            command = _command(work, identity, expected_revision=1)
            confirm_daily_review(work, command, clock=lambda: _CONFIRMED_AT + timedelta(days=1))
            work.commit()

    with state.work() as work:
        details = work.plans.get_version_details(identity)
        assert (details.review_id, details.review_revision, details.review_confirmed_at) == (
            original.review_id, original.review_revision, original.review_confirmed_at)
        assert SourceCoverageStore(work.daily.session).receipt(original.review_id) == receipt
        assert work.daily.session.scalar(select(func.count()).select_from(CoverageReviewRow)) == 1


def test_same_assessment_in_new_bundle_revision_invalidates_the_old_review_receipt(state):
    identity, draft = _save(state)
    _confirm(state, identity)
    with state.work() as work:
        store = SourceCoverageStore(work.daily.session)
        before = store.latest(identity)
        after = store.append(identity, before.assessment, inputs=before.inputs,
            expected_revision=before.revision, command_id="independent-reassessment",
            now=_CONFIRMED_AT + timedelta(minutes=1))
        assert after.assessment.evidence_hash == before.assessment.evidence_hash
        assert after.evidence_hash != before.evidence_hash
        work.commit()

    with state.work() as work:
        details = work.plans.get_version_details(identity)
        assert source_coverage_authority.require_current_coverage(work, details) == after
        with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_STALE$"):
            source_coverage_authority.require_current_coverage(work, details, require_review=True)
        with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_STALE$"):
            source_coverage_authority.require_repository_review(work.plans, identity)
        with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_STALE$"):
            work.plans.activate(draft.to_executable(), expected_revision=0,
                                validation=PlanValidationResult(issues=()))
        assert work.plans.get_active(details.symbol) is None


def test_receipt_write_failure_rolls_back_original_review_and_daily_binding(state, monkeypatch):
    identity, _ = _save(state)

    def reject_receipt(self, receipt):
        raise RuntimeError("synthetic receipt write failure")

    monkeypatch.setattr(SourceCoverageStore, "save_receipt", reject_receipt)

    with pytest.raises(RuntimeError, match="^synthetic receipt write failure$"):
        _confirm(state, identity)

    _assert_unconfirmed(state, identity)
    with state.work() as work:
        binding = work.daily.get("review-" + identity)
        assert binding["revision"] == 1
        assert binding["payload"]["confirmed"] is False
        assert binding["payload"]["review_id"] is None
        assert binding["payload"]["review_revision"] == 0


@pytest.mark.parametrize("proof", ["absent", "blocked", "unconfirmed"])
def test_repository_direct_activation_cannot_bypass_current_proof_and_receipt(
    state, monkeypatch, proof,
):
    identity, draft = (_without_coverage(state, monkeypatch) if proof == "absent"
                       else _save(state, blocked=proof == "blocked"))

    with pytest.raises(SourceCoverageAuthorityError, match="^SOURCE_COVERAGE_REQUIRED$"):
        with state.work() as work:
            work.plans.activate(draft.to_executable(), expected_revision=0,
                                validation=PlanValidationResult(issues=()))
            work.commit()

    _assert_unconfirmed(state, identity)


def test_repository_activation_accepts_only_the_exact_current_reviewed_bundle(state):
    identity, draft = _save(state)
    _confirm(state, identity)

    with state.work() as work:
        active = work.plans.activate(draft.to_executable(), expected_revision=0,
                                     validation=PlanValidationResult(issues=()))
        assert active.plan_version_id == identity and active.revision == 1
        work.commit()
