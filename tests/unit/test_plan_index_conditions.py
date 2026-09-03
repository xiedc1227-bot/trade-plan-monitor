"""Schema v2 board-index binding and condition allow-list contracts."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    MarketEvidence,
    migrate_trade_plan_to_schema_v2,
    validate_trade_plan,
)
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    ReturnFactRequest,
    ReturnWindow,
    SmaFactRequest,
    SmaLookbackFactRequest,
)
from trade_plan_monitor.market_index.requirements import (
    iter_plan_index_conditions,
    plan_index_fact_requests,
)


def _v1_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "plan_id": "v1-baseline",
        "version": 1,
        "symbol": "003043.SZ",
        "name": "V1 baseline",
        "market": "SZSE",
        "metadata": {},
        "activation": {"mode": "MANUAL"},
        "position": {"max_qty": 100, "core_target_qty": 100},
        "levels": {
            "low_buy": {"low_fen": 1000, "high_fen": 1100},
            "pressure": {"low_fen": 1200, "high_fen": 1300},
            "risk_line_fen": 900,
            "pressure_reference_fen": 1250,
        },
        "entry": {"condition": {"type": "NON_DECREASING_CLOSE"}},
        "reduction": {"condition": {"type": "CLOSE_IN_BAR_LOWER_HALF"}},
        "risk": {
            "condition": {
                "type": "OFFICIAL_CLOSE_BELOW_LEVEL",
                "level": "RISK_LINE",
            }
        },
        "blockers": {"condition": {"type": "MANUAL_EVENT_RISK_CLEAR"}},
        "monitoring": {},
    }


def _v2_payload(*, condition: dict[str, object] | None = None) -> dict[str, object]:
    payload = deepcopy(_v1_payload())
    payload["schema_version"] = 2
    payload["version"] = 2
    payload["reference_market"] = {
        "selection": "AUTO_BOARD",
        "mapping_version": "board-index-map-v1",
        "index_code": "399001.SZ",
    }
    if condition is not None:
        payload["entry"] = {"condition": condition}
    return payload


VALID_INDEX_CONDITIONS = (
    {"type": "INDEX_CLOSE_GTE_MA", "index_role": "BOARD_REFERENCE", "period": 2},
    {"type": "INDEX_CLOSE_LTE_MA", "index_role": "BOARD_REFERENCE", "period": 250},
    {
        "type": "INDEX_MA_NON_DECREASING",
        "index_role": "BOARD_REFERENCE",
        "period": 2,
        "lookback": 1,
    },
    {
        "type": "INDEX_MA_NON_INCREASING",
        "index_role": "BOARD_REFERENCE",
        "period": 250,
        "lookback": 60,
    },
    {
        "type": "INDEX_RETURN_GTE",
        "index_role": "BOARD_REFERENCE",
        "window": "FIVE_MINUTE_BUCKETS",
        "window_size": 1,
        "threshold_ratio": Decimal("-1"),
    },
    {
        "type": "INDEX_RETURN_LTE",
        "index_role": "BOARD_REFERENCE",
        "window": "OFFICIAL_OPEN_DAYS",
        "window_size": 250,
        "threshold_ratio": Decimal("10"),
    },
)


def test_schema_v1_canonical_bytes_and_hash_do_not_drift() -> None:
    plan = TradePlan.model_validate(_v1_payload())

    assert "reference_market" not in dump_plan_json(plan)
    assert plan_sha256(plan) == "5783545ccd20f3c35c9393c2468eb59057a36f0b0cc33a21a5abd3fc16daf977"


@pytest.mark.parametrize("condition", VALID_INDEX_CONDITIONS)
def test_schema_v1_rejects_every_index_condition(condition: dict[str, object]) -> None:
    payload = _v1_payload()
    payload["entry"] = {"condition": condition}

    with pytest.raises(ValidationError, match="Schema v1"):
        TradePlan.model_validate(payload)


@pytest.mark.parametrize("condition", VALID_INDEX_CONDITIONS)
def test_schema_v2_accepts_all_six_index_leaves_at_inclusive_bounds(
    condition: dict[str, object],
) -> None:
    plan = TradePlan.model_validate(_v2_payload(condition=condition))

    assert plan.schema_version == 2
    assert plan.reference_market is not None
    assert plan.reference_market.index_code is MarketIndexCode.SHENZHEN_COMPONENT
    assert plan.entry.condition.type == condition["type"]


@pytest.mark.parametrize(
    "condition",
    [
        {"type": "INDEX_CLOSE_GTE_MA", "index_role": "BOARD_REFERENCE", "period": 1},
        {"type": "INDEX_CLOSE_LTE_MA", "index_role": "BOARD_REFERENCE", "period": 251},
        {
            "type": "INDEX_MA_NON_DECREASING",
            "index_role": "BOARD_REFERENCE",
            "period": 20,
            "lookback": 0,
        },
        {
            "type": "INDEX_MA_NON_INCREASING",
            "index_role": "BOARD_REFERENCE",
            "period": 20,
            "lookback": 61,
        },
        {
            "type": "INDEX_RETURN_GTE",
            "index_role": "BOARD_REFERENCE",
            "window": "FIVE_MINUTE_BUCKETS",
            "window_size": 0,
            "threshold_ratio": Decimal("0"),
        },
        {
            "type": "INDEX_RETURN_LTE",
            "index_role": "BOARD_REFERENCE",
            "window": "OFFICIAL_OPEN_DAYS",
            "window_size": 251,
            "threshold_ratio": Decimal("0"),
        },
        {
            "type": "INDEX_RETURN_GTE",
            "index_role": "BOARD_REFERENCE",
            "window": "MINUTES",
            "window_size": 5,
            "threshold_ratio": Decimal("0"),
        },
        {
            "type": "INDEX_RETURN_LTE",
            "index_role": "BOARD_REFERENCE",
            "window": "OFFICIAL_OPEN_DAYS",
            "window_size": 5,
            "threshold_ratio": Decimal("10.01"),
        },
        {
            "type": "INDEX_RETURN_GTE",
            "index_role": "BOARD_REFERENCE",
            "window": "OFFICIAL_OPEN_DAYS",
            "window_size": 5,
            "threshold_ratio": Decimal("-1.01"),
        },
    ],
)
def test_schema_v2_index_parameters_fail_outside_exact_bounds(
    condition: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TradePlan.model_validate(_v2_payload(condition=condition))


@pytest.mark.parametrize(
    "value",
    [0.1, "1e-1", "0.10", "+0.1", "-0", Decimal("0.10"), Decimal("NaN")],
)
def test_threshold_ratio_rejects_binary_float_and_noncanonical_values(value: object) -> None:
    condition = {
        "type": "INDEX_RETURN_GTE",
        "index_role": "BOARD_REFERENCE",
        "window": "OFFICIAL_OPEN_DAYS",
        "window_size": 5,
        "threshold_ratio": value,
    }

    with pytest.raises(ValidationError):
        TradePlan.model_validate(_v2_payload(condition=condition))


@pytest.mark.parametrize(
    "mutation",
    [
        {"selection": "MANUAL", "mapping_version": "board-index-map-v1", "index_code": "399001.SZ"},
        {
            "selection": "AUTO_BOARD",
            "mapping_version": "board-index-map-v2",
            "index_code": "399001.SZ",
        },
        {
            "selection": "AUTO_BOARD",
            "mapping_version": "board-index-map-v1",
            "index_code": "399006.SZ",
        },
    ],
)
def test_schema_v2_recomputes_and_rejects_binding_mismatch(
    mutation: dict[str, object],
) -> None:
    payload = _v2_payload()
    payload["reference_market"] = mutation

    with pytest.raises(ValidationError):
        TradePlan.model_validate(payload)


def test_schema_versions_have_explicit_reference_market_boundaries() -> None:
    missing = _v2_payload()
    del missing["reference_market"]
    with pytest.raises(ValidationError, match="Schema v2"):
        TradePlan.model_validate(missing)

    v1_with_binding = _v1_payload()
    v1_with_binding["reference_market"] = _v2_payload()["reference_market"]
    with pytest.raises(ValidationError, match="Schema v1"):
        TradePlan.model_validate(v1_with_binding)


def test_explicit_migration_creates_new_v2_version_without_mutating_v1() -> None:
    original = TradePlan.model_validate(_v1_payload())
    original_json = dump_plan_json(original)

    migrated = migrate_trade_plan_to_schema_v2(original, new_version=2)

    assert dump_plan_json(original) == original_json
    assert original.schema_version == 1
    assert migrated.schema_version == 2
    assert migrated.version == 2
    assert migrated.reference_market is not None
    assert migrated.reference_market.index_code is MarketIndexCode.SHENZHEN_COMPONENT
    assert plan_sha256(migrated) != plan_sha256(original)
    assert load_plan_json(dump_plan_json(migrated)) == migrated


def test_migration_requires_a_newer_version_and_only_accepts_v1() -> None:
    original = TradePlan.model_validate(_v1_payload())
    with pytest.raises(ValueError, match="new immutable version"):
        migrate_trade_plan_to_schema_v2(original, new_version=1)

    migrated = migrate_trade_plan_to_schema_v2(original, new_version=2)
    with pytest.raises(ValueError, match="Schema v1"):
        migrate_trade_plan_to_schema_v2(migrated, new_version=3)


def test_binding_and_condition_parameters_participate_in_schema_v2_hash() -> None:
    first_payload = _v2_payload(condition=deepcopy(VALID_INDEX_CONDITIONS[4]))
    second_payload = deepcopy(first_payload)
    second_entry = second_payload["entry"]
    assert isinstance(second_entry, dict)
    second_condition = second_entry["condition"]
    assert isinstance(second_condition, dict)
    second_condition["threshold_ratio"] = Decimal("0")

    first = TradePlan.model_validate(first_payload)
    second = TradePlan.model_validate(second_payload)

    assert plan_sha256(first) != plan_sha256(second)


def test_schema_v2_index_leaf_declares_its_activation_evidence_capability() -> None:
    plan = TradePlan.model_validate(_v2_payload(condition=deepcopy(VALID_INDEX_CONDITIONS[0])))

    result = validate_trade_plan(
        plan,
        available_market_evidence=ALL_MARKET_EVIDENCE - {MarketEvidence.BOARD_INDEX_DATA},
    )

    assert not result.can_activate
    assert tuple(issue.path for issue in result.issues) == ("entry.condition",)
    assert "BOARD_INDEX_DATA" in result.issues[0].message


def test_plan_requirements_are_deduplicated_and_retain_exact_leaf_paths() -> None:
    payload = _v2_payload()
    payload["entry"] = {
        "condition": {
            "type": "ALL",
            "conditions": [
                {
                    "type": "INDEX_CLOSE_GTE_MA",
                    "index_role": "BOARD_REFERENCE",
                    "period": 20,
                },
                {
                    "type": "INDEX_CLOSE_LTE_MA",
                    "index_role": "BOARD_REFERENCE",
                    "period": 20,
                },
                {
                    "type": "INDEX_MA_NON_DECREASING",
                    "index_role": "BOARD_REFERENCE",
                    "period": 20,
                    "lookback": 5,
                },
            ],
        }
    }
    payload["risk"] = {
        "condition": {
            "type": "INDEX_RETURN_GTE",
            "index_role": "BOARD_REFERENCE",
            "window": "OFFICIAL_OPEN_DAYS",
            "window_size": 5,
            "threshold_ratio": Decimal("-0.03"),
        }
    }
    plan = TradePlan.model_validate(payload)

    leaves = iter_plan_index_conditions(plan)
    requests = plan_index_fact_requests(plan)

    assert tuple(path for path, _condition in leaves) == (
        "entry.condition.conditions[0]",
        "entry.condition.conditions[1]",
        "entry.condition.conditions[2]",
        "risk.condition",
    )
    assert requests == tuple(
        sorted(
            (
                SmaFactRequest(period=20),
                SmaLookbackFactRequest(period=20, lookback=5),
                ReturnFactRequest(
                    window=ReturnWindow.OFFICIAL_OPEN_DAYS,
                    window_size=5,
                ),
            ),
            key=lambda item: item.model_dump_json(),
        )
    )


def test_v2_plan_without_index_leaf_has_no_fact_requirement() -> None:
    plan = TradePlan.model_validate(_v2_payload())

    assert iter_plan_index_conditions(plan) == ()
    assert plan_index_fact_requests(plan) == ()
