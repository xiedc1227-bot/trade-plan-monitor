from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.models import ExecutionConfig
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
    start = date(2026, 8, 20)
    manifest = DatasetManifest(
        dataset_hash=_hash(f"dataset:{label}"),
        scope=DatasetScope(
            symbols=(plan.symbol,),
            start=start,
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


def _summary(run_input: BacktestRunInput, label: str) -> BacktestRunSummary:
    return BacktestRunSummary(
        run_id=run_input.run_id,
        plan_sha256=run_input.plan_sha256,
        dataset_hash=run_input.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=datetime(2026, 8, 24, 15, 30, tzinfo=_SHANGHAI),
        event_start=run_input.start,
        event_end=run_input.end,
        symbols=(run_input.plan_snapshot.symbol,),
        coverage={"detailCount": 0, "fillCount": 0},
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


def _fill(summary: BacktestRunSummary, index: int) -> BacktestFillRecord:
    return BacktestFillRecord.from_value(
        {
            "fill_id": _hash(f"{summary.run_id}:fill:{index:04d}"),
            "run_id": summary.run_id,
            "filled_at": datetime(2026, 8, 24, 14, index % 60, tzinfo=_SHANGHAI),
            "symbol": summary.symbols[0],
            "quantity": 100,
            "price_fen": 1_000 + index,
            "fees": {"commission_fen": 500},
        },
        version="v2",
    )


def _detail(
    summary: BacktestRunSummary,
    index: int,
    *,
    payload: dict[str, object] | None = None,
) -> BacktestDetailRecord:
    return BacktestDetailRecord(
        detail_id=_hash(f"{summary.run_id}:detail:{index:04d}"),
        run_id=summary.run_id,
        kind=BacktestDetailKind.DECISION,
        event_at=datetime(2026, 8, 24, 13, index % 60, tzinfo=_SHANGHAI),
        payload=payload or {"identity": f"detail-{index:04d}"},
    )


def _stage(
    store: BacktestResultStore,
    label: str,
) -> tuple[BacktestRunInput, BacktestRunSummary]:
    run_input = _run_input(label)
    summary = _summary(run_input, label)
    assert store.record_verified_run(summary, run_input=run_input) is True
    return run_input, summary


def _publication_arguments(
    summary: BacktestRunSummary,
    fills: tuple[BacktestFillRecord, ...],
    details: tuple[BacktestDetailRecord, ...],
) -> dict[str, object]:
    return {
        "run_id": summary.run_id,
        "expected_fill_count": len(fills),
        "expected_detail_count": len(details),
        "expected_report_hash": summary.assumptions["reportHash"],
        "expected_fill_set_hash": backtest_fill_set_hash(fills, version="v2"),
        "expected_detail_set_hash": backtest_detail_set_hash(details, version="v2"),
    }


def _stage_revision(path: Path, run_id: str) -> int:
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT stage_revision FROM backtest_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_stage_revision_tracks_each_row_mutation_and_ordinary_reads_hide_stage(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "publication.sqlite3")
    _run, summary = _stage(store, "revision")
    fills = (_fill(summary, 0), _fill(summary, 1))
    detail = _detail(summary, 0)

    assert _stage_revision(store.database_path, summary.run_id) == 1
    assert store.record_fills(summary.run_id, fills) == 2
    assert _stage_revision(store.database_path, summary.run_id) == 3
    assert store.record_fills(summary.run_id, fills) == 0
    assert _stage_revision(store.database_path, summary.run_id) == 3
    assert store.record_details(summary.run_id, (detail,)) == 1
    assert _stage_revision(store.database_path, summary.run_id) == 4
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute(
            "UPDATE backtest_detail SET event_at = event_at WHERE detail_id = ?",
            (detail.detail_id,),
        )
        connection.execute("DELETE FROM backtest_fill WHERE fill_id = ?", (fills[0].fill_id,))
        connection.commit()
    assert _stage_revision(store.database_path, summary.run_id) == 6

    assert store.get_run(summary.run_id) is None
    assert store.get_verified_run(summary.run_id) is None
    assert store.list_runs() == ()
    assert store.list_fills(summary.run_id) == ()
    assert store.list_details(summary.run_id) == ()
    assert store.statistics().model_dump() == {
        "run_count": 0,
        "fill_count": 0,
        "detail_count": 0,
    }


def test_2001_rows_use_bounded_snapshot_then_uncommitted_short_participant(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "bounded-publication.sqlite3")
    _run, summary = _stage(store, "bounded")
    fills = tuple(_fill(summary, index) for index in range(1_001))
    details = tuple(_detail(summary, index) for index in range(1_000))
    assert store.record_fills(summary.run_id, fills[:1_000]) == 1_000
    assert store.record_fills(summary.run_id, fills[1_000:]) == 1
    assert store.record_details(summary.run_id, details) == 1_000

    proof = store.verify_staged_publication(**_publication_arguments(summary, fills, details))
    assert proof.stage_revision == 2_002
    assert proof.fill_count == 1_001
    assert proof.detail_count == 1_000
    assert proof.read_batch_count == 3
    assert proof.max_read_batch_size == 1_000

    with closing(sqlite3.connect(store.database_path, isolation_level=None)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="not issued"):
            store.materialize_verified_publication(
                connection,
                replace(proof, fill_count=0),
            )
        connection.rollback()

    with closing(sqlite3.connect(store.database_path, isolation_level=None)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        assert store.materialize_verified_publication(connection, proof) is True
        assert connection.in_transaction is True
        connection.rollback()
    assert store.get_run(summary.run_id) is None

    with closing(sqlite3.connect(store.database_path, isolation_level=None)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        assert store.materialize_verified_publication(connection, proof) is True
        assert connection.in_transaction is True
        connection.commit()
    assert store.get_verified_run(summary.run_id) == summary


def test_publication_revision_fence_rejects_a_post_snapshot_stage_mutation(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "revision-fence.sqlite3")
    _run, summary = _stage(store, "fence")
    fills = (_fill(summary, 0),)
    assert store.record_fills(summary.run_id, fills) == 1
    proof = store.verify_staged_publication(**_publication_arguments(summary, fills, ()))

    assert store.record_details(summary.run_id, (_detail(summary, 0),)) == 1
    with closing(sqlite3.connect(store.database_path, isolation_level=None)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(ResultConflictError, match="stage revision"):
            store.materialize_verified_publication(connection, proof)
        assert connection.in_transaction is True
        connection.rollback()
    assert store.get_run(summary.run_id) is None


@pytest.mark.parametrize("surface", ["run", "input", "plan"])
def test_short_participant_fails_closed_on_post_snapshot_run_input_or_plan_mismatch(
    tmp_path: Path,
    surface: str,
) -> None:
    store = BacktestResultStore(tmp_path / f"{surface}-mismatch.sqlite3")
    _run, summary = _stage(store, surface)
    proof = store.verify_staged_publication(**_publication_arguments(summary, (), ()))
    with closing(sqlite3.connect(store.database_path)) as connection:
        if surface == "run":
            connection.execute(
                "UPDATE backtest_run SET dataset_hash = ? WHERE run_id = ?",
                ("f" * 64, summary.run_id),
            )
        elif surface == "input":
            connection.execute(
                "UPDATE backtest_run_input SET input_hash = ? WHERE run_id = ?",
                ("f" * 64, summary.run_id),
            )
        else:
            connection.execute(
                "UPDATE backtest_plan_snapshot SET snapshot_json = '{}' WHERE plan_sha256 = ?",
                (summary.plan_sha256,),
            )
        connection.commit()

    with closing(sqlite3.connect(store.database_path, isolation_level=None)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(ResultConflictError, match="changed"):
            store.materialize_verified_publication(connection, proof)
        connection.rollback()
    assert store.get_run(summary.run_id) is None


def test_publication_rejects_count_hash_and_oversized_item_without_truncation(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "closed-publication.sqlite3")
    _run, summary = _stage(store, "closed")
    detail = _detail(summary, 0)
    assert store.record_details(summary.run_id, (detail,)) == 1
    arguments = _publication_arguments(summary, (), (detail,))

    with pytest.raises(RuntimeError, match="incomplete"):
        store.verify_staged_publication(**{**arguments, "expected_detail_count": 2})
    with pytest.raises(ResultConflictError, match="detail"):
        store.verify_staged_publication(**{**arguments, "expected_detail_set_hash": "f" * 64})

    oversized = _detail(summary, 1, payload={"blob": "界" * 11_000})
    payload = oversized.model_dump(mode="python", round_trip=True)
    payload["kind"] = oversized.kind.value
    payload["event_at"] = oversized.event_at.isoformat(timespec="microseconds")
    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert len(payload_json.encode("utf-8")) > 32 * 1_024
    content_hash = sha256(b"backtest-detail-record-v2\0" + payload_json.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO backtest_detail (
                detail_id, run_id, kind, event_at, content_domain,
                content_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oversized.detail_id,
                oversized.run_id,
                oversized.kind.value,
                oversized.event_at.isoformat(timespec="microseconds"),
                "backtest-detail-record-v2",
                content_hash,
                payload_json,
                "2026-08-24T15:30:00.000000+08:00",
            ),
        )
        connection.commit()

    oversized_arguments = _publication_arguments(summary, (), (detail, oversized))
    with pytest.raises(ResultConflictError, match="32 KiB"):
        store.verify_staged_publication(**oversized_arguments)
    with closing(sqlite3.connect(store.database_path)) as connection:
        stored = connection.execute(
            "SELECT payload_json FROM backtest_detail WHERE detail_id = ?",
            (oversized.detail_id,),
        ).fetchone()
    assert stored == (payload_json,)
    assert store.get_run(summary.run_id) is None
