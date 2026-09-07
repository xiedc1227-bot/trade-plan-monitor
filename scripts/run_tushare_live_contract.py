"""Market-window-gated one-shot launcher for the live Tushare contract.

This module deliberately checks only local wall-clock eligibility. Until an OS
secret-store adapter can inject a token directly into a one-shot child, it
fails closed instead of inheriting the parent environment.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_AUTHORIZATION_ENV = "TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE"


def _wall_clock_is_eligible(now: datetime) -> bool:
    local = now.astimezone(_SHANGHAI)
    if local.weekday() >= 5:
        return False
    current = local.time()
    return (
        time(9, 32) <= current <= time(11, 28)
        or time(13, 2) <= current <= time(14, 56)
        or time(15, 20) <= current <= time(16, 30)
    )


def main() -> int:
    observed_at = datetime.now(_SHANGHAI)
    if not _wall_clock_is_eligible(observed_at):
        print(
            json.dumps(
                {
                    "outcome": "NOT_RUN_MARKET_WINDOW",
                    "timezone": "Asia/Shanghai",
                    "weekday": observed_at.strftime("%A"),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 0

    if os.environ.get(_AUTHORIZATION_ENV) != "1":
        print(
            json.dumps(
                {"outcome": "NOT_RUN_UNAUTHORIZED", "timezone": "Asia/Shanghai"},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2

    print(
        json.dumps(
            {
                "outcome": "NOT_RUN_SECRET_INJECTION_UNAVAILABLE",
                "timezone": "Asia/Shanghai",
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
