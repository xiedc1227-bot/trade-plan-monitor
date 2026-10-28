"""A finite five-minute requirement describes evidence; it never supplies the fact."""

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_daily_conditions import synthetic_series
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.ai.daily_review import build_daily_review, semantic_values
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_policy_text import supported_policy_text
from trade_plan_monitor.decision.daily_conditions import evaluate_daily_condition
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

REQUIREMENT = "Human verifies the completed five-minute pattern"
REQUIREMENT_PATH = "ordinary_rules[0].condition.evidence_requirement"
CONDITION_PATH = "ordinary_rules[0].condition."


def _candidate(*, requirement=REQUIREMENT, fact_kind="TECHNICAL"):
    raw = unified_payload()
    raw.update(levels=None, monitoring=None, risk_branches=[], alert_rules=[])
    raw["position"] = {"max_qty": 1000}
    raw["ordinary_rules"] = raw["ordinary_rules"][:1]
    raw["ordinary_rules"][0].update(
        zone=None,
        validity={"mode": "PLAN_ACTIVE"},
        condition={"type": "REVIEWED_FACT", "fact_kind": fact_kind,
                   "evidence_requirement": requirement, "validity_scope": "TRADE_DATE"},
        confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        execution_window="CURRENT_SESSION",
    )
    plan = UnifiedTradePlan.model_validate(raw)
    draft = UnifiedPlanDraft.from_executable(plan)
    source, mapping = source_mapping(draft)
    assert draft.to_executable() == plan
    assert build_daily_review(draft, mapping, source).issues == ()
    assert {row.path: row.value for row in mapping.bindings} == semantic_values(draft)
    return draft, source, mapping


def _proof(*, requirement=REQUIREMENT, fact_kind="TECHNICAL"):
    draft, source, mapping = _candidate(requirement=requirement, fact_kind=fact_kind)
    before = draft.model_dump_json(), mapping.model_dump_json(), source
    proof = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    assert (draft.model_dump_json(), mapping.model_dump_json(), source) == before
    assert proof.authority_granted is False
    assert proof.automatic_fidelity_verified is False
    return draft, source, proof


def test_exact_five_minute_requirement_is_registered_only_as_a_technical_manual_atom():
    values = {CONDITION_PATH + "type": "REVIEWED_FACT",
              CONDITION_PATH + "fact_kind": "TECHNICAL"}

    assert supported_policy_text(REQUIREMENT_PATH, REQUIREMENT, values)


def test_exact_source_coverage_keeps_the_five_minute_manual_requirement_executable():
    draft, source, proof = _proof()

    assert proof.coverage_complete is True
    assert proof.status == "COMPLETE"
    assert proof.issues == ()
    rows = [row for row in proof.obligations if REQUIREMENT_PATH in row.paths]
    assert rows and all(row.state == "MAPPED" for row in rows)
    assert all(row.scope == "BUY" for row in rows)
    assert any(row.kind == "PREDICATE" and REQUIREMENT in row.excerpt for row in rows)
    assert all(source[row.start:row.end] == row.excerpt for row in rows)
    assert draft.ordinary_rules[0].condition.evidence_requirement == REQUIREMENT
    assert draft.ordinary_rules[0].confirmation.timeframe_minutes == 5
    assert len(draft.ordinary_rules) == 1
    assert draft.alert_rules == () and draft.risk_branches == ()


@pytest.mark.parametrize("fact_kind", [
    "PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TRADE_VIABILITY",
    "SEVERE_STRUCTURE", "SEVERE_DETERIORATION",
])
def test_five_minute_requirement_cannot_supply_another_fact_kind(fact_kind):
    _, source, proof = _proof(fact_kind=fact_kind)

    assert proof.coverage_complete is False
    assert proof.status == "BLOCKED"
    assert any(issue.code == "SOURCE_CONTEXT_UNVERIFIED" and issue.path == REQUIREMENT_PATH
               and source[issue.start:issue.end].endswith(f'"{REQUIREMENT}"')
               for issue in proof.issues if issue.start is not None)


def test_five_minute_requirement_is_not_registered_outside_the_reviewed_fact_type():
    values = {CONDITION_PATH + "type": "MINUTE_CLOSE_BELOW",
              CONDITION_PATH + "fact_kind": "TECHNICAL"}

    assert not supported_policy_text(REQUIREMENT_PATH, REQUIREMENT, values)
    assert not supported_policy_text(
        "ordinary_rules[0].independent_signal.evidence_requirement", REQUIREMENT, values)


@pytest.mark.parametrize("requirement", [
    "Do not require: " + REQUIREMENT,
    "不要求：" + REQUIREMENT,
    REQUIREMENT + "; buy only when turnover exceeds 3 percent.",
    REQUIREMENT + " and turnover must exceed 3 percent.",
], ids=["negated-english", "negated-chinese", "mandatory-tail-semicolon", "mandatory-tail-and"])
def test_negation_and_additional_mandatory_tail_cannot_borrow_the_registered_prefix(requirement):
    _, source, proof = _proof(requirement=requirement)

    assert proof.coverage_complete is False
    assert proof.status == "BLOCKED"
    start = source.index(REQUIREMENT_PATH + " = ")
    end = source.find("\n", start)
    assert any(issue.code == "SOURCE_CONTEXT_UNVERIFIED"
               and max(start, issue.start) < min(end, issue.end)
               for issue in proof.issues if issue.start is not None)


@pytest.mark.parametrize("fact_variant", ["missing", "unverified", "wrong-kind", "stale-date"])
def test_covered_requirement_still_waits_for_an_actual_scoped_verified_fact(fact_variant):
    draft, _, proof = _proof()
    assert proof.coverage_complete is True
    series, _ = synthetic_series(count=2)
    fact = {"id": "separate-human-fact", "kind": "TECHNICAL", "verified": True,
            "trade_date": str(series.bars[-1].trade_date)}
    if fact_variant == "unverified":
        fact["verified"] = False
    elif fact_variant == "wrong-kind":
        fact["kind"] = "VOLUME_OR_CANDLE"
    elif fact_variant == "stale-date":
        fact["trade_date"] = str(series.bars[0].trade_date)
    facts = () if fact_variant == "missing" else (fact,)

    evidence = evaluate_daily_condition(draft.ordinary_rules[0].condition, series, facts=facts)

    assert evidence.outcome == "MISSING_INPUT"
    assert evidence.reason == "REVIEWED_FACT_REQUIRED"
    assert evidence.fact_ids == ()
    assert evidence.condition.evidence_requirement == REQUIREMENT
