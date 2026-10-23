"""Reproducible isolated attribution; never a native-bound or API acceptance proof."""

import argparse
import ctypes
import gc
import hashlib
import json
import os
import tracemalloc
from collections import defaultdict
from pathlib import Path
from threading import Event, Thread
from time import perf_counter, thread_time

from scripts.experiments.bounded_benchmark import frozen_engine
from scripts.experiments.global_evidence_large import large_candidate
from scripts.experiments.global_evidence_scan import COLUMNS, FROM, ORDER
from scripts.experiments.process_metrics import process_metrics
from scripts.experiments.validator_scan import latest

from trade_plan_monitor.runtime.market_indexes import ALWAYS_ON_INDEX_CODES as codes
from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, RawIndexCandidate
from trade_plan_monitor.state.projections import _latest_index_records


def cpu_times():
    times = [ctypes.c_ulonglong() for _ in range(4)]
    if not ctypes.windll.kernel32.GetProcessTimes(
        ctypes.c_void_p(-1), *(ctypes.byref(value) for value in times)
    ):
        raise OSError("process times unavailable")
    return dict(kernel=times[2].value / 10**7, user=times[3].value / 10**7)


def main(args):
    before = None
    if args.memory:
        rows = (large_candidate(),)
    else:
        before = hashlib.sha256(args.monitor.read_bytes()).hexdigest()
        engine = frozen_engine(args.monitor)
        with engine.connect() as connection, connection.begin():
            mapping = connection.exec_driver_sql(
                "select mapping_version from market_index_snapshot_head limit 1"
            ).scalar_one()
            query = (
                "select " + ",".join(COLUMNS) + FROM + " where h.mapping_version=? "
                "and h.index_code in (" + ",".join("?" for _ in codes) + ")" + ORDER
            )
            with connection.exec_driver_sql(query, (mapping, *(c.value for c in codes))) as cursor:
                rows = tuple(
                    RawIndexCandidate.from_values(
                        tuple(v[: len(HEAD_FIELDS)]), tuple(v[len(HEAD_FIELDS) :])
                    )
                    for v in cursor
                )
        engine.dispose()
    records = []
    expected = _latest_index_records(iter(rows), codes)
    for round_number in range(3):
        for variant in (
            ("original", "validator") if round_number % 2 == 0 else ("validator", "original")
        ):
            gc.collect()
            phases, memories = defaultdict(lambda: dict(wall=0, cpu=0, calls=0)), []

            def observe(stage, wall, cpu, phases=phases):
                phases[stage]["wall"] += wall
                phases[stage]["cpu"] += cpu
                phases[stage]["calls"] += 1

            stop = Event()

            def sample(stop=stop, memories=memories):
                while not stop.is_set():
                    memories.append(process_metrics(os.getpid()))
                    stop.wait(0.01)

            sampler = Thread(target=sample)
            sampler.start()
            if args.memory:
                tracemalloc.start()
            try:
                native = cpu_times()
                start, cpu = perf_counter(), thread_time()
                result = (
                    latest(iter(rows), codes, observe)
                    if variant == "validator"
                    else _latest_index_records(iter(rows), codes)
                )
                elapsed, used = perf_counter() - start, thread_time() - cpu
                split = {key: value - native[key] for key, value in cpu_times().items()}
                peak = tracemalloc.get_traced_memory()[1] if args.memory else None
                assert result == expected
                del result
            finally:
                if args.memory:
                    tracemalloc.stop()
                stop.set()
                sampler.join()
            records.append(
                dict(
                    round=round_number + 1,
                    variant=variant,
                    wall=elapsed,
                    cpu=used,
                    processCpu=split,
                    tracedPeak=peak,
                    phases=dict(phases),
                    memorySamples=memories,
                )
            )
    if before:
        assert hashlib.sha256(args.monitor.read_bytes()).hexdigest() == before
    report = dict(
        scope="Isolated pure validator, raw inputs and expected output prebuilt/excluded; "
        "three alternating rounds; memory tracing timings are diagnostic only. "
        "Sampled process memory is not a bound; retained allocator/order effects remain.",
        inputSha256=before,
        rows=len(rows),
        jsonBytes=sum(len(r.payload[9]) for r in rows),
        records=records,
    )
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--monitor", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
