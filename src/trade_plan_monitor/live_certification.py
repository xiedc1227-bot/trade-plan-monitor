"""Parent-side, secret-blind launcher for live Tushare certification."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
DEFAULT_CREDENTIAL_TARGET: Final = "trade-plan-monitor/tushare-live"
_CHILD_SURFACE_ENV: Final = "TRADE_PLAN_MONITOR_LIVE_CERTIFICATION_SURFACE"
_SAFE_ENVIRONMENT_NAMES: Final = frozenset(
    {
        "appdata",
        "comspec",
        "localappdata",
        "no_color",
        "path",
        "pathext",
        "systemdrive",
        "systemroot",
        "temp",
        "tmp",
        "userprofile",
        "username",
        "windir",
    }
)
_SECRET_NAME_MARKERS: Final = ("API_KEY", "PASSWORD", "SECRET", "TOKEN")


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


def child_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Copy only non-secret OS values required by the isolated Python child."""

    sanitized: dict[str, str] = {}
    for name, value in source.items():
        upper_name = name.upper()
        if name.casefold() not in _SAFE_ENVIRONMENT_NAMES:
            continue
        if any(marker in upper_name for marker in _SECRET_NAME_MARKERS):
            continue
        if isinstance(value, str):
            sanitized[name] = value
    return sanitized


def launch_live_certification(
    *,
    surface: LiveCertificationSurface,
    authorization: str,
    credential_target: str,
    now: datetime | None = None,
    environment: Mapping[str, str] | None = None,
    executable: Path | None = None,
    project_root: Path | None = None,
    runner: Callable[..., object] = subprocess.run,
) -> LiveCertificationLaunchResult:
    """Launch one credential-reading child only after local eligibility checks."""

    observed_at = datetime.now(_SHANGHAI) if now is None else now
    if not market_window_is_eligible(surface, observed_at):
        return LiveCertificationLaunchResult("NOT_RUN_MARKET_WINDOW", 0)
    if authorization != required_authorization(surface):
        raise ValueError("authorization does not match the selected live surface")
    if type(credential_target) is not str or not credential_target.strip():
        raise ValueError("credential target is invalid")

    child_env = child_environment(os.environ if environment is None else environment)
    child_env[_CHILD_SURFACE_ENV] = surface.value
    python = Path(sys.executable) if executable is None else executable
    root = Path(__file__).parents[2] if project_root is None else project_root
    command = [
        str(python),
        "-m",
        "trade_plan_monitor.live_certification_child",
        "--surface",
        surface.value,
        "--credential-target",
        credential_target,
    ]
    completed = runner(command, cwd=root, env=child_env, check=False)
    return_code = getattr(completed, "returncode", None)
    if type(return_code) is not int:
        raise TypeError("live child runner must return an integer returncode")
    return LiveCertificationLaunchResult(
        "COMPLETED" if return_code == 0 else "FAILED",
        return_code,
    )


__all__ = [
    "DEFAULT_CREDENTIAL_TARGET",
    "LiveCertificationLaunchResult",
    "LiveCertificationSurface",
    "child_environment",
    "launch_live_certification",
    "market_window_is_eligible",
    "required_authorization",
]
