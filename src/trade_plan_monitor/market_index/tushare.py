"""Certified, fail-closed Tushare board-index provider.

Tushare documents ``idx_mins`` as the historical index-minute endpoint,
``rt_idx_min_daily`` as the current-day index-minute endpoint, and
``index_daily`` as the official daily endpoint:
https://tushare.pro/document/2?doc_id=419
https://tushare.pro/document/2?doc_id=420
https://tushare.pro/document/1?doc_id=95
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, DecimalException
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from zoneinfo import ZoneInfo

import pandas as pd

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexIssueCode,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.provider import MarketIndexProviderBatch
from trade_plan_monitor.runtime.request_control import (
    RequestPriority,
    TushareOperation,
    TushareRequestController,
)

_PROFILE_ID: Final = "tushare-board-index-live-v1"
_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_INDEX_MINUTE_ENDPOINT: Final = "idx_mins"
_INDEX_REALTIME_MINUTE_ENDPOINT: Final = "rt_idx_min_daily"
_INDEX_DAILY_ENDPOINT: Final = "index_daily"
_INDEX_MINUTE_FIELDS: Final = "ts_code,trade_time,open,close,high,low,vol,amount"
_INDEX_REALTIME_MINUTE_FIELDS: Final = "ts_code,freq,time,open,close,high,low,vol,amount"
_INDEX_DAILY_FIELDS: Final = "ts_code,trade_date,open,high,low,close,vol,amount"
LIVE_TUSHARE_INDEX_CODES: Final = (
    MarketIndexCode.SSE_COMPOSITE,
    MarketIndexCode.SHENZHEN_COMPONENT,
    MarketIndexCode.CHINEXT,
    MarketIndexCode.STAR_50,
)
_INDEX_MINUTE_COLUMNS: Final = (
    "ts_code",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
)
_MAX_REQUESTED_BARS: Final = 8_000


class TushareMarketIndexCapabilityStatus(StrEnum):
    """Index-only certification state; it is not a stock-provider capability."""

    UNVERIFIED = "UNVERIFIED"
    DEFERRED = "DEFERRED"
    READY = "READY"
    BLOCKED_PERMISSION = "BLOCKED_PERMISSION"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"


class TushareMarketIndexSourceTimeLabel(StrEnum):
    """Index-only raw timestamp interpretation established by index evidence."""

    UNVERIFIED = "UNVERIFIED"
    START = "START"
    END = "END"


@dataclass(frozen=True, slots=True)
class TushareMarketIndexProfile:
    """Independent board-index profile with no guessed endpoint or time label."""

    profile_id: str
    capabilities: Mapping[MarketIndexCode, TushareMarketIndexCapabilityStatus]
    source_time_label: TushareMarketIndexSourceTimeLabel
    five_minute_endpoint: str | None
    realtime_five_minute_endpoint: str | None
    official_daily_endpoint: str | None

    def __post_init__(self) -> None:
        if self.profile_id != _PROFILE_ID:
            raise ValueError("unsupported Tushare market-index profile")
        capabilities = dict(self.capabilities)
        if set(capabilities) != set(MarketIndexCode):
            raise ValueError("market-index profile must classify every approved index")
        if any(
            not isinstance(index_code, MarketIndexCode)
            or not isinstance(status, TushareMarketIndexCapabilityStatus)
            for index_code, status in capabilities.items()
        ):
            raise TypeError("market-index capabilities use dedicated enum values")
        if capabilities[MarketIndexCode.BSE_50] is TushareMarketIndexCapabilityStatus.READY:
            raise ValueError("BSE 50 live index is deferred")
        unverified = self.source_time_label is TushareMarketIndexSourceTimeLabel.UNVERIFIED
        if unverified:
            if (
                self.five_minute_endpoint is not None
                or self.realtime_five_minute_endpoint is not None
                or self.official_daily_endpoint is not None
                or any(
                    status is not TushareMarketIndexCapabilityStatus.UNVERIFIED
                    for status in capabilities.values()
                )
            ):
                raise ValueError("unverified market-index profile cannot enable endpoints")
        elif (
            self.five_minute_endpoint != _INDEX_MINUTE_ENDPOINT
            or self.realtime_five_minute_endpoint != _INDEX_REALTIME_MINUTE_ENDPOINT
            or self.official_daily_endpoint != _INDEX_DAILY_ENDPOINT
            or any(
                status is TushareMarketIndexCapabilityStatus.UNVERIFIED
                for status in capabilities.values()
            )
            or TushareMarketIndexCapabilityStatus.READY not in capabilities.values()
        ):
            raise ValueError("market-index profile requires independent live certification")
        object.__setattr__(self, "capabilities", MappingProxyType(capabilities))


def unverified_tushare_market_index_profile() -> TushareMarketIndexProfile:
    """Return the only truthful profile before an authorized index observation."""

    return TushareMarketIndexProfile(
        profile_id=_PROFILE_ID,
        capabilities={
            index_code: TushareMarketIndexCapabilityStatus.UNVERIFIED
            for index_code in MarketIndexCode
        },
        source_time_label=TushareMarketIndexSourceTimeLabel.UNVERIFIED,
        five_minute_endpoint=None,
        realtime_five_minute_endpoint=None,
        official_daily_endpoint=None,
    )


def certified_tushare_market_index_profile(
    *,
    capabilities: Mapping[MarketIndexCode, TushareMarketIndexCapabilityStatus],
    source_time_label: TushareMarketIndexSourceTimeLabel,
) -> TushareMarketIndexProfile:
    """Build the strict profile shape accepted only after index-specific evidence."""

    return TushareMarketIndexProfile(
        profile_id=_PROFILE_ID,
        capabilities=capabilities,
        source_time_label=source_time_label,
        five_minute_endpoint=_INDEX_MINUTE_ENDPOINT,
        realtime_five_minute_endpoint=_INDEX_REALTIME_MINUTE_ENDPOINT,
        official_daily_endpoint=_INDEX_DAILY_ENDPOINT,
    )


class TushareMarketIndexProviderError(RuntimeError):
    """Stable index-provider failure without SDK response or credential context."""

    def __init__(self) -> None:
        self.code = MarketIndexIssueCode.PROVIDER_UNAVAILABLE.value
        super().__init__("Tushare market-index provider unavailable")


class TushareMarketIndexProvider:
    """Independent live surface that cannot call an uncertified index endpoint."""

    def __init__(
        self,
        *,
        profile: TushareMarketIndexProfile,
        client: object | None = None,
        request_controller: TushareRequestController | object | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(profile, TushareMarketIndexProfile):
            raise TypeError("profile must be a TushareMarketIndexProfile")
        self._profile = profile
        self._client = client
        self._request_controller = request_controller
        self._now = now

    @property
    def profile(self) -> TushareMarketIndexProfile:
        return self._profile

    async def acquire_index_data(
        self,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        five_minute_bar_count: int,
        official_daily_bar_count: int,
    ) -> MarketIndexProviderBatch:
        if not isinstance(index_code, MarketIndexCode):
            raise TypeError("index_code must be a MarketIndexCode")
        if not isinstance(decision_cutoff, datetime) or decision_cutoff.tzinfo is None:
            raise TypeError("decision_cutoff must be timezone-aware")
        if decision_cutoff.utcoffset() != timedelta(hours=8):
            raise ValueError("decision_cutoff must use Asia/Shanghai")
        for name, value in (
            ("five_minute_bar_count", five_minute_bar_count),
            ("official_daily_bar_count", official_daily_bar_count),
        ):
            if type(value) is not int or not 1 <= value <= _MAX_REQUESTED_BARS:
                raise ValueError(f"{name} must be between 1 and {_MAX_REQUESTED_BARS}")
        if (
            self._profile.capabilities[index_code] is not TushareMarketIndexCapabilityStatus.READY
            or self._profile.source_time_label is TushareMarketIndexSourceTimeLabel.UNVERIFIED
            or self._client is None
            or self._request_controller is None
            or self._now is None
        ):
            raise TushareMarketIndexProviderError from None

        cutoff = decision_cutoff.astimezone(_SHANGHAI)
        work_prefix = f"index:{index_code.value}:{cutoff.strftime('%Y%m%dT%H%M')}"
        try:
            minute_frame = await self._request_controller.execute(
                TushareOperation.INDEX_MINUTES,
                lambda: self._fetch_index_minutes(index_code, cutoff),
                work_key=f"{work_prefix}:minutes",
                priority=RequestPriority.MARKET_DEADLINE,
            )
            realtime_minute_frame = await self._request_controller.execute(
                TushareOperation.INDEX_MINUTES,
                lambda: self._fetch_realtime_index_minutes(index_code),
                work_key=f"{work_prefix}:realtime-minutes",
                priority=RequestPriority.MARKET_DEADLINE,
            )
            daily_frame = await self._request_controller.execute(
                TushareOperation.INDEX_DAILY,
                lambda: self._fetch_index_daily(index_code, cutoff),
                work_key=f"{work_prefix}:daily",
                priority=RequestPriority.MARKET_DEADLINE,
            )
            if (
                not isinstance(minute_frame, pd.DataFrame)
                or not isinstance(realtime_minute_frame, pd.DataFrame)
                or not isinstance(daily_frame, pd.DataFrame)
            ):
                raise ValueError("index provider returned a non-tabular response")
            minute_frame = self._combined_minute_frame(
                minute_frame,
                realtime_minute_frame,
            )
            observed_at = self._observed_at()
            revision = self._content_revision(minute_frame, daily_frame)
            minute_bars = self._minute_bars(
                minute_frame,
                index_code=index_code,
                decision_cutoff=cutoff,
                observed_at=observed_at,
                revision=revision,
            )[-five_minute_bar_count:]
            daily_bars = self._daily_bars(
                daily_frame,
                index_code=index_code,
                decision_cutoff=cutoff,
                observed_at=observed_at,
                revision=revision,
                required_bar_count=official_daily_bar_count,
            )
            return MarketIndexProviderBatch(
                index_code=index_code,
                five_minute_bars=minute_bars,
                official_daily_bars=daily_bars,
                content_revision=revision,
                observed_at=observed_at,
            )
        except Exception:
            raise TushareMarketIndexProviderError from None

    def _fetch_index_minutes(
        self,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
    ) -> object:
        endpoint = getattr(self._client, _INDEX_MINUTE_ENDPOINT)
        return endpoint(
            ts_code=index_code.value,
            freq="5min",
            start_date=(decision_cutoff - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
            end_date=datetime.combine(
                decision_cutoff.date() - timedelta(days=1),
                time(23, 59, 59),
                _SHANGHAI,
            ).strftime("%Y-%m-%d %H:%M:%S"),
            fields=_INDEX_MINUTE_FIELDS,
        )

    def _fetch_realtime_index_minutes(self, index_code: MarketIndexCode) -> object:
        endpoint = getattr(self._client, _INDEX_REALTIME_MINUTE_ENDPOINT)
        return endpoint(
            ts_code=index_code.value,
            freq="5MIN",
            fields=_INDEX_REALTIME_MINUTE_FIELDS,
        )

    @staticmethod
    def _combined_minute_frame(
        historical: pd.DataFrame,
        realtime: pd.DataFrame,
    ) -> pd.DataFrame:
        TushareMarketIndexProvider._require_columns(
            historical,
            {"ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"},
        )
        symbol_column = "ts_code" if "ts_code" in realtime.columns else "code"
        TushareMarketIndexProvider._require_columns(
            realtime,
            {symbol_column, "time", "open", "high", "low", "close", "vol", "amount"},
        )
        frequency_count = Counter(realtime.columns)["freq"]
        if frequency_count not in (0, 1) or (
            frequency_count == 1 and not realtime["freq"].astype(str).eq("5MIN").all()
        ):
            raise ValueError("realtime index-minute frequency is invalid")
        current = realtime.rename(columns={symbol_column: "ts_code", "time": "trade_time"})
        return pd.concat(
            [historical[list(_INDEX_MINUTE_COLUMNS)], current[list(_INDEX_MINUTE_COLUMNS)]],
            ignore_index=True,
        )

    def _fetch_index_daily(
        self,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
    ) -> object:
        endpoint = getattr(self._client, _INDEX_DAILY_ENDPOINT)
        return endpoint(
            ts_code=index_code.value,
            start_date=(decision_cutoff.date() - timedelta(days=400)).strftime("%Y%m%d"),
            end_date=decision_cutoff.date().strftime("%Y%m%d"),
            fields=_INDEX_DAILY_FIELDS,
        )

    def _observed_at(self) -> datetime:
        if self._now is None:  # pragma: no cover - constructor gate
            raise ValueError("index provider clock is unavailable")
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("index provider clock must be timezone-aware")
        canonical = value.astimezone(_SHANGHAI)
        if value.utcoffset() != canonical.utcoffset():
            raise ValueError("index provider clock must use Asia/Shanghai")
        return canonical

    def _minute_bars(
        self,
        frame: pd.DataFrame,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        observed_at: datetime,
        revision: int,
    ) -> tuple[MarketIndexBar, ...]:
        self._require_columns(
            frame,
            {"ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"},
        )
        candidates: dict[datetime, MarketIndexBar] = {}
        for row in frame.to_dict(orient="records"):
            try:
                if row["ts_code"] != index_code.value:
                    continue
                source_at = self._source_datetime(row["trade_time"])
                bar_at = (
                    source_at + timedelta(minutes=5)
                    if self._profile.source_time_label is TushareMarketIndexSourceTimeLabel.START
                    else source_at
                )
                local_time = bar_at.timetz().replace(tzinfo=None)
                valid_session_time = time(9, 35) <= local_time <= time(11, 30) or time(
                    13, 5
                ) <= local_time <= time(15, 0)
                if bar_at.minute % 5 or not valid_session_time or bar_at > decision_cutoff:
                    continue
                bar = self._bar(
                    row,
                    index_code=index_code,
                    interval=MarketIndexInterval.FIVE_MINUTE,
                    bar_at=bar_at,
                    observed_at=observed_at,
                    source_kind=MarketIndexSourceKind.PROVISIONAL,
                    revision=revision,
                    daily_units=False,
                )
            except DecimalException, KeyError, TypeError, ValueError:
                continue
            if bar_at in candidates:
                raise ValueError("duplicate index-minute identity")
            candidates[bar_at] = bar
        return tuple(candidates[key] for key in sorted(candidates))

    def _daily_bars(
        self,
        frame: pd.DataFrame,
        *,
        index_code: MarketIndexCode,
        decision_cutoff: datetime,
        observed_at: datetime,
        revision: int,
        required_bar_count: int,
    ) -> tuple[MarketIndexBar, ...]:
        self._require_columns(
            frame,
            {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"},
        )
        latest_official_date = decision_cutoff.date()
        if decision_cutoff.timetz().replace(tzinfo=None) < time(15, 0):
            latest_official_date -= timedelta(days=1)
        # The endpoint may return years of irrelevant conflicting history. Establish
        # the requested latest date identities before validating their price payloads;
        # a corrupt required date cannot be silently replaced with an older one.
        rows_by_date: dict[date, list[dict[str, object]]] = {}
        for row in frame.to_dict(orient="records"):
            if row["ts_code"] != index_code.value:
                continue
            try:
                trade_date = datetime.strptime(str(row["trade_date"]), "%Y%m%d").date()
            except ValueError:
                continue
            if trade_date <= latest_official_date:
                rows_by_date.setdefault(trade_date, []).append(row)
        required_dates = sorted(rows_by_date)[-required_bar_count:]
        candidates: dict[datetime, MarketIndexBar] = {}
        for row in (row for day in required_dates for row in rows_by_date[day]):
            try:
                if row["ts_code"] != index_code.value:
                    continue
                trade_date = datetime.strptime(str(row["trade_date"]), "%Y%m%d").date()
                if trade_date > latest_official_date:
                    continue
                bar_at = datetime.combine(trade_date, time(15, 0), _SHANGHAI)
                bar = self._bar(
                    row,
                    index_code=index_code,
                    interval=MarketIndexInterval.OFFICIAL_DAILY,
                    bar_at=bar_at,
                    observed_at=observed_at,
                    source_kind=MarketIndexSourceKind.OFFICIAL,
                    revision=revision,
                    daily_units=True,
                )
            except DecimalException, KeyError, TypeError, ValueError:
                continue
            if bar_at in candidates and candidates[bar_at] != bar:
                raise ValueError("duplicate index-daily identity")
            candidates[bar_at] = bar
        if len(candidates) != len(required_dates):
            raise ValueError("required index-daily history is invalid")
        return tuple(candidates[key] for key in sorted(candidates))

    @staticmethod
    def _bar(
        row: Mapping[str, object],
        *,
        index_code: MarketIndexCode,
        interval: MarketIndexInterval,
        bar_at: datetime,
        observed_at: datetime,
        source_kind: MarketIndexSourceKind,
        revision: int,
        daily_units: bool,
    ) -> MarketIndexBar:
        scale_volume = Decimal(100) if daily_units else Decimal(1)
        scale_amount = Decimal(1_000) if daily_units else Decimal(1)
        return MarketIndexBar(
            index_code=index_code,
            interval=interval,
            bar_at=bar_at,
            open_points=TushareMarketIndexProvider._positive_decimal(row["open"]),
            high_points=TushareMarketIndexProvider._positive_decimal(row["high"]),
            low_points=TushareMarketIndexProvider._positive_decimal(row["low"]),
            close_points=TushareMarketIndexProvider._positive_decimal(row["close"]),
            volume=TushareMarketIndexProvider._nonnegative_decimal(row["vol"]) * scale_volume,
            amount=TushareMarketIndexProvider._nonnegative_decimal(row["amount"]) * scale_amount,
            observed_at=observed_at,
            source_kind=source_kind,
            provider_revision=revision,
        )

    @staticmethod
    def _source_datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        else:
            raise TypeError("index minute timestamp is invalid")
        return (
            parsed.replace(tzinfo=_SHANGHAI)
            if parsed.tzinfo is None
            else parsed.astimezone(_SHANGHAI)
        )

    @staticmethod
    def _positive_decimal(value: object) -> Decimal:
        converted = TushareMarketIndexProvider._nonnegative_decimal(value)
        if converted <= 0:
            raise ValueError("index point value must be positive")
        return converted

    @staticmethod
    def _nonnegative_decimal(value: object) -> Decimal:
        if isinstance(value, bool):
            raise TypeError("index numeric value cannot be bool")
        converted = Decimal(str(value))
        if not converted.is_finite() or converted < 0:
            raise ValueError("index numeric value must be finite and non-negative")
        return converted

    @staticmethod
    def _require_columns(frame: pd.DataFrame, required: set[str]) -> None:
        counts = Counter(frame.columns)
        if any(counts[column] != 1 for column in required):
            raise ValueError("index response schema is invalid")

    @staticmethod
    def _content_revision(minute_frame: pd.DataFrame, daily_frame: pd.DataFrame) -> int:
        payload = json.dumps(
            {
                "daily": daily_frame.to_dict(orient="records"),
                "minutes": minute_frame.to_dict(orient="records"),
            },
            default=str,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        revision = int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") & 0x7FFFFFFF
        return revision or 1


__all__ = [
    "LIVE_TUSHARE_INDEX_CODES",
    "TushareMarketIndexCapabilityStatus",
    "TushareMarketIndexProfile",
    "TushareMarketIndexProvider",
    "TushareMarketIndexProviderError",
    "TushareMarketIndexSourceTimeLabel",
    "certified_tushare_market_index_profile",
    "unverified_tushare_market_index_profile",
]
