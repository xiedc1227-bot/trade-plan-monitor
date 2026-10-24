import pytest


@pytest.mark.parametrize(
    "symbol,minimum,increment",
    [
        ("600000.SH", 100, 100),
        ("000002.SZ", 100, 100),
        ("300750.SZ", 100, 100),
        ("688001.SH", 200, 1),
        ("920001.BJ", 100, 1),
    ],
)
def test_official_grid_is_dated_and_board_specific(symbol, minimum, increment):
    from datetime import date

    from trade_plan_monitor.domain.market_quantity_rules import official_buy_grid

    rules = official_buy_grid(symbol, date(2026, 7, 6))
    assert (rules.minimum, rules.increment) == (minimum, increment)
    assert len(rules.content_hash) == 64
    assert official_buy_grid(symbol, date(2026, 7, 5)) is None
    assert official_buy_grid("510300.SH", date(2026, 7, 6)) is None


@pytest.mark.parametrize(
    "base,regime,capacity,candidate,authorized,reason",
    [
        (300, "NORMAL_TRANSITION", 500, 300, 300, None),
        (300, "WEAK", 500, 100, 100, None),
        (100, "WEAK", 500, None, 0, "P1_EXCEPTION_REQUIRED"),
        (300, "NORMAL_TRANSITION", 200, 300, 0, "MAX_QUANTITY_CAPACITY"),
        (300, "WEAK", 0, 100, 0, "MAX_QUANTITY_CAPACITY"),
    ],
)
def test_specification_examples(base, regime, capacity, candidate, authorized, reason):
    from trade_plan_monitor.decision.quantity_policy import calculate_quantity

    result = calculate_quantity(
        base_quantity=base,
        regime=regime,
        minimum=100,
        increment=100,
        capacity=capacity,
        condition="SATISFIED",
        risk="UNSATISFIED",
        route_blocker=None,
    )
    assert (result.candidate_quantity, result.authorized_quantity) == (candidate, authorized)
    assert (result.blockers[0] if result.blockers else None) == reason


@pytest.mark.parametrize(
    "change",
    [
        {"capacity": None},
        {"minimum": None},
        {"condition": "MISSING_INPUT"},
        {"condition": "UNSATISFIED"},
        {"risk": "SATISFIED"},
        {"risk": "MISSING_INPUT"},
        {"route_blocker": "P1_EXCEPTION_REQUIRED"},
        {"regime": "UNKNOWN"},
        {"minimum": 150, "increment": 100},
    ],
)
def test_blockers_never_manufacture_positive_authority(change):
    from trade_plan_monitor.decision.quantity_policy import calculate_quantity

    args = dict(
        base_quantity=300,
        regime="NORMAL_TRANSITION",
        minimum=100,
        increment=100,
        capacity=500,
        condition="SATISFIED",
        risk="UNSATISFIED",
        route_blocker=None,
    )
    assert calculate_quantity(**(args | change)).authorized_quantity == 0


def test_known_broken_market_does_not_report_missing_market_evidence():
    from trade_plan_monitor.decision.quantity_policy import calculate_quantity

    result = calculate_quantity(
        base_quantity=300, regime="BROKEN", minimum=100, increment=100,
        capacity=500, condition="SATISFIED", risk="UNSATISFIED",
        route_blocker="P1_EXCEPTION_REQUIRED",
    )
    assert result.authorized_quantity == 0
    assert result.candidate_quantity is None
    assert result.blockers == ("P1_EXCEPTION_REQUIRED", "MARKET_BROKEN")


def test_normal_market_below_star_minimum_is_not_a_weak_market_exception():
    from trade_plan_monitor.decision.quantity_policy import calculate_quantity

    result = calculate_quantity(
        base_quantity=100, regime="NORMAL_TRANSITION", minimum=200, increment=1,
        capacity=500, condition="SATISFIED", risk="UNSATISFIED", route_blocker=None,
    )
    assert result.candidate_quantity is None and result.authorized_quantity == 0
    assert result.blockers == ("MARKET_QUANTITY_BELOW_MINIMUM",)
