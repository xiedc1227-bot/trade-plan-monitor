"""Read-only fence against independently published index corrections."""

from trade_plan_monitor.market_index.canonical import canonical_json, linked_index_bar_content
from trade_plan_monitor.market_index.models import MarketIndexSnapshot
from trade_plan_monitor.state.projections import ProjectionRepository


def linked_index_current(session, evaluation, now):
    """Check the consumed bars, not unrelated intraday ticks or polling timestamps."""
    decisions = evaluation.get("market_linkage")
    if not decisions:
        return True
    raw = evaluation.get("linked_index_source")
    if raw is None:
        return False
    try:
        source = MarketIndexSnapshot.model_validate_json(canonical_json(raw))
        records = ProjectionRepository(session).list_latest_market_index_snapshots(
            mapping_version=source.mapping_version, index_codes=(source.index_code,)
        )
        if len(records) != 1:
            return False
        current = records[0].snapshot
        if current.observed_at > now:
            return False
        available = {bar.bar_at: bar for bar in current.official_daily_bars}
        consumed = source.official_daily_bars
        return bool(consumed) and all(
            bar.bar_at in available
            and available[bar.bar_at].observed_at <= now
            and linked_index_bar_content(available[bar.bar_at]) == linked_index_bar_content(bar)
            for bar in consumed
        )
    except ValueError, TypeError:
        return False
