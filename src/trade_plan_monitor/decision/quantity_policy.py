"""Floor-only source quantity calculation; capacity never resizes the candidate."""

from math import gcd
from typing import Annotated, Literal

from pydantic import Field, model_validator

from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, PositiveWholeQty, WholeQty
from trade_plan_monitor.domain.market_linkage_models import legal_quantity_floor


class QuantityCalculation(DailyValue):
    formula_version: Literal["market-linkage-calculation-v1"] = "market-linkage-calculation-v1"
    base_quantity: PositiveWholeQty
    factor: Literal["1", "0.5"] | None
    ceiling: Annotated[int, Field(ge=0, le=9_007_199_254_740_991)] | None
    minimum: Annotated[int, Field(gt=0, le=9_007_199_254_740_991)] | None
    increment: Annotated[int, Field(gt=0, le=9_007_199_254_740_991)] | None
    candidate_quantity: WholeQty | None
    capacity: int | None
    authorized_quantity: WholeQty
    blockers: tuple[str, ...]
    calculation_hash: str

    @model_validator(mode="after")
    def consistent_calculation(self):
        if self.calculation_hash != daily_hash(
            "market-linkage-calculation-v1",
            self.model_dump(mode="json", exclude={"calculation_hash"}),
        ):
            raise ValueError("quantity calculation hash mismatch")
        ceiling = (
            None
            if self.factor is None
            else self.base_quantity
            if self.factor == "1"
            else self.base_quantity // 2
        )
        candidate = (
            None
            if ceiling is None or self.minimum is None or self.increment is None
            else legal_quantity_floor(ceiling, minimum=self.minimum, increment=self.increment)
        )
        if self.ceiling != ceiling or self.candidate_quantity != candidate:
            raise ValueError("quantity calculation does not match its operands")
        if self.authorized_quantity != (candidate if candidate and not self.blockers else 0):
            raise ValueError("quantity authorization does not match its blockers")
        if self.authorized_quantity and (
            self.capacity is None or self.capacity < self.authorized_quantity
        ):
            raise ValueError("quantity authorization exceeds available capacity")
        return self


def quantity_preflight(base_quantity, regime, minimum, increment):
    if (
        type(base_quantity) is not int
        or not 0 < base_quantity <= 9_007_199_254_740_991
        or base_quantity % 100
    ):
        raise ValueError("invalid source Q0")
    if regime == "BROKEN":
        return None, None, None, "MARKET_BROKEN"
    if regime not in {"NORMAL_TRANSITION", "WEAK"}:
        return None, None, None, "MARKET_INPUT_UNKNOWN"
    factor = "1" if regime == "NORMAL_TRANSITION" else "0.5"
    ceiling = base_quantity if factor == "1" else base_quantity // 2
    if minimum is None or increment is None:
        return factor, ceiling, None, "MARKET_RULES_UNKNOWN"
    candidate = legal_quantity_floor(ceiling, minimum=minimum, increment=increment)
    if minimum % gcd(100, increment):
        reason = "MARKET_QUANTITY_INCOMPATIBLE"
    else:
        reason = (None if candidate else "P1_EXCEPTION_REQUIRED" if regime == "WEAK"
                  else "MARKET_QUANTITY_BELOW_MINIMUM")
    return factor, ceiling, candidate, reason


def calculate_quantity(
    *, base_quantity, regime, minimum, increment, capacity, condition, risk, route_blocker
):
    factor, ceiling, candidate, error = quantity_preflight(
        base_quantity, regime, minimum, increment
    )
    reasons = [code for code in (route_blocker, error) if code]
    if condition != "SATISFIED":
        reasons.append(
            "CONFIRMATION_UNKNOWN" if condition == "MISSING_INPUT" else "CONFIRMATION_UNMET"
        )
    if risk != "UNSATISFIED":
        reasons.append("HIGHER_PRIORITY_RISK" if risk == "SATISFIED" else "RISK_INPUT_UNKNOWN")
    if capacity is None:
        reasons.append("POSITION_UNKNOWN")
    elif candidate is not None and capacity < candidate:
        reasons.append("MAX_QUANTITY_CAPACITY")
    payload = dict(
        formula_version="market-linkage-calculation-v1",
        base_quantity=base_quantity,
        factor=factor,
        ceiling=ceiling,
        minimum=minimum,
        increment=increment,
        candidate_quantity=candidate,
        capacity=capacity,
        authorized_quantity=candidate if candidate and not reasons else 0,
        blockers=tuple(dict.fromkeys(reasons)),
    )
    return QuantityCalculation(**payload,
        calculation_hash=daily_hash("market-linkage-calculation-v1", payload))
