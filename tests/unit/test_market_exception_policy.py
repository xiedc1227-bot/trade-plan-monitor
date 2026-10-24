"""Route admission is separate from approval and ordinary sizing."""

import pytest

from trade_plan_monitor.decision.market_exception_policy import select_exception
from trade_plan_monitor.domain.market_exception_models import ExceptionRoutes


def selection(**changes):
    kwargs = dict(
        regime="WEAK", strength="STRONG", base_quantity=100, minimum=100, increment=100,
        confirmation="SATISFIED", risk="UNSATISFIED",
        permissions=ExceptionRoutes(weak_minimum="PER_OCCURRENCE", broken_strong="PER_OCCURRENCE"),
    )
    return select_exception(**(kwargs | changes))


def test_minimum_exception_only_after_strong_s1_and_below_minimum_reduction():
    value = selection()
    assert (value.route, value.group, value.eligible, value.blockers) == (
        "WEAK_MINIMUM", "S1", True, (),
    )
    star = selection(base_quantity=300, minimum=200, increment=1)
    assert star.eligible and star.route == "WEAK_MINIMUM"


@pytest.mark.parametrize("changes", [
    {"regime": "NORMAL_TRANSITION"},
    {"base_quantity": 300},
    {"base_quantity": 400, "minimum": 200, "increment": 1},
])
def test_ordinary_routes_never_need_an_exception_or_strength(changes):
    value = selection(**(changes | {"strength": "UNKNOWN"}))
    assert value.route is None
    assert not value.eligible
    assert value.blockers == ()


@pytest.mark.parametrize("changes,blocker", [
    ({"strength": "NOT_STRONG"}, "RELATIVE_STRENGTH_NOT_STRONG"),
    ({"strength": "UNKNOWN"}, "MARKET_INPUT_UNKNOWN"),
    ({"confirmation": "UNSATISFIED"}, "CONFIRMATION_UNMET"),
    ({"confirmation": "MISSING_INPUT"}, "CONFIRMATION_UNKNOWN"),
    ({"risk": "SATISFIED"}, "HIGHER_PRIORITY_RISK"),
    ({"risk": "MISSING_INPUT"}, "RISK_INPUT_UNKNOWN"),
    ({"minimum": None, "increment": None}, "MARKET_RULES_UNKNOWN"),
    ({"minimum": 150, "increment": 100}, "MARKET_QUANTITY_INCOMPATIBLE"),
    ({"minimum": 200}, "EXCEPTION_QUANTITY_INVALID"),
    ({"regime": "UNKNOWN"}, "MARKET_INPUT_UNKNOWN"),
])
def test_ineligible_evidence_cannot_be_approved(changes, blocker):
    value = selection(**changes)
    assert not value.eligible
    assert blocker in value.blockers


def test_broken_route_needs_strong_s2_and_explicit_permission():
    value = selection(regime="BROKEN", base_quantity=500)
    assert (value.route, value.group, value.eligible) == ("BROKEN_STRONG", "S2", True)
    for strength in ("NOT_STRONG", "UNKNOWN"):
        assert not selection(regime="BROKEN", strength=strength).eligible
    disabled = ExceptionRoutes(weak_minimum="DISABLED", broken_strong="DISABLED")
    assert selection(permissions=disabled).blockers == ("EXCEPTION_DISABLED",)
    assert selection(regime="BROKEN", permissions=disabled).blockers == ("EXCEPTION_DISABLED",)


@pytest.mark.parametrize("minimum,increment,blocker", [
    (150, 100, "MARKET_QUANTITY_INCOMPATIBLE"),
    (200, 1, "MARKET_QUANTITY_BELOW_MINIMUM"),
])
def test_broken_route_cannot_offer_approval_without_any_legal_quantity(minimum, increment, blocker):
    value = selection(regime="BROKEN", minimum=minimum, increment=increment)
    assert not value.eligible
    assert blocker in value.blockers
