"""Sanitized one-shot probes for independent stock and board-index surfaces."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import pandas as pd

from trade_plan_monitor.live_profiles import (
    IndexLiveCertification,
    StockLiveCertification,
    create_index_certification,
    create_stock_certification,
    write_live_certification,
)
from trade_plan_monitor.market_data.models import (
    ProviderCapabilities,
    ProviderCapabilityStatus,
)
from trade_plan_monitor.market_data.sessions import (
    SourceTimeLabel,
    expected_minute_ends,
    normalize_source_minute,
)
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexSourceTimeLabel,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    RequestPriority,
    TushareOperation,
)

_SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
_STOCK_SYMBOLS: Final = (
    "000001.SZ",
    "000002.SZ",
    "000063.SZ",
    "000333.SZ",
    "000651.SZ",
    "300750.SZ",
    "600000.SH",
    "600036.SH",
    "600519.SH",
    "601318.SH",
)
_PROBE_SYMBOL: Final = "600000.SH"
_CALENDAR_FIELDS: Final = "exchange,cal_date,is_open,pretrade_date"
_LIMIT_FIELDS: Final = "trade_date,ts_code,up_limit,down_limit"
_DAILY_FIELDS: Final = "ts_code,trade_date,open,high,low,close,vol,amount"
_MINUTE_FIELDS: Final = "ts_code,time,open,close,high,low,vol,amount"
_CURRENT_DAY_FIELDS: Final = "ts_code,freq,time,open,close,high,low,vol,amount"
_INDEX_MINUTE_FIELDS: Final = "ts_code,trade_time,open,close,high,low,vol,amount"
_INDEX_DAILY_FIELDS: Final = "ts_code,trade_date,open,high,low,close,vol,amount"


class LiveProbeWindowError(RuntimeError):
    """Stable failure when the provider calendar cannot prove an open session."""


def _canonical_observed_at(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError("observed_at must be timezone-aware")
    canonical = value.astimezone(_SHANGHAI)
    if value.utcoffset() != canonical.utcoffset():
        raise ValueError("observed_at must use Asia/Shanghai")
    return canonical


def _provider_frame(client: object, endpoint: str, kwargs: dict[str, object]) -> pd.DataFrame:
    try:
        method = getattr(client, endpoint)
        frame = method(**kwargs)
    except TushareProviderError:
        raise
    except Exception as error:
        raise TushareMarketDataProvider._safe_provider_error(endpoint, error) from None
    if not isinstance(frame, pd.DataFrame):
        raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, endpoint)
    return frame


async def _call_frame(
    *,
    client: object,
    request_controller: object,
    operation: TushareOperation,
    endpoint: str,
    work_key: str,
    kwargs: dict[str, object],
) -> pd.DataFrame:
    result = await request_controller.execute(
        operation,
        lambda: _provider_frame(client, endpoint, kwargs),
        work_key=work_key,
        priority=RequestPriority.BACKGROUND,
    )
    if not isinstance(result, pd.DataFrame):
        raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, endpoint)
    return result


def _require_rows(frame: pd.DataFrame, required: set[str]) -> None:
    counts = Counter(str(column) for column in frame.columns)
    if frame.empty or any(counts[column] != 1 for column in required):
        raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, "schema")


def _stock_status(error: Exception) -> ProviderCapabilityStatus:
    code = _error_code(error)
    if code in (TushareErrorCode.BLOCKED_PERMISSION, RequestControlErrorCode.BLOCKED_PERMISSION):
        return ProviderCapabilityStatus.BLOCKED_PERMISSION
    if code in (TushareErrorCode.RATE_LIMITED, RequestControlErrorCode.RATE_LIMITED):
        return ProviderCapabilityStatus.RATE_LIMITED
    return ProviderCapabilityStatus.ERROR


def _index_status(error: Exception) -> TushareMarketIndexCapabilityStatus:
    code = _error_code(error)
    if code in (TushareErrorCode.BLOCKED_PERMISSION, RequestControlErrorCode.BLOCKED_PERMISSION):
        return TushareMarketIndexCapabilityStatus.BLOCKED_PERMISSION
    if code in (TushareErrorCode.RATE_LIMITED, RequestControlErrorCode.RATE_LIMITED):
        return TushareMarketIndexCapabilityStatus.RATE_LIMITED
    return TushareMarketIndexCapabilityStatus.ERROR


def _error_code(error: Exception) -> TushareErrorCode | RequestControlErrorCode | None:
    if isinstance(error, TushareProviderError):
        return error.code
    if isinstance(error, RequestControlError):
        return error.code
    return None


def _is_rate_limited(error: Exception) -> bool:
    return _error_code(error) in (
        TushareErrorCode.RATE_LIMITED,
        RequestControlErrorCode.RATE_LIMITED,
    )


def _calendar_dates(frame: pd.DataFrame, today: date) -> tuple[bool, date]:
    _require_rows(frame, {"exchange", "cal_date", "is_open", "pretrade_date"})
    rows = frame.to_dict(orient="records")
    target = next((row for row in rows if str(row["cal_date"]) == today.strftime("%Y%m%d")), None)
    if target is None or str(target["is_open"]) not in {"0", "1"}:
        raise LiveProbeWindowError("provider calendar did not classify the current date")
    if str(target["is_open"]) != "1":
        raise LiveProbeWindowError("provider calendar reports a closed session")
    previous = datetime.strptime(str(target["pretrade_date"]), "%Y%m%d").date()
    if previous >= today:
        raise LiveProbeWindowError("provider calendar previous date is invalid")
    return True, previous


def _source_times(frame: pd.DataFrame, column: str, observed_at: datetime) -> tuple[datetime, ...]:
    parsed = pd.to_datetime(frame[column], errors="coerce")
    values = tuple(
        sorted(
            item.to_pydatetime().replace(tzinfo=_SHANGHAI)
            for item in parsed
            if not pd.isna(item) and item.date() == observed_at.date()
        )
    )
    if not values:
        raise ValueError("minute timestamps are unavailable")
    return values


def _stock_time_label(
    samples: tuple[pd.DataFrame, pd.DataFrame],
    observed_at: datetime,
) -> SourceTimeLabel:
    expected = set(expected_minute_ends(observed_at.date(), is_open=True))
    conclusions: list[SourceTimeLabel] = []
    for sample in samples:
        _require_rows(
            sample,
            {"freq", "time", "open", "close", "high", "low", "vol", "amount"},
        )
        candidates: list[SourceTimeLabel] = []
        for label in (SourceTimeLabel.START, SourceTimeLabel.END):
            try:
                normalized = {
                    normalize_source_minute(value, label=label, is_open=True)
                    for value in _source_times(sample, "time", observed_at)
                }
            except ValueError:
                continue
            if normalized.issubset(expected) and min(expected) in normalized:
                candidates.append(label)
        if len(candidates) != 1:
            return SourceTimeLabel.UNVERIFIED
        conclusions.append(candidates[0])
    if len(set(conclusions)) != 1:
        return SourceTimeLabel.UNVERIFIED
    return conclusions[0]


def _index_expected_ends(trade_date: date) -> set[datetime]:
    one_minute = expected_minute_ends(trade_date, is_open=True)
    return {value for value in one_minute if value.minute % 5 == 0}


def _index_time_label(
    samples: list[pd.DataFrame],
    observed_at: datetime,
) -> TushareMarketIndexSourceTimeLabel:
    expected = _index_expected_ends(observed_at.date())
    conclusions: list[TushareMarketIndexSourceTimeLabel] = []
    for sample in samples:
        _require_rows(
            sample,
            {"ts_code", "trade_time", "open", "close", "high", "low", "vol", "amount"},
        )
        source = _source_times(sample, "trade_time", observed_at)
        candidates: list[TushareMarketIndexSourceTimeLabel] = []
        for label in (
            TushareMarketIndexSourceTimeLabel.START,
            TushareMarketIndexSourceTimeLabel.END,
        ):
            normalized = {
                value + timedelta(minutes=5)
                if label is TushareMarketIndexSourceTimeLabel.START
                else value
                for value in source
            }
            if normalized.issubset(expected) and min(expected) in normalized:
                candidates.append(label)
        if len(candidates) != 1:
            return TushareMarketIndexSourceTimeLabel.UNVERIFIED
        conclusions.append(candidates[0])
    if not conclusions or len(set(conclusions)) != 1:
        return TushareMarketIndexSourceTimeLabel.UNVERIFIED
    return conclusions[0]


async def certify_stock(
    *,
    client: object,
    request_controller: object,
    observed_at: datetime,
    endpoint_url: str,
    output_path: Path,
) -> StockLiveCertification:
    """Probe all stock surfaces independently and persist only sanitized evidence."""

    now = _canonical_observed_at(observed_at)
    statuses = {
        "realtime_minutes": ProviderCapabilityStatus.UNVERIFIED,
        "current_day_minutes": ProviderCapabilityStatus.UNVERIFIED,
        "trading_calendar": ProviderCapabilityStatus.UNVERIFIED,
        "daily_limits": ProviderCapabilityStatus.UNVERIFIED,
        "daily_bars": ProviderCapabilityStatus.UNVERIFIED,
    }
    calendar = await _call_frame(
        client=client,
        request_controller=request_controller,
        operation=TushareOperation.TRADING_CALENDAR,
        endpoint="trade_cal",
        work_key="live-stock-calendar",
        kwargs={
            "exchange": "",
            "start_date": (now.date() - timedelta(days=14)).strftime("%Y%m%d"),
            "end_date": now.strftime("%Y%m%d"),
            "fields": _CALENDAR_FIELDS,
        },
    )
    _, reference_date = _calendar_dates(calendar, now.date())
    statuses["trading_calendar"] = ProviderCapabilityStatus.READY

    calls = (
        (
            "daily_limits",
            TushareOperation.DAILY_LIMITS,
            "stk_limit",
            {"trade_date": reference_date.strftime("%Y%m%d"), "fields": _LIMIT_FIELDS},
            {"trade_date", "ts_code", "up_limit", "down_limit"},
        ),
        (
            "daily_bars",
            TushareOperation.DAILY_BARS,
            "daily",
            {
                "ts_code": _PROBE_SYMBOL,
                "start_date": reference_date.strftime("%Y%m%d"),
                "end_date": reference_date.strftime("%Y%m%d"),
                "fields": _DAILY_FIELDS,
            },
            {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"},
        ),
        (
            "realtime_minutes",
            TushareOperation.REALTIME_MINUTES,
            "rt_min",
            {"ts_code": ",".join(_STOCK_SYMBOLS), "freq": "1MIN", "fields": _MINUTE_FIELDS},
            {"ts_code", "time", "open", "high", "low", "close", "vol", "amount"},
        ),
    )
    stop = False
    for field, operation, endpoint, kwargs, required in calls:
        if stop:
            break
        try:
            frame = await _call_frame(
                client=client,
                request_controller=request_controller,
                operation=operation,
                endpoint=endpoint,
                work_key=f"live-stock-{endpoint}",
                kwargs=kwargs,
            )
            _require_rows(frame, required)
            if field == "realtime_minutes" and set(
                frame["ts_code"].astype(str)
            ) != set(_STOCK_SYMBOLS):
                raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, endpoint)
            statuses[field] = ProviderCapabilityStatus.READY
        except (RequestControlError, TushareProviderError) as error:
            statuses[field] = _stock_status(error)
            stop = _is_rate_limited(error)

    samples: list[pd.DataFrame] = []
    while not stop and len(samples) < 2:
        try:
            frame = await _call_frame(
                client=client,
                request_controller=request_controller,
                operation=TushareOperation.CURRENT_DAY_MINUTES,
                endpoint="rt_min_daily",
                work_key=f"live-stock-current-{len(samples) + 1}",
                kwargs={"ts_code": _PROBE_SYMBOL, "freq": "1MIN", "fields": _CURRENT_DAY_FIELDS},
            )
            symbol_column = "ts_code" if "ts_code" in frame.columns else "code"
            _require_rows(
                frame,
                {symbol_column, "freq", "time", "open", "high", "low", "close", "vol", "amount"},
            )
            samples.append(frame)
        except (RequestControlError, TushareProviderError) as error:
            statuses["current_day_minutes"] = _stock_status(error)
            stop = _is_rate_limited(error)
            break
    label = (
        _stock_time_label((samples[0], samples[1]), now)
        if len(samples) == 2
        else SourceTimeLabel.UNVERIFIED
    )
    if len(samples) == 2:
        statuses["current_day_minutes"] = (
            ProviderCapabilityStatus.READY
            if label is not SourceTimeLabel.UNVERIFIED
            else ProviderCapabilityStatus.ERROR
        )
    profile = create_stock_certification(
        observed_at=now,
        endpoint_url=endpoint_url,
        capabilities=ProviderCapabilities.model_validate(statuses),
        source_time_label=label,
    )
    write_live_certification(Path(output_path), profile)
    return profile


async def certify_board_indexes(
    *,
    client: object,
    request_controller: object,
    observed_at: datetime,
    endpoint_url: str,
    output_path: Path,
) -> IndexLiveCertification:
    """Probe every approved index independently and persist sanitized evidence."""

    now = _canonical_observed_at(observed_at)
    calendar = await _call_frame(
        client=client,
        request_controller=request_controller,
        operation=TushareOperation.TRADING_CALENDAR,
        endpoint="trade_cal",
        work_key="live-index-calendar",
        kwargs={
            "exchange": "SSE",
            "start_date": (now.date() - timedelta(days=14)).strftime("%Y%m%d"),
            "end_date": now.strftime("%Y%m%d"),
            "fields": _CALENDAR_FIELDS,
        },
    )
    _, reference_date = _calendar_dates(calendar, now.date())
    statuses = {
        code: TushareMarketIndexCapabilityStatus.UNVERIFIED for code in MarketIndexCode
    }
    minute_samples: list[pd.DataFrame] = []
    stop = False
    for code in MarketIndexCode:
        if stop:
            break
        outcomes: list[TushareMarketIndexCapabilityStatus] = []
        try:
            minutes = await _call_frame(
                client=client,
                request_controller=request_controller,
                operation=TushareOperation.INDEX_MINUTES,
                endpoint="idx_mins",
                work_key=f"live-index-minutes-{code.value}",
                kwargs={
                    "ts_code": code.value,
                    "freq": "5min",
                    "start_date": f"{now:%Y-%m-%d} 09:30:00",
                    "end_date": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "fields": _INDEX_MINUTE_FIELDS,
                },
            )
            _require_rows(
                minutes,
                {"ts_code", "trade_time", "open", "high", "low", "close", "vol", "amount"},
            )
            if set(minutes["ts_code"].astype(str)) != {code.value}:
                raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, "idx_mins")
            minute_samples.append(minutes)
            outcomes.append(TushareMarketIndexCapabilityStatus.READY)
        except (RequestControlError, TushareProviderError) as error:
            outcomes.append(_index_status(error))
            stop = _is_rate_limited(error)

        if not stop:
            try:
                daily = await _call_frame(
                    client=client,
                    request_controller=request_controller,
                    operation=TushareOperation.INDEX_DAILY,
                    endpoint="index_daily",
                    work_key=f"live-index-daily-{code.value}",
                    kwargs={
                        "ts_code": code.value,
                        "start_date": reference_date.strftime("%Y%m%d"),
                        "end_date": reference_date.strftime("%Y%m%d"),
                        "fields": _INDEX_DAILY_FIELDS,
                    },
                )
                _require_rows(
                    daily,
                    {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"},
                )
                if set(daily["ts_code"].astype(str)) != {code.value}:
                    raise TushareProviderError(TushareErrorCode.INVALID_RESPONSE, "index_daily")
                outcomes.append(TushareMarketIndexCapabilityStatus.READY)
            except (RequestControlError, TushareProviderError) as error:
                outcomes.append(_index_status(error))
                stop = _is_rate_limited(error)
        statuses[code] = next(
            (
                status
                for status in outcomes
                if status is not TushareMarketIndexCapabilityStatus.READY
            ),
            TushareMarketIndexCapabilityStatus.READY,
        )

    label = _index_time_label(minute_samples, now)
    if label is TushareMarketIndexSourceTimeLabel.UNVERIFIED:
        statuses = {
            code: (
                TushareMarketIndexCapabilityStatus.ERROR
                if status is TushareMarketIndexCapabilityStatus.READY
                else status
            )
            for code, status in statuses.items()
        }
    profile = create_index_certification(
        observed_at=now,
        endpoint_url=endpoint_url,
        capabilities=statuses,
        source_time_label=label,
    )
    write_live_certification(Path(output_path), profile)
    return profile


__all__ = ["LiveProbeWindowError", "certify_board_indexes", "certify_stock"]
