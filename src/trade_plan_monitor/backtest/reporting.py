"""Stable JSON/CSV emission and isolated persistence for completed backtests."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from hashlib import sha256
from io import StringIO
from itertools import islice
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from trade_plan_monitor.backtest.results import (
    BacktestDetailKind,
    BacktestDetailRecord,
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunStatus,
    BacktestRunSummary,
    ExportCancelled,
    backtest_detail_set_hash,
    backtest_fill_set_hash,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.backtest.runner import RUN_FORMULA_VERSION, BacktestRunReport

_MAX_RESULT_BATCH = 100
_MAX_EXPORT_CHUNK_BYTES = 64 * 1_024
_V2_FILL_FIELDS = (
    "schema_version",
    "run_id",
    "fill_id",
    "filled_at",
    "side",
    "symbol",
    "bucket",
    "quantity",
    "price_fen",
    "notional_fen",
    "fees_fen",
    "cash_delta_fen",
    "realized_pnl_fen",
)


class ReportPersistenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    summary_created: bool
    fills_created: int = Field(ge=0)
    details_created: int = Field(ge=0)


def persist_report(
    store: BacktestResultStore,
    report: BacktestRunReport,
    *,
    run_input: BacktestRunInput | None = None,
) -> ReportPersistenceResult:
    """Persist one immutable report without copying its historical market bars."""

    if not isinstance(store, BacktestResultStore):
        raise TypeError("store must be a BacktestResultStore")
    if not isinstance(report, BacktestRunReport):
        raise TypeError("report must be a BacktestRunReport")
    if run_input is not None and not isinstance(run_input, BacktestRunInput):
        raise TypeError("run_input must be a BacktestRunInput or None")
    version = "v2" if run_input is not None else "v1"
    fills = tuple(BacktestFillRecord.from_value(fill, version=version) for fill in report.fills)
    detail_count = (
        len(report.decisions)
        + len(report.signals)
        + len(report.outcomes)
        + len(report.daily_equity)
    )
    completed_at = report.daily_equity[-1].marked_at
    summary = _summary_for_report(report, completed_at=completed_at, run_input=run_input)
    if run_input is None:
        summary_created = store.record_run(
            summary,
            materialized=False,
            retention_at=datetime.now(UTC),
        )
        existing = store.get_run(report.run_id)
    else:
        summary_created = store.record_verified_run(
            summary,
            run_input=run_input,
            retention_at=datetime.now(completed_at.tzinfo),
        )
        existing = store.get_verified_run(report.run_id)
    if not summary_created and existing is not None:
        return ReportPersistenceResult(
            summary_created=False,
            fills_created=0,
            details_created=0,
        )
    fills_created = sum(
        store.record_fills(report.run_id, batch) for batch in _chunks(fills, _MAX_RESULT_BATCH)
    )
    details_created = sum(
        store.record_details(report.run_id, batch)
        for batch in _chunks(_detail_records(report, version=version), _MAX_RESULT_BATCH)
    )
    publication = store.verify_staged_publication(
        report.run_id,
        expected_fill_count=len(report.fills),
        expected_detail_count=detail_count,
        expected_report_hash=report.report_hash,
        expected_fill_set_hash=backtest_fill_set_hash(fills, version=version),
        expected_detail_set_hash=backtest_detail_set_hash(
            _detail_records(report, version=version),
            version=version,
        ),
    )
    store.publish_verified_publication(publication)
    return ReportPersistenceResult(
        summary_created=summary_created,
        fills_created=fills_created,
        details_created=details_created,
    )


def _summary_for_report(
    report: BacktestRunReport,
    *,
    completed_at: datetime,
    run_input: BacktestRunInput | None = None,
) -> BacktestRunSummary:
    detail_count = (
        len(report.decisions)
        + len(report.signals)
        + len(report.outcomes)
        + len(report.daily_equity)
    )
    assumptions = {
        "adjustmentPolicy": "NONE",
        "executionConfig": report.execution_config.model_dump(
            mode="python",
            round_trip=True,
        ),
        "executionConfigHash": report.execution_config.config_hash,
        "limitations": report.limitations,
        "manualEventRisk": report.manual_event_risk,
        "reportHash": report.report_hash,
    }
    return BacktestRunSummary(
        run_id=report.run_id,
        plan_sha256=report.plan_hash,
        dataset_hash=report.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=completed_at,
        event_start=report.start,
        event_end=report.end,
        symbols=(report.symbol,),
        coverage={
            "dailyEquityCount": len(report.daily_equity),
            "decisionCount": len(report.decisions),
            "detailCount": detail_count,
            "end": report.end,
            "fillCount": len(report.fills),
            "orderCount": len(report.orders),
            "outcomeCount": len(report.outcomes),
            "signalCount": len(report.signals),
            "start": report.start,
        },
        assumptions=assumptions,
        formula_versions={
            "execution": report.execution_config.formula_version,
            "indicator": "ta-v1",
            "runner": (RUN_FORMULA_VERSION if run_input is None else run_input.run_formula_version),
        },
        final_metrics=report.metrics.model_dump(mode="python", round_trip=True),
    )


def write_report_files(
    report: BacktestRunReport,
    *,
    json_path: str | Path,
    csv_path: str | Path,
) -> tuple[Path, Path]:
    """Atomically emit byte-stable JSON and a stable simulated-fill CSV ledger."""

    if not isinstance(report, BacktestRunReport):
        raise TypeError("report must be a BacktestRunReport")
    resolved_json = Path(json_path).expanduser().resolve()
    resolved_csv = Path(csv_path).expanduser().resolve()
    if resolved_json == resolved_csv:
        raise ValueError("json_path and csv_path must be different")
    summary = _summary_for_report(report, completed_at=datetime(1970, 1, 1, tzinfo=UTC))
    fills = tuple(BacktestFillRecord.from_value(fill) for fill in report.fills)
    return write_persisted_report_files(
        summary,
        fills,
        json_path=resolved_json,
        csv_path=resolved_csv,
    )


def iter_export_summary(
    store: BacktestResultStore,
    run_id: str,
    cancelled: Callable[[], bool],
) -> Iterator[bytes]:
    """Incrementally encode one verified active-v2 summary without a file buffer."""

    _require_export_inputs(store, cancelled)
    if cancelled():
        return
    summary = store.export_summary(run_id)
    report_hash = summary.assumptions.get("reportHash")
    if not isinstance(report_hash, str):
        raise ValueError("summary assumptions must include reportHash")
    payload = {
        "schemaVersion": "backtest-report-summary-v2",
        "runId": summary.run_id,
        "reportHash": report_hash,
        "status": summary.status.value,
        "planHash": summary.plan_sha256,
        "datasetHash": summary.dataset_hash,
        "completedAt": summary.completed_at,
        "eventStart": summary.event_start,
        "eventEnd": summary.event_end,
        "symbols": summary.symbols,
        "coverage": summary.coverage,
        "assumptions": summary.assumptions,
        "formulaVersions": summary.formula_versions,
        "finalMetrics": summary.final_metrics,
        "blockers": summary.blockers,
    }
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    for fragment in encoder.iterencode(payload):
        if cancelled():
            return
        yield _bounded_export_chunk(fragment)
    if cancelled():
        return
    yield b"\n"


def iter_export_fills(
    store: BacktestResultStore,
    run_id: str,
    cancelled: Callable[[], bool],
) -> Iterator[bytes]:
    """Incrementally encode verified active-v2 fill batches as stable CSV rows."""

    _require_export_inputs(store, cancelled)
    if cancelled():
        return
    store.export_summary(run_id)
    if cancelled():
        return
    yield _v2_csv_header()
    batches = store.iter_export_fill_batches(run_id, cancelled)
    try:
        while True:
            try:
                batch = next(batches)
            except ExportCancelled:
                return
            except StopIteration:
                return
            for fill in batch:
                if cancelled():
                    return
                yield _v2_fill_csv_row(fill)
    finally:
        batches.close()


def write_persisted_report_files(
    summary: BacktestRunSummary,
    fills: tuple[BacktestFillRecord, ...],
    *,
    json_path: str | Path,
    csv_path: str | Path,
) -> tuple[Path, Path]:
    """Compatibility alias for the explicitly offline immutable v1 exporter."""

    return write_offline_v1_compatibility_report_files(
        summary,
        fills,
        json_path=json_path,
        csv_path=csv_path,
    )


def write_offline_v1_compatibility_report_files(
    summary: BacktestRunSummary,
    fills: tuple[BacktestFillRecord, ...],
    *,
    json_path: str | Path,
    csv_path: str | Path,
) -> tuple[Path, Path]:
    """Rebuild immutable UTC-v1 files for explicitly offline compatibility only."""

    if not isinstance(summary, BacktestRunSummary):
        raise TypeError("summary must be a BacktestRunSummary")
    if type(fills) is not tuple or any(not isinstance(fill, BacktestFillRecord) for fill in fills):
        raise TypeError("fills must be a tuple of BacktestFillRecord values")
    if any(fill.run_id != summary.run_id for fill in fills):
        raise ValueError("every fill must belong to summary.run_id")
    expected_fill_count = summary.coverage.get("fillCount")
    if type(expected_fill_count) is not int or expected_fill_count < 0:
        raise ValueError("summary coverage must include a non-negative fillCount")
    if len(fills) != expected_fill_count:
        raise RuntimeError("stored fill ledger is incomplete")
    resolved_json = Path(json_path).expanduser().resolve()
    resolved_csv = Path(csv_path).expanduser().resolve()
    if resolved_json == resolved_csv:
        raise ValueError("json_path and csv_path must be different")
    csv_buffer = StringIO(newline="")
    fieldnames = (
        "run_id",
        "fill_id",
        "filled_at",
        "side",
        "symbol",
        "bucket",
        "quantity",
        "price_fen",
        "notional_fen",
        "fees_fen",
        "cash_delta_fen",
        "realized_pnl_fen",
    )
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for fill in sorted(fills, key=lambda item: (item.filled_at, item.fill_id)):
        payload = fill.payload
        fees = payload.get("fees")
        if not isinstance(fees, dict):
            raise ValueError("stored fill fees must be an object")
        writer.writerow(
            {
                "run_id": summary.run_id,
                "fill_id": fill.fill_id,
                "filled_at": fill.filled_at.isoformat(timespec="microseconds"),
                "side": payload["side"],
                "symbol": payload["symbol"],
                "bucket": payload["bucket"],
                "quantity": payload["quantity"],
                "price_fen": payload["price_fen"],
                "notional_fen": payload["notional_fen"],
                "fees_fen": fees["total_fen"],
                "cash_delta_fen": payload["cash_delta_fen"],
                "realized_pnl_fen": (
                    "" if payload.get("realized_pnl_fen") is None else payload["realized_pnl_fen"]
                ),
            }
        )
    report_hash = summary.assumptions.get("reportHash")
    if not isinstance(report_hash, str):
        raise ValueError("summary assumptions must include reportHash")
    json_payload = {
        "schemaVersion": "backtest-report-summary-v1",
        "runId": summary.run_id,
        "reportHash": report_hash,
        "status": summary.status.value,
        "planHash": summary.plan_sha256,
        "datasetHash": summary.dataset_hash,
        "eventStart": summary.event_start,
        "eventEnd": summary.event_end,
        "symbols": summary.symbols,
        "coverage": summary.coverage,
        "assumptions": summary.assumptions,
        "formulaVersions": summary.formula_versions,
        "finalMetrics": summary.final_metrics,
        "blockers": summary.blockers,
    }
    _atomic_write_if_changed(resolved_json, _stable_json(json_payload) + "\n")
    _atomic_write_if_changed(resolved_csv, csv_buffer.getvalue())
    return resolved_json, resolved_csv


def _require_export_inputs(
    store: BacktestResultStore,
    cancelled: Callable[[], bool],
) -> None:
    if not isinstance(store, BacktestResultStore):
        raise TypeError("store must be a BacktestResultStore")
    if not callable(cancelled):
        raise TypeError("cancelled must be callable")


def _bounded_export_chunk(content: str) -> bytes:
    encoded = content.encode("utf-8")
    if not encoded or len(encoded) > _MAX_EXPORT_CHUNK_BYTES:
        raise RuntimeError("export chunk must contain between 1 byte and 64 KiB")
    return encoded


def _v2_csv_header() -> bytes:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=_V2_FILL_FIELDS, lineterminator="\n")
    writer.writeheader()
    return _bounded_export_chunk(buffer.getvalue())


def _v2_fill_csv_row(fill: BacktestFillRecord) -> bytes:
    payload = fill.payload
    fees = payload.get("fees")
    if not isinstance(fees, dict):
        raise ValueError("stored fill fees must be an object")
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=_V2_FILL_FIELDS, lineterminator="\n")
    writer.writerow(
        {
            "schema_version": "backtest-simulated-fills-v2",
            "run_id": fill.run_id,
            "fill_id": fill.fill_id,
            "filled_at": fill.filled_at.isoformat(timespec="microseconds"),
            "side": payload["side"],
            "symbol": payload["symbol"],
            "bucket": payload["bucket"],
            "quantity": payload["quantity"],
            "price_fen": payload["price_fen"],
            "notional_fen": payload["notional_fen"],
            "fees_fen": fees["total_fen"],
            "cash_delta_fen": payload["cash_delta_fen"],
            "realized_pnl_fen": (
                "" if payload.get("realized_pnl_fen") is None else payload["realized_pnl_fen"]
            ),
        }
    )
    return _bounded_export_chunk(buffer.getvalue())


def _detail_records(
    report: BacktestRunReport,
    *,
    version: str = "v1",
) -> Iterator[BacktestDetailRecord]:
    for decision in report.decisions:
        yield BacktestDetailRecord.from_value(
            BacktestDetailKind.DECISION,
            decision,
            run_id=report.run_id,
            event_at=decision.snapshot.evaluated_at,
            detail_id=_scoped_detail_id(
                report.run_id,
                BacktestDetailKind.DECISION,
                f"{decision.result_hash}:{decision.snapshot.evaluated_at.isoformat()}",
            ),
            version=version,
        )
    for signal in report.signals:
        yield BacktestDetailRecord.from_value(
            BacktestDetailKind.SIGNAL,
            signal,
            detail_id=_scoped_detail_id(
                report.run_id,
                BacktestDetailKind.SIGNAL,
                signal.signal_id,
            ),
            version=version,
        )
    for outcome in report.outcomes:
        yield BacktestDetailRecord.from_value(
            BacktestDetailKind.EXECUTION_OUTCOME,
            outcome,
            run_id=report.run_id,
            event_at=outcome.resolved_at,
            detail_id=_scoped_detail_id(
                report.run_id,
                BacktestDetailKind.EXECUTION_OUTCOME,
                outcome.outcome_id,
            ),
            version=version,
        )
    for snapshot in report.daily_equity:
        yield BacktestDetailRecord.from_value(
            BacktestDetailKind.DAILY_EQUITY,
            snapshot,
            detail_id=_scoped_detail_id(
                report.run_id,
                BacktestDetailKind.DAILY_EQUITY,
                snapshot.snapshot_id,
            ),
            version=version,
        )


def _scoped_detail_id(run_id: str, kind: BacktestDetailKind, source_id: str) -> str:
    payload = f"{run_id}\0{kind.value}\0{source_id}".encode()
    return sha256(b"backtest-detail-identity-v1\0" + payload).hexdigest()


def _chunks[T](values: Iterable[T], size: int) -> Iterator[tuple[T, ...]]:
    iterator = iter(values)
    while batch := tuple(islice(iterator, size)):
        yield batch


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary_path = Path(stream.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _atomic_write_if_changed(path: Path, content: str) -> None:
    encoded = content.encode("utf-8")
    try:
        if path.read_bytes() == encoded:
            return
    except FileNotFoundError:
        pass
    _atomic_write(path, content)


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"unsupported stable JSON value: {type(value).__name__}")


__all__ = [
    "ReportPersistenceResult",
    "iter_export_fills",
    "iter_export_summary",
    "persist_report",
    "write_offline_v1_compatibility_report_files",
    "write_persisted_report_files",
    "write_report_files",
]
