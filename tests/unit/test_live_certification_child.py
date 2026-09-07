"""Credential-lifetime contracts for the one-shot certification child."""

from __future__ import annotations

import os

from trade_plan_monitor.live_certification import LiveCertificationSurface
from trade_plan_monitor.live_certification_child import run_live_child


def test_stock_child_materializes_token_only_while_pytest_is_running() -> None:
    observed: dict[str, str | None] = {}
    secret = bytearray(b"synthetic-token-material")

    def pytest_main(arguments: list[str]) -> int:
        observed["token"] = os.environ.get("TUSHARE_TOKEN")
        observed["child"] = os.environ.get("TRADE_PLAN_MONITOR_TUSHARE_LIVE_CHILD")
        observed["authorization"] = os.environ.get(
            "TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE"
        )
        observed["arguments"] = " ".join(arguments)
        return 0

    os.environ.pop("TUSHARE_TOKEN", None)
    result = run_live_child(
        surface=LiveCertificationSurface.STOCK,
        credential_target="trade-plan-monitor/tushare-live",
        credential_reader=lambda _target: secret,
        pytest_main=pytest_main,
    )

    assert result == 0
    assert observed == {
        "token": "synthetic-token-material",
        "child": "1",
        "authorization": "1",
        "arguments": "tests/contract/test_tushare_live.py -q -m live",
    }
    assert "TUSHARE_TOKEN" not in os.environ
    assert secret == bytearray(len(secret))


def test_index_child_uses_independent_markers_and_selector() -> None:
    observed: dict[str, str | None] = {}

    def pytest_main(arguments: list[str]) -> int:
        observed["stock"] = os.environ.get("TRADE_PLAN_MONITOR_TUSHARE_LIVE_CHILD")
        observed["index"] = os.environ.get("TRADE_PLAN_MONITOR_INDEX_LIVE_CHILD")
        observed["authorization"] = os.environ.get(
            "TRADE_PLAN_MONITOR_ALLOW_INDEX_LIVE"
        )
        observed["arguments"] = " ".join(arguments)
        return 0

    result = run_live_child(
        surface=LiveCertificationSurface.BOARD_INDEX,
        credential_target="trade-plan-monitor/tushare-live",
        credential_reader=lambda _target: bytearray(b"synthetic-token-material"),
        pytest_main=pytest_main,
    )

    assert result == 0
    assert observed == {
        "stock": None,
        "index": "1",
        "authorization": "1",
        "arguments": "tests/contract/test_tushare_index_live.py -q -m live",
    }
    assert "TUSHARE_TOKEN" not in os.environ


def test_child_rejects_invalid_credential_bytes_without_running_pytest() -> None:
    called = False

    def pytest_main(_arguments: list[str]) -> int:
        nonlocal called
        called = True
        return 0

    result = run_live_child(
        surface=LiveCertificationSurface.STOCK,
        credential_target="trade-plan-monitor/tushare-live",
        credential_reader=lambda _target: bytearray(b"contains whitespace"),
        pytest_main=pytest_main,
    )

    assert result == 2
    assert called is False
    assert "TUSHARE_TOKEN" not in os.environ
