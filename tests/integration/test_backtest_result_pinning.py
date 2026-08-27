"""Revision-checked application-owned pin idempotency."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.pagination import HmacCursorSigner
from trade_plan_monitor.backtest.result_service import (
    BacktestResultNotFoundError,
    BacktestResultService,
)
from trade_plan_monitor.backtest.results import (
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


def _materialized_run(store: BacktestResultStore, label: str) -> BacktestRunSummary:
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
    run_input = BacktestRunInput.create(
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
    summary = BacktestRunSummary(
        run_id=run_input.run_id,
        plan_sha256=run_input.plan_sha256,
        dataset_hash=run_input.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=datetime(2026, 8, 24, 15, 30, tzinfo=_SHANGHAI),
        event_start=run_input.start,
        event_end=run_input.end,
        symbols=(plan.symbol,),
        coverage={
            "decisionCount": 0,
            "signalCount": 0,
            "outcomeCount": 0,
            "dailyEquityCount": 0,
            "detailCount": 0,
            "fillCount": 0,
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
    assert store.record_verified_run(summary, run_input=run_input)
    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    assert store.mark_run_materialized(
        summary.run_id,
        expected_fill_count=0,
        expected_detail_count=0,
        expected_report_hash=report_hash,
        expected_fill_set_hash=backtest_fill_set_hash((), version="v2"),
        expected_detail_set_hash=backtest_detail_set_hash((), version="v2"),
    )
    return summary


def _service(
    store: BacktestResultStore,
    now: list[datetime],
) -> BacktestResultService:
    return BacktestResultService(
        store=store,
        cursor_signer=HmacCursorSigner(b"p" * 32),
        clock=lambda: now[0],
    )


def test_pin_requires_revision_and_replays_the_exact_original_response(tmp_path: Path) -> None:
    store = BacktestResultStore(tmp_path / "pin.sqlite3")
    summary = _materialized_run(store, "pin")
    now = [datetime(2026, 8, 27, 10, tzinfo=_SHANGHAI)]
    service = _service(store, now)

    pinned = service.set_pinned(
        summary.run_id,
        pinned=True,
        expected_revision=0,
        idempotency_key="pin-intent-1",
    )
    assert pinned.summary.pinned is True
    assert pinned.revision == 1
    unpinned = service.set_pinned(
        summary.run_id,
        pinned=False,
        expected_revision=1,
        idempotency_key="pin-intent-2",
    )
    replay = service.set_pinned(
        summary.run_id,
        pinned=True,
        expected_revision=0,
        idempotency_key="pin-intent-1",
    )

    assert unpinned.summary.pinned is False and unpinned.revision == 2
    assert replay == pinned
    assert replay.summary.pinned is True and replay.revision == 1
    assert service.get_run(summary.run_id).summary.pinned is False
    assert summary.assumptions["reportHash"] == replay.summary.assumptions["reportHash"]


def test_pin_conflicts_write_nothing_and_do_not_change_report_identity(tmp_path: Path) -> None:
    store = BacktestResultStore(tmp_path / "conflict.sqlite3")
    summary = _materialized_run(store, "conflict")
    now = [datetime(2026, 8, 27, 11, tzinfo=_SHANGHAI)]
    service = _service(store, now)

    initial = service.get_run(summary.run_id)
    with pytest.raises(ResultConflictError, match="pin revision"):
        service.set_pinned(
            summary.run_id,
            pinned=True,
            expected_revision=1,
            idempotency_key="stale-revision",
        )
    assert service.get_run(summary.run_id) == initial

    service.set_pinned(
        summary.run_id,
        pinned=True,
        expected_revision=0,
        idempotency_key="reused-key",
    )
    before_conflict = service.get_run(summary.run_id)
    with pytest.raises(ResultConflictError, match="idempotency key"):
        service.set_pinned(
            summary.run_id,
            pinned=False,
            expected_revision=1,
            idempotency_key="reused-key",
        )
    assert service.get_run(summary.run_id) == before_conflict
    assert before_conflict.summary.assumptions["reportHash"] == summary.assumptions["reportHash"]


def test_pin_key_expires_after_the_canonical_fourteen_day_window(tmp_path: Path) -> None:
    store = BacktestResultStore(tmp_path / "expiry.sqlite3")
    summary = _materialized_run(store, "expiry")
    now = [datetime(2026, 8, 1, 9, tzinfo=_SHANGHAI)]
    service = _service(store, now)

    first = service.set_pinned(
        summary.run_id,
        pinned=True,
        expected_revision=0,
        idempotency_key="recyclable-key",
    )
    now[0] += timedelta(days=14)
    second = service.set_pinned(
        summary.run_id,
        pinned=False,
        expected_revision=1,
        idempotency_key="fresh-key",
    )

    assert first.revision == 1
    assert second.summary.pinned is False and second.revision == 2
    with sqlite3.connect(store.database_path) as connection:
        stored = str(
            connection.execute(
                "SELECT pin_idempotency_json FROM backtest_run WHERE run_id = ?",
                (summary.run_id,),
            ).fetchone()[0]
        )
    assert "recyclable-key" not in stored


@pytest.mark.parametrize("key", ["", "-bad", "k" * 129])
def test_pin_key_is_strict_and_unknown_runs_are_sanitized(tmp_path: Path, key: str) -> None:
    store = BacktestResultStore(tmp_path / "validation.sqlite3")
    summary = _materialized_run(store, "validation")
    now = [datetime(2026, 8, 27, 12, tzinfo=_SHANGHAI)]
    service = _service(store, now)

    with pytest.raises(ValueError, match="idempotency_key"):
        service.set_pinned(
            summary.run_id,
            pinned=True,
            expected_revision=0,
            idempotency_key=key,
        )
    with pytest.raises(BacktestResultNotFoundError, match="^backtest result not found$"):
        service.get_run("0" * 64)
