"""Versioned backtest run-input identity and initial-lot contracts."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import get_type_hints
from uuid import UUID

import pytest
from pydantic import ValidationError

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.models import ExecutionConfig, PositionLot
from trade_plan_monitor.backtest.run_input import (
    RUN_FORMULA_V1,
    RUN_FORMULA_V2,
    BacktestInitialLotInput,
    BacktestRunInput,
)
from trade_plan_monitor.backtest.runner import OfflineBacktestRunner, backtest_run_id
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import PositionPolicy
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile

_FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "backtest"
_PLAN_PATH = Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _goldens() -> dict[str, object]:
    return json.loads((_FIXTURE_DIRECTORY / "v1_identity_goldens.json").read_text("utf-8"))


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


def _config(case: dict[str, object]) -> ExecutionConfig:
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


def _lot(
    lot_key: str,
    *,
    bucket: str = "TACTICAL",
    acquired: date = date(2026, 8, 19),
    quantity: int = 100,
    cost_basis_fen: int = 100_000,
) -> BacktestInitialLotInput:
    return BacktestInitialLotInput(
        lot_key=lot_key,
        bucket=bucket,
        acquired_trade_date=acquired,
        quantity=quantity,
        cost_basis_fen=cost_basis_fen,
    )


def _run_input(
    *,
    plan=None,
    initial_lots: tuple[BacktestInitialLotInput, ...] = (),
    plan_version_id: UUID | None = None,
    initial_cash_fen: int = 1_000_000,
) -> BacktestRunInput:
    case = _goldens()["cases"][0]
    return BacktestRunInput.create(
        plan=plan or _plan(),
        manifest=_manifest(case),
        initial_cash_fen=initial_cash_fen,
        initial_lots=initial_lots,
        execution_config=_config(case),
        manual_event_risk=False,
        plan_version_id=plan_version_id,
    )


def test_empty_initial_lots_preserve_every_literal_v1_run_id() -> None:
    goldens = _goldens()
    plan = _plan()

    for case in goldens["cases"]:
        run_input = BacktestRunInput.create(
            plan=plan,
            manifest=_manifest(case),
            initial_cash_fen=case["initial_cash_fen"],
            initial_lots=(),
            execution_config=_config(case),
            manual_event_risk=case["manual_event_risk"],
            plan_version_id=UUID("4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"),
        )

        assert run_input.schema_version == "backtest-run-input-v1"
        assert run_input.run_formula_version == RUN_FORMULA_V1
        assert run_input.plan_sha256 == goldens["plan_sha256"]
        assert run_input.run_id == case["run_id"], case["label"]
        assert run_input.derive_position_lots() == ()


def test_nonempty_lots_normalize_select_v2_and_derive_only_after_hash() -> None:
    plan = _plan().model_copy(
        update={
            "position": PositionPolicy(
                max_qty=300,
                core_target_qty=100,
                tactical_target_qty=200,
            )
        }
    )
    inputs = (
        _lot("tactical-b"),
        _lot("core-a", bucket="CORE"),
        _lot("tactical-a"),
    )
    first = _run_input(
        plan=plan,
        initial_lots=inputs,
        plan_version_id=UUID("4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"),
    )
    second = _run_input(
        plan=plan,
        initial_lots=tuple(reversed(inputs)),
        plan_version_id=UUID("f9586c94-e03f-4807-b2d8-1023843f110f"),
    )

    assert first.run_formula_version == RUN_FORMULA_V2
    assert tuple(item.lot_key for item in first.initial_lots) == (
        "core-a",
        "tactical-a",
        "tactical-b",
    )
    assert first.run_id == second.run_id
    expected_preimage = {
        "formula_version": RUN_FORMULA_V2,
        "plan_hash": plan_sha256(plan),
        "plan_version": plan.version,
        "dataset_hash": first.dataset_hash,
        "start": first.start.isoformat(),
        "end": first.end.isoformat(),
        "initial_cash_fen": first.initial_cash_fen,
        "initial_lots": [
            item.model_dump(mode="python", round_trip=True) for item in first.initial_lots
        ],
        "indicator_formula_version": plan.monitoring.indicator_formula_version,
        "context_bounds": {
            "calendar_days": 512,
            "daily_bars_before_current": 499,
            "five_minute_bars": 512,
        },
        "execution_config_hash": first.execution_config.config_hash,
        "execution_config": first.execution_config.model_dump(mode="python", round_trip=True),
        "manual_event_risk": False,
    }
    expected_run_id = sha256(
        (RUN_FORMULA_V2 + "\0" + canonical_json(expected_preimage)).encode("utf-8")
    ).hexdigest()
    assert first.run_id == expected_run_id

    positions = first.derive_position_lots()
    assert len({position.lot_id for position in positions}) == 3
    assert positions == tuple(
        PositionLot.from_initial_input(
            run_id=first.run_id,
            symbol=plan.symbol,
            lot_key=item.lot_key,
            bucket=item.bucket,
            acquired_trade_date=item.acquired_trade_date,
            quantity=item.quantity,
            cost_basis_fen=item.cost_basis_fen,
        )
        for item in first.initial_lots
    )
    assert "lot_id" not in BacktestInitialLotInput.model_fields
    assert "run_id" not in BacktestInitialLotInput.model_fields


def test_runner_interfaces_accept_inputs_not_run_bound_position_lots() -> None:
    expected = tuple[BacktestInitialLotInput, ...]

    assert get_type_hints(backtest_run_id)["initial_lots"] == expected
    assert get_type_hints(OfflineBacktestRunner.run)["initial_lots"] == expected

    case = _goldens()["cases"][0]
    position = PositionLot.create_initial(
        run_id="1" * 64,
        symbol="003043.SZ",
        bucket="TACTICAL",
        acquired_trade_date=date(2026, 8, 19),
        quantity=100,
        cost_basis_fen=100_000,
        source_key="legacy-cycle",
    )
    with pytest.raises(TypeError, match="BacktestInitialLotInput"):
        backtest_run_id(
            plan=_plan(),
            manifest=_manifest(case),
            initial_cash_fen=case["initial_cash_fen"],
            execution_config=_config(case),
            manual_event_risk=case["manual_event_risk"],
            initial_lots=(position,),
        )


@pytest.mark.parametrize(
    "update",
    (
        {"lot_key": ""},
        {"lot_key": "-leading"},
        {"lot_key": "contains space"},
        {"lot_key": "a" * 65},
        {"bucket": "OTHER"},
        {"acquired_trade_date": "2026-08-19"},
        {"quantity": 0},
        {"quantity": 101},
        {"quantity": True},
        {"cost_basis_fen": 0},
        {"cost_basis_fen": _MAX_SAFE_INTEGER + 1},
        {"unexpected": "value"},
    ),
)
def test_initial_lot_input_is_strict_closed_and_bounded(update: dict[str, object]) -> None:
    values: dict[str, object] = {
        "lot_key": "lot-1",
        "bucket": "CORE",
        "acquired_trade_date": date(2026, 8, 19),
        "quantity": 100,
        "cost_basis_fen": 100_000,
    }
    values.update(update)

    with pytest.raises(ValidationError):
        BacktestInitialLotInput.model_validate(values)


@pytest.mark.parametrize(
    ("initial_lots", "initial_cash_fen", "message"),
    (
        ((_lot("duplicate"), _lot("duplicate", bucket="CORE")), 1_000_000, "unique"),
        ((_lot("future", acquired=date(2026, 8, 21)),), 1_000_000, "dataset start"),
        ((_lot("core-1", bucket="CORE"), _lot("core-2", bucket="CORE")), 1_000_000, "CORE"),
        ((_lot("too-expensive", cost_basis_fen=_MAX_SAFE_INTEGER),), 1, "safe integer"),
        (tuple(_lot(f"lot-{index:03d}") for index in range(201)), 1_000_000, "200"),
    ),
)
def test_run_input_rejects_duplicate_keys_dates_caps_and_unsafe_money(
    initial_lots: tuple[BacktestInitialLotInput, ...],
    initial_cash_fen: int,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _run_input(initial_lots=initial_lots, initial_cash_fen=initial_cash_fen)


def test_exactly_200_lots_are_supported_and_normalized() -> None:
    plan = _plan().model_copy(
        update={
            "position": PositionPolicy(
                max_qty=20_000,
                core_target_qty=10_000,
                tactical_target_qty=10_000,
            )
        }
    )
    lots = tuple(
        _lot(
            f"lot-{index:03d}",
            bucket="CORE" if index < 100 else "TACTICAL",
            cost_basis_fen=1,
        )
        for index in reversed(range(200))
    )

    run_input = _run_input(plan=plan, initial_lots=lots)

    assert len(run_input.initial_lots) == 200
    assert run_input.initial_lots == tuple(
        sorted(
            run_input.initial_lots,
            key=lambda item: (item.bucket, item.acquired_trade_date, item.lot_key),
        )
    )
    assert run_input.run_formula_version == RUN_FORMULA_V2


def test_operational_fields_are_closed_and_plan_version_is_identity_free() -> None:
    first = _run_input(
        initial_lots=(_lot("seed"),),
        plan_version_id=UUID("4c623c8c-ca26-4cd8-8cb2-08cd5e61be93"),
    )
    second = _run_input(
        initial_lots=(_lot("seed"),),
        plan_version_id=UUID("f9586c94-e03f-4807-b2d8-1023843f110f"),
    )

    assert first.run_id == second.run_id
    for excluded in (
        "job_id",
        "attempt",
        "progress",
        "audit_timestamp",
        "cancelled",
    ):
        assert excluded not in BacktestRunInput.model_fields
        with pytest.raises(ValidationError):
            BacktestRunInput.model_validate(
                first.model_dump(mode="python", round_trip=True) | {excluded: "forbidden"}
            )
