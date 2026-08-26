"""Stable CLI dispatch for isolated backtest commands."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from trade_plan_monitor.backtest.application import BacktestApplicationService, _yuan_to_fen
from trade_plan_monitor.cli import main as run_cli


def test_backtest_sync_requires_an_explicit_flag_and_preserves_scope_types() -> None:
    calls: list[tuple[str, object]] = []
    outputs: list[object] = []

    class Service:
        async def sync(self, **kwargs):
            calls.append(("sync", kwargs))
            return {"ok": True}

    def factory(config, market, results, reports):
        calls.append(("factory", (config, market, results, reports)))
        return Service()

    assert (
        run_cli(
            [
                "backtest",
                "sync",
                "--symbols",
                "600000.SH",
                "--start",
                "2026-08-24",
                "--end",
                "2026-08-24",
                "--allow-network",
            ],
            backtest_service_factory=factory,
            result_writer=outputs.append,
        )
        == 0
    )
    assert calls[0] == (
        "factory",
        (
            Path("config/app.yaml"),
            Path("data/backtest-market.sqlite3"),
            Path("data/backtest-results.sqlite3"),
            Path("backtest-reports"),
        ),
    )
    name, values = calls[1]
    assert name == "sync"
    assert values["symbols"] == ("600000.SH",)
    assert values["allow_network"] is True
    assert values["start"].isoformat() == "2026-08-24"
    assert outputs == [{"ok": True}]


def test_backtest_run_requires_explicit_execution_and_event_risk_inputs() -> None:
    captured: list[dict[str, object]] = []

    class Service:
        def run(self, **kwargs):
            captured.append(kwargs)
            return "done"

    result = run_cli(
        [
            "backtest",
            "run",
            "--dataset",
            "a" * 64,
            "--plan",
            "plan.yaml",
            "--initial-cash-yuan",
            "100000",
            "--commission-rate",
            "0.0003",
            "--minimum-commission-yuan",
            "5",
            "--stamp-duty-rate",
            "0.0005",
            "--transfer-fee-rate",
            "0.00001",
            "--buy-slippage-bps",
            "2",
            "--sell-slippage-bps",
            "2",
            "--no-event-risk",
        ],
        backtest_service_factory=lambda *_paths: Service(),
        result_writer=lambda _value: None,
    )

    assert result == 0
    assert captured[0]["manual_event_risk"] is False
    assert str(captured[0]["commission_rate"]) == "0.0003"


def test_sync_without_network_grant_stops_before_config_or_database_access(tmp_path) -> None:
    market_path = tmp_path / "market.sqlite3"
    service = BacktestApplicationService(
        config_path=tmp_path / "missing-config.yaml",
        market_database=market_path,
        results_database=tmp_path / "results.sqlite3",
        report_directory=tmp_path / "reports",
    )

    with pytest.raises(PermissionError, match="allow-network"):
        asyncio.run(
            service.sync(
                symbols=("600000.SH",),
                start=date(2026, 8, 24),
                end=date(2026, 8, 24),
                warmup_start=date(2026, 8, 24),
                refresh=False,
                allow_network=False,
            )
        )

    assert not market_path.exists()


def test_bse_sync_stops_before_config_or_database_access(tmp_path) -> None:
    market_path = tmp_path / "market.sqlite3"
    service = BacktestApplicationService(
        config_path=tmp_path / "missing-config.yaml",
        market_database=market_path,
        results_database=tmp_path / "results.sqlite3",
        report_directory=tmp_path / "reports",
    )

    with pytest.raises(ValueError, match="UNSUPPORTED_HISTORICAL_CALENDAR:BSE"):
        asyncio.run(
            service.sync(
                symbols=("920000.BJ",),
                start=date(2026, 8, 24),
                end=date(2026, 8, 24),
                warmup_start=date(2026, 8, 24),
                refresh=False,
                allow_network=True,
            )
        )

    assert not market_path.exists()


def test_yuan_to_fen_is_exact_under_any_ambient_decimal_precision() -> None:
    value = Decimal("100000.01")

    with localcontext() as context:
        context.prec = 6
        low_precision = _yuan_to_fen(value, "initial_cash_yuan", positive=True)
    with localcontext() as context:
        context.prec = 50
        high_precision = _yuan_to_fen(value, "initial_cash_yuan", positive=True)

    assert low_precision == high_precision == 10_000_001
    assert _yuan_to_fen(Decimal("5.000"), "minimum_commission_yuan", positive=False) == 500


def test_yuan_to_fen_rejects_unsafe_or_inexact_expansions_before_integer_conversion() -> None:
    with pytest.raises(ValueError, match="maximum supported amount"):
        _yuan_to_fen(Decimal("1E+1000000000"), "initial_cash_yuan", positive=True)
    with pytest.raises(ValueError, match="at most two decimal places"):
        _yuan_to_fen(Decimal("0.001"), "minimum_commission_yuan", positive=False)
    with pytest.raises(ValueError, match="maximum supported amount"):
        _yuan_to_fen(Decimal("92233720368547758.08"), "initial_cash_yuan", positive=True)

    assert (
        _yuan_to_fen(
            Decimal("92233720368547758.07"),
            "initial_cash_yuan",
            positive=True,
        )
        == 9_223_372_036_854_775_807
    )
