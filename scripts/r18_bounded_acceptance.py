"""R18 one-shot candidate for 2026-09-15. Default invocation makes no network calls."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, time

from scripts import r14_bounded_acceptance as bounded

PROPOSAL_ID = "R18-20260915-AFTERNOON-60"
AUTHORIZATION = "R18_20260915_3_AI_60_MARKET_IN_APP_15MIN"
RUN_ID = "r18-20260915-a"
MARKET_CAPS = {
    **bounded._MARKET_CAPS,
    "rt_min_daily": 2,
    "rt_idx_min_daily": 30,
}


def _eligible(now: datetime) -> bool:
    return now.date() == date(2026, 9, 15) and time(14, 30) <= now.time() <= time(14, 40)


def _preflight() -> dict[str, object]:
    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.live_profiles import load_index_certification

    result = bounded._preflight(start_window_eligible=_eligible, market_caps=MARKET_CAPS)
    index_ready = False
    try:
        configuration = load_application_config(bounded._ROOT / "config/app.yaml")
        if configuration.tushare.api_url is not None:
            profile = load_index_certification(
                bounded._ROOT / "data/live-certification/tushare-board-index-live.json",
                now=datetime.now(bounded._SHANGHAI),
                endpoint_url=str(configuration.tushare.api_url),
            )
            index_ready = profile is not None and bounded._INDEXES <= {
                code.value for code in profile.ready_indexes
            }
    except OSError, ValueError:
        pass
    return {
        **result,
        "ready": bool(result.get("ready") and index_ready),
        "market": {**result.get("market", {}), "indexCertificateReady": index_ready},
        "proposalId": PROPOSAL_ID,
        "runId": RUN_ID,
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
                session_root=bounded._ROOT / "data/r18-acceptance",
                market_caps=MARKET_CAPS,
                proposal_id=PROPOSAL_ID,
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
