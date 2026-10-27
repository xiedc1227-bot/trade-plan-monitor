"""A registered manual atom must retain its exact technical kind."""

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_coverage_adversarial import _native_candidate

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
