"""Automatic-GC diagnostics; scope-only capture never authorizes a lease refund."""

import argparse
import gc
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from statistics import median
from time import perf_counter, thread_time

from scripts.experiments import c_benchmark, failure_boundary

from trade_plan_monitor.state.projections import ProjectionError, ProjectionMissingDependencyError


def scope_diagnostic(rows, codes):
    # Only the child harness may use this: its final collection retains cleanup responsibility.
    outcome = failure_boundary._capture(rows, codes, lambda *a: None, {})
    if isinstance(outcome, failure_boundary.Failure):
        if outcome.missing:
            raise ProjectionMissingDependencyError("missing immutable snapshot")
        raise ProjectionError("Stored market-index snapshot is invalid")
    return outcome


def child(fixtures, shape, variant):
    path = fixtures / (shape + ".sqlite3")
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    (row,) = c_benchmark.rows_from(path)
    payload = list(row.payload)
    payload[9] = payload[9].replace(b'"high_points":"1.', b'"high_points":"0.')
    assert payload[9] != row.payload[9]
    invalid = replace(row, payload=tuple(payload))
    del row, payload
    gc.collect()
    assert gc.isenabled()
    verify = scope_diagnostic if variant == "scope" else failure_boundary.latest
    cpu, wall = thread_time(), perf_counter()
    for _ in range(3):
        try:
            verify(iter((invalid,)), c_benchmark.CODES)
        except ProjectionError:
            pass
        else:
            raise AssertionError("invalid evidence accepted")
    validation_cpu = thread_time() - cpu
    cleanup_cpu = thread_time()
    collected = gc.collect()
    cleanup_cpu = thread_time() - cleanup_cpu
    result = dict(
        shape=shape,
        variant=variant,
        calls=3,
        validationCpu=validation_cpu,
        finalCleanupCpu=cleanup_cpu,
        totalCpu=thread_time() - cpu,
        totalWall=perf_counter() - wall,
        collected=collected,
        automaticGc=gc.isenabled(),
        inputSha256=fingerprint,
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == fingerprint
    return result


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(
        attempts=[],
        qualification="DIAGNOSTIC_ONLY",
        limits=(
            "3 rounds; 3 calls per fresh child; automatic GC on; final full collection "
            "included for both variants. Scope variant retains cleanup obligation until "
            "that endpoint. No caller-frame, native-bound or concurrency qualification."
        ),
    )
    report["sourceSha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def save():
        temporary = args.output / "measurements.tmp"
        temporary.write_text(json.dumps(report, indent=2), encoding="utf8")
        temporary.replace(args.output / "measurements.json")

    save()
    try:
        for shape in ("decimal", "dense"):
            for turn in range(3):
                for variant in ("full", "scope") if turn % 2 == 0 else ("scope", "full"):
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            __spec__.name,
                            "--child",
                            "--fixtures",
                            str(args.fixtures),
                            "--shape",
                            shape,
                            "--variant",
                            variant,
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=90,
                    )
                    report["attempts"].append(dict(round=turn + 1, **json.loads(result.stdout)))
                    save()
        report["medians"] = [
            dict(
                shape=shape,
                variant=variant,
                totalCpu=median(
                    a["totalCpu"]
                    for a in report["attempts"]
                    if a["shape"] == shape and a["variant"] == variant
                ),
            )
            for shape in ("decimal", "dense")
            for variant in ("full", "scope")
        ]
        report["admissions"] = []
        for shape in ("decimal", "dense"):
            (row,) = c_benchmark.rows_from(args.fixtures / (shape + ".sqlite3"))
            # Full validation precedes admission diagnostics, not an admission bypass.
            failure_boundary.latest(iter((row,)), c_benchmark.CODES)
            report["admissions"].append(
                dict(
                    shape=shape,
                    **c_benchmark.sql_admission(row, args.output / (shape + ".sqlite3")),
                )
            )
    except Exception as error:
        report["failure"] = dict(kind=type(error).__name__, message=str(error))
        raise
    finally:
        save()
    print(json.dumps(report["medians"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--shape", choices=("decimal", "dense"))
    parser.add_argument("--variant", choices=("full", "scope"))
    args = parser.parse_args()
    if args.child:
        print(json.dumps(child(args.fixtures, args.shape, args.variant)))
    else:
        if args.output is None:
            parser.error("--output required")
        run(args)
