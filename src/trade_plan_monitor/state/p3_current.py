"""Read current simulation-only basis without manufacturing opening authority."""

from trade_plan_monitor.state.p3_accounting import capital_storage_ready
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository


def current_capital_inputs(accounting, symbol, now):
    inventory = accounting.snapshot(symbol, now.date())
    book = (CapitalRepository(accounting.repo.session).get(symbol)
            if capital_storage_ready(accounting.repo.session) else None)
    revision = None if book is None else book.revision
    basis = None
    if inventory["known"]:
        if book is None and inventory["total_qty"] == 0:
            basis, revision = 0, 0
        elif (book is not None and book.updated_at <= now
                and book.inventory_revision == inventory["revision"]):
            position = accounting._position(symbol)
            actual = {(lot["id"], lot["bucket"]): lot["quantity"]
                      for lot in position["payload"]["batches"]}
            if actual == {(lot.lot_id, lot.bucket): lot.quantity for lot in book.lots}:
                basis = book.retained_basis_fen
    return dict(retained_basis_fen=basis, book_revision=revision)
