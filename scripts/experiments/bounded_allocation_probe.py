"""Separate allocation-profile run, explicitly excluded from latency measurements."""

import argparse
import gc
import json
import sqlite3
import tracemalloc
from pathlib import Path

from scripts.experiments import bounded_transport
from scripts.experiments.bounded_codec import plan

from trade_plan_monitor.runtime.market_indexes import ALWAYS_ON_INDEX_CODES
from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, PAYLOAD_FIELDS, RawIndexCandidate
from trade_plan_monitor.state.projections import _latest_index_records


def profiled_child(connection, generation):
    original = bounded_transport._job

    def profile(*args):
        gc.collect()
        tracemalloc.start()
        result = original(*args)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return dict(result, tracedChildCurrentBytes=current, tracedChildPeakBytes=peak)
    bounded_transport._job = profile
    bounded_transport._worker(connection, generation)


def load_rows(path):
    connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON')
    columns = ','.join(['h.'+f for f in HEAD_FIELDS]+['p.'+f for f in PAYLOAD_FIELDS])
    query = ('select '+columns+' from market_index_snapshot_head h left join '
             'market_index_snapshot p on h.snapshot_hash=p.snapshot_hash order by '
             'h.mapping_version,h.index_code,h.decision_cutoff,h.request_set_hash')
    try:
        rows = []
        for values in connection.execute(query):
            payload = tuple(values[len(HEAD_FIELDS):])
            rows.append(RawIndexCandidate.from_values(
                tuple(values[:len(HEAD_FIELDS)]), None if payload[0] is None else payload,
            ))
        return tuple(rows)
    finally:
        connection.close()


def main(args):
    rows = load_rows(args.monitor)
    expected = _latest_index_records(iter(rows), ALWAYS_ON_INDEX_CODES)
    admission = plan(rows)
    original = bounded_transport._worker
    bounded_transport._worker = profiled_child
    report = dict(scope='Profiled Python allocations only; excludes latency and kernel memory.',
                  rawBytes=admission.raw_bytes, reservedBytes=admission.reserved,
                  chunks=len(admission.chunks), runs=[])
    try:
        with bounded_transport.ChunkWorker() as worker:
            for _ in range(3):
                gc.collect()
                tracemalloc.start()
                result = worker.validate(rows, ALWAYS_ON_INDEX_CODES)
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                assert result == expected
                report['runs'].append(dict(parentCurrentBytes=current, parentPeakBytes=peak,
                                           proof=worker.last))
                del result
                assert worker.retained_bytes == 0
    finally:
        bounded_transport._worker = original
    args.output.write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monitor', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    main(parser.parse_args())
