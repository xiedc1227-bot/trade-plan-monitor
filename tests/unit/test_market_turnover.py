"""Deterministic Shanghai/Shenzhen market-turnover summary tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexHealth,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSnapshot,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.market_index.turnover import (
    build_market_turnover_summary,
    completed_market_turnover_bucket_count,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADE_DATE = datetime(2026, 9, 10, tzinfo=SHANGHAI).date()
OBSERVED_AT = datetime(2026, 9, 10, 10, 0, 2, tzinfo=SHANGHAI)


def _bucket_ends(count: int, *, days_ago: int = 0) -> tuple[datetime, ...]:
    trade_day = datetime(2026, 9, 10, tzinfo=SHANGHAI) - timedelta(days=days_ago)
    morning = tuple(
        trade_day.replace(hour=9, minute=35) + timedelta(minutes=5 * index)
        for index in range(24)
    )
    afternoon = tuple(
        trade_day.replace(hour=13, minute=5) + timedelta(minutes=5 * index)
        for index in range(24)
    )
    return (morning + afternoon)[:count]


def _snapshot(
    index_code: MarketIndexCode,
    *,
    amount_per_bucket: str,
    bucket_count: int = 6,
    prior_amount: str,
    prior_days_ago: int = 1,
    previous_amount_per_bucket: str | None = None,
) -> MarketIndexSnapshot:
    bucket_ends = _bucket_ends(bucket_count)
    observed_at = bucket_ends[-1] + timedelta(seconds=2)
    previous_bucket_amount = (
        Decimal(prior_amount) / Decimal(48)
        if previous_amount_per_bucket is None
        else Decimal(previous_amount_per_bucket)
    )
    minute_values = tuple(
        (bar_at, previous_bucket_amount)
        for bar_at in _bucket_ends(48, days_ago=prior_days_ago)
    ) + tuple((bar_at, Decimal(amount_per_bucket)) for bar_at in bucket_ends)
    five_minute_bars = tuple(
        MarketIndexBar(
            index_code=index_code,
            interval=MarketIndexInterval.FIVE_MINUTE,
            bar_at=bar_at,
            open_points=Decimal("100"),
            high_points=Decimal("101"),
            low_points=Decimal("99"),
            close_points=Decimal("100"),
            volume=Decimal("10"),
            amount=amount,
            observed_at=observed_at,
            source_kind=MarketIndexSourceKind.PROVISIONAL,
            provider_revision=3,
        )
        for bar_at, amount in minute_values
    )
    previous_close = datetime(2026, 9, 10, 15, 0, tzinfo=SHANGHAI) - timedelta(
        days=prior_days_ago
    )
    daily = MarketIndexBar(
        index_code=index_code,
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        bar_at=previous_close,
        open_points=Decimal("100"),
        high_points=Decimal("101"),
        low_points=Decimal("99"),
        close_points=Decimal("100"),
        volume=Decimal("100"),
        amount=Decimal(prior_amount),
        observed_at=observed_at,
        source_kind=MarketIndexSourceKind.OFFICIAL,
        provider_revision=3,
    )
    return build_market_index_snapshot(
        index_code=index_code,
        decision_cutoff=bucket_ends[-1],
        requests=(),
        five_minute_bars=five_minute_bars,
        official_daily_bars=(daily,),
        content_revision=3,
        observed_at=observed_at,
        observed_no_later_than=observed_at,
    )


def test_compares_current_turnover_with_the_previous_trading_day_at_the_same_cutoff() -> None:
    summary = build_market_turnover_summary(
        (
            _snapshot(
                MarketIndexCode.SSE_COMPOSITE,
                amount_per_bucket="100",
                prior_amount="1000",
                previous_amount_per_bucket="80",
            ),
            _snapshot(
                MarketIndexCode.SHENZHEN_A_SHARE,
                amount_per_bucket="200",
                prior_amount="2000",
                previous_amount_per_bucket="160",
            ),
        )
    )

    assert summary is not None
    assert summary.current_amount == Decimal("1800")
    assert summary.previous_amount == Decimal("1440")
    assert summary.change_amount == Decimal("360")
    assert summary.estimated_full_day_amount == Decimal("14400")
    assert summary.completed_bucket_at == datetime(2026, 9, 10, 10, 0, tzinfo=SHANGHAI)
    assert summary.estimate_method == "LINEAR_COMPLETED_FIVE_MINUTE_BUCKETS"
    assert summary.benchmark_codes == ("000001.SH", "399107.SZ")


def test_close_estimate_equals_actual_turnover() -> None:
    summary = build_market_turnover_summary(
        (
            _snapshot(
                MarketIndexCode.SSE_COMPOSITE,
                amount_per_bucket="100",
                bucket_count=48,
                prior_amount="4000",
            ),
            _snapshot(
                MarketIndexCode.SHENZHEN_A_SHARE,
                amount_per_bucket="200",
                bucket_count=48,
                prior_amount="8000",
            ),
        )
    )

    assert summary is not None
    assert summary.current_amount == Decimal("14400")
    assert summary.estimated_full_day_amount == summary.current_amount


def test_uses_last_complete_aligned_bucket_during_one_bucket_publication_lag() -> None:
    sse = _snapshot(
        MarketIndexCode.SSE_COMPOSITE,
        amount_per_bucket="100",
        prior_amount="1000",
    )
    shenzhen = _snapshot(
        MarketIndexCode.SHENZHEN_A_SHARE,
        amount_per_bucket="200",
        prior_amount="2000",
    )
    delayed_cutoff = sse.decision_cutoff + timedelta(minutes=5)
    delayed = tuple(
        snapshot.model_copy(
            update={
                "decision_cutoff": delayed_cutoff,
                "health": MarketIndexHealth.STALE,
                "issues": (MarketIndexIssueCode.STALE_DATA,),
            }
        )
        for snapshot in (sse, shenzhen)
    )

    summary = build_market_turnover_summary(delayed)

    assert summary is not None
    assert summary.current_amount == Decimal("1800")
    assert summary.completed_bucket_at == sse.completed_bucket_at


def test_completed_bucket_count_covers_lunch_break_and_close() -> None:
    assert completed_market_turnover_bucket_count(
        datetime(2026, 9, 10, 10, 35, tzinfo=SHANGHAI)
    ) == 13
    assert completed_market_turnover_bucket_count(
        datetime(2026, 9, 10, 11, 30, tzinfo=SHANGHAI)
    ) == 24
    assert completed_market_turnover_bucket_count(
        datetime(2026, 9, 10, 15, 0, tzinfo=SHANGHAI)
    ) == 48


def test_rejects_incomplete_or_non_live_benchmark_data() -> None:
    sse = _snapshot(
        MarketIndexCode.SSE_COMPOSITE,
        amount_per_bucket="100",
        prior_amount="1000",
    )
    shenzhen = _snapshot(
        MarketIndexCode.SHENZHEN_A_SHARE,
        amount_per_bucket="200",
        prior_amount="2000",
    )
    gapped = shenzhen.model_copy(
        update={"five_minute_bars": shenzhen.five_minute_bars[1:]}
    )
    blocked = shenzhen.model_copy(
        update={
            "health": MarketIndexHealth.BLOCKED,
            "issues": ("PROVIDER_UNAVAILABLE",),
        }
    )

    assert build_market_turnover_summary((sse, gapped)) is None
    assert build_market_turnover_summary((sse, blocked)) is None


def test_rejects_benchmark_snapshots_from_different_cutoffs() -> None:
    sse = _snapshot(
        MarketIndexCode.SSE_COMPOSITE,
        amount_per_bucket="100",
        prior_amount="1000",
    )
    shenzhen = _snapshot(
        MarketIndexCode.SHENZHEN_A_SHARE,
        amount_per_bucket="200",
        prior_amount="2000",
    )

    assert build_market_turnover_summary(
        (
            sse,
            shenzhen.model_copy(
                update={
                    "decision_cutoff": shenzhen.decision_cutoff + timedelta(minutes=5)
                }
            ),
        )
    ) is None


def test_rejects_previous_amounts_from_different_trading_days() -> None:
    assert build_market_turnover_summary(
        (
            _snapshot(
                MarketIndexCode.SSE_COMPOSITE,
                amount_per_bucket="100",
                prior_amount="1000",
            ),
            _snapshot(
                MarketIndexCode.SHENZHEN_A_SHARE,
                amount_per_bucket="200",
                prior_amount="2000",
                prior_days_ago=2,
            ),
        )
    ) is None
