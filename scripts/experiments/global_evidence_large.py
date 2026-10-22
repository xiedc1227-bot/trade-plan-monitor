"""Reproducible valid large evidence; raw payloads stay in the local test workspace."""

import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from scripts.experiments.global_evidence_scan import COLUMNS, shape

from trade_plan_monitor.market_index.canonical import verified_market_index_snapshot_json
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.runtime.market_indexes import DASHBOARD_INDEX_CODES
from trade_plan_monitor.state.index_evidence import RawIndexCandidate
from trade_plan_monitor.state.projections import _latest_index_records, _market_index_values


def large_candidate(count=480, digits=8500):
    now = datetime(2026, 10, 22, 16, tzinfo=ZoneInfo('Asia/Shanghai'))
    price = Decimal('1.'+'1'*digits)
    bars = tuple(MarketIndexBar(
        index_code=DASHBOARD_INDEX_CODES[0], interval=MarketIndexInterval.OFFICIAL_DAILY,
        bar_at=datetime.combine((now-timedelta(days=count-i)).date(), time(15), now.tzinfo),
        open_points=price, high_points=price, low_points=price, close_points=price,
        observed_at=now, source_kind=MarketIndexSourceKind.OFFICIAL, provider_revision=1,
    ) for i in range(count))
    value = build_market_index_snapshot(
        index_code=DASHBOARD_INDEX_CODES[0], decision_cutoff=now, requests=(),
        five_minute_bars=(), official_daily_bars=bars, content_revision=1,
        observed_at=now, observed_no_later_than=now,
    )
    payload = SimpleNamespace(**_market_index_values(
        value, 1, verified_market_index_snapshot_json(value),
    ))
    head = SimpleNamespace(
        mapping_version=value.mapping_version, index_code=value.index_code.value,
        decision_cutoff=value.decision_cutoff.isoformat(), request_set_hash=value.request_set_hash,
        provider_content_revision=1, snapshot_hash=value.snapshot_hash, updated_at=now.isoformat(),
    )
    return RawIndexCandidate.capture(head, payload)


def main():
    row = large_candidate()
    original = _latest_index_records(iter((row,)), DASHBOARD_INDEX_CODES)
    metadata = [1, 1]
    for i, value in enumerate((*row.head, *row.payload)):
        if i == 16:
            metadata.extend(('text', len(value)))
        elif type(value) is int:
            metadata.extend(('integer', len(str(value))))
        else:
            metadata.extend(('text', len(value.encode('utf8'))))
    assert len(metadata) == 2+2*len(COLUMNS)
    bound = shape(metadata)
    report = dict(jsonBytes=len(row.payload[9]), originalAccepted=bool(original),
                  belowWriteLimit=len(row.payload[9]) <= 16*1024*1024,
                  workBound=bound.work, rawBound=bound.raw, limit=64*1024*1024,
                  gate='FAIL' if bound.work > 64*1024*1024 else 'PASS')
    Path('.pytest_cache/global-admission/large-row.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
