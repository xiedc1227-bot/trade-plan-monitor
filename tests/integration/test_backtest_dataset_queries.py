"""Bounded dataset catalog queries and signed keyset traversal."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import DatasetItem, DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.dataset_service import (
    BacktestDatasetFilters,
    BacktestDatasetService,
    DatasetNotFoundError,
)
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.pagination import HmacCursorSigner, InvalidCursorError
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile

SHANGHAI = ZoneInfo("Asia/Shanghai")
PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1
DATASET_ROUTE = "/backtest-datasets"
DATASET_ORDER = "createdAt DESC,datasetHash DESC"


def _dataset_hash(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _insert_dataset(
    store: BacktestMarketStore,
    *,
    label: str,
    created_at: str,
    symbol: str = "600000.SH",
    start: date = date(2026, 8, 21),
    end: date = date(2026, 8, 24),
) -> str:
    scope = DatasetScope(
        symbols=(symbol,),
        start=start,
        end=end,
        warmup_start=start,
        historical_profile=PROFILE,
    )
    artifact_hash = _dataset_hash(f"artifact:{label}")
    item = DatasetItem(
        natural_key=f"MINUTE:{symbol}:{start.isoformat()}",
        artifact_hash=artifact_hash,
        kind="MINUTE",
        symbol=symbol,
        trade_date=start,
    )
    identity = {
        "schema_version": "backtest-dataset-v1",
        "scope": scope.model_dump(mode="python", round_trip=True),
        "items": [item.model_dump(mode="python", round_trip=True)],
    }
    dataset_hash = sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    manifest = DatasetManifest(dataset_hash=dataset_hash, scope=scope, items=(item,))
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO market_artifact (
                artifact_hash, kind, provider, contract_version,
                natural_key, content_json, created_at
            ) VALUES (?, 'MINUTE', 'TUSHARE', ?, ?, '{}', ?)
            """,
            (artifact_hash, PROFILE.value, item.natural_key, created_at),
        )
        connection.execute(
            "INSERT INTO market_dataset (dataset_hash, manifest_json, created_at) VALUES (?, ?, ?)",
            (
                dataset_hash,
                canonical_json(manifest.model_dump(mode="python", round_trip=True)),
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO market_dataset_item (
                dataset_hash, natural_key, artifact_hash, kind, symbol, trade_date
            ) VALUES (?, ?, ?, 'MINUTE', ?, ?)
            """,
            (
                dataset_hash,
                f"MINUTE:{symbol}:{start.isoformat()}",
                artifact_hash,
                symbol,
                start.isoformat(),
            ),
        )
        connection.commit()
    return dataset_hash


def _service(store: BacktestMarketStore, key: bytes = b"k" * 32) -> BacktestDatasetService:
    return BacktestDatasetService(store=store, cursor_signer=HmacCursorSigner(key))


def test_get_dataset_returns_bounded_summary_without_manifest_membership(
    tmp_path,
    monkeypatch,
) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    dataset_hash = _insert_dataset(
        store,
        label="bounded",
        created_at="2026-08-27T02:03:04.000005+00:00",
    )

    monkeypatch.setattr(
        store,
        "dataset_manifest",
        lambda _: pytest.fail("public summary must not load the full manifest"),
    )
    summary = _service(store).get_dataset(dataset_hash)
    serialized = summary.model_dump(mode="json")

    assert set(serialized) == {
        "dataset_hash",
        "schema_version",
        "scope",
        "coverage",
        "created_at",
        "verified_at",
    }
    assert "items" not in summary.model_dump_json()
    assert "natural_key" not in summary.model_dump_json()
    assert "provider" not in summary.scope.model_dump_json()
    assert "2026-08-27T10:03:04.000005+08:00" in summary.model_dump_json()
    assert summary.created_at == datetime(2026, 8, 27, 10, 3, 4, 5, tzinfo=SHANGHAI)
    assert summary.verified_at == summary.created_at
    assert summary.coverage.symbol_count == 1
    assert summary.coverage.trading_day_count == 1
    assert summary.coverage.minute_day_count == 1
    assert summary.coverage.minute_bar_count == 240
    assert summary.coverage.blockers == ()


def test_get_dataset_uses_a_stable_not_found_error(tmp_path) -> None:
    service = _service(BacktestMarketStore(tmp_path / "market.sqlite3"))

    with pytest.raises(DatasetNotFoundError, match="^dataset not found$"):
        service.get_dataset("0" * 64)


@pytest.mark.parametrize("limit", [True, 0, 101])
def test_list_dataset_limit_is_bounded(tmp_path, limit) -> None:
    service = _service(BacktestMarketStore(tmp_path / "market.sqlite3"))

    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        service.list_datasets(limit=limit)


def test_signed_keyset_traversal_is_stable_and_excludes_later_inserts(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    tied_low = _insert_dataset(
        store,
        label="tied-low",
        created_at="2026-08-27T02:00:00.000000+00:00",
    )
    tied_high = _insert_dataset(
        store,
        label="tied-high",
        created_at="2026-08-27T02:00:00.000000+00:00",
    )
    oldest = _insert_dataset(
        store,
        label="oldest",
        created_at="2026-08-27T01:00:00.000000+00:00",
    )
    expected = sorted((tied_low, tied_high), reverse=True) + [oldest]
    service = _service(store)

    first = service.list_datasets(limit=2)
    inserted_later = _insert_dataset(
        store,
        label="inserted-later",
        created_at="2026-08-27T03:00:00.000000+00:00",
    )
    second = service.list_datasets(limit=2, cursor=first.next_cursor)

    visited = [item.dataset_hash for item in (*first.items, *second.items)]
    assert visited == expected
    assert inserted_later not in visited
    assert len(visited) == len(set(visited))
    assert first.has_more is True
    assert first.next_cursor is not None
    assert len(first.next_cursor) <= 512
    assert second.has_more is False
    assert second.next_cursor is None
    assert first.high_watermark == second.high_watermark
    assert len(first.high_watermark) <= 512


def test_dataset_filters_are_applied_and_bound_to_the_cursor(tmp_path) -> None:
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _insert_dataset(
        store,
        label="sh-new",
        created_at="2026-08-27T03:00:00.000000+00:00",
    )
    sh_old = _insert_dataset(
        store,
        label="sh-old",
        created_at="2026-08-27T02:00:00.000000+00:00",
    )
    _insert_dataset(
        store,
        label="sz",
        symbol="000001.SZ",
        created_at="2026-08-27T01:00:00.000000+00:00",
    )
    service = _service(store)
    sh_filter = BacktestDatasetFilters(symbol="600000.SH")
    first = service.list_datasets(limit=1, filters=sh_filter)

    assert first.filters == sh_filter
    assert first.has_more is True
    assert first.next_cursor is not None
    second = service.list_datasets(limit=1, cursor=first.next_cursor, filters=sh_filter)
    assert [item.dataset_hash for item in second.items] == [sh_old]

    with pytest.raises(InvalidCursorError, match="^invalid cursor$"):
        service.list_datasets(
            limit=1,
            cursor=first.next_cursor,
            filters=BacktestDatasetFilters(symbol="000001.SZ"),
        )


def test_tampered_route_filter_and_order_mismatches_fail_uniformly() -> None:
    signer = HmacCursorSigner(b"s" * 32)
    filters = {"symbol": "600000.SH"}
    token = signer.encode(
        route=DATASET_ROUTE,
        filters=filters,
        order=DATASET_ORDER,
        high_water=("2026-08-27T11:00:00.000000+08:00", "f" * 64),
        last_seen=("2026-08-27T10:00:00.000000+08:00", "e" * 64),
    )
    failures = (
        (token[:-1] + ("A" if token[-1] != "A" else "B"), DATASET_ROUTE, filters, DATASET_ORDER),
        (token, "/backtest-runs", filters, DATASET_ORDER),
        (token, DATASET_ROUTE, {"symbol": "000001.SZ"}, DATASET_ORDER),
        (token, DATASET_ROUTE, filters, "datasetHash ASC"),
    )

    for candidate, route, candidate_filters, order in failures:
        with pytest.raises(InvalidCursorError) as error:
            signer.decode(
                candidate,
                route=route,
                filters=candidate_filters,
                order=order,
            )
        assert str(error.value) == "invalid cursor"
