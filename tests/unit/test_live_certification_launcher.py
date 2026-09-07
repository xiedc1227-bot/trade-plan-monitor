"""Security contracts for the one-shot live-certification launcher."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.live_certification import (
    LiveCertificationSurface,
    child_environment,
    launch_live_certification,
    required_authorization,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_child_environment_is_allowlisted_and_removes_every_secret_candidate() -> None:
    source = {
        "SystemRoot": r"C:\Windows",
        "PATH": r"C:\Windows\System32",
        "TEMP": r"C:\Temp",
        "TUSHARE_TOKEN": "parent-secret",
        "DEEPSEEK_API_KEY": "another-secret",
        "DATABASE_PASSWORD": "database-secret",
        "UNRELATED": "must-not-cross-boundary",
    }

    sanitized = child_environment(source)

    assert sanitized == {
        "PATH": r"C:\Windows\System32",
        "SystemRoot": r"C:\Windows",
        "TEMP": r"C:\Temp",
    }
    assert all(
        marker not in name.upper()
        for name in sanitized
        for marker in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
    )


@pytest.mark.parametrize(
    ("surface", "authorization"),
    [
        (LiveCertificationSurface.STOCK, "LPC005_STOCK_LIVE_CERTIFICATION"),
        (LiveCertificationSurface.BOARD_INDEX, "LPC007_BOARD_INDEX_LIVE_CERTIFICATION"),
    ],
)
def test_each_surface_has_a_distinct_exact_authorization(
    surface: LiveCertificationSurface,
    authorization: str,
) -> None:
    assert required_authorization(surface) == authorization


def test_launcher_fails_before_child_outside_market_window() -> None:
    calls: list[object] = []

    result = launch_live_certification(
        surface=LiveCertificationSurface.STOCK,
        authorization=required_authorization(LiveCertificationSurface.STOCK),
        credential_target="trade-plan-monitor/tushare-live",
        now=datetime(2026, 9, 7, 8, 0, tzinfo=SHANGHAI),
        runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert result.outcome == "NOT_RUN_MARKET_WINDOW"
    assert result.return_code == 0
    assert calls == []


def test_stock_authorization_cannot_start_index_certification() -> None:
    with pytest.raises(ValueError, match="authorization does not match"):
        launch_live_certification(
            surface=LiveCertificationSurface.BOARD_INDEX,
            authorization=required_authorization(LiveCertificationSurface.STOCK),
            credential_target="trade-plan-monitor/tushare-live",
            now=datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI),
            runner=lambda *_args, **_kwargs: None,
        )


def test_launcher_passes_only_reference_and_sanitized_environment_to_child() -> None:
    captured: dict[str, object] = {}
    parent_environment = {
        "SystemRoot": r"C:\Windows",
        "PATH": r"C:\Windows\System32",
        "TEMP": r"C:\Temp",
        "TUSHARE_TOKEN": "must-not-reach-child",
        "DEEPSEEK_API_KEY": "must-not-reach-child-either",
    }

    def runner(
        command: list[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        check: bool,
    ) -> CompletedProcess[str]:
        captured.update(command=command, cwd=cwd, env=dict(env), check=check)
        return CompletedProcess(command, 0)

    result = launch_live_certification(
        surface=LiveCertificationSurface.BOARD_INDEX,
        authorization=required_authorization(LiveCertificationSurface.BOARD_INDEX),
        credential_target="trade-plan-monitor/tushare-live",
        now=datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI),
        environment=parent_environment,
        executable=Path(os.fsdecode(os.fsencode(r"C:\Python\python.exe"))),
        project_root=Path(r"C:\project"),
        runner=runner,
    )

    assert result.outcome == "COMPLETED"
    command = captured["command"]
    assert isinstance(command, list)
    assert command == [
        r"C:\Python\python.exe",
        "-m",
        "trade_plan_monitor.live_certification_child",
        "--surface",
        "BOARD_INDEX",
        "--credential-target",
        "trade-plan-monitor/tushare-live",
    ]
    serialized = repr((captured["command"], captured["env"]))
    assert "must-not-reach-child" not in serialized
    assert "TUSHARE_TOKEN" not in serialized
    assert "DEEPSEEK_API_KEY" not in serialized
    assert captured["env"] == {
        "PATH": r"C:\Windows\System32",
        "SystemRoot": r"C:\Windows",
        "TEMP": r"C:\Temp",
        "TRADE_PLAN_MONITOR_LIVE_CERTIFICATION_SURFACE": "BOARD_INDEX",
    }
    assert captured["check"] is False
