"""Complete observed full-wire replacements require independent source and scope proof."""

import json

import pytest
from tests.integration.preparation_review_current_fixtures import field_source, reviewed_mapping
from tests.unit.test_source_change_assurance import _NOW, _assemble, _parent
from tests.unit.test_source_change_attacks import _two_rule_parent
from tests.unit.test_source_change_composition import _assess
from tests.unit.test_source_change_composition_attacks import _initial
from tests.unit.test_source_controls import _variant
from tests.unit.test_source_risk_table_controls import _parent as _scoped_parent

from trade_plan_monitor.ai.daily_review import DailyFieldBinding, DailyMapping
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateExtractionOutput,
    PlanUpdateOperation,
)
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.risk_scope import risk_identity


def _case(*, parent_case=None, draft=None, phrase="完整替换此前计划。", tail="", omit=None,
          root_list=None, scope_wrong=False, output_scope="FULL_REPLACEMENT", retain=False):
    base, parent = _parent() if parent_case is None else parent_case
    if draft is None:
        draft = base.draft.model_copy(update={"position": base.draft.position.model_copy(
            update={"max_qty": 500})})
    native = field_source(draft)
    text = native + ("\nordinary_rules = " + canonical(root_list)
                     if root_list is not None else "") + "\n" + phrase + tail
    mapping = reviewed_mapping(draft, text)
    if omit is not None:
        line = next(row for row in native.splitlines() if row.startswith(omit + " = "))
        text = text.replace(line + "\n", "")
        mapping_without = reviewed_mapping(draft, native)
        # Rebuild the exact source map with this field owned by the existing
        # product registry. Unregistered policy defaults still fail old review.
        from trade_plan_monitor.ai.daily_review import DailyClause
        from trade_plan_monitor.ai.review import server_source_clauses
        from trade_plan_monitor.ai.source_obligations import declarations

        declared = declarations(text)
        actual_clauses = server_source_clauses(text)
        bindings = []
        for bound in mapping_without.bindings:
            if bound.path == omit:
                bindings.append(DailyFieldBinding(path=omit, value=bound.value,
                    origin="PRODUCT_CONTRACT", unit="JSON", clause_ids=(), supplement_id=None))
            else:
                matched = next(row for row in declared if row.path == bound.path)
                ids = tuple(row.clause_id for row in actual_clauses
                            if matched.start <= row.start < row.end <= matched.end)
                bindings.append(bound.model_copy(update={"clause_ids": ids}))
        clauses = tuple(DailyClause.model_validate(row.model_dump() | dict(
            disposition="POLICY" if (paths := tuple(bound.path for bound in bindings
                if row.clause_id in bound.clause_ids)) else "CONTEXT", paths=paths,
            semantic_role=None if paths else "COMMENTARY", reason="Exact source or scope."))
            for row in actual_clauses)
        mapping = DailyMapping(mapping_version="daily-mapping-v1",
            candidate_content_hash=mapping_without.candidate_content_hash,
            bindings=tuple(bindings), clauses=clauses, supplements=())
    scope = tuple(row.clause_id for row in mapping.clauses if "完整替换此前计划" in row.excerpt)
    if scope_wrong:
        scope = (mapping.clauses[0].clause_id,)
    clauses = tuple(row.model_copy(update={"disposition": "POLICY", "semantic_role": None})
                    if row.clause_id in scope else row for row in mapping.clauses)
    operations = (() if output_scope == "FULL_REPLACEMENT" else (PlanUpdateOperation(
        target="position", action="MODIFY", clause_ids=next(
            row.clause_ids for row in mapping.bindings if row.path == "position.max_qty")),))
    output = PlanUpdateExtractionOutput(schema_version="monitor-loop-update-extraction-v1",
        draft=draft, clauses=clauses, bindings=mapping.bindings, scope=output_scope,
        scope_clause_ids=scope, retain_unmentioned=retain, operations=operations,
        assumptions=(), warnings=())
    source = PreparationSource(source_id="replacement-source", text=text, available_at=_NOW,
                               effective_trade_date=_NOW.date())
    context = context_from_review(base, parent.binding.candidate_hash)
    case = _assemble(base, parent, source, output, context)
    assert "draft" in json.loads(case[3].derivation.raw_json)
    assert len(case[3].derivation.stages) == 3
    return case


def test_complete_current_full_wire_after_image_and_exact_scope_get_current_proof():
    case = _case()
    assert not case[2].review.issues
    proof = _assess(case)
    assert proof.coverage_complete and proof.source_assessment.coverage_complete
    assert proof.source_assessment.raw_delta_verified
    assert proof.source_assessment.provider_full_draft_supplied
    assert proof.current_automatic_fidelity_verified is False and proof.authority_granted is False
    assert {owner.source_id for owner in proof.owners} == {case[0].source_id}
    assert proof.source_assessment.changed_paths == ("position.max_qty",)


@pytest.mark.parametrize("changes", [
    {"tail": "\nOnly buy after the blue lantern turns green."},
    {"tail": "\n其余规则保留。"}, {"tail": "\n今日没有新增指令。"},
    {"phrase": "不是完整替换此前计划。"}, {"phrase": "假设完整替换此前计划。"},
    {"phrase": "如果明天站稳，完整替换此前计划。"},
    {"phrase": "如果明天站稳：\n完整替换此前计划。"},
    {"phrase": "“完整替换此前计划。”"},
    {"phrase": "B. 背景说明\n完整替换此前计划。"},
    {"scope_wrong": True},
    {"output_scope": "EXPLICIT_CHANGES", "retain": True},
])
def test_scope_phrase_never_waives_unknowns_qualifications_headers_or_missing_after_field(changes):
    case = _case(**changes)
    proof = _assess(case)
    assert proof.status == "BLOCKED" and proof.source_assessment.issues
    assert proof.source_assessment.raw_delta_verified
    assert proof.authority_granted is False


@pytest.mark.parametrize("path", [
    "schema_version", "execution_mode", "execution_version", "trading_rules.settlement",
    "trading_rules.tick_size_fen", "activation.mode", "ordinary_rules[0].validity.mode",
])
def test_registered_product_defaults_need_no_literal_source_spelling_in_full_replacement(path):
    case = _case(omit=path)
    assert case[2].review.issues == () and len(case[3].derivation.stages) == 3
    assert not any(line.startswith(path + " = ") for line in case[0].text.splitlines())
    proof = _assess(case)
    assert proof.coverage_complete and proof.source_assessment.coverage_complete
    owner, = (row for row in proof.owners if row.path == path)
    assert owner.origin == "PRODUCT_CONTRACT" and owner.obligation_ids == ()
    assert not any(path in row.paths for row in proof.source_assessment.obligations)
    assert proof.source_assessment.raw_delta_verified
    assert proof.source_assessment.provider_full_draft_supplied
    assert proof.current_automatic_fidelity_verified is False and proof.authority_granted is False


@pytest.mark.parametrize("path", [
    "position.max_qty", "ordinary_rules[0].quantity", "ordinary_rules[0].condition.price_fen",
])
def test_quantity_and_condition_omissions_cannot_claim_product_default_ownership(path):
    with pytest.raises(ValueError, match="product contract"):
        _case(omit=path)


@pytest.mark.parametrize("tail,code", [
    ("\nschema_version = 4", "SOURCE_RELATION_MISMATCH"),
    ("\nOnly buy after the blue lantern turns green.", "SOURCE_CONTEXT_UNVERIFIED"),
])
def test_registered_default_never_waives_explicit_conflicting_or_unknown_source(tail, code):
    case = _case(omit="schema_version", tail=tail)
    assert case[2].review.issues == ()
    proof = _assess(case)
    assert proof.status == "BLOCKED"
    assert any(row.code == code for row in proof.source_assessment.issues)


def test_default_evidence_requires_the_exact_registered_binding_shape():
    case = _case(omit="schema_version")
    bindings = tuple(row.model_copy(update={"unit": "TEXT"}) if row.path == "schema_version"
                     else row for row in case[1].bindings)
    output = case[1].model_copy(update={"bindings": bindings})
    changed = _assemble(case[5], case[6], case[0], output, case[4])
    assert changed[2].review.issues == ()
    proof = _assess(changed)
    assert proof.status == "BLOCKED"
    assert any(row.path == "schema_version" for row in proof.source_assessment.issues)


@pytest.mark.parametrize("target", ["ordinary_rules", "alert_rules", "risk_branches"])
def test_empty_product_default_never_supplies_a_whole_rule_withdrawal(target):
    parent = _variant("risk" if target == "risk_branches" else "alert")
    after = parent[0].draft.model_copy(update={target: ()})
    case = _case(parent_case=parent, draft=after, omit=target)
    assert case[2].review.issues == ()
    proof = _assess(case)
    assert proof.status == "BLOCKED"
    assert any(row.action == "REVOKE" and row.target == target and not row.obligation_ids
               for row in proof.source_assessment.operations)
    owner, = (row for row in proof.owners if row.path == target)
    assert owner.origin == "PRODUCT_CONTRACT" and owner.obligation_ids == ()


@pytest.mark.parametrize("target", ["ordinary_rules", "alert_rules", "risk_branches"])
def test_registered_empty_wire_default_still_needs_separate_exact_withdrawal_evidence(target):
    parent = _variant("risk" if target == "risk_branches" else "alert")
    after = parent[0].draft.model_copy(update={target: ()})
    before = getattr(parent[0].draft, target)
    if target == "risk_branches":
        controls = "".join(f"\n对全部新旧持仓一并废止风险规则{risk_identity(row)}，"
                           "今后不再执行该规则。"
                           for row in before)
    else:
        controls = "".join(f"\noperations[{index}] = " + canonical(dict(
            target=target, rule_id=row.rule_id, action="REVOKE"))
                           for index, row in enumerate(before))
    case = _case(parent_case=parent, draft=after, omit=target, tail=controls)
    proof = _assess(case)
    assert case[2].review.issues == () and proof.coverage_complete
    assert all(row.obligation_ids for row in proof.source_assessment.operations
               if row.target == target and row.action == "REVOKE")
    owner, = (row for row in proof.owners if row.path == target)
    assert owner.origin == "PRODUCT_CONTRACT" and owner.obligation_ids == ()


def test_blocked_current_parent_cannot_be_replaced_into_complete_authority():
    case = _case(parent_case=_parent(extra="Every action also depends on the blue lantern."))
    proof = _assess(case)
    assert proof.status == "BLOCKED"
    assert set(case[6].global_obligations) <= set(proof.global_obligations)


def test_scope_sentence_cannot_grant_initial_source_coverage_without_a_predecessor():
    base, _ = _parent()
    text = field_source(base.draft) + "\n完整替换此前计划。"
    mapping = reviewed_mapping(base.draft, text)
    _, proof = _initial(base.draft, text, mapping, source_id="initial-not-a-replacement")
    assert proof.status == "BLOCKED" and not proof.coverage_complete
    assert any(row.excerpt == "完整替换此前计划。" and row.scope == "UNKNOWN"
               for row in proof.source_assessment.obligations)


def test_removing_ordinary_rule_requires_complete_root_list_absence_not_just_after_leaves():
    parent = _two_rule_parent()
    draft = parent[0].draft.model_copy(update={
        "ordinary_rules": parent[0].draft.ordinary_rules[1:]})
    unproven = _assess(_case(parent_case=parent, draft=draft))
    assert unproven.status == "BLOCKED"
    rows = [row.model_dump(mode="json") for row in draft.ordinary_rules]
    proven = _assess(_case(parent_case=parent, draft=draft, root_list=rows))
    assert proven.coverage_complete
    removal, = (row for row in proven.source_assessment.operations if row.action == "REVOKE")
    assert removal.target == "ordinary_rules" and removal.rule_id == "low-buy"
    assert len(removal.obligation_ids) >= 2


def test_exact_empty_ordinary_root_list_can_remove_old_ordinary_rules_but_preserve_alert():
    parent = _variant("alert")
    draft = parent[0].draft.model_copy(update={"ordinary_rules": ()})
    case = _case(parent_case=parent, draft=draft)
    proof = _assess(case)
    assert proof.coverage_complete
    assert draft.alert_rules and not draft.ordinary_rules
    assert "ordinary_rules = []" in case[0].text
    assert sum(row.action == "REVOKE" for row in proof.source_assessment.operations) == 2


def test_empty_risk_root_list_and_complete_replacement_never_supply_whole_risk_withdrawal():
    parent = _variant("risk")
    draft = parent[0].draft.model_copy(update={"risk_branches": ()})
    case = _case(parent_case=parent, draft=draft)
    proof = _assess(case)
    assert "risk_branches = []" in case[0].text
    assert proof.status == "BLOCKED"
    assert any(row.action == "REVOKE" and row.target == "risk_branches"
               and not row.obligation_ids for row in proof.source_assessment.operations)


@pytest.mark.parametrize("mutation", ["incomplete", "reordered"])
def test_removal_absence_cannot_be_inferred_from_an_incomplete_or_reordered_root_list(mutation):
    parent = _two_rule_parent()
    before = parent[0].draft
    replacement = before.ordinary_rules[-1].model_copy(update={"rule_id": "replacement-sell"})
    after = before.model_copy(update={"ordinary_rules": (before.ordinary_rules[0], replacement)})
    rows = [row.model_dump(mode="json") for row in after.ordinary_rules]
    assert _assess(_case(parent_case=parent, draft=after, root_list=rows)).coverage_complete
    roots = rows[:1] if mutation == "incomplete" else rows[::-1]
    proof = _assess(_case(parent_case=parent, draft=after, root_list=roots))
    assert proof.status == "BLOCKED" and proof.source_assessment.issues


def test_full_replacement_risk_withdrawal_still_needs_its_exact_entire_rule_control():
    parent = _variant("risk")
    after = parent[0].draft.model_copy(update={"risk_branches": ()})
    controls = "".join(f"\n对全部新旧持仓一并废止风险规则{risk_identity(row)}，今后不再执行该规则。"
                       for row in parent[0].draft.risk_branches)
    case = _case(parent_case=parent, draft=after, tail=controls)
    proof = _assess(case)
    assert proof.coverage_complete
    withdrawals = [row for row in proof.source_assessment.operations
                   if row.target == "risk_branches" and row.action == "REVOKE"]
    assert withdrawals and all(row.obligation_ids for row in withdrawals)


def _optional_removal(kind):
    parent = _scoped_parent(old_scope="2026-10-25") if kind == "scope" else _scoped_parent()
    before = parent[0].draft
    if kind == "scope":
        branches = list(before.risk_branches)
        branches[0] = branches[0].model_copy(update={"holding_scope": None})
        after = before.model_copy(update={"risk_branches": tuple(branches)})
        path = "risk_branches[0].holding_scope"
    elif kind == "core_target":
        assert before.position.core_target_qty is not None
        after = before.model_copy(update={"position": before.position.model_copy(
            update={"core_target_qty": None})})
        path = "position.core_target_qty"
    elif kind == "zone":
        rules = list(before.ordinary_rules)
        assert rules[0].zone is not None
        rules[0] = rules[0].model_copy(update={"zone": None})
        after = before.model_copy(update={"ordinary_rules": tuple(rules)})
        path = "ordinary_rules[0].zone"
    else:
        raise AssertionError("unknown optional removal fixture")
    return parent, after, path


@pytest.mark.parametrize("kind", ["scope", "core_target", "zone"])
def test_full_replacement_cannot_silently_remove_an_optional_policy(kind):
    parent, after, path = _optional_removal(kind)
    case = _case(parent_case=parent, draft=after)
    assert parent[1].coverage_complete and case[2].review.issues == ()
    assert path not in case[0].text and len(case[3].derivation.stages) == 3
    proof = _assess(case)
    assert any(own == path or own.startswith(path + ".")
               for own in proof.source_assessment.changed_paths)
    assert proof.status == "BLOCKED" and not proof.coverage_complete
    assert any(row.path == path or row.path.startswith(path + ".")
               for row in proof.source_assessment.issues)


@pytest.mark.parametrize("kind", ["scope", "core_target", "zone"])
def test_a_registered_wire_default_cannot_supply_missing_optional_policy_absence(kind):
    parent, after, path = _optional_removal(kind)
    case = _case(parent_case=parent, draft=after, omit="schema_version")
    proof = _assess(case)
    assert case[2].review.issues == () and proof.status == "BLOCKED"
    assert not any(row.path == "schema_version" for row in proof.source_assessment.issues)
    assert any(row.path == path or row.path.startswith(path + ".")
               for row in proof.source_assessment.issues)


def _after_container(kind, draft):
    if kind == "scope":
        return "risk_branches[0]", draft.risk_branches[0].model_dump(mode="json")
    if kind == "core_target":
        return "position", draft.position.model_dump(mode="json")
    if kind == "zone":
        return "ordinary_rules[0]", draft.ordinary_rules[0].model_dump(mode="json")
    raise AssertionError("unknown optional removal fixture")


@pytest.mark.parametrize("kind", ["scope", "core_target", "zone"])
def test_exact_complete_typed_after_container_independently_proves_optional_absence(kind):
    parent, after, path = _optional_removal(kind)
    root, value = _after_container(kind, after)
    case = _case(parent_case=parent, draft=after, tail="\n" + root + " = " + canonical(value))
    proof = _assess(case)
    assert case[2].review.issues == () and proof.coverage_complete
    operation, = (row for row in proof.source_assessment.operations
                  if row.action == "MODIFY" and any(own == path or own.startswith(path + ".")
                                                   for own in row.changed_paths))
    assert any(row.obligation_id in operation.obligation_ids and root in row.paths
               for row in proof.source_assessment.obligations)
    assert proof.authority_granted is False


@pytest.mark.parametrize("kind", ["core_target", "zone"])
def test_explicit_native_nullable_after_value_is_separate_from_replacement_scope(kind):
    parent, after, path = _optional_removal(kind)
    case = _case(parent_case=parent, draft=after, tail="\n" + path + " = null")
    proof = _assess(case)
    assert proof.coverage_complete and case[2].review.issues == ()
    assert any(row.excerpt == path + " = null" and row.state == "MAPPED"
               for row in proof.source_assessment.obligations)


def test_explicit_null_for_excluded_native_scope_keeps_the_existing_conflict():
    parent, after, path = _optional_removal("scope")
    case = _case(parent_case=parent, draft=after, tail="\n" + path + " = null")
    proof = _assess(case)
    assert proof.status == "BLOCKED"
    assert any(row.code == "SOURCE_RELATION_MISMATCH" and row.path == path
               for row in proof.source_assessment.issues)


@pytest.mark.parametrize("kind", ["scope", "core_target", "zone"])
@pytest.mark.parametrize("mutation", ["partial", "background", "conditional"])
def test_optional_absence_needs_complete_current_known_after_evidence(kind, mutation):
    parent, after, _ = _optional_removal(kind)
    root, value = _after_container(kind, after)
    if mutation == "partial":
        value = dict(value)
        del value["kind" if kind == "scope" else "max_qty" if kind == "core_target" else "side"]
    prefix = ("\nB. 背景说明\n" if mutation == "background" else
              "\n如果明天满足另一个条件：\n" if mutation == "conditional" else "\n")
    case = _case(parent_case=parent, draft=after, tail=prefix + root + " = " + canonical(value))
    proof = _assess(case)
    assert proof.status == "BLOCKED" and proof.source_assessment.issues
    assert proof.authority_granted is False


def test_another_stable_risk_owner_cannot_donate_its_complete_container_absence():
    parent, after, path = _optional_removal("scope")
    case = _case(parent_case=parent, draft=after, tail="\nrisk_branches[1] = " + canonical(
        after.risk_branches[1].model_dump(mode="json")))
    proof = _assess(case)
    assert case[2].review.issues == () and proof.status == "BLOCKED"
    assert any(row.path.startswith(path + ".") for row in proof.source_assessment.issues)


def test_same_null_value_on_another_ordinary_rule_does_not_prove_this_removed_zone():
    parent = _variant("zone")
    rules = list(parent[0].draft.ordinary_rules)
    assert rules[0].zone == "LOW_BUY" and rules[1].zone is None
    rules[0] = rules[0].model_copy(update={"zone": None})
    after = parent[0].draft.model_copy(update={"ordinary_rules": tuple(rules)})
    path = "ordinary_rules[0].zone"
    case = _case(parent_case=parent, draft=after, tail="\nordinary_rules[1].zone = null")
    proof = _assess(case)
    assert case[2].review.issues == () and proof.status == "BLOCKED"
    assert any(row.path == path for row in proof.source_assessment.issues)
