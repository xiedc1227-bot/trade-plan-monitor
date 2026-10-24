"""Versioned, self-contained official index revisions for frozen linked replay."""

from datetime import datetime, time
from typing import Literal

from pydantic import Field, field_validator, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.market_index.identity import ReferenceMarketBinding
from trade_plan_monitor.market_index.models import MarketIndexBar, MarketIndexInterval
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot


class LinkedIndexReplaySource(DailyValue):
    version: Literal["market-linkage-replay-source-v1"] = "market-linkage-replay-source-v1"
    reference_market: ReferenceMarketBinding
    bars: tuple[MarketIndexBar, ...] = Field(min_length=1, max_length=10000)

    @field_validator("bars", mode="before")
    @classmethod
    def decode_bars(cls, values):
        return tuple(MarketIndexBar.model_validate_json(canonical_json(value)) for value in values)

    @model_validator(mode="after")
    def identities(self):
        keys = [(bar.observed_at, bar.bar_at) for bar in self.bars]
        if keys != sorted(set(keys)) or any(
            bar.index_code != self.reference_market.index_code
            or bar.interval != MarketIndexInterval.OFFICIAL_DAILY
            or bar.observed_at < bar.bar_at
            for bar in self.bars
        ):
            raise ValueError("LINKED_INDEX_REPLAY_IDENTITY_INVALID")
        return self

    def validate_scope(self, *, binding, session_dates, started_at, cutoff):
        if tuple(sorted(set(session_dates))) != tuple(session_dates):
            raise ValueError("LINKED_INDEX_REPLAY_CALENDAR_INVALID")
        if binding != self.reference_market:
            raise ValueError("LINKED_INDEX_REPLAY_BINDING_MISMATCH")
        past = [day for day in session_dates if day < started_at.date()]
        expected = {
            *past[-60:],
            *(
                day
                for day in session_dates
                if started_at.date() <= day
                and datetime.combine(day, time(15), cutoff.tzinfo) <= cutoff
            ),
        }
        available = {bar.bar_at.date() for bar in self.bars if bar.observed_at <= cutoff}
        if len(past) < 60 or not expected <= available:
            raise ValueError("LINKED_INDEX_REPLAY_HISTORY_MISSING")

    def snapshot_at(self, now, session_dates):
        completed = [
            day for day in session_dates if datetime.combine(day, time(15), now.tzinfo) <= now
        ]
        if not completed:
            return None
        cutoff = datetime.combine(completed[-1], time(15), now.tzinfo)
        available = {}
        for bar in self.bars:
            if bar.observed_at <= now and bar.bar_at <= cutoff:
                available[bar.bar_at] = bar
        if not available:
            return None
        bars = tuple(available[key] for key in sorted(available))[-60:]
        # A stable revision/capture time across unrelated stock arrivals. Never
        # manufacture five-minute index bars to satisfy a daily-only dependency.
        observed = max(bar.observed_at for bar in bars)
        revision = 1 + sum(bar.observed_at <= observed for bar in self.bars)
        return build_market_index_snapshot(
            index_code=self.reference_market.index_code,
            decision_cutoff=cutoff,
            requests=(),
            five_minute_bars=(),
            official_daily_bars=bars,
            content_revision=revision,
            observed_at=observed,
            observed_no_later_than=now,
            minimum_official_daily_bar_count=60,
        )


def freeze_linked_index(connection, *, plan, calendar, started_at, cutoff):
    """Read verified artifacts only; the resulting manifest owns complete bytes."""
    from trade_plan_monitor.backtest.market_store import _validated_index_artifact_row

    rows = connection.execute(
        "SELECT artifact_hash, natural_key, content_json "
        "FROM market_index_artifact WHERE natural_key LIKE ?",
        (f"INDEX_DAILY:{plan.reference_market.index_code.value}:%",),
    )
    days = tuple(day.cal_date for day in calendar if day.is_open)
    bars = tuple(
        sorted(
            (
                bar
                for row in rows
                if (bar := _validated_index_artifact_row(row)).observed_at <= cutoff
                and bar.bar_at.date() in days
            ),
            key=lambda bar: (bar.observed_at, bar.bar_at, bar.provider_revision),
        )
    )
    if not bars:
        raise ValueError("LINKED_INDEX_REPLAY_HISTORY_MISSING")
    source = LinkedIndexReplaySource(reference_market=plan.reference_market, bars=bars)
    source.validate_scope(
        binding=plan.reference_market, session_dates=days, started_at=started_at, cutoff=cutoff
    )
    return source
