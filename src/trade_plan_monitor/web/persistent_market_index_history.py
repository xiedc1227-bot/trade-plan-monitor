"""Persistent current-head market-index history for the monitor Web boundary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest

from anyio import to_thread
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.market_index.canonical import canonical_json
from trade_plan_monitor.market_index.identity import MAPPING_VERSION, MarketIndexCode
from trade_plan_monitor.market_index.models import MarketIndexBar, MarketIndexInterval
from trade_plan_monitor.market_index.selection import snapshot_rank
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.unit_of_work import UnitOfWork
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.market_indexes import MarketIndexHistoryAnchor

UnitOfWorkFactory = Callable[[], UnitOfWork]

_HISTORY_HASH_DOMAIN = b"monitor-market-index-history-v1\0"
_MAX_SOURCE_PAGE = 2_001


class PersistentMarketIndexHistorySource:
    """Rebuild one ordered trend from immutable snapshots named by current heads."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        if not callable(unit_of_work_factory):
            raise TypeError("unit_of_work_factory must be callable")
        self._unit_of_work_factory = unit_of_work_factory

    async def capture_market_index_history(
        self,
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        start_at: datetime,
        end_at: datetime,
    ) -> MarketIndexHistoryAnchor | None:
        return await to_thread.run_sync(
            lambda: self._guarded(
                lambda: self._capture(
                    index_code=index_code,
                    interval=interval,
                    start_at=start_at,
                    end_at=end_at,
                )
            )
        )

    async def read_market_index_history(
        self,
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        start_at: datetime,
        end_at: datetime,
        snapshot_hash: str,
        after_at: datetime | None,
        high_water_at: datetime,
        limit: int,
    ) -> tuple[MarketIndexBar, ...]:
        if type(limit) is not int or not 1 <= limit <= _MAX_SOURCE_PAGE:
            raise ValueError(f"limit must be between 1 and {_MAX_SOURCE_PAGE}")
        return await to_thread.run_sync(
            lambda: self._guarded(
                lambda: self._read(
                    index_code=index_code,
                    interval=interval,
                    start_at=start_at,
                    end_at=end_at,
                    snapshot_hash=snapshot_hash,
                    after_at=after_at,
                    high_water_at=high_water_at,
                    limit=limit,
                )
            )
        )

    def _capture(
        self,
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        start_at: datetime,
        end_at: datetime,
    ) -> MarketIndexHistoryAnchor | None:
        bars = self._series(
            index_code=index_code,
            interval=interval,
            start_at=start_at,
            end_at=end_at,
        )
        if not bars:
            return None
        return MarketIndexHistoryAnchor(
            high_water_at=bars[-1].bar_at,
            snapshot_hash=_history_snapshot_hash(
                index_code=index_code,
                interval=interval,
                bars=bars,
            ),
        )

    def _read(
        self,
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        start_at: datetime,
        end_at: datetime,
        snapshot_hash: str,
        after_at: datetime | None,
        high_water_at: datetime,
        limit: int,
    ) -> tuple[MarketIndexBar, ...]:
        bars = tuple(
            bar
            for bar in self._series(
                index_code=index_code,
                interval=interval,
                start_at=start_at,
                end_at=end_at,
            )
            if bar.bar_at <= high_water_at
        )
        current_hash = _history_snapshot_hash(
            index_code=index_code,
            interval=interval,
            bars=bars,
        )
        if not compare_digest(current_hash, snapshot_hash):
            raise RepositoryError("Market-index history changed during traversal")
        return tuple(
            bar for bar in bars if after_at is None or bar.bar_at > after_at
        )[:limit]

    def _series(
        self,
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[MarketIndexBar, ...]:
        with self._unit_of_work_factory() as work:
            records = work.projections.list_market_index_snapshot_heads(
                mapping_version=MAPPING_VERSION,
                index_code=index_code,
                start_at=start_at,
                end_at=end_at,
            )
            selected: dict[datetime, tuple[tuple[object, ...], MarketIndexBar]] = {}
            for record in records:
                snapshot = record.snapshot
                candidates = (
                    snapshot.five_minute_bars
                    if interval is MarketIndexInterval.FIVE_MINUTE
                    else snapshot.official_daily_bars
                )
                rank = snapshot_rank(snapshot)
                for bar in candidates:
                    if not start_at <= bar.bar_at <= end_at:
                        continue
                    incoming = (*rank, bar.observed_at, bar.provider_revision)
                    current = selected.get(bar.bar_at)
                    if current is None or incoming > current[0]:
                        selected[bar.bar_at] = incoming, bar
            return tuple(selected[bar_at][1] for bar_at in sorted(selected))

    @staticmethod
    def _guarded[Result](operation: Callable[[], Result]) -> Result:
        try:
            return operation()
        except (RepositoryError, SQLAlchemyError, ValidationError):
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE) from None


def _history_snapshot_hash(
    *,
    index_code: MarketIndexCode,
    interval: MarketIndexInterval,
    bars: tuple[MarketIndexBar, ...],
) -> str:
    payload = {
        "indexCode": index_code,
        "interval": interval,
        "bars": bars,
    }
    return sha256(
        _HISTORY_HASH_DOMAIN + canonical_json(payload).encode("utf-8")
    ).hexdigest()


__all__ = ["PersistentMarketIndexHistorySource"]
