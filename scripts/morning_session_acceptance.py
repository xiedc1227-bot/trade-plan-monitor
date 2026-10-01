"""R20 same-morning bounded live acceptance. Default invocation makes no network calls."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, time
from hashlib import sha256

from scripts import bounded_live_acceptance as bounded

from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V5

PROPOSAL_ID = "R20-20260915-A-105"
AUTHORIZATION = "R20_20260915_A_3_AI_105_MARKET_IN_APP_38MIN_V5_8192"
RUN_ID = "r20-20260915-a"
BIND_PORT = 18766
PROMPT_VERSION = PLAN_EXTRACTION_PROMPT_V5
AI_OUTPUT_TOKENS = 8192
MARKET_CAPS = {
    **bounded._MARKET_CAPS,
    "rt_min_daily": 2,
    "rt_min": 40,
    "rt_idx_min_daily": 50,
}
MARKET_TOTAL = 105
WALL_SECONDS = 2280
STOP_ON_MARKET_FAILURE_KEYS = frozenset({"trade_cal"})
STOP_ON_REFERENCE_FAILURE = True


def _eligible(now: datetime) -> bool:
    return now.date() == date(2026, 9, 15) and time(10, 35) <= now.time() <= time(10, 50)


def _preflight() -> dict[str, object]:
    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.live_profiles import load_index_certification

    result = bounded._preflight(
        start_window_eligible=_eligible,
        market_caps=MARKET_CAPS,
        market_total=MARKET_TOTAL,
        wall_seconds=WALL_SECONDS,
        bind_port=BIND_PORT,
        ai_output_tokens=AI_OUTPUT_TOKENS,
        prompt_version=PROMPT_VERSION,
    )
    index_ready = False
    configured_output_tokens: int | None = None
    configured_prompt_version: str | None = None
    try:
        configuration = load_application_config(bounded._ROOT / "config/app.yaml")
        configured_output_tokens = configuration.ai.max_output_tokens
        configured_prompt_version = configuration.ai.prompt_version
        if configuration.tushare.api_url is not None:
            profile = load_index_certification(
                bounded._ROOT / "data/live-certification/tushare-board-index-live.json",
                now=datetime.now(bounded._SHANGHAI),
                endpoint_url=str(configuration.tushare.api_url),
            )
            index_ready = profile is not None and bounded._INDEXES <= {
                code.value for code in profile.ready_indexes
            }
    except (OSError, ValueError):
        pass
    sources = bounded.approved_sources(prompt_version=PROMPT_VERSION)
    return {
        **result,
        "ready": bool(result.get("ready") and index_ready),
        "market": {**result.get("market", {}), "indexCertificateReady": index_ready},
        "ai": {
            **result.get("ai", {}),
            "configuredOutputTokens": configured_output_tokens,
            "configuredPromptVersion": configured_prompt_version,
            "sessionOverrideOutputTokens": AI_OUTPUT_TOKENS,
            "sessionOverridePromptVersion": PROMPT_VERSION,
            "balanceStatus": "UNKNOWN_NOT_PROBED",
        },
        "sourceHashes": {
            case_id: sha256(source.encode("utf-8")).hexdigest()
            for case_id, (source, _) in sources.items()
        },
        "estimatedThreeRequestUsd": 0.117523,
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
                session_root=bounded._ROOT / "data/r20-acceptance",
                market_caps=MARKET_CAPS,
                market_total=MARKET_TOTAL,
                wall_seconds=WALL_SECONDS,
                proposal_id=PROPOSAL_ID,
                bind_port=BIND_PORT,
                prompt_version=PROMPT_VERSION,
                ai_output_tokens=AI_OUTPUT_TOKENS,
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
