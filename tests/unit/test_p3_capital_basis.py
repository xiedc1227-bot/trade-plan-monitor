"""Historical cost release follows exact actual lots, preserving residual fen."""

import pytest
from pydantic import ValidationError

from trade_plan_monitor.decision.p3_basis import CapitalLot, release_basis, retained_basis


def lot(identity="a", quantity=400, basis=450001, bucket="TACTICAL"):
    return CapitalLot(lot_id=identity, bucket=bucket, quantity=quantity,
                      retained_basis_fen=basis, provenance_ref="explicit-opening")


def test_partial_lot_then_full_lot_sale_conserves_every_fen():
    first = release_basis((lot(),), [{"id": "a", "bucket": "TACTICAL", "quantity": 100}])
    assert first.released_fen == 112500
    assert first.lots[0].quantity == 300 and first.lots[0].retained_basis_fen == 337501
    final = release_basis(first.lots, [{"id": "a", "bucket": "TACTICAL", "quantity": 300}])
    assert final.released_fen == 337501 and final.lots == ()
    assert first.released_fen+final.released_fen == 450001
    assert retained_basis(final.lots) == 0


def test_exact_authoritative_lot_wins_instead_of_new_fifo_allocation():
    old, new, core = lot("old"), lot("new", basis=100000), lot("core", bucket="CORE")
    r = release_basis((old, new, core), [{"id": "new", "bucket": "TACTICAL", "quantity": 100}])
    assert r.released_fen == 25000 and r.lots[0] == old and r.lots[2] == core
    assert r.lots[1].retained_basis_fen == 75000


def test_unknown_cost_stays_unknown_until_unknown_lots_are_gone():
    known, unknown = lot(), lot("unknown", quantity=100, basis=None)
    assert retained_basis((known, unknown)) is None
    r = release_basis((known, unknown), [
        {"id": "unknown", "bucket": "TACTICAL", "quantity": 100}])
    assert r.released_fen is None and retained_basis(r.lots) == 450001
    assert lot(basis=0).retained_basis_fen == 0


@pytest.mark.parametrize("allocations", [
    [{"id": "missing", "bucket": "TACTICAL", "quantity": 100}],
    [{"id": "a", "bucket": "CORE", "quantity": 100}],
    [{"id": "a", "bucket": "TACTICAL", "quantity": 500}],
    [{"id": "a", "bucket": "TACTICAL", "quantity": 99}],
    [{"id": "a", "bucket": "TACTICAL", "quantity": 100}]*2,
])
def test_invalid_actual_allocations_cannot_release_budget(allocations):
    with pytest.raises(ValueError):
        release_basis((lot(),), allocations)


def test_duplicate_or_overflow_basis_never_yields_a_known_amount():
    with pytest.raises(ValueError):
        retained_basis((lot(), lot()))
    with pytest.raises(ValueError):
        retained_basis((lot("a", basis=9007199254740991), lot("b")))
    with pytest.raises(ValidationError):
        lot(basis=True)


def test_many_whole_sales_preserve_the_exact_original_basis():
    current = (lot(quantity=1000, basis=987654321),)
    released = 0
    for _ in range(10):
        outcome = release_basis(current, [{"id": "a", "bucket": "TACTICAL", "quantity": 100}])
        released += outcome.released_fen
        current = outcome.lots
    assert released == 987654321 and not current
