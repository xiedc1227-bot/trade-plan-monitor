"""One row-local representation retains the original evidence byte contract."""

from datetime import datetime, timedelta

import pytest
from tests.unit.test_market_index_data import SHANGHAI, _daily_bars, _five_minute_bars

from trade_plan_monitor.market_index import canonical
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexSnapshot,
    ReturnFactRequest,
    ReturnWindow,
    SmaFactRequest,
    SmaLookbackFactRequest,
)
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot


@pytest.fixture
def snapshot():
    cutoff = datetime(2026, 9, 2, 10, 35, tzinfo=SHANGHAI)
    return build_market_index_snapshot(
        index_code=MarketIndexCode.CHINEXT, decision_cutoff=cutoff,
        requests=(SmaFactRequest(period=3), SmaLookbackFactRequest(period=2, lookback=2),
                  ReturnFactRequest(window=ReturnWindow.FIVE_MINUTE_BUCKETS, window_size=2),
                  ReturnFactRequest(window=ReturnWindow.OFFICIAL_OPEN_DAYS, window_size=2)),
        five_minute_bars=_five_minute_bars(), official_daily_bars=_daily_bars(),
        content_revision=1, observed_at=cutoff + timedelta(seconds=2),
        observed_no_later_than=cutoff + timedelta(seconds=2),
    )


def test_verified_json_exports_one_tree_and_matches_original_bytes(snapshot, monkeypatch):
    assert snapshot.snapshot_hash == (
        "2ff6cf1474a11e92fa146bff23b708092e8506107c793047523041e91c4814fa"
    )
    expected = canonical.canonical_json(snapshot)
    original = canonical.canonical_value
    exports = []

    def observe(value):
        if isinstance(value, MarketIndexSnapshot):
            exports.append(value)
        return original(value)

    monkeypatch.setattr(canonical, "canonical_value", observe)
    assert canonical.verified_market_index_snapshot_json(snapshot) == expected
    assert exports == [snapshot]
    assert canonical.validate_market_index_snapshot_integrity(snapshot) is None


@pytest.mark.parametrize("field", [
    "bar_set_hash", "request_set_hash", "formula_definition_hash", "snapshot_hash",
])
def test_each_hash_gate_remains_required(snapshot, field):
    changed = snapshot.model_copy(update={field: "0" * 64})
    with pytest.raises(ValueError, match="mismatch"):
        canonical.verified_market_index_snapshot_json(changed)
    with pytest.raises(ValueError, match="mismatch"):
        canonical.validate_market_index_snapshot_integrity(changed)


def test_rehashed_fact_formula_still_fails(snapshot):
    fact = snapshot.indicator_facts[0].model_copy(update={"formula_definition_hash": "f" * 64})
    payload = snapshot.model_dump(mode="python", round_trip=True, exclude={"snapshot_hash"})
    payload["indicator_facts"] = (fact, *snapshot.indicator_facts[1:])
    changed = snapshot.model_copy(update={
        "indicator_facts": payload["indicator_facts"],
        "snapshot_hash": canonical.market_index_snapshot_hash(payload),
    })
    with pytest.raises(ValueError, match="fact formula hash mismatch"):
        canonical.verified_market_index_snapshot_json(changed)


def test_reordered_requests_and_facts_keep_sorted_set_and_literal_root(snapshot):
    payload = snapshot.model_dump(mode="python", round_trip=True, exclude={"snapshot_hash"})
    payload["fact_requests"] = tuple(reversed(snapshot.fact_requests))
    payload["indicator_facts"] = tuple(reversed(snapshot.indicator_facts))
    reordered = MarketIndexSnapshot.model_validate({
        **payload, "snapshot_hash": canonical.market_index_snapshot_hash(payload),
    })
    assert reordered.request_set_hash == snapshot.request_set_hash
    assert canonical.verified_market_index_snapshot_json(reordered) == canonical.canonical_json(
        reordered
    )


def test_exact_public_type_boundaries(snapshot):
    class SnapshotSubclass(MarketIndexSnapshot):
        pass

    with pytest.raises(TypeError, match="snapshot must"):
        canonical.verified_market_index_snapshot_json(
            SnapshotSubclass.model_validate(snapshot.model_dump())
        )
    with pytest.raises(TypeError, match="requests must"):
        canonical.verified_market_index_snapshot_json(
            snapshot.model_copy(update={"fact_requests": list(snapshot.fact_requests)})
        )


def test_bar_subclass_is_rejected_before_normalizing(snapshot):
    from trade_plan_monitor.market_index.models import MarketIndexBar

    class BarSubclass(MarketIndexBar):
        pass

    subclass_bar = BarSubclass.model_validate(snapshot.five_minute_bars[0].model_dump())
    changed = snapshot.model_copy(update={"five_minute_bars": (subclass_bar,)})
    with pytest.raises(TypeError, match="exact tuple of MarketIndexBar"):
        canonical.verified_market_index_snapshot_json(changed)


@pytest.mark.parametrize("bars_count", [128, None], ids=["128-bars", "near-16-MiB"])
def test_larger_payload_keeps_full_hash_and_literal_bytes(snapshot, bars_count):
    # Repeated valid typed bars isolate representation size; this is not market history.
    near_limit = bars_count is None
    if near_limit:
        bar_bytes = len(canonical.canonical_json(snapshot.five_minute_bars[0]).encode("utf-8")) + 1
        bars_count = (15 * 1024 * 1024 + 512 * 1024) // bar_bytes
    bars = (snapshot.five_minute_bars[0],) * bars_count
    changed = snapshot.model_copy(update={
        "five_minute_bars": bars,
        "bar_set_hash": canonical.market_index_bar_set_hash(bars + snapshot.official_daily_bars),
    })
    payload = changed.model_dump(mode="python", round_trip=True, exclude={"snapshot_hash"})
    changed = changed.model_copy(update={"snapshot_hash": canonical.market_index_snapshot_hash(
        payload
    )})
    literal = canonical.canonical_json(changed)
    if near_limit:
        assert 15 * 1024 * 1024 < len(literal.encode("utf-8")) < 16 * 1024 * 1024
    parsed = MarketIndexSnapshot.model_validate_json(literal)
    assert canonical.verified_market_index_snapshot_json(parsed) == literal
