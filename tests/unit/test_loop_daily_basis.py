"""Frozen replay admits same-provider daily prices without future or raw fallbacks."""

import sqlite3
from decimal import Decimal
from types import SimpleNamespace

import pytest
from tests.integration.test_backtest_market_store import _calendar, _daily
from tests.unit.test_monitor_loop_cutoff import daily_plan
from tests.unit.test_monitor_loop_schedule import at

from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.loop_replay import _Frames, _insert


def frames(proofs):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE arrival(at TEXT, identity TEXT PRIMARY KEY, kind TEXT, payload TEXT)")
    calendar = tuple(
        _calendar().model_copy(
            update={
                "cal_date": at(d).date(),
                "previous_trade_date": at(d - 1).date(),
            }
        )
        for d in (24, 25)
    )
    for d in (24, 25):
        bar = _daily().model_copy(update={"trade_date": at(d).date(), "received_at": at(d, 15, 20)})
        _insert(db, bar.received_at, "DAILY", bar.model_dump_json())
    _insert(db, at(25, 9, 31), "BOUNDARY", "")
    run = SimpleNamespace(
        boundary=SimpleNamespace(started_at=at(24, 15, 20), evidence_cutoff=at(25, 15, 20))
    )
    return db, _Frames(
        db,
        daily_plan(),
        run,
        calendar,
        CancellationToken(),
        lambda _: None,
        adjustment_factors=proofs,
    )


def proof(day, factor="1", available=None):
    from trade_plan_monitor.backtest.daily_basis import HistoricalAdjustmentFactor

    return HistoricalAdjustmentFactor(
        symbol=_daily().symbol,
        trade_date=at(day).date(),
        factor=Decimal(factor),
        available_at=available or at(day, 9, 30),
        collected_at=at(26, 16),
    )


def test_daily_arrivals_reach_runtime_and_anchor_changes_only_when_available():
    db, source = frames((proof(24), proof(25, "2")))
    try:
        values = list(source)
        assert values[0].runtime.series is not None
        assert values[0].runtime.series.bars[-1].close == Decimal(_daily().close_fen)
        assert values[1].runtime.series.bars[-1].close == Decimal(_daily().close_fen) / 2
        assert values[-1].runtime.series.bars[-1].trade_date == at(25).date()
        assert not any("PRICE_BASIS_UNVERIFIED" in f.runtime.data_blockers for f in values)
        assert all(
            b.available_at <= f.runtime.evaluated_at for f in values for b in f.runtime.series.bars
        )
    finally:
        db.close()


@pytest.mark.parametrize("problem", ["missing", "future", "wrong-symbol"])
def test_missing_or_future_or_foreign_anchor_never_admits_raw_daily(problem):
    proofs = (
        ()
        if problem == "missing"
        else (
            proof(24, available=at(25, 16))
            if problem == "future"
            else proof(24).model_copy(update={"symbol": "600001.SH"}),
        )
    )
    db, source = frames(proofs)
    try:
        first = next(iter(source))
        assert first.runtime.series is None
        assert "PRICE_BASIS_UNVERIFIED" in first.runtime.data_blockers
    finally:
        db.close()


def test_basis_store_preserves_receipt_detects_tampering_and_has_no_read_side_effect(tmp_path):
    from trade_plan_monitor.backtest.daily_basis import DailyBasisStore

    store = DailyBasisStore(tmp_path / "market.sqlite3")
    assert store.read(_daily().symbol, at(24).date(), at(25).date()) == ()
    assert not store.path.exists()
    store.record((proof(24), proof(25)))
    values = store.read(_daily().symbol, at(24).date(), at(25).date(), cutoff=at(24, 16))
    assert values == (proof(24),)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE daily_factor SET collected_at='corrupted'")
    with pytest.raises(ValueError, match="integrity"):
        store.read(_daily().symbol, at(24).date(), at(25).date())
