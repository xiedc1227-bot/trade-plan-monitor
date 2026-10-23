"""P0 diagnostic with frozen read-only input and locally generated large rows."""

import argparse
import gc
import hashlib
import json
import sqlite3
import tracemalloc
from datetime import timedelta, timezone
from pathlib import Path
from statistics import median
from time import perf_counter, thread_time

from scripts.experiments import global_evidence_large as fixtures
from scripts.experiments.bounded_benchmark import frozen_engine
from scripts.experiments.c_validator import latest
from scripts.experiments.evidence_representation import OrderedScan
from scripts.experiments.global_evidence_budget import Budget, BudgetUnavailable
from scripts.experiments.global_evidence_scan import COLUMNS, FROM, ORDER
from scripts.experiments.validator_scan import latest as iterative

from trade_plan_monitor.runtime.market_indexes import ALWAYS_ON_INDEX_CODES as CODES
from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, PAYLOAD_FIELDS, RawIndexCandidate
from trade_plan_monitor.state.projections import _latest_index_records


def rows_from(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as con:
        con.execute("pragma query_only=on")
        con.execute("begin")
        mapping = con.execute(
            "select mapping_version from market_index_snapshot_head limit 1"
        ).fetchone()[0]
        query = (
            "select "
            + ",".join(COLUMNS)
            + FROM
            + " where h.mapping_version=? and h.index_code in ("
            + ",".join("?" for _ in CODES)
            + ")"
            + ORDER
        )
        return tuple(
            RawIndexCandidate.from_values(tuple(v[:7]), tuple(v[7:]))
            for v in con.execute(query, (mapping, *(c.value for c in CODES)))
        )


def sql_admission(row, path):
    with sqlite3.connect(path) as con:
        for table, fields in [
            ("market_index_snapshot_head", HEAD_FIELDS),
            ("market_index_snapshot", PAYLOAD_FIELDS),
        ]:
            con.execute("create table " + table + " (" + ",".join(fields) + ")")
        payload = list(row.payload)
        payload[9] = payload[9].decode()
        for table, values in [
            ("market_index_snapshot_head", row.head),
            ("market_index_snapshot", payload),
        ]:
            con.execute(
                "insert into " + table + " values (" + ",".join("?" for _ in values) + ")", values
            )
    engine, budget = frozen_engine(path), Budget()
    with engine.connect() as con, con.begin():
        scan = OrderedScan(con, budget, row.head[0], CODES)
        with scan.metadata():
            raw, work, count = scan.measure()
            try:
                with scan.acquire(work, "scan") as lease:
                    latest(scan.rows(lease), CODES, budget=budget)
                status = "accepted"
            except BudgetUnavailable:
                status = "availability_failed"
    engine.dispose()
    budget.drain()
    return dict(
        raw=raw, work=work, rows=count, status=status, scan=scan.stats, ledger=budget.snapshot()
    )


def run(args):
    fingerprint = hashlib.sha256(args.monitor.read_bytes()).hexdigest()
    rows = rows_from(args.monitor)
    expected = _latest_index_records(iter(rows), CODES)
    attempts = []
    variants = [
        ("original", _latest_index_records),
        ("iterative", iterative),
        ("c64", lambda r, c: latest(r, c, target=65536)),
        ("c256", latest),
    ]
    for number in range(3):
        for name, verify in variants if number % 2 == 0 else variants[::-1]:
            gc.collect()
            started, cpu = perf_counter(), thread_time()
            result = verify(iter(rows), CODES)
            wall, used = perf_counter() - started, thread_time() - cpu
            assert result == expected
            attempts.append(dict(round=number + 1, variant=name, wall=wall, cpu=used, equal=True))
            del result
    del rows, expected
    memory, admissions = [], []
    for label, count, digits in (
        [] if args.cpu_only else [("decimal", 480, 8500), ("dense", 40000, 1)]
    ):
        old_zone = fixtures.ZoneInfo
        try:
            fixtures.ZoneInfo = lambda _: timezone(timedelta(hours=8))
            row = fixtures.large_candidate(count=count, digits=digits)
        finally:
            fixtures.ZoneInfo = old_zone
        expected = _latest_index_records(iter((row,)), CODES)
        for name, verify in (variants[0], variants[-1]):
            gc.collect()
            tracemalloc.start()
            result = verify(iter((row,)), CODES)
            live, peak = tracemalloc.get_traced_memory()
            assert result == expected
            del result
            gc.collect()
            drained = tracemalloc.get_traced_memory()[0]
            tracemalloc.stop()
            memory.append(
                dict(
                    shape=label,
                    variant=name,
                    jsonBytes=len(row.payload[9]),
                    live=live,
                    peak=peak,
                    drained=drained,
                    equal=True,
                )
            )
        admissions.append(
            dict(
                shape=label,
                **sql_admission(row, args.output.parent / (label + "-admission.sqlite3")),
            )
        )
        del row, expected
    assert hashlib.sha256(args.monitor.read_bytes()).hexdigest() == fingerprint
    report = dict(
        inputSha256=fingerprint,
        attempts=attempts,
        memory=memory,
        admissions=admissions,
        medians={
            name: {
                k: median(r[k] for r in attempts if r["variant"] == name) for k in ("wall", "cpu")
            }
            for name, _ in variants
        },
        limits=(
            "3 diagnostic rounds; memory is one traced full-validator pass per shape/variant, "
            "excludes prebuilt raw and expected output and untracked native allocations. "
            "No production integration or native-bound claim."
        ),
    )
    args.output.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report["medians"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monitor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-only", action="store_true")
    run(parser.parse_args())
