"""Credential-lifetime contracts for the one-shot certification child."""

from __future__ import annotations

import os
from pathlib import Path

from trade_plan_monitor.live_certification import LiveCertificationSurface
from trade_plan_monitor.live_certification_child import run_live_child


def test_stock_child_materializes_token_only_while_certification_is_running(
    tmp_path: Path,
) -> None:
    observed: dict[str, str | None] = {}
    secret = bytearray(b"synthetic-token-material")

    def certification_runner(surface: LiveCertificationSurface, output: Path) -> int:
        observed["token"] = os.environ.get("TUSHARE_TOKEN")
        observed["child"] = os.environ.get("TRADE_PLAN_MONITOR_TUSHARE_LIVE_CHILD")
        observed["authorization"] = os.environ.get(
            "TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE"
        )
        observed["surface"] = surface.value
        observed["output"] = str(output)
        return 0

    os.environ.pop("TUSHARE_TOKEN", None)
    result = run_live_child(
        surface=LiveCertificationSurface.STOCK,
        credential_target="trade-plan-monitor/tushare-live",
        credential_reader=lambda _target: secret,
        certification_runner=certification_runner,
        output_directory=tmp_path,
    )

    assert result == 0
    assert observed == {
        "token": "synthetic-token-material",
        "child": "1",
        "authorization": "1",
        "surface": "STOCK",
        "output": str(tmp_path),
    }
    assert "TUSHARE_TOKEN" not in os.environ
    assert secret == bytearray(len(secret))


def test_index_child_uses_independent_markers_and_surface(tmp_path: Path) -> None:
    observed: dict[str, str | None] = {}

    def certification_runner(surface: LiveCertificationSurface, output: Path) -> int:
        observed["stock"] = os.environ.get("TRADE_PLAN_MONITOR_TUSHARE_LIVE_CHILD")
        observed["index"] = os.environ.get("TRADE_PLAN_MONITOR_INDEX_LIVE_CHILD")
        observed["authorization"] = os.environ.get(
            "TRADE_PLAN_MONITOR_ALLOW_INDEX_LIVE"
        )
        observed["surface"] = surface.value
        observed["output"] = str(output)
        return 0

    result = run_live_child(
        surface=LiveCertificationSurface.BOARD_INDEX,
        credential_target="trade-plan-monitor/tushare-live",
        credential_reader=lambda _target: bytearray(b"synthetic-token-material"),
        certification_runner=certification_runner,
        output_directory=tmp_path,
    )

    assert result == 0
    assert observed == {
        "stock": None,
        "index": "1",
        "authorization": "1",
        "surface": "BOARD_INDEX",
        "output": str(tmp_path),
    }
    assert "TUSHARE_TOKEN" not in os.environ


def test_child_rejects_invalid_credential_bytes_without_running_certification(
    tmp_path: Path,
) -> None:
    called = False

    def certification_runner(_surface: LiveCertificationSurface, _output: Path) -> int:
        nonlocal called
        called = True
        return 0

    result = run_live_child(
        surface=LiveCertificationSurface.STOCK,
        credential_target="trade-plan-monitor/tushare-live",
        credential_reader=lambda _target: bytearray(b"contains whitespace"),
        certification_runner=certification_runner,
        output_directory=tmp_path,
    )

    assert result == 2
    assert called is False
    assert "TUSHARE_TOKEN" not in os.environ
