"""Prepare budget transitions before writing inventory; persist in the same session."""

from dataclasses import dataclass

from sqlalchemy import inspect

from trade_plan_monitor.decision.p3_basis import CapitalLot, release_basis
from trade_plan_monitor.decision.p3_capital import safe_integer
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.p3_models import CapitalBook


@dataclass(frozen=True)
class CapitalTransition:
    book: CapitalBook
    expected_revision: int
    command_id: str
    request_hash: str
    kind: str
    details: dict


def _quantities(batches):
    result = {(p["id"], p["bucket"]): p["quantity"] for p in batches}
    if len(result) != len(batches):
        raise ValueError("CAPITAL_LOTS_CHANGED")
    return result


def capital_storage_ready(session):
    key = "p3_capital_storage_ready"
    if key not in session.info:
        session.info[key] = inspect(session.connection()).has_table("simulation_capital_book")
    return session.info[key]


def prepare_capital_transition(
    session, before, after_batches, *, identity, side, now, debit_fen=None, details=None
):
    if not capital_storage_ready(session):
        if debit_fen is not None:
            raise ValueError("CAPITAL_STORAGE_NOT_READY")
        return None
    repo = CapitalRepository(session)
    book = repo.get(before["symbol"])
    if book is None and debit_fen is None:
        return None  # Old plans gain no cost prerequisite or sidecar initialization.
    old = _quantities(before["payload"]["batches"])
    new = _quantities(after_batches)
    current = (
        book is not None
        and book.inventory_revision == before["revision"]
        and {(p.lot_id, p.bucket): p.quantity for p in book.lots} == old
    )
    if debit_fen is not None and (side != "BUY" or not safe_integer(debit_fen, positive=True)):
        raise ValueError("CAPITAL_BUY_DEBIT_INVALID")
    if debit_fen is not None and not current and old:
        raise ValueError("CAPITAL_BASE_UNKNOWN")
    allocations, released = [], None
    if side == "SELL" and current:
        if not new.keys() <= old.keys() or any(new.get(k, 0) > q for k, q in old.items()):
            raise ValueError("CAPITAL_LOTS_CHANGED")
        allocations = [
            dict(id=k[0], bucket=k[1], quantity=q - new.get(k, 0))
            for k, q in old.items()
            if new.get(k, 0) < q
        ]
        transition = release_basis(book.lots, allocations)
        lots, released = transition.lots, transition.released_fen
    elif side == "BUY" and (current or not old):
        if any(new.get(k) != q for k, q in old.items()):
            raise ValueError("CAPITAL_LOTS_CHANGED")
        added = new.keys() - old.keys()
        if debit_fen is not None and len(added) != 1:
            raise ValueError("CAPITAL_BUY_ALLOCATION_INVALID")
        lots = (
            *(book.lots if current else ()),
            *(
                CapitalLot(
                    lot_id=k[0],
                    bucket=k[1],
                    quantity=new[k],
                    retained_basis_fen=debit_fen,
                    provenance_ref=identity,
                )
                for k in sorted(added)
            ),
        )
    else:
        # An older binary changed quantity without a budget receipt. Do not invent old costs.
        lots = tuple(
            CapitalLot(
                lot_id=k[0], bucket=k[1], quantity=q, retained_basis_fen=None, provenance_ref=None
            )
            for k, q in new.items()
        )
    revision = 0 if book is None else book.revision
    updated = CapitalBook.build(
        symbol=before["symbol"],
        revision=revision + 1,
        inventory_revision=before["revision"] + 1,
        updated_at=now,
        lots=lots,
    )
    intent = dict(
        simulation_id=identity,
        symbol=before["symbol"],
        side=side,
        inventory_revision=before["revision"],
        book_revision=revision,
        resulting_hash=updated.evidence_hash,
        debit_fen=debit_fen,
        details=details,
    )
    return CapitalTransition(
        book=updated,
        expected_revision=revision,
        command_id=daily_hash(
            "capital-simulation-command-v1", {"simulation_id": identity, "symbol": before["symbol"]}
        ),
        request_hash=daily_hash("capital-inventory-change-v1", intent),
        kind=(side if current or not old else "UNKNOWN_CHANGE"),
        details={
            "simulation_id": identity,
            "side": side,
            "debit_fen": debit_fen,
            "released_basis_fen": released,
            "allocations": allocations,
            "policy": details,
        },
    )


def persist_capital_transition(session, transition, position, now):
    if transition is None:
        return None
    if position["revision"] != transition.book.inventory_revision or _quantities(
        position["payload"]["batches"]
    ) != {(p.lot_id, p.bucket): p.quantity for p in transition.book.lots}:
        raise ValueError("CAPITAL_INVENTORY_MISMATCH")
    return CapitalRepository(session).write(
        transition.book,
        expected_revision=transition.expected_revision,
        command_id=transition.command_id,
        request_hash=transition.request_hash,
        kind=transition.kind,
        now=now,
        details=transition.details,
    )
