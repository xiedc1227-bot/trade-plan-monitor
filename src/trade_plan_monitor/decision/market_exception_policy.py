"""Pure exception eligibility and quantity checks; never issue human authority."""

from typing import Literal

from pydantic import Field

from trade_plan_monitor.decision.quantity_policy import quantity_preflight
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.market_exception_models import ExceptionRoute


class ExceptionQuantityDecision(DailyValue):
    candidate_quantity: int | None = Field(strict=True)
    authorized_quantity: Literal[0] = 0
    blockers: tuple[str, ...]


def validate_exception_quantity(
    *, route, base_quantity, minimum, increment, capacity, proposed_quantity,
):
    """Validate exact user intent without rounding, sizing defaults or approval."""
    if route not in {"WEAK_MINIMUM", "BROKEN_STRONG"}:
        raise ValueError("unknown exception route")
    quantity_preflight(base_quantity, "NORMAL_TRANSITION", minimum, increment)
    if proposed_quantity is not None and (
        type(proposed_quantity) is not int
        or not 0 <= proposed_quantity <= 9_007_199_254_740_991
    ):
        raise ValueError("exception quantity must be a bounded integer")
    if capacity is not None and type(capacity) is not int:
        raise ValueError("capacity must be an integer or unknown")
    candidate = minimum if route == "WEAK_MINIMUM" else proposed_quantity
    blockers = []
    if minimum is None or increment is None:
        blockers.append("MARKET_RULES_UNKNOWN")
    if candidate is None:
        if route == "BROKEN_STRONG":
            blockers.append("EXCEPTION_QUANTITY_REQUIRED")
    elif (
        not 0 < candidate <= base_quantity
        or candidate % 100
        or minimum is not None and candidate < minimum
        or minimum is not None and increment is not None and (candidate - minimum) % increment
        or route == "WEAK_MINIMUM" and (
            proposed_quantity is not None or base_quantity // 2 >= candidate
        )
    ):
        blockers.append("EXCEPTION_QUANTITY_INVALID")
    if capacity is None:
        blockers.append("POSITION_UNKNOWN")
    elif candidate is not None and capacity < candidate:
        blockers.append("MAX_QUANTITY_CAPACITY")
    return ExceptionQuantityDecision(candidate_quantity=candidate, blockers=tuple(blockers))


class ExceptionEligibility(DailyValue):
    route: ExceptionRoute | None
    group: Literal["S0", "S1", "S2"] | None
    blockers: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return self.route is not None and not self.blockers


def select_exception(
    *, regime, strength, base_quantity, minimum, increment, confirmation, risk, permissions,
):
    """Admit only the two approved routes; ordinary routes have no approval dependency."""
    _, _, ordinary, error = quantity_preflight(base_quantity, regime, minimum, increment)
    if regime == "NORMAL_TRANSITION" or regime == "WEAK" and ordinary is not None:
        return ExceptionEligibility(
            route=None, group="S0" if regime == "NORMAL_TRANSITION" else "S1",
            blockers=() if error is None else (error,),
        )
    if regime == "WEAK" and error == "P1_EXCEPTION_REQUIRED":
        route, group, permission = "WEAK_MINIMUM", "S1", permissions.weak_minimum
    elif regime == "BROKEN":
        if strength != "STRONG":
            return ExceptionEligibility(route=None, group=None, blockers=(
                "MARKET_BROKEN" if strength == "NOT_STRONG" else "MARKET_INPUT_UNKNOWN",
            ))
        route, group, permission = "BROKEN_STRONG", "S2", permissions.broken_strong
    else:
        return ExceptionEligibility(route=None, group=None, blockers=(
            error or "MARKET_INPUT_UNKNOWN",
        ))
    blockers = []
    if permission != "PER_OCCURRENCE":
        blockers.append("EXCEPTION_DISABLED")
    if minimum is None or increment is None:
        blockers.append("MARKET_RULES_UNKNOWN")
    elif route == "WEAK_MINIMUM" and (minimum % 100 or minimum > base_quantity):
        blockers.append("EXCEPTION_QUANTITY_INVALID")
    elif route == "BROKEN_STRONG":
        _, _, _, grid_error = quantity_preflight(
            base_quantity, "NORMAL_TRANSITION", minimum, increment,
        )
        if grid_error:
            blockers.append(grid_error)
    if strength != "STRONG":
        blockers.append(
            "RELATIVE_STRENGTH_NOT_STRONG" if strength == "NOT_STRONG" else "MARKET_INPUT_UNKNOWN"
        )
    if confirmation != "SATISFIED":
        blockers.append(
            "CONFIRMATION_UNMET" if confirmation == "UNSATISFIED" else "CONFIRMATION_UNKNOWN"
        )
    if risk != "UNSATISFIED":
        blockers.append("HIGHER_PRIORITY_RISK" if risk == "SATISFIED" else "RISK_INPUT_UNKNOWN")
    return ExceptionEligibility(route=route, group=group, blockers=tuple(blockers))
