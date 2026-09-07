"""Run stock or board-index certification from the local application YAML."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.live_certification import LiveCertificationSurface
from trade_plan_monitor.market_data.tushare_client import (
    TushareClientConfigurationError,
    create_tushare_client,
)
from trade_plan_monitor.runtime.clock import SystemClock
from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
from trade_plan_monitor.tushare_live_probe import (
    LiveProbeWindowError,
    certify_board_indexes,
    certify_stock,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


async def _certify_surface(
    surface: LiveCertificationSurface,
    config_path: Path,
    output_directory: Path,
) -> dict[str, object]:
    configuration = load_application_config(config_path).tushare
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
                endpoint_url=str(configuration.api_url).rstrip("/"),
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
            endpoint_url=str(configuration.api_url).rstrip("/"),
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


def run_configured_certification(
    surface: LiveCertificationSurface,
    config_path: Path,
    output_directory: Path,
) -> int:
    """Run one selected live surface and print only its stable outcome."""

    try:
        result = asyncio.run(_certify_surface(surface, config_path, output_directory))
    except (OSError, ValidationError, LiveProbeWindowError, TushareClientConfigurationError):
        result = {"outcome": "NOT_RUN_CONFIG_UNAVAILABLE", "surface": surface.value}
        return_code = 2
    except Exception:
        result = {"outcome": "CERTIFICATION_FAILED", "surface": surface.value}
        return_code = 1
    else:
        return_code = 0
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return return_code


__all__ = ["run_configured_certification"]
