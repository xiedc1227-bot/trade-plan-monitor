"""Exact AI characterization and transport-independent complete change analysis."""

from dataclasses import fields, is_dataclass
from datetime import timedelta
from hashlib import sha256

import pytest
from tests.unit.test_source_change_assurance import _assess, _case
from tests.unit.test_source_control_changes import _case as _control_case

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyFieldBinding,
    DailyMapping,
    DailySupplement,
)
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_change_core import analyze_source_changes
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.update_review import build_update_review

_BASELINES = {
    "cap": (4736, "1db9cf4fdc24bebe87b4516d296cfd6335de75d6eff2d1b94810c81a56dc2822",
            "2189ae8d1dd37c1f919c7a742e507bb3fe797ae59861ea05cd7cf298d722d37c", "COMPLETE"),
    "unknown": (5389, "4faae46c793bf5a2d46e1abe56bce134aee29f13aeac2463e02319452607f0fd",
                "f4084ab685f16e54ebdfab1966b9d4d55fd8da3fc9f95dde5c889e4576dc6618", "BLOCKED"),
    "revoke": (6751, "fb0afeb5799ed0b5e0aa5c58c3eba60a2ab49864e9dce3dd8d22c31c2df47ddc",
               "509ac70d8e4f558d003ee856ddf51544abe2eeb2e3d397cc02f47d00d2a6dd43", "COMPLETE"),
    "ordered_issues": (6400, "70894d1967d211e02fa3da23bc5488b5bc20783b34cdbcd443fe3e680bb4d5c4",
                       "1322cf90b81b745974b61e9f4f06e3be39da3647232a31e1f9cf87fa301ed021",
                       "BLOCKED"),
}


def _fixture(kind):
    if kind == "cap":
        return _case()
    if kind == "unknown":
        return _case(extra="Only buy when turnover exceeds 3 percent.")
    if kind == "revoke":
        return _control_case("取消原来的买入规则。")
    if kind == "ordered_issues":
        case = list(_control_case(
            "取消原来的买入规则。Only buy when turnover exceeds 3 percent.", action="RETAIN"))
        case[3] = None
        case[7] = case[7].model_copy(update={"inputs_hash": None})
        return tuple(case)
    raise AssertionError("unknown characterization fixture")


def _ai(case):
    source, output, materialized, inputs, context, base, parent, binding = case
    return _assess(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding)


@pytest.mark.parametrize("kind", _BASELINES)
def test_existing_ai_full_json_bytes_and_evidence_hash_are_exactly_preserved(kind):
    """Frozen before moving production logic; hashes cover every serialized field."""
    result = _ai(_fixture(kind))
    wire = result.model_dump_json().encode()
    length, wire_hash, evidence_hash, status = _BASELINES[kind]

    assert len(wire) == length
    assert sha256(wire).hexdigest() == wire_hash
    assert result.evidence_hash == evidence_hash and result.status == status
    if kind == "ordered_issues":
        assert [issue.code for issue in result.issues] == [
            "SOURCE_CONTEXT_UNVERIFIED", "SOURCE_NORMALIZATION_LOSS", "SOURCE_RELATION_MISMATCH",
        ]


def _core(case, **overrides):
    source, output, materialized, _, context, base, parent, _ = case
    values = dict(source=source, output=output, reviewed=materialized.review,
        complete_mapping=output.review(source.text).mapping, context=context,
        base_review=base, verified_parent=parent)
    return analyze_source_changes(**(values | overrides))


@pytest.mark.parametrize("kind", _BASELINES)
def test_shared_core_retains_every_semantic_operation_and_issue_in_its_original_position(kind):
    case = _fixture(kind)
    original = tuple(value.model_dump_json() for value in case if value is not None)
    ai = _ai(case)

    core = _core(case)

    assert core.obligations == ai.obligations and core.operations == ai.operations
    assert core.changed_paths == ai.changed_paths
    assert core.draft == case[2].review.draft
    for field in ("source_hash", "source_binding_hash", "content_hash", "mapping_hash",
                  "review_evidence_hash", "base_hash", "parent_assurance_hash", "parent_verified"):
        assert getattr(core, field) == getattr(ai, field)
    if kind == "ordered_issues":
        assert core.head_issues == ai.issues[:1] and core.tail_issues == ai.issues[2:]
    else:
        assert (*core.head_issues, *core.tail_issues) == ai.issues
    assert tuple(value.model_dump_json() for value in case if value is not None) == original


def test_shared_core_is_only_analysis_and_has_no_provider_or_authority_claim():
    core = _core(_fixture("cap"))
    assert is_dataclass(core)
    names = {field.name for field in fields(core)}
    assert names.isdisjoint({"status", "coverage_complete", "coverageComplete", "authority_granted",
                           "raw_delta_verified", "provider_full_draft_supplied", "inputs_hash",
                           "derivation_hash", "binding"})
    assert not hasattr(core, "coverage_complete")
    assert not hasattr(core, "automatic_fidelity_verified")


@pytest.mark.parametrize("problem", ["mapping", "source_header", "context", "review_header"])
def test_shared_core_rejects_wrong_complete_mapping_source_review_or_parent_context(problem):
    case = _fixture("cap")
    source, output, materialized, _, context, _, _, _ = case
    if problem == "mapping":
        changed = dict(complete_mapping=output.review(source.text).mapping.model_copy(update={
            "candidate_content_hash": "f" * 64}))
    elif problem == "source_header":
        changed = dict(source=source.model_copy(update={
            "authored_at": source.available_at - timedelta(hours=1)}))
    elif problem == "context":
        changed = dict(context=context.model_copy(update={"base_hash": "f" * 64}))
    else:
        changed = dict(reviewed=materialized.review.model_copy(update={
            "source_id": "wrong-source"}))

    with pytest.raises(ValueError):
        _core(case, **changed)


def test_complete_verifier_issues_are_not_filtered_to_manufacture_partial_coverage():
    case = _fixture("cap")
    source, output, _, _, _, base, _, _ = case
    mapping = output.review(source.text).mapping.model_copy(update={"bindings": ()})
    reviewed = build_update_review(base, source, output, mapping=mapping)
    original_issues = reviewed.issues
    assert original_issues

    core = _core(case, complete_mapping=mapping, reviewed=reviewed)

    assert any(issue.path == "draft" and issue.code == "SOURCE_COVERAGE_REQUIRED"
               for issue in core.head_issues)
    assert reviewed.issues == original_issues
    assert core.review_evidence_hash == reviewed.evidence_hash


def test_incomplete_current_parent_is_visible_in_shared_analysis_without_claiming_complete():
    case = _fixture("cap")
    parent = case[6]
    parent = type(parent).build(**(
        {name: getattr(parent, name) for name in type(parent).model_fields
         if name not in {"status", "evidence_hash"}}
        | {"issues": (CoverageIssue(code="SOURCE_COVERAGE_REQUIRED",
                                    message="Unproven inherited requirement"),)}))

    core = _core(case, verified_parent=parent)

    assert core.parent_verified is False
    assert any(issue.message == "Current inherited authority requires the complete current "
               "predecessor proof." for issue in core.head_issues)


def test_registered_complete_mapping_override_works_without_any_provider_result_wrapper():
    case = _fixture("cap")
    source, output, _, _, context, base, parent, _ = case
    path = "position.max_qty"
    source = source.model_copy(update={"text": path + " = null"})
    clauses = tuple(DailyClause.model_validate(row.model_dump() | dict(
        disposition="POLICY", semantic_role="DIRECTIVE", paths=(path,),
        reason="Source explicitly leaves this supported parameter missing"))
        for row in server_source_clauses(source.text))
    ids = tuple(row.clause_id for row in clauses)
    output = output.model_copy(update={
        "clauses": clauses, "bindings": (), "scope_clause_ids": ids,
        "operations": tuple(row.model_copy(update={"clause_ids": ids})
                            for row in output.operations),
    })
    content_hash = output.review(source.text).mapping.candidate_content_hash
    supplement = DailySupplement(supplement_id="registered-current-maximum",
        candidate_content_hash=content_hash, path=path, value=500,
        reason="Explicit registered user correction of the missing supported maximum")
    mapping = DailyMapping(mapping_version="daily-mapping-v1", candidate_content_hash=content_hash,
        clauses=clauses, bindings=(DailyFieldBinding(path=path, value=500,
            origin="HUMAN_SUPPLEMENT", unit="JSON", clause_ids=(),
            supplement_id=supplement.supplement_id),), supplements=(supplement,))
    reviewed = build_update_review(base, source, output, mapping=mapping)
    assert reviewed.issues == ()

    core = analyze_source_changes(source, output, reviewed, mapping, context=context,
        base_review=base, verified_parent=parent)

    assert core.head_issues == core.tail_issues == ()
    assert core.mapping.supplements == (supplement,)
    assert core.changed_paths == (path,)
    assert core.obligations[0].state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
    assert core.operations and core.operations[0].obligation_ids
