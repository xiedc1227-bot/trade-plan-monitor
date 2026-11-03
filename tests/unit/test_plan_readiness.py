"""Literal readiness expectations, independent of trading predicate truth."""

from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

NOW = datetime(2026, 11, 2, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
AXES = (
    "SOURCE_COVERAGE", "REVIEW_ACTIVATION", "RUNTIME_OWNERSHIP",
    "DATA_EVALUATION", "INVENTORY_CAPITAL", "NOTIFICATION_DELIVERY",
)


def context():
    from trade_plan_monitor.web.plan_readiness_models import ReadinessContext

    return ReadinessContext(
        plan_version_id=UUID("41699c9c-8c65-4ab8-9740-20efdd45e3d9"),
        content_hash="a" * 64, source_hash="b" * 64, coverage_hash="c" * 64,
        review_receipt_hash="d" * 64, activation_revision=7,
        runtime_generation=UUID("b2f55d82-8d98-4c5e-a3bc-18529f84e982"),
        inventory_revision=1,
    )


def observation(**changes):
    from trade_plan_monitor.web.plan_readiness_models import ReadinessObservation

    value = dict(context=context(), availability="CURRENT", observed_at=NOW,
                 as_of=NOW - timedelta(minutes=5), expires_at=NOW + timedelta(seconds=30),
                 evidence_refs=("evaluation-actual-1",))
    value.update(changes)
    return ReadinessObservation(**value)


def leaf(path="condition", state="CONDITION_FALSE", reason=None):
    from trade_plan_monitor.web.plan_readiness_models import ConditionReadiness

    return ConditionReadiness(condition_path=path, state=state, reason=reason,
                              evidence_refs=("bar-actual-1",) if reason is None else ())


def rule(**changes):
    from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget
    from trade_plan_monitor.web.plan_readiness_models import (
        InventoryRequirements,
        RuleReadinessFacts,
    )

    target = OfficialCloseEvaluationTarget(trade_date=date(2026, 10, 30))
    value = dict(owner_kind="ORDINARY_RULE", owner_id="buy-1", side="BUY",
                 requirements=InventoryRequirements(inventory=True),
                 expected_target=target, evaluated_target=target,
                 evaluated_at=NOW - timedelta(minutes=1), observation=observation(),
                 root_outcome="UNSATISFIED", leaves=(leaf(),))
    value.update(changes)
    return RuleReadinessFacts(**value)


def snapshot(*, rules=None, replacements=None, **changes):
    from trade_plan_monitor.web.plan_readiness_models import AxisReadiness, ReadinessSnapshot

    replacements = replacements or {}
    axes = tuple(AxisReadiness(axis=name, state="PASS", observation=observation())
                 if name not in replacements else replacements[name] for name in AXES)
    value = dict(computed_at=NOW, context=context(), scope="TRADE_RULES", axes=axes,
                 rules=(rule(),) if rules is None else rules)
    value.update(changes)
    return ReadinessSnapshot(**value)


def assess(value):
    from trade_plan_monitor.web.plan_readiness_summary import summarize_readiness

    return summarize_readiness(value)


def test_complete_current_false_is_healthy_and_never_grants_authority():
    result = assess(snapshot())
    assert result.summary == "READY_FOR_MONITORING"
    assert result.rules[0].state == "CONDITION_FALSE"
    assert result.rules[0].facts.root_outcome == "UNSATISFIED"
    assert result.authority_granted is False
    assert result.model_dump(mode="json", by_alias=True)["authorityGranted"] is False
    assert result.fresh_until == NOW + timedelta(seconds=30)


def test_all_false_cannot_hide_a_missing_leaf():
    result = assess(snapshot(rules=(rule(leaves=(
        leaf("condition.conditions[0]"),
        leaf("condition.conditions[1]", "MISSING_INPUT", "MISSING_DATA"),
    )),)))
    assert result.summary == "BLOCKED"
    assert result.rules[0].state == "MISSING_INPUT"
    assert result.rules[0].facts.root_outcome == "UNSATISFIED"
    assert result.rules[0].facts.leaves[1].reason == "MISSING_DATA"


def test_first_evaluation_is_not_false_or_ready():
    result = assess(snapshot(rules=(rule(evaluated_at=None, evaluated_target=None,
                                      root_outcome=None, observation=None, leaves=()),)))
    assert result.summary == "UNKNOWN"
    assert result.rules[0].state == "AWAITING_FIRST_EVALUATION"


def test_every_axis_must_be_present_exactly_once():
    valid = snapshot()
    with pytest.raises(ValidationError):
        valid.model_copy(update={"axes": valid.axes[:-1]})
    with pytest.raises(ValidationError):
        valid.model_copy(update={"axes": (*valid.axes[:-1], valid.axes[0])})


def axis(name, state, reason=None, **changes):
    from trade_plan_monitor.web.plan_readiness_models import AxisReadiness

    return AxisReadiness(axis=name, state=state, reason=reason,
                         observation=observation(**changes))


def waiting_rule(**changes):
    from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget
    from trade_plan_monitor.web.plan_readiness_models import ExpectedConfirmation

    target = OfficialCloseEvaluationTarget(trade_date=NOW.date())
    values = dict(target=target, expected_at=NOW.replace(hour=15),
                  calendar_reference="calendar-owned-1", prior_inputs_complete=True,
                  observation=observation(calendar_reference="calendar-owned-1"))
    values.update(changes)
    return rule(expected_target=target, evaluated_target=None, evaluated_at=None,
                root_outcome=None, observation=None, leaves=(),
                expected_confirmation=ExpectedConfirmation(**values))


def test_future_owned_wait_retains_nonempty_expected_leaves_and_prior_root():
    value = waiting_rule().model_copy(update={
        "root_outcome": "UNSATISFIED",
        "leaves": (leaf("condition.conditions[0]", "UNKNOWN", "EXPECTED_CONFIRMATION"),
                   leaf("condition.conditions[1]", "CONDITION_FALSE")),
    })
    result = assess(snapshot(rules=(value,)))
    assert result.rules[0].state == "WAITING_OFFICIAL_CONFIRMATION"
    assert result.summary == "WAITING_EXPECTED_CONFIRMATION"
    assert result.rules[0].facts.leaves == value.leaves
    assert result.rules[0].facts.root_outcome == "UNSATISFIED"


@pytest.mark.parametrize("state,reason", [
    ("UNKNOWN", "DEPENDENCY_UNVERIFIED"),
    ("MISSING_INPUT", "MISSING_DATA"),
    ("MISSING_INPUT", "HUMAN_EVIDENCE_REQUIRED"),
    ("BLOCKED", "UNDEFINED_RULE"),
])
def test_future_wait_never_hides_another_incomplete_native_leaf(state, reason):
    value = waiting_rule().model_copy(update={"leaves": (
        leaf("condition.conditions[0]", "UNKNOWN", "EXPECTED_CONFIRMATION"),
        leaf("condition.conditions[1]", state, reason),
    )})
    result = assess(snapshot(rules=(value,)))
    assert result.rules[0].state == state
    assert result.rules[0].reason == reason
    assert len(result.rules[0].facts.leaves) == 2


@pytest.mark.parametrize("change", ["past", "target", "calendar", "prior", "owner", "event-time"])
def test_expected_unknown_leaf_needs_the_entire_future_owned_wait(change):
    wait = waiting_rule().expected_confirmation
    replacements = {}
    if change == "past":
        wait = wait.model_copy(update={"expected_at": NOW})
    elif change == "target":
        wait = wait.model_copy(update={"target": rule().evaluated_target})
    elif change == "calendar":
        wait = wait.model_copy(update={"calendar_reference": "different-calendar"})
    elif change == "prior":
        wait = wait.model_copy(update={"prior_inputs_complete": False})
    elif change == "event-time":
        wait = wait.model_copy(update={"expected_at": NOW + timedelta(minutes=30)})
    else:
        replacements["RUNTIME_OWNERSHIP"] = axis(
            "RUNTIME_OWNERSHIP", "UNKNOWN", "AUTHORITY_UNAVAILABLE")
    value = waiting_rule().model_copy(update={"expected_confirmation": wait, "leaves": (
        leaf(state="UNKNOWN", reason="EXPECTED_CONFIRMATION"),)})
    result = assess(snapshot(rules=(value,), replacements=replacements))
    assert result.rules[0].state == "UNKNOWN"
    assert result.summary == "UNKNOWN"


@pytest.mark.parametrize("leaves", ["empty", "known", "expected"])
def test_wrong_event_time_never_becomes_wait_even_without_unknown_leaves(leaves):
    values = {"empty": (), "known": (leaf(),),
              "expected": (leaf(state="UNKNOWN", reason="EXPECTED_CONFIRMATION"),)}
    value = waiting_rule(expected_at=NOW + timedelta(minutes=30)).model_copy(
        update={"leaves": values[leaves]})
    result = assess(snapshot(rules=(value,)))
    assert result.rules[0].state == "UNKNOWN"
    assert result.summary == "UNKNOWN"


@pytest.mark.parametrize("state,reason,expected", [
    ("UNKNOWN", "DEPENDENCY_UNVERIFIED", "AWAITING_FIRST_EVALUATION"),
    ("UNKNOWN", "AUTHORITY_UNAVAILABLE", "UNKNOWN"),
    ("MISSING_INPUT", "HUMAN_EVIDENCE_REQUIRED", "MISSING_INPUT"),
    ("MISSING_INPUT", "MISSING_DATA", "MISSING_INPUT"),
    ("BLOCKED", "UNDEFINED_RULE", "BLOCKED"),
])
def test_first_evaluation_preserves_all_native_leaves_and_real_failure_priority(
    state, reason, expected,
):
    value = rule(evaluated_at=None, evaluated_target=None, root_outcome=None, observation=None,
                 leaves=(leaf("condition.conditions[0]", state, reason),))
    result = assess(snapshot(rules=(value,)))
    assert result.rules[0].state == expected
    assert result.rules[0].facts.leaves == value.leaves


@pytest.mark.parametrize("quote_present", [True, False])
def test_rule_expiry_keeps_unrelated_buy_quote_out_of_sell(quote_present):
    from trade_plan_monitor.decision.models import IntradayEvaluationTarget
    from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
    from trade_plan_monitor.web.plan_readiness_service import _rule_expiry

    quote = DailyExecutionQuote(symbol="003043.SZ", price_fen=990,
        quote_at=NOW - timedelta(minutes=4, seconds=55), available_at=NOW,
        evaluated_at=NOW, tradable=True, special_state_verified=True, liquidity_available=True)
    inputs = dict(context_expiry=NOW + timedelta(seconds=20),
        target=IntradayEvaluationTarget(bucket_end=NOW.replace(minute=0)),
        daily_event=None, daily_required=False, quote=quote if quote_present else None)
    assert _rule_expiry(NOW, **inputs, quote_required=False) == NOW + timedelta(seconds=20)
    assert _rule_expiry(NOW, **inputs, quote_required=True) == (
        NOW + timedelta(seconds=5) if quote_present else None)
    if quote_present:
        assert _rule_expiry(NOW + timedelta(seconds=1), **inputs, quote_required=True) == (
            NOW + timedelta(seconds=5))


@pytest.mark.parametrize("root,complete", [
    ("SATISFIED", "CONDITION_TRUE"), ("UNSATISFIED", "CONDITION_FALSE"),
])
def test_decisive_root_never_hides_required_human_evidence(root, complete):
    result = assess(snapshot(rules=(rule(root_outcome=root, leaves=(
        leaf("condition.conditions[0]", complete),
        leaf("condition.conditions[1]", "MISSING_INPUT", "HUMAN_EVIDENCE_REQUIRED"),
    )),)))
    assert result.summary == "BLOCKED"
    assert result.rules[0].reason == "HUMAN_EVIDENCE_REQUIRED"
    assert result.rules[0].facts.root_outcome == root
    assert len(result.rules[0].facts.leaves) == 2


@pytest.mark.parametrize("state,reason", [
    ("MISSING_INPUT", "MISSING_DATA"), ("MISSING_INPUT", "STALE_DATA"),
    ("MISSING_INPUT", "HUMAN_EVIDENCE_REQUIRED"), ("BLOCKED", "UNDEFINED_RULE"),
])
def test_missing_data_undefined_rule_and_required_human_evidence_remain_distinct(state, reason):
    result = assess(snapshot(rules=(rule(leaves=(leaf(state=state, reason=reason),)),)))
    assert result.summary == "BLOCKED"
    assert result.rules[0].state == state
    assert result.rules[0].reason == reason


@pytest.mark.parametrize("availability", ["CACHED", "UNAVAILABLE", "PERSISTED_ONLY"])
def test_noncurrent_observations_never_certify_runtime_or_false(availability):
    result = assess(snapshot(rules=(rule(observation=observation(availability=availability)),)))
    assert result.summary == "UNKNOWN"
    assert result.rules[0].state == "UNKNOWN"
    assert result.rules[0].reason == "AUTHORITY_UNAVAILABLE"
    assert result.fresh_until is None


@pytest.mark.parametrize("field,value", [
    ("activation_revision", 8),
    ("runtime_generation", UUID("a2f55d82-8d98-4c5e-a3bc-18529f84e982")),
    ("source_hash", "e" * 64), ("coverage_hash", "e" * 64),
    ("review_receipt_hash", "e" * 64),
])
def test_different_admitted_context_never_joins_old_evaluation(field, value):
    observed = observation(context=context().model_copy(update={field: value}))
    result = assess(snapshot(rules=(rule(observation=observed),)))
    assert result.summary == "UNKNOWN"
    assert result.rules[0].reason == "CONTEXT_CHANGED"


@pytest.mark.parametrize("expires", [NOW, NOW - timedelta(seconds=1)])
def test_existing_expiry_is_exclusive_and_not_renewed(expires):
    result = assess(snapshot(rules=(rule(observation=observation(expires_at=expires)),)))
    assert result.summary == "UNKNOWN"
    assert result.rules[0].reason == "EVIDENCE_EXPIRED"
    assert result.fresh_until is None


def test_first_target_and_existing_expiries_do_not_use_a_new_uniform_ttl():
    value = rule(observation=observation(expires_at=NOW + timedelta(seconds=7)))
    assert assess(snapshot(rules=(value,))).fresh_until == NOW + timedelta(seconds=7)
    timeless = value.model_copy(update={"observation": observation(expires_at=None)})
    assert assess(snapshot(rules=(timeless,))).fresh_until is None
    old = timeless.model_copy(update={"observation": observation(
        expires_at=None, observed_at=NOW - timedelta(seconds=1))})
    assert assess(snapshot(rules=(old,))).summary == "UNKNOWN"


def test_wrong_target_cannot_be_reported_as_complete_false():
    from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget

    other = OfficialCloseEvaluationTarget(trade_date=date(2026, 10, 29))
    result = assess(snapshot(rules=(rule(evaluated_target=other),)))
    assert result.summary == "UNKNOWN"
    assert result.rules[0].reason == "TARGET_MISMATCH"


def test_owned_future_official_close_is_expected_waiting():
    result = assess(snapshot(rules=(waiting_rule(),)))
    assert result.summary == "WAITING_EXPECTED_CONFIRMATION"
    assert result.rules[0].state == "WAITING_OFFICIAL_CONFIRMATION"
    assert result.rules[0].facts.evaluated_at is None


@pytest.mark.parametrize("mutation,expected,reason", [
    ("prior_missing", "BLOCKED", "MISSING_DATA"),
    ("due", "UNKNOWN", "AUTHORITY_UNAVAILABLE"),
    ("calendar_mismatch", "UNKNOWN", "AUTHORITY_UNAVAILABLE"),
    ("old_owner", "UNKNOWN", "AUTHORITY_UNAVAILABLE"),
    ("wrong_target", "UNKNOWN", "TARGET_MISMATCH"),
])
def test_expected_wait_requires_current_owner_calendar_target_and_previous_inputs(
    mutation, expected, reason,
):
    from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget

    changes, replacements = {}, {}
    if mutation == "prior_missing":
        changes["prior_inputs_complete"] = False
    elif mutation == "due":
        changes["expected_at"] = NOW
    elif mutation == "calendar_mismatch":
        changes["calendar_reference"] = "different-calendar"
    elif mutation == "old_owner":
        replacements["RUNTIME_OWNERSHIP"] = axis(
            "RUNTIME_OWNERSHIP", "UNKNOWN", "AUTHORITY_UNAVAILABLE")
    else:
        changes["target"] = OfficialCloseEvaluationTarget(trade_date=date(2026, 10, 30))
    value = waiting_rule(**changes)
    if mutation == "wrong_target":
        value = value.model_copy(update={"expected_target": waiting_rule().expected_target})
    result = assess(snapshot(rules=(value,), replacements=replacements))
    assert result.summary == expected
    assert result.rules[0].reason == reason


@pytest.mark.parametrize("blocked,review,unknown,service,waiting,expected", [
    (True, True, True, True, True, "BLOCKED"),
    (False, True, True, True, True, "NEEDS_REVIEW"),
    (False, False, True, True, True, "UNKNOWN"),
    (False, False, False, True, True, "WAITING_REQUIRED_SERVICE"),
    (False, False, False, False, True, "WAITING_EXPECTED_CONFIRMATION"),
    (False, False, False, False, False, "READY_FOR_MONITORING"),
])
def test_summary_precedence_uses_all_axes(blocked, review, unknown, service, waiting, expected):
    replacements = {}
    if blocked:
        replacements["INVENTORY_CAPITAL"] = axis(
            "INVENTORY_CAPITAL", "BLOCKED", "CONFIGURATION_BLOCKED")
    if review:
        replacements["SOURCE_COVERAGE"] = axis(
            "SOURCE_COVERAGE", "BLOCKED", "SOURCE_REVIEW_REQUIRED")
    if unknown:
        replacements["RUNTIME_OWNERSHIP"] = axis(
            "RUNTIME_OWNERSHIP", "UNKNOWN", "AUTHORITY_UNAVAILABLE")
    if service:
        replacements["NOTIFICATION_DELIVERY"] = axis(
            "NOTIFICATION_DELIVERY", "WAIT", "SERVICE_PENDING")
    result = assess(snapshot(rules=(waiting_rule() if waiting else rule(),),
                             replacements=replacements))
    assert result.summary == expected
    assert len(result.axes) == 6
    assert result.authority_granted is False


def test_broad_wait_axis_without_owned_calendar_evidence_is_unknown():
    result = assess(snapshot(replacements={"DATA_EVALUATION": axis(
        "DATA_EVALUATION", "WAIT", "EXPECTED_CONFIRMATION")}))
    assert result.summary == "UNKNOWN"


def test_execution_ineligibility_does_not_change_monitor_health_or_quantity():
    from trade_plan_monitor.web.plan_readiness_models import ReadinessExecutionState

    execution = ReadinessExecutionState(approved_quantity=700, consumed=True,
                                       execution_window="NEXT_EXCHANGE_SESSION_ONLY",
                                       window_state="CLOSED", eligible=False,
                                       reason="WHOLE_QUANTITY_CAP_EXCEEDED")
    result = assess(snapshot(rules=(rule(execution=execution),)))
    assert result.summary == "READY_FOR_MONITORING"
    assert result.rules[0].facts.execution == execution
    assert result.rules[0].facts.execution.approved_quantity == 700


def test_buy_missing_evidence_preserves_independent_original_risk_sell():
    buy = rule(leaves=(leaf(state="MISSING_INPUT", reason="HUMAN_EVIDENCE_REQUIRED"),))
    sell = rule(owner_kind="RISK_BRANCH", owner_id="original-risk", side="SELL")
    result = assess(snapshot(rules=(buy, sell), replacements={"INVENTORY_CAPITAL": axis(
        "INVENTORY_CAPITAL", "BLOCKED", "MISSING_DATA")}))
    assert result.summary == "BLOCKED"
    assert result.rules[0].state == "MISSING_INPUT"
    assert result.rules[1].state == "CONDITION_FALSE"
    assert result.rules[1].facts.owner_id == "original-risk"


def test_unrelated_buy_book_revision_does_not_stale_a_sell_observation():
    sell = rule(owner_kind="RISK_BRANCH", owner_id="original-risk", side="SELL",
                observation=observation(context=context().model_copy(update={"book_revision": 1})))
    result = assess(snapshot(rules=(sell,)))
    assert result.rules[0].state == "CONDITION_FALSE"
    assert result.summary == "READY_FOR_MONITORING"


@pytest.mark.parametrize("mode,cost,fees", [
    ("MARKET_VALUE_CAP", False, False), ("OPEN_COST_CAP", True, True),
])
def test_money_dependencies_come_from_exact_native_policy(mode, cost, fees):
    from tests.unit.test_p3_policy_contract import p3_payload

    from trade_plan_monitor.domain.p3_policy_models import P3TradePlan
    from trade_plan_monitor.domain.risk_scope import risk_identity
    from trade_plan_monitor.web.plan_readiness_summary import inventory_requirements

    plan = P3TradePlan.model_validate(p3_payload(mode))
    buy = next(rule for rule in plan.ordinary_rules if rule.side == "BUY")
    required = inventory_requirements(plan, owner_kind="ORDINARY_RULE", owner_id=buy.rule_id)
    assert required.inventory and required.quote and required.simulation_book
    assert required.cost_basis is cost
    assert required.fees is fees
    assert required.economics is False
    risk = inventory_requirements(plan, owner_kind="RISK_BRANCH",
                                  owner_id=risk_identity(plan.risk_branches[0]))
    assert risk.inventory and risk.sellability
    assert not risk.cost_basis and not risk.simulation_book


def test_alert_only_has_no_inventory_book_or_cost_dependency():
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.web.plan_readiness_summary import inventory_requirements

    raw = unified_payload()
    original = raw["ordinary_rules"][0]
    raw.update(ordinary_rules=[], risk_branches=[], alert_rules=[dict(
        kind="RISK_ALERT", rule_id="alert-1", condition=original["condition"],
        confirmation=original["confirmation"])])
    plan = UnifiedTradePlan.model_validate(raw)
    required = inventory_requirements(plan, owner_kind="ALERT_RULE", owner_id="alert-1")
    assert not required.required
    alert = rule(owner_kind="ALERT_RULE", owner_id="alert-1", side=None, requirements=required)
    result = assess(snapshot(scope="ALERT_ONLY", rules=(alert,), replacements={
        "INVENTORY_CAPITAL": axis("INVENTORY_CAPITAL", "BLOCKED", "MISSING_DATA")}))
    assert result.summary == "READY_FOR_MONITORING"
    assert next(item for item in result.axes if item.axis == "INVENTORY_CAPITAL").state == (
        "NOT_APPLICABLE")
    with pytest.raises(ValueError, match="actual native rule"):
        inventory_requirements(plan, owner_kind="ORDINARY_RULE", owner_id="alert-1")


def test_alert_only_cannot_omit_required_notification_axis():
    from trade_plan_monitor.web.plan_readiness_models import (
        AxisReadiness,
        InventoryRequirements,
    )

    alert = rule(owner_kind="ALERT_RULE", owner_id="alert-1", side=None,
                 requirements=InventoryRequirements())
    with pytest.raises(ValidationError):
        snapshot(scope="ALERT_ONLY", rules=(alert,), replacements={
            "NOTIFICATION_DELIVERY": AxisReadiness(
                axis="NOTIFICATION_DELIVERY", state="NOT_APPLICABLE"),
        })


def test_models_are_closed_frozen_strict_and_false_is_literal():
    value = snapshot()
    with pytest.raises(ValidationError):
        value.computed_at = NOW
    with pytest.raises(ValidationError):
        value.model_copy(update={"scope": "FULL_TRADING"})
    with pytest.raises(ValidationError):
        value.axes[0].model_copy(update={"state": "READY"})
    with pytest.raises(ValidationError):
        value.context.model_copy(update={"activation_revision": True})
    with pytest.raises(ValidationError):
        value.model_copy(update={"new_worker": True})
    result = assess(value)
    for invalid in (True, 0, "false"):
        with pytest.raises(ValidationError):
            result.model_copy(update={"authority_granted": invalid})


def test_readiness_is_deterministic_and_leaves_inputs_unchanged():
    value = snapshot()
    before = value.model_dump_json()
    first = assess(value)
    assert assess(value) == first
    assert value.model_dump_json() == before
    assert first.snapshot is value
