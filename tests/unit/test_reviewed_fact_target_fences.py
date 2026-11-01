"""Explicit targets remain unusable by every old kind-only fact path."""

from datetime import timedelta

import pytest
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from tests.unit.test_daily_conditions import synthetic_series
from tests.unit.test_reviewed_fact_targets import _fact, _leaf, _plan, _with_second_rule

from trade_plan_monitor.decision.daily_conditions import evaluate_daily_condition
from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_models import DailyCondition
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256
from trade_plan_monitor.domain.reviewed_fact_targets import (
    assess_unbound_fact,
    filter_unbound_facts,
    list_reviewed_fact_targets,
    resolve_reviewed_fact_target,
)
from trade_plan_monitor.domain.unified_plan_models import UnifiedCondition, UnifiedTradePlan

OWNER = "actual-owner-version"


@pytest.fixture(scope="module")
def series():
    # Existing explicit synthetic fixture ends on 2026-09-22, within rule validity.
    return synthetic_series(count=114)[0]


def _targets(plan):
    return list_reviewed_fact_targets(plan, plan_version_id=OWNER,
                                     content_hash=daily_plan_content_sha256(plan))


def _observed(plan, series, **changes):
    return _fact(plan, trade_date=str(series.bars[-1].trade_date), signal_id="actual-signal",
                 available_at=series.cutoff.isoformat(), verified_at=series.cutoff.isoformat(),
                 **changes)


def _evaluate(engine, raw, series, facts):
    condition = TypeAdapter(DailyCondition if engine == "daily" else UnifiedCondition
                            ).validate_python(raw)
    kwargs = dict(facts=facts, signal_id="actual-signal")
    if engine == "unified":
        return evaluate_unified_condition(condition, series, target=series.cutoff, **kwargs)
    return evaluate_daily_condition(condition, series, **kwargs)


@pytest.mark.parametrize("satisfied", [True, False])
def test_target_of_a_cannot_fold_into_the_unbound_definition_shared_with_b(series, satisfied):
    plan = _with_second_rule(_plan())
    legacy = _observed(plan, series, satisfied=satisfied)
    decision = assess_unbound_fact(plan, legacy)
    assert decision.usable and decision.definition_count == 1
    assert {ref.owner_id for ref in decision.definitions} == {"low-buy", "sell-other"}
    target = next(t for t in _targets(plan) if t.owner_id == "low-buy")
    assert resolve_reviewed_fact_target(plan, target, plan_version_id=OWNER).owner_id == "low-buy"
    targeted = {**legacy, "reviewed_fact_target": target.model_dump()}
    before = canonical(targeted), plan.model_dump_json()
    assert assess_unbound_fact(plan, targeted).reason == "INVALID_FACT"
    assert filter_unbound_facts(plan, (targeted,)) == ()
    assert before == (canonical(targeted), plan.model_dump_json())


@pytest.mark.parametrize("engine", ["daily", "unified"])
@pytest.mark.parametrize("satisfied", [True, False])
@pytest.mark.parametrize("marker", [None, {}, "self-consistent"])
def test_raw_kind_only_engine_cannot_lend_a_targeted_fact_to_b(series, engine, satisfied, marker):
    plan = _with_second_rule(_plan())
    if marker == "self-consistent":
        marker = next(t.model_dump() for t in _targets(plan) if t.owner_id == "low-buy")
    fact = _observed(plan, series, satisfied=satisfied, reviewed_fact_target=marker)
    # B has exactly the same kind, definition and date/signal as A, but no A authority.
    leaf = plan.ordinary_rules[1].condition.conditions[0].model_dump(mode="json")
    result = _evaluate(engine, leaf, series, (fact,))
    assert result.outcome == "MISSING_INPUT" and result.fact_ids == ()


@pytest.mark.parametrize("engine", ["daily", "unified"])
@pytest.mark.parametrize("target_scope", ["TRADE_DATE", "SIGNAL"])
@pytest.mark.parametrize("satisfied", [True, False])
def test_target_presence_blocks_both_overlapping_date_and_signal_paths(
    series, engine, target_scope, satisfied,
):
    plan = _plan(_leaf(), _leaf(scope="SIGNAL"))
    index = 0 if target_scope == "TRADE_DATE" else 1
    fact = _observed(plan, series, satisfied=satisfied,
                     reviewed_fact_target=_targets(plan)[index].model_dump())
    for scope in ("TRADE_DATE", "SIGNAL"):
        result = _evaluate(engine, _leaf(scope=scope), series, (fact,))
        assert result.outcome == "MISSING_INPUT" and result.fact_ids == ()


@pytest.mark.parametrize("engine", ["daily", "unified"])
@pytest.mark.parametrize("purpose", ["ORDINARY_CONFIRMATION", "RESET"])
def test_confirmation_and_reset_targets_cannot_fall_back_to_kind_matching(series, engine, purpose):
    raw = _plan().model_dump(mode="json")
    raw["ordinary_rules"][0]["independent_signal"] = dict(
        mode="LATER_CLOSE_RESET_THEN_CONFIRM", reset_condition=_leaf())
    plan = UnifiedTradePlan.model_validate(raw)
    path = "independent_signal.reset_condition" if purpose == "RESET" else "condition.conditions[0]"
    target = next(t for t in _targets(plan) if t.condition_path == path)
    ref = resolve_reviewed_fact_target(plan, target, plan_version_id=OWNER)
    assert f'"purpose":"{purpose}"' in ref.observation_context
    fact = _observed(plan, series, reviewed_fact_target=target.model_dump())
    assert _evaluate(engine, _leaf(), series, (fact,)).outcome == "MISSING_INPUT"


@pytest.mark.parametrize("kind", [
    "TRADABILITY", "FULL_SESSION_SUSPENSION", "INDEPENDENT_EVENT", "SIGNAL_INVALIDATION",
])
def test_target_presence_is_checked_before_control_fact_passthrough(series, kind):
    plan = _plan()
    legacy = _observed(plan, series, kind=kind)
    assert assess_unbound_fact(plan, legacy).reason == "CONTROL_FACT"
    assert filter_unbound_facts(plan, (legacy,))[0] is legacy
    fact = {**legacy, "reviewed_fact_target": None}
    assert assess_unbound_fact(plan, fact).reason == "INVALID_FACT"
    assert filter_unbound_facts(plan, (fact,)) == ()
    for engine in ("daily", "unified"):
        assert _evaluate(engine, _leaf(kind=kind), series, (fact,)).outcome == "MISSING_INPUT"


@pytest.mark.parametrize("marker", [None, {}, False, "broken-target"])
def test_falsy_or_damaged_target_never_becomes_unbound(series, marker):
    plan = _plan()
    fact = _observed(plan, series, reviewed_fact_target=marker)
    assert assess_unbound_fact(plan, fact).reason == "INVALID_FACT"
    assert filter_unbound_facts(plan, (fact,)) == ()


@pytest.mark.parametrize("engine", ["daily", "unified"])
@pytest.mark.parametrize("satisfied", [True, False])
def test_all_stays_missing_but_an_independent_numeric_any_branch_still_passes(
    series, engine, satisfied,
):
    plan = _plan()
    fact = _observed(plan, series, satisfied=satisfied,
                     reviewed_fact_target=_targets(plan)[0].model_dump())
    numeric = dict(type="DAILY_PRICE_COMPARE", field="close", offset=0, comparator="GT",
                   reference=dict(mode="FIXED", value="0", unit="FEN",
                                  as_of=series.bars[-1].trade_date.isoformat(),
                                  source="Synthetic independent numeric condition"))
    for mode, expected in (("ALL", "MISSING_INPUT"), ("ANY", "SATISFIED")):
        result = _evaluate(engine, dict(type=mode, conditions=[_leaf(), numeric]), series, (fact,))
        assert result.outcome == expected
        assert [c.outcome for c in result.children] == ["MISSING_INPUT", "SATISFIED"]


@pytest.mark.parametrize("engine", ["daily", "unified"])
@pytest.mark.parametrize("satisfied", [True, False])
def test_targeted_newer_fact_does_not_hide_same_day_same_kind_legal_unbound_fact(
    series, engine, satisfied,
):
    plan = _plan()
    legacy = _observed(plan, series, id="legal-unbound")
    later = (series.cutoff + timedelta(minutes=1)).isoformat()
    targeted = {**legacy, "id": "targeted-newer", "satisfied": satisfied,
                "available_at": later, "verified_at": later,
                "reviewed_fact_target": _targets(plan)[0].model_dump()}
    facts = (targeted, legacy)
    before = canonical(facts)
    projected = filter_unbound_facts(plan, facts)
    assert len(projected) == 1 and projected[0] is legacy
    for inputs in (facts, projected):
        result = _evaluate(engine, _leaf(), series, inputs)
        assert result.outcome == "SATISFIED" and result.fact_ids == ("legal-unbound",)
    assert canonical(facts) == before


def test_explicit_null_in_model_cannot_disappear_into_unbound_fallback(series):
    class SerializedFact(BaseModel):
        model_config = ConfigDict(extra="allow")
        reviewed_fact_target: object = Field(default=None, exclude_if=lambda value: value is None)

    plan = _plan()
    legacy = SerializedFact(**_observed(plan, series))
    marked = SerializedFact(**_observed(plan, series), reviewed_fact_target=None)
    assert legacy.model_dump() == marked.model_dump()
    assert assess_unbound_fact(plan, legacy).usable
    assert assess_unbound_fact(plan, marked).reason == "INVALID_FACT"
    assert filter_unbound_facts(plan, (marked, legacy)) == (legacy,)
