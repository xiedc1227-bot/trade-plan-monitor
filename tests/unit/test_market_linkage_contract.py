"""Independent contract checks for the opt-in market-linked plan."""

import pytest
from pydantic import ValidationError

from trade_plan_monitor.domain.market_linkage_models import QuantityPolicy, legal_quantity_floor


def policy(**changes):
    return (
        dict(
            mode="MARKET_FACTOR",
            base_quantity=300,
            normal_factor="1",
            weak_factor="0.5",
            rounding="LEGAL_FLOOR",
            capacity_policy="BLOCK_FULL",
            signal_quantity_policy="FREEZE",
        )
        | changes
    )


def test_policy_preserves_exact_factors_and_required_fields():
    value = QuantityPolicy.model_validate(policy())
    assert value.model_dump(mode="json")["weak_factor"] == "0.5"
    raw = policy()
    del raw["base_quantity"]
    with pytest.raises(ValidationError):
        QuantityPolicy.model_validate(raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"base_quantity": 0},
        {"base_quantity": 150},
        {"base_quantity": True},
        {"weak_factor": 0.5},
        {"weak_factor": "0.6"},
        {"normal_factor": "2"},
        {"capacity_policy": "CLIP"},
        {"quantity": 300},
    ],
)
def test_policy_rejects_strategy_changes_and_ambiguous_values(changes):
    with pytest.raises(ValidationError):
        QuantityPolicy.model_validate(policy(**changes))


@pytest.mark.parametrize(
    "ceiling,minimum,increment,expected",
    [
        (150, 100, 100, 100),
        (50, 100, 100, None),
        (300, 200, 1, 300),
        (350, 150, 50, 300),
        (300, 150, 100, None),
        (200, 200, 100, 200),
    ],
)
def test_market_grid_intersection_does_not_round_up(ceiling, minimum, increment, expected):
    assert legal_quantity_floor(ceiling, minimum=minimum, increment=increment) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ceiling": True, "minimum": 100, "increment": 100},
        {"ceiling": 100, "minimum": 0, "increment": 100},
        {"ceiling": 100, "minimum": 100, "increment": 0},
    ],
)
def test_invalid_market_quantity_rules_are_not_silently_fixed(kwargs):
    with pytest.raises(ValueError):
        legal_quantity_floor(**kwargs)


def linked_payload():
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.market_index.identity import resolve_board_reference

    raw = unified_payload()
    raw.update(schema_version=6, execution_version="condition-plan-v2")
    raw["reference_market"] = resolve_board_reference(raw["symbol"]).binding.model_dump(mode="json")
    buy = next(r for r in raw["ordinary_rules"] if r["side"] == "BUY")
    buy.pop("quantity")
    buy["quantity_policy"] = policy()
    buy["market_policy"] = dict(
        policy_version="market-linkage-v1", base_confirmation="S0", exception_policy="BLOCK_P1"
    )
    return raw


def test_linked_plan_and_fixed_rules_preserve_their_distinct_quantities():
    from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan

    plan = MarketLinkedTradePlan.model_validate(linked_payload())
    buy = next(r for r in plan.ordinary_rules if r.side == "BUY")
    assert "quantity" not in buy.model_dump()
    assert buy.quantity_policy.base_quantity == 300
    assert MarketLinkedTradePlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize("change", ["quantity", "minute", "core", "index", "missing_s0"])
def test_linked_plan_rejects_semantically_invalid_rules(change):
    from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan

    raw = linked_payload()
    buy = next(r for r in raw["ordinary_rules"] if r["side"] == "BUY")
    if change == "quantity":
        buy["quantity"] = 300
    elif change == "minute":
        buy["confirmation"] = {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5}
    elif change == "core":
        buy["bucket"] = "CORE"
    elif change == "index":
        raw["reference_market"]["index_code"] = "899050.BJ"
    else:
        buy["condition"] = None
    with pytest.raises(ValidationError):
        MarketLinkedTradePlan.model_validate(raw)


def test_existing_reader_rejects_linked_payload_without_reinterpreting_it():
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    with pytest.raises(ValidationError):
        UnifiedTradePlan.model_validate(linked_payload())


def test_linked_codec_draft_and_hash_round_trip():
    import json
    from hashlib import sha256

    from trade_plan_monitor.domain.daily_plan_validation import (
        daily_draft_content_sha256,
        daily_draft_issues,
        daily_draft_json,
        load_daily_draft_json,
    )
    from trade_plan_monitor.domain.plan_codec import (
        dump_plan_json,
        dump_plan_yaml,
        load_plan_json,
        load_plan_yaml,
    )
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

    plan = load_plan_json(json.dumps(linked_payload()))
    assert load_plan_yaml(dump_plan_yaml(plan)) == plan
    assert load_plan_json(dump_plan_json(plan)) == plan
    draft = load_daily_draft_json(dump_plan_json(plan))
    assert draft.to_executable() == plan
    assert load_daily_draft_json(daily_draft_json(draft)) == draft
    assert daily_draft_issues(draft) == ()
    content = plan.model_dump(mode="json", exclude={"plan_id", "version", "name", "metadata"})
    expected = sha256(
        b"plan-review-content-v3\x00"
        + json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert daily_plan_content_sha256(plan) == daily_draft_content_sha256(draft) == expected


def test_incomplete_linked_draft_stays_incomplete():
    import json

    from trade_plan_monitor.domain.daily_plan_validation import (
        daily_draft_issues,
        load_daily_draft_json,
    )

    raw = linked_payload()
    raw["ordinary_rules"][0]["quantity_policy"]["base_quantity"] = None
    draft = load_daily_draft_json(json.dumps(raw))
    assert draft.to_executable() is None
    assert daily_draft_issues(draft)


@pytest.mark.parametrize("count,depth", [(43, 1), (1, 4)])
def test_policy_expansion_is_included_in_bounds(count, depth):
    from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan

    raw = linked_payload()
    leaf = {
        "type": "DAILY_PRICE_IN_RANGE",
        "field": "close",
        "offset": 0,
        "range": {"low_fen": 100, "high_fen": 200, "include_low": True, "include_high": True},
    }
    root = {"type": "ALL", "conditions": [dict(leaf) for _ in range(count)]}
    for _ in range(depth - 1):
        root = {"type": "ALL", "conditions": [root]}
    raw["ordinary_rules"][0]["condition"] = root
    with pytest.raises(ValidationError):
        MarketLinkedTradePlan.model_validate(raw)


def test_preflight_matches_independent_enumeration():
    for minimum in (1, 100, 150, 200, 301):
        for increment in (1, 3, 50, 100, 151):
            for ceiling in (0, 50, 150, 300, 1000):
                candidates = [q for q in range(minimum, ceiling + 1, increment) if q % 100 == 0]
                assert legal_quantity_floor(ceiling, minimum=minimum, increment=increment) == (
                    max(candidates) if candidates else None
                )
