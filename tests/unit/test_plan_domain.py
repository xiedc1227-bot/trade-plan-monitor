import json
from collections.abc import Callable
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trade_plan_monitor.domain.plan_codec import (
    MAX_PLAN_DOCUMENT_BYTES,
    PlanDocumentError,
    dump_plan_json,
    dump_plan_yaml,
    load_plan_json,
    load_plan_yaml,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    DateRangeActivation,
    ManualActivation,
    PositionPolicy,
    PriceZone,
    TradePlan,
    TradingDayActivation,
)
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    DraftReviewIssue,
    MarketEvidence,
    price_zone_owners,
    validate_trade_plan,
)

PlanLoader = Callable[[str | bytes], TradePlan]


def _valid_plan_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "plan_id": "huaya-smart",
        "version": 1,
        "symbol": "003043.SZ",
        "name": "华亚智能",
        "market": "SZSE",
        "metadata": {
            "report_at": "2026-08-06T01:16:00+08:00",
            "reference_price_fen": 6660,
        },
        "activation": {"mode": "MANUAL"},
        "position": {
            "lot_size": 100,
            "max_qty": 200,
            "core_target_qty": 100,
            "tactical_target_qty": 100,
        },
        "levels": {
            "low_buy": {"low_fen": 6300, "high_fen": 6450},
            "pressure": {"low_fen": 6880, "high_fen": 7020},
            "risk_line_fen": 6080,
            "pressure_reference_fen": 6906,
        },
        "entry": {"condition": {"type": "NON_DECREASING_CLOSE"}},
        "reduction": {
            "condition": {
                "type": "UPPER_WICK_RATIO_GTE",
                "minimum_ratio": Decimal("0.40"),
            }
        },
        "risk": {
            "condition": {
                "type": "OFFICIAL_CLOSE_BELOW_LEVEL",
                "level": "RISK_LINE",
            }
        },
        "blockers": {"condition": {"type": "MANUAL_EVENT_RISK_CLEAR"}},
        "monitoring": {
            "timeframe_minutes": 5,
            "indicator_formula_version": "ta-v1",
        },
    }


def _replace_entry_condition(condition: object) -> dict[str, object]:
    payload = _valid_plan_payload()
    payload["entry"] = {"condition": condition}
    return payload


def _nested_all_condition(depth: int) -> dict[str, object]:
    condition: dict[str, object] = {"type": "NON_DECREASING_CLOSE"}
    for _ in range(depth - 1):
        condition = {"type": "ALL", "conditions": [condition]}
    return condition


def test_trade_plan_preserves_integer_fen_and_version_identity() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())

    assert plan.schema_version == 1
    assert plan.plan_id == "huaya-smart"
    assert plan.version == 1
    assert plan.symbol == "003043.SZ"
    assert plan.market == "SZSE"
    assert plan.metadata.reference_price_fen == 6660
    assert plan.levels.low_buy.low_fen == 6300
    assert plan.levels.pressure_reference_fen == 6906
    assert isinstance(plan.activation, ManualActivation)


@pytest.mark.parametrize(
    ("activation", "expected_type"),
    [
        ({"mode": "MANUAL"}, ManualActivation),
        (
            {"mode": "TRADING_DAY", "trading_day": "2026-08-07"},
            TradingDayActivation,
        ),
        (
            {
                "mode": "DATE_RANGE",
                "start_date": "2026-08-07",
                "end_date": "2026-08-14",
            },
            DateRangeActivation,
        ),
    ],
)
def test_activation_policy_uses_the_mode_discriminator(
    activation: dict[str, object],
    expected_type: type[object],
) -> None:
    payload = _valid_plan_payload()
    payload["activation"] = activation

    plan = TradePlan.model_validate(payload)

    assert isinstance(plan.activation, expected_type)


@pytest.mark.parametrize(
    "activation",
    [
        {"mode": "TRADING_DAY"},
        {"mode": "DATE_RANGE", "start_date": "2026-08-07"},
        {"mode": "DATE_RANGE", "end_date": "2026-08-14"},
        {"mode": "AUTOMATIC"},
    ],
)
def test_incomplete_or_unknown_activation_policies_fail(
    activation: dict[str, object],
) -> None:
    payload = _valid_plan_payload()
    payload["activation"] = activation

    with pytest.raises(ValidationError):
        TradePlan.model_validate(payload)


def test_date_range_requires_ordered_dates() -> None:
    payload = _valid_plan_payload()
    payload["activation"] = {
        "mode": "DATE_RANGE",
        "start_date": "2026-08-14",
        "end_date": "2026-08-07",
    }

    with pytest.raises(ValidationError, match="start date cannot be after end date"):
        TradePlan.model_validate(payload)


@pytest.mark.parametrize(
    "symbol",
    ["003043", "003043.SHARE", "A03043.SZ", "003043.sz", "00043.SZ"],
)
def test_invalid_a_share_symbols_fail(symbol: str) -> None:
    payload = _valid_plan_payload()
    payload["symbol"] = symbol

    with pytest.raises(ValidationError):
        TradePlan.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("version", 0),
        ("version", "1"),
        ("plan_id", "../huaya"),
        ("plan_id", ""),
        ("name", " "),
        ("market", "NASDAQ"),
    ],
)
def test_invalid_plan_identity_fields_fail(field: str, value: object) -> None:
    payload = _valid_plan_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        TradePlan.model_validate(payload)


@pytest.mark.parametrize(
    "invalid_price",
    [0, -1, 6300.5, Decimal("6300.5"), "6300"],
)
def test_price_zone_rejects_non_positive_or_non_integer_fen(invalid_price: object) -> None:
    with pytest.raises(ValidationError):
        PriceZone(low_fen=invalid_price, high_fen=6450)


def test_price_zone_requires_ordered_bounds() -> None:
    with pytest.raises(ValidationError, match="lower bound cannot exceed upper bound"):
        PriceZone(low_fen=6451, high_fen=6450)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("risk_line_fen", 0),
        ("risk_line_fen", "6080"),
        ("pressure_reference_fen", 6906.5),
    ],
)
def test_named_price_levels_require_positive_integer_fen(field: str, value: object) -> None:
    payload = _valid_plan_payload()
    levels = payload["levels"]
    assert isinstance(levels, dict)
    levels[field] = value

    with pytest.raises(ValidationError):
        TradePlan.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lot_size", 200),
        ("max_qty", 0),
        ("max_qty", 250),
        ("core_target_qty", -100),
        ("core_target_qty", 50),
        ("tactical_target_qty", "100"),
    ],
)
def test_position_policy_rejects_invalid_board_lots(field: str, value: object) -> None:
    payload = {
        "lot_size": 100,
        "max_qty": 200,
        "core_target_qty": 100,
        "tactical_target_qty": 100,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        PositionPolicy.model_validate(payload)


def test_plan_and_nested_values_are_immutable_versions() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())

    with pytest.raises(ValidationError, match="frozen"):
        plan.version = 2
    with pytest.raises(ValidationError, match="frozen"):
        plan.levels.low_buy.low_fen = 6200


def test_plan_rejects_unknown_fields_at_every_level() -> None:
    payload = deepcopy(_valid_plan_payload())
    payload["enabled"] = True
    position = payload["position"]
    assert isinstance(position, dict)
    position["current_qty"] = 0

    with pytest.raises(ValidationError) as error:
        TradePlan.model_validate(payload)

    rejected_paths = {".".join(map(str, item["loc"])) for item in error.value.errors()}
    assert "enabled" in rejected_paths
    assert "position.current_qty" in rejected_paths


def test_metadata_requires_timezone_aware_report_time() -> None:
    payload = _valid_plan_payload()
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    metadata["report_at"] = "2026-08-06T01:16:00"

    with pytest.raises(ValidationError):
        TradePlan.model_validate(payload)


def test_trading_day_is_parsed_as_a_date() -> None:
    payload = _valid_plan_payload()
    payload["activation"] = {
        "mode": "TRADING_DAY",
        "trading_day": "2026-08-07",
    }

    plan = TradePlan.model_validate(payload)

    assert isinstance(plan.activation, TradingDayActivation)
    assert plan.activation.trading_day == date(2026, 8, 7)


@pytest.mark.parametrize(
    ("condition", "expected_model"),
    [
        (
            {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
            "PriceInZoneCondition",
        ),
        (
            {"type": "NO_NEW_LOW_FOR_BARS", "bars": 2},
            "NoNewLowForBarsCondition",
        ),
        (
            {"type": "NON_DECREASING_CLOSE"},
            "NonDecreasingCloseCondition",
        ),
        (
            {"type": "VOLUME_TO_PREVIOUS_LTE", "max_ratio": Decimal("1.00")},
            "VolumeToPreviousLteCondition",
        ),
        (
            {
                "type": "VOLUME_TO_MEDIAN_LTE",
                "max_ratio": Decimal("1.50"),
                "window_bars": 20,
            },
            "VolumeToMedianLteCondition",
        ),
        (
            {
                "type": "MACD_HIST_IMPROVEMENT_GTE",
                "minimum_improvement": Decimal("0.02"),
            },
            "MacdHistImprovementGteCondition",
        ),
        (
            {"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"},
            "PriceReclaimsIndicatorCondition",
        ),
        (
            {"type": "UPPER_WICK_RATIO_GTE", "minimum_ratio": Decimal("0.40")},
            "UpperWickRatioGteCondition",
        ),
        (
            {
                "type": "RETREAT_FROM_SESSION_HIGH_GTE",
                "minimum_ratio": Decimal("0.01"),
            },
            "RetreatFromSessionHighGteCondition",
        ),
        (
            {"type": "CLOSE_IN_BAR_LOWER_HALF"},
            "CloseInBarLowerHalfCondition",
        ),
        (
            {
                "type": "CONSECUTIVE_CLOSES_BELOW_LEVEL",
                "level": "PRESSURE_REFERENCE",
                "bars": 2,
            },
            "ConsecutiveClosesBelowLevelCondition",
        ),
        (
            {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "RISK_LINE"},
            "OfficialCloseBelowLevelCondition",
        ),
        (
            {"type": "NEXT_TRADING_DAY_RECOVERY", "level": "RISK_LINE"},
            "NextTradingDayRecoveryCondition",
        ),
        (
            {"type": "POSITION_BUCKET_AVAILABLE", "bucket": "TACTICAL"},
            "PositionBucketAvailableCondition",
        ),
        (
            {"type": "SELLABLE_QUANTITY_GTE", "quantity": 100},
            "SellableQuantityGteCondition",
        ),
        (
            {"type": "MANUAL_EVENT_RISK_CLEAR"},
            "ManualEventRiskClearCondition",
        ),
        (
            {
                "type": "DISTANCE_FROM_LIMIT_DOWN_GTE",
                "minimum_ratio": Decimal("0.01"),
            },
            "DistanceFromLimitDownGteCondition",
        ),
        (
            {"type": "LOWER_BAND_HITS_LTE", "max_hits": 3, "window_bars": 4},
            "LowerBandHitsLteCondition",
        ),
    ],
)
def test_schema_v1_condition_type_is_closed_and_typed(
    condition: dict[str, object],
    expected_model: str,
) -> None:
    plan = TradePlan.model_validate(_replace_entry_condition(condition))

    assert type(plan.entry.condition).__name__ == expected_model
    assert plan.entry.condition.type == condition["type"]


def test_condition_composition_supports_only_all_and_any() -> None:
    condition = {
        "type": "ALL",
        "conditions": [
            {"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"},
            {
                "type": "ANY",
                "conditions": [
                    {"type": "NON_DECREASING_CLOSE"},
                    {"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "EMA10"},
                ],
            },
        ],
    }

    plan = TradePlan.model_validate(_replace_entry_condition(condition))

    assert plan.entry.condition.type == "ALL"
    nested = plan.entry.condition.conditions[1]
    assert nested.type == "ANY"
    assert tuple(child.type for child in nested.conditions) == (
        "NON_DECREASING_CLOSE",
        "PRICE_RECLAIMS_INDICATOR",
    )


def test_condition_json_schema_exposes_only_the_twenty_allowlisted_tags() -> None:
    schema = TradePlan.model_json_schema()
    definitions = schema["$defs"]
    mapping = definitions["EntryPolicy"]["properties"]["condition"]["discriminator"]["mapping"]

    assert set(mapping) == {
        "ALL",
        "ANY",
        "CLOSE_IN_BAR_LOWER_HALF",
        "CONSECUTIVE_CLOSES_BELOW_LEVEL",
        "DISTANCE_FROM_LIMIT_DOWN_GTE",
        "LOWER_BAND_HITS_LTE",
        "MACD_HIST_IMPROVEMENT_GTE",
        "MANUAL_EVENT_RISK_CLEAR",
        "NEXT_TRADING_DAY_RECOVERY",
        "NON_DECREASING_CLOSE",
        "NO_NEW_LOW_FOR_BARS",
        "OFFICIAL_CLOSE_BELOW_LEVEL",
        "POSITION_BUCKET_AVAILABLE",
        "PRICE_IN_ZONE",
        "PRICE_RECLAIMS_INDICATOR",
        "RETREAT_FROM_SESSION_HIGH_GTE",
        "SELLABLE_QUANTITY_GTE",
        "UPPER_WICK_RATIO_GTE",
        "VOLUME_TO_MEDIAN_LTE",
        "VOLUME_TO_PREVIOUS_LTE",
    }
    assert (
        definitions["EntryPolicy"]["properties"]["condition"]["discriminator"]["propertyName"]
        == "type"
    )


def test_condition_nesting_depth_four_is_valid() -> None:
    plan = TradePlan.model_validate(_replace_entry_condition(_nested_all_condition(4)))

    assert plan.entry.condition.type == "ALL"


def test_condition_nesting_depth_above_four_fails() -> None:
    with pytest.raises(ValidationError, match="depth cannot exceed 4"):
        TradePlan.model_validate(_replace_entry_condition(_nested_all_condition(5)))


def test_condition_leaf_limit_is_fifty_per_plan() -> None:
    payload = _replace_entry_condition(
        {
            "type": "ALL",
            "conditions": [{"type": "NON_DECREASING_CLOSE"} for _ in range(47)],
        }
    )

    plan = TradePlan.model_validate(payload)

    assert len(plan.entry.condition.conditions) == 47


def test_condition_leaf_count_above_fifty_per_plan_fails() -> None:
    payload = _replace_entry_condition(
        {
            "type": "ALL",
            "conditions": [{"type": "NON_DECREASING_CLOSE"} for _ in range(48)],
        }
    )

    with pytest.raises(ValidationError, match="leaf count cannot exceed 50"):
        TradePlan.model_validate(payload)


@pytest.mark.parametrize(
    "condition",
    [
        {"type": "ALL", "conditions": []},
        {"type": "NO_NEW_LOW_FOR_BARS", "bars": 0},
        {"type": "NO_NEW_LOW_FOR_BARS", "bars": "2"},
        {"type": "PRICE_IN_ZONE", "zone": "levels.low_buy"},
        {"type": "VOLUME_TO_PREVIOUS_LTE", "max_ratio": Decimal("NaN")},
        {"type": "VOLUME_TO_PREVIOUS_LTE", "max_ratio": "__import__('os')"},
        {"type": "VOLUME_TO_PREVIOUS_LTE", "max_ratio": Decimal("10.01")},
        {
            "type": "VOLUME_TO_MEDIAN_LTE",
            "max_ratio": Decimal("1.50"),
            "window_bars": 501,
        },
        {"type": "MACD_HIST_IMPROVEMENT_GTE", "minimum_improvement": Decimal("0")},
        {"type": "PRICE_RECLAIMS_INDICATOR", "indicator": "CUSTOM_FORMULA"},
        {"type": "UPPER_WICK_RATIO_GTE", "minimum_ratio": Decimal("1.01")},
        {"type": "OFFICIAL_CLOSE_BELOW_LEVEL", "level": "prices.risk"},
        {"type": "POSITION_BUCKET_AVAILABLE", "bucket": "ARBITRARY"},
        {"type": "SELLABLE_QUANTITY_GTE", "quantity": 50},
        {"type": "LOWER_BAND_HITS_LTE", "max_hits": 5, "window_bars": 4},
    ],
)
def test_condition_parameters_are_bounded(condition: dict[str, object]) -> None:
    with pytest.raises(ValidationError) as error:
        TradePlan.model_validate(_replace_entry_condition(condition))

    assert any(item["loc"][:2] == ("entry", "condition") for item in error.value.errors())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expression", "price > 6300"),
        ("script", "__import__('os').system('whoami')"),
        ("sql", "DROP TABLE trade_plan"),
        ("field_path", "__class__.__mro__"),
        ("import", "os.system"),
        ("call", "https://example.invalid/run"),
    ],
)
def test_condition_expression_sql_paths_imports_and_calls_fail(
    field: str,
    value: str,
) -> None:
    condition = {"type": "NON_DECREASING_CLOSE", field: value}

    with pytest.raises(ValidationError) as error:
        TradePlan.model_validate(_replace_entry_condition(condition))

    assert any(item["loc"][-1] == field for item in error.value.errors())


@pytest.mark.parametrize(
    "condition",
    [
        "price > 6300",
        {"type": "PYTHON_EXPRESSION", "expression": "price > 6300"},
        {"type": "AND", "conditions": [{"type": "NON_DECREASING_CLOSE"}]},
    ],
)
def test_raw_expression_and_unknown_condition_types_fail(condition: object) -> None:
    with pytest.raises(ValidationError) as error:
        TradePlan.model_validate(_replace_entry_condition(condition))

    assert any(item["loc"][:2] == ("entry", "condition") for item in error.value.errors())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeframe_minutes", 1),
        ("indicator_formula_version", "python-eval-v1"),
    ],
)
def test_monitoring_condition_context_is_allowlisted(field: str, value: object) -> None:
    payload = _valid_plan_payload()
    monitoring = payload["monitoring"]
    assert isinstance(monitoring, dict)
    monitoring[field] = value

    with pytest.raises(ValidationError) as error:
        TradePlan.model_validate(payload)

    assert any(item["loc"] == ("monitoring", field) for item in error.value.errors())


def test_condition_values_are_immutable() -> None:
    plan = TradePlan.model_validate(
        _replace_entry_condition({"type": "PRICE_IN_ZONE", "zone": "LOW_BUY"})
    )

    with pytest.raises(ValidationError, match="frozen"):
        plan.entry.condition.zone = "PRESSURE"


def test_validation_accepts_the_complete_valid_plan() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert result.issues == ()
    assert result.can_save is True
    assert result.can_activate is True


@pytest.mark.parametrize(
    ("symbol", "market", "expected_market"),
    [
        ("003043.SZ", "SSE", "SZSE"),
        ("600519.SH", "BSE", "SSE"),
        ("920001.BJ", "SZSE", "BSE"),
    ],
)
def test_validation_rejects_symbol_market_mismatches(
    symbol: str,
    market: str,
    expected_market: str,
) -> None:
    payload = _valid_plan_payload()
    payload["symbol"] = symbol
    payload["market"] = market
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    issue = next(item for item in result.issues if item.code == "SYMBOL_MARKET_MISMATCH")
    assert issue.path == "market"
    assert issue.severity == "ERROR"
    assert issue.activation_blocking is True
    assert expected_market in issue.message
    assert result.can_save is False
    assert result.can_activate is False


@pytest.mark.parametrize(
    ("core_qty", "tactical_qty", "expected_code"),
    [
        (0, 0, "POSITION_TARGET_EMPTY"),
        (200, 100, "POSITION_TARGET_EXCEEDS_MAX"),
    ],
)
def test_validation_enforces_positive_bounded_position_targets(
    core_qty: int,
    tactical_qty: int,
    expected_code: str,
) -> None:
    payload = _valid_plan_payload()
    position = payload["position"]
    assert isinstance(position, dict)
    position["core_target_qty"] = core_qty
    position["tactical_target_qty"] = tactical_qty
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert expected_code in {item.code for item in result.issues}
    assert result.can_save is False


def test_validation_accepts_position_targets_equal_to_the_maximum() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert not any(item.code.startswith("POSITION_TARGET_") for item in result.issues)


@pytest.mark.parametrize(
    ("low_buy", "pressure"),
    [
        (
            {"low_fen": 6300, "high_fen": 6900},
            {"low_fen": 6880, "high_fen": 7020},
        ),
        (
            {"low_fen": 6300, "high_fen": 6880, "include_high": True},
            {"low_fen": 6880, "high_fen": 7020, "include_low": True},
        ),
    ],
)
def test_validation_rejects_overlapping_or_double_owned_action_zones(
    low_buy: dict[str, object],
    pressure: dict[str, object],
) -> None:
    payload = _valid_plan_payload()
    levels = payload["levels"]
    assert isinstance(levels, dict)
    levels["low_buy"] = low_buy
    levels["pressure"] = pressure
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert "PRICE_ZONES_OVERLAP" in {item.code for item in result.issues}
    assert result.can_save is False


def test_validation_allows_touching_zones_with_one_boundary_owner() -> None:
    payload = _valid_plan_payload()
    levels = payload["levels"]
    assert isinstance(levels, dict)
    levels["low_buy"] = {"low_fen": 6300, "high_fen": 6880}
    levels["pressure"] = {
        "low_fen": 6880,
        "high_fen": 7020,
        "include_low": False,
    }
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert "PRICE_ZONES_OVERLAP" not in {item.code for item in result.issues}
    assert price_zone_owners(plan.levels, 6880) == ("LOW_BUY",)


def test_validation_rejects_a_zone_with_no_owned_integer_fen_price() -> None:
    payload = _valid_plan_payload()
    levels = payload["levels"]
    assert isinstance(levels, dict)
    levels["low_buy"] = {
        "low_fen": 6300,
        "high_fen": 6301,
        "include_low": False,
        "include_high": False,
    }
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    issue = next(item for item in result.issues if item.code == "PRICE_ZONE_EMPTY")
    assert issue.path == "levels.low_buy"
    assert result.can_save is False


def test_validation_uses_discrete_fen_when_checking_zone_overlap() -> None:
    payload = _valid_plan_payload()
    levels = payload["levels"]
    assert isinstance(levels, dict)
    levels["low_buy"] = {
        "low_fen": 6300,
        "high_fen": 6301,
        "include_high": False,
    }
    levels["pressure"] = {
        "low_fen": 6300,
        "high_fen": 6301,
        "include_low": False,
    }
    levels["pressure_reference_fen"] = 6301
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert price_zone_owners(plan.levels, 6300) == ("LOW_BUY",)
    assert price_zone_owners(plan.levels, 6301) == ("PRESSURE",)
    assert "PRICE_ZONES_OVERLAP" not in {item.code for item in result.issues}


def test_validation_sample_boundaries_have_exactly_one_owner() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())

    assert price_zone_owners(plan.levels, 6450) == ("LOW_BUY",)
    assert price_zone_owners(plan.levels, 6880) == ("PRESSURE",)


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("risk_line_fen", 6300, "RISK_LINE_NOT_BELOW_LOW_BUY"),
        (
            "pressure_reference_fen",
            6800,
            "PRESSURE_REFERENCE_OUTSIDE_ZONE",
        ),
    ],
)
def test_validation_enforces_named_level_relationships(
    field: str,
    value: int,
    expected_code: str,
) -> None:
    payload = _valid_plan_payload()
    levels = payload["levels"]
    assert isinstance(levels, dict)
    levels[field] = value
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert expected_code in {item.code for item in result.issues}
    assert result.can_save is False


def test_validation_blocks_activation_when_required_market_evidence_is_missing() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())
    evidence = ALL_MARKET_EVIDENCE - {MarketEvidence.OFFICIAL_DAILY_BARS}

    result = validate_trade_plan(
        plan,
        available_market_evidence=evidence,
    )

    issue = next(item for item in result.issues if item.code == "MARKET_EVIDENCE_UNAVAILABLE")
    assert issue.path == "risk.condition"
    assert issue.severity == "WARNING"
    assert issue.activation_blocking is True
    assert "OFFICIAL_DAILY_BARS" in issue.message
    assert result.can_save is True
    assert result.can_activate is False


def test_validation_reports_nested_condition_evidence_with_stable_paths() -> None:
    payload = _replace_entry_condition(
        {
            "type": "ALL",
            "conditions": [
                {"type": "NON_DECREASING_CLOSE"},
                {
                    "type": "MACD_HIST_IMPROVEMENT_GTE",
                    "minimum_improvement": Decimal("0.01"),
                },
            ],
        }
    )
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=frozenset(),
    )

    missing_paths = {
        item.path for item in result.issues if item.code == "MARKET_EVIDENCE_UNAVAILABLE"
    }
    assert "entry.condition.conditions[0]" in missing_paths
    assert "entry.condition.conditions[1]" in missing_paths


def test_validation_blocks_unresolved_material_ai_review_issues() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())
    review_issue = DraftReviewIssue(
        kind="UNMAPPED_TEXT",
        path="source.unmapped[0]",
        material=True,
    )

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
        review_issues=(review_issue,),
    )

    issue = next(item for item in result.issues if item.code == "UNRESOLVED_MATERIAL_AI_ISSUE")
    assert issue.path == "source.unmapped[0]"
    assert issue.severity == "WARNING"
    assert issue.activation_blocking is True
    assert result.can_save is True
    assert result.can_activate is False


def test_validation_ignores_resolved_ai_review_issues() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())
    review_issue = DraftReviewIssue(
        kind="ASSUMPTION",
        path="entry.condition",
        material=True,
        resolved=True,
    )

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
        review_issues=(review_issue,),
    )

    assert result.issues == ()
    assert result.can_activate is True


@pytest.mark.parametrize("kind", ["ASSUMPTION", "WARNING", "MISSING_EVIDENCE"])
def test_validation_blocks_unresolved_ai_assumptions_warnings_and_evidence_gaps(
    kind: str,
) -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())
    review_issue = DraftReviewIssue(
        kind=kind,
        path="metadata.report_at",
        material=False,
    )

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
        review_issues=(review_issue,),
    )

    issue = next(item for item in result.issues if item.code == "UNRESOLVED_AI_REVIEW_ISSUE")
    assert issue.activation_blocking is True
    assert result.can_save is True
    assert result.can_activate is False


def test_validation_keeps_an_ordinary_non_material_review_warning_non_blocking() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())
    review_issue = DraftReviewIssue(
        kind="UNMAPPED_TEXT",
        path="source.unmapped[0]",
        material=False,
    )

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
        review_issues=(review_issue,),
    )

    issue = next(item for item in result.issues if item.code == "UNRESOLVED_AI_WARNING")
    assert issue.activation_blocking is False
    assert result.can_save is True
    assert result.can_activate is True


def test_validation_issue_serialization_has_stable_public_fields() -> None:
    payload = _valid_plan_payload()
    payload["market"] = "SSE"
    plan = TradePlan.model_validate(payload)

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert result.issues[0].model_dump(mode="json", by_alias=True) == {
        "code": "SYMBOL_MARKET_MISMATCH",
        "path": "market",
        "severity": "ERROR",
        "message": "Symbol suffix .SZ requires market SZSE.",
        "activationBlocking": True,
    }


def test_validation_review_input_rejects_arbitrary_ai_text_fields() -> None:
    with pytest.raises(ValidationError):
        DraftReviewIssue.model_validate(
            {
                "kind": "WARNING",
                "path": "entry.condition",
                "material": True,
                "message": "<script>alert(1)</script>",
            }
        )


def test_codec_round_trips_yaml_and_json_without_precision_loss() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())

    from_json = load_plan_json(dump_plan_json(plan))
    from_yaml = load_plan_yaml(dump_plan_yaml(plan))

    assert from_json == plan
    assert from_yaml == plan
    assert load_plan_json(dump_plan_json(plan).encode("utf-8")) == plan
    assert load_plan_yaml(dump_plan_yaml(plan).encode("utf-8")) == plan
    assert from_yaml.levels.low_buy.high_fen == 6450
    assert from_yaml.reduction.condition.minimum_ratio == Decimal("0.40")


def test_json_export_is_canonical_and_independent_of_input_key_order() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())
    canonical = dump_plan_json(plan)
    data = json.loads(canonical)
    reversed_data = {key: data[key] for key in reversed(tuple(data))}

    reordered_plan = load_plan_json(json.dumps(reversed_data, ensure_ascii=False))

    assert dump_plan_json(reordered_plan) == canonical
    assert canonical == json.dumps(
        data,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_plan_hash_is_stable_and_sensitive_to_one_fen_or_one_board_lot() -> None:
    plan = TradePlan.model_validate(_valid_plan_payload())
    one_fen_payload = deepcopy(_valid_plan_payload())
    one_fen_levels = one_fen_payload["levels"]
    assert isinstance(one_fen_levels, dict)
    low_buy = one_fen_levels["low_buy"]
    assert isinstance(low_buy, dict)
    low_buy["low_fen"] = 6301
    one_lot_payload = deepcopy(_valid_plan_payload())
    one_lot_position = one_lot_payload["position"]
    assert isinstance(one_lot_position, dict)
    one_lot_position["tactical_target_qty"] = 0

    original_hash = plan_sha256(plan)

    assert plan_sha256(plan) == original_hash
    assert plan_sha256(TradePlan.model_validate(one_fen_payload)) != original_hash
    assert plan_sha256(TradePlan.model_validate(one_lot_payload)) != original_hash
    assert len(original_hash) == 64


def test_one_share_change_is_rejected_instead_of_rounded_before_hashing() -> None:
    plan_data = json.loads(dump_plan_json(TradePlan.model_validate(_valid_plan_payload())))
    plan_data["position"]["core_target_qty"] = 101

    with pytest.raises(PlanDocumentError) as error:
        load_plan_json(json.dumps(plan_data, ensure_ascii=False))

    assert error.value.code == "INVALID_PLAN"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_import_rejects_non_finite_numbers(constant: str) -> None:
    document = dump_plan_json(TradePlan.model_validate(_valid_plan_payload()))
    document = document.replace('"reference_price_fen":6660', f'"reference_price_fen":{constant}')

    with pytest.raises(PlanDocumentError) as error:
        load_plan_json(document)

    assert error.value.code == "UNSUPPORTED_VALUE"


@pytest.mark.parametrize("constant", [".nan", ".inf", "-.inf"])
def test_yaml_import_rejects_non_finite_numbers(constant: str) -> None:
    document = dump_plan_yaml(TradePlan.model_validate(_valid_plan_payload()))
    document = document.replace("reference_price_fen: 6660", f"reference_price_fen: {constant}")

    with pytest.raises(PlanDocumentError) as error:
        load_plan_yaml(document)

    assert error.value.code == "UNSUPPORTED_VALUE"


def test_yaml_import_rejects_python_object_tags() -> None:
    document = '!!python/object/new:builtins.str ["not-a-plan"]'

    with pytest.raises(PlanDocumentError) as error:
        load_plan_yaml(document)

    assert error.value.code == "INVALID_SYNTAX"


@pytest.mark.parametrize(
    ("loader", "document"),
    [
        (
            load_plan_json,
            dump_plan_json(TradePlan.model_validate(_valid_plan_payload())).replace(
                '"version":1',
                '"version":1,"version":2',
            ),
        ),
        (
            load_plan_yaml,
            dump_plan_yaml(TradePlan.model_validate(_valid_plan_payload())).replace(
                "\nversion: 1\n",
                "\nversion: 1\nversion: 2\n",
                1,
            ),
        ),
    ],
)
def test_plan_import_rejects_duplicate_mapping_keys(
    loader: PlanLoader,
    document: str,
) -> None:
    with pytest.raises(PlanDocumentError) as error:
        loader(document)

    assert error.value.code == "DUPLICATE_KEY"


@pytest.mark.parametrize("loader", [load_plan_json, load_plan_yaml])
def test_plan_import_rejects_oversized_text_before_parsing(loader: PlanLoader) -> None:
    oversized_document = "华" * (MAX_PLAN_DOCUMENT_BYTES // 3 + 1)

    with pytest.raises(PlanDocumentError) as error:
        loader(oversized_document)

    assert error.value.code == "DOCUMENT_TOO_LARGE"


@pytest.mark.parametrize(
    ("loader", "document"),
    [
        (load_plan_json, "[]"),
        (load_plan_yaml, "- not\n- a\n- plan\n"),
    ],
)
def test_plan_import_requires_one_mapping_root(
    loader: PlanLoader,
    document: str,
) -> None:
    with pytest.raises(PlanDocumentError) as error:
        loader(document)

    assert error.value.code == "INVALID_ROOT"


@pytest.mark.parametrize("loader", [load_plan_json, load_plan_yaml])
def test_plan_import_rejects_invalid_utf8_bytes(loader: PlanLoader) -> None:
    with pytest.raises(PlanDocumentError) as error:
        loader(b"\xff")

    assert error.value.code == "INVALID_ENCODING"


def test_yaml_import_rejects_recursive_alias_graphs() -> None:
    document = "root: &root\n  self: *root\n"

    with pytest.raises(PlanDocumentError) as error:
        load_plan_yaml(document)

    assert error.value.code == "UNSUPPORTED_VALUE"


def test_huaya_sample_is_valid_stable_and_round_trips() -> None:
    sample_path = Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"

    plan = load_plan_yaml(sample_path.read_text(encoding="utf-8"))
    validation = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    assert plan.symbol == "003043.SZ"
    assert plan.name == "华亚智能"
    assert plan.metadata.reference_price_fen == 6660
    assert plan.position.max_qty == 200
    assert plan.position.core_target_qty == 100
    assert plan.position.tactical_target_qty == 100
    assert plan.levels.low_buy.model_dump() == {
        "low_fen": 6300,
        "high_fen": 6450,
        "include_low": True,
        "include_high": True,
    }
    assert plan.levels.pressure.model_dump() == {
        "low_fen": 6880,
        "high_fen": 7020,
        "include_low": True,
        "include_high": True,
    }
    assert plan.levels.risk_line_fen == 6080
    assert plan.entry.condition.type == "ALL"
    assert tuple(child.type for child in plan.entry.condition.conditions) == (
        "PRICE_IN_ZONE",
        "NO_NEW_LOW_FOR_BARS",
        "NON_DECREASING_CLOSE",
        "VOLUME_TO_PREVIOUS_LTE",
        "VOLUME_TO_MEDIAN_LTE",
        "ANY",
    )
    entry_momentum = plan.entry.condition.conditions[-1]
    assert tuple(child.type for child in entry_momentum.conditions) == (
        "MACD_HIST_IMPROVEMENT_GTE",
        "PRICE_RECLAIMS_INDICATOR",
    )
    assert plan.reduction.condition.type == "ALL"
    assert tuple(child.type for child in plan.reduction.condition.conditions) == (
        "PRICE_IN_ZONE",
        "SELLABLE_QUANTITY_GTE",
        "ANY",
    )
    pressure_patterns = plan.reduction.condition.conditions[-1]
    assert tuple(child.type for child in pressure_patterns.conditions) == (
        "UPPER_WICK_RATIO_GTE",
        "RETREAT_FROM_SESSION_HIGH_GTE",
        "ALL",
        "CONSECUTIVE_CLOSES_BELOW_LEVEL",
    )
    assert validation.can_save is True
    assert validation.can_activate is True
    assert load_plan_json(dump_plan_json(plan)) == plan
    assert load_plan_yaml(dump_plan_yaml(plan)) == plan
    assert plan_sha256(plan) == "8d057c6d437f0fa059b00ca7538893c4bfa6cbf1c7a1acbbdf4f5a02efde5ea6"
