"""Bounded public result queries, availability, and signed traversal."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.pagination import HmacCursorSigner, InvalidCursorError
from trade_plan_monitor.backtest.result_service import (
    BacktestArtifactAvailability,
    BacktestDetailFilters,
    BacktestResultService,
    BacktestRunFilters,
)
from trade_plan_monitor.backtest.results import (
    BacktestDetailKind,
    BacktestDetailRecord,
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunStatus,
    BacktestRunSummary,
    ResultConflictError,
    backtest_detail_set_hash,
    backtest_fill_set_hash,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile

_PLAN_PATH = Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _hash(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _run_input(label: str) -> BacktestRunInput:
    plan = load_plan_yaml(_PLAN_PATH.read_text(encoding="utf-8"))
    manifest = DatasetManifest(
        dataset_hash=_hash(f"dataset:{label}"),
        scope=DatasetScope(
            symbols=(plan.symbol,),
            start=date(2026, 8, 20),
            end=date(2026, 8, 24),
            warmup_start=date(2025, 8, 20),
            historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        ),
        items=(),
    )
    return BacktestRunInput.create(
        plan=plan,
        manifest=manifest,
        initial_cash_fen=10_000_000,
        initial_lots=(),
        execution_config=ExecutionConfig(
            commission_rate=Decimal("0.0003"),
            minimum_commission_fen=500,
            stamp_duty_rate=Decimal("0.0005"),
            transfer_fee_rate=Decimal("0.00001"),
            buy_slippage_bps=Decimal("2"),
            sell_slippage_bps=Decimal("2"),
        ),
        manual_event_risk=False,
    )


def _fill(run_id: str, index: int) -> BacktestFillRecord:
    return BacktestFillRecord.from_value(
        {
            "fill_id": _hash(f"{run_id}:fill:{index}"),
            "run_id": run_id,
            "filled_at": datetime(2026, 8, 24, 13, index, tzinfo=_SHANGHAI),
            "symbol": "003043.SZ",
            "quantity": 100,
            "price_fen": 1_000 + index,
            "fees": {"commission_fen": 500},
        },
        version="v2",
    )


def _detail(
    run_id: str,
    kind: BacktestDetailKind,
    identity: str,
    minute: int,
) -> BacktestDetailRecord:
    return BacktestDetailRecord(
        detail_id=identity * 64,
        run_id=run_id,
        kind=kind,
        event_at=datetime(2026, 8, 24, 14, minute, tzinfo=_SHANGHAI),
        payload={"identity": f"{kind.value}:{identity}"},
    )


def _materialize(
    store: BacktestResultStore,
    label: str,
    *,
    completed_at: datetime,
    fills: tuple[BacktestFillRecord, ...] | None = None,
    details: tuple[BacktestDetailRecord, ...] | None = None,
    retention_at: datetime | None = None,
    materialize: bool = True,
) -> tuple[BacktestRunSummary, tuple[BacktestFillRecord, ...], tuple[BacktestDetailRecord, ...]]:
    run_input = _run_input(label)
    resolved_fills = fills or ()
    resolved_details = details or ()
    counts = {kind: 0 for kind in BacktestDetailKind}
    for detail in resolved_details:
        counts[detail.kind] += 1
    summary = BacktestRunSummary(
        run_id=run_input.run_id,
        plan_sha256=run_input.plan_sha256,
        dataset_hash=run_input.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=completed_at,
        event_start=run_input.start,
        event_end=run_input.end,
        symbols=(run_input.plan_snapshot.symbol,),
        coverage={
            "decisionCount": counts[BacktestDetailKind.DECISION],
            "signalCount": counts[BacktestDetailKind.SIGNAL],
            "outcomeCount": counts[BacktestDetailKind.EXECUTION_OUTCOME],
            "dailyEquityCount": counts[BacktestDetailKind.DAILY_EQUITY],
            "detailCount": len(resolved_details),
            "fillCount": len(resolved_fills),
        },
        assumptions={
            "executionConfigHash": run_input.execution_config.config_hash,
            "manualEventRisk": run_input.manual_event_risk,
            "reportHash": _hash(f"report:{label}"),
        },
        formula_versions={
            "execution": run_input.execution_config.formula_version,
            "indicator": run_input.indicator_formula_version,
            "runner": run_input.run_formula_version,
        },
        final_metrics={"totalReturn": "0"},
    )
    assert store.record_verified_run(
        summary,
        run_input=run_input,
        retention_at=retention_at,
    )
    recorded_fill_count = 0
    for start in range(0, len(resolved_fills), 1_000):
        recorded_fill_count += store.record_fills(
            summary.run_id,
            resolved_fills[start : start + 1_000],
        )
    assert recorded_fill_count == len(resolved_fills)
    recorded_detail_count = 0
    for start in range(0, len(resolved_details), 1_000):
        recorded_detail_count += store.record_details(
            summary.run_id,
            resolved_details[start : start + 1_000],
        )
    assert recorded_detail_count == len(resolved_details)
    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    if materialize:
        assert store.mark_run_materialized(
            summary.run_id,
            expected_fill_count=len(resolved_fills),
            expected_detail_count=len(resolved_details),
            expected_report_hash=report_hash,
            expected_fill_set_hash=backtest_fill_set_hash(resolved_fills, version="v2"),
            expected_detail_set_hash=backtest_detail_set_hash(resolved_details, version="v2"),
        )
    return summary, resolved_fills, resolved_details


def _service(store: BacktestResultStore) -> BacktestResultService:
    return BacktestResultService(store=store, cursor_signer=HmacCursorSigner(b"q" * 32))


@pytest.mark.parametrize("limit", [True, 0, 101])
def test_all_result_page_limits_are_bounded(tmp_path: Path, limit: object) -> None:
    service = _service(BacktestResultStore(tmp_path / "results.sqlite3"))

    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        service.list_runs(limit=limit)  # type: ignore[arg-type]


def test_run_keyset_filters_are_stable_and_exclude_later_inserts(tmp_path: Path) -> None:
    store = BacktestResultStore(tmp_path / "runs.sqlite3")
    expected: list[str] = []
    for label, hour in (("new", 11), ("middle", 10), ("old", 9)):
        summary, _, _ = _materialize(
            store,
            label,
            completed_at=datetime(2026, 8, 24, hour, tzinfo=_SHANGHAI),
        )
        expected.append(summary.run_id)
    staged, staged_fills, staged_details = _materialize(
        store,
        "staged-before-page",
        completed_at=datetime(2026, 8, 24, 8, tzinfo=_SHANGHAI),
        materialize=False,
    )
    service = _service(store)

    first = service.list_runs(limit=2, filters=BacktestRunFilters(pinned=False))
    staged_report_hash = staged.assumptions["reportHash"]
    assert isinstance(staged_report_hash, str)
    assert store.mark_run_materialized(
        staged.run_id,
        expected_fill_count=len(staged_fills),
        expected_detail_count=len(staged_details),
        expected_report_hash=staged_report_hash,
        expected_fill_set_hash=backtest_fill_set_hash(staged_fills, version="v2"),
        expected_detail_set_hash=backtest_detail_set_hash(staged_details, version="v2"),
    )
    inserted, _, _ = _materialize(
        store,
        "inserted-later",
        completed_at=datetime(2026, 8, 24, 12, tzinfo=_SHANGHAI),
    )
    second = service.list_runs(
        limit=2,
        cursor=first.next_cursor,
        filters=BacktestRunFilters(pinned=False),
    )

    visited = [item.summary.run_id for item in (*first.items, *second.items)]
    assert visited == expected
    assert inserted.run_id not in visited
    assert staged.run_id not in visited
    assert len(visited) == len(set(visited))
    assert first.high_watermark == second.high_watermark
    assert first.has_more is True and second.has_more is False
    assert len(first.model_dump_json().encode("utf-8")) < 4 * 1024 * 1024

    with pytest.raises(InvalidCursorError, match="^invalid cursor$"):
        service.list_runs(
            limit=2,
            cursor=first.next_cursor,
            filters=BacktestRunFilters(pinned=True),
        )


def test_fill_and_detail_pages_use_declared_orders_and_availability(tmp_path: Path) -> None:
    store = BacktestResultStore(tmp_path / "details.sqlite3")
    run_input = _run_input("details")
    fills = tuple(_fill(run_input.run_id, index) for index in range(3))
    details = (
        _detail(run_input.run_id, BacktestDetailKind.DECISION, "a", 0),
        _detail(run_input.run_id, BacktestDetailKind.DECISION, "b", 1),
        _detail(run_input.run_id, BacktestDetailKind.DAILY_EQUITY, "f", 2),
    )
    summary, _, _ = _materialize(
        store,
        "details",
        completed_at=datetime(2026, 8, 24, 15, tzinfo=_SHANGHAI),
        fills=fills,
        details=details,
        retention_at=datetime(2026, 1, 1, tzinfo=_SHANGHAI),
    )
    service = _service(store)

    first_fills = service.list_fills(summary.run_id, limit=2)
    second_fills = service.list_fills(
        summary.run_id,
        limit=2,
        cursor=first_fills.next_cursor,
    )
    assert [item.fill_id for item in (*first_fills.items, *second_fills.items)] == [
        item.fill_id for item in fills
    ]

    decisions = service.list_details(
        summary.run_id,
        limit=1,
        filters=BacktestDetailFilters(kind=BacktestDetailKind.DECISION),
    )
    signals = service.list_details(
        summary.run_id,
        filters=BacktestDetailFilters(kind=BacktestDetailKind.SIGNAL),
    )
    equity = service.get_equity_series(summary.run_id)
    assert decisions.availability is BacktestArtifactAvailability.AVAILABLE
    assert decisions.has_more is True
    assert signals.availability is BacktestArtifactAvailability.NOT_RECORDED
    assert signals.items == () and signals.next_cursor is None and signals.has_more is False
    assert equity.availability is BacktestArtifactAvailability.AVAILABLE
    assert [item.detail_id for item in equity.items] == ["f" * 64]

    pruned = store.prune_details(
        as_of=datetime(2027, 1, 1, tzinfo=_SHANGHAI),
        batch_size=1,
    )
    assert pruned.deleted_count == 1
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM backtest_detail WHERE run_id = ? AND kind = 'DECISION'",
            (summary.run_id,),
        ).fetchone() == (1,)
    expired = service.list_details(
        summary.run_id,
        filters=BacktestDetailFilters(kind=BacktestDetailKind.DECISION),
    )
    assert expired.availability is BacktestArtifactAvailability.EXPIRED
    assert expired.items == () and expired.next_cursor is None and expired.has_more is False


def test_detail_page_uses_one_wal_snapshot_during_partial_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = BacktestResultStore(tmp_path / "snapshot.sqlite3")
    run_input = _run_input("snapshot-cleanup")
    details = (
        _detail(run_input.run_id, BacktestDetailKind.DECISION, "a", 0),
        _detail(run_input.run_id, BacktestDetailKind.DECISION, "b", 1),
    )
    summary, _, _ = _materialize(
        store,
        "snapshot-cleanup",
        completed_at=datetime(2026, 8, 24, 15, tzinfo=_SHANGHAI),
        details=details,
        retention_at=datetime(2026, 1, 1, tzinfo=_SHANGHAI),
    )
    cleanup_store = BacktestResultStore(store.database_path)
    original_connect = store._connect
    cleanup_started = False

    @contextmanager
    def interleaved_connect():
        nonlocal cleanup_started
        with original_connect() as connection:

            class _ConnectionProxy:
                def execute(self, query, parameters=()):
                    nonlocal cleanup_started
                    if not cleanup_started and "SELECT d.event_at, d.detail_id" in query:
                        cleanup_started = True
                        result = cleanup_store.prune_result_rows(
                            as_of=datetime(2027, 1, 1, tzinfo=_SHANGHAI),
                            remaining_budget=1,
                        )
                        assert result.deleted_count == 1
                    return connection.execute(query, parameters)

                def __getattr__(self, name):
                    return getattr(connection, name)

            yield _ConnectionProxy()

    monkeypatch.setattr(store, "_connect", interleaved_connect)

    page = _service(store).list_details(
        summary.run_id,
        filters=BacktestDetailFilters(kind=BacktestDetailKind.DECISION),
    )

    assert cleanup_started is True
    assert page.availability is BacktestArtifactAvailability.AVAILABLE
    assert tuple(item.detail_id for item in page.items) == tuple(item.detail_id for item in details)
    assert (
        cleanup_store.artifact_state(summary.run_id, BacktestDetailKind.DECISION).availability
        is BacktestArtifactAvailability.EXPIRED
    )
    assert len(cleanup_store.list_details(summary.run_id)) == 1


def test_public_detail_filter_and_equity_cap_fail_closed(tmp_path: Path) -> None:
    store = BacktestResultStore(tmp_path / "closed.sqlite3")

    with pytest.raises(ValueError, match="public detail kind"):
        BacktestDetailFilters(kind=BacktestDetailKind.DEBUG_TRACE)

    run_input = _run_input("equity-cap")
    details = tuple(
        BacktestDetailRecord(
            detail_id=_hash(f"equity:{index}"),
            run_id=run_input.run_id,
            kind=BacktestDetailKind.DAILY_EQUITY,
            event_at=datetime(2026, 8, 24, 14, index % 60, tzinfo=_SHANGHAI)
            + timedelta(days=index),
            payload={"index": index},
        )
        for index in range(2_001)
    )
    with pytest.raises(ResultConflictError, match="2,000"):
        _materialize(
            store,
            "equity-cap",
            completed_at=datetime(2026, 8, 24, 15, tzinfo=_SHANGHAI),
            details=details,
        )
