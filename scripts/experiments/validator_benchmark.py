"""Declared diagnostic schedule after the valid-large-row feasibility gate failed.

Full frozen monitor/result reads, synthetic authority, no production performance claim.
"""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from threading import Event, Thread, get_ident
from time import perf_counter, process_time
from zoneinfo import ZoneInfo

from scripts.experiments.bounded_benchmark import (
    FrozenStore,
    frozen_authority,
    frozen_engine,
    output_hash,
)
from scripts.experiments.evidence_cohort import Flights
from scripts.experiments.global_evidence_budget import Budget
from scripts.experiments.process_metrics import process_metrics
from scripts.experiments.validator_adapter import install
from sqlalchemy.orm import sessionmaker

from trade_plan_monitor.backtest.composition import _ProductionBacktestService
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


async def run(args):
    now = datetime(2026, 10, 22, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    value, thread = frozen_authority(now), get_ident()
    calls = 0

    def authority():
        nonlocal calls
        assert get_ident() == thread
        calls += 1
        return value

    engine = frozen_engine(args.monitor)
    service = object.__new__(_ProductionBacktestService)
    service._result_store = FrozenStore(args.results)
    result_run = service._result_store.get_result_run(args.run)
    report = dict(
        scope="Diagnostic only after valid-large-row gate failure; frozen RO/synthetic "
        "authority; not performance acceptance.",
        samples=[],
        inputs={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.monitor, args.results)
        },
    )
    expected = {}

    def save():
        args.output.write_text(json.dumps(report, indent=2), encoding="utf8")

    async def sample(variant, readers, mixed, round_number):
        nonlocal calls
        calls = 0
        budget, scans, timings = Budget(), [], []
        flights = Flights(budget, funded=True)
        reader = RuntimeStatusReadService(
            sessionmaker(bind=engine, expire_on_commit=False), authority, clock=lambda: now
        )
        stop, memories = Event(), []

        def observe():
            while not stop.is_set():
                parent = process_metrics(os.getpid())
                memories.append(dict(parent=parent, child=None))
                stop.wait(0.02)

        sampler = Thread(target=observe)
        sampler.start()
        try:
            start, cpu = perf_counter(), process_time()

            async def monitor():
                before = perf_counter()
                try:
                    response = (await reader._read())[0].model_dump(mode="json")
                    digest = output_hash(response)
                    expected.setdefault("monitor", digest)
                    assert expected["monitor"] == digest
                    timings.append(
                        dict(kind="monitor", ok=True, seconds=perf_counter() - before, hash=digest)
                    )
                except Exception as error:
                    timings.append(
                        dict(
                            kind="monitor",
                            ok=False,
                            seconds=perf_counter() - before,
                            error=type(error).__name__,
                        )
                    )

            async def result():
                before = perf_counter()
                try:
                    response = await asyncio.to_thread(service._project_run, result_run)
                    digest = output_hash(response.model_dump(mode="json"))
                    expected.setdefault("result", digest)
                    assert expected["result"] == digest
                    timings.append(
                        dict(kind="result", ok=True, seconds=perf_counter() - before, hash=digest)
                    )
                except Exception as error:
                    timings.append(
                        dict(
                            kind="result",
                            ok=False,
                            seconds=perf_counter() - before,
                            error=type(error).__name__,
                        )
                    )

            with install(flights, scans, variant):
                try:
                    jobs = [asyncio.create_task(monitor()) for _ in range(readers)]
                    if mixed:
                        jobs.append(asyncio.create_task(result()))
                    await asyncio.gather(*jobs)
                finally:
                    await reader.stop()
                    flights.drain()
            wall, parent_cpu = perf_counter() - start, process_time() - cpu
        finally:
            stop.set()
            sampler.join()
        item = dict(
            variant=variant,
            readers=readers,
            mixed=mixed,
            round=round_number,
            wallSeconds=wall,
            parentCpuSeconds=parent_cpu,
            childCpuSeconds=0,
            authorityCalls=calls,
            requests=timings,
            scans=scans,
            budget=budget.snapshot(),
            flights=flights.stats,
            events=flights.events,
            originalFlights=reader._index_verifier.snapshot(),
            memorySamples=memories,
        )
        assert budget.snapshot()["used"] == 0 and reader.outstanding_work == 0
        report["samples"].append(item)
        save()
        fields = ("variant", "readers", "mixed", "round", "wallSeconds", "authorityCalls")
        print(json.dumps({k: item[k] for k in fields}), flush=True)

    try:
        if args.memory:
            await sample(args.memory, 8, True, 0)
            return
        if args.smoke:
            for variant in ("ordered", "validator", "slots2", "slots1", "combined2", "combined1"):
                await sample(variant, 1, True, 0)
            return
        for round_number in range(1, 4):
            for readers in (1, 2, 8):
                variants = ("ordered", "validator", "slots2", "slots1", "combined2", "combined1")
                if round_number % 2 == 0:
                    variants = tuple(reversed(variants))
                for variant in variants:
                    await sample(variant, readers, False, round_number)
            variants = ("ordered", "validator", "slots2", "slots1", "combined2", "combined1")
            for variant in variants if round_number % 2 else tuple(reversed(variants)):
                await sample(variant, 1, True, round_number)
    finally:
        report["workerCreated"] = False
        engine.dispose()
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monitor", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument(
        "--memory", choices=["ordered", "validator", "slots2", "slots1", "combined2", "combined1"]
    )
    asyncio.run(run(parser.parse_args()))
