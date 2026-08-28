"""Application boundary for bounded immutable dataset catalog reads."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.backtest.dataset import BacktestDatasetSummary
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.pagination import CursorSigner, InvalidCursorError
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.models import AShareSymbol

DATASET_CATALOG_ROUTE = "datasets"
DATASET_CATALOG_ORDER = "createdAt DESC,datasetHash DESC"
DEFAULT_DATASET_PAGE_LIMIT = 20
MAX_DATASET_PAGE_LIMIT = 100
_EMPTY_HIGH_WATER = ("0001-01-01T00:00:00.000000+08:00", "0" * 64)


class _DatasetCatalogValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BacktestDatasetFilters(_DatasetCatalogValue):
    """Closed normalized filters accepted by the dataset catalog."""

    symbol: AShareSymbol | None = None
    start_on_or_after: date | None = None
    end_on_or_before: date | None = None
    historical_profile: HistoricalMinuteProfile | None = None
    adjustment_policy: Literal["NONE"] | None = None

    @model_validator(mode="after")
    def require_verified_profile(self) -> Self:
        if self.historical_profile is HistoricalMinuteProfile.UNVERIFIED:
            raise ValueError("historical_profile must be verified")
        return self

    def cursor_binding(self) -> dict[str, object]:
        """Return the exact normalized camelCase filter object bound by cursors."""

        return {
            "symbol": self.symbol,
            "startOnOrAfter": self.start_on_or_after,
            "endOnOrBefore": self.end_on_or_before,
            "historicalProfile": self.historical_profile,
            "adjustmentPolicy": self.adjustment_policy,
        }


class BacktestDatasetPage(_DatasetCatalogValue):
    """One bounded immutable traversal page."""

    filters: BacktestDatasetFilters
    items: tuple[BacktestDatasetSummary, ...] = Field(max_length=MAX_DATASET_PAGE_LIMIT)
    limit: int = Field(ge=1, le=MAX_DATASET_PAGE_LIMIT)
    next_cursor: str | None = Field(default=None, max_length=512)
    has_more: bool
    high_watermark: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_page_state(self) -> Self:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more and next_cursor must agree")
        if len(self.items) > self.limit:
            raise ValueError("dataset page cannot contain more than limit items")
        return self


class DatasetNotFoundError(LookupError):
    """Stable application error for an unknown dataset identity."""

    def __init__(self) -> None:
        super().__init__("dataset not found")


class BacktestDatasetService:
    """Serve bounded summaries while keeping full manifests inside the store."""

    def __init__(self, *, store: BacktestMarketStore, cursor_signer: CursorSigner) -> None:
        if not isinstance(store, BacktestMarketStore):
            raise TypeError("store must be a BacktestMarketStore")
        self._store = store
        self._cursor_signer = cursor_signer

    def get_dataset(self, dataset_hash: str) -> BacktestDatasetSummary:
        try:
            return self._store.dataset_summary(dataset_hash)
        except KeyError:
            raise DatasetNotFoundError from None

    def list_datasets(
        self,
        *,
        limit: int = DEFAULT_DATASET_PAGE_LIMIT,
        cursor: str | None = None,
        filters: BacktestDatasetFilters | None = None,
    ) -> BacktestDatasetPage:
        if type(limit) is not int or not 1 <= limit <= MAX_DATASET_PAGE_LIMIT:
            raise ValueError("limit must be between 1 and 100")
        normalized_filters = BacktestDatasetFilters() if filters is None else filters
        if not isinstance(normalized_filters, BacktestDatasetFilters):
            raise TypeError("filters must be BacktestDatasetFilters")
        binding = normalized_filters.cursor_binding()
        high_water: tuple[str, str] | None = None
        after: tuple[str, str] | None = None
        snapshot_revision: int
        if cursor is not None:
            decoded = self._cursor_signer.decode(
                cursor,
                route=DATASET_CATALOG_ROUTE,
                filters=binding,
                order=DATASET_CATALOG_ORDER,
            )
            try:
                high_water = _catalog_position(decoded.high_water)
                snapshot_revision = _catalog_snapshot(decoded.snapshot)
                if decoded.last_seen is None:
                    raise ValueError
                after = _catalog_position(decoded.last_seen)
            except TypeError, ValueError:
                raise InvalidCursorError from None
        else:
            snapshot_revision = self._store.dataset_catalog_revision()

        values = self._store.list_dataset_summaries(
            limit=limit + 1,
            symbol=normalized_filters.symbol,
            start_on_or_after=normalized_filters.start_on_or_after,
            end_on_or_before=normalized_filters.end_on_or_before,
            historical_profile=(
                None
                if normalized_filters.historical_profile is None
                else normalized_filters.historical_profile.value
            ),
            adjustment_policy=normalized_filters.adjustment_policy,
            snapshot_revision=snapshot_revision,
            high_water=high_water,
            after=after,
        )
        if high_water is None:
            high_water = _position_for_summary(values[0]) if values else _EMPTY_HIGH_WATER
        high_watermark = self._cursor_signer.encode(
            route=DATASET_CATALOG_ROUTE,
            filters=binding,
            order=DATASET_CATALOG_ORDER,
            high_water=high_water,
            last_seen=None,
            snapshot=(snapshot_revision,),
        )
        has_more = len(values) > limit
        items = values[:limit]
        next_cursor = None
        if has_more:
            next_cursor = self._cursor_signer.encode(
                route=DATASET_CATALOG_ROUTE,
                filters=binding,
                order=DATASET_CATALOG_ORDER,
                high_water=high_water,
                last_seen=_position_for_summary(items[-1]),
                snapshot=(snapshot_revision,),
            )
        return BacktestDatasetPage(
            filters=normalized_filters,
            items=items,
            limit=limit,
            next_cursor=next_cursor,
            has_more=has_more,
            high_watermark=high_watermark,
        )


def _position_for_summary(summary: BacktestDatasetSummary) -> tuple[str, str]:
    return summary.created_at.isoformat(timespec="microseconds"), summary.dataset_hash


def _catalog_position(value: tuple[str, ...]) -> tuple[str, str]:
    if type(value) is not tuple or len(value) != 2:
        raise ValueError("dataset cursor position must contain two values")
    created_at_text, dataset_hash = value
    if len(dataset_hash) != 64 or any(
        character not in "0123456789abcdef" for character in dataset_hash
    ):
        raise ValueError("dataset cursor hash is invalid")
    created_at = datetime.fromisoformat(created_at_text)
    if created_at.tzinfo is None or created_at.utcoffset() != timedelta(hours=8):
        raise ValueError("dataset cursor time must use +08:00")
    if created_at.isoformat(timespec="microseconds") != created_at_text:
        raise ValueError("dataset cursor time must use fixed-six-digit +08:00")
    return created_at_text, dataset_hash


def _catalog_snapshot(value: tuple[int, ...] | None) -> int:
    if value is None or len(value) != 1:
        raise ValueError("dataset cursor snapshot must contain one value")
    return value[0]


__all__ = [
    "DATASET_CATALOG_ORDER",
    "DATASET_CATALOG_ROUTE",
    "DEFAULT_DATASET_PAGE_LIMIT",
    "MAX_DATASET_PAGE_LIMIT",
    "BacktestDatasetFilters",
    "BacktestDatasetPage",
    "BacktestDatasetService",
    "DatasetNotFoundError",
]
