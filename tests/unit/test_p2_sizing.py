"""Explicit tier boundaries precede existing market reductions."""

from decimal import Decimal

import pytest
from tests.unit.test_p2_policy_contract import sizing

from trade_plan_monitor.decision.p2_sizing import calculate_sizing
from trade_plan_monitor.domain.p2_policy_models import TierSizing


@pytest.mark.parametrize(("atr", "expected", "tier"), [
    ("0", 1000, 0), ("49.999", 1000, 0), ("50", 500, 1), ("100", 500, 1)])
def test_exact_half_open_boundaries(atr, expected, tier):
    result = calculate_sizing(TierSizing.model_validate(sizing()),
                              atr_fen=Decimal(atr), close_fen=Decimal(1000),
                              minimum=100, increment=100)
    assert result.q0 == expected
    assert result.tier_index == tier


@pytest.mark.parametrize(("base", "minimum", "expected"), [
    (100, 100, None), (200, 100, 100), (500, 200, 200), (300, 200, None)])
def test_legal_grid_floor_never_invents_minimum_exception(base, minimum, expected):
    raw = sizing() | {"base_qty": base}
    result = calculate_sizing(TierSizing.model_validate(raw), atr_fen=Decimal(50),
                              close_fen=Decimal(1000), minimum=minimum, increment=1)
    assert result.q0 == expected
    assert result.blocker == ("VOLATILITY_BELOW_MINIMUM" if expected is None else None)


@pytest.mark.parametrize(("atr", "close", "minimum"), [
    (None, Decimal(1000), 100), (Decimal(50), None, 100),
    (Decimal(50), Decimal(0), 100), (Decimal(50), Decimal(1000), None)])
def test_missing_inputs_are_unknown(atr, close, minimum):
    result = calculate_sizing(TierSizing.model_validate(sizing()), atr_fen=atr,
                              close_fen=close, minimum=minimum, increment=100)
    assert result.q0 is None
    assert result.blocker in {"VOLATILITY_INPUT_UNKNOWN", "MARKET_RULES_UNKNOWN"}


def test_zero_multiplier_is_a_no_buy_result():
    raw = sizing()
    raw["tiers"][1]["multiplier"] = "0"
    result = calculate_sizing(TierSizing.model_validate(raw), atr_fen=Decimal(50),
                              close_fen=Decimal(1000), minimum=100, increment=100)
    assert result.q0 is None
