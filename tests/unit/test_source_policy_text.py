"""A registered manual atom must retain its exact technical kind."""

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_coverage_adversarial import _native_candidate
from tests.unit.test_source_coverage_semantics import _native_baseline, _rebuilt_source

from trade_plan_monitor.ai.daily_review import DailySupplement, build_daily_review
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.domain.p3_validation import P3PlanDraft


@pytest.mark.parametrize("kind,complete", [("VOLUME_OR_CANDLE", True), ("PRICE_STRUCTURE", False)])
def test_registered_volume_atom_cannot_be_reinterpreted_as_another_fact_kind(kind, complete):
    raw = _native_candidate("ALL").model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"]["conditions"].append(dict(
        type="REVIEWED_FACT", fact_kind=kind, evidence_requirement="成交不异常放大",
        validity_scope="TRADE_DATE"))
    draft = P3PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    proof = assess_source_coverage(draft, mapping, source)
    assert proof.coverage_complete is complete
    assert proof.authority_granted is False


@pytest.mark.parametrize("field", ["provenance.excerpt", "schedule_id", "version"])
def test_fee_annotation_labels_cannot_hide_an_additional_forward_condition(field):
    draft, _, _ = _native_baseline()
    raw = draft.model_dump(mode="json")
    schedule = raw["position"]["limit"]["capital_policy"]["buy_cost_schedule"]
    parent = schedule["provenance"] if field.startswith("provenance.") else schedule
    parent[field.split(".")[-1]] = "Only buy when turnover exceeds 3 percent."
    draft = P3PlanDraft.model_validate(raw)
    source, mapping = source_mapping(draft)
    proof = assess_source_coverage(draft, mapping, source)
    assert not proof.coverage_complete
    assert proof.authority_granted is False


def test_human_supplement_cannot_fill_a_missing_text_with_an_unsupported_numeric_gate():
    raw = _native_candidate("ALL").model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"]["conditions"].append(dict(
        type="REVIEWED_FACT", fact_kind="TECHNICAL",
        evidence_requirement="Only buy when turnover exceeds 3 percent.",
        validity_scope="TRADE_DATE"))
    draft = P3PlanDraft.model_validate(raw)
    _, original = source_mapping(draft)
    path = "ordinary_rules[0].condition.conditions[2].evidence_requirement"
    source, mapping, _ = _rebuilt_source(draft, original, replacements={path: None})
    supplement = DailySupplement(supplement_id="missing-text", path=path,
        candidate_content_hash=mapping.candidate_content_hash,
        value="Only buy when turnover exceeds 3 percent.", reason="Human supplies missing text")
    mapping = mapping.model_copy(update={"supplements": (supplement,), "bindings": tuple(
        row.model_copy(update=dict(origin="HUMAN_SUPPLEMENT", clause_ids=(),
            supplement_id=supplement.supplement_id)) if row.path == path else row
        for row in mapping.bindings
    )})
    assert not build_daily_review(draft, mapping, source).issues
    proof = assess_source_coverage(draft, mapping, source, origin="HUMAN")
    assert not proof.coverage_complete
    assert proof.authority_granted is False
