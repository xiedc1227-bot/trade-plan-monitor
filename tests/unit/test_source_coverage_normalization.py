"""Normalization evidence must prove its complete original image and changes."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.ai.daily_review import DailyClause
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_models import NormalizationChange, NormalizationTrace
from trade_plan_monitor.ai.source_resolution import normalize_source_draft
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.domain.p3_validation import P3PlanDraft


def _capture(before, after, source):
    from trade_plan_monitor.ai.source_normalization import capture_normalization

    return capture_normalization(before, after, source)


def _validate(trace, draft, source):
    from trade_plan_monitor.ai.source_normalization import validate_normalization

    return validate_normalization(trace, draft, source)


def _baseline():
    draft = P3PlanDraft.model_validate(p3_payload())
    source, mapping = source_mapping(draft)
    return draft, source, mapping


def _signed_mutation(trace, **changes):
    values = trace.model_dump(mode="python", exclude={"evidence_hash"})
    return NormalizationTrace.build(**(values | changes))


def _normalization_loss(assessment):
    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.automatic_fidelity_verified is False
    assert assessment.authority_granted is False
    assert "SOURCE_NORMALIZATION_LOSS" in {issue.code for issue in assessment.issues}


def _display_change():
    draft, source, mapping = _baseline()
    after = draft.model_dump(mode="json")
    before = deepcopy(after)
    before["name"] = "Original AI display name"
    assert before["name"] != after["name"]
    return draft, source, mapping, before, after


def test_new_ai_candidate_without_normalization_preimage_is_not_automatically_verified():
    draft, source, mapping = _baseline()

    assessment = assess_source_coverage(draft, mapping, source, origin="AI_NEW")

    _normalization_loss(assessment)


def test_identity_normalization_proves_full_raw_hashes_without_modifying_inputs():
    draft, source, mapping = _baseline()
    before = draft.model_dump(mode="json")
    after = deepcopy(before)
    snapshot_before, snapshot_after = canonical(before), canonical(after)

    trace = _capture(before, after, source)

    assert trace.source_hash == scope_hash(source)
    assert trace.before_hash == daily_hash("source-normalization-candidate-v1", before)
    assert trace.after_hash == daily_hash("source-normalization-candidate-v1", after)
    assert trace.changes == ()
    assert _validate(trace, draft, source) == before
    assert canonical(before) == snapshot_before and canonical(after) == snapshot_after
    assessment = assess_source_coverage(
        draft, mapping, source, normalization=trace, origin="AI_NEW",
    )
    assert assessment.coverage_complete is True
    assert assessment.automatic_fidelity_verified is True
    assert assessment.authority_granted is False


def test_complete_harmless_display_change_can_reconstruct_the_original_candidate():
    draft, source, mapping, before, after = _display_change()
    trace = _capture(before, after, source)

    assert trace.before_hash != trace.after_hash
    assert [change.path for change in trace.changes] == ["name"]
    assert _validate(trace, draft, source) == before
    assert trace.changes[0].before_json == canonical({"present": True, "value": before["name"]})
    assert trace.changes[0].after_json == canonical({"present": True, "value": after["name"]})
    assessment = assess_source_coverage(
        draft, mapping, source, normalization=trace, origin="AI_NEW",
    )
    assert assessment.coverage_complete is True
    assert assessment.automatic_fidelity_verified is True


def test_reconstruction_distinguishes_a_missing_key_from_an_explicit_null():
    draft, _, _ = _baseline()
    after = draft.model_dump(mode="json")
    after["metadata"]["report_at"] = None
    draft = P3PlanDraft.model_validate(after)
    source, _ = source_mapping(draft)
    before = deepcopy(after)
    before["metadata"].pop("report_at")

    trace = _capture(before, after, source)

    change = next(change for change in trace.changes if change.path == "metadata.report_at")
    assert change.before_json == canonical({"present": False})
    assert change.after_json == canonical({"present": True, "value": None})
    reconstructed = _validate(trace, draft, source)
    assert reconstructed == before
    assert "report_at" not in reconstructed["metadata"]


@pytest.mark.parametrize("field", ["source_hash", "before_hash", "after_hash"])
def test_a_self_consistent_trace_cannot_lie_about_source_or_candidate_images(field):
    draft, source, mapping, before, after = _display_change()
    trace = _capture(before, after, source)
    forged = _signed_mutation(trace, **{field: "f" * 64})
    assert NormalizationTrace.model_validate_json(forged.model_dump_json()) == forged

    with pytest.raises(ValueError):
        _validate(forged, draft, source)
    assessment = assess_source_coverage(
        draft, mapping, source, normalization=forged, origin="AI_NEW",
    )
    _normalization_loss(assessment)


@pytest.mark.parametrize("mutation", ["omitted", "duplicated", "overlapping", "unknown_path"])
def test_a_rehashed_trace_cannot_omit_duplicate_overlap_or_invent_changes(mutation):
    draft, source, mapping, before, after = _display_change()
    if mutation == "overlapping":
        before["metadata"]["reference_price_fen"] = (
            (after["metadata"]["reference_price_fen"] or 0) + 1
        )
    trace = _capture(before, after, source)
    if mutation == "omitted":
        changes = ()
    elif mutation == "duplicated":
        changes = (*trace.changes, trace.changes[0])
    elif mutation == "overlapping":
        changes = (*trace.changes, NormalizationChange(
            path="metadata",
            before_json=canonical({"present": True, "value": before["metadata"]}),
            after_json=canonical({"present": True, "value": after["metadata"]}),
            reason="SOURCE_NORMALIZATION",
        ))
    else:
        changes = (*trace.changes, NormalizationChange(
            path="ordinary_rules[999].condition",
            before_json=canonical({"present": True, "value": {"type": "ALL"}}),
            after_json=canonical({"present": True, "value": []}),
            reason="SOURCE_NORMALIZATION",
        ))
    forged = _signed_mutation(trace, changes=changes)
    assert NormalizationTrace.model_validate_json(forged.model_dump_json()) == forged

    with pytest.raises(ValueError):
        _validate(forged, draft, source)
    assessment = assess_source_coverage(
        draft, mapping, source, normalization=forged, origin="AI_NEW",
    )
    _normalization_loss(assessment)


def test_invalid_original_candidate_cannot_be_laundered_into_automatic_fidelity():
    draft, source, mapping = _baseline()
    after = draft.model_dump(mode="json")
    before = deepcopy(after)
    before["schema_version"] = 999
    trace = _capture(before, after, source)

    assessment = assess_source_coverage(
        draft, mapping, source, normalization=trace, origin="AI_NEW",
    )

    _normalization_loss(assessment)


def test_actual_evaluation_only_normalization_cannot_delete_source_buy_obligations():
    original, source, original_mapping = _baseline()
    source += "\n再重新设置低吸区并评估第一笔。"
    before = original.model_dump(mode="json")
    after = normalize_source_draft(
        deepcopy(before), SimpleNamespace(text=source, effective_trade_date=None),
    )
    assert before["ordinary_rules"] and after["ordinary_rules"] == []
    draft = P3PlanDraft.model_validate(after)
    canonical_clauses = server_source_clauses(source)
    value = canonical_clauses[-1].model_dump()
    value.update(disposition="CONTEXT", paths=(), semantic_role="COMMENTARY",
                 reason="This sentence proposes evaluating a future entry.")
    mapping = original_mapping.model_copy(update={
        "candidate_content_hash": daily_draft_content_sha256(draft),
        "clauses": (*original_mapping.clauses, DailyClause.model_validate(value)),
    })
    assert [(c.clause_id, c.start, c.end, c.excerpt) for c in mapping.clauses] == [
        (c.clause_id, c.start, c.end, c.excerpt) for c in canonical_clauses
    ]
    # Keep the actual original provider bindings; do not fabricate a new preimage map.
    assert mapping.bindings == original_mapping.bindings
    trace = _capture(before, draft.model_dump(mode="json"), source)
    assert any(change.path == "ordinary_rules" for change in trace.changes)
    assert not any(change.path.startswith("ordinary_rules[") for change in trace.changes)
    assert _validate(trace, draft, source) == before

    assessment = assess_source_coverage(
        draft, mapping, source, normalization=trace, origin="AI_NEW",
    )

    _normalization_loss(assessment)


@pytest.mark.parametrize("origin", ["HUMAN", "AI_HISTORICAL"])
@pytest.mark.parametrize("with_trace", [False, True])
def test_non_new_ai_origins_cannot_retroactively_claim_raw_automatic_fidelity(origin, with_trace):
    draft, source, mapping = _baseline()
    payload = draft.model_dump(mode="json")
    trace = _capture(payload, payload, source) if with_trace else None

    assessment = assess_source_coverage(
        draft, mapping, source, normalization=trace, origin=origin,
    )

    assert assessment.coverage_complete is True
    assert assessment.automatic_fidelity_verified is False
    assert assessment.authority_granted is False
