"""Incremental active-v2 exports and explicit offline v1 compatibility."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest import reporting
from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.results import (
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunStatus,
    BacktestRunSummary,
    ExportCancelled,
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


def _summary(run_input: BacktestRunInput, label: str, *, fill_count: int) -> BacktestRunSummary:
    return BacktestRunSummary(
        run_id=run_input.run_id,
        plan_sha256=run_input.plan_sha256,
        dataset_hash=run_input.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=datetime(2026, 8, 24, 15, 30, 1, 123, tzinfo=_SHANGHAI),
        event_start=run_input.start,
        event_end=run_input.end,
        symbols=(run_input.plan_snapshot.symbol,),
        coverage={
            "dailyEquityCount": 0,
            "decisionCount": 0,
            "detailCount": 0,
            "fillCount": fill_count,
            "outcomeCount": 0,
            "signalCount": 0,
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
        final_metrics={"totalReturn": "0.010000"},
    )


def _fill(run_id: str, index: int) -> BacktestFillRecord:
    filled_at = datetime(2026, 8, 24, 9, 30, index % 60, index, tzinfo=_SHANGHAI)
    return BacktestFillRecord.from_value(
        {
            "fill_id": _hash(f"{run_id}:fill:{index:04d}"),
            "run_id": run_id,
            "filled_at": filled_at,
            "side": "BUY" if index % 2 == 0 else "SELL",
            "symbol": "003043.SZ",
            "bucket": "TACTICAL",
            "quantity": 100,
            "price_fen": 1_000 + index,
            "notional_fen": 100_000 + index * 100,
            "fees": {"total_fen": 500 + index},
            "cash_delta_fen": -(100_500 + index * 101),
            "realized_pnl_fen": None if index % 2 == 0 else index,
        },
        version="v2",
    )


def _materialize_v2(
    store: BacktestResultStore,
    label: str,
    *,
    fill_count: int,
) -> tuple[BacktestRunSummary, tuple[BacktestFillRecord, ...]]:
    run_input = _run_input(label)
    fills = tuple(_fill(run_input.run_id, index) for index in range(fill_count))
    summary = _summary(run_input, label, fill_count=len(fills))
    assert store.record_verified_run(summary, run_input=run_input)
    for index in range(0, len(fills), 1_000):
        assert store.record_fills(summary.run_id, fills[index : index + 1_000]) == len(
            fills[index : index + 1_000]
        )
    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    assert store.mark_run_materialized(
        summary.run_id,
        expected_fill_count=len(fills),
        expected_detail_count=0,
        expected_report_hash=report_hash,
        expected_fill_set_hash=backtest_fill_set_hash(fills, version="v2"),
        expected_detail_set_hash=backtest_detail_set_hash((), version="v2"),
    )
    return summary, fills


def test_active_v2_summary_and_fill_exports_are_byte_stable_shanghai_streams(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "results.sqlite3")
    summary, fills = _materialize_v2(store, "stable-export", fill_count=2)
    before = store.statistics()

    first_summary_chunks = tuple(
        reporting.iter_export_summary(store, summary.run_id, cancelled=lambda: False)
    )
    second_summary = b"".join(
        reporting.iter_export_summary(store, summary.run_id, cancelled=lambda: False)
    )
    first_fill_chunks = tuple(
        reporting.iter_export_fills(store, summary.run_id, cancelled=lambda: False)
    )
    second_fills = b"".join(
        reporting.iter_export_fills(store, summary.run_id, cancelled=lambda: False)
    )

    assert b"".join(first_summary_chunks) == second_summary
    assert b"".join(first_fill_chunks) == second_fills
    assert sha256(second_fills).hexdigest() == (
        "e3375b11598517613ff5c0d7af17e0b7378355580a0ce6ced8ee703c56eb519c"
    )
    assert first_summary_chunks and first_fill_chunks
    assert all(
        0 < len(chunk) <= 64 * 1_024 for chunk in (*first_summary_chunks, *first_fill_chunks)
    )
    summary_payload = json.loads(second_summary)
    assert summary_payload["schemaVersion"] == "backtest-report-summary-v2"
    assert summary_payload["completedAt"] == "2026-08-24T15:30:01.000123+08:00"
    fill_text = second_fills.decode("utf-8")
    assert fill_text.startswith("schema_version,run_id,fill_id,filled_at,")
    assert fill_text.count("backtest-simulated-fills-v2") == len(fills)
    assert "+08:00" in fill_text
    assert "+00:00" not in fill_text
    exported_fills = tuple(
        fill
        for batch in store.iter_export_fill_batches(summary.run_id, cancelled=lambda: False)
        for fill in batch
    )
    assert exported_fills == tuple(sorted(fills, key=lambda fill: (fill.filled_at, fill.fill_id)))
    assert store.statistics() == before


def test_v2_fill_export_observes_cancellation_between_bounded_database_batches(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "results.sqlite3")
    summary, _fills = _materialize_v2(store, "cancel-export", fill_count=1_001)
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    cancelled_chunks = tuple(reporting.iter_export_fills(store, summary.run_id, cancelled))

    assert checks == 2
    assert cancelled_chunks == ()

    stop_after_first_batch = False
    batches = store.iter_export_fill_batches(
        summary.run_id,
        cancelled=lambda: stop_after_first_batch,
    )
    assert len(next(batches)) == 1_000
    stop_after_first_batch = True
    with pytest.raises(ExportCancelled):
        next(batches)
    batches.close()


@pytest.mark.parametrize("surface", ["payload", "sql_identity"])
def test_v2_fill_export_rejects_tampering_before_the_first_fill_row(
    tmp_path: Path,
    surface: str,
) -> None:
    store = BacktestResultStore(tmp_path / f"tampered-export-{surface}.sqlite3")
    summary, fills = _materialize_v2(store, f"tampered-export-{surface}", fill_count=1)
    with sqlite3.connect(store.database_path) as connection:
        if surface == "payload":
            connection.execute(
                "UPDATE backtest_fill SET payload_json = payload_json || ' ' WHERE fill_id = ?",
                (fills[0].fill_id,),
            )
        else:
            connection.execute(
                "UPDATE backtest_fill SET filled_at = ? WHERE fill_id = ?",
                ("2026-08-24T09:31:00.000000+08:00", fills[0].fill_id),
            )
        connection.commit()

    chunks = reporting.iter_export_fills(store, summary.run_id, cancelled=lambda: False)
    assert next(chunks) == (
        b"schema_version,run_id,fill_id,filled_at,side,symbol,bucket,quantity,"
        b"price_fen,notional_fen,fees_fen,cash_delta_fen,realized_pnl_fen\n"
    )
    failure = RuntimeError if surface == "payload" else ResultConflictError
    with pytest.raises(failure):
        next(chunks)
    chunks.close()


def test_v2_fill_export_verifies_the_final_batch_before_the_first_fill_row(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "tampered-final-batch-export.sqlite3")
    summary, fills = _materialize_v2(store, "tampered-final-batch-export", fill_count=1_001)
    final_fill = max(fills, key=lambda fill: fill.fill_id)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE backtest_fill SET filled_at = ? WHERE fill_id = ?",
            ("2026-08-24T09:31:00.000000+08:00", final_fill.fill_id),
        )
        connection.commit()

    chunks = reporting.iter_export_fills(store, summary.run_id, cancelled=lambda: False)
    assert next(chunks) == (
        b"schema_version,run_id,fill_id,filled_at,side,symbol,bucket,quantity,"
        b"price_fen,notional_fen,fees_fen,cash_delta_fen,realized_pnl_fen\n"
    )
    with pytest.raises(ResultConflictError):
        next(chunks)
    chunks.close()


def test_active_export_rejects_v1_while_named_offline_export_preserves_v1_bytes(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "results.sqlite3")
    run_id = _hash("legacy-run")
    summary = BacktestRunSummary(
        run_id=run_id,
        plan_sha256=_hash("legacy-plan"),
        dataset_hash=_hash("legacy-dataset"),
        status=BacktestRunStatus.COMPLETED,
        completed_at=datetime(2026, 8, 24, 7, 20, tzinfo=UTC),
        event_start=date(2026, 8, 20),
        event_end=date(2026, 8, 24),
        symbols=("003043.SZ",),
        coverage={"fillCount": 1},
        assumptions={"reportHash": _hash("legacy-report")},
        formula_versions={"execution": "execution-model-v1", "indicator": "ta-v1"},
        final_metrics={"totalReturn": "0"},
    )
    fill = BacktestFillRecord.from_value(
        {
            "fill_id": "legacy-fill-001",
            "run_id": run_id,
            "filled_at": datetime(2026, 8, 24, 1, 36, tzinfo=UTC),
            "side": "BUY",
            "symbol": "003043.SZ",
            "bucket": "TACTICAL",
            "quantity": 100,
            "price_fen": 6_401,
            "notional_fen": 640_100,
            "fees": {"total_fen": 507},
            "cash_delta_fen": -640_607,
            "realized_pnl_fen": None,
        }
    )
    json_path = tmp_path / "legacy-summary.json"
    csv_path = tmp_path / "legacy-fills.csv"

    reporting.write_offline_v1_compatibility_report_files(
        summary,
        (fill,),
        json_path=json_path,
        csv_path=csv_path,
    )
    assert json.loads(json_path.read_bytes())["schemaVersion"] == "backtest-report-summary-v1"
    assert b"2026-08-24T01:36:00.000000+00:00" in csv_path.read_bytes()

    assert store.record_run(summary)
    assert store.record_fills(run_id, (fill,)) == 1
    assert store.mark_run_materialized(
        run_id,
        expected_fill_count=1,
        expected_detail_count=0,
        expected_report_hash=_hash("legacy-report"),
        expected_fill_set_hash=backtest_fill_set_hash((fill,), version="v1"),
        expected_detail_set_hash=backtest_detail_set_hash((), version="v1"),
    )
    with pytest.raises(KeyError, match="active v2"):
        tuple(reporting.iter_export_summary(store, run_id, cancelled=lambda: False))
