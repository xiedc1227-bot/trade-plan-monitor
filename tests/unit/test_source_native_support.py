"""Exact source equality must not certify an unsupported runtime configuration."""

from copy import deepcopy
from datetime import date

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_coverage_semantics import _native_baseline

from trade_plan_monitor.ai.daily_review import build_daily_review, semantic_values
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.domain.p3_validation import P3PlanDraft
from trade_plan_monitor.market_data.daily_indicators import PARAMETERS

_REFERENCE = "alert_rules[0].condition.conditions[1].reference"


def _candidate(parameters):
    """Keep source and candidate identical, independently varying runtime support."""
    original, _, _ = _native_baseline()
    raw = original.model_dump(mode="json")
    reference = raw["alert_rules"][0]["condition"]["conditions"][1]["reference"]
    assert reference["indicator"] == "MA20"
    assert reference["formula_version"] == "daily-ta-v2"
    reference["parameters"] = deepcopy(parameters)
    draft = P3PlanDraft.model_validate(raw)
    assert draft.to_executable() is not None
    source, mapping = source_mapping(draft)
    assert {binding.path: binding.value for binding in mapping.bindings} == semantic_values(draft)
    assert build_daily_review(draft, mapping, source).issues == ()
    return draft, source, mapping


def test_registered_ma20_parameters_are_source_covered_and_runtime_supported():
    parameters = {"period": 20}
    assert parameters == PARAMETERS["MA20"]
    draft, source, mapping = _candidate(parameters)
    assert f"{_REFERENCE}.parameters.period = 20" in source

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    assert assessment.authority_granted is False


@pytest.mark.parametrize("parameters", [{}, {"period": 21}, {"turnover": 3}],
                         ids=["missing-period", "wrong-period", "foreign-parameter"])
def test_exactly_mapped_but_unexecutable_ma20_parameters_block_current_coverage(parameters):
    assert parameters != PARAMETERS["MA20"]
    draft, source, mapping = _candidate(parameters)
    source_before, candidate_before = source, draft.model_dump_json()

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    unsupported = [issue for issue in assessment.issues
                   if issue.code == "SOURCE_COVERAGE_UNSUPPORTED"]
    assert unsupported
    assert any(issue.path.startswith(_REFERENCE) for issue in unsupported)
    assert any(isinstance(issue.start, int) and isinstance(issue.end, int)
               and 0 <= issue.start < issue.end <= len(source) for issue in unsupported)
    assert source == source_before and draft.model_dump_json() == candidate_before
    # Current eligibility changes; the independently frozen historical verifier does not.
    assert build_daily_review(draft, mapping, source).issues == ()


def _comparison(*, kind="DAILY_PRICE_COMPARE", indicator="MA20", unit=None):
    reference = ({
        "mode": "FIXED", "value": "1000", "unit": unit, "as_of": date(2026, 9, 1),
        "source": "Exact synthetic fixed threshold",
    } if unit else {
        "mode": "DYNAMIC", "indicator": indicator, "formula_version": "daily-ta-v2",
        "parameters": deepcopy(PARAMETERS[indicator]), "offset": 0,
    })
    return {
        "type": kind, "offset": 0, "comparator": "GT", "reference": reference,
        **({"field": "close"} if kind == "DAILY_PRICE_COMPARE" else {
            "indicator": indicator, "formula_version": "daily-ta-v2",
            "parameters": deepcopy(PARAMETERS[indicator]),
        }),
    }


def _condition_candidate(condition):
    original, _, _ = _candidate({"period": 20})
    raw = original.model_dump(mode="json")
    raw["alert_rules"][0]["condition"]["conditions"][1] = deepcopy(condition)
    draft = P3PlanDraft.model_validate(raw)
    assert draft.to_executable() is not None
    source, mapping = source_mapping(draft)
    assert {binding.path: binding.value for binding in mapping.bindings} == semantic_values(draft)
    assert build_daily_review(draft, mapping, source).issues == ()
    return draft, source, mapping


@pytest.mark.parametrize("condition", [
    _comparison(unit="FEN"),
    _comparison(kind="DAILY_INDICATOR_COMPARE", unit="INDICATOR"),
], ids=["price-with-fixed-fen", "indicator-with-fixed-indicator-unit"])
def test_registered_fixed_reference_units_remain_valid_positive_comparisons(condition):
    draft, source, mapping = _condition_candidate(condition)

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is True
    assert assessment.status == "COMPLETE"
    assert assessment.issues == ()
    assert assessment.authority_granted is False


@pytest.mark.parametrize("condition", [
    _comparison(unit="INDICATOR"),
    _comparison(indicator="RSI14"),
    _comparison(indicator="BOLL_BANDWIDTH"),
    _comparison(kind="DAILY_INDICATOR_COMPARE", unit="FEN"),
], ids=["price-with-fixed-indicator-unit", "price-with-rsi14-reference",
        "price-with-boll-bandwidth-reference", "indicator-with-fixed-fen"])
def test_exactly_mapped_reference_unit_mismatches_block_current_coverage(condition):
    draft, source, mapping = _condition_candidate(condition)
    reference = condition["reference"]
    if reference["mode"] == "DYNAMIC":
        assert reference["parameters"] == PARAMETERS[reference["indicator"]]

    assessment = assess_source_coverage(draft, mapping, source)

    assert assessment.coverage_complete is False
    assert assessment.status == "BLOCKED"
    assert assessment.authority_granted is False
    unsupported = [issue for issue in assessment.issues
                   if issue.code == "SOURCE_COVERAGE_UNSUPPORTED"]
    assert unsupported
    assert any(issue.path.startswith(_REFERENCE) for issue in unsupported)
    assert any(isinstance(issue.start, int) and isinstance(issue.end, int)
               and 0 <= issue.start < issue.end <= len(source) for issue in unsupported)
    assert build_daily_review(draft, mapping, source).issues == ()
