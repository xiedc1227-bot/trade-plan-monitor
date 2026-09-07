"""One-shot child that materializes an OS credential only for a live selector."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from typing import Final

from trade_plan_monitor.live_certification import LiveCertificationSurface
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


def run_live_child(
    *,
    surface: LiveCertificationSurface,
    credential_target: str,
    credential_reader: Callable[[str], bytearray] = read_windows_generic_credential,
    pytest_main: Callable[[list[str]], int] | None = None,
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
            test_path = "tests/contract/test_tushare_live.py"
        else:
            os.environ[_INDEX_CHILD_ENV] = "1"
            os.environ[_INDEX_AUTH_ENV] = "1"
            test_path = "tests/contract/test_tushare_index_live.py"
        if pytest_main is None:
            import pytest

            selected_pytest_main = pytest.main
        else:
            selected_pytest_main = pytest_main
        return int(selected_pytest_main([test_path, "-q", "-m", "live"]))
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
