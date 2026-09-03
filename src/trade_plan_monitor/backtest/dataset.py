"""Immutable identities for verified historical backtest datasets."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import date, datetime
from hashlib import sha256
from typing import Literal, Protocol, Self, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.models import (
    AShareSymbol,
    DailyBar,
    DailyLimit,
    MinuteBar,
    TradingDay,
)
from trade_plan_monitor.market_index.canonical import (
    FORMULA_DEFINITION_HASH,
)
from trade_plan_monitor.market_index.canonical import (
    canonical_json as canonical_index_json,
)
from trade_plan_monitor.market_index.identity import (
    MAPPING_VERSION,
    Board,
    MarketIndexCode,
    resolve_board_reference,
)
from trade_plan_monitor.market_index.models import MarketIndexBar

from .index_data import IndexArtifactMembership, market_index_data_hash
from .time import SHANGHAI, format_shanghai_datetime

DATASET_SCHEMA_VERSION = "backtest-dataset-v1"
INDEX_DATASET_SCHEMA_VERSION = "backtest-dataset-v2"
MAX_BACKTEST_YEARS = 5
MAX_WARMUP_YEARS = 2
MAX_DATASET_BLOCKERS = 100


class _DatasetValue(BaseModel):
    """Keep dataset identities closed and immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Keep public copies inside the same validated dataset contract."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class DatasetScope(_DatasetValue):
    """Canonical symbol and date range covered by one frozen dataset."""

    symbols: tuple[AShareSymbol, ...]
    start: date
    end: date
    warmup_start: date
    historical_profile: HistoricalMinuteProfile
    provider: Literal["TUSHARE"] = "TUSHARE"
    adjustment_policy: Literal["NONE"] = "NONE"

    @field_validator("symbols")
    @classmethod
    def canonicalize_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not 1 <= len(value) <= 10:
            raise ValueError("symbols must contain between 1 and 10 entries")
        if len(set(value)) != len(value):
            raise ValueError("symbols must not contain duplicates")
        if any(symbol.endswith(".BJ") for symbol in value):
            raise ValueError("UNSUPPORTED_HISTORICAL_CALENDAR:BSE")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_dates_and_profile(self) -> Self:
        if self.start > self.end:
            raise ValueError("start cannot be after end")
        if self.end > _calendar_years_after(self.start, MAX_BACKTEST_YEARS):
            raise ValueError("backtest date range cannot exceed 5 calendar years")
        if self.warmup_start > self.start:
            raise ValueError("warmup_start cannot be after start")
        if self.start > _calendar_years_after(self.warmup_start, MAX_WARMUP_YEARS):
            raise ValueError("warmup range cannot exceed 2 calendar years")
        if self.historical_profile is HistoricalMinuteProfile.UNVERIFIED:
            raise ValueError("historical_profile must be verified before freezing")
        return self


class DatasetItem(_DatasetValue):
    """One immutable market artifact selected by a frozen dataset."""

    natural_key: str = Field(min_length=1, max_length=128)
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["CALENDAR", "MINUTE", "LIMIT", "DAILY"]
    symbol: AShareSymbol | None = None
    trade_date: date


class DatasetReferenceMarketBinding(_DatasetValue):
    """One stock symbol's exact derived board-index binding in a v2 manifest."""

    symbol: AShareSymbol
    selection: Literal["AUTO_BOARD"] = "AUTO_BOARD"
    mapping_version: Literal["board-index-map-v1"] = MAPPING_VERSION
    index_code: MarketIndexCode
    display_name: str = Field(min_length=1, max_length=32)
    board: Board

    @classmethod
    def from_symbol(cls, symbol: str) -> Self:
        resolved = resolve_board_reference(symbol)
        return cls(
            symbol=resolved.symbol,
            index_code=resolved.index_code,
            display_name=resolved.display_name,
            board=resolved.board,
        )

    @model_validator(mode="after")
    def validate_derived_identity(self) -> Self:
        resolved = resolve_board_reference(self.symbol)
        if (
            self.index_code is not resolved.index_code
            or self.display_name != resolved.display_name
            or self.board is not resolved.board
            or self.mapping_version != resolved.mapping_version
        ):
            raise ValueError("dataset reference-market binding must be derived from symbol")
        return self


class DatasetManifest(_DatasetValue):
    """Stable manifest whose canonical bytes define ``dataset_hash``."""

    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal["backtest-dataset-v1", "backtest-dataset-v2"] = DATASET_SCHEMA_VERSION
    scope: DatasetScope
    items: tuple[DatasetItem, ...]
    reference_market_bindings: tuple[DatasetReferenceMarketBinding, ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
    )
    index_items: tuple[IndexArtifactMembership, ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
    )
    market_index_data_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        exclude_if=lambda value: value is None,
    )
    formula_definition_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        exclude_if=lambda value: value is None,
    )

    @classmethod
    def build_v2(
        cls,
        *,
        scope: DatasetScope,
        stock_items: tuple[DatasetItem, ...],
        index_items: tuple[IndexArtifactMembership, ...],
    ) -> Self:
        if not isinstance(scope, DatasetScope):
            raise TypeError("scope must be a DatasetScope")
        if type(stock_items) is not tuple or any(
            type(item) is not DatasetItem for item in stock_items
        ):
            raise TypeError("stock_items must be an exact tuple of DatasetItem")
        if type(index_items) is not tuple or any(
            type(item) is not IndexArtifactMembership for item in index_items
        ):
            raise TypeError("index_items must be an exact tuple of IndexArtifactMembership")
        bindings = tuple(
            DatasetReferenceMarketBinding.from_symbol(symbol) for symbol in scope.symbols
        )
        ordered_stock = tuple(sorted(stock_items, key=lambda item: item.natural_key))
        ordered_index = tuple(sorted(index_items, key=lambda item: item.natural_key))
        index_hash = market_index_data_hash(ordered_index)
        identity = {
            "schema_version": INDEX_DATASET_SCHEMA_VERSION,
            "scope": scope,
            "items": ordered_stock,
            "reference_market_bindings": bindings,
            "index_items": ordered_index,
            "market_index_data_hash": index_hash,
            "formula_definition_hash": FORMULA_DEFINITION_HASH,
        }
        dataset_hash = sha256(canonical_index_json(identity).encode("utf-8")).hexdigest()
        return cls(
            dataset_hash=dataset_hash,
            schema_version=INDEX_DATASET_SCHEMA_VERSION,
            scope=scope,
            items=ordered_stock,
            reference_market_bindings=bindings,
            index_items=ordered_index,
            market_index_data_hash=index_hash,
            formula_definition_hash=FORMULA_DEFINITION_HASH,
        )

    @model_validator(mode="after")
    def validate_versioned_shape(self) -> Self:
        if self.items != tuple(sorted(self.items, key=lambda item: item.natural_key)):
            raise ValueError("dataset stock items must use canonical order")
        if self.schema_version == DATASET_SCHEMA_VERSION:
            if (
                self.reference_market_bindings
                or self.index_items
                or self.market_index_data_hash is not None
                or self.formula_definition_hash is not None
            ):
                raise ValueError("backtest-dataset-v1 forbids index identity fields")
            return self
        expected_bindings = tuple(
            DatasetReferenceMarketBinding.from_symbol(symbol) for symbol in self.scope.symbols
        )
        if self.reference_market_bindings != expected_bindings:
            raise ValueError("v2 dataset bindings must match every stock symbol")
        if self.index_items != tuple(sorted(self.index_items, key=lambda item: item.natural_key)):
            raise ValueError("v2 dataset index items must use canonical order")
        if len({item.natural_key for item in self.index_items}) != len(self.index_items):
            raise ValueError("v2 dataset index item identities must be unique")
        allowed_codes = {binding.index_code for binding in expected_bindings}
        if any(item.index_code not in allowed_codes for item in self.index_items):
            raise ValueError("v2 dataset cannot contain an unrelated index")
        if self.market_index_data_hash != market_index_data_hash(self.index_items):
            raise ValueError("v2 dataset market_index_data_hash mismatch")
        if self.formula_definition_hash != FORMULA_DEFINITION_HASH:
            raise ValueError("v2 dataset formula_definition_hash mismatch")
        identity = {
            "schema_version": INDEX_DATASET_SCHEMA_VERSION,
            "scope": self.scope,
            "items": self.items,
            "reference_market_bindings": self.reference_market_bindings,
            "index_items": self.index_items,
            "market_index_data_hash": self.market_index_data_hash,
            "formula_definition_hash": self.formula_definition_hash,
        }
        expected_hash = sha256(canonical_index_json(identity).encode("utf-8")).hexdigest()
        if self.dataset_hash != expected_hash:
            raise ValueError("v2 dataset_hash must match its exact canonical membership")
        return self


class BacktestDatasetScopeSummary(_DatasetValue):
    """Bounded public projection of one frozen dataset scope."""

    symbols: tuple[AShareSymbol, ...]
    start: date
    end: date
    warmup_start: date
    historical_profile: HistoricalMinuteProfile
    adjustment_policy: Literal["NONE"] = "NONE"


class BacktestDatasetCoverage(_DatasetValue):
    """Bounded coverage counts for a verified immutable dataset."""

    symbol_count: int = Field(ge=0)
    trading_day_count: int = Field(ge=0)
    calendar_row_count: int = Field(ge=0)
    minute_day_count: int = Field(ge=0)
    minute_bar_count: int = Field(ge=0)
    daily_limit_row_count: int = Field(ge=0)
    daily_bar_row_count: int = Field(ge=0)
    blockers: tuple[str, ...] = Field(max_length=MAX_DATASET_BLOCKERS)

    @field_validator("blockers")
    @classmethod
    def validate_blockers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("blockers must be ordered and unique")
        if any(
            not blocker or not blocker.replace("_", "").isalnum() or blocker != blocker.upper()
            for blocker in value
        ):
            raise ValueError("blockers must contain stable UPPER_SNAKE codes")
        return value


class BacktestDatasetSummary(_DatasetValue):
    """Public dataset catalog value that never carries manifest membership."""

    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: Literal["backtest-dataset-v1", "backtest-dataset-v2"] = DATASET_SCHEMA_VERSION
    scope: BacktestDatasetScopeSummary
    coverage: BacktestDatasetCoverage
    created_at: datetime
    verified_at: datetime

    @field_validator("created_at", "verified_at")
    @classmethod
    def canonicalize_business_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("dataset metadata time must be timezone-aware")
        return value.astimezone(SHANGHAI)

    @field_serializer("created_at", "verified_at", when_used="json")
    def serialize_business_time(self, value: datetime) -> str:
        return format_shanghai_datetime(value)


class FrozenSymbolDay(_DatasetValue):
    """One verified symbol-day payload yielded by the internal frozen reader."""

    symbol: AShareSymbol
    trade_date: date
    trading_day: TradingDay
    minutes: tuple[MinuteBar, ...] = Field(max_length=240)
    daily_limit: DailyLimit | None
    daily_bar: DailyBar | None

    @model_validator(mode="after")
    def validate_symbol_day(self) -> Self:
        if self.trading_day.cal_date != self.trade_date:
            raise ValueError("trading_day must match trade_date")
        if self.trading_day.exchange != exchange_for_symbol(self.symbol):
            raise ValueError("trading_day exchange must match symbol")
        if not self.trading_day.is_open:
            if self.minutes or self.daily_limit is not None or self.daily_bar is not None:
                raise ValueError("closed symbol-day cannot contain market payloads")
            return self
        if self.daily_bar is None:
            raise ValueError("open symbol-day requires an official daily bar")
        if (
            self.daily_bar.symbol != self.symbol
            or self.daily_bar.trade_date != self.trade_date
            or not self.daily_bar.is_official
        ):
            raise ValueError("daily_bar must be official and match symbol-day")
        if bool(self.minutes) != (self.daily_limit is not None):
            raise ValueError("minutes and daily_limit must be present together")
        if self.minutes:
            if len(self.minutes) != 240:
                raise ValueError("event-range symbol-day requires exactly 240 minutes")
            if any(
                minute.symbol != self.symbol or minute.bar_end.date() != self.trade_date
                for minute in self.minutes
            ):
                raise ValueError("minutes must match symbol-day")
            if self.daily_limit is None:  # pragma: no cover - guarded above
                raise ValueError("event-range symbol-day requires daily_limit")
            if (
                self.daily_limit.symbol != self.symbol
                or self.daily_limit.trade_date != self.trade_date
            ):
                raise ValueError("daily_limit must match symbol-day")
        return self


class FrozenDatasetReader(Protocol):
    """One-shot internal stream over a verified frozen dataset snapshot."""

    @property
    def dataset_hash(self) -> str: ...

    @property
    def scope(self) -> DatasetScope: ...

    def __iter__(self) -> Iterator[FrozenSymbolDay]: ...


@runtime_checkable
class FrozenMarketIndexDatasetReader(FrozenDatasetReader, Protocol):
    """Extended v2 reader exposing only immutable frozen index membership."""

    @property
    def manifest(self) -> DatasetManifest: ...

    @property
    def dataset_revision(self) -> int: ...

    def market_index_bars(
        self,
        index_code: MarketIndexCode,
    ) -> tuple[MarketIndexBar, ...]: ...


@runtime_checkable
class FrozenDatasetSource(Protocol):
    """Factory boundary that opens a fresh frozen reader for each replay attempt."""

    def open_frozen_dataset(
        self,
        dataset_hash: str,
    ) -> AbstractContextManager[FrozenDatasetReader]: ...


@runtime_checkable
class SymbolFilteredFrozenDatasetSource(Protocol):
    """Optional optimized view over one symbol in a verified frozen dataset."""

    def open_frozen_symbol_dataset(
        self,
        dataset_hash: str,
        symbol: str,
    ) -> AbstractContextManager[FrozenDatasetReader]: ...


class DatasetFreezeResult(_DatasetValue):
    """Fail-closed verification outcome."""

    ready: bool
    dataset_hash: str | None
    blockers: tuple[str, ...]

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.ready:
            if self.dataset_hash is None or self.blockers:
                raise ValueError("a ready dataset requires a hash and no blockers")
        elif self.dataset_hash is not None or not self.blockers:
            raise ValueError("a blocked dataset requires blockers and no hash")
        return self


class MarketStoreStatistics(_DatasetValue):
    """Bounded database counts used by maintenance and tests."""

    artifact_count: int = Field(ge=0)
    head_count: int = Field(ge=0)
    minute_artifact_count: int = Field(ge=0)
    minute_head_count: int = Field(ge=0)
    dataset_count: int = Field(ge=0)


def exchange_for_symbol(symbol: str) -> Literal["SSE", "SZSE", "BSE"]:
    """Map one canonical A-share suffix to its exchange calendar."""

    if type(symbol) is not str:
        raise TypeError("symbol must be a string")
    suffix = symbol.rsplit(".", maxsplit=1)[-1]
    exchanges: dict[str, Literal["SSE", "SZSE", "BSE"]] = {
        "SH": "SSE",
        "SZ": "SZSE",
        "BJ": "BSE",
    }
    try:
        return exchanges[suffix]
    except KeyError as error:
        raise ValueError(f"unsupported A-share symbol: {symbol}") from error


def _calendar_years_after(value: date, years: int) -> date:
    """Return a calendar-year boundary, clamping leap day to February 28."""

    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


__all__ = [
    "BacktestDatasetCoverage",
    "BacktestDatasetScopeSummary",
    "BacktestDatasetSummary",
    "DATASET_SCHEMA_VERSION",
    "INDEX_DATASET_SCHEMA_VERSION",
    "MAX_DATASET_BLOCKERS",
    "MAX_BACKTEST_YEARS",
    "MAX_WARMUP_YEARS",
    "DatasetFreezeResult",
    "DatasetItem",
    "DatasetManifest",
    "DatasetReferenceMarketBinding",
    "DatasetScope",
    "FrozenDatasetReader",
    "FrozenMarketIndexDatasetReader",
    "FrozenDatasetSource",
    "FrozenSymbolDay",
    "MarketStoreStatistics",
    "SymbolFilteredFrozenDatasetSource",
    "exchange_for_symbol",
]
