"""Reverse boundaries for the unpublished technical-only daily contract."""

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_plan import synthetic_plan_payload

from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan, ReviewedDailyFact
from trade_plan_monitor.state.daily_state_models import DailyFactState
from trade_plan_monitor.web.routers.daily_plans import DailyFactCommand


@pytest.mark.parametrize("kind", ["ANNOUNCEMENT_CHECK", "FUNDAMENTAL_INVALIDATION"])
def test_excluded_fact_kinds_reject_domain_api_and_storage(kind):
    with pytest.raises(ValidationError):
        ReviewedDailyFact(
            type="REVIEWED_FACT",
            fact_kind=kind,
            evidence_requirement="Synthetic excluded requirement",
            validity_scope="TRADE_DATE",
        )
    payload = dict(
        plan_version_id="00000000-0000-4000-8000-000000000001",
        content_hash="a" * 64,
        kind="TECHNICAL",
        trade_date="2026-09-22",
        evidence="Synthetic excluded fact cannot authorize monitoring",
    )
    api = {**payload, "fact_id": "excluded", "expected_revision": 0}
    state = {
        **payload,
        "signal_id": None,
        "verified": True,
        "verified_at": "2026-09-22T10:00:00+08:00",
        "available_at": "2026-09-22T10:00:00+08:00",
        "official_evidence": None,
    }
    assert DailyFactCommand.model_validate(api).kind == "TECHNICAL"
    assert DailyFactState.model_validate(state).kind == "TECHNICAL"
    for model, raw in ((DailyFactCommand, api), (DailyFactState, state)):
        with pytest.raises(ValidationError) as caught:
            model.model_validate({**raw, "kind": kind})
        assert [e["loc"] for e in caught.value.errors()] == [("kind",)]


def test_only_two_technical_risk_branches_are_executable():
    plan = DailyTradePlan.model_validate(synthetic_plan_payload())
    assert {branch.kind for branch in plan.risk_branches} == {
        "ORDINARY_TECHNICAL",
        "SEVERE_TECHNICAL",
    }
    assert plan.execution_policy.risk_priority == "SEVERE_THEN_ORDINARY"


@pytest.mark.parametrize("location", ["technical", "prerequisites", "independent_signal"])
@pytest.mark.parametrize("kind", ["ANNOUNCEMENT_CHECK", "FUNDAMENTAL_INVALIDATION"])
def test_excluded_fact_kind_cannot_enter_nested_conditions(location, kind):
    raw = synthetic_plan_payload()
    assert DailyTradePlan.model_validate(raw).schema_version == 4
    leaf = dict(
        type="REVIEWED_FACT",
        fact_kind=kind,
        evidence_requirement="Synthetic excluded requirement",
        validity_scope="TRADE_DATE",
    )
    nested = {"type": "ANY", "conditions": [{"type": "ALL", "conditions": [leaf]}]}
    rule = raw["ordinary_rules"][0]
    if location == "prerequisites":
        rule[location] = [nested]
    elif location == "independent_signal":
        rule[location] = {"mode": "LATER_CLOSE_RESET_THEN_CONFIRM", "reset_condition": nested}
    else:
        rule[location] = nested
    with pytest.raises(ValidationError):
        DailyTradePlan.model_validate(raw)


@pytest.mark.parametrize(
    "kind", ["TRADABILITY", "FULL_SESSION_SUSPENSION", "INDEPENDENT_EVENT", "SIGNAL_INVALIDATION"]
)
def test_negative_control_fact_rejected_at_api_and_storage(kind):
    payload = {
        "plan_version_id": "00000000-0000-4000-8000-000000000001",
        "content_hash": "a" * 64,
        "kind": kind,
        "trade_date": "2026-09-22",
        "signal_id": "previous-signal",
        "evidence": "Synthetic verified technical assertion for this test",
        "satisfied": False,
    }
    api = {**payload, "fact_id": "negative-control", "expected_revision": 0}
    state = {
        **payload,
        "verified": True,
        "verified_at": "2026-09-22T10:00:00+08:00",
        "available_at": "2026-09-22T10:00:00+08:00",
        "official_evidence": None,
    }
    for model, raw in ((DailyFactCommand, api), (DailyFactState, state)):
        with pytest.raises(
            ValidationError, match="negative assertions apply only to technical condition facts"
        ):
            model.model_validate(raw)


def test_old_fact_defaults_true_and_explicit_negative_predicate_remains_false():
    raw = {
        "plan_version_id": "00000000-0000-4000-8000-000000000001",
        "content_hash": "a" * 64,
        "kind": "TECHNICAL",
        "trade_date": "2026-09-22",
        "signal_id": None,
        "evidence": "Synthetic verified technical assertion for this test",
        "verified": True,
        "verified_at": "2026-09-22T10:00:00+08:00",
        "available_at": "2026-09-22T10:00:00+08:00",
        "official_evidence": None,
    }
    assert DailyFactState.model_validate(raw).satisfied is True
    assert "satisfied" not in raw  # Reading historical bytes never mutates them.
    assert DailyFactState.model_validate({**raw, "satisfied": False}).satisfied is False
