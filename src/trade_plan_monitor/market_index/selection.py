"""Effective display selection; never changes an attempted plan input."""

from datetime import datetime

from trade_plan_monitor.market_index.models import MarketIndexHealth, MarketIndexSnapshot


def snapshot_rank(snapshot: MarketIndexSnapshot) -> tuple:
    """Prefer target, valid data and capture order; revisions are opaque identities."""
    return (
        snapshot.decision_cutoff,
        snapshot.health is MarketIndexHealth.LIVE,
        len(snapshot.fact_requests),
        snapshot.observed_at,
        snapshot.snapshot_hash,
    )


def retain_effective_snapshot(
    current: MarketIndexSnapshot,
    incoming: MarketIndexSnapshot,
    *,
    current_observed_at: datetime | None = None,
    incoming_observed_at: datetime | None = None,
) -> bool:
    """Retain by capture time, including captures reusing an immutable payload."""
    if (
        current.mapping_version,
        current.index_code,
        current.decision_cutoff,
        current.request_set_hash,
    ) != (
        incoming.mapping_version,
        incoming.index_code,
        incoming.decision_cutoff,
        incoming.request_set_hash,
    ):
        raise ValueError("effective selection requires the same snapshot key")
    current_capture_time = (
        current.observed_at if current_observed_at is None else current_observed_at
    )
    incoming_capture_time = (
        incoming.observed_at if incoming_observed_at is None else incoming_observed_at
    )
    return (
        current.health is MarketIndexHealth.LIVE and incoming.health is not MarketIndexHealth.LIVE
    ) or incoming_capture_time < current_capture_time
