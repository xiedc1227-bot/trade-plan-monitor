"""Explicit, bounded live acceptance using a new test-owned monitor database.

Uses the installed production composition and local config/evidence unchanged.
The after-close intraday invocation verifies the wire/persistence path with STALE
data; it is deliberately not evidence of a fresh open-market trading signal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import time
from pathlib import Path
from time import monotonic
from uuid import uuid4

from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_models import EntryPolicy, IndexCloseGteMaCondition
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    migrate_trade_plan_to_schema_v2,
    validate_trade_plan,
)
from trade_plan_monitor.runtime.clock import SystemClock
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


async def verify(config_path: Path, *, wait_for_scheduled_close: bool = False) -> dict[str, object]:
    import trade_plan_monitor.runtime.production as production

    clock = SystemClock()
    started = clock.now()
    if started.time() < time(15, 20):
        raise RuntimeError("this bounded acceptance requires the after-close window")
    root = config_path.resolve().parent.parent
    run_id = uuid4().hex
    output = root / "data/live-certification" / f"production-{run_id}.json"
    database = output.with_suffix(".sqlite3")
    assert not database.exists()
    engine = create_sqlite_engine(database)
    upgrade_database(engine)
    sessions = create_session_factory(engine)
    # Test fixtures have an explicit pre-open activation origin in their own DB.
    activation_at = started.replace(hour=9, minute=0, second=0, microsecond=0)
    sample = load_plan_yaml((root / "config/plans/003043.SZ.sample.yaml").read_text("utf-8"))
    with SqlAlchemyUnitOfWork(sessions, clock=lambda: activation_at) as work:
        for symbol, market in (("003043.SZ", "SZSE"), ("600000.SH", "SSE")):
            plan = sample.model_copy(
                update={
                    "symbol": symbol,
                    "market": market,
                    "plan_id": f"acceptance-{symbol}",
                }
            )
            plan = migrate_trade_plan_to_schema_v2(plan, new_version=2)
            plan = plan.model_copy(
                update={
                    "entry": EntryPolicy(
                        condition=IndexCloseGteMaCondition(
                            index_role="BOARD_REFERENCE",
                            period=5,
                        )
                    ),
                }
            )
            work.plans.save_draft(plan, source_text="isolated production acceptance fixture")
            work.plans.activate(
                plan,
                expected_revision=0,
                validation=validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE),
            )
        work.commit()
    engine.dispose()

    calls = []
    original_factory = production.create_tushare_client

    def observed_client(configuration):
        client = original_factory(configuration)
        original_query = client.query

        def query(name, fields="", **kwargs):
            calls.append(
                {"operation": name, "symbol": kwargs.get("ts_code"), "started": monotonic()}
            )
            return original_query(name, fields=fields, **kwargs)

        client.query = query
        return client

    production.create_tushare_client = observed_client
    report = {
        "startedAt": started.isoformat(),
        "database": database.name,
        "scope": "AFTER_CLOSE_PRODUCTION_COMPOSITION",
        "network": "config/app.yaml",
    }
    first = create_monitor_composition(config_path=config_path, database_path=database)
    scheduled_close = asyncio.Event()
    original_deadline = first._runtime._run_deadline

    async def observed_deadline(deadline):
        execution_started = clock.now()
        results = await original_deadline(deadline)
        if deadline.kind is DeadlineKind.OFFICIAL_CLOSE:
            report["scheduledOfficialClose"] = {
                "dueAt": deadline.due_at.isoformat(),
                "startedAt": execution_started.isoformat(),
                "results": [row.status.value for row in results],
            }
            scheduled_close.set()
        return results

    if wait_for_scheduled_close:
        first._runtime._run_deadline = observed_deadline
    try:
        startup = await first.start()
        report["startup"] = startup.status.value
        report["providers"] = {
            row.capability: {"status": row.status.value, "errorCode": row.error_code}
            for row in startup.providers
        }
        report["nextPollAt"] = (
            None if startup.next_poll_at is None else startup.next_poll_at.isoformat()
        )
        if startup.read_only:
            report["outcome"] = "STARTUP_DEGRADED"
            return report
        cutoff = started.replace(hour=15, minute=0, second=0, microsecond=0)
        intraday = MarketDeadline(
            kind=DeadlineKind.REALTIME_MINUTE,
            trade_date=started.date(),
            due_at=cutoff,
            bar_end=cutoff,
        )
        result = await first._runtime._run_deadline(intraday)
        report["intraday"] = [
            {
                "status": row.status.value,
                "signal": row.evaluation_result.snapshot.signal_type.value
                if row.evaluation_result
                else None,
            }
            for row in result
        ]
        report["freshIntradayCertifiedByThisRun"] = False
        report["intradayHealth"] = {}
        for symbol in ("003043.SZ", "600000.SH"):
            health = await first.read_service.get_symbol_health(symbol=symbol)
            report["intradayHealth"][symbol] = health.model_dump(mode="json", by_alias=True)
        pipeline = original_deadline.__self__._pipeline
        report["indexes"] = {
            code.value: snapshot.health.value
            for code, snapshot in pipeline.index_service.latest_snapshots().items()
        }
        assert report["indexes"] == {"000001.SH": "LIVE", "399001.SZ": "LIVE"}
        count = len(calls)
        # An incomplete identity has no claim; offline tests cover committed intraday idempotency.
        if result:
            repeat = await first._runtime._run_deadline(intraday)
            report["duplicateIntraday"] = {
                "results": len(repeat),
                "newRequests": len(calls) - count,
            }
        official = MarketDeadline(
            kind=DeadlineKind.OFFICIAL_CLOSE,
            trade_date=started.date(),
            due_at=clock.now(),
            close_attempt=1,
        )
        if wait_for_scheduled_close:
            next_poll = startup.next_poll_at
            if next_poll is None or next_poll.date() != started.date():
                raise RuntimeError("no remaining same-day official deadline")
            print(json.dumps({"waitingForScheduledClose": next_poll.isoformat()}), flush=True)
            await asyncio.wait_for(
                scheduled_close.wait(),
                timeout=max(0, (next_poll - clock.now()).total_seconds()) + 180,
            )
            report["officialClose"] = report["scheduledOfficialClose"]["results"]
        else:
            result = await first._runtime._run_deadline(official)
            report["officialClose"] = [row.status.value for row in result]
        assert report["officialClose"] == ["COMMITTED", "COMMITTED"]
        count = len(calls)
        repeat = await original_deadline(official)
        report["duplicateOfficial"] = {"results": len(repeat), "newRequests": len(calls) - count}
        assert not repeat and len(calls) == count
        before = await first.read_service.get_dashboard()
        report["dashboardType"] = type(before).__name__
        report["sequence"] = before.sequence
    except Exception as error:
        report["outcome"] = "FAILED"
        report["errorType"] = type(error).__name__
        # Application-owned errors are sanitized; no provider payload is emitted.
        report["errorCode"] = getattr(error, "code", None)
        raise
    finally:
        await first.stop()
        production.create_tushare_client = original_factory
        report["requestCounts"] = dict(Counter(item["operation"] for item in calls))
        report["minimumStartSpacingSeconds"] = min(
            (b["started"] - a["started"] for a, b in zip(calls, calls[1:], strict=False)),
            default=None,
        )
        report["finishedAt"] = clock.now().isoformat()
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    second = create_monitor_composition(config_path=config_path, database_path=database)
    try:
        restarted = await second.start()
        after = await second.read_service.get_dashboard()
        report["restart"] = restarted.status.value
        report["restartSequence"] = after.sequence
        report["preservedSequence"] = after.sequence == before.sequence
        report["outcome"] = (
            "PASSED"
            if report["preservedSequence"] and not restarted.read_only
            else "RESTART_MISMATCH"
        )
    finally:
        await second.stop()
        report["finishedAt"] = clock.now().isoformat()
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/app.yaml"))
    parser.add_argument(
        "--authorize", required=True, choices=["LPC006_LPC008_PRODUCTION_ACCEPTANCE"]
    )
    parser.add_argument(
        "--wait-for-scheduled-close",
        action="store_true",
        help="Observe the next same-day official close through the production supervisor.",
    )
    args = parser.parse_args()
    report = asyncio.run(
        verify(args.config, wait_for_scheduled_close=args.wait_for_scheduled_close)
    )
    if report.get("outcome") != "PASSED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
