"""Risk facts separate actual comparison, obligation, origin and maintenance."""

import hashlib
import json
import subprocess
import sys
from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from tests.unit.test_plan_readiness import NOW, context, leaf, observation, rule, snapshot
from tests.unit.test_plan_readiness_fact_models import A6_JSON, A6_SHA256, notice

from trade_plan_monitor.web import plan_readiness_models as models


def obligation(**changes):
    values = dict(
        risk_id="risk-actual",
        revision=3,
        kind="SEVERE_TECHNICAL",
        status="CONFIRMED",
        confirmed_trade_date=date(2026, 10, 29),
        earliest_execution_date=date(2026, 10, 30),
        fulfilled_at=None,
        blockers=(),
    )
    values.update(changes)
    return models.ReadinessRiskObligation(**values)


def current(**changes):
    from trade_plan_monitor.decision.models import IntradayEvaluationTarget
    from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
    from trade_plan_monitor.domain.unified_plan_models import MinuteCloseBelow
    from trade_plan_monitor.state.daily_state_models import DailyRiskEvaluation

    values = dict(
        plan_version_id=str(context().plan_version_id),
        content_hash=context().content_hash,
        review_id="current-review",
        activation_revision=context().activation_revision,
        risk_identity="risk-branch",
        kind="SEVERE_TECHNICAL",
        target=IntradayEvaluationTarget(bucket_end=NOW - timedelta(minutes=5)),
        evaluated_at=NOW - timedelta(minutes=1),
        ordinary_close=None,
        evidence=UnifiedConditionEvidence(
            outcome="UNSATISFIED",
            bar_ids=("actual-bar",),
            condition=MinuteCloseBelow(
                type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=950
            ),
        ),
    )
    values.update(changes)
    return DailyRiskEvaluation(**values)


def origin(*, kind="SEVERE_TECHNICAL", **changes):
    from trade_plan_monitor.decision.daily_risk import DailyRiskBirth

    values = dict(
        evaluation_id="original-immutable-eval",
        plan_version_id="prior-plan-version",
        content_hash="e" * 64,
        review_id="original-review",
        activation_revision=2,
        evaluated_at=NOW - timedelta(days=3),
        birth=DailyRiskBirth(
            risk_identity="risk-branch",
            kind=kind,
            status_before="CLEAR",
            status_after="PENDING" if kind == "ORDINARY_TECHNICAL" else "CONFIRMED",
            close_date=date(2026, 10, 29),
        ),
    )
    values.update(changes)
    return models.ReadinessRiskOrigin(**values)


def risk(**changes):
    values = dict(
        current=current(),
        obligation=obligation(),
        origin=origin(),
        maintenance=models.AxisReadiness(
            axis="DATA_EVALUATION", state="PASS", observation=observation()
        ),
    )
    values.update(changes)
    return models.ReadinessRiskFacts(**values)


def test_default_risk_is_omitted_from_old_rule_json():
    value = rule()
    assert value.risk is None
    assert "risk" not in value.model_dump(mode="json", by_alias=True)


def test_actual_false_is_independent_of_a_confirmed_old_obligation():
    facts = risk()
    value = rule(
        owner_kind="RISK_BRANCH",
        owner_id="risk-branch",
        side="SELL",
        risk=facts,
        expected_target=facts.current.target,
        evaluated_target=facts.current.target,
    )
    assert value.risk.current.evidence.outcome == "UNSATISFIED"
    assert value.risk.obligation.status == "CONFIRMED"
    assert value.risk.origin.plan_version_id != str(context().plan_version_id)
    assert models.RuleReadinessFacts.model_validate_json(value.model_dump_json()) == value


def risk_rule(facts, **changes):
    actual = facts.current
    values = dict(
        owner_kind="RISK_BRANCH",
        owner_id="risk-branch",
        side="SELL",
        risk=facts,
        evaluated_target=None if actual is None else actual.target,
        evaluated_at=None if actual is None else actual.evaluated_at,
        root_outcome=None if actual is None or actual.evidence is None else actual.evidence.outcome,
        leaves=() if actual is None or actual.evidence is None else (leaf(),),
    )
    values.update(changes)
    return rule(**values)


def test_old_a6_and_rich_a7_bytes_remain_identical_with_risk_absent_or_null():
    restored = models.ReadinessAssessment.model_validate_json(A6_JSON)
    assert restored.model_dump_json(by_alias=True) == A6_JSON
    assert hashlib.sha256(A6_JSON.encode()).hexdigest() == A6_SHA256
    rich = rule(
        money=models.ReadinessMoneyFacts(
            inputs=models.AxisReadiness(
                axis="INVENTORY_CAPITAL", state="PASS", observation=observation()
            )
        ),
        notification=notice(),
        execution=models.ReadinessExecutionState(
            signal_id="signal-original", signal_revision=3, observation=observation(), blockers=()
        ),
    )
    before = rich.model_dump_json(by_alias=True)
    assert len(before.encode()) == 4456
    assert hashlib.sha256(before.encode()).hexdigest() == (
        "7602f9b441a7b22514da217b570a6c264756d92d158dc6b728f5ffde22c53c9a"
    )
    assert rich.model_copy(update={"risk": None}).model_dump_json(by_alias=True) == before


@pytest.mark.parametrize("status", ["CONFIRMED", "FULFILLED"])
def test_ordinary_design_skip_can_describe_maintenance_without_a_new_comparison(status):
    facts = risk(
        current=None,
        obligation=obligation(
            kind="ORDINARY_TECHNICAL",
            status=status,
            fulfilled_at=NOW - timedelta(hours=1) if status == "FULFILLED" else None,
        ),
        origin=origin(kind="ORDINARY_TECHNICAL"),
    )
    value = risk_rule(facts)
    assert value.risk.maintenance.state == "PASS"
    assert value.risk.current is None and value.root_outcome is None and value.leaves == ()
    assert value.evaluated_at is None and value.evaluated_target is None
    assert "current" not in value.model_dump(mode="json")["risk"]
    from trade_plan_monitor.web.plan_readiness_summary import summarize_readiness

    assessed = summarize_readiness(snapshot(rules=(value,)))
    # Verified designed skip is not missing applicable authority.
    assert assessed.summary == "READY_FOR_MONITORING"
    assert assessed.authority_granted is False


def test_missing_origin_preserves_current_comparison_and_persisted_obligation_only():
    unknown = models.AxisReadiness(
        axis="DATA_EVALUATION", state="UNKNOWN", reason="DEPENDENCY_UNVERIFIED"
    )
    value = risk_rule(risk(origin=None, maintenance=unknown))
    assert value.root_outcome == "UNSATISFIED"
    assert value.risk.obligation.status == "CONFIRMED" and value.risk.origin is None
    assert "origin" not in value.model_dump(mode="json")["risk"]


def test_no_current_or_obligation_can_be_reported_as_unknown_without_invented_values():
    value = risk_rule(
        risk(
            current=None,
            obligation=None,
            origin=None,
            maintenance=models.AxisReadiness(
                axis="DATA_EVALUATION",
                state="UNKNOWN",
                reason="AUTHORITY_UNAVAILABLE",
                observation=observation(availability="PERSISTED_ONLY"),
            ),
        )
    )
    wire = value.model_dump(mode="json", by_alias=True)["risk"]
    assert set(wire) == {"maintenance"}


@pytest.mark.parametrize("kind", ["ORDINARY_RULE", "ALERT_RULE"])
def test_risk_facts_cannot_be_attached_to_nonrisk_owners(kind):
    with pytest.raises(ValidationError):
        rule(owner_kind=kind, side=None if kind == "ALERT_RULE" else "BUY", risk=risk())


@pytest.mark.parametrize(
    "change",
    [
        "current-owner",
        "origin-owner",
        "kind",
        "target",
        "time",
        "root",
        "fake-skip-root",
        "fake-skip-leaf",
        "fake-skip-time",
    ],
)
def test_risk_owner_and_comparison_fields_cannot_be_rebound(change):
    facts = risk()
    changes = {}
    if change == "current-owner":
        facts = risk(current=current(risk_identity="other-branch"))
    elif change == "origin-owner":
        birth = origin().birth.model_copy(update={"risk_identity": "other-branch"})
        facts = risk(origin=origin(birth=birth))
    elif change == "kind":
        with pytest.raises(ValidationError):
            risk(obligation=obligation(kind="ORDINARY_TECHNICAL"))
        return
    elif change == "target":
        changes["evaluated_target"] = rule().evaluated_target
    elif change == "time":
        changes["evaluated_at"] = NOW
    elif change == "root":
        changes["root_outcome"] = "SATISFIED"
    else:
        facts = risk(
            current=None,
            obligation=obligation(kind="ORDINARY_TECHNICAL"),
            origin=origin(kind="ORDINARY_TECHNICAL"),
        )
        changes[
            {
                "fake-skip-root": "root_outcome",
                "fake-skip-leaf": "leaves",
                "fake-skip-time": "evaluated_at",
            }[change]
        ] = (
            "SATISFIED"
            if change == "fake-skip-root"
            else (leaf(),)
            if change == "fake-skip-leaf"
            else NOW
        )
    with pytest.raises(ValidationError):
        risk_rule(facts, **changes)


@pytest.mark.parametrize(
    "change",
    [
        "axis",
        "cached",
        "persisted",
        "missing-origin",
        "missing-obligation",
        "missing-current",
        "context",
        "unknown-time",
    ],
)
def test_maintenance_pass_requires_coherent_current_facts(change):
    values = {}
    if change == "axis":
        values["maintenance"] = models.AxisReadiness(
            axis="INVENTORY_CAPITAL", state="PASS", observation=observation()
        )
    elif change in {"cached", "persisted"}:
        values["maintenance"] = models.AxisReadiness(
            axis="DATA_EVALUATION",
            state="PASS",
            observation=observation(
                availability="CACHED" if change == "cached" else "PERSISTED_ONLY"
            ),
        )
    elif change == "missing-origin":
        values["origin"] = None
    elif change == "missing-obligation":
        values.update(obligation=None, origin=None)
    elif change == "missing-current":
        values["current"] = None
    elif change == "context":
        values["maintenance"] = models.AxisReadiness(
            axis="DATA_EVALUATION",
            state="PASS",
            observation=observation(
                context=context().model_copy(update={"activation_revision": 8})
            ),
        )
    else:
        values["maintenance"] = models.AxisReadiness(
            axis="DATA_EVALUATION", state="PASS", observation=observation(as_of=None)
        )
    with pytest.raises(ValidationError):
        risk_rule(risk(**values))


@pytest.mark.parametrize(
    "field,value",
    [("plan_version_id", "older-version"), ("content_hash", "f" * 64), ("activation_revision", 9)],
)
def test_current_comparison_matches_admitted_context_but_origin_keeps_its_original(field, value):
    with pytest.raises(ValidationError):
        risk_rule(risk(current=current(**{field: value})))


@pytest.mark.parametrize("value", [True, "3", -1, 2**53])
def test_obligation_revision_is_a_strict_bounded_native_integer(value):
    with pytest.raises(ValidationError):
        obligation(revision=value)


@pytest.mark.parametrize(
    "changes",
    [
        dict(status="PENDING"),
        dict(confirmed_trade_date=None),
        dict(blockers=("x",) * 129),
        dict(revision=3, unexpected=True),
    ],
)
def test_obligation_rejects_inconsistent_status_or_unregistered_fields(changes):
    with pytest.raises(ValidationError):
        obligation(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        dict(evaluation_id="evaluation-head-003043.SZ"),
        dict(activation_revision=True),
        dict(activation_revision=0),
        dict(content_hash="invalid"),
        dict(evaluated_at=NOW.replace(tzinfo=None)),
        dict(evaluated_at=NOW - timedelta(days=6)),
        dict(unknown_permission=True),
    ],
)
def test_origin_rejects_impossible_identity_and_times_without_synthesizing_a_birth(changes):
    with pytest.raises(ValidationError):
        origin(**changes)


def test_risk_json_retains_native_names_closed_fields_and_immutability():
    value = risk_rule(risk())
    wire = json.loads(value.model_dump_json(by_alias=True))
    assert "plan_version_id" in wire["risk"]["current"]
    assert "planVersionId" in wire["risk"]["origin"]
    assert "risk_identity" in wire["risk"]["origin"]["birth"]
    assert models.RuleReadinessFacts.model_validate_json(json.dumps(wire)) == value
    with pytest.raises(ValidationError):
        value.risk.obligation.revision = 8
    wire["risk"]["futurePermission"] = True
    with pytest.raises(ValidationError):
        models.RuleReadinessFacts.model_validate_json(json.dumps(wire))


def test_new_risk_components_do_not_reuse_daily_risk_state_or_import_reports():
    schema = models.RuleReadinessFacts.model_json_schema()
    assert "ReadinessRiskObligation" in schema["$defs"]
    assert "DailyRiskState" not in schema["$defs"]
    code = (
        "import sys; import trade_plan_monitor.web.plan_readiness_models; "
        "assert not any(name.startswith('trade_plan_monitor.backtest') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


@pytest.mark.parametrize("close,status", [(4100, "CLEAR"), (3800, "PENDING"), (3810, "CONFIRMED")])
def test_real_new_cause_retains_old_fulfillment_without_becoming_currently_fulfilled(close, status):
    from datetime import datetime

    from tests.unit.test_daily_risk_observer import DAYS, ordinary, run

    previous = run(run(), day=DAYS[1])
    prior_fulfilled = "2026-09-22T15:20:00+08:00"
    ordinary(previous).update(
        status="FULFILLED", fulfilled_at=prior_fulfilled, cause_cutover_at=prior_fulfilled
    )
    result = run(previous, day=DAYS[2], close=3800 if status == "CONFIRMED" else close)
    if status == "CONFIRMED":
        result = run(result, day=DAYS[3], close=close)
    actual = ordinary(result)
    assert actual["status"] == status and actual["fulfilled_at"] == prior_fulfilled
    projected = obligation(
        kind=actual["kind"],
        status=status,
        confirmed_trade_date=None
        if actual.get("confirmed_trade_date") is None
        else date.fromisoformat(actual["confirmed_trade_date"]),
        earliest_execution_date=None
        if actual.get("earliest_execution_date") is None
        else date.fromisoformat(actual["earliest_execution_date"]),
        fulfilled_at=datetime.fromisoformat(actual["fulfilled_at"]),
        blockers=tuple(actual["blockers"]),
    )
    assert projected.status == status and projected.fulfilled_at.isoformat() == prior_fulfilled
    if status != "CONFIRMED":
        assert projected.confirmed_trade_date is None
    else:
        assert projected.fulfilled_at.date() < projected.confirmed_trade_date


@pytest.mark.parametrize(
    "state,reason",
    [("UNKNOWN", "DEPENDENCY_UNVERIFIED"), ("MISSING_INPUT", "HUMAN_EVIDENCE_REQUIRED")],
)
def test_absent_comparison_retains_definition_diagnostic_leaves(state, reason):
    facts = risk(
        current=None,
        origin=None,
        maintenance=models.AxisReadiness(
            axis="DATA_EVALUATION", state="UNKNOWN", reason="DEPENDENCY_UNVERIFIED"
        ),
    )
    diagnostic = leaf(state=state, reason=reason)
    value = risk_rule(facts, leaves=(diagnostic,))
    assert value.risk.current is None and value.root_outcome is None
    assert value.leaves == (diagnostic,)


def test_native_ordinary_comparison_remains_a_close_observation_without_a_condition_root():
    from tests.unit.test_daily_risk_observer import DAYS, run

    from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget

    observations = []
    run(_evaluation_observer=observations.append)
    actual = observations[0]
    old = origin(kind="ORDINARY_TECHNICAL")
    old = old.model_copy(
        update={"birth": old.birth.model_copy(update={"risk_identity": actual.risk_identity})}
    )
    facts = risk(
        current=current(
            kind="ORDINARY_TECHNICAL",
            risk_identity=actual.risk_identity,
            target=OfficialCloseEvaluationTarget(trade_date=DAYS[0]),
            evidence=None,
            ordinary_close=actual,
        ),
        origin=old,
        obligation=obligation(kind="ORDINARY_TECHNICAL"),
    )
    value = risk_rule(facts, owner_id=actual.risk_identity)
    assert value.risk.current.ordinary_close == actual
    assert value.root_outcome is None and value.leaves == ()


def test_embedded_native_risk_trees_cannot_bypass_the_fifty_leaf_budget():
    from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
    from trade_plan_monitor.domain.unified_plan_models import UnifiedAll

    native = current().evidence
    tree = UnifiedConditionEvidence(
        outcome="UNSATISFIED",
        condition=UnifiedAll(type="ALL", conditions=(native.condition,) * 26),
        children=(native,) * 26,
    )
    values = []
    for identity in ("risk-a", "risk-b"):
        original = origin()
        original = original.model_copy(
            update={"birth": original.birth.model_copy(update={"risk_identity": identity})}
        )
        values.append(
            risk_rule(
                risk(current=current(risk_identity=identity, evidence=tree), origin=original),
                owner_id=identity,
                leaves=(),
            )
        )
    with pytest.raises(ValidationError, match="fifty"):
        snapshot(rules=tuple(values))
    assert len(snapshot(rules=(values[0],)).rules) == 1
