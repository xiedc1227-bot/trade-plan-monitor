"""Only proved ordinary maintenance may exempt an inapplicable new comparison."""

from datetime import timedelta

import pytest
from tests.unit.test_plan_readiness import NOW, axis, context, rule, snapshot
from tests.unit.test_plan_readiness_risk_models import obligation, origin, risk, risk_rule

from trade_plan_monitor.web.plan_readiness_summary import summarize_readiness


def test_proved_ordinary_skip_remains_unknown_but_does_not_mean_missing_authority():
    value = risk_rule(
        risk(
            current=None,
            obligation=obligation(kind="ORDINARY_TECHNICAL"),
            origin=origin(kind="ORDINARY_TECHNICAL"),
        )
    )
    result = summarize_readiness(snapshot(rules=(value,)))
    assert result.rules[0].state == "UNKNOWN"
    assert result.summary == "READY_FOR_MONITORING"
    assert result.authority_granted is False


def test_skip_cannot_exempt_maintenance_observed_before_a_related_inventory_revision():
    value = risk_rule(
        risk(
            current=None,
            obligation=obligation(kind="ORDINARY_TECHNICAL"),
            origin=origin(kind="ORDINARY_TECHNICAL"),
        )
    )
    current = snapshot(
        rules=(value,), context=context().model_copy(update={"inventory_revision": 2})
    )
    result = summarize_readiness(current)
    assert result.summary == "UNKNOWN"
    assert result.rules[0].reason == "CONTEXT_CHANGED"


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "cached",
        "missing-origin",
        "missing-maintenance",
        "owner",
        "other-rule",
        "notification",
    ],
)
def test_ordinary_skip_does_not_hide_other_missing_applicable_authority(change):
    values = {}
    if change == "expired":
        values["maintenance"] = axis("DATA_EVALUATION", "PASS", expires_at=NOW)
    elif change == "cached":
        values["maintenance"] = axis(
            "DATA_EVALUATION", "UNKNOWN", "DEPENDENCY_UNVERIFIED", availability="CACHED"
        )
    elif change in {"missing-origin", "missing-maintenance"}:
        values["maintenance"] = axis("DATA_EVALUATION", "UNKNOWN", "DEPENDENCY_UNVERIFIED")
        if change == "missing-origin":
            values["origin"] = None
    defaults = dict(
        current=None,
        obligation=obligation(kind="ORDINARY_TECHNICAL"),
        origin=origin(kind="ORDINARY_TECHNICAL"),
    )
    defaults.update(values)
    value = risk_rule(risk(**defaults))
    rules = (value,)
    replacements = {}
    if change == "owner":
        replacements["RUNTIME_OWNERSHIP"] = axis(
            "RUNTIME_OWNERSHIP", "UNKNOWN", "AUTHORITY_UNAVAILABLE"
        )
    elif change == "notification":
        replacements["NOTIFICATION_DELIVERY"] = axis(
            "NOTIFICATION_DELIVERY", "UNKNOWN", "DELIVERY_UNVERIFIED"
        )
    elif change == "other-rule":
        rules += (rule(root_outcome=None, leaves=(), evaluated_at=None, observation=None),)
    result = summarize_readiness(snapshot(rules=rules, replacements=replacements))
    assert result.summary == "UNKNOWN"


def test_actual_maintenance_expiry_is_included_in_fresh_until():
    value = risk_rule(
        risk(
            current=None,
            obligation=obligation(kind="ORDINARY_TECHNICAL"),
            origin=origin(kind="ORDINARY_TECHNICAL"),
            maintenance=axis("DATA_EVALUATION", "PASS", expires_at=NOW + timedelta(seconds=3)),
        )
    )
    result = summarize_readiness(snapshot(rules=(value,)))
    assert result.summary == "READY_FOR_MONITORING"
    assert result.fresh_until == NOW + timedelta(seconds=3)
