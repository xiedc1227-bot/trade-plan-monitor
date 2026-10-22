"""Read-only conservative SQL batch accounting; not a concurrent RSS measurement."""

import argparse
import json
from pathlib import Path
from sys import getsizeof

from scripts.experiments.bounded_allocation_probe import load_rows
from scripts.experiments.bounded_benchmark import frozen_engine
from scripts.experiments.bounded_codec import LIMIT, RESERVE, AdmissionError, plan
from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, PAYLOAD_FIELDS
from trade_plan_monitor.state.models import MarketIndexSnapshot, MarketIndexSnapshotHead


def main(args):
    head, payload = MarketIndexSnapshotHead.__table__, MarketIndexSnapshot.__table__
    query = select(*(head.c[f] for f in HEAD_FIELDS), *(payload.c[f] for f in PAYLOAD_FIELDS))
    query = query.select_from(head).outerjoin(
        payload, head.c.snapshot_hash == payload.c.snapshot_hash,
    )
    query = query.order_by(head.c.mapping_version, head.c.index_code, head.c.decision_cutoff,
                           head.c.request_set_hash).execution_options(yield_per=128)
    engine = frozen_engine(args.monitor)
    batches = []
    previous = -1
    with Session(engine) as session, session.execute(query) as result:
        for position, row in enumerate(result):
            # Observe the actual DBAPI result buffer before it is advanced again.
            buffer = result.cursor_strategy._rowbuffer
            if len(buffer) > previous:
                values = [tuple(row), *buffer]
                retained = getsizeof(values) + sum(
                    getsizeof(v) + sum(getsizeof(s) for s in v) for v in values
                )
                batches.append(dict(first=position, rows=len(values), conservativeBytes=retained))
            previous = len(buffer)
    engine.dispose()
    rows = load_rows(args.monitor)
    maximum = max(b['conservativeBytes'] for b in batches)
    raw = sum(r.retained_size() for r in rows)
    variants = []
    for followers in (0, 1, 7):
        external = followers * maximum
        try:
            admission = plan(rows, external_bytes=external)
            variants.append(dict(followers=followers, admitted=True, bytes=admission.reserved))
        except AdmissionError:
            variants.append(dict(followers=followers, admitted=False,
                                 bytes=raw+RESERVE+external))
    report = dict(scope='Actual SQL batch geometry with conservative repeated-scalar accounting; '
                        'simultaneous follower envelopes are arithmetic, not observed RSS.',
                  rawBytes=raw, limitBytes=LIMIT, reserveBytes=RESERVE, batches=batches,
                  maximumSqlBatchBytes=maximum, admissions=variants)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monitor', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
