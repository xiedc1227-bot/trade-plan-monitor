"""Offline Windows load gate: real monitor ledger/API and admitted native workers.

No production pressure controller, live providers or user databases are involved.
Default phases are the approved 600 seconds; --smoke is development evidence only.
"""

import argparse
import ctypes
import json
import math
import os
import platform
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from threading import enumerate as threads
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tests.integration.test_backtest_isolation_fault_matrix import FIXTURE  # noqa: E402
from tests.integration.test_daily_plan_chain import (  # noqa: E402
    FRIDAY,
    SH,
    TUESDAY,
    WEDNESDAY,
    Chain,
    OfflineRuntime,
)
from tests.integration.test_monitor_loop_production_composition import (  # noqa: E402
    BASE,
    NOW,
    ORIGIN,
    environment,
    post,
    wait,
)
from tests.integration.test_monitor_loop_production_composition import (  # noqa: E402
    FIXTURE as SOURCE_FIXTURE,
)
from tests.integration.test_plan_preparation_review import review_command  # noqa: E402

from trade_plan_monitor.backtest.composition import (  # noqa: E402
    create_backtest_composition_factory,
)
from trade_plan_monitor.backtest.preparation_store import PreparationStore  # noqa: E402
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote  # noqa: E402
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs  # noqa: E402
from trade_plan_monitor.state.models import TradingCalendar  # noqa: E402
from trade_plan_monitor.web.app import create_app  # noqa: E402


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def wal_bytes(root):
    """Sample extant WAL files; a legal concurrent checkpoint can remove one."""
    total = 0
    for path in root.rglob("*-wal"):
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total


def working_set():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "working",
                "pool_peak",
                "pool",
                "nonpaged_peak",
                "nonpaged",
                "pagefile",
                "pagefile_peak",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(Counters),
        ctypes.c_ulong,
    ]
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    assert ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    return counters.working


class Runtime(OfflineRuntime):
    def __init__(self, chain):
        super().__init__(chain)
        self.starts = self.stops = 0

    async def start(self):
        self.starts += 1

    async def stop(self):
        self.stops += 1


def make_app(root, patches):
    market_root = root / "backtest"
    _unused_app, ai, _unused_runtime, _unused_calls = environment(market_root, patches)
    monitor_root = root / "monitor"
    monitor_root.mkdir()
    chain = Chain(monitor_root)
    factory = create_backtest_composition_factory(
        config_path=market_root / "absent.yaml",
        plan_snapshot_reader=None,
        market_database=market_root / "market.sqlite3",
        results_database=market_root / "results.sqlite3",
        cursor_key_path=market_root / "cursor.key",
        preparation_database=market_root / "preparation.sqlite3",
    )
    calls = []

    def activate():
        calls.append(monotonic())
        return factory()

    runtime = Runtime(chain)
    app = create_app(
        runtime_factory=lambda: runtime,
        plan_lifecycle_factory=lambda: chain.plans,
        backtest_lifecycle_factory=activate,
        ai_lifecycle_factory=lambda: ai,
    )
    chain.client = TestClient(app, base_url=ORIGIN)
    return chain, ai, runtime, calls, market_root


def activate_monitor(chain):
    plans = []
    original = chain.plan
    with chain.plans._unit_of_work() as work:
        work.daily.session.add_all(
            TradingCalendar(
                exchange="SSE",
                cal_date=day,
                is_open=True,
                previous_trade_date=previous,
            )
            for previous, day in (
                (FRIDAY - timedelta(days=1), FRIDAY),
                (FRIDAY, TUESDAY),
                (TUESDAY, WEDNESDAY),
            )
        )
        work.commit()
    series = chain.series()
    for index, symbol in enumerate(FIXTURE["symbols"]):
        chain.plan = original.model_copy(update={"symbol": symbol, "plan_id": f"load-{index}"})
        chain.activate()
        current = series.model_copy(
            update={
                "symbol": chain.plan.symbol,
                "bars": tuple(
                    bar.model_copy(update={"symbol": chain.plan.symbol}) for bar in series.bars
                ),
            }
        )
        chain.runtime.run_inputs(
            plan=chain.plan,
            inputs=DailyRuntimeInputs(
                evaluated_at=chain.now,
                official_trade_date=FRIDAY,
                series=current,
                session_dates=(FRIDAY, TUESDAY, WEDNESDAY),
                suspended_dates=(),
                quote=None,
                data_blockers=(),
            ),
        )
        for kind in (
            "PRICE_STRUCTURE",
            "VOLUME_OR_CANDLE",
            "TECHNICAL",
            "SEVERE_STRUCTURE",
            "SEVERE_DETERIORATION",
        ):
            chain.post(
                "daily-plan-facts",
                {
                    "planVersionId": chain.version["id"],
                    "contentHash": chain.version["contentHash"],
                    "factId": symbol + "-" + kind,
                    "kind": kind,
                    "tradeDate": str(FRIDAY),
                    "satisfied": not kind.startswith("SEVERE_"),
                    "evidence": "Offline reviewed facts for this symbol and completed session.",
                    "expectedRevision": 0,
                },
            )
        chain.post(
            "simulation-position-confirmations",
            {
                "symbol": symbol,
                "coreQty": 100,
                "tacticalQty": 0,
                "expectedRevision": 0,
            },
        )
        plans.append(chain.plan)
    return plans, series


def monitor_tick(chain, plans, series, number, scheduled):
    delay_ms = max(0, (monotonic() - scheduled) * 1000)
    chain.now = datetime(2026, 9, 22, 10, tzinfo=SH) + timedelta(seconds=number)
    results = []
    for plan in plans:
        current = series.model_copy(
            update={
                "symbol": plan.symbol,
                "bars": tuple(
                    bar.model_copy(update={"symbol": plan.symbol}) for bar in series.bars
                ),
            }
        )
        quote = DailyExecutionQuote(
            symbol=plan.symbol,
            price_fen=3970,
            quote_at=chain.now,
            available_at=chain.now,
            evaluated_at=chain.now,
            tradable=True,
            special_state_verified=True,
            liquidity_available=True,
        )
        result = chain.runtime.run_inputs(
            plan=plan,
            inputs=DailyRuntimeInputs(
                evaluated_at=chain.now,
                official_trade_date=None,
                series=current,
                session_dates=(FRIDAY, TUESDAY, WEDNESDAY),
                suspended_dates=(),
                quote=quote,
                data_blockers=(),
            ),
        )
        assert not result.duplicate and result.evaluation_id is not None
        assert result.snapshot["signals"][0]["state"] == "READY"
        assert result.snapshot["signals"][0]["executable_qty"] == 100
        results.append(result)
    return delay_ms, results


def prepare(client, root):
    assert (
        post(
            client,
            BASE,
            {
                "input": {
                    "preparation_id": "load",
                    "sources": [SOURCE_FIXTURE["source"]],
                }
            },
            "create-load",
        ).status_code
        == 201
    )
    for index in range(2):
        record = client.get(BASE + "/load").json()
        assert (
            post(
                client,
                BASE + "/load/extractions",
                {
                    "expectedRevision": record["revision"],
                },
                f"extract-{index}",
            ).status_code
            == 202
        )
        wait(
            client,
            BASE + "/load",
            lambda value: value["status"] in {"FAILED", "CANDIDATE"} and value["workPhase"] is None,
        )
    record = PreparationStore(root / "preparation.sqlite3", clock=lambda: NOW).get("load")
    reviewed = post(
        client,
        BASE + "/load/reviews",
        {
            "review": review_command(record, account=None).model_dump(mode="json"),
        },
        "review-load",
    )
    assert reviewed.status_code == 200, reviewed.text
    return reviewed.json()["manifestHash"]


def replay_load(client, manifest, stopped, *, deadline):
    count = 0
    admission = []
    while not stopped.is_set() and monotonic() < deadline:
        started = monotonic()
        response = post(
            client,
            "/api/v1/backtest-runs",
            {
                "preparationId": "load",
                "manifestHash": manifest,
                "response": {"mode": "FOLLOW_REMINDERS", "responseDelaySeconds": count},
                "costs": {
                    "commissionRate": "0.0003",
                    "minimumCommissionFen": 500,
                    "stampDutyRate": "0.0005",
                    "transferFeeRate": "0.00001",
                    "buySlippageFen": 1,
                    "sellSlippageFen": 1,
                },
            },
            f"load-run-{count}",
        )
        assert response.status_code == 202, response.text
        admission.append((monotonic() - started) * 1000)
        receipt = response.json()
        assert not receipt["reused"]
        terminal = wait(
            client,
            "/api/v1/backtest-jobs/" + receipt["jobId"],
            lambda value: value["status"] in {"COMPLETED", "FAILED"},
        )
        assert terminal["status"] == "COMPLETED", terminal
        count += 1
        stopped.wait(max(0, min(
            FIXTURE["backtest_start_interval_seconds"] - (monotonic() - started),
            deadline - monotonic(),
        )))
    return {
        "completed_runs": count,
        "admission_p95_ms": percentile(admission, 0.95) if admission else None,
    }


def phase(chain, plans, series, seconds, *, offset, worker):
    start = monotonic()
    delays, status_times, memories, events, identities = [], [], [], [], set()
    ticks = 0
    next_monitor = next_status = start
    pending = None
    maximum_threads = maximum_wal = 0
    next_progress = start + 60
    while monotonic() < start + seconds:
        now = monotonic()
        if now >= next_monitor:
            if pending is not None:
                delay, results = pending.result(timeout=FIXTURE["phase_timeout_seconds"])
                delays.append(delay)
                for result in results:
                    assert result.evaluation_id not in identities
                    identities.add(result.evaluation_id)
                    events.extend(result.event_ids)
            pending = worker.submit(
                monitor_tick, chain, plans, series, offset + ticks, next_monitor
            )
            ticks += 1
            next_monitor += FIXTURE["monitor_interval_seconds"]
        if now >= next_status:
            begun = monotonic()
            symbol = plans[len(status_times) % len(plans)].symbol
            response = chain.client.get("/api/v1/plan-runtime/" + symbol)
            status_times.append((monotonic() - begun) * 1000)
            assert response.status_code == 200, response.text
            maximum_threads = max(
                maximum_threads, sum(thread.name.startswith("backtest-") for thread in threads())
            )
            memories.append(working_set())
            maximum_wal = max(
                maximum_wal,
                wal_bytes(chain.plans._database_path.parent.parent),
            )
            next_status += FIXTURE["status_interval_seconds"]
        if monotonic() >= next_progress:
            print(json.dumps({
                "phase": "baseline" if offset == 0 else "load",
                "elapsed_seconds": round(monotonic() - start, 1),
                "completed_evaluations": len(identities),
                "status_samples": len(status_times),
                "monitor_schedule_p99_ms": percentile(delays, 0.99),
            }), flush=True)
            next_progress += 60
        sleep(min(0.005, max(0.001, min(next_monitor, next_status) - monotonic())))
    if pending is not None:
        delay, results = pending.result(timeout=FIXTURE["phase_timeout_seconds"])
        delays.append(delay)
        for result in results:
            assert result.evaluation_id not in identities
            identities.add(result.evaluation_id)
            events.extend(result.event_ids)
    assert len(events) == len(set(events))
    return {
        "seconds": seconds,
        "elapsed_seconds": monotonic() - start,
        "monitor_ticks": ticks,
        "status_samples": len(status_times),
        "status_p95_ms": percentile(status_times, 0.95),
        "status_p99_ms": percentile(status_times, 0.99),
        "monitor_schedule_p99_ms": percentile(delays, 0.99),
        "evaluations": len(identities),
        "semantic_reminders": len(events),
        "rss_start_bytes": memories[0],
        "rss_peak_bytes": max(memories),
        "rss_end_bytes": memories[-1],
        "wal_peak_bytes": maximum_wal,
        "backtest_threads_peak": maximum_threads,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("windows-threads",), required=True)
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".pytest_cache/backtest-thread-load.json"
    )
    args = parser.parse_args()
    assert platform.system() == "Windows", "The accepted profile requires Windows."
    seconds = 3 if args.smoke else FIXTURE["phase_seconds"]
    report = {
        "profile": args.profile,
        "offline": True,
        "smoke": args.smoke,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
        },
        "fixture": FIXTURE,
    }
    patches = pytest.MonkeyPatch()
    root = Path(tempfile.mkdtemp(prefix="backtest-thread-load-"))
    report["disposable_root"] = str(root)
    try:
        chain, ai, runtime, calls, market_root = make_app(root, patches)
        with (
            chain.client,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="offline-monitor") as worker,
        ):
            plans, series = activate_monitor(chain)
            print("Baseline phase started", flush=True)
            report["baseline"] = phase(chain, plans, series, seconds, offset=0, worker=worker)
            assert calls == [] and not ai.calls
            assert report["baseline"]["backtest_threads_peak"] == 0
            manifest = prepare(chain.client, market_root)
            stopped = Event()
            with ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="offline-admission"
            ) as executor:
                load = executor.submit(
                    replay_load, chain.client, manifest, stopped,
                    deadline=monotonic() + seconds,
                )
                try:
                    print("Admitted replay/WAL load phase started", flush=True)
                    report["load"] = phase(
                        chain, plans, series, seconds, offset=seconds, worker=worker
                    )
                finally:
                    stopped.set()
                report["backtest_work"] = load.result(timeout=FIXTURE["phase_timeout_seconds"])
            for value in (report["baseline"], report["load"]):
                assert value["monitor_ticks"] == seconds, value
                assert value["evaluations"] == seconds * 10, value
            assert len(calls) == 1 and len(ai.calls) == 2
            assert runtime.starts == 1 and runtime.stops == 0
            assert report["baseline"]["semantic_reminders"] == 10
            assert report["load"]["semantic_reminders"] == 0
            assert report["load"]["backtest_threads_peak"] <= FIXTURE["maximum_backtest_threads"]
            assert report["backtest_work"]["completed_runs"] > 0
            if not args.smoke:
                for value in (report["baseline"], report["load"]):
                    assert value["status_samples"] >= FIXTURE["minimum_status_samples"]
                    assert value["status_p95_ms"] <= FIXTURE["status_p95_ms"]
                    assert value["status_p99_ms"] <= FIXTURE["status_p99_ms"]
                assert (
                    report["load"]["status_p95_ms"] - report["baseline"]["status_p95_ms"]
                    <= FIXTURE["status_p95_added_ms"]
                )
                assert (
                    report["load"]["monitor_schedule_p99_ms"]
                    - report["baseline"]["monitor_schedule_p99_ms"]
                    <= FIXTURE["monitor_p99_added_ms"]
                )
        assert runtime.stops == 1
        assert not any(thread.name.startswith("backtest-") for thread in threads())
        report["passed"] = True
    finally:
        patches.undo()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
