"""Isolated full-validator diagnostic; no service dependency installation."""

import argparse
import ctypes
import gc
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter, thread_time

import pydantic_core._pydantic_core as core
from scripts.experiments import c_benchmark, failure_boundary

from trade_plan_monitor.state.projections import ProjectionError, _latest_index_records


def run(fixtures, output):
    output.mkdir(parents=True, exist_ok=False)
    report = dict(
        nativePath=core.__file__,
        nativeSha256=hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),
        cases=[],
        qualification="DIAGNOSTIC_ONLY",
    )
    dll = ctypes.CDLL(core.__file__)
    try:
        stat = dll.tpm_allocation_stat
    except AttributeError:
        stat = None
    if stat:
        stat.argtypes = [ctypes.c_size_t]
        stat.restype = ctypes.c_size_t

    def snapshot():
        return [stat(i) for i in range(4)] if stat else None

    try:
        before = snapshot()
        python_only = bytearray(8 * 1024 * 1024)
        report["pythonDomainControl"] = dict(
            before=before, during=snapshot(), bytes=len(python_only)
        )
        del python_only
        for shape in ("decimal", "dense"):
            path = fixtures / (shape + ".sqlite3")
            fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
            (row,) = c_benchmark.rows_from(path)
            expected = _latest_index_records(iter((row,)), c_benchmark.CODES)
            gc.collect()
            before = snapshot()
            cpu, wall = thread_time(), perf_counter()
            actual = failure_boundary.latest(iter((row,)), c_benchmark.CODES)
            used, elapsed = thread_time() - cpu, perf_counter() - wall
            assert actual == expected
            encoded = repr(actual).encode()
            del actual, expected
            gc.collect()
            valid_stats = snapshot()
            payload = list(row.payload)
            payload[9] = payload[9].replace(b'"high_points":"1.', b'"high_points":"0.')
            assert payload[9] != row.payload[9]
            invalid = replace(row, payload=tuple(payload))
            try:
                failure_boundary.latest(iter((invalid,)), c_benchmark.CODES)
            except ProjectionError:
                rejected = True
            else:
                raise AssertionError("tampered evidence accepted")
            del invalid, payload
            gc.collect()
            admission = c_benchmark.sql_admission(row, output / (shape + ".sqlite3"))
            del row
            gc.collect()
            report["cases"].append(
                dict(
                    shape=shape,
                    inputSha256=fingerprint,
                    outputSha256=hashlib.sha256(encoded).hexdigest(),
                    cpu=used,
                    wall=elapsed,
                    before=before,
                    afterValidRelease=valid_stats,
                    afterPhysicalRelease=snapshot(),
                    tamperRejected=rejected,
                    admission=admission,
                )
            )
            assert hashlib.sha256(path.read_bytes()).hexdigest() == fingerprint
        if stat and stat(3):
            raise AssertionError("allocation accounting loss")
    except Exception as error:
        report["failure"] = repr(error)
        raise
    finally:
        (output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.fixtures, args.output)
