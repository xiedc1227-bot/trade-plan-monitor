"""Pure native leaf matching; no SQL, source review or action authority."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter
from tests.unit.test_daily_conditions import synthetic_series
from tests.unit.test_reviewed_fact_targets import _fact, _leaf, _plan, _with_second_rule
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256
from trade_plan_monitor.domain.reviewed_fact_targets import list_reviewed_fact_targets
from trade_plan_monitor.domain.unified_plan_models import UnifiedCondition, UnifiedTradePlan

OWNER = "actual-owner-version"
NOW = datetime(2026, 9, 22, 16, 5, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture(scope="module")
def series():
    return synthetic_series(count=114)[0]


def _targeted(plan, *, owner_kind="ORDINARY_RULE", owner_id="low-buy",
              path="condition.conditions[0]", **changes):
    target = next(t for t in list_reviewed_fact_targets(plan, plan_version_id=OWNER,
                  content_hash=daily_plan_content_sha256(plan))
                  if (t.owner_kind, t.owner_id, t.condition_path) == (owner_kind, owner_id, path))
    return _fact(plan, plan_version_id=OWNER, signal_id="actual-signal",
                 available_at="2026-09-22T16:00:00+08:00",
                 verified_at="2026-09-22T16:00:00+08:00",
                 reviewed_fact_target=target.model_dump(), **changes)


def _evaluate(plan, facts, series, *, owner_kind="ORDINARY_RULE", owner_id="low-buy",
              path="condition", version=OWNER, condition=None, context=True,
              signal_id="actual-signal"):
    condition = plan.ordinary_rules[0].condition if condition is None else condition
    if isinstance(condition, dict):
        condition = TypeAdapter(UnifiedCondition).validate_python(condition)
    options = dict(facts=facts, target=NOW, signal_id=signal_id)
    if context:
        options.update(_fact_owner=(plan, version, owner_kind, owner_id), _condition_path=path)
    return evaluate_unified_condition(condition, series, **options)


@pytest.mark.parametrize("satisfied,expected", [(True, "SATISFIED"), (False, "UNSATISFIED")])
def test_exact_a_target_does_not_supply_or_negate_same_kind_same_definition_b(
    series, satisfied, expected,
):
    plan = _with_second_rule(_plan())
    fact = _targeted(plan, satisfied=satisfied)
    before = canonical(fact), plan.model_dump_json()
    a = _evaluate(plan, (fact,), series)
    b = _evaluate(plan, (fact,), series, owner_id="sell-other",
                  condition=plan.ordinary_rules[1].condition)
    assert a.outcome == expected and a.children[0].fact_ids == (fact["id"],)
    assert b.outcome == "MISSING_INPUT" and b.children[0].fact_ids == ()
    assert before == (canonical(fact), plan.model_dump_json())


def test_recursive_positions_latest_and_conflicts_are_target_local(series):
    plan = _plan(_leaf(), _leaf())
    first = _targeted(plan, id="a-yes")
    second = _targeted(plan, path="condition.conditions[1]", id="b-no", satisfied=False)
    second.update(available_at="2026-09-22T16:01:00+08:00")
    result = _evaluate(plan, (first, second), series)
    assert [c.outcome for c in result.children] == ["SATISFIED", "UNSATISFIED"]
    assert [c.fact_ids for c in result.children] == [("a-yes",), ("b-no",)]
    conflict = {**first, "id": "a-no", "satisfied": False}
    second["satisfied"] = True
    result = _evaluate(plan, (first, conflict, second), series)
    assert result.outcome == "MISSING_INPUT"
    assert [c.outcome for c in result.children] == ["MISSING_INPUT", "SATISFIED"]
    assert result.children[0].reason == "CONFLICTING_REVIEWED_FACT"
    assert result.children[1].fact_ids == ("b-no",)


def test_same_owner_nested_repeated_leaves_cannot_share_a_target(series):
    plan = _plan(dict(type="ANY", conditions=[_leaf(), _leaf()]))
    fact = _targeted(plan, path="condition.conditions[0].conditions[1]")
    result = _evaluate(plan, (fact,), series)
    assert result.outcome == "SATISFIED"
    assert [c.outcome for c in result.children[0].children] == ["MISSING_INPUT", "SATISFIED"]


def test_native_ordinary_alert_risk_and_reset_observations_are_distinct(series):
    raw = unified_payload()
    leaf = _leaf(kind="SEVERE_STRUCTURE")
    raw["ordinary_rules"][0]["condition"] = leaf
    raw["ordinary_rules"][0]["independent_signal"] = dict(
        mode="LATER_CLOSE_RESET_THEN_CONFIRM", reset_condition=leaf)
    raw["alert_rules"] = [dict(kind="RISK_ALERT", rule_id="actual-alert", condition=leaf,
                               confirmation={"kind": "OFFICIAL_DAILY_CLOSE"})]
    raw["risk_branches"][1].update(rule_id="actual-risk", condition=leaf)
    plan = UnifiedTradePlan.model_validate(raw)
    node = plan.ordinary_rules[0].condition
    owners = [("ORDINARY_RULE", "low-buy", "condition"),
              ("ORDINARY_RULE", "low-buy", "independent_signal.reset_condition"),
              ("ALERT_RULE", "actual-alert", "condition"),
              ("RISK_BRANCH", "actual-risk", "condition")]
    for selected in owners:
        fact = _targeted(plan, owner_kind=selected[0], owner_id=selected[1], path=selected[2],
                         kind="SEVERE_STRUCTURE")
        for current in owners:
            result = _evaluate(plan, (fact,), series, owner_kind=current[0],
                               owner_id=current[1], path=current[2], condition=node)
            assert result.outcome == ("SATISFIED" if selected == current else "MISSING_INPUT")


@pytest.mark.parametrize("change", [
    "owner", "version", "path", "header", "period", "scope", "definition", "kind",
    "hash", "content", "fact_owner",
])
def test_wrong_native_binding_definition_or_metadata_cannot_match(series, change):
    plan = _with_second_rule(_plan())
    fact = _targeted(plan)
    options = {}
    if change == "owner":
        options["owner_id"] = "sell-other"
    elif change == "version":
        options["version"] = "another-version"
    elif change == "path":
        options["path"] = "independent_signal.reset_condition"
    elif change == "header":
        plan = plan.model_copy(update={"version": plan.version + 1, "name": "Other native header"})
    elif change == "period":
        raw = plan.model_dump(mode="json")
        raw["ordinary_rules"][0].update(
            confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            execution_window="CURRENT_SESSION")
        plan = UnifiedTradePlan.model_validate(raw)
    elif change in {"scope", "definition"}:
        options["condition"] = _leaf(scope="SIGNAL") if change == "scope" else _leaf("明显下影")
        options["path"] = "condition.conditions[0]"
    elif change == "kind":
        fact["kind"] = "TECHNICAL"
    elif change == "hash":
        fact["reviewed_fact_target"]["target_hash"] = "0" * 64
    elif change == "content":
        fact["content_hash"] = "0" * 64
    else:
        fact["plan_version_id"] = "another-version"
    assert _evaluate(plan, (fact,), series, **options).outcome == "MISSING_INPUT"


@pytest.mark.parametrize("scope", ["TRADE_DATE", "SIGNAL"])
def test_date_and_signal_still_obey_original_matching_prerequisites(series, scope):
    plan = _plan(_leaf(scope=scope))
    fact = _targeted(plan)
    assert _evaluate(plan, (fact,), series).outcome == "SATISFIED"
    wrong = {**fact, "trade_date": "2026-09-21", "signal_id": "another-signal"}
    assert _evaluate(plan, (wrong,), series).outcome == "MISSING_INPUT"
    if scope == "SIGNAL":
        assert _evaluate(plan, (fact,), series, signal_id=None).outcome == "MISSING_INPUT"


@pytest.mark.parametrize("marker", [None, {}, False, "damaged"])
def test_damaged_target_never_falls_back_even_with_context(series, marker):
    plan = _plan()
    fact = {**_targeted(plan), "reviewed_fact_target": marker}
    assert _evaluate(plan, (fact,), series).outcome == "MISSING_INPUT"


def test_default_entry_keeps_isolation_and_context_does_not_enable_ambiguous_unbound(series):
    plan = _plan(_leaf(), _leaf("明显下影"))
    targeted = _targeted(plan)
    assert _evaluate(plan, (targeted,), series, context=False).outcome == "MISSING_INPUT"
    result = _evaluate(plan, (targeted,), series)
    assert [c.outcome for c in result.children] == ["SATISFIED", "MISSING_INPUT"]
    unbound = {key: value for key, value in targeted.items() if key != "reviewed_fact_target"}
    assert _evaluate(plan, (unbound,), series, context=False).outcome == "SATISFIED"
    assert _evaluate(plan, (unbound,), series).outcome == "MISSING_INPUT"


@pytest.mark.parametrize("mode,truth,expected", [
    ("ALL", True, "SATISFIED"), ("ALL", False, "UNSATISFIED"),
    ("ANY", True, "SATISFIED"), ("ANY", False, "SATISFIED"),
])
def test_original_three_valued_tree_and_independent_numeric_decision_remain(
    series, mode, truth, expected,
):
    numeric = dict(type="DAILY_PRICE_COMPARE", field="close", offset=0, comparator="GT",
                   reference=dict(mode="FIXED", value="0", unit="FEN", as_of="2026-09-22",
                                  source="Synthetic independent numeric condition"))
    raw = _plan(_leaf(), numeric).model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"]["type"] = mode
    plan = UnifiedTradePlan.model_validate(raw)
    fact = _targeted(plan, satisfied=truth)
    assert _evaluate(plan, (fact,), series).outcome == expected
    missing = _evaluate(plan, (), series)
    assert missing.outcome == ("MISSING_INPUT" if mode == "ALL" else "SATISFIED")
    assert [c.outcome for c in missing.children] == ["MISSING_INPUT", "SATISFIED"]


def test_bad_newer_target_cannot_hide_valid_target_and_unique_old_fact_still_works(series):
    plan = _plan()
    valid = _targeted(plan, id="valid-target")
    bad = {**valid, "id": "bad-newer", "satisfied": False,
           "available_at": "2026-09-22T16:04:00+08:00",
           "reviewed_fact_target": {**valid["reviewed_fact_target"], "target_hash": "0" * 64}}
    result = _evaluate(plan, (bad, valid), series)
    assert result.outcome == "SATISFIED" and result.children[0].fact_ids == ("valid-target",)
    old = {key: value for key, value in valid.items() if key != "reviewed_fact_target"}
    assert _evaluate(plan, (old,), series).outcome == "SATISFIED"


def test_existing_target_model_uses_the_same_resolution_as_json_fields(series):
    plan = _plan()
    fact = _targeted(plan)
    target = list_reviewed_fact_targets(
        plan, plan_version_id=OWNER, content_hash=daily_plan_content_sha256(plan))[0]
    fact["reviewed_fact_target"] = target
    assert _evaluate(plan, (fact,), series).outcome == "SATISFIED"
    fact["reviewed_fact_target"] = type(target).model_construct(
        **{**target.model_dump(), "target_hash": "damaged"})
    assert _evaluate(plan, (fact,), series).outcome == "MISSING_INPUT"
    fact["reviewed_fact_target"] = None
    assert _evaluate(plan, (fact,), series).outcome == "MISSING_INPUT"
