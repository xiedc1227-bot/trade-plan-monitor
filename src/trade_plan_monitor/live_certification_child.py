"""One-shot child that materializes an OS credential only for a live selector."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from trade_plan_monitor.config import TushareConfiguration
from trade_plan_monitor.live_certification import LiveCertificationSurface
from trade_plan_monitor.market_data.tushare_client import (
    TushareClientConfigurationError,
    create_tushare_client,
)
from trade_plan_monitor.runtime.clock import SystemClock
from trade_plan_monitor.runtime.request_control import (
    create_live_tushare_request_controller,
)
from trade_plan_monitor.tushare_live_probe import (
    LiveProbeWindowError,
    certify_board_indexes,
    certify_stock,
)
from trade_plan_monitor.windows_credentials import (
    WindowsCredentialError,
    read_windows_generic_credential,
)

_TOKEN_ENV: Final = "TUSHARE_TOKEN"
_STOCK_CHILD_ENV: Final = "TRADE_PLAN_MONITOR_TUSHARE_LIVE_CHILD"
_STOCK_AUTH_ENV: Final = "TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE"
_INDEX_CHILD_ENV: Final = "TRADE_PLAN_MONITOR_INDEX_LIVE_CHILD"
_INDEX_AUTH_ENV: Final = "TRADE_PLAN_MONITOR_ALLOW_INDEX_LIVE"
_MANAGED_ENVIRONMENT_NAMES: Final = (
    _TOKEN_ENV,
    _STOCK_CHILD_ENV,
    _STOCK_AUTH_ENV,
    _INDEX_CHILD_ENV,
    _INDEX_AUTH_ENV,
)
_ENDPOINT: Final = "https://api.quicksync.cn"
_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_DEFAULT_OUTPUT_DIRECTORY: Final = Path(__file__).parents[2] / "data" / "live-certification"


def _zero(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _token_text(value: bytearray) -> str:
    if not 1 <= len(value) <= 8_192 or any(not 0x21 <= byte <= 0x7E for byte in value):
        raise WindowsCredentialError("Windows credential is not a valid provider token")
    try:
        return value.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        raise WindowsCredentialError("Windows credential is not a valid provider token") from None


async def _certify_surface(
    surface: LiveCertificationSurface,
    output_directory: Path,
) -> dict[str, object]:
    configuration = TushareConfiguration.model_validate(
        {
            "api_url": _ENDPOINT,
            "timeout_seconds": 15,
            "token_ref": {"environment_variable": _TOKEN_ENV},
        }
    )
    client = create_tushare_client(configuration)
    clock = SystemClock()
    observed_at = datetime.now(_SHANGHAI)
    controller = create_live_tushare_request_controller(clock=clock)
    try:
        if surface is LiveCertificationSurface.STOCK:
            profile = await certify_stock(
                client=client,
                request_controller=controller,
                observed_at=observed_at,
                endpoint_url=_ENDPOINT,
                output_path=output_directory / "tushare-stock-live.json",
            )
            return {
                "outcome": "CERTIFIED" if profile.ready else "CERTIFIED_VISIBLE_BLOCK",
                "profileId": profile.profile_id,
                "surface": surface.value,
            }
        profile = await certify_board_indexes(
            client=client,
            request_controller=controller,
            observed_at=observed_at,
            endpoint_url=_ENDPOINT,
            output_path=output_directory / "tushare-board-index-live.json",
        )
        return {
            "outcome": "CERTIFIED" if profile.ready_indexes else "CERTIFIED_VISIBLE_BLOCK",
            "profileId": profile.profile_id,
            "readyIndexCount": len(profile.ready_indexes),
            "surface": surface.value,
        }
    finally:
        await controller.aclose()


def _run_default_certification(
    surface: LiveCertificationSurface,
    output_directory: Path,
) -> int:
    try:
        result = asyncio.run(_certify_surface(surface, output_directory))
    except (LiveProbeWindowError, TushareClientConfigurationError):
        result = {"outcome": "NOT_RUN_PREREQUISITE", "surface": surface.value}
        return_code = 2
    except Exception:
        result = {"outcome": "CERTIFICATION_FAILED", "surface": surface.value}
        return_code = 1
    else:
        return_code = 0
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return return_code


def run_live_child(
    *,
    surface: LiveCertificationSurface,
    credential_target: str,
    credential_reader: Callable[[str], bytearray] = read_windows_generic_credential,
    certification_runner: Callable[[LiveCertificationSurface, Path], int] | None = None,
    output_directory: Path = _DEFAULT_OUTPUT_DIRECTORY,
) -> int:
    """Read, use, and erase one token without returning it to the launcher."""

    if not isinstance(surface, LiveCertificationSurface):
        raise TypeError("surface must be a LiveCertificationSurface")
    previous = {name: os.environ.get(name) for name in _MANAGED_ENVIRONMENT_NAMES}
    material: bytearray | None = None
    token: str | None = None
    try:
        material = credential_reader(credential_target)
        token = _token_text(material)
        os.environ[_TOKEN_ENV] = token
        if surface is LiveCertificationSurface.STOCK:
            os.environ[_STOCK_CHILD_ENV] = "1"
            os.environ[_STOCK_AUTH_ENV] = "1"
        else:
            os.environ[_INDEX_CHILD_ENV] = "1"
            os.environ[_INDEX_AUTH_ENV] = "1"
        selected_runner = (
            _run_default_certification
            if certification_runner is None
            else certification_runner
        )
        return int(selected_runner(surface, output_directory))
    except WindowsCredentialError:
        print(
            json.dumps(
                {"outcome": "NOT_RUN_CREDENTIAL_UNAVAILABLE", "surface": surface.value},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    finally:
        token = None
        if material is not None:
            _zero(material)
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", required=True, choices=tuple(LiveCertificationSurface))
    parser.add_argument("--credential-target", required=True)
    arguments = parser.parse_args()
    surface = LiveCertificationSurface(arguments.surface)
    expected_surface = os.environ.get("TRADE_PLAN_MONITOR_LIVE_CERTIFICATION_SURFACE")
    if expected_surface != surface.value:
        print(
            json.dumps(
                {"outcome": "NOT_RUN_CHILD_BOUNDARY_INVALID", "surface": surface.value},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    return run_live_child(surface=surface, credential_target=arguments.credential_target)


if __name__ == "__main__":
    raise SystemExit(main())
