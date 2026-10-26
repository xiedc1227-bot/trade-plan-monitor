"""Release retained budget cost from actual inventory allocations, not proceeds."""

from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier, PositiveWholeQty
from trade_plan_monitor.domain.p2_policy_models import MAX_SAFE, SafeFen


class CapitalLot(DailyValue):
    lot_id: Identifier
    bucket: Literal["CORE", "TACTICAL"]
    quantity: PositiveWholeQty
    retained_basis_fen: SafeFen | None
    provenance_ref: str | None = Field(default=None, max_length=128)


def retained_basis(lots):
    if len(lots) > 500 or len({(p.lot_id, p.bucket) for p in lots}) != len(lots):
        raise ValueError("capital lot identities or count are inconsistent")
    if (sum(p.quantity for p in lots) > MAX_SAFE
            or sum(p.retained_basis_fen or 0 for p in lots) > MAX_SAFE):
        raise ValueError("capital totals overflow safe integer bounds")
    return (None if any(p.retained_basis_fen is None for p in lots)
            else sum(p.retained_basis_fen for p in lots))


class BasisRelease(DailyValue):
    lots: tuple[CapitalLot, ...] = Field(max_length=500)
    released_fen: SafeFen | None

    @model_validator(mode="after")
    def consistent(self):
        retained_basis(self.lots)
        return self


def release_basis(lots, allocations):
    """Each whole simulation may reduce a larger lot; all remaining fen stay in that lot."""
    retained_basis(lots)
    known = {(p.lot_id, p.bucket): p for p in lots}
    selected = {}
    for value in allocations:
        key, quantity = (value["id"], value["bucket"]), value["quantity"]
        if (key in selected or key not in known or type(quantity) is not int
                or not 0 < quantity <= known[key].quantity or quantity % 100):
            raise ValueError("capital release differs from actual inventory allocation")
        selected[key] = quantity
    remaining, released = [], 0
    for item in lots:
        sold = selected.get((item.lot_id, item.bucket), 0)
        if not sold:
            remaining.append(item)
            continue
        basis = item.retained_basis_fen
        debit = None if basis is None else basis*sold//item.quantity
        released = None if debit is None or released is None else released+debit
        if sold < item.quantity:
            remaining.append(item.model_copy(update={"quantity": item.quantity-sold,
                "retained_basis_fen": None if basis is None else basis-debit}))
    return BasisRelease(lots=tuple(remaining), released_fen=released)
