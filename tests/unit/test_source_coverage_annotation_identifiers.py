"""A label-shaped sentence is not independent proof of non-policy meaning."""

from copy import deepcopy

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_coverage_semantics import _native_baseline

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.domain.p3_validation import P3PlanDraft


@pytest.mark.parametrize("instruction", [
    "All-risk-exits-must-wait-for-blue-light",
    "Only-buy-when-turnover-exceeds-3-percent",
])
def test_unregistered_instruction_cannot_become_context_by_replacing_spaces_with_hyphens(
    instruction,
):
    before, _, _ = _native_baseline()
    raw = before.model_dump(mode="json")
    condition = deepcopy(raw["alert_rules"][0]["condition"]["conditions"][0])
    condition["reference"]["source"] = instruction
    raw["ordinary_rules"][0]["condition"]["conditions"].append(condition)
    path = "ordinary_rules[0].condition.conditions[3].reference.source"
    draft = P3PlanDraft.model_validate(raw)
    assert draft.to_executable() is not None
    source, mapping = source_mapping(draft)
    assert build_daily_review(draft, mapping, source).issues == ()
    assert instruction in source

    result = assess_source_coverage(draft, mapping, source)

    assert result.coverage_complete is False
    assert result.authority_granted is False
    unproven = [row for row in result.obligations if path in row.paths]
    assert unproven
    assert all(row.state in {"UNRESOLVED", "UNSUPPORTED"} for row in unproven)
    assert all(row.scope == "UNKNOWN" for row in unproven)
