"""One-way result retention participant with a caller-owned row budget."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest import reporting
from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.results import (
    BacktestArtifactAvailability,
    BacktestDetailKind,
    BacktestDetailRecord,
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunStatus,
    BacktestRunSummary,
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


def _summary(
    run_input: BacktestRunInput,
    label: str,
    *,
    completed_at: datetime,
    fill_count: int,
    detail_count: int,
) -> BacktestRunSummary:
    return BacktestRunSummary(
        run_id=run_input.run_id,
        plan_sha256=run_input.plan_sha256,
        dataset_hash=run_input.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=completed_at,
        event_start=run_input.start,
        event_end=run_input.end,
        symbols=(run_input.plan_snapshot.symbol,),
        coverage={
            "dailyEquityCount": 1 if detail_count else 0,
            "decisionCount": 1 if detail_count > 1 else 0,
            "detailCount": detail_count,
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
        final_metrics={"totalReturn": "0"},
    )


def _fill(run_id: str, label: str) -> BacktestFillRecord:
    return BacktestFillRecord.from_value(
        {
            "fill_id": _hash(f"fill:{label}"),
            "run_id": run_id,
            "filled_at": datetime(2026, 8, 24, 10, tzinfo=_SHANGHAI),
            "side": "BUY",
            "symbol": "003043.SZ",
            "bucket": "TACTICAL",
            "quantity": 100,
            "price_fen": 1_000,
            "notional_fen": 100_000,
            "fees": {"total_fen": 500},
            "cash_delta_fen": -100_500,
            "realized_pnl_fen": None,
        },
        version="v2",
    )


def _detail(run_id: str, kind: BacktestDetailKind, label: str) -> BacktestDetailRecord:
    return BacktestDetailRecord(
        detail_id=_hash(f"detail:{label}"),
        run_id=run_id,
        kind=kind,
        event_at=datetime(2026, 8, 24, 14, tzinfo=_SHANGHAI),
        payload={"identity": label},
    )


def _materialize_old_v2(
    store: BacktestResultStore,
    label: str,
    *,
    as_of: datetime,
) -> tuple[BacktestRunSummary, BacktestFillRecord, tuple[BacktestDetailRecord, ...]]:
    run_input = _run_input(label)
    fill = _fill(run_input.run_id, label)
    details = (
        _detail(run_input.run_id, BacktestDetailKind.DECISION, f"{label}:decision"),
        _detail(run_input.run_id, BacktestDetailKind.DAILY_EQUITY, f"{label}:equity"),
    )
    summary = _summary(
        run_input,
        label,
        completed_at=as_of - timedelta(days=91),
        fill_count=1,
        detail_count=2,
    )
    assert store.record_verified_run(
        summary,
        run_input=run_input,
        retention_at=as_of - timedelta(days=91),
    )
    assert store.record_fills(summary.run_id, (fill,)) == 1
    assert store.record_details(summary.run_id, details) == 2
    report_hash = summary.assumptions["reportHash"]
    assert isinstance(report_hash, str)
    assert store.mark_run_materialized(
        summary.run_id,
        expected_fill_count=1,
        expected_detail_count=2,
        expected_report_hash=report_hash,
        expected_fill_set_hash=backtest_fill_set_hash((fill,), version="v2"),
        expected_detail_set_hash=backtest_detail_set_hash(details, version="v2"),
    )
    return summary, fill, details


def test_result_cleanup_consumes_only_caller_budget_and_never_vacuums(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = BacktestResultStore(tmp_path / "results.sqlite3")
    as_of = datetime(2026, 8, 27, 12, tzinfo=_SHANGHAI)
    summary, fill, _details = _materialize_old_v2(store, "bounded", as_of=as_of)
    statements: list[str] = []
    original_connect = store._connect

    def traced_connect():
        manager = original_connect()

        class _TracedConnection:
            def __enter__(self):
                connection = manager.__enter__()
                connection.set_trace_callback(statements.append)
                return connection

            def __exit__(self, *args):
                return manager.__exit__(*args)

        return _TracedConnection()

    monkeypatch.setattr(store, "_connect", traced_connect)

    first = store.prune_result_rows(as_of=as_of, remaining_budget=1)
    second = store.prune_result_rows(as_of=as_of, remaining_budget=1)

    assert first.deleted_count == second.deleted_count == 1
    assert store.get_verified_run(summary.run_id) is not None
    assert store.list_fills(summary.run_id) == (fill,)
    assert store.list_details(summary.run_id) == ()
    assert all("VACUUM" not in statement.upper() for statement in statements)


def test_expired_detail_and_equity_cannot_be_reconstructed_by_export_recovery(
    tmp_path: Path,
) -> None:
    store = BacktestResultStore(tmp_path / "results.sqlite3")
    as_of = datetime(2026, 8, 27, 12, tzinfo=_SHANGHAI)
    summary, fill, details = _materialize_old_v2(store, "expiry", as_of=as_of)
    before = store.statistics()

    result = store.prune_result_rows(as_of=as_of, remaining_budget=2)
    assert result.deleted_count == 2
    assert (
        store.artifact_state(summary.run_id, BacktestDetailKind.DECISION).availability
        is BacktestArtifactAvailability.EXPIRED
    )
    assert (
        store.artifact_state(summary.run_id, BacktestDetailKind.DAILY_EQUITY).availability
        is BacktestArtifactAvailability.EXPIRED
    )

    summary_bytes = b"".join(
        reporting.iter_export_summary(store, summary.run_id, cancelled=lambda: False)
    )
    fill_bytes = b"".join(
        reporting.iter_export_fills(store, summary.run_id, cancelled=lambda: False)
    )

    assert b"backtest-report-summary-v2" in summary_bytes
    assert b"backtest-simulated-fills-v2" in fill_bytes
    assert store.statistics().run_count == before.run_count
    assert store.statistics().fill_count == before.fill_count
    assert store.statistics().detail_count == before.detail_count - 2
    assert store.list_details(summary.run_id) == ()
    with pytest.raises(ValueError, match="cannot append details"):
        store.record_details(summary.run_id, details)
    assert store.list_fills(summary.run_id) == (fill,)


def test_zero_remaining_budget_performs_no_result_cleanup(tmp_path: Path) -> None:
    store = BacktestResultStore(tmp_path / "results.sqlite3")
    as_of = datetime(2026, 8, 27, 12, tzinfo=_SHANGHAI)
    summary, fill, details = _materialize_old_v2(store, "zero-budget", as_of=as_of)

    result = store.prune_result_rows(as_of=as_of, remaining_budget=0)

    assert result.deleted_count == 0
    assert result.has_more is True
    assert store.get_verified_run(summary.run_id) is not None
    assert store.list_fills(summary.run_id) == (fill,)
    assert {item.detail_id for item in store.list_details(summary.run_id)} == {
        item.detail_id for item in details
    }

    empty_store = BacktestResultStore(tmp_path / "empty-results.sqlite3")
    assert (
        empty_store.prune_result_rows(
            as_of=as_of,
            remaining_budget=0,
        ).has_more
        is False
    )
