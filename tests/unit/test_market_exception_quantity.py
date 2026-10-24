"""Independent sizing examples: validation never grants occurrence authority."""

import pytest

from trade_plan_monitor.decision.market_exception_policy import validate_exception_quantity


@pytest.mark.parametrize("route,q0,minimum,increment,capacity,proposed,candidate,blocker", [
    ("WEAK_MINIMUM", 100, 100, 100, 500, None, 100, None),
    ("WEAK_MINIMUM", 300, 200, 1, 500, None, 200, None),
    ("WEAK_MINIMUM", 100, 200, 1, 500, None, 200, "EXCEPTION_QUANTITY_INVALID"),
    ("WEAK_MINIMUM", 100, 100, 100, 0, None, 100, "MAX_QUANTITY_CAPACITY"),
    ("WEAK_MINIMUM", 200, 150, 1, 500, None, 150, "EXCEPTION_QUANTITY_INVALID"),
    ("WEAK_MINIMUM", 100, 100, 100, 500, 100, 100, "EXCEPTION_QUANTITY_INVALID"),
    ("BROKEN_STRONG", 500, 100, 100, 400, 300, 300, None),
    ("BROKEN_STRONG", 500, 100, 100, 400, 500, 500, "MAX_QUANTITY_CAPACITY"),
    ("BROKEN_STRONG", 500, 100, 100, 800, None, None, "EXCEPTION_QUANTITY_REQUIRED"),
    ("BROKEN_STRONG", 500, 100, 100, 800, 0, 0, "EXCEPTION_QUANTITY_INVALID"),
    ("BROKEN_STRONG", 500, 100, 100, 800, 150, 150, "EXCEPTION_QUANTITY_INVALID"),
    ("BROKEN_STRONG", 500, 100, 100, 800, 600, 600, "EXCEPTION_QUANTITY_INVALID"),
    ("BROKEN_STRONG", 500, 100, 100, 800, 100, 100, None),
    ("BROKEN_STRONG", 500, 100, 100, 800, 500, 500, None),
    ("BROKEN_STRONG", 300, 200, 1, 500, 200, 200, None),
    ("BROKEN_STRONG", 300, 200, 1, 500, 100, 100, "EXCEPTION_QUANTITY_INVALID"),
    ("BROKEN_STRONG", 300, 200, 1, 500, 250, 250, "EXCEPTION_QUANTITY_INVALID"),
    ("BROKEN_STRONG", 300, 100, 100, None, 200, 200, "POSITION_UNKNOWN"),
    ("BROKEN_STRONG", 300, None, None, 500, 200, 200, "MARKET_RULES_UNKNOWN"),
])
def test_exact_route_quantities(
    route, q0, minimum, increment, capacity, proposed, candidate, blocker,
):
    result = validate_exception_quantity(
        route=route, base_quantity=q0, minimum=minimum, increment=increment,
        capacity=capacity, proposed_quantity=proposed,
    )
    assert result.candidate_quantity == candidate
    assert result.blockers == (() if blocker is None else (blocker,))
    assert result.authorized_quantity == 0


@pytest.mark.parametrize("value", [True, 100.0, "100", -100, 9007199254741000])
def test_invalid_quantities_are_never_coerced(value):
    with pytest.raises(ValueError):
        validate_exception_quantity(route="BROKEN_STRONG", base_quantity=300,
            minimum=100, increment=100, capacity=500, proposed_quantity=value)
