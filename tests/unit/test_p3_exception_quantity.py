"""Grid validation has no inventory default or money-derived candidate."""

import pytest

from trade_plan_monitor.decision.market_exception_policy import exception_quantity_grid


@pytest.mark.parametrize(("route", "proposed", "expected", "blocker"), [
    ("WEAK_MINIMUM", None, 100, None),
    ("WEAK_MINIMUM", 100, 100, "EXCEPTION_QUANTITY_INVALID"),
    ("BROKEN_STRONG", None, None, "EXCEPTION_QUANTITY_REQUIRED"),
    ("BROKEN_STRONG", 100, 100, None),
    ("BROKEN_STRONG", 50, 50, "EXCEPTION_QUANTITY_INVALID"),
    ("BROKEN_STRONG", 200, 200, "EXCEPTION_QUANTITY_INVALID"),
])
def test_grid_only_preserves_exact_intent(route, proposed, expected, blocker):
    result = exception_quantity_grid(route=route, base_quantity=100, minimum=100,
        increment=100, proposed_quantity=proposed)
    assert result.candidate_quantity == expected
    assert result.authorized_quantity == 0
    assert result.blockers == (() if blocker is None else (blocker,))
