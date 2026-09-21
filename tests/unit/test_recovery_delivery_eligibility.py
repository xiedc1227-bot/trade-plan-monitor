"""Pure recovered risk delivery uses current evidence, never emission history alone."""

from datetime import timedelta
from uuid import UUID

import pytest
from test_explicit_rules import _bars, _inventory, _plan_with_rules, _rule

from trade_plan_monitor.decision.explicit_rules import (
    ExplicitEvaluationResult,
    ExplicitRuleStateSnapshot,
    evaluate_explicit_rules,
)
from trade_plan_monitor.decision.models import ConditionOutcome
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.notifications.identity import explicit_alert_event_id
from trade_plan_monitor.notifications.models import ExplicitAlertEvent, build_explicit_alert_payload
from trade_plan_monitor.notifications.recovery_eligibility import (
    ActiveExplicitPlan,
    RecoveryBarrierEvidence,
    RecoveryDeliveryStatus,
    classify_explicit_risk_delivery,
)
from trade_plan_monitor.notifications.render import render_explicit_alert

GENERATION = UUID("c2ed6b63-a01f-45c1-9c64-9c180c551fbc")
FIRST = _bars()[-1].bar_end
TARGET = FIRST + timedelta(minutes=5)
NOW = TARGET + timedelta(seconds=5)


def risk_plan(*, safety=False, trade=False):
    risk = _rule(
        "risk", condition={"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1000},
        action={"type": "RISK_ALERT"},
    )
    if safety:
        risk["safety_conditions"] = {"type": "MANUAL_EVENT_RISK_CLEAR"}
    rules = [risk]
    if trade:
        rules.append(_rule(
            "buy", condition={"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1000},
            action={"type": "BUY", "quantity": 100},
        ))
    return _plan_with_rules(*rules)


def evaluate(
    plan, *, target=TARGET, close=990, missing=False, manual=False, repeated=True,
    short_history=False,
):
    bars = tuple(
        bar.model_copy(update={"bar_end": bar.bar_end + (target - FIRST)})
        for bar in _bars(current_close=close)
    )
    return evaluate_explicit_rules(
        plan=plan, bars=() if missing else (bars[-1:] if short_history else bars),
        trading_calendar=(),
        target_bucket_end=target, evaluated_at=target + timedelta(seconds=2),
        activation_revision=1, inventory=_inventory(100), manual_event_risk=manual,
        rule_states=(
            ExplicitRuleStateSnapshot(
                rule_id="risk", activation_revision=1, revision=1,
                has_emitted=True, last_emitted_bucket_end=FIRST,
            ),
        ) if repeated else (),
    )


def event_for(plan):
    result = evaluate(plan, target=FIRST, repeated=False)
    signal = next(intent for intent in result.signal_intents if intent.action.type == "RISK_ALERT")
    payload = build_explicit_alert_payload(
        event_id=explicit_alert_event_id(signal), plan=plan, result=result, signal=signal,
    )
    return ExplicitAlertEvent(
        **payload.model_dump(mode="python"), sequence=1,
        message_text=render_explicit_alert(payload), created_at=result.evaluated_at,
    )


def inputs(
    *, safety=False, trade=False, close=990, missing=False, manual=False,
    plan=None, short_history=False,
):
    plan = plan if plan is not None else risk_plan(safety=safety, trade=trade)
    return dict(
        event=event_for(plan),
        active=ActiveExplicitPlan(
            plan=plan, activation_revision=1, activated_at=FIRST - timedelta(minutes=20),
            observed_at=NOW,
        ),
        latest=evaluate(
            plan, close=close, missing=missing, manual=manual, short_history=short_history,
        ),
        barrier=RecoveryBarrierEvidence(
            symbol=plan.symbol, plan_hash=plan_sha256(plan), activation_revision=1,
            runtime_generation=GENERATION, target_bucket_end=TARGET,
            reconciled_through=TARGET, pending_obligations=0, observed_at=NOW,
        ),
        target_bucket_end=TARGET, runtime_generation=GENERATION, now=NOW,
    )


@pytest.mark.parametrize(
    ("close", "missing", "expected"),
    [(990, False, "ELIGIBLE"), (1000, False, "SUPPRESS"), (990, True, "HOLD")],
)
def test_latest_risk_truth_controls_delivery_after_completed_barrier(close, missing, expected):
    arguments = inputs(close=close, missing=missing)
    decision = classify_explicit_risk_delivery(**arguments)
    assert decision.status.value == expected


def test_repeat_suppression_and_empty_intents_do_not_mean_recovered_risk():
    arguments = inputs()
    event_before = arguments["event"].model_dump_json()
    result_before = arguments["latest"].model_dump_json()
    assert arguments["latest"].signal_intents == ()
    assert arguments["latest"].rule_results[0].suppression_reason == "ONCE_ALREADY_EMITTED"
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.ELIGIBLE
    assert arguments["event"].model_dump_json() == event_before
    assert arguments["latest"].model_dump_json() == result_before


@pytest.mark.parametrize("manual", [True, None])
def test_safety_false_suppresses_and_safety_unknown_holds(manual):
    decision = classify_explicit_risk_delivery(**inputs(safety=True, manual=manual))
    assert decision.status.value == ("SUPPRESS" if manual is True else "HOLD")


def test_false_condition_with_unknown_safety_holds_without_terminal_suppression():
    decision = classify_explicit_risk_delivery(**inputs(safety=True, close=1000, manual=None))
    assert decision.status is RecoveryDeliveryStatus.HOLD


@pytest.mark.parametrize("barrier_change", [
    {"pending_obligations": 1}, {"reconciled_through": FIRST},
    {"reconciled_through": None}, {"target_bucket_end": FIRST},
    {"runtime_generation": UUID(int=1)}, {"activation_revision": 2},
    {"plan_hash": "0" * 64}, {"symbol": "600000.SH"},
    {"observed_at": NOW + timedelta(seconds=1)},
])
def test_barrier_must_prove_same_generation_activation_and_completed_current_target(barrier_change):
    arguments = inputs()
    payload = arguments["barrier"].model_dump(mode="python") | barrier_change
    arguments["barrier"] = RecoveryBarrierEvidence.model_validate(payload)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


@pytest.mark.parametrize("missing", ["barrier", "latest"])
def test_missing_current_evidence_holds(missing):
    arguments = inputs()
    arguments[missing] = None
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


@pytest.mark.parametrize("change", [
    {"activation_revision": 2}, {"activated_at": FIRST + timedelta(seconds=1)},
])
def test_actual_activation_change_suppresses_old_alert(change):
    arguments = inputs()
    arguments["active"] = ActiveExplicitPlan.model_validate(
        arguments["active"].model_dump(mode="python") | change,
    )
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.SUPPRESS


def test_authoritatively_absent_active_plan_suppresses_old_alert():
    arguments = inputs()
    arguments["active"] = None
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.SUPPRESS


@pytest.mark.parametrize("target", [FIRST, TARGET + timedelta(minutes=5)])
def test_wrong_or_future_latest_target_cannot_satisfy_current_request(target):
    arguments = inputs()
    arguments["latest"] = evaluate(arguments["active"].plan, target=target)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


def test_known_true_risk_remains_valid_when_it_blocks_a_different_trade_rule():
    arguments = inputs(trade=True)
    assert "RISK_RULE_CONFLICT" in arguments["latest"].rule_results[1].blockers
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.ELIGIBLE


@pytest.mark.parametrize("blocker", ["CONFLICT_INPUT_UNKNOWN", "PLAN_INACTIVE", "UNKNOWN_CODE"])
def test_unexpected_blockers_on_selected_risk_cannot_invent_eligibility(blocker):
    arguments = inputs()
    payload = arguments["latest"].model_dump(mode="python", exclude={"result_hash"})
    payload["rule_results"][0]["blockers"] = (blocker,)
    arguments["latest"] = ExplicitEvaluationResult.build(**payload)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


@pytest.mark.parametrize("change", [
    {"activation_revision": 2}, {"plan_hash": "0" * 64}, {"symbol": "600000.SH"},
    {"evaluated_at": NOW + timedelta(seconds=1)},
])
def test_latest_result_identity_and_clock_must_match_current_evidence(change):
    arguments = inputs()
    payload = arguments["latest"].model_dump(mode="python", exclude={"result_hash"}) | change
    arguments["latest"] = ExplicitEvaluationResult.build(**payload)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


@pytest.mark.parametrize("mutation", ["rule", "action", "condition", "future-bar"])
def test_current_rule_action_and_source_evidence_are_fenced(mutation):
    arguments = inputs()
    payload = arguments["latest"].model_dump(mode="python", exclude={"result_hash"})
    rule = payload["rule_results"][0]
    if mutation == "rule":
        rule["rule_id"] = "different-rule"
    elif mutation == "action":
        rule["action"] = {"type": "BUY", "quantity": 100}
    elif mutation == "condition":
        rule["condition_evidence"]["condition"]["price_fen"] = 1001
    else:
        rule["condition_evidence"]["bar_ends"] = (TARGET + timedelta(minutes=5),)
    arguments["latest"] = ExplicitEvaluationResult.build(**payload)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


def test_expired_explicit_activation_does_not_inherit_legacy_cross_day_exception():
    arguments = inputs()
    arguments["now"] = NOW + timedelta(days=1)
    decision = classify_explicit_risk_delivery(**arguments)
    assert decision.status is RecoveryDeliveryStatus.SUPPRESS
    assert decision.reason.value == "ACTIVATION_EXPIRED"


def test_clock_reversal_holds_an_otherwise_known_true_risk():
    arguments = inputs()
    arguments["now"] = NOW - timedelta(seconds=1)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


def test_result_committed_after_barrier_observation_requires_new_barrier_evidence():
    arguments = inputs()
    barrier = arguments["barrier"].model_dump(mode="python")
    barrier["observed_at"] = TARGET + timedelta(seconds=1)
    arguments["barrier"] = RecoveryBarrierEvidence.model_validate(barrier)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


def test_risk_true_has_no_blanket_ninety_second_expiry():
    arguments = inputs()
    arguments["now"] = NOW + timedelta(hours=1)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.ELIGIBLE


@pytest.mark.parametrize("value", [TARGET + timedelta(seconds=1), TARGET.replace(tzinfo=None)])
def test_invalid_requested_cutoff_is_not_silently_normalized(value):
    arguments = inputs()
    arguments["target_bucket_end"] = value
    with pytest.raises(ValueError):
        classify_explicit_risk_delivery(**arguments)


def test_future_requested_target_holds_even_if_latest_result_is_known_true():
    arguments = inputs()
    arguments["target_bucket_end"] = TARGET + timedelta(minutes=5)
    assert classify_explicit_risk_delivery(**arguments).status is RecoveryDeliveryStatus.HOLD


@pytest.mark.parametrize("rule_id", ["missing-risk-rule", "buy"])
@pytest.mark.parametrize("has_barrier", [True, False])
def test_original_event_with_invalid_active_rule_is_terminal_before_barrier(rule_id, has_barrier):
    arguments = inputs(trade=True)
    plan = arguments["active"].plan
    source = evaluate(plan, target=FIRST, repeated=False)
    payload = source.model_dump(mode="python", exclude={"result_hash"})
    risk = payload["rule_results"][0]
    risk["rule_id"] = rule_id
    risk["state_transition"]["rule_id"] = rule_id
    payload["rule_results"] = (risk,)
    payload["signal_intents"][0]["rule_id"] = rule_id
    source = ExplicitEvaluationResult.build(**payload)
    signal = source.signal_intents[0]
    alert_payload = build_explicit_alert_payload(
        event_id=explicit_alert_event_id(signal), plan=plan, result=source, signal=signal,
    )
    # Ordinary model validation intentionally does not prove membership in active plan.rules.
    arguments["event"] = ExplicitAlertEvent.model_validate({
        **alert_payload.model_dump(mode="python"), "sequence": 1,
        "message_text": render_explicit_alert(alert_payload), "created_at": source.evaluated_at,
    })
    if not has_barrier:
        arguments["barrier"] = None
    decision = classify_explicit_risk_delivery(**arguments)
    assert decision.status is RecoveryDeliveryStatus.SUPPRESS
    assert decision.reason.value == "ACTIVE_IDENTITY_INVALID"


@pytest.mark.parametrize(
    ("operator", "close", "outcome", "expected"),
    [
        ("ANY", 990, ConditionOutcome.SATISFIED, "ELIGIBLE"),
        ("ALL", 1000, ConditionOutcome.UNSATISFIED, "SUPPRESS"),
        ("ALL", 990, ConditionOutcome.MISSING_INPUT, "HOLD"),
        ("ANY", 1000, ConditionOutcome.MISSING_INPUT, "HOLD"),
    ],
)
def test_composite_uses_committed_root_truth_without_reinterpreting_unknown_children(
    operator, close, outcome, expected,
):
    plan = _plan_with_rules(_rule(
        "risk",
        condition={
            "type": operator,
            "conditions": [
                {"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1000},
                {
                    "type": "VOLUME_TO_MEAN_GTE", "window_bars": 5,
                    "minimum_ratio": "1", "history_scope": "CONTIGUOUS_TRADING_BARS",
                },
            ],
        },
        action={"type": "RISK_ALERT"},
    ))
    arguments = inputs(plan=plan, close=close, short_history=True)
    root = arguments["latest"].rule_results[0].condition_evidence
    assert root.outcome is outcome
    assert root.children[1].outcome is ConditionOutcome.MISSING_INPUT
    assert classify_explicit_risk_delivery(**arguments).status.value == expected
