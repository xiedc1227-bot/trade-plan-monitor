"""A structural price relationship cannot become current stop, BUY or blanket row authority."""

import json
from datetime import timedelta

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_change_composition_attacks import _next
from tests.unit.test_source_change_scopes import _replace_parent
from tests.unit.test_source_control_changes import _assess
from tests.unit.test_source_initial_assurance import _binding
from tests.unit.test_source_risk_table_controls import _ORIGINAL, _parent, _row, _table
from tests.unit.test_source_risk_table_integration import _case

from trade_plan_monitor.ai.daily_review import DailyClause, DailyFieldBinding, semantic_values
from trade_plan_monitor.ai.plan_extraction import CurrentPlanExtractionOutput
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef
from trade_plan_monitor.ai.source_change_composition import assess_change_current
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_core import analyze_source
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_initial_assurance import assess_initial_current
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.source_obligations import declarations, value_at
from trade_plan_monitor.ai.source_risk_controls import parse_source_risk_controls
from trade_plan_monitor.ai.source_risk_table_controls import parse_source_risk_table_controls
from trade_plan_monitor.ai.source_risk_table_coverage import (
    build_risk_table_coverage,
    validate_risk_table_coverage,
)
from trade_plan_monitor.ai.source_semantic_atoms import semantic_atoms
from trade_plan_monitor.ai.update_review import build_initial_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.state.source_coverage_values import CoverageInputs


def _coverage(case):
    source, output, _, _, _, base, parent, _ = case
    evidence = build_risk_table_coverage(source, base, parent)
    analysis = analyze_source(output.draft, output.review(source.text).mapping, source.text,
                              risk_tables=evidence)
    return evidence, analysis


def test_scope_and_structural_reference_are_two_complete_independent_obligations():
    case = _case()
    evidence, result = _coverage(case)
    group, = evidence.analysis.groups
    dependency, = evidence.references
    assert result.issues == () and evidence.issues == ()
    assert dependency.price_owner == next(row for row in case[6].owners
                                         if row.path == "levels.risk_line_fen")
    assert dependency.price_binding == next(row for row in case[5].bindings
                                           if row.path == "levels.risk_line_fen")
    assert dependency.parent_binding == case[6].binding
    assert set(result.proven_paths) == {
        "risk_branches[0].holding_scope.mode", "risk_branches[0].holding_scope.trade_date"}
    relations, scopes = [], []
    for row in result.obligations:
        meaning = json.loads(row.semantics_json)
        if meaning["treatment"] == "REGISTERED_STRUCTURAL_RECOVERY_REFERENCE":
            relations.append(row)
            assert row.kind == "RELATION" and row.scope == "RISK" and row.state == "MAPPED"
            assert row.paths == () and row.group_id == group.group_id
            assert row.relation_ids == (group.scope_control.control_id,)
            assert meaning["structural_reference"] == (
                group.structural_reference.model_dump(mode="json"))
            assert meaning["price_dependency"] == dependency.model_dump(mode="json")
            assert not ({"side", "quantity", "stop", "condition"} & meaning.keys())
        elif meaning["treatment"] == "REGISTERED_SOURCE_RISK_CONTROL":
            scopes.append(row)
    assert relations and len(relations) == len(scopes)
    assert {(row.start, row.end, row.excerpt) for row in relations} == {
        (row.start, row.end, row.excerpt) for row in scopes}
    current = _assess(case)
    assert current.coverage_complete
    assert {row.obligation_id for row in relations} <= {
        row.obligation_id for row in current.global_obligations}
    price_owner = next(row for row in current.owners if row.path == "levels.risk_line_fen")
    assert price_owner.origin == "BASE"
    assert price_owner.proof_hash == dependency.price_owner.proof_hash
    assert not any(row.source_id == case[0].source_id and "risk_line_fen" in row.path
                   for row in current.owners)


@pytest.mark.parametrize("problem", ["missing-owner", "wrong-original-path", "wrong-obligation",
                                      "product-owner"])
def test_complete_parent_still_needs_the_exact_original_price_owner(problem):
    base, parent = _parent()
    unrelated = next(row for row in parent.source_assessment.obligations
                     if row.paths == ("position.max_qty",))
    owners = []
    for owner in parent.owners:
        if owner.path == "levels.risk_line_fen":
            if problem == "missing-owner":
                continue
            change = ({"original_path": "position.max_qty"} if problem == "wrong-original-path"
                      else {"obligation_ids": (unrelated.obligation_id,)}
                      if problem == "wrong-obligation" else {"origin": "PRODUCT_CONTRACT"})
            owner = owner.model_copy(update=change)
        owners.append(owner)
    parent = _replace_parent(parent, owners=tuple(owners))
    assert parent.coverage_complete
    case = _case(base=base, parent=parent)
    assert case[2].review.issues == ()
    evidence, result = _coverage(case)

    assert evidence.analysis.groups and evidence.references == () and evidence.framing == ()
    assert any(row.code == "SOURCE_COVERAGE_REQUIRED" for row in evidence.issues)
    assert any(row.kind == "RELATION" and row.state == "UNRESOLVED" for row in result.obligations)
    assert not _assess(case).coverage_complete


def test_relationship_cannot_disappear_while_the_scope_control_is_kept_mapped():
    case = _case()
    evidence, _ = _coverage(case)
    with pytest.raises(ValueError, match="relationship"):
        evidence.model_copy(update={"references": ()})
    missing = evidence.model_copy(update=dict(references=(), framing=(), issues=(CoverageIssue(
        code="SOURCE_COVERAGE_REQUIRED", message="The original structural meaning is unproven"),)))

    result = analyze_source(case[1].draft, case[1].review(case[0].text).mapping, case[0].text,
                            risk_tables=missing)

    assert any(row.kind == "PREDICATE" and row.scope == "RISK" and row.state == "MAPPED"
               for row in result.obligations)
    assert any(row.kind == "RELATION" and row.state == "UNRESOLVED" for row in result.obligations)
    assert result.issues


def test_table_evidence_cannot_be_reused_for_different_source_or_role():
    case = _case()
    evidence, _ = _coverage(case)
    with pytest.raises(ValueError, match="source"):
        validate_risk_table_coverage(evidence, case[0].text.replace("25.99", "26.00"))
    dependency = evidence.references[0]
    with pytest.raises(ValueError):
        dependency.reference.model_copy(update={"role": "NEW_POSITION_STOP"})


@pytest.mark.parametrize("text", [
    _table() + "\n| 追加条件 | 未定义 | 风险退出先等待蓝灯 |",
    "如果明天上涨：\n" + _table(),
    "条件尚未完成\n## 2. 核心价格位置更新\n\n" + _table(),
    "```\n" + _table(),
    "B. Background\n" + _table(),
    _table().replace("**25.99**", "**26.00**"),
    _table().replace("而不是给新仓位直接设止损", "直接给新仓位设止损"),
    _table() + "\n" + _row(),
], ids=["unknown-row", "antecedent", "unfinished-heading", "fence", "background",
        "wrong-price", "wrong-role", "duplicate-target"])
def test_unrecognized_rows_antecedents_price_role_changes_and_duplicates_keep_blocking(text):
    case = _case(text)
    assert case[2].review.issues == ()
    result = _assess(case)

    assert not result.coverage_complete and result.source_assessment.issues
    assert any(row.scope == "UNKNOWN" or row.state not in {"MAPPED", "CONTEXT_VERIFIED"}
               for row in result.source_assessment.obligations)
    if not parse_source_risk_table_controls(case[0], case[5], case[6]).groups:
        assert not any(json.loads(row.semantics_json or "{}").get("treatment") == (
            "REGISTERED_RISK_TABLE_SYNTAX") for row in result.source_assessment.obligations)


@pytest.mark.parametrize("problem", ["revoke", "unused", "non-scope-change"])
def test_mixed_row_scope_and_price_role_cannot_authorize_other_actual_changes(problem):
    text, options = _table(), {}
    if problem == "revoke":
        options["action"] = "REVOKE"
    elif problem == "unused":
        options["no_operations"] = True
    else:
        text += '\nrisk_branches[0].risk_line_fen = 1234\nrisk_branches[0].risk_comparison = "LT"'
        options["other_update"] = {"risk_line_fen": 1234, "risk_comparison": "LT"}
    case = _case(text, **options)
    assert case[2].review.issues == ()

    result = _assess(case)

    assert not result.coverage_complete and result.source_assessment.issues
    assert any(row.code == "SOURCE_RELATION_MISMATCH" for row in result.source_assessment.issues)


def test_dedicated_and_table_controls_cannot_repeat_the_same_risk_target():
    text = "旧持仓继续执行风险规则ORDINARY_TECHNICAL，新开仓位不适用该规则。\n" + _table()
    case = _case(text)
    assert case[2].review.issues == ()
    assert parse_source_risk_controls(case[0], case[5], case[6]).controls
    assert parse_source_risk_table_controls(case[0], case[5], case[6]).groups

    result = _assess(case)

    assert not result.coverage_complete
    assert all(row.state == "CONFLICT" for row in result.source_assessment.obligations
               if row.scope == "RISK")


def test_inherited_parent_price_binding_is_preserved_without_reassigning_original_ownership():
    base, parent = _parent()
    middle_case = _next(base, parent)
    middle = _assess(middle_case)
    assert middle.coverage_complete
    source = middle_case[0].model_copy(update=dict(source_id="next-risk-table", text=_table(),
        available_at=middle_case[0].available_at + timedelta(days=1),
        effective_trade_date=(middle_case[0].available_at + timedelta(days=1)).date()))
    before = (middle.model_dump_json(), middle_case[2].review.model_dump_json())

    evidence = build_risk_table_coverage(source, middle_case[2].review, middle)

    assert evidence.issues == () and len(evidence.references) == 1
    dependency = evidence.references[0]
    assert dependency.price_owner.origin == "BASE"
    original = next(row for row in parent.owners if row.path == "levels.risk_line_fen")
    assert dependency.price_owner.proof_hash == original.proof_hash
    assert dependency.price_owner.source_binding_hash == original.source_binding_hash
    assert dependency.price_owner.human_receipt_hash == original.human_receipt_hash
    assert before == (middle.model_dump_json(), middle_case[2].review.model_dump_json())


def test_full_unedited_original04_remains_blocked_until_its_other_real_meanings_are_supported():
    original = _ORIGINAL.read_text(encoding="utf-8")
    case = _case(original)
    assert case[0].text == original
    assert len(case[3].derivation.stages) == 3

    result = _assess(case)

    assert not result.coverage_complete and result.source_assessment.issues
    assert any(row.scope == "UNKNOWN" and row.state == "UNRESOLVED"
               for row in result.source_assessment.obligations)
    assert case[0].text == _ORIGINAL.read_text(encoding="utf-8")


def _container_parent(root, *, shared_price=False):
    base, _ = _parent(branch_price=2599 if root != "levels" else None,
                      no_global=root != "levels" and not shared_price)
    draft = base.draft
    values = semantic_values(draft)
    lines = [(path, canonical(value)) for path, value in values.items()
             if path != root and not path.startswith((root + ".", root + "["))]
    lines.append((root, canonical(value_at(draft.executable_payload(), root))))
    text = "\n".join(path + " = " + value for path, value in lines)
    canonical_clauses = server_source_clauses(text)
    container = next(row for row in declarations(text) if row.path == root)
    atoms = semantic_atoms(text, container)
    groups, offset = {}, 0
    for path, value in lines:
        end = offset + len(path + " = " + value)
        source_rows = tuple(row for row in canonical_clauses if offset <= row.start < end)
        paths = tuple(own for own in values
                      if own == path or own.startswith((path + ".", path + "[")))
        for own in paths:
            related = [atom for atom in atoms if own == atom.path
                       or own.startswith((atom.path + ".", atom.path + "["))]
            atom = max(related, key=lambda row: len(row.path)) if path == root and related else None
            groups[own] = tuple(row.clause_id for row in source_rows if atom is None or (
                row.start < atom.end and row.end > atom.start))
        if path == root:
            # Optional null members have no semantic_values binding slot. Keep
            # their exact container clauses linked to its stable kind instead
            # of deleting those raw members or pretending they were background.
            cited = {identity for own in paths for identity in groups[own]}
            uncited = tuple(row.clause_id for row in source_rows if row.clause_id not in cited)
            anchor = next((own for own in paths if own.endswith(".kind")), paths[0])
            groups[anchor] = (*groups[anchor], *uncited)
        offset = end + 1
    clauses = tuple(DailyClause.model_validate(row.model_dump() | dict(disposition="POLICY",
        paths=tuple(path for path, identities in groups.items() if row.clause_id in identities),
        reason="Exact complete source inventory with native-atom field citations"))
        for row in canonical_clauses)
    _, template = source_mapping(draft)
    mapping = template.model_copy(update=dict(clauses=clauses, bindings=tuple(
        DailyFieldBinding(path=path, value=value, origin=(
            "SOURCE_SEMANTIC" if value is None or type(value) is bool else "SOURCE"),
            unit="JSON", clause_ids=groups[path], supplement_id=None)
        for path, value in values.items())))
    source = PreparationSource(source_id="container-price-parent", text=text,
        available_at=base.available_at, effective_trade_date=base.available_at.date())
    review = build_initial_review(draft, mapping, source)
    assert review.issues == ()
    output = CurrentPlanExtractionOutput(draft=draft, clauses=mapping.clauses,
                                         bindings=mapping.bindings)
    image = draft.model_dump(mode="json")
    trace = capture_normalization(image, image, text)
    coverage = assess_source_coverage(draft, mapping, text, normalization=trace, origin="AI_NEW")
    raw = "\n" + json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    derivation = SourceDerivationEvidence.build(kind="FULL_DRAFT", source_hash=source.source_hash,
        raw_json=raw,
        context_json=None, base_hash=None, stages=(DerivationStage.build(
            phase="SOURCE_NORMALIZED", output_json=canonical(output.model_dump(mode="json"))),))
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, normalization=trace,
        initial_coverage=coverage, derivation=derivation)
    parent = assess_initial_current(source, review, mapping, inputs,
                                     binding=_binding(source, review, inputs))
    assert coverage.coverage_complete and parent.coverage_complete, parent.issues
    return source, review, parent


@pytest.mark.parametrize("root", ["levels", "risk_branches[0]", "risk_branches"],
                         ids=["global-levels", "local-branch", "branch-list-with-all"])
def test_complete_container_parent_price_atoms_support_the_actual_table_update(root):
    source, base, parent = _container_parent(root)
    assert root + " = {" in source.text or root + " = [" in source.text
    assert any(json.loads(row.semantics_json or "{}").get("treatment") == (
        "COMPLETE_JSON_DECLARATION") for row in parent.source_assessment.obligations)
    if root == "risk_branches":
        assert any(row.kind == "RELATION" for row in parent.source_assessment.obligations)
    price_path = "levels.risk_line_fen" if root == "levels" else "risk_branches[0].risk_line_fen"
    owner = next(row for row in parent.owners if row.path == price_path)
    linked = [row for row in parent.source_assessment.obligations
              if row.obligation_id in owner.obligation_ids]
    assert any(json.loads(row.semantics_json or "{}") == dict(path=price_path, value=2599)
               for row in linked)
    case = _case(base=base, parent=parent)
    assert case[2].review.issues == () and len(case[3].derivation.stages) == 3

    result = _assess(case)

    assert result.coverage_complete, result.source_assessment.issues
    dependency = build_risk_table_coverage(case[0], base, parent).references[0]
    assert dependency.price_owner == owner
    assert len(canonical(dict(treatment="REGISTERED_STRUCTURAL_RECOVERY_REFERENCE",
        structural_reference=dependency.reference.model_dump(mode="json"),
        price_dependency=dependency.model_dump(mode="json")))) <= 8192


def test_inherited_complete_container_price_owner_supports_actual_multihop_table_update():
    _, base, parent = _container_parent("risk_branches[0]")
    middle_case = _next(base, parent)
    middle = _assess(middle_case)
    assert middle.coverage_complete
    case = list(_case(base=middle_case[2].review, parent=middle))
    case[7] = case[7].model_copy(update={"item_index": middle.binding.item_index + 1})
    source, output, materialized, inputs, context, base, parent, binding = case

    result = assess_change_current(source, output, materialized, inputs, context=context,
        base_review=base, verified_parent=parent, binding=binding, prefix=(
            *parent.prefix, PrefixAssuranceRef(binding=parent.binding,
                                              assurance_hash=parent.evidence_hash)))

    assert result.coverage_complete, result.source_assessment.issues
    dependency = build_risk_table_coverage(source, base, parent).references[0]
    assert dependency.price_owner.origin == "BASE"


@pytest.mark.parametrize("problem", ["wrong-price-field", "same-value-other-path", "missing-owner",
                                      "container-label-only"])
def test_container_price_owner_cannot_be_replaced_by_an_unrelated_or_selfsigned_meaning(problem):
    _, base, parent = _container_parent("risk_branches[0]", shared_price=True)
    path = "risk_branches[0].risk_line_fen"
    source_rows = parent.source_assessment.obligations
    other = next(row for row in source_rows if row.paths == ("levels.risk_line_fen",))
    assert json.loads(other.semantics_json) == dict(path="levels.risk_line_fen", value=2599)
    owners = []
    for owner in parent.owners:
        if owner.path == path:
            if problem == "missing-owner":
                continue
            if problem == "wrong-price-field":
                owner = owner.model_copy(update={"original_path": "levels.risk_line_fen"})
            elif problem == "same-value-other-path":
                owner = owner.model_copy(update={"obligation_ids": (other.obligation_id,)})
            else:
                ids = tuple(row.obligation_id for row in source_rows
                            if row.obligation_id in owner.obligation_ids and json.loads(
                                row.semantics_json or "{}").get("treatment") == (
                                    "COMPLETE_JSON_DECLARATION"))
                assert ids
                owner = owner.model_copy(update={"obligation_ids": ids})
        owners.append(owner)
    changed = _replace_parent(parent, owners=tuple(owners))
    assert changed.coverage_complete  # Self-consistent model status is not source proof.
    case = _case(base=base, parent=changed)
    assert case[2].review.issues == () and len(case[3].derivation.stages) == 3

    evidence = build_risk_table_coverage(case[0], base, changed)
    result = _assess(case)

    assert evidence.references == () and evidence.issues
    assert not result.coverage_complete and result.source_assessment.issues
