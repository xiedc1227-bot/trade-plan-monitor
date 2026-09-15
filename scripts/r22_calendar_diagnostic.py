"""R22 one-shot live calendar diagnostic. Default invocation makes no network calls."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, time

from scripts import r14_bounded_acceptance as bounded

PROPOSAL_ID = "R22-20260915-A-CALENDAR-1"
AUTHORIZATION = "R22_20260915_A_0_AI_1_TRADE_CAL_IN_APP_15SEC"
RUN_ID = "r22-20260915-a"
BIND_PORT = 18767
AI_TOTAL = 0
MARKET_CAPS = {
    "trade_cal": 1,
    "stk_limit": 0,
    "daily": 0,
    "rt_min_daily": 0,
    "rt_min": 0,
    "idx_mins": 0,
    "rt_idx_min_daily": 0,
    "index_daily": 0,
}
MARKET_TOTAL = 1
WALL_SECONDS = 15
STOP_ON_MARKET_FAILURE_KEYS = frozenset({"trade_cal"})
STOP_ON_REFERENCE_FAILURE = True


def _eligible(now: datetime) -> bool:
    return now.date() == date(2026, 9, 15) and time(11, 20) <= now.time() <= time(11, 55)


def _preflight() -> dict[str, object]:
    result = bounded._preflight(
        start_window_eligible=_eligible,
        market_caps=MARKET_CAPS,
        market_total=MARKET_TOTAL,
        wall_seconds=WALL_SECONDS,
        bind_port=BIND_PORT,
        ai_total=AI_TOTAL,
        require_ai=False,
    )
    return {
        **result,
        "proposalId": PROPOSAL_ID,
        "runId": RUN_ID,
        "diagnosticOnly": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize", default="")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv)
    preflight = _preflight()
    if not args.execute:
        print(json.dumps(preflight, ensure_ascii=False, sort_keys=True))
        return 0
    if args.authorize != AUTHORIZATION or not preflight.get("ready"):
        print(json.dumps({"status": "NOT_RUN_AUTHORIZATION_OR_PREFLIGHT"}))
        return 2
    if args.run_id != RUN_ID or not _eligible(datetime.now(bounded._SHANGHAI)):
        print(json.dumps({"status": "NOT_RUN_INVALID_ID_OR_WINDOW"}))
        return 2
    try:
        return asyncio.run(
            bounded._serve(
                RUN_ID,
                session_root=bounded._ROOT / "data/r22-calendar-diagnostic",
                market_caps=MARKET_CAPS,
                market_total=MARKET_TOTAL,
                wall_seconds=WALL_SECONDS,
                proposal_id=PROPOSAL_ID,
                bind_port=BIND_PORT,
                ai_total=AI_TOTAL,
                ai_caps={},
                stop_on_market_failure_keys=STOP_ON_MARKET_FAILURE_KEYS,
                stop_on_reference_failure=STOP_ON_REFERENCE_FAILURE,
            )
        )
    except FileExistsError:
        print(json.dumps({"status": "NOT_RUN_SESSION_ALREADY_CLAIMED"}))
        return 2
    except bounded.BudgetDenied:
        print(json.dumps({"status": "NOT_RUN_PRECONDITION_DENIED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
