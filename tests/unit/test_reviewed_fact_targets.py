"""Actual native reviewed requirements, never source/candidate truth or permits."""

import json
from dataclasses import FrozenInstanceError
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_plan import synthetic_plan_payload
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.domain.reviewed_fact_targets import (
    assess_unbound_fact,
    filter_unbound_facts,
    list_reviewed_fact_targets,
    resolve_reviewed_fact_target,
)
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

SH = ZoneInfo("Asia/Shanghai")
TARGET = datetime(2026, 9, 22, 9, 35, tzinfo=SH)


def _leaf(requirement="成交不异常放大", scope="TRADE_DATE", kind="VOLUME_OR_CANDLE"):
    return dict(type="REVIEWED_FACT", fact_kind=kind,
                evidence_requirement=requirement, validity_scope=scope)


def _plan(*leaves):
    raw = unified_payload()
    raw.update(ordinary_rules=raw["ordinary_rules"][:1], risk_branches=[], alert_rules=[])
    raw["ordinary_rules"][0]["condition"] = dict(type="ALL", conditions=leaves or (_leaf(),))
    return UnifiedTradePlan.model_validate(raw)


def _fact(plan, **changes):
    value = dict(id="actual-volume-only", kind="VOLUME_OR_CANDLE", verified=True,
                 satisfied=True, trade_date="2026-09-22", signal_id=None,
                 content_hash=daily_plan_content_sha256(plan))
    value.update(changes)
    return value


def test_unique_native_requirement_keeps_the_actual_predicate_fact():
    plan = _plan(_leaf())
    fact = _fact(plan)
    result = assess_unbound_fact(plan, fact)
    assert result.usable and result.reason == "UNIQUE_DEFINITION"
    assert result.definition_count == 1
    assert filter_unbound_facts(plan, (fact,))[0] is fact


def test_projection_does_not_let_one_fact_satisfy_two_different_hard_requirements():
    plan = _plan(_leaf(), _leaf("明显下影"))
    fact = _fact(plan)
    before = evaluate_unified_condition(plan.ordinary_rules[0].condition, None,
                                        facts=(fact,), target=TARGET)
    assert before.outcome == "SATISFIED"  # The actual unsafe producer baseline remains.
    after = evaluate_unified_condition(plan.ordinary_rules[0].condition, None,
        facts=filter_unbound_facts(plan, (fact,)), target=TARGET)
    assert after.outcome == "MISSING_INPUT"
    assert [child.outcome for child in after.children] == ["MISSING_INPUT", "MISSING_INPUT"]


def test_decision_preserves_distinct_complete_definitions_and_exact_leaf_json():
    plan = _plan(_leaf(), _leaf("明显下影"))
    result = assess_unbound_fact(plan, _fact(plan))
    assert not result.usable and result.reason == "AMBIGUOUS_DEFINITION"
    assert result.definition_count == 2 and result.definition_json is None
    assert [json.loads(r.definition_json)["evidence_requirement"] for r in result.definitions] == [
        "成交不异常放大", "明显下影"]
    assert [r.condition_path for r in result.definitions] == [
        "condition.conditions[0]", "condition.conditions[1]"]
    assert {r.owner_kind for r in result.definitions} == {"ORDINARY_RULE"}
    assert {r.owner_id for r in result.definitions} == {"low-buy"}


def test_identical_complete_definition_folds_count_but_keeps_all_original_refs():
    plan = _plan(_leaf(), _leaf())
    result = assess_unbound_fact(plan, _fact(plan))
    assert result.usable and result.definition_count == 1 and len(result.definitions) == 2
    assert result.definition_json == canonical(_leaf())
    assert result.definitions[0].observation_context == result.definitions[1].observation_context
    assert result.definitions[0].condition_path != result.definitions[1].condition_path


@pytest.mark.parametrize("signal", [None, "existing-signal"])
def test_actual_fact_eligibility_combines_overlapping_date_and_signal_scopes(signal):
    plan = _plan(_leaf(), _leaf("明显下影", scope="SIGNAL"))
    result = assess_unbound_fact(plan, _fact(plan, signal_id=signal))
    assert result.reason == ("UNIQUE_DEFINITION" if signal is None else "AMBIGUOUS_DEFINITION")
    assert result.definition_count == (1 if signal is None else 2)
    if signal is not None:
        before = evaluate_unified_condition(plan.ordinary_rules[0].condition, None,
            facts=(_fact(plan, signal_id=signal),), target=TARGET, signal_id=signal)
        assert before.outcome == "SATISFIED"
        assert filter_unbound_facts(plan, (_fact(plan, signal_id=signal),)) == ()


def test_signal_only_requirement_needs_actual_nonempty_signal_id():
    plan = _plan(_leaf(scope="SIGNAL"))
    assert assess_unbound_fact(plan, _fact(plan)).reason == "NO_DEFINITION"
    assert assess_unbound_fact(plan, _fact(plan, signal_id="")).reason == "NO_DEFINITION"
    assert assess_unbound_fact(plan, _fact(plan, signal_id="existing")).usable


@pytest.mark.parametrize("requirement", [
    "量能不能异常放大", "成交不异常放大；原文约束：另外必须收起", "成交不异常放大且明显下影",
])
def test_no_synonym_truncation_or_merged_testimony_equivalence(requirement):
    plan = _plan(_leaf(), _leaf(requirement))
    assert assess_unbound_fact(plan, _fact(plan)).reason == "AMBIGUOUS_DEFINITION"


@pytest.mark.parametrize("kind", [
    "TRADABILITY", "FULL_SESSION_SUSPENSION", "INDEPENDENT_EVENT", "SIGNAL_INVALIDATION",
])
def test_controls_pass_through_without_proving_a_reviewed_predicate(kind):
    plan = _plan(_leaf(), _leaf("明显下影"))
    fact = _fact(plan, kind=kind)
    result = assess_unbound_fact(plan, fact)
    assert result.reason == "CONTROL_FACT" and not result.usable
    assert result.definition_count == 0 and result.definition_json is None
    assert filter_unbound_facts(plan, (fact,))[0] is fact


@pytest.mark.parametrize("kind", [
    "TRADABILITY", "FULL_SESSION_SUSPENSION", "INDEPENDENT_EVENT", "SIGNAL_INVALIDATION",
])
def test_native_control_kind_used_as_hard_predicate_cannot_bypass_attribution(kind):
    plan = _plan(_leaf("Exact first complete requirement", kind=kind),
                 _leaf("Exact different complete requirement", kind=kind, scope="SIGNAL"))
    fact = _fact(plan, kind=kind, signal_id="actual-existing-signal")
    result = assess_unbound_fact(plan, fact)
    assert result.reason == "AMBIGUOUS_DEFINITION" and not result.usable
    assert result.definition_count == 2
    assert filter_unbound_facts(plan, (fact,)) == ()


@pytest.mark.parametrize("kind", [
    "TRADABILITY", "FULL_SESSION_SUSPENSION", "INDEPENDENT_EVENT", "SIGNAL_INVALIDATION",
])
def test_single_actual_control_kind_predicate_uses_normal_exact_definition_matching(kind):
    plan = _plan(_leaf("Exact declared complete requirement", kind=kind))
    result = assess_unbound_fact(plan, _fact(plan, kind=kind))
    assert result.reason == "UNIQUE_DEFINITION" and result.usable
    assert result.definition_json == canonical(
        _leaf("Exact declared complete requirement", kind=kind))


def test_content_mismatch_is_not_repaired_from_another_equal_kind():
    plan = _plan(_leaf())
    fact = _fact(plan, content_hash="0" * 64)
    assert assess_unbound_fact(plan, fact).reason == "CONTENT_MISMATCH"
    assert filter_unbound_facts(plan, (fact,)) == ()


@pytest.mark.parametrize("changes", [
    {"kind": "OTHER"}, {"kind": []}, {"kind": {}}, {"verified": 1},
    {"trade_date": "2026-02-30"}, {"trade_date": "20260922"},
    {"trade_date": None}, {"signal_id": 5}, {"satisfied": "true"},
])
def test_invalid_fact_data_never_supplies_predicate_evidence(changes):
    plan = _plan(_leaf())
    fact = _fact(plan, **changes)
    assert assess_unbound_fact(plan, fact).reason == "INVALID_FACT"
    assert filter_unbound_facts(plan, (fact,)) == ()


@pytest.mark.parametrize("value", [None, [], "FACT", object()])
def test_nonfact_input_is_a_closed_diagnostic(value):
    assert assess_unbound_fact(_plan(), value).reason == "INVALID_FACT"


def test_negative_fact_keeps_its_own_truth_and_original_object():
    plan = _plan(_leaf())
    fact = _fact(plan, satisfied=False)
    filtered = filter_unbound_facts(plan, (fact,))
    assert filtered[0] is fact and fact["satisfied"] is False
    result = evaluate_unified_condition(plan.ordinary_rules[0].condition, None,
                                        facts=filtered, target=TARGET)
    assert result.outcome == "UNSATISFIED"


def _with_second_rule(plan, *, confirmation=None, validity=None):
    raw = plan.model_dump(mode="json")
    second = {**raw["ordinary_rules"][0], "side": "SELL", "rule_id": "sell-other", "zone": None}
    if confirmation is not None:
        second.update(confirmation=confirmation, execution_window="CURRENT_SESSION")
    if validity is not None:
        second["validity"] = validity
    raw["ordinary_rules"].append(second)
    return UnifiedTradePlan.model_validate(raw)


def test_same_leaf_different_declared_confirmation_period_is_not_one_observation():
    plan = _with_second_rule(_plan(), confirmation={"kind": "COMPLETED_BAR_CLOSE",
                                                   "timeframe_minutes": 5})
    result = assess_unbound_fact(plan, _fact(plan))
    assert result.reason == "AMBIGUOUS_DEFINITION" and result.definition_count == 2
    assert len({r.definition_json for r in result.definitions}) == 1
    assert len({r.observation_context for r in result.definitions}) == 2


def test_same_leaf_same_context_in_distinct_rules_keeps_refs_without_new_semantic_default():
    plan = _with_second_rule(_plan())
    result = assess_unbound_fact(plan, _fact(plan))
    assert result.usable and result.definition_count == 1
    assert {r.owner_id for r in result.definitions} == {"low-buy", "sell-other"}


def test_same_leaf_different_explicit_validity_is_not_silently_folded():
    plan = _with_second_rule(_plan(), validity={"mode": "PLAN_ACTIVE"})
    result = assess_unbound_fact(plan, _fact(plan))
    assert result.reason == "AMBIGUOUS_DEFINITION"
    assert result.definition_count == 2


def test_reset_observation_is_separate_from_confirmation_even_with_identical_leaf():
    plan = _plan()
    raw = plan.model_dump(mode="json")
    raw["ordinary_rules"][0]["independent_signal"] = dict(
        mode="LATER_CLOSE_RESET_THEN_CONFIRM", reset_condition=_leaf())
    plan = UnifiedTradePlan.model_validate(raw)
    result = assess_unbound_fact(plan, _fact(plan))
    assert result.reason == "AMBIGUOUS_DEFINITION" and result.definition_count == 2
    assert any(r.condition_path == "independent_signal.reset_condition" for r in result.definitions)


def test_alert_and_severe_risk_native_roots_are_catalogued_without_metadata_recursion():
    raw = unified_payload()
    raw["ordinary_rules"][0]["condition"] = _leaf()
    raw["alert_rules"] = [dict(kind="RISK_ALERT", rule_id="alert-own", condition=_leaf(),
                               confirmation={"kind": "OFFICIAL_DAILY_CLOSE"})]
    plan = UnifiedTradePlan.model_validate(raw)
    volume = assess_unbound_fact(plan, _fact(plan))
    assert {r.owner_kind for r in volume.definitions} == {"ORDINARY_RULE", "ALERT_RULE"}
    severe = assess_unbound_fact(plan, _fact(plan, kind="SEVERE_STRUCTURE"))
    assert severe.usable and severe.definitions[0].owner_kind == "RISK_BRANCH"
    assert severe.definitions[0].owner_id == "SEVERE_TECHNICAL"
    raw["ordinary_rules"][0]["condition"] = dict(
        type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=4000)
    raw["alert_rules"] = []
    raw["name"] = "REVIEWED_FACT VOLUME_OR_CANDLE 成交不异常放大"
    plan = UnifiedTradePlan.model_validate(raw)
    assert assess_unbound_fact(plan, _fact(plan)).reason == "NO_DEFINITION"


def test_schema4_uses_only_real_typed_roots_and_ignores_disabled_rule_text():
    raw = synthetic_plan_payload()
    raw["ordinary_rules"][1]["reason"] = "REVIEWED_FACT VOLUME_OR_CANDLE 明显下影"
    plan = DailyTradePlan.model_validate(raw)
    result = assess_unbound_fact(plan, _fact(plan))
    assert result.usable and len(result.definitions) == 1
    assert result.definitions[0].condition_path == "volume_or_candle"
    raw["ordinary_rules"][0]["prerequisites"] = [_leaf("明显下影")]
    changed = DailyTradePlan.model_validate(raw)
    result = assess_unbound_fact(changed, _fact(changed))
    assert result.reason == "AMBIGUOUS_DEFINITION"
    assert {r.condition_path for r in result.definitions} == {
        "volume_or_candle", "prerequisites[0]"}


@pytest.mark.parametrize("schema", [5, 6, 7, 8, 9])
def test_typed_current_schema_variants_share_the_actual_native_content_binding(schema):
    from tests.unit.test_market_exception_contract import exception_payload
    from tests.unit.test_market_linkage_contract import linked_payload
    from tests.unit.test_p2_policy_contract import p2_payload
    from tests.unit.test_p3_policy_contract import p3_payload

    raw = {5: unified_payload, 6: linked_payload, 7: exception_payload,
           8: p2_payload, 9: p3_payload}[schema]()
    raw["ordinary_rules"][0]["condition"] = _leaf()
    plan = load_plan_json(json.dumps(raw))
    before = plan.model_dump_json(), daily_plan_content_sha256(plan)
    assert assess_unbound_fact(plan, _fact(plan)).usable
    assert (plan.model_dump_json(), daily_plan_content_sha256(plan)) == before


def test_diagnostics_and_inputs_are_immutable_and_keep_actual_hashes():
    plan = _plan(_leaf(), _leaf())
    fact = _fact(plan)
    before = canonical(fact), plan.model_dump_json(), daily_plan_content_sha256(plan)
    result = assess_unbound_fact(plan, fact)
    assert isinstance(result.definitions, tuple)
    assert isinstance(result.definitions[0].observation_context, str)
    with pytest.raises(FrozenInstanceError):
        result.reason = "INVALID_FACT"
    with pytest.raises(FrozenInstanceError):
        result.definitions[0].owner_id = "foreign"
    filter_unbound_facts(plan, (fact,))
    assert before == (canonical(fact), plan.model_dump_json(), daily_plan_content_sha256(plan))
    assert not any(hasattr(result, name) for name in ("authority_granted", "hash", "version"))


def test_existing_native_fifty_leaf_bound_is_preserved():
    plan = _plan(*(_leaf() for _ in range(50)))
    result = assess_unbound_fact(plan, _fact(plan))
    assert result.usable and result.definition_count == 1 and len(result.definitions) == 50
    with pytest.raises(ValidationError, match="fifty"):
        _plan(*(_leaf() for _ in range(51)))


OWNER_VERSION = "actual-owner-version"


def _targets(plan, version=OWNER_VERSION):
    return list_reviewed_fact_targets(plan, plan_version_id=version,
                                     content_hash=daily_plan_content_sha256(plan))


def _resolve(plan, target, version=OWNER_VERSION):
    return resolve_reviewed_fact_target(plan, target, plan_version_id=version)


@pytest.mark.parametrize("second", [_leaf(), _leaf("明显下影"), _leaf(scope="SIGNAL")])
def test_explicit_target_keeps_each_actual_position_even_when_old_definitions_fold(second):
    plan = _plan(_leaf(), second)
    before = plan.model_dump_json(), daily_plan_content_sha256(plan)
    targets = _targets(plan)
    assert len(targets) == 2
    assert [t.condition_path for t in targets] == [
        "condition.conditions[0]", "condition.conditions[1]"]
    assert len({t.target_hash for t in targets}) == 2
    assert all(t.plan_version_id == OWNER_VERSION and t.version == "reviewed-fact-target-v1"
               and t.content_hash == before[1] for t in targets)
    refs = assess_unbound_fact(plan, _fact(plan, signal_id="existing")).definitions
    assert tuple(_resolve(plan, t) for t in targets) == refs
    assert before == (plan.model_dump_json(), daily_plan_content_sha256(plan))


def test_explicit_target_distinguishes_rules_with_the_same_complete_requirement():
    plan = _with_second_rule(_plan())
    targets = _targets(plan)
    assert {t.owner_id for t in targets} == {"low-buy", "sell-other"}
    assert len({t.target_hash for t in targets}) == 2
    assert assess_unbound_fact(plan, _fact(plan)).definition_count == 1


def test_explicit_target_reuses_confirmation_reset_alert_and_risk_catalog_contexts():
    raw = unified_payload()
    raw["ordinary_rules"][0]["condition"] = _leaf()
    raw["ordinary_rules"][0]["independent_signal"] = dict(
        mode="LATER_CLOSE_RESET_THEN_CONFIRM", reset_condition=_leaf())
    raw["alert_rules"] = [dict(kind="RISK_ALERT", rule_id="alert-own", condition=_leaf(),
                               confirmation={"kind": "OFFICIAL_DAILY_CLOSE"})]
    raw["risk_branches"][1]["rule_id"] = "actual-severe"
    plan = UnifiedTradePlan.model_validate(raw)
    targets = _targets(plan)
    assert len(targets) == 5
    refs = tuple(_resolve(plan, t) for t in targets)
    assert {json.loads(r.observation_context)["purpose"] for r in refs} == {
        "ORDINARY_CONFIRMATION", "RESET", "ALERT_CONFIRMATION", "RISK_CONFIRMATION"}
    assert {t.owner_kind for t in targets} == {"ORDINARY_RULE", "ALERT_RULE", "RISK_BRANCH"}
    assert {t.owner_id for t in targets if t.owner_kind == "RISK_BRANCH"} == {"actual-severe"}
    assert len({t.target_hash for t in targets}) == 5
    reset = next(t for t in targets if t.condition_path == "independent_signal.reset_condition")
    moved = {**reset.model_dump(), "condition_path": "condition"}
    with pytest.raises(ValueError):
        _resolve(plan, moved)


@pytest.mark.parametrize("changes", [
    {"plan_version_id": "active-sibling"}, {"content_hash": "0" * 64},
    {"owner_kind": "ALERT_RULE"}, {"owner_id": "sell-other"},
    {"condition_path": "condition.conditions[1]"}, {"target_hash": "0" * 64},
])
def test_explicit_target_rejects_a_changed_coordinate_with_the_original_hash(changes):
    plan = _with_second_rule(_plan(_leaf(), _leaf()))
    targets = _targets(plan)
    assert len(targets) == 4
    with pytest.raises(ValueError):
        _resolve(plan, {**targets[0].model_dump(), **changes})


@pytest.mark.parametrize("changes", [
    {"version": "other"}, {"owner_kind": "PLAN"}, {"owner_id": 1},
    {"condition_path": " condition.conditions[0]"}, {"target_hash": "A" * 64},
    {"authority_granted": True}, {"evidence": "volume already verified"},
])
def test_explicit_target_parser_is_closed_strict_and_never_uses_testimony(changes):
    plan = _plan()
    targets = _targets(plan)
    assert len(targets) == 1
    with pytest.raises(ValueError):
        _resolve(plan, {**targets[0].model_dump(), **changes})


@pytest.mark.parametrize("field", ["version", "plan_version_id", "content_hash", "target_hash"])
def test_explicit_target_parser_requires_the_complete_binding(field):
    plan = _plan()
    targets = _targets(plan)
    assert len(targets) == 1
    value = targets[0].model_dump()
    del value[field]
    with pytest.raises(ValueError):
        _resolve(plan, value)


def test_explicit_target_equal_content_does_not_identify_another_sql_owner_or_native_header():
    plan = _plan()
    targets = _targets(plan)
    assert len(targets) == 1
    target = targets[0]
    other = _targets(plan, "active-sibling")[0]
    assert other.content_hash == target.content_hash and other.target_hash != target.target_hash
    with pytest.raises(ValueError):
        _resolve(plan, target, "active-sibling")
    sibling = plan.model_copy(update={"version": plan.version + 1, "name": "Other owner"})
    assert daily_plan_content_sha256(sibling) == target.content_hash
    assert _targets(sibling)[0].target_hash != target.target_hash
    with pytest.raises(ValueError):
        _resolve(sibling, target)


@pytest.mark.parametrize("change", ["definition", "confirmation", "validity"])
def test_explicit_target_rejects_changed_definition_or_observation_context(change):
    plan = _plan()
    targets = _targets(plan)
    assert len(targets) == 1
    raw = plan.model_dump(mode="json")
    rule = raw["ordinary_rules"][0]
    if change == "definition":
        rule["condition"]["conditions"][0] = _leaf("明显下影")
    elif change == "confirmation":
        rule.update(confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
                    execution_window="CURRENT_SESSION")
    else:
        rule["validity"] = {"mode": "PLAN_ACTIVE"}
    changed = UnifiedTradePlan.model_validate(raw)
    with pytest.raises(ValueError):
        _resolve(changed, targets[0])


def test_explicit_target_schema4_keeps_native_roots_and_ignores_disabled_text():
    raw = synthetic_plan_payload()
    raw["ordinary_rules"][0]["prerequisites"] = [_leaf()]
    raw["ordinary_rules"][0]["independent_signal"] = dict(
        mode="LATER_CLOSE_RESET_THEN_CONFIRM", reset_condition=_leaf())
    plan = DailyTradePlan.model_validate(raw)
    targets = _targets(plan)
    assert {t.condition_path for t in targets} == {
        "price_structure", "volume_or_candle", "technical", "prerequisites[0]",
        "independent_signal.reset_condition"}
    assert all(t.owner_id == "low-buy" for t in targets)
    assert all(_resolve(plan, t).condition_path == t.condition_path for t in targets)


def test_explicit_target_is_immutable_bounded_and_does_not_become_a_verified_fact():
    plan = _plan(*(_leaf() for _ in range(50)))
    targets = _targets(plan)
    assert len(targets) == len({t.target_hash for t in targets}) == 50
    assert not any(hasattr(targets[0], key)
                   for key in ("verified", "satisfied", "authority_granted"))
    with pytest.raises(ValidationError):
        targets[0].owner_id = "foreign"


@pytest.mark.parametrize("version,content", [("", None), (1, None), ("actual", "0" * 64)])
def test_explicit_target_empty_catalog_still_validates_supplied_owner_binding(version, content):
    raw = _plan().model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"] = dict(
        type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=4000)
    plan = UnifiedTradePlan.model_validate(raw)
    assert _targets(plan) == ()
    with pytest.raises(ValueError):
        list_reviewed_fact_targets(plan, plan_version_id=version,
                                   content_hash=content or daily_plan_content_sha256(plan))


@pytest.mark.parametrize("schema", [5, 6, 7, 8, 9])
def test_explicit_target_current_schema_variants_resolve_the_existing_native_leaf(schema):
    from tests.unit.test_market_exception_contract import exception_payload
    from tests.unit.test_market_linkage_contract import linked_payload
    from tests.unit.test_p2_policy_contract import p2_payload
    from tests.unit.test_p3_policy_contract import p3_payload

    raw = {5: unified_payload, 6: linked_payload, 7: exception_payload,
           8: p2_payload, 9: p3_payload}[schema]()
    raw["ordinary_rules"][0]["condition"] = _leaf()
    plan = load_plan_json(json.dumps(raw))
    targets = _targets(plan)
    target = next(t for t in targets if t.owner_kind == "ORDINARY_RULE")
    ref = _resolve(plan, target)
    assert ref.definition_json == canonical(_leaf())
    assert ref.owner_id == raw["ordinary_rules"][0]["rule_id"]


@pytest.mark.parametrize("value", [None, [], "kind-only", 1])
def test_explicit_target_parser_rejects_nonselector_inputs(value):
    with pytest.raises(ValueError):
        _resolve(_plan(), value)


def test_explicit_target_revalidates_models_and_rejects_nonexistent_native_paths():
    plan = _plan()
    target = _targets(plan)[0]
    forged = type(target).model_construct(**{**target.model_dump(), "target_hash": "invalid"})
    with pytest.raises(ValueError):
        _resolve(plan, forged)
    for path in ("condition", "name", "condition.conditions[999]", "condition.conditions[-1]"):
        with pytest.raises(ValueError):
            _resolve(plan, {**target.model_dump(), "condition_path": path})


def test_explicit_target_independent_fixed_preimage_and_digest():
    # Independently specified literals, not an expected value from the target generator.
    payload = dict(
        version="reviewed-fact-target-v1", plan_version_id="actual-owner-version",
        content_hash="115602b028d5716a224f7583d49e5e38c017e25e5c6eb52440ec47fd5e114837",
        owner_kind="ORDINARY_RULE", owner_id="low-buy", condition_path="condition.conditions[0]",
        native_plan_hash="88f512a4259038c5e135e69649431600e1cab69444f3c6af114a6d5349fc235c",
        definition_json=(
            '{"evidence_requirement":"成交不异常放大","fact_kind":"VOLUME_OR_CANDLE",'
            '"type":"REVIEWED_FACT","validity_scope":"TRADE_DATE"}'),
        observation_context=(
            '{"confirmation":{"kind":"OFFICIAL_DAILY_CLOSE"},"purpose":"ORDINARY_CONFIRMATION",'
            '"validity":{"end_date":"2026-12-31","mode":"DATE_RANGE","start_date":"2026-09-01"}}'),
    )
    expected_hash = "8efad0ab16e6f026dbf7c5967ad00420a7b984aab8c865a748139a9beca88513"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    preimage = b"reviewed-fact-target-v1\x00" + encoded
    assert len(preimage) == 746 and sha256(preimage).hexdigest() == expected_hash
    assert daily_hash("reviewed-fact-target-v1", payload) == expected_hash
    plan = _plan()
    assert plan_sha256(plan) == payload["native_plan_hash"]
    assert daily_plan_content_sha256(plan) == payload["content_hash"]
    expected = {key: value for key, value in payload.items()
                if key not in {"native_plan_hash", "definition_json", "observation_context"}}
    expected["target_hash"] = expected_hash
    assert _targets(plan)[0].model_dump() == expected
    resolved = _resolve(plan, expected)
    assert resolved.definition_json == payload["definition_json"]
    assert resolved.observation_context == payload["observation_context"]
