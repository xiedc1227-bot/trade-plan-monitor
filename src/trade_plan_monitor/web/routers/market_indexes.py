"""Read-only board-index history contract over an injected server service."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Protocol, Self, cast

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BeforeValidator, Field, model_validator

from trade_plan_monitor.backtest.time import (
    format_shanghai_datetime,
    parse_shanghai_datetime,
)
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexSourceKind,
)
from trade_plan_monitor.web.backtest_pagination import (
    BacktestApiCursorSigner,
    BacktestCursorState,
)
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.dashboard import (
    ReadModel,
    Sha256Hex,
    validate_read_response,
)

router = APIRouter(prefix="/api/v1", tags=["market-indexes"])

_MAX_HISTORY_LIMIT = 2_000
_MAX_CURSOR_CHARACTERS = 512
_FIVE_MINUTE_MAX_RANGE = timedelta(days=31)
_CANONICAL_SHANGHAI_DATETIME = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?\+08:00$"
)
_SIGNED_CURSOR = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def _require_canonical_shanghai_datetime(value: object) -> object:
    if type(value) is str and _CANONICAL_SHANGHAI_DATETIME.fullmatch(value) is None:
        raise ValueError("market-index range must use canonical +08:00 timestamps")
    return value


IndexRangeDatetime = Annotated[
    ShanghaiDatetime,
    BeforeValidator(_require_canonical_shanghai_datetime),
]
IndexCodePath = Annotated[MarketIndexCode, Path(alias="indexCode")]
IndexIntervalQuery = Annotated[MarketIndexInterval, Query()]
RangeStartQuery = Annotated[IndexRangeDatetime, Query(alias="startAt")]
RangeEndQuery = Annotated[IndexRangeDatetime, Query(alias="endAt")]
HistoryLimitQuery = Annotated[int, Query(ge=1, le=_MAX_HISTORY_LIMIT)]
CursorQuery = Annotated[
    str | None,
    Query(min_length=3, max_length=_MAX_CURSOR_CHARACTERS, pattern=_SIGNED_CURSOR.pattern),
]
PositivePoints = Annotated[Decimal, Field(strict=True, gt=0, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[
    Decimal,
    Field(strict=True, ge=0, allow_inf_nan=False),
]


class MarketIndexBarView(ReadModel):
    """One already validated history point; it has no plan interpretation."""

    index_code: MarketIndexCode
    interval: MarketIndexInterval
    bar_at: ShanghaiDatetime
    open_points: PositivePoints
    high_points: PositivePoints
    low_points: PositivePoints
    close_points: PositivePoints
    volume: NonNegativeDecimal | None
    amount: NonNegativeDecimal | None
    observed_at: ShanghaiDatetime
    source_kind: MarketIndexSourceKind
    provider_revision: Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]

    @model_validator(mode="after")
    def validate_bar(self) -> Self:
        MarketIndexBar.model_validate(self.model_dump(mode="python", round_trip=True))
        return self


class MarketIndexBarPage(ReadModel):
    items: tuple[MarketIndexBarView, ...] = Field(default=(), max_length=_MAX_HISTORY_LIMIT)
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_HISTORY_LIMIT)]
    next_cursor: (
        Annotated[
            str,
            Field(
                strict=True,
                min_length=3,
                max_length=_MAX_CURSOR_CHARACTERS,
                pattern=_SIGNED_CURSOR.pattern,
            ),
        ]
        | None
    )
    has_more: bool = Field(strict=True)
    snapshot_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.limit:
            raise ValueError("history page item count cannot exceed limit")
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("hasMore and nextCursor must agree")
        identities = tuple(item.bar_at for item in self.items)
        if any(
            current <= previous
            for previous, current in zip(identities, identities[1:], strict=False)
        ):
            raise ValueError("market-index bars must be strictly increasing")
        return self


class MarketIndexReadService(Protocol):
    """Server-owned history traversal, including signed cursor verification."""

    async def list_market_index_bars(
        self,
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        start_at: datetime,
        end_at: datetime,
        limit: int,
        cursor: str | None,
    ) -> MarketIndexBarPage | None: ...


class MarketIndexHistoryAnchor(ReadModel):
    """Immutable high-water identity captured before a paginated traversal."""

    high_water_at: ShanghaiDatetime
    snapshot_hash: Sha256Hex


class MarketIndexHistorySource(Protocol):
    """Storage-facing source that can replay one captured immutable history view."""

    async def capture_market_index_history(
        self,
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        start_at: datetime,
        end_at: datetime,
    ) -> MarketIndexHistoryAnchor | None: ...

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
    ) -> tuple[MarketIndexBar, ...]: ...


_HISTORY_CURSOR_ROUTE = "/market-indexes/{indexCode}/bars"
_HISTORY_CURSOR_ORDER = "barAt:asc"


class SignedMarketIndexHistoryService:
    """Freeze a history identity and verify every continuation cursor server-side."""

    def __init__(
        self,
        *,
        source: MarketIndexHistorySource,
        cursor_signer: BacktestApiCursorSigner,
    ) -> None:
        if not isinstance(cursor_signer, BacktestApiCursorSigner):
            raise TypeError("cursor_signer must be a BacktestApiCursorSigner")
        self._source = source
        self._cursor_signer = cursor_signer

    async def list_market_index_bars(
        self,
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        start_at: datetime,
        end_at: datetime,
        limit: int,
        cursor: str | None,
    ) -> MarketIndexBarPage | None:
        filters = {
            "indexCode": index_code.value,
            "interval": interval.value,
            "startAt": format_shanghai_datetime(start_at),
            "endAt": format_shanghai_datetime(end_at),
        }
        if cursor is None:
            captured = await self._source.capture_market_index_history(
                index_code=index_code,
                interval=interval,
                start_at=start_at,
                end_at=end_at,
            )
            if captured is None:
                return None
            anchor = MarketIndexHistoryAnchor.model_validate(captured)
            if not start_at <= anchor.high_water_at <= end_at:
                raise ValueError("market-index history high water lies outside request")
            state = BacktestCursorState(
                high_water=(
                    format_shanghai_datetime(anchor.high_water_at),
                    anchor.snapshot_hash,
                ),
                last_seen=None,
                membership_revision=None,
            )
        else:
            state = self._cursor_signer.decode(
                cursor,
                route=_HISTORY_CURSOR_ROUTE,
                filters=filters,
                order=_HISTORY_CURSOR_ORDER,
            )

        high_water_at, snapshot_hash = _decode_history_position(state.high_water)
        if not start_at <= high_water_at <= end_at:
            raise ValueError("market-index cursor high water lies outside request")
        after_at = None
        if state.last_seen is not None:
            after_at, last_snapshot_hash = _decode_history_position(state.last_seen)
            if last_snapshot_hash != snapshot_hash or after_at > high_water_at:
                raise ValueError("market-index cursor position is inconsistent")

        raw_bars = await self._source.read_market_index_history(
            index_code=index_code,
            interval=interval,
            start_at=start_at,
            end_at=end_at,
            snapshot_hash=snapshot_hash,
            after_at=after_at,
            high_water_at=high_water_at,
            limit=limit + 1,
        )
        bars = _validate_history_bars(
            raw_bars,
            index_code=index_code,
            interval=interval,
            start_at=start_at,
            end_at=end_at,
            after_at=after_at,
            high_water_at=high_water_at,
            maximum_count=limit + 1,
        )
        has_more = len(bars) > limit
        visible = bars[:limit]
        next_cursor = None
        if has_more:
            last_bar = visible[-1]
            next_cursor = self._cursor_signer.encode(
                route=_HISTORY_CURSOR_ROUTE,
                filters=filters,
                order=_HISTORY_CURSOR_ORDER,
                high_water=state.high_water,
                last_seen=(
                    format_shanghai_datetime(last_bar.bar_at),
                    snapshot_hash,
                ),
            )
        return MarketIndexBarPage(
            items=tuple(
                MarketIndexBarView.model_validate(bar.model_dump(mode="python", round_trip=True))
                for bar in visible
            ),
            limit=limit,
            next_cursor=next_cursor,
            has_more=has_more,
            snapshot_hash=snapshot_hash,
        )


def _decode_history_position(position: tuple[str, ...]) -> tuple[datetime, str]:
    if len(position) != 2 or re.fullmatch(r"[0-9a-f]{64}", position[1]) is None:
        raise ValueError("market-index cursor position is invalid")
    return parse_shanghai_datetime(position[0]), position[1]


def _validate_history_bars(
    value: object,
    *,
    index_code: MarketIndexCode,
    interval: MarketIndexInterval,
    start_at: datetime,
    end_at: datetime,
    after_at: datetime | None,
    high_water_at: datetime,
    maximum_count: int,
) -> tuple[MarketIndexBar, ...]:
    if type(value) is not tuple or len(value) > maximum_count:
        raise ValueError("market-index history source returned an invalid page")
    bars = tuple(value)
    if any(type(bar) is not MarketIndexBar for bar in bars):
        raise ValueError("market-index history source returned an invalid bar")
    identities = tuple(bar.bar_at for bar in bars)
    if any(
        current <= previous for previous, current in zip(identities, identities[1:], strict=False)
    ):
        raise ValueError("market-index history source is not strictly ordered")
    if any(
        bar.index_code is not index_code
        or bar.interval is not interval
        or not start_at <= bar.bar_at <= min(end_at, high_water_at)
        or (after_at is not None and bar.bar_at <= after_at)
        for bar in bars
    ):
        raise ValueError("market-index history source returned a mismatched bar")
    return bars


def get_market_index_read_service(request: Request) -> MarketIndexReadService:
    service = getattr(request.app.state, "market_index_read_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(MarketIndexReadService, service)


MarketIndexReadServiceDependency = Annotated[
    MarketIndexReadService,
    Depends(get_market_index_read_service),
]


def _range_is_too_large(
    *,
    interval: MarketIndexInterval,
    start_at: datetime,
    end_at: datetime,
) -> bool:
    if start_at > end_at:
        return True
    if interval is MarketIndexInterval.FIVE_MINUTE:
        return end_at - start_at > _FIVE_MINUTE_MAX_RANGE
    try:
        maximum_end = start_at.replace(year=start_at.year + 10)
    except ValueError:
        maximum_end = start_at.replace(year=start_at.year + 10, day=28)
    return end_at > maximum_end


@router.get(
    "/market-indexes/{indexCode}/bars",
    response_model=MarketIndexBarPage,
)
async def list_market_index_bars(
    index_code: IndexCodePath,
    interval: IndexIntervalQuery,
    start_at: RangeStartQuery,
    end_at: RangeEndQuery,
    limit: HistoryLimitQuery,
    service: MarketIndexReadServiceDependency,
    cursor: CursorQuery = None,
) -> MarketIndexBarPage:
    if _range_is_too_large(interval=interval, start_at=start_at, end_at=end_at):
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)
    value = await service.list_market_index_bars(
        index_code=index_code,
        interval=interval,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        cursor=cursor,
    )
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    response = validate_read_response(value, MarketIndexBarPage)
    if response.limit != limit:
        raise ValueError("market-index history response limit does not match request")
    if any(item.index_code is not index_code for item in response.items):
        raise ValueError("market-index history response identity does not match request")
    if any(item.interval is not interval for item in response.items):
        raise ValueError("market-index history interval does not match request")
    if any(not start_at <= item.bar_at <= end_at for item in response.items):
        raise ValueError("market-index history item lies outside requested range")
    return response


__all__ = [
    "MarketIndexBarPage",
    "MarketIndexBarView",
    "MarketIndexHistoryAnchor",
    "MarketIndexHistorySource",
    "MarketIndexReadService",
    "SignedMarketIndexHistoryService",
    "get_market_index_read_service",
    "router",
]
