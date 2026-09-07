"""Explicitly selected live Tushare certification from local configuration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_DEFAULT_OUTPUT_DIRECTORY: Final = Path(__file__).parents[2] / "data" / "live-certification"


class LiveCertificationSurface(StrEnum):
    STOCK = "STOCK"
    BOARD_INDEX = "BOARD_INDEX"


@dataclass(frozen=True, slots=True)
class LiveCertificationLaunchResult:
    outcome: str
    return_code: int


def required_authorization(surface: LiveCertificationSurface) -> str:
    if surface is LiveCertificationSurface.STOCK:
        return "LPC005_STOCK_LIVE_CERTIFICATION"
    if surface is LiveCertificationSurface.BOARD_INDEX:
        return "LPC007_BOARD_INDEX_LIVE_CERTIFICATION"
    raise TypeError("surface must be a LiveCertificationSurface")


def market_window_is_eligible(surface: LiveCertificationSurface, now: datetime) -> bool:
    if not isinstance(surface, LiveCertificationSurface):
        raise TypeError("surface must be a LiveCertificationSurface")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise TypeError("now must be timezone-aware")
    local = now.astimezone(_SHANGHAI)
    if local.weekday() >= 5:
        return False
    current = local.time()
    intraday_start = time(9, 32) if surface is LiveCertificationSurface.STOCK else time(9, 40)
    afternoon_start = time(13, 2) if surface is LiveCertificationSurface.STOCK else time(13, 10)
    return (
        intraday_start <= current <= time(11, 25)
        or afternoon_start <= current <= time(14, 55)
        or time(15, 20) <= current <= time(16, 30)
    )


def launch_live_certification(
    *,
    surface: LiveCertificationSurface,
    authorization: str,
    config_path: Path,
    output_directory: Path = _DEFAULT_OUTPUT_DIRECTORY,
    now: datetime | None = None,
    runner: Callable[[LiveCertificationSurface, Path, Path], int] | None = None,
) -> LiveCertificationLaunchResult:
    """Run one configured surface directly after local eligibility checks."""

    observed_at = datetime.now(_SHANGHAI) if now is None else now
    if not market_window_is_eligible(surface, observed_at):
        return LiveCertificationLaunchResult("NOT_RUN_MARKET_WINDOW", 0)
    if authorization != required_authorization(surface):
        raise ValueError("authorization does not match the selected live surface")
    if not isinstance(config_path, Path):
        raise TypeError("config_path must be a Path")
    if not isinstance(output_directory, Path):
        raise TypeError("output_directory must be a Path")
    if runner is None:
        from trade_plan_monitor.live_certification_runner import (
            run_configured_certification,
        )

        selected_runner = run_configured_certification
    else:
        selected_runner = runner
    return_code = selected_runner(surface, config_path, output_directory)
    if type(return_code) is not int:
        raise TypeError("live certification runner must return an integer returncode")
    return LiveCertificationLaunchResult(
        "COMPLETED" if return_code == 0 else "FAILED",
        return_code,
    )


__all__ = [
    "LiveCertificationLaunchResult",
    "LiveCertificationSurface",
    "launch_live_certification",
    "market_window_is_eligible",
    "required_authorization",
]
