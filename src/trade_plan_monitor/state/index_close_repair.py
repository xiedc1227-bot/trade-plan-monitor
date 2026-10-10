"""Idempotent startup repair; immutable captures and decision references stay intact."""

from datetime import datetime, time

from trade_plan_monitor.market_index.identity import MAPPING_VERSION
from trade_plan_monitor.runtime.market_indexes import ALWAYS_ON_INDEX_CODES
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
    monitor_event_id,
)


def repair_current_index_display(work, *, now: datetime) -> tuple[int, int]:
    days = work.references.list_trading_days("SSE", now.date(), now.date())
    trade_date = now.date()
    if days and (not days[0].is_open or now.time() < time(9, 30)):
        from datetime import timedelta

        previous = work.references.list_trading_days(
            "SSE", now.date() - timedelta(days=366), now.date()
        )
        trade_date = max(
            (day.cal_date for day in previous if day.is_open and day.cal_date < now.date()),
            default=trade_date,
        )
    backfilled = work.projections.backfill_market_index_acquisitions(
        trade_date=trade_date, mapping_version=MAPPING_VERSION
    )
    repaired = work.projections.repair_market_index_heads(
        trade_date=trade_date, mapping_version=MAPPING_VERSION
    )
    if repaired:
        for record in work.projections.list_latest_market_index_snapshots(
            mapping_version=MAPPING_VERSION,
            index_codes=ALWAYS_ON_INDEX_CODES,
        ):
            snapshot = record.snapshot
            if snapshot.decision_cutoff.date() != trade_date:
                continue
            work.events.append(
                MonitorEventDraft(
                    event_id=monitor_event_id(
                        MonitorEventType.MARKET_INDEX_UPDATED,
                        snapshot.index_code.value,
                        "effective-head-repair-v1",
                        snapshot.snapshot_hash,
                    ),
                    event_type=MonitorEventType.MARKET_INDEX_UPDATED,
                    aggregate_id=snapshot.index_code.value,
                    payload=MonitorEventPayload(
                        entity_id=snapshot.index_code.value,
                        revision=snapshot.revision,
                        status=snapshot.health.value,
                    ),
                    occurred_at=now,
                )
            )
    return repaired, backfilled
