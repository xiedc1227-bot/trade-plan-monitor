"""Isolated NBB diagnostics; never lowers admission or certifies native bounds."""

import argparse
import gc
import hashlib
import json
import os
import shutil
import tracemalloc
from dataclasses import replace
from pathlib import Path
from statistics import median
from time import perf_counter, thread_time

import pydantic_core._pydantic_core as native
from scripts.experiments import c_benchmark, failure_boundary, fused_c_validator
from scripts.experiments.process_metrics import process_metrics

from trade_plan_monitor.state.projections import ProjectionError, _latest_index_records


def run(args):
    args.output.mkdir(exist_ok=False)
    paths = [args.monitor, args.fixtures / "decimal.sqlite3", args.fixtures / "dense.sqlite3"]
    fingerprints = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = dict(inputs=fingerprints, cpu=[], memory=[], admissions=[])
    variants = [
        ("original", _latest_index_records),
        ("fused", fused_c_validator.latest),
        ("boundary", failure_boundary.latest),
    ]

    def save():
        (args.output / "measurements.json").write_text(
            json.dumps(report, indent=2), encoding="utf8"
        )

    rows = c_benchmark.rows_from(args.monitor)
    expected = _latest_index_records(iter(rows), c_benchmark.CODES)
    for turn in range(3):
        for name, verify in variants if turn % 2 == 0 else variants[::-1]:
            gc.collect()
            start, cpu = perf_counter(), thread_time()
            result = verify(iter(rows), c_benchmark.CODES)
            elapsed, used = perf_counter() - start, thread_time() - cpu
            assert result == expected
            report["cpu"].append(dict(round=turn + 1, variant=name, wall=elapsed, cpu=used))
            del result
    del rows, expected
    report["medians"] = {
        name: {
            k: median(r[k] for r in report["cpu"] if r["variant"] == name) for k in ("wall", "cpu")
        }
        for name, _ in variants
    }
    save()
    for shape, path in zip(("decimal", "dense"), paths[1:], strict=True):
        (row,) = c_benchmark.rows_from(path)
        expected = _latest_index_records(iter((row,)), c_benchmark.CODES)
        payload = list(row.payload)
        payload[9] = payload[9].replace(b'"high_points":"1.', b'"high_points":"0.')
        assert payload[9] != row.payload[9]
        invalid = replace(row, payload=tuple(payload))
        del payload
        for mode, candidate in [("success", row), ("invalid", invalid)]:
            for name, verify in variants:
                gc.collect()
                before = process_metrics(os.getpid())
                tracemalloc.start()
                held = None
                start, cpu = perf_counter(), thread_time()
                try:
                    result = verify(iter((candidate,)), c_benchmark.CODES)
                except ProjectionError as error:
                    held = error
                elapsed, used = perf_counter() - start, thread_time() - cpu
                live, peak = tracemalloc.get_traced_memory()
                if mode == "success":
                    assert held is None and result == expected
                    del result
                else:
                    assert held is not None
                chain = held is not None and (
                    held.__cause__ is not None or held.__context__ is not None
                )
                after = process_metrics(os.getpid())
                held = None
                gc.collect()
                drained = tracemalloc.get_traced_memory()[0]
                tracemalloc.stop()
                report["memory"].append(
                    dict(
                        shape=shape,
                        mode=mode,
                        variant=name,
                        rawBytes=len(candidate.payload[9]),
                        live=live,
                        peak=peak,
                        drained=drained,
                        retainedChain=chain,
                        wall=elapsed,
                        cpu=used,
                        processBefore=before,
                        processHeld=after,
                        processDrained=process_metrics(os.getpid()),
                    )
                )
                save()
        previous = c_benchmark.latest
        try:
            c_benchmark.latest = failure_boundary.latest
            admission = c_benchmark.sql_admission(row, args.output / (shape + ".sqlite3"))
        finally:
            c_benchmark.latest = previous
        assert admission["status"] == "availability_failed"
        assert admission["scan"]["payloadQueries"] == 0 and admission["ledger"]["used"] == 0
        report["admissions"].append(dict(shape=shape, **admission))
        del expected, row, invalid, candidate
        save()
    report["build"] = dict(
        binarySha256=hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
        buildInfo=native.build_info,
        buildProfile=native.build_profile,
        toolchain={name: shutil.which(name) for name in ("rustc", "cargo", "cl")},
        qualification="NOT_PROVEN: actual compiler/CRT/allocator and artifact binding missing",
    )
    report["nativeEnvelope"] = dict(
        status="NOT_PROVEN",
        missing=[
            "native allocator interception",
            "parser/error conversion allocation bounds",
            "driver/cast and encoder reallocations",
            "aggregate concurrent process ceiling",
        ],
        observation=(
            "Process snapshots include trace instrumentation and retained expected models; "
            "not peaks or bounds."
        ),
    )
    report["sourceSha256"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            Path(__file__).relative_to(Path.cwd()),
            Path(failure_boundary.__file__).relative_to(Path.cwd()),
        )
    }
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == fingerprints[str(p)] for p in paths)
    report["decision"] = "P1_NO_GO: native envelope and legal SQL availability fail"
    report["limits"] = (
        "3 CPU rounds; one traced pass per shape/mode/variant; prebuilt raw and expected "
        "excluded from trace. Failure GC is synchronous and included. "
        "No production integration or native allocation guarantee."
    )
    save()
    print(json.dumps(report["medians"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monitor", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
