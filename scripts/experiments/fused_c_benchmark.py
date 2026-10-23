"""Frozen-input diagnostics; no production registration or native-bound certification."""

import argparse
import gc
import hashlib
import importlib.metadata
import json
import platform
import sqlite3
import tracemalloc
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from statistics import median
from time import perf_counter, thread_time

from scripts.experiments import c_benchmark as reference
from scripts.experiments import fused_c_validator
from scripts.experiments import global_evidence_large as fixtures

from trade_plan_monitor.state.projections import _latest_index_records


def run(args):
    output = args.output
    output.mkdir(exist_ok=False)
    fingerprint = hashlib.sha256(args.monitor.read_bytes()).hexdigest()
    variants = [
        ("original", _latest_index_records),
        ("c256", reference.latest),
        ("fused", fused_c_validator.latest),
    ]
    rows = reference.rows_from(args.monitor)
    expected = _latest_index_records(iter(rows), reference.CODES)
    attempts = []
    for turn in range(3):
        for name, verify in variants if turn % 2 == 0 else variants[::-1]:
            gc.collect()
            start, cpu = perf_counter(), thread_time()
            result = verify(iter(rows), reference.CODES)
            wall, used = perf_counter() - start, thread_time() - cpu
            assert result == expected
            attempts.append(dict(round=turn + 1, variant=name, wall=wall, cpu=used, equal=True))
            del result
    del expected, rows
    report = dict(
        inputSha256=fingerprint,
        attempts=attempts,
        memory=[],
        admissions=[],
        medians={
            name: {
                k: median(r[k] for r in attempts if r["variant"] == name) for k in ("wall", "cpu")
            }
            for name, _ in variants
        },
    )
    # Checkpoint before the expensive traced/error runs; never silently discard timing.
    (output / "measurements.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    for label, count, digits in [("decimal", 480, 8500), ("dense", 40000, 1)]:
        zone = fixtures.ZoneInfo
        try:
            fixtures.ZoneInfo = lambda _: timezone(timedelta(hours=8))
            row = fixtures.large_candidate(count=count, digits=digits)
        finally:
            fixtures.ZoneInfo = zone
        expected = _latest_index_records(iter((row,)), reference.CODES)
        for name, verify in variants:
            gc.collect()
            tracemalloc.start()
            result = verify(iter((row,)), reference.CODES)
            live, peak = tracemalloc.get_traced_memory()
            assert result == expected
            del result
            gc.collect()
            drained = tracemalloc.get_traced_memory()[0]
            tracemalloc.stop()
            report["memory"].append(
                dict(
                    shape=label,
                    variant=name,
                    mode="success",
                    rawBytes=len(row.payload[9]),
                    live=live,
                    peak=peak,
                    drained=drained,
                    equal=True,
                )
            )
        # Deliberately retain the exception chain until explicit release.
        raw = row.payload[9].replace(b'"high_points":"1.', b'"high_points":"0.')
        assert raw != row.payload[9]
        payload = list(row.payload)
        payload[9] = raw
        invalid = replace(row, payload=tuple(payload))
        errors = []
        for name, verify in variants:
            gc.collect()
            tracemalloc.start()
            held = None
            try:
                verify(iter((invalid,)), reference.CODES)
            except Exception as error:
                held = error
            assert held is not None
            kind = type(held).__name__
            errors.append(kind)
            cause = held.__cause__
            count_errors = cause.error_count() if hasattr(cause, "error_count") else None
            live, peak = tracemalloc.get_traced_memory()
            del held, cause
            gc.collect()
            drained = tracemalloc.get_traced_memory()[0]
            tracemalloc.stop()
            report["memory"].append(
                dict(
                    shape=label,
                    variant=name,
                    mode="invalid_OHLC",
                    error=kind,
                    errorCount=count_errors,
                    live=live,
                    peak=peak,
                    drained=drained,
                )
            )
        assert len(set(errors)) == 1
        # Native qualification is absent: keep the existing conservative reservation.
        previous = reference.latest
        try:
            reference.latest = fused_c_validator.latest
            admission = reference.sql_admission(row, output / (label + ".sqlite3"))
        finally:
            reference.latest = previous
        assert admission["status"] == "availability_failed"
        assert admission["scan"]["payloadQueries"] == 0 and admission["ledger"]["used"] == 0
        report["admissions"].append(dict(shape=label, **admission))
        del expected, row, raw, payload, invalid
        (output / "measurements.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    import pydantic_core

    native = Path(pydantic_core.__file__).parent
    report["provenance"] = dict(
        python=platform.python_version(),
        sqlite=sqlite3.sqlite_version,
        packages={
            n: importlib.metadata.version(n) for n in ("pydantic", "pydantic-core", "SQLAlchemy")
        },
        nativeBinarySha256={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in native.glob("*.pyd")
        },
        bundledRustSourceCount=len(list(native.rglob("*.rs"))),
        qualification=(
            "NOT_PROVEN: installed binary identity is not matching native allocation source/proof"
        ),
    )
    report["sourceSha256"] = {
        str(p).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            Path(__file__).relative_to(Path.cwd()),
            Path(fused_c_validator.__file__).relative_to(Path.cwd()),
        ]
    }
    assert hashlib.sha256(args.monitor.read_bytes()).hexdigest() == fingerprint
    report["decision"] = "P1_NO_GO; native qualification and legal-row SQL availability fail"
    report["limits"] = (
        "3 diagnostic rounds, no SQL in CPU. Single traced full-validator/error pass per "
        "shape/variant excludes prebuilt raw and expected outputs. Native allocator transients/"
        "absolute process peaks remain unproven; no reduced admission or browser integration."
    )
    (output / "measurements.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report["medians"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monitor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
