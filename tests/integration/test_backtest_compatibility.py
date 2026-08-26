"""Literal compatibility goldens for immutable local backtest v1 artifacts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import get_type_hints
from uuid import UUID

import pytest

from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.reporting import write_persisted_report_files
from trade_plan_monitor.backtest.results import (
    BacktestFillRecord,
    BacktestRunStatus,
    BacktestRunSummary,
)
from trade_plan_monitor.backtest.runner import (
    BacktestMetrics,
    BacktestRunReport,
    OfflineBacktestRunner,
    backtest_run_id,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile

_FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "backtest"
_PLAN_PATH = Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
_PLAN_VERSION_IDS = (
    UUID("4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"),
    UUID("f9586c94-e03f-4807-b2d8-1023843f110f"),
)


def _load_identity_goldens() -> dict[str, object]:
    return json.loads((_FIXTURE_DIRECTORY / "v1_identity_goldens.json").read_text(encoding="utf-8"))


def _plan():
    return load_plan_yaml(_PLAN_PATH.read_text(encoding="utf-8"))


def _manifest(case: dict[str, object]) -> DatasetManifest:
    start = date.fromisoformat(str(case["start"]))
    return DatasetManifest(
        dataset_hash=case["dataset_hash"],
        scope=DatasetScope(
            symbols=("003043.SZ",),
            start=start,
            end=date.fromisoformat(str(case["end"])),
            warmup_start=start.replace(year=start.year - 1),
            historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        ),
        items=(),
    )


def _execution_config(case: dict[str, object]) -> ExecutionConfig:
    values = dict(case["execution_config"])
    for field in (
        "commission_rate",
        "stamp_duty_rate",
        "transfer_fee_rate",
        "buy_slippage_bps",
        "sell_slippage_bps",
    ):
        values[field] = Decimal(values[field])
    return ExecutionConfig.model_validate(values)


def _empty_report(
    case: dict[str, object],
    *,
    run_id: str,
    plan_hash: str,
) -> BacktestRunReport:
    initial_cash_fen = int(case["initial_cash_fen"])
    metrics = BacktestMetrics(
        initial_cash_fen=initial_cash_fen,
        initial_equity_fen=initial_cash_fen,
        final_cash_fen=initial_cash_fen,
        final_equity_fen=initial_cash_fen,
        total_return=Decimal("0"),
        maximum_drawdown=Decimal("0"),
        trade_count=0,
        winning_sell_count=0,
        win_rate=Decimal("0"),
        turnover_fen=0,
        total_cost_fen=0,
        realized_pnl_fen=0,
        unrealized_pnl_fen=0,
        blocked_count=0,
        skipped_count=0,
    )
    return BacktestRunReport.build(
        run_id=run_id,
        plan_hash=plan_hash,
        dataset_hash=case["dataset_hash"],
        symbol="003043.SZ",
        start=date.fromisoformat(str(case["start"])),
        end=date.fromisoformat(str(case["end"])),
        manual_event_risk=case["manual_event_risk"],
        execution_config=_execution_config(case),
        decisions=(),
        signals=(),
        orders=(),
        fills=(),
        outcomes=(),
        daily_equity=(),
        final_positions=(),
        metrics=metrics,
    )


def test_v1_run_and_report_identities_match_literal_goldens() -> None:
    goldens = _load_identity_goldens()
    plan = _plan()
    plan_hash = plan_sha256(plan)

    assert plan_hash == goldens["plan_sha256"]
    assert len(goldens["cases"]) >= 3
    for case in goldens["cases"]:
        manifest = _manifest(case)
        arguments = {
            "plan": plan,
            "manifest": manifest,
            "initial_cash_fen": case["initial_cash_fen"],
            "execution_config": _execution_config(case),
            "manual_event_risk": case["manual_event_risk"],
        }
        run_ids = {
            backtest_run_id(**arguments, plan_version_id=None),
            *(backtest_run_id(**arguments, plan_version_id=value) for value in _PLAN_VERSION_IDS),
        }

        assert run_ids == {case["run_id"]}, case["label"]
        report = _empty_report(case, run_id=case["run_id"], plan_hash=plan_hash)
        assert report.report_hash == case["report_hash"], case["label"]


def test_nullable_plan_version_lookup_metadata_is_explicit_and_strict() -> None:
    expected = UUID | None

    assert get_type_hints(backtest_run_id)["plan_version_id"] == expected
    assert get_type_hints(OfflineBacktestRunner.run)["plan_version_id"] == expected

    case = _load_identity_goldens()["cases"][0]
    with pytest.raises(TypeError, match="plan_version_id must be a UUID or None"):
        backtest_run_id(
            plan=_plan(),
            manifest=_manifest(case),
            initial_cash_fen=case["initial_cash_fen"],
            execution_config=_execution_config(case),
            manual_event_risk=case["manual_event_risk"],
            plan_version_id="4c623c8c-ca26-4cd8-8cb2-08cd5e61be93",
        )


def test_utc_v1_summary_json_and_fill_csv_match_exact_fixture_bytes(tmp_path: Path) -> None:
    goldens = _load_identity_goldens()
    case = goldens["cases"][0]
    report = _empty_report(
        case,
        run_id=case["run_id"],
        plan_hash=goldens["plan_sha256"],
    )
    summary = BacktestRunSummary(
        run_id=report.run_id,
        plan_sha256=report.plan_hash,
        dataset_hash=report.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=datetime(2026, 8, 24, 7, 20, tzinfo=UTC),
        event_start=report.start,
        event_end=report.end,
        symbols=(report.symbol,),
        coverage={
            "dailyEquityCount": 1,
            "decisionCount": 49,
            "detailCount": 50,
            "end": report.end,
            "fillCount": 1,
            "orderCount": 1,
            "outcomeCount": 1,
            "signalCount": 1,
            "start": report.start,
        },
        assumptions={
            "adjustmentPolicy": "NONE",
            "executionConfig": report.execution_config.model_dump(
                mode="python",
                round_trip=True,
            ),
            "executionConfigHash": report.execution_config.config_hash,
            "limitations": report.limitations,
            "manualEventRisk": report.manual_event_risk,
            "reportHash": report.report_hash,
        },
        formula_versions={
            "execution": report.execution_config.formula_version,
            "indicator": "ta-v1",
            "runner": "backtest-run-v1",
        },
        final_metrics=report.metrics.model_dump(mode="python", round_trip=True),
    )
    fill = BacktestFillRecord.from_value(
        {
            "fill_id": "legacy-fill-001",
            "run_id": report.run_id,
            "filled_at": datetime(2026, 8, 24, 1, 36, tzinfo=UTC),
            "side": "BUY",
            "symbol": report.symbol,
            "bucket": "TACTICAL",
            "quantity": 100,
            "price_fen": 6_401,
            "notional_fen": 640_100,
            "fees": {"total_fen": 507},
            "cash_delta_fen": -640_607,
            "realized_pnl_fen": None,
        }
    )
    json_path = tmp_path / "summary.json"
    csv_path = tmp_path / "fills.csv"

    write_persisted_report_files(
        summary,
        (fill,),
        json_path=json_path,
        csv_path=csv_path,
    )

    assert json_path.read_bytes() == (_FIXTURE_DIRECTORY / "v1_result_summary.json").read_bytes()
    assert csv_path.read_bytes() == (_FIXTURE_DIRECTORY / "v1_fills.csv").read_bytes()
    assert b"2026-08-24T01:36:00.000000+00:00" in csv_path.read_bytes()
