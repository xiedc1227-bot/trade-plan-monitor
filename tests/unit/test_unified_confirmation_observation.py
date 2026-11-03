"""Observe the existing evaluation without creating another signal or evaluator."""

import json
from copy import deepcopy
from datetime import date
from hashlib import sha256

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_conditions import synthetic_series
from tests.unit.test_source_tranches import tranche_plan

from trade_plan_monitor.decision import unified_lifecycle as lifecycle
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

# Frozen before production edits on c8515f4: full 1020-byte original return,
# independently SHA-256 checked by PowerShell/.NET, not rebuilt by confirm_signal.
OLD_RETURN = (
    b'{"basis_id":"synthetic-qfq","blockers":[],"bucket":"TACTICAL",'
    b'"confirmation_kind":"OFFICIAL_DAILY_CLOSE","confirmed_at":null,'
    b'"confirmed_trade_date":"2026-06-01","evidence":[{"bar_ids":["synthetic-0"],'
    b'"basis_id":"synthetic-qfq","children":[],"condition":{"comparator":"LT",'
    b'"field":"close","offset":0,"reference":{"as_of":"2026-06-01","mode":"FIXED",'
    b'"source":"Synthetic threshold","unit":"FEN","value":"5000"},'
    b'"type":"DAILY_PRICE_COMPARE"},"fact_ids":[],"operands":["3900","5000"],'
    b'"outcome":"SATISFIED","reason":null,"session_dates":["2026-06-01"]}],'
    b'"evidence_fingerprint":"7da9fc1b0d40516ffdd465aa936dd891c92e54c5c65ed8adf87b5d875c968cf6",'
    b'"executable_qty":0,"execution_date":"2026-06-02",'
    b'"execution_window":"NEXT_EXCHANGE_SESSION_ONLY","lineage":"synthetic-daily",'
    b'"occurrence_mode":"ONCE_PER_RULE","plan_version_id":"version-1","planned_qty":100,'
    b'"review_id":"review-1","rule_id":"first-100","side":"BUY",'
    b'"signal_id":"5cd4e6ec21a54ade444fd0f3156a7091abaa5678a55527ec9eea576d84bc56e1",'
    b'"simulated_qty":0,"state":"CONFIRMED"}'
)
OLD_SHA256 = "2e071382162ffb8b3e44038eff5de7209d94b06c5af957d81e168d9ada115c6c"
_OMITTED = object()


def confirm(plan=None, *, index=0, day=1, observer=_OMITTED, **changes):
    plan = plan or tranche_plan()
    series, _ = synthetic_series(count=day)
    sessions, _ = synthetic_series(count=6)
    kwargs = dict(series=series, facts=(), previous=(), session_dates=sessions.session_dates,
                  plan_version_id="version-1", review_id="review-1")
    kwargs.update(changes)
    if observer is not _OMITTED:
        kwargs["_evaluation_observer"] = observer
    return lifecycle.confirm_signal(plan, plan.ordinary_rules[index], **kwargs)


def plan_with(*, single_rule=False, **changes):
    raw = tranche_plan().model_dump(mode="json")
    if single_rule:
        raw["ordinary_rules"] = raw["ordinary_rules"][:1]
    raw["ordinary_rules"][0].update(changes)
    return UnifiedTradePlan.model_validate(raw)


@pytest.fixture
def evaluations(monkeypatch):
    original = lifecycle.evaluate_unified_condition
    actual = []

    def counted(*args, **kwargs):
        value = original(*args, **kwargs)
        actual.append(value)
        return value

    monkeypatch.setattr(lifecycle, "evaluate_unified_condition", counted)
    return actual


def test_literal_old_return_is_independent_and_matches_the_unobserved_call():
    assert len(OLD_RETURN) == 1020
    assert sha256(OLD_RETURN).hexdigest() == OLD_SHA256
    assert canonical(confirm()).encode() == OLD_RETURN


@pytest.mark.parametrize("value,outcome", [
    ("5000", "SATISFIED"), ("3800", "UNSATISFIED"), (None, "MISSING_INPUT"),
], ids=["true", "false", "missing"])
def test_observer_keeps_actual_outcome_even_without_a_signal(value, outcome, evaluations):
    condition = tranche_plan().ordinary_rules[0].condition.model_dump(mode="json")
    if value is None:
        condition["offset"] = 1
    else:
        condition["reference"]["value"] = value
    observed = []
    result = confirm(plan_with(condition=condition), observer=observed.append)
    assert len(evaluations) == len(observed) == 1
    assert observed[0] is evaluations[0]
    assert observed[0].outcome == outcome
    assert observed[0].condition.model_dump(mode="json") == condition
    assert (result is not None) is (outcome == "SATISFIED")


@pytest.mark.parametrize("operator,value,outcome", [
    ("ALL", "3800", "UNSATISFIED"), ("ANY", "5000", "SATISFIED"),
    ("ALL", "5000", "MISSING_INPUT"), ("ANY", "3800", "MISSING_INPUT"),
])
def test_all_any_preserve_missing_children_and_original_signal_semantics(
    operator, value, outcome, evaluations,
):
    leaf = tranche_plan().ordinary_rules[0].condition.model_dump(mode="json")
    leaf["reference"]["value"] = value
    missing = deepcopy(leaf)
    missing["offset"] = 1
    condition = {"type": operator, "conditions": [leaf, missing]}
    observed = []
    result = confirm(plan_with(condition=condition), observer=observed.append)
    assert len(evaluations) == len(observed) == 1  # one root invocation; native recursion unchanged
    assert observed[0] is evaluations[0]
    assert observed[0].outcome == outcome
    assert len(observed[0].children) == 2
    assert observed[0].children[1].outcome == "MISSING_INPUT"
    assert observed[0].model_dump(mode="json")["children"][1]["condition"] == missing
    assert (result is not None) is (outcome == "SATISFIED")


def test_observer_receives_the_same_frozen_object_and_old_return_bytes(evaluations):
    observed = []
    result = confirm(observer=observed.append)
    assert observed == evaluations and len(observed) == 1
    assert observed[0] is evaluations[0]
    assert canonical(result).encode() == OLD_RETURN
    assert result["evidence"] == [observed[0].model_dump(mode="json")]
    with pytest.raises(ValidationError):
        observed[0].outcome = "UNSATISFIED"


def test_explicit_none_preserves_old_bytes_and_single_root_evaluation(evaluations):
    assert canonical(confirm(observer=None)).encode() == OLD_RETURN
    assert len(evaluations) == 1


@pytest.mark.parametrize("gate", ["zone", "unfilled", "independent-event", "reset"])
def test_actual_satisfied_evidence_survives_post_evaluation_rejection(gate, evaluations):
    plan = tranche_plan()
    previous = ()
    if gate == "zone":
        raw = plan.model_dump(mode="json")
        raw["ordinary_rules"][0]["zone"] = "LOW_BUY"
        raw["levels"]["low_buy"].update(low_fen=3000, high_fen=3100)
        plan = UnifiedTradePlan.model_validate(raw)
    else:
        independent = {"mode": "REVIEWED_INDEPENDENT_EVENT",
                       "evidence_requirement": "A new independent technical structure"}
        if gate == "reset":
            independent = {"mode": "LATER_CLOSE_RESET_THEN_CONFIRM",
                "reset_condition": plan.ordinary_rules[0].condition.model_dump(mode="json")}
        plan = plan_with(single_rule=True, independent_signal=independent)
        first = json.loads(OLD_RETURN)
        if gate != "unfilled":
            first.update(state="SIMULATED", simulated_qty=100)
        previous = (first,)
    observed = []
    assert confirm(plan, day=2, previous=previous, observer=observed.append) is None
    assert len(evaluations) == len(observed) == 1
    assert observed[0] is evaluations[0] and observed[0].outcome == "SATISFIED"


@pytest.mark.parametrize("state", ["CONFIRMED", "READY", "SIMULATED", "EXPIRED", "INVALIDATED"])
def test_once_per_rule_existing_occurrence_returns_before_evaluation(state, evaluations):
    prior = json.loads(OLD_RETURN)
    prior.update(state=state, simulated_qty=100 if state == "SIMULATED" else 0)
    observed = []
    assert confirm(day=3, previous=(prior,), observer=observed.append) is None
    assert evaluations == observed == []  # no evidence means UNKNOWN, never a manufactured FALSE


@pytest.mark.parametrize("gate", ["no-predecessor", "unfilled-predecessor", "before-execution"])
def test_predecessor_admission_is_not_bypassed_to_create_observations(gate, evaluations):
    prior = json.loads(OLD_RETURN)
    day = 2
    if gate == "before-execution":
        prior.update(state="SIMULATED", simulated_qty=100)
        day = 1
    previous = () if gate == "no-predecessor" else (prior,)
    observed = []
    assert confirm(index=1, day=day, previous=previous, observer=observed.append) is None
    assert evaluations == observed == []


@pytest.mark.parametrize("gate", [
    "no-series", "minute-inputs", "validity", "fact-owner", "p2-linkage",
])
def test_other_pre_evaluation_returns_do_not_invent_condition_results(gate, evaluations):
    plan, changes = tranche_plan(), {}
    if gate == "no-series":
        changes["series"] = None
    elif gate == "minute-inputs":
        plan = plan_with(condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5,
                                    "price_fen": 5000},
                         confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
                         execution_window="CURRENT_SESSION")
    elif gate == "validity":
        plan = plan_with(validity={"mode": "DATE_RANGE", "start_date": date(2026, 6, 2),
                                   "end_date": date(2026, 6, 5)})
    elif gate == "fact-owner":
        changes.update(_condition_facts=(), _fact_owner=(plan, "sibling", "ORDINARY_RULE", "wrong"))
    else:
        from tests.unit.test_p3_policy_contract import p3_payload

        from trade_plan_monitor.domain.p3_policy_models import P3TradePlan
        plan = P3TradePlan.model_validate(p3_payload())
    observed = []
    assert confirm(plan, observer=observed.append, **changes) is None
    assert evaluations == observed == []


def test_falsey_callable_observer_is_not_mistaken_for_absence(evaluations):
    class Observer:
        def __init__(self):
            self.values = []

        def __bool__(self):
            return False

        def __call__(self, evidence):
            self.values.append(evidence)

    observer = Observer()
    assert canonical(confirm(observer=observer)).encode() == OLD_RETURN
    assert len(observer.values) == 1 and observer.values[0] is evaluations[0]
