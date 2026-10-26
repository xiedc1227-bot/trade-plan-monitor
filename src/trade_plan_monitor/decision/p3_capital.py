"""Exact monetary predicates consume a selected quantity, never choose one."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from trade_plan_monitor.decision.p2_economics import BuyDebitResult, calculate_buy_debit
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, PositiveWholeQty, WholeQty
from trade_plan_monitor.domain.p2_policy_models import MAX_SAFE, PositiveFen, SafeFen
from trade_plan_monitor.domain.p3_policy_models import CombinedCapitalLimit, OpenCostCap


class BoundedCapacity(DailyValue):
    mode: Literal["BOUNDED"] = "BOUNDED"
    remaining_qty: WholeQty


class UnboundedCapacity(DailyValue):
    mode: Literal["UNBOUNDED"] = "UNBOUNDED"


class UnknownCapacity(DailyValue):
    mode: Literal["UNKNOWN"] = "UNKNOWN"


ShareCapacity = Annotated[BoundedCapacity | UnboundedCapacity | UnknownCapacity,
                          Field(discriminator="mode")]


class CapitalAssessment(DailyValue):
    version: Literal["capital-limit-evidence-v1"] = "capital-limit-evidence-v1"
    mode: Literal["OPEN_COST_CAP", "MARKET_VALUE_CAP"]
    phase: Literal["CONFIRMATION", "CURRENT", "EXECUTION"]
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["PASS", "FAIL", "UNKNOWN"]
    quantity: PositiveWholeQty | None
    price_fen: PositiveFen | None
    total_qty: WholeQty | None
    inventory_revision: SafeFen | None
    book_revision: SafeFen | None
    cap_fen: PositiveFen
    before_fen: SafeFen | None
    after_fen: SafeFen | None
    remaining_fen: Annotated[int, Field(strict=True, ge=-MAX_SAFE, le=MAX_SAFE)] | None
    share_capacity: ShareCapacity
    buy_debit: BuyDebitResult | None
    blockers: tuple[str, ...]
    evidence_hash: str

    @model_validator(mode="after")
    def verify_hash(self):
        if self.evidence_hash != daily_hash(self.version,
                self.model_dump(mode="json", exclude={"evidence_hash"})):
            raise ValueError("capital assessment hash mismatch")
        return self


def safe_integer(value, *, positive=False, whole=False):
    return (type(value) is int and (0 < value if positive else 0 <= value)
            and value <= MAX_SAFE and (not whole or value % 100 == 0))


def share_capacity(position, total_qty):
    if not safe_integer(total_qty, whole=True):
        return UnknownCapacity()
    if isinstance(position.limit, CombinedCapitalLimit):
        return BoundedCapacity(remaining_qty=max(0, position.limit.max_qty-total_qty))
    return UnboundedCapacity()


def assess_capital(position, *, quantity, price_fen, total_qty, retained_basis_fen,
                   symbol, session, inventory_revision=None, book_revision=None, phase="CURRENT"):
    policy = position.limit.capital_policy
    capacity = share_capacity(position, total_qty)
    raw = dict(mode=policy.mode, phase=phase,
        policy_hash=daily_hash("capital-policy-v1", position.limit.model_dump(mode="json")),
        quantity=quantity if safe_integer(quantity, positive=True, whole=True) else None,
        price_fen=price_fen if safe_integer(price_fen, positive=True) else None,
        total_qty=total_qty if safe_integer(total_qty, whole=True) else None,
        inventory_revision=inventory_revision, book_revision=book_revision,
        cap_fen=policy.cap_fen, before_fen=None, after_fen=None, remaining_fen=None,
        share_capacity=capacity, buy_debit=None)

    def result(outcome, blockers=(), **values):
        unsigned = CapitalAssessment.model_construct(**(raw | values), outcome=outcome,
                                                     blockers=blockers, evidence_hash="")
        data = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return CapitalAssessment.model_validate(data | {
            "evidence_hash": daily_hash("capital-limit-evidence-v1", data)})

    if isinstance(capacity, UnknownCapacity):
        return result("UNKNOWN", ("CAPITAL_POSITION_UNKNOWN",))
    if raw["quantity"] is None:
        return result("UNKNOWN", ("CAPITAL_QUANTITY_UNKNOWN",))
    if raw["price_fen"] is None:
        return result("UNKNOWN", ("CAPITAL_QUOTE_UNKNOWN",))
    if total_qty+quantity > MAX_SAFE:
        return result("UNKNOWN", ("CAPITAL_OVERFLOW",))
    buy = None
    if isinstance(policy, OpenCostCap):
        if not safe_integer(retained_basis_fen):
            return result("UNKNOWN", ("CAPITAL_BASE_UNKNOWN",))
        buy = calculate_buy_debit(policy.buy_cost_schedule, quantity=quantity,
            entry_fen=price_fen, symbol=symbol, session=session)
        if buy.outcome != "PASS":
            return result("UNKNOWN", (("CAPITAL_OVERFLOW" if buy.reason == "ECONOMICS_OVERFLOW"
                                       else buy.reason),), buy_debit=buy)
        before, after = retained_basis_fen, retained_basis_fen+buy.debit_fen
    else:
        before, after = total_qty*price_fen, (total_qty+quantity)*price_fen
    if max(before, after) > MAX_SAFE:
        return result("UNKNOWN", ("CAPITAL_OVERFLOW",))
    blockers = []
    if isinstance(capacity, BoundedCapacity) and quantity > capacity.remaining_qty:
        blockers.append("MAX_QUANTITY_CAPACITY")
    if after > policy.cap_fen:
        blockers.append("CAPITAL_LIMIT_EXCEEDED")
    return result("FAIL" if blockers else "PASS", tuple(blockers),
        before_fen=before, after_fen=after, remaining_fen=policy.cap_fen-after, buy_debit=buy)
