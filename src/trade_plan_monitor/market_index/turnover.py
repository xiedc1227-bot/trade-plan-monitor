"""Deterministic whole-market turnover summary from certified index benchmarks."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexHealth,
    MarketIndexIssueCode,
    MarketIndexSnapshot,
)

MARKET_TURNOVER_INDEX_CODES = (
    MarketIndexCode.SSE_COMPOSITE,
    MarketIndexCode.SHENZHEN_A_SHARE,
)
MARKET_TURNOVER_BUCKET_COUNT = 48

FiniteAmount = Annotated[Decimal, Field(strict=True, allow_inf_nan=False)]
NonNegativeAmount = Annotated[Decimal, Field(strict=True, ge=0, allow_inf_nan=False)]


class MarketTurnoverSummary(BaseModel):
    """One fail-closed Shanghai plus Shenzhen A-share turnover result."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    current_amount: NonNegativeAmount
    previous_amount: NonNegativeAmount
    change_amount: FiniteAmount
    estimated_full_day_amount: NonNegativeAmount
    completed_bucket_at: AwareDatetime
    estimate_method: Literal["LINEAR_COMPLETED_FIVE_MINUTE_BUCKETS"] = (
        "LINEAR_COMPLETED_FIVE_MINUTE_BUCKETS"
    )
    benchmark_codes: tuple[Literal["000001.SH"], Literal["399107.SZ"]] = (
        "000001.SH",
        "399107.SZ",
    )

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.completed_bucket_at.utcoffset() != timedelta(hours=8):
            raise ValueError("turnover cutoff must use the Asia/Shanghai offset")
        if self.change_amount != self.current_amount - self.previous_amount:
            raise ValueError("turnover change must equal current minus previous")
        return self


def build_market_turnover_summary(
    snapshots: tuple[MarketIndexSnapshot, ...],
) -> MarketTurnoverSummary | None:
    """Return a summary when both benchmarks share one complete usable cutoff."""

    if type(snapshots) is not tuple or any(
        type(snapshot) is not MarketIndexSnapshot for snapshot in snapshots
    ):
        raise TypeError("snapshots must be a tuple of MarketIndexSnapshot values")
    by_code = {snapshot.index_code: snapshot for snapshot in snapshots}
    if set(by_code) != set(MARKET_TURNOVER_INDEX_CODES):
        return None
    selected = tuple(by_code[code] for code in MARKET_TURNOVER_INDEX_CODES)
    if any(not _is_turnover_snapshot_usable(snapshot) for snapshot in selected):
        return None
    decision_cutoffs = {snapshot.decision_cutoff for snapshot in selected}
    if len(decision_cutoffs) != 1:
        return None
    cutoffs = {snapshot.completed_bucket_at for snapshot in selected}
    if len(cutoffs) != 1 or None in cutoffs:
        return None
    completed_bucket_at = next(iter(cutoffs))
    assert completed_bucket_at is not None
    expected = _expected_bucket_ends(completed_bucket_at)
    if not expected:
        return None

    current_amount = Decimal(0)
    previous_bars = []
    for snapshot in selected:
        current_bars = tuple(
            bar
            for bar in snapshot.five_minute_bars
            if bar.bar_at.date() == completed_bucket_at.date()
        )
        if tuple(bar.bar_at for bar in current_bars) != expected or any(
            bar.amount is None for bar in current_bars
        ):
            return None
        previous = tuple(
            bar
            for bar in snapshot.official_daily_bars
            if bar.bar_at.date() < completed_bucket_at.date()
        )
        if not previous or previous[-1].amount is None:
            return None
        previous_bars.append(previous[-1])
        current_amount += sum(
            (bar.amount for bar in current_bars if bar.amount is not None),
            Decimal(0),
        )
    if len({bar.bar_at for bar in previous_bars}) != 1:
        return None
    previous_amount = sum(
        (bar.amount for bar in previous_bars if bar.amount is not None),
        Decimal(0),
    )

    estimated = (
        current_amount * Decimal(MARKET_TURNOVER_BUCKET_COUNT) / Decimal(len(expected))
    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return MarketTurnoverSummary(
        current_amount=current_amount,
        previous_amount=previous_amount,
        change_amount=current_amount - previous_amount,
        estimated_full_day_amount=estimated,
        completed_bucket_at=completed_bucket_at,
    )


def _is_turnover_snapshot_usable(snapshot: MarketIndexSnapshot) -> bool:
    completed_bucket_at = snapshot.completed_bucket_at
    if completed_bucket_at is None:
        return False
    if snapshot.health is MarketIndexHealth.LIVE:
        return snapshot.decision_cutoff == completed_bucket_at
    return (
        snapshot.health is MarketIndexHealth.STALE
        and snapshot.issues == (MarketIndexIssueCode.STALE_DATA,)
        and snapshot.decision_cutoff - completed_bucket_at == timedelta(minutes=5)
    )


def completed_market_turnover_bucket_count(completed_bucket_at: datetime) -> int:
    """Return the number of complete regular-session five-minute buckets."""

    if not isinstance(completed_bucket_at, datetime):
        raise TypeError("completed_bucket_at must be a datetime")
    return len(_expected_bucket_ends(completed_bucket_at))


def _expected_bucket_ends(completed_bucket_at: datetime) -> tuple[datetime, ...]:
    local_time = completed_bucket_at.timetz().replace(tzinfo=None)
    if completed_bucket_at.utcoffset() != timedelta(hours=8) or (
        local_time < time(9, 35)
        or time(11, 30) < local_time < time(13, 5)
        or local_time > time(15, 0)
        or completed_bucket_at.minute % 5
        or completed_bucket_at.second
        or completed_bucket_at.microsecond
    ):
        return ()
    morning_start = completed_bucket_at.replace(hour=9, minute=35)
    afternoon_start = completed_bucket_at.replace(hour=13, minute=5)
    ends = tuple(morning_start + timedelta(minutes=5 * index) for index in range(24))
    ends += tuple(afternoon_start + timedelta(minutes=5 * index) for index in range(24))
    return tuple(value for value in ends if value <= completed_bucket_at)


__all__ = [
    "MARKET_TURNOVER_BUCKET_COUNT",
    "MARKET_TURNOVER_INDEX_CODES",
    "MarketTurnoverSummary",
    "build_market_turnover_summary",
    "completed_market_turnover_bucket_count",
]
