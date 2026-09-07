"""Explicitly authorized, fail-closed live Tushare contract evidence.

This module is safe during the default offline suite: every network test requires
an independent process-local authorization flag before constructing a client.
Only allowlisted observations may be printed; raw frames, exceptions, request
arguments, credentials, and authorization responses never leave the test process.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as wall_time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pydantic import ValidationError

from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.market_data.aggregation import aggregate_provisional_daily_bar
from trade_plan_monitor.market_data.models import (
    ProviderCapabilities,
    ProviderCapabilityStatus,
)
from trade_plan_monitor.market_data.reconciliation import (
    CloseReconciliationStatus,
    reconcile_daily_close,
)
from trade_plan_monitor.market_data.sessions import (
    SourceTimeLabel,
    SourceTimeMappingUnverifiedError,
    expected_minute_ends,
    normalize_source_minute,
)
from trade_plan_monitor.market_data.tushare import (
    TushareErrorCode,
    TushareMarketDataProvider,
    TushareProviderError,
)
from trade_plan_monitor.market_data.tushare_client import (
    TushareClientConfigurationError,
    create_tushare_client,
)
from trade_plan_monitor.runtime.health import (
    DatabaseHealthSnapshot,
    DeliveryHealthSnapshot,
    ExecutorHealthSnapshot,
    ProviderHealthSnapshot,
    RuntimeHealthDetails,
    RuntimeResourceStatus,
    RuntimeServiceStatus,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.runtime.service import RuntimeLifecycleService
from trade_plan_monitor.web.routers.health import ProviderHealthView

_ROOT = Path(__file__).parents[2]
_PROJECT_CONFIG = _ROOT / "config" / "app.yaml"
_REPORTS = (
    _ROOT / "docs" / "verification" / "tushare-live.md",
    _ROOT / "docs" / "verification" / "tushare-live.zh-CN.md",
)
_HEALTH_MATRIX = _ROOT / "web" / "src" / "components" / "health" / "HealthMatrix.vue"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_AUTHORIZATION_ENV = "TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE"
_OBSERVATION_ENV = "T058_REPORT_OBSERVATIONS"
_ENDPOINT = "https://api.quicksync.cn"
_PROBE_SYMBOL = "600000.SH"
_BATCH_SYMBOLS = (
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
_MIN_CALL_INTERVAL_SECONDS = 1.25
_TIMEOUT_SECONDS = 15
_MIN_CLOSE_OBSERVATION_TIME = wall_time(15, 20)
_MINUTE_FIELDS = "ts_code,time,open,close,high,low,vol,amount"
_CURRENT_DAY_FIELDS = "ts_code,freq,time,open,close,high,low,vol,amount"
_CALENDAR_FIELDS = "exchange,cal_date,is_open,pretrade_date"
_LIMIT_FIELDS = "trade_date,ts_code,up_limit,down_limit"
_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,vol,amount"
_CAPABILITY_FIELDS = {
    "daily": "daily_bars",
    "rt_min": "realtime_minutes",
    "rt_min_daily": "current_day_minutes",
    "stk_limit": "daily_limits",
    "trade_cal": "trading_calendar",
}
_CAPABILITY_OPERATIONS = frozenset(_CAPABILITY_FIELDS)
_VISIBLE_BLOCK_STATUSES = frozenset({"BLOCKED_PERMISSION", "ERROR", "RATE_LIMITED"})
_ACCEPTED_CAPABILITY_STATUSES = frozenset({"READY", *_VISIBLE_BLOCK_STATUSES})
_VISIBLE_STATUS_PRESENTATIONS = {
    "BLOCKED_PERMISSION": 'BLOCKED_PERMISSION: { label: "权限阻断", marker: "■" }',
    "ERROR": 'ERROR: { label: "错误", marker: "×" }',
    "RATE_LIMITED": 'RATE_LIMITED: { label: "限流", marker: "◆" }',
}
_REQUIRED_REPORT_TOKENS = (
    "T058",
    "P18",
    "Asia/Shanghai",
    "+08:00",
    "rt_min",
    "rt_min_daily",
    "trade_cal",
    "stk_limit",
    "daily",
    "10-symbol",
    "15:00",
    "TUSHARE_TOKEN",
)
_REPORT_SECRET_PATTERNS = (
    re.compile(r"run[.]quicksync[.]cn/code/", re.IGNORECASE),
    re.compile(r"Authorization\s*:", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"TUSHARE_TOKEN\s*(?:=|:)\s*[^`\s]+", re.IGNORECASE),
)
_CANONICAL_EVIDENCE_PATTERN = re.compile(
    r"<!-- T058-CANONICAL-EVIDENCE-START -->\s*"
    r"```json\s*(?P<payload>\{.*?\})\s*```\s*"
    r"<!-- T058-CANONICAL-EVIDENCE-END -->",
    re.DOTALL,
)
_EXPECTED_CANONICAL_EVIDENCE = {
    "acceptanceBranch": "VISIBLE_BLOCK",
    "baseline": "eee65fd9ede37cee229c0147ba2ddb55a5f311d5",
    "capabilities": {
        "daily": "ERROR",
        "rt_min": "ERROR",
        "rt_min_daily": "ERROR",
        "stk_limit": "ERROR",
        "trade_cal": "ERROR",
    },
    "calls": [
        {
            "latencyMs": 7,
            "operation": "trade_cal",
            "providerErrorCode": "TRANSIENT",
            "result": "ERROR",
            "rows": 0,
            "sample": 1,
            "startedAt": "2026-08-31T11:24:21+08:00",
        },
        {
            "latencyMs": 24,
            "operation": "stk_limit",
            "providerErrorCode": "TRANSIENT",
            "result": "ERROR",
            "rows": 0,
            "sample": 1,
            "startedAt": "2026-08-31T11:24:22+08:00",
        },
        {
            "latencyMs": 2,
            "operation": "daily",
            "providerErrorCode": "TRANSIENT",
            "result": "ERROR",
            "rows": 0,
            "sample": 1,
            "startedAt": "2026-08-31T11:24:23+08:00",
        },
        {
            "latencyMs": 13,
            "operation": "rt_min",
            "providerErrorCode": "TRANSIENT",
            "result": "ERROR",
            "rows": 0,
            "sample": 1,
            "startedAt": "2026-08-31T11:24:24+08:00",
        },
        {
            "latencyMs": 26,
            "operation": "rt_min_daily",
            "providerErrorCode": "TRANSIENT",
            "result": "ERROR",
            "rows": 0,
            "sample": 1,
            "startedAt": "2026-08-31T11:24:25+08:00",
        },
        {
            "latencyMs": 18,
            "operation": "rt_min_daily",
            "providerErrorCode": "TRANSIENT",
            "result": "ERROR",
            "rows": 0,
            "sample": 2,
            "startedAt": "2026-08-31T11:24:26+08:00",
        },
    ],
    "endpointHost": "api.quicksync.cn",
    "finalMinute": None,
    "officialCloseRows": None,
    "pacingSeconds": 1.0,
    "rateLimitObservation": "NO_429_UNDER_PACING",
    "requestedSymbols": 10,
    "returnedSymbols": 0,
    "sourceTimeLabel": "SourceTimeLabel.UNVERIFIED",
    "timezone": "Asia/Shanghai",
}


class _SanitizedCallError(RuntimeError):
    """One provider failure reduced to stable, provider-independent fields."""

    def __init__(
        self,
        operation: str,
        provider_error_code: str,
        capability_status: str,
    ) -> None:
        self.operation = operation
        self.provider_error_code = provider_error_code
        self.capability_status = capability_status
        super().__init__(f"{operation}:{capability_status}")


@dataclass(frozen=True, slots=True)
class _CallObservation:
    operation: str
    started_at: str
    latency_ms: int
    row_count: int
    columns: tuple[str, ...]
    returned_symbol_count: int
    first_source_time: str | None
    last_source_time: str | None
    capability_status: str
    error_code: str | None


@dataclass(slots=True)
class _LiveEvidence:
    capability_statuses: dict[str, str] = field(default_factory=dict)
    call_semantics: tuple[dict[str, object], ...] = ()
    source_time_label: SourceTimeLabel = SourceTimeLabel.UNVERIFIED
    requested_symbols: int = len(_BATCH_SYMBOLS)
    returned_symbols: int = 0
    final_minute: str | None = None
    official_close_rows: int | None = None
    market_window_outcome: str = "RUN"


@dataclass(frozen=True, slots=True)
class _LiveContext:
    client: _PacedRecordingClient
    observed_at: datetime
    evidence: _LiveEvidence = field(default_factory=_LiveEvidence)


class _RuntimeClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    async def sleep_until(self, deadline: datetime) -> None:
        self.current = deadline


class _RuntimeScheduler:
    def __init__(self, deadline: MarketDeadline) -> None:
        self.deadline = deadline

    def next_deadline(self, *, after: datetime | None = None) -> MarketDeadline | None:
        return self.deadline if after is None else None

    async def wait_for_next(self, *, after: datetime | None = None) -> MarketDeadline | None:
        del after
        return None


class _RuntimeDispatcher:
    async def aclose(self) -> None:
        return None


class _RuntimeRequestController:
    def close(self) -> None:
        return None


class _OfflineTransientClient:
    def daily(self, **kwargs: Any) -> pd.DataFrame:
        del kwargs
        raise ConnectionError("connection failed")


class _OfflineInvalidResponseClient:
    def daily(self, **kwargs: Any) -> object:
        del kwargs
        return object()


class _OfflineRateLimitedClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def daily(self, **kwargs: Any) -> pd.DataFrame:
        del kwargs
        self.calls.append("daily")
        raise TushareProviderError(TushareErrorCode.RATE_LIMITED, "daily")

    def trade_cal(self, **kwargs: Any) -> pd.DataFrame:
        del kwargs
        self.calls.append("trade_cal")
        return pd.DataFrame()


class _UnreadableEnvironment(Mapping[str, str]):
    def __getitem__(self, key: str) -> str:
        raise AssertionError(f"environment must not be read: {key}")

    def __iter__(self):  # type: ignore[no-untyped-def]
        raise AssertionError("environment must not be read")

    def __len__(self) -> int:
        raise AssertionError("environment must not be read")


class _PacedRecordingClient:
    """Pace SDK calls and retain only allowlisted observations plus in-memory frames."""

    def __init__(self, client: object) -> None:
        self._client = client
        self._last_started_monotonic: float | None = None
        self._started_monotonic: list[float] = []
        self.observations: list[_CallObservation] = []
        self.last_frames: dict[str, pd.DataFrame] = {}

    def rt_min(self, **kwargs: Any) -> pd.DataFrame:
        return self._call("rt_min", kwargs)

    def rt_min_daily(self, **kwargs: Any) -> pd.DataFrame:
        return self._call("rt_min_daily", kwargs)

    def trade_cal(self, **kwargs: Any) -> pd.DataFrame:
        return self._call("trade_cal", kwargs)

    def stk_limit(self, **kwargs: Any) -> pd.DataFrame:
        return self._call("stk_limit", kwargs)

    def daily(self, **kwargs: Any) -> pd.DataFrame:
        return self._call("daily", kwargs)

    def assert_pacing(self) -> None:
        for previous, current in zip(
            self._started_monotonic,
            self._started_monotonic[1:],
            strict=False,
        ):
            if current - previous < _MIN_CALL_INTERVAL_SECONDS - 0.01:
                _fail("T058_LIVE_PACING_INTERVAL_VIOLATION")

    def _record_failure(
        self,
        *,
        operation: str,
        started_at: datetime,
        latency_ms: int,
        error_code: str,
        capability_status: str,
    ) -> None:
        self.observations.append(
            _CallObservation(
                operation=operation,
                started_at=started_at.isoformat(timespec="seconds"),
                latency_ms=latency_ms,
                row_count=0,
                columns=(),
                returned_symbol_count=0,
                first_source_time=None,
                last_source_time=None,
                capability_status=capability_status,
                error_code=error_code,
            )
        )

    def _call(self, operation: str, kwargs: dict[str, Any]) -> pd.DataFrame:
        now_monotonic = time.monotonic()
        if self._last_started_monotonic is not None:
            remaining = _MIN_CALL_INTERVAL_SECONDS - (now_monotonic - self._last_started_monotonic)
            if remaining > 0:
                time.sleep(remaining)

        started_monotonic = time.monotonic()
        self._last_started_monotonic = started_monotonic
        self._started_monotonic.append(started_monotonic)
        started_at = _shanghai_now()
        try:
            method = getattr(self._client, operation)
            frame = method(**kwargs)
        except Exception as error:
            latency_ms = round((time.monotonic() - started_monotonic) * 1_000)
            error_code, capability_status = _classify_error(operation, error)
            self._record_failure(
                operation=operation,
                started_at=started_at,
                latency_ms=latency_ms,
                error_code=error_code,
                capability_status=capability_status,
            )
            raise _SanitizedCallError(operation, error_code, capability_status) from None

        latency_ms = round((time.monotonic() - started_monotonic) * 1_000)
        if not isinstance(frame, pd.DataFrame):
            self._record_failure(
                operation=operation,
                started_at=started_at,
                latency_ms=latency_ms,
                error_code="INVALID_RESPONSE",
                capability_status="ERROR",
            )
            raise _SanitizedCallError(operation, "INVALID_RESPONSE", "ERROR") from None
        if latency_ms > _TIMEOUT_SECONDS * 1_000:
            self._record_failure(
                operation=operation,
                started_at=started_at,
                latency_ms=latency_ms,
                error_code="TRANSIENT",
                capability_status="ERROR",
            )
            raise _SanitizedCallError(operation, "TRANSIENT", "ERROR") from None

        safe_frame = frame.copy(deep=True)
        self.last_frames[operation] = safe_frame
        source_times = _safe_source_times(safe_frame)
        symbols = _safe_symbols(safe_frame)
        self.observations.append(
            _CallObservation(
                operation=operation,
                started_at=started_at.isoformat(timespec="seconds"),
                latency_ms=latency_ms,
                row_count=len(safe_frame.index),
                columns=tuple(sorted(str(column) for column in safe_frame.columns)),
                returned_symbol_count=len(symbols),
                first_source_time=source_times[0] if source_times else None,
                last_source_time=source_times[-1] if source_times else None,
                capability_status="READY",
                error_code=None,
            )
        )
        return frame


def _call(client: _PacedRecordingClient, operation: str, **kwargs: Any) -> pd.DataFrame:
    return getattr(client, operation)(**kwargs)


def _fail(code: str) -> None:
    pytest.fail(code, pytrace=False)


def _shanghai_now() -> datetime:
    return datetime.now(tz=_SHANGHAI)


def _classify_error(operation: str, error: Exception) -> tuple[str, str]:
    provider_error = (
        error
        if isinstance(error, TushareProviderError)
        else TushareMarketDataProvider._safe_provider_error(operation, error)
    )
    if provider_error.code is TushareErrorCode.BLOCKED_PERMISSION:
        capability_status = ProviderCapabilityStatus.BLOCKED_PERMISSION
    elif provider_error.code is TushareErrorCode.RATE_LIMITED:
        capability_status = ProviderCapabilityStatus.RATE_LIMITED
    else:
        capability_status = ProviderCapabilityStatus.ERROR
    return provider_error.code.value, capability_status.value


def _probe_call(
    client: _PacedRecordingClient,
    statuses: dict[str, str],
    operation: str,
    **kwargs: Any,
) -> pd.DataFrame | None:
    try:
        frame = _call(client, operation, **kwargs)
    except _SanitizedCallError as error:
        statuses[operation] = error.capability_status
        if error.provider_error_code == TushareErrorCode.RATE_LIMITED.value:
            _fail("T058_LIVE_RATE_LIMITED_STOP")
        return None
    statuses[operation] = "READY"
    return frame


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _realtime_contract_window(observed_at: datetime, *, today_open: bool | None) -> bool:
    if today_open is not True:
        return False
    local_time = observed_at.astimezone(_SHANGHAI).time()
    return (
        wall_time(9, 32) <= local_time <= wall_time(11, 28)
        or wall_time(13, 2) <= local_time <= wall_time(14, 56)
        or local_time >= _MIN_CLOSE_OBSERVATION_TIME
    )


def _require_columns(frame: pd.DataFrame, operation: str, required: set[str]) -> None:
    columns = [str(column) for column in frame.columns]
    if len(columns) != len(set(columns)) or not required.issubset(columns):
        _fail(f"T058_LIVE_{operation.upper()}_SCHEMA_UNVERIFIED")


def _safe_source_times(frame: pd.DataFrame) -> tuple[str, ...]:
    if "time" not in frame.columns:
        return ()
    parsed = pd.to_datetime(frame["time"], errors="coerce")
    values = sorted(
        value.to_pydatetime().replace(tzinfo=_SHANGHAI).isoformat(timespec="minutes")
        for value in parsed
        if not pd.isna(value)
    )
    return tuple(values)


def _safe_symbols(frame: pd.DataFrame) -> tuple[str, ...]:
    symbol_column = "ts_code" if "ts_code" in frame.columns else "code"
    if symbol_column not in frame.columns:
        return ()
    return tuple(sorted({str(value) for value in frame[symbol_column].dropna()}))


def _source_datetimes(frame: pd.DataFrame, observed_at: datetime) -> tuple[datetime, ...]:
    parsed = pd.to_datetime(frame["time"], errors="coerce")
    values = tuple(
        sorted(
            value.to_pydatetime().replace(tzinfo=_SHANGHAI)
            for value in parsed
            if not pd.isna(value) and value.date() == observed_at.date()
        )
    )
    if not values:
        _fail("T058_LIVE_SOURCE_TIME_ROWS_UNAVAILABLE")
    return values


def _derive_source_time_label(
    samples: tuple[pd.DataFrame, pd.DataFrame],
    observed_at: datetime,
) -> SourceTimeLabel:
    conclusions: list[SourceTimeLabel] = []
    expected = set(expected_minute_ends(observed_at.date(), is_open=True))

    for sample in samples:
        raw_times = _source_datetimes(sample, observed_at)
        candidates: list[SourceTimeLabel] = []
        for label in (SourceTimeLabel.START, SourceTimeLabel.END):
            try:
                mapped = {
                    normalize_source_minute(value, label=label, is_open=True) for value in raw_times
                }
            except ValueError:
                continue
            if mapped.issubset(expected) and min(expected) in mapped:
                candidates.append(label)
        if len(candidates) != 1:
            _fail("T058_LIVE_SOURCE_TIME_MAPPING_UNVERIFIED")
        conclusions.append(candidates[0])

    if len(set(conclusions)) != 1:
        _fail("T058_LIVE_SOURCE_TIME_MAPPING_UNSTABLE")
    return conclusions[0]


def _calendar_dates(frame: pd.DataFrame, today: date) -> tuple[bool, date]:
    _require_columns(frame, "trade_cal", {"exchange", "cal_date", "is_open", "pretrade_date"})
    parsed: list[tuple[date, bool]] = []
    for row in frame.to_dict(orient="records"):
        try:
            cal_date = datetime.strptime(str(row["cal_date"]), "%Y%m%d").date()
            is_open = int(row["is_open"]) == 1
        except TypeError, ValueError:
            continue
        parsed.append((cal_date, is_open))
    today_open = any(value == today and is_open for value, is_open in parsed)
    previous = [value for value, is_open in parsed if is_open and value < today]
    if not previous:
        _fail("T058_LIVE_REFERENCE_TRADING_DATE_UNAVAILABLE")
    return today_open, max(previous)


def _assert_requested_symbol_boundary(frame: pd.DataFrame) -> None:
    _require_columns(
        frame,
        "rt_min",
        {"ts_code", "time", "open", "close", "high", "low", "vol", "amount"},
    )
    returned = set(_safe_symbols(frame))
    if returned != set(_BATCH_SYMBOLS):
        _fail("T058_LIVE_TEN_SYMBOL_BATCH_UNVERIFIED")


def _decimal(value: object, code: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation, TypeError, ValueError:
        _fail(code)
    if not result.is_finite():
        _fail(code)
    return result


def _assert_realtime_units(
    raw_frame: pd.DataFrame,
    normalized: list[Any],
    label: SourceTimeLabel,
) -> None:
    records = raw_frame.to_dict(orient="records")
    matched = 0
    for bar in normalized:
        for row in records:
            if str(row.get("ts_code")) != bar.symbol:
                continue
            raw_time = pd.to_datetime(row.get("time"), errors="coerce")
            if pd.isna(raw_time):
                continue
            mapped = normalize_source_minute(
                raw_time.to_pydatetime().replace(tzinfo=_SHANGHAI),
                label=label,
                is_open=True,
            )
            if mapped != bar.bar_end:
                continue
            if _decimal(row.get("close"), "T058_LIVE_REALTIME_PRICE_UNVERIFIED") * 100 != Decimal(
                bar.close_fen
            ):
                _fail("T058_LIVE_REALTIME_PRICE_UNIT_MISMATCH")
            if _decimal(row.get("vol"), "T058_LIVE_REALTIME_VOLUME_UNVERIFIED") != Decimal(
                bar.volume_shares
            ):
                _fail("T058_LIVE_REALTIME_VOLUME_UNIT_MISMATCH")
            if _decimal(row.get("amount"), "T058_LIVE_REALTIME_AMOUNT_UNVERIFIED") != Decimal(
                bar.amount_yuan
            ):
                _fail("T058_LIVE_REALTIME_AMOUNT_UNIT_MISMATCH")
            matched += 1
            break
    if matched == 0:
        _fail("T058_LIVE_REALTIME_UNIT_SAMPLE_UNAVAILABLE")


def _assert_daily_units(raw_frame: pd.DataFrame, normalized: list[Any]) -> None:
    records = raw_frame.to_dict(orient="records")
    matched = 0
    for bar in normalized:
        for row in records:
            if str(row.get("ts_code")) != bar.symbol:
                continue
            if str(row.get("trade_date")) != bar.trade_date.strftime("%Y%m%d"):
                continue
            if _decimal(row.get("vol"), "T058_LIVE_DAILY_VOLUME_UNVERIFIED") * 100 != Decimal(
                bar.volume_shares
            ):
                _fail("T058_LIVE_DAILY_VOLUME_UNIT_MISMATCH")
            if _decimal(row.get("amount"), "T058_LIVE_DAILY_AMOUNT_UNVERIFIED") * 1_000 != Decimal(
                bar.amount_yuan
            ):
                _fail("T058_LIVE_DAILY_AMOUNT_UNIT_MISMATCH")
            matched += 1
            break
    if matched == 0:
        _fail("T058_LIVE_DAILY_UNIT_SAMPLE_UNAVAILABLE")


def _assert_unverified_mapping_blocks_provider(
    client: _PacedRecordingClient,
    today: date,
) -> None:
    calls_before = len(client.observations)
    provider = TushareMarketDataProvider(
        client,
        now=_shanghai_now,
        is_open_on=lambda value: value == today,
        probe_symbol=_PROBE_SYMBOL,
    )
    with pytest.raises(SourceTimeMappingUnverifiedError, match="UNVERIFIED"):
        provider.current_day_minutes(_PROBE_SYMBOL)
    if len(client.observations) != calls_before:
        _fail("T058_LIVE_UNVERIFIED_MAPPING_REACHED_PROVIDER")


def _assert_application_remains_visibly_blocked(
    statuses: dict[str, str],
    observed_at: datetime,
) -> None:
    if (
        set(statuses) != _CAPABILITY_OPERATIONS
        or not set(statuses.values()).issubset(_ACCEPTED_CAPABILITY_STATUSES)
        or not set(statuses.values()).intersection(_VISIBLE_BLOCK_STATUSES)
    ):
        _fail("T058_LIVE_VISIBLE_BLOCK_INPUT_INVALID")

    capabilities = ProviderCapabilities(
        **{
            field_name: ProviderCapabilityStatus(statuses[operation])
            for operation, field_name in _CAPABILITY_FIELDS.items()
        }
    )
    if RuntimeLifecycleService._all_capabilities_ready(capabilities):
        _fail("T058_LIVE_RUNTIME_ACCEPTED_BLOCKED_CAPABILITIES")

    providers = tuple(
        ProviderHealthSnapshot(
            capability=capability,
            status=ProviderCapabilityStatus(statuses[capability]),
            checked_at=observed_at,
            latency_ms=0,
            error_code=None if statuses[capability] == "READY" else statuses[capability],
            next_retry_at=None,
        )
        for capability in sorted(_CAPABILITY_OPERATIONS)
    )
    details = RuntimeHealthDetails(
        providers=providers,
        executor=ExecutorHealthSnapshot(max_workers=2, active_count=0, waiting_count=0),
        database=DatabaseHealthSnapshot(
            status=RuntimeResourceStatus.READY,
            wal_status=RuntimeResourceStatus.READY,
        ),
        delivery=DeliveryHealthSnapshot(
            status=RuntimeResourceStatus.READY,
            pending_count=0,
            failed_count=0,
        ),
    )
    bar_end = datetime.combine(observed_at.date(), wall_time(9, 31), _SHANGHAI)
    deadline = MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=observed_at.date(),
        bar_end=bar_end,
        due_at=bar_end + timedelta(seconds=12),
    )
    service = RuntimeLifecycleService(
        clock=_RuntimeClock(observed_at),
        validate_configuration=lambda: None,
        open_database=lambda: None,
        load_active_symbols=lambda: (_PROBE_SYMBOL,),
        probe_capabilities=lambda: capabilities,
        refresh_references=lambda _trade_date: None,
        recover_startup=lambda _trade_date: None,
        scheduler=_RuntimeScheduler(deadline),
        run_deadline=lambda _deadline: None,
        dispatcher=_RuntimeDispatcher(),
        request_controller=_RuntimeRequestController(),
        checkpoint_wal=lambda: None,
        close_database=lambda: None,
        health_details=lambda: details,
    )
    startup = asyncio.run(service.start())
    health = service.health()
    owned_task_count = service.owned_task_count
    asyncio.run(service.stop())
    if (
        startup.status is not RuntimeServiceStatus.DEGRADED
        or startup.read_only is not True
        or startup.next_poll_at is not None
        or health.status is not RuntimeServiceStatus.DEGRADED
        or health.read_only is not True
        or health.next_poll_at is not None
        or owned_task_count != 0
    ):
        _fail("T058_LIVE_RUNTIME_BLOCK_NOT_VISIBLE")

    api_statuses: dict[str, str] = {}
    for provider in health.providers:
        view = ProviderHealthView.model_validate(provider.model_dump(mode="python"))
        serialized = view.model_dump(mode="json", by_alias=True)
        api_statuses[str(serialized["capability"])] = str(serialized["status"])
    if api_statuses != statuses:
        _fail("T058_LIVE_HEALTH_API_BLOCK_NOT_VISIBLE")

    health_matrix = _HEALTH_MATRIX.read_text(encoding="utf-8")
    visible_contract = (
        ':data-status="provider.status"',
        "{{ providerStatus(provider.status).label }}",
    )
    if any(fragment not in health_matrix for fragment in visible_contract):
        _fail("T058_LIVE_HEALTH_UI_BLOCK_NOT_VISIBLE")
    visible_statuses = set(statuses.values()).intersection(_VISIBLE_BLOCK_STATUSES)
    if any(
        _VISIBLE_STATUS_PRESENTATIONS[status] not in health_matrix for status in visible_statuses
    ):
        _fail("T058_LIVE_HEALTH_UI_BLOCK_NOT_VISIBLE")


def _stable_observed_statuses(client: _PacedRecordingClient) -> dict[str, str]:
    observed: dict[str, set[str]] = {}
    for observation in client.observations:
        if observation.operation not in _CAPABILITY_OPERATIONS:
            continue
        observed.setdefault(observation.operation, set()).add(observation.capability_status)
    if any(len(values) != 1 for values in observed.values()):
        _fail("T058_LIVE_CAPABILITY_OBSERVATION_UNSTABLE")
    return {operation: next(iter(values)) for operation, values in observed.items()}


def _normalized_call_semantics(
    observations: list[_CallObservation],
) -> tuple[dict[str, object], ...]:
    sample_counts: dict[str, int] = {}
    semantics: list[dict[str, object]] = []
    for observation in observations:
        sample = sample_counts.get(observation.operation, 0) + 1
        sample_counts[observation.operation] = sample
        semantics.append(
            {
                "operation": observation.operation,
                "sample": sample,
                "providerErrorCode": observation.error_code,
                "result": observation.capability_status,
                "rows": observation.row_count,
            }
        )
    return tuple(semantics)


def _canonical_evidence(report: str) -> dict[str, object]:
    matches = list(_CANONICAL_EVIDENCE_PATTERN.finditer(report))
    if len(matches) != 1:
        _fail("T058_LIVE_CANONICAL_EVIDENCE_MISSING")
    try:
        payload = json.loads(matches[0].group("payload"))
    except json.JSONDecodeError:
        _fail("T058_LIVE_CANONICAL_EVIDENCE_INVALID")
    if not isinstance(payload, dict):
        _fail("T058_LIVE_CANONICAL_EVIDENCE_INVALID")
    return payload


def _report_semantics(evidence: dict[str, object]) -> dict[str, object]:
    keys = (
        "acceptanceBranch",
        "capabilities",
        "endpointHost",
        "finalMinute",
        "officialCloseRows",
        "requestedSymbols",
        "returnedSymbols",
        "sourceTimeLabel",
        "timezone",
    )
    if any(key not in evidence for key in keys):
        _fail("T058_LIVE_REPORT_SEMANTICS_INCOMPLETE")
    raw_calls = evidence.get("calls")
    if not isinstance(raw_calls, list) or not 1 <= len(raw_calls) <= 32:
        _fail("T058_LIVE_REPORT_CALL_SEMANTICS_INVALID")
    call_keys = ("operation", "sample", "providerErrorCode", "result", "rows")
    calls: list[dict[str, object]] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict) or any(key not in raw_call for key in call_keys):
            _fail("T058_LIVE_REPORT_CALL_SEMANTICS_INVALID")
        calls.append({key: raw_call[key] for key in call_keys})
    semantics = {key: evidence[key] for key in keys}
    semantics["calls"] = calls
    return semantics


def _live_semantics(context: _LiveContext) -> dict[str, object]:
    evidence = context.evidence
    if set(evidence.capability_statuses) != _CAPABILITY_OPERATIONS or not evidence.call_semantics:
        _fail("T058_LIVE_REPORT_SESSION_EVIDENCE_INCOMPLETE")
    acceptance_branch = (
        "READY"
        if all(status == "READY" for status in evidence.capability_statuses.values())
        else "VISIBLE_BLOCK"
    )
    return {
        "acceptanceBranch": acceptance_branch,
        "capabilities": dict(sorted(evidence.capability_statuses.items())),
        "calls": [dict(call) for call in evidence.call_semantics],
        "endpointHost": "api.quicksync.cn",
        "finalMinute": evidence.final_minute,
        "officialCloseRows": evidence.official_close_rows,
        "requestedSymbols": evidence.requested_symbols,
        "returnedSymbols": evidence.returned_symbols,
        "sourceTimeLabel": f"SourceTimeLabel.{evidence.source_time_label.name}",
        "timezone": "Asia/Shanghai",
    }


def _emit_observations(
    client: _PacedRecordingClient,
    *,
    capability_statuses: dict[str, str],
    source_time_label: SourceTimeLabel,
    requested_symbols: int,
    returned_symbols: int,
    final_minute: str | None = None,
    official_close_rows: int | None = None,
) -> None:
    if os.environ.get(_OBSERVATION_ENV) != "1":
        return
    payload = {
        "capabilities": dict(sorted(capability_statuses.items())),
        "endpointHost": "api.quicksync.cn",
        "finalMinute": final_minute,
        "officialCloseRows": official_close_rows,
        "observations": [asdict(observation) for observation in client.observations],
        "pacingSeconds": _MIN_CALL_INTERVAL_SECONDS,
        "rateLimitObservation": "NOT_OBSERVED_UNDER_PACING",
        "requestedSymbols": requested_symbols,
        "returnedSymbols": returned_symbols,
        "sourceTimeLabel": f"SourceTimeLabel.{source_time_label.name}",
        "timezone": "Asia/Shanghai",
    }
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def _require_authorized_live_run(
    marker_expression: str,
    environment: Mapping[str, str],
) -> None:
    """Validate the explicitly selected live run before loading configuration."""

    if marker_expression.strip() != "live":
        pytest.skip("live Tushare tests require the explicit '-m live' selector")
    if environment.get(_AUTHORIZATION_ENV) != "1":
        pytest.fail("T058_LIVE_NETWORK_AUTHORIZATION_UNAVAILABLE", pytrace=False)


@pytest.fixture(scope="session")
def authorized_live_context(request: pytest.FixtureRequest) -> _LiveContext:
    observed_at = _shanghai_now()
    if not _realtime_contract_window(observed_at, today_open=True):
        pytest.skip("T058_LIVE_NOT_RUN_MARKET_WINDOW")
    marker_expression = str(request.config.getoption("markexpr")).strip()
    _require_authorized_live_run(marker_expression, os.environ)

    try:
        configuration = load_application_config(_PROJECT_CONFIG).tushare.model_copy(
            update={"api_url": _ENDPOINT, "timeout_seconds": _TIMEOUT_SECONDS}
        )
        raw_client = create_tushare_client(configuration)
    except (OSError, ValidationError, TushareClientConfigurationError):
        pytest.fail("T058_LIVE_CLIENT_INITIALIZATION_FAILED", pytrace=False)
    return _LiveContext(
        client=_PacedRecordingClient(raw_client),
        observed_at=observed_at,
    )


def test_live_harness_offline_safety_contract() -> None:
    with pytest.raises(pytest.skip.Exception):
        _require_authorized_live_run("not live", _UnreadableEnvironment())

    with pytest.raises(
        pytest.fail.Exception,
        match="T058_LIVE_NETWORK_AUTHORIZATION_UNAVAILABLE",
    ):
        _require_authorized_live_run("live", {})

    assert _realtime_contract_window(
        datetime(2026, 9, 5, 10, 0, tzinfo=_SHANGHAI),
        today_open=False,
    ) is False
    assert _realtime_contract_window(
        datetime(2026, 9, 7, 8, 0, tzinfo=_SHANGHAI),
        today_open=True,
    ) is False
    assert _realtime_contract_window(
        datetime(2026, 9, 7, 10, 0, tzinfo=_SHANGHAI),
        today_open=True,
    ) is True

    raw_client = _OfflineRateLimitedClient()
    client = _PacedRecordingClient(raw_client)
    statuses: dict[str, str] = {}
    with pytest.raises(pytest.fail.Exception, match="T058_LIVE_RATE_LIMITED_STOP"):
        _probe_call(client, statuses, "daily")
        _probe_call(client, statuses, "trade_cal")
    assert raw_client.calls == ["daily"]
    assert statuses == {"daily": "RATE_LIMITED"}
    assert _MIN_CALL_INTERVAL_SECONDS >= 1.25


@pytest.mark.live
def test_authorized_live_capabilities_pacing_and_intraday_contract(
    authorized_live_context: _LiveContext,
) -> None:
    context = authorized_live_context
    client = context.client
    observed_at = _shanghai_now()
    today = observed_at.date()
    if today.weekday() >= 5:
        context.evidence.market_window_outcome = "NOT_RUN_MARKET_WINDOW"
        pytest.skip("T058_LIVE_NOT_RUN_MARKET_WINDOW")
    calendar_start = today - timedelta(days=14)
    statuses: dict[str, str] = {}
    calendar = _probe_call(
        client,
        statuses,
        "trade_cal",
        exchange="",
        start_date=calendar_start.strftime("%Y%m%d"),
        end_date=today.strftime("%Y%m%d"),
        fields=_CALENDAR_FIELDS,
    )
    today_open: bool | None = None
    reference_date = _previous_weekday(today)
    if calendar is not None:
        today_open, reference_date = _calendar_dates(calendar, today)
    if not _realtime_contract_window(observed_at, today_open=today_open):
        context.evidence.market_window_outcome = "NOT_RUN_MARKET_WINDOW"
        pytest.skip("T058_LIVE_NOT_RUN_MARKET_WINDOW")

    limits = _probe_call(
        client,
        statuses,
        "stk_limit",
        trade_date=reference_date.strftime("%Y%m%d"),
        fields=_LIMIT_FIELDS,
    )
    if limits is not None:
        _require_columns(
            limits,
            "stk_limit",
            {"trade_date", "ts_code", "up_limit", "down_limit"},
        )
        if limits.empty:
            statuses["stk_limit"] = "UNVERIFIED_EMPTY"

    daily = _probe_call(
        client,
        statuses,
        "daily",
        ts_code=_PROBE_SYMBOL,
        start_date=reference_date.strftime("%Y%m%d"),
        end_date=reference_date.strftime("%Y%m%d"),
        fields=_DAILY_FIELDS,
    )
    if daily is not None:
        _require_columns(
            daily,
            "daily",
            {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"},
        )
        if daily.empty:
            statuses["daily"] = "UNVERIFIED_EMPTY"

    batch = _probe_call(
        client,
        statuses,
        "rt_min",
        ts_code=",".join(_BATCH_SYMBOLS),
        freq="1MIN",
        fields=_MINUTE_FIELDS,
    )
    if batch is not None:
        _assert_requested_symbol_boundary(batch)

    current_day_samples: list[pd.DataFrame] = []
    for _ in range(2):
        current_day = _probe_call(
            client,
            statuses,
            "rt_min_daily",
            ts_code=_PROBE_SYMBOL,
            freq="1MIN",
            fields=_CURRENT_DAY_FIELDS,
        )
        if current_day is None:
            continue
        symbol_column = "ts_code" if "ts_code" in current_day.columns else "code"
        _require_columns(
            current_day,
            "rt_min_daily",
            {
                symbol_column,
                "freq",
                "time",
                "open",
                "close",
                "high",
                "low",
                "vol",
                "amount",
            },
        )
        if current_day.empty:
            statuses["rt_min_daily"] = "UNVERIFIED_EMPTY"
        else:
            current_day_samples.append(current_day)

    source_time_label = SourceTimeLabel.UNVERIFIED
    contract_window = _realtime_contract_window(observed_at, today_open=today_open)
    if contract_window and len(current_day_samples) == 2:
        source_time_label = _derive_source_time_label(
            (current_day_samples[0], current_day_samples[1]),
            observed_at,
        )

    if (
        source_time_label is not SourceTimeLabel.UNVERIFIED
        and statuses.get("rt_min") == "READY"
        and statuses.get("daily") == "READY"
    ):
        provider = TushareMarketDataProvider(
            client,
            now=_shanghai_now,
            is_open_on=lambda value: value == today,
            source_time_label=source_time_label,
            probe_symbol=_PROBE_SYMBOL,
        )
        try:
            normalized_realtime = provider.realtime_minutes(_BATCH_SYMBOLS)
            raw_realtime = client.last_frames["rt_min"]
            normalized_daily = provider.daily_bars(_PROBE_SYMBOL, reference_date, reference_date)
            raw_daily = client.last_frames["daily"]
        except KeyError, TushareProviderError, _SanitizedCallError:
            _fail("T058_LIVE_NORMALIZATION_FAILED")
        _assert_realtime_units(raw_realtime, normalized_realtime, source_time_label)
        _assert_daily_units(raw_daily, normalized_daily)

    client.assert_pacing()
    returned_symbols = len(set(_safe_symbols(batch))) if batch is not None else 0
    context.evidence.capability_statuses = dict(statuses)
    context.evidence.call_semantics = _normalized_call_semantics(client.observations)
    context.evidence.source_time_label = source_time_label
    context.evidence.returned_symbols = returned_symbols
    _emit_observations(
        client,
        capability_statuses=statuses,
        source_time_label=source_time_label,
        requested_symbols=len(_BATCH_SYMBOLS),
        returned_symbols=returned_symbols,
    )
    if set(statuses) != _CAPABILITY_OPERATIONS:
        _fail("T058_LIVE_CAPABILITY_SET_INCOMPLETE")
    stable_statuses = _stable_observed_statuses(client)
    if any(status != "READY" for status in statuses.values()):
        if (
            statuses == stable_statuses
            and set(statuses.values()).issubset(_ACCEPTED_CAPABILITY_STATUSES)
            and set(statuses.values()).intersection(_VISIBLE_BLOCK_STATUSES)
        ):
            _assert_unverified_mapping_blocks_provider(client, today)
            _assert_application_remains_visibly_blocked(statuses, observed_at)
            return
        _fail("T058_LIVE_CAPABILITY_RESULT_UNSTABLE")
    if today_open is not True or not contract_window:
        _fail("T058_LIVE_CONTRACT_WINDOW_UNAVAILABLE")
    if source_time_label is SourceTimeLabel.UNVERIFIED:
        _fail("T058_LIVE_SOURCE_TIME_MAPPING_UNVERIFIED")


@pytest.mark.live
def test_authorized_live_final_minute_and_official_close(
    authorized_live_context: _LiveContext,
) -> None:
    context = authorized_live_context
    if context.evidence.market_window_outcome == "NOT_RUN_MARKET_WINDOW":
        pytest.skip("T058_LIVE_NOT_RUN_MARKET_WINDOW")
    observed_at = _shanghai_now()
    client = context.client
    today = observed_at.date()
    observed_statuses = _stable_observed_statuses(client)
    if (
        set(observed_statuses) == _CAPABILITY_OPERATIONS
        and set(observed_statuses.values()).issubset(_ACCEPTED_CAPABILITY_STATUSES)
        and set(observed_statuses.values()).intersection(_VISIBLE_BLOCK_STATUSES)
    ):
        _assert_unverified_mapping_blocks_provider(client, today)
        _assert_application_remains_visibly_blocked(observed_statuses, observed_at)
        return
    if observed_at.time() < _MIN_CLOSE_OBSERVATION_TIME:
        _fail("T058_LIVE_OFFICIAL_CLOSE_WINDOW_UNAVAILABLE")

    statuses: dict[str, str] = {}
    current_day_samples: list[pd.DataFrame] = []
    for _ in range(2):
        sample = _probe_call(
            client,
            statuses,
            "rt_min_daily",
            ts_code=_PROBE_SYMBOL,
            freq="1MIN",
            fields=_CURRENT_DAY_FIELDS,
        )
        if sample is not None:
            current_day_samples.append(sample)
    if any(status != "READY" for status in statuses.values()):
        _fail("T058_LIVE_CLOSE_CAPABILITY_RESULT_UNSTABLE")
    if len(current_day_samples) != 2:
        _fail("T058_LIVE_CLOSE_CAPABILITY_SET_INCOMPLETE")

    calendar = client.last_frames.get("trade_cal")
    if calendar is None:
        _fail("T058_LIVE_CLOSE_CALENDAR_EVIDENCE_MISSING")
    today_open, _ = _calendar_dates(calendar, today)
    if not today_open:
        _fail("T058_LIVE_CLOSE_DATE_NOT_OPEN")

    source_time_label = _derive_source_time_label(
        (current_day_samples[0], current_day_samples[1]),
        observed_at,
    )
    provider = TushareMarketDataProvider(
        client,
        now=lambda: observed_at,
        is_open_on=lambda value: value == today,
        source_time_label=source_time_label,
        probe_symbol=_PROBE_SYMBOL,
    )
    try:
        minutes_first = provider.current_day_minutes(_PROBE_SYMBOL)
        minutes_second = provider.current_day_minutes(_PROBE_SYMBOL)
        official_first = provider.daily_bars(_PROBE_SYMBOL, today, today)
        official_second = provider.daily_bars(_PROBE_SYMBOL, today, today)
    except TushareProviderError, _SanitizedCallError:
        _fail("T058_LIVE_CLOSE_NORMALIZATION_FAILED")

    expected = expected_minute_ends(today, is_open=True)
    if len(expected) != 240 or len(minutes_first) != 240 or minutes_first != minutes_second:
        _fail("T058_LIVE_FINAL_MINUTE_COUNT_UNVERIFIED")
    if minutes_first[-1].bar_end != expected[-1] or expected[-1].time() != wall_time(15, 0):
        _fail("T058_LIVE_FINAL_MINUTE_UNVERIFIED")
    if (
        len(official_first) != 1
        or official_first != official_second
        or not official_first[0].is_official
    ):
        _fail("T058_LIVE_OFFICIAL_CLOSE_NOT_READY")

    provisional = aggregate_provisional_daily_bar(
        current_day_minutes=tuple(minutes_first),
        source_as_of=expected[-1],
    )
    if provisional is None:
        _fail("T058_LIVE_PROVISIONAL_CLOSE_UNVERIFIED")
    reconciliation = reconcile_daily_close(
        symbol=_PROBE_SYMBOL,
        current_trade_date=today,
        daily_bars=(provisional, official_first[0]),
    )
    if (
        reconciliation.status is not CloseReconciliationStatus.OFFICIAL_READY
        or not reconciliation.advance_close_risk
    ):
        _fail("T058_LIVE_OFFICIAL_RECONCILIATION_UNVERIFIED")

    client.assert_pacing()
    final_minute = minutes_first[-1].bar_end.isoformat(timespec="minutes")
    context.evidence.call_semantics = _normalized_call_semantics(client.observations)
    context.evidence.source_time_label = source_time_label
    context.evidence.final_minute = final_minute
    context.evidence.official_close_rows = len(official_first)
    _emit_observations(
        client,
        capability_statuses={
            "daily": "READY",
            "rt_min_daily": "READY",
        },
        source_time_label=source_time_label,
        requested_symbols=1,
        returned_symbols=1,
        final_minute=final_minute,
        official_close_rows=len(official_first),
    )


@pytest.mark.live
def test_bilingual_live_report_contract_is_redacted_and_equivalent(
    request: pytest.FixtureRequest,
) -> None:
    offline_client = _PacedRecordingClient(_OfflineTransientClient())
    offline_statuses: dict[str, str] = {}
    if _probe_call(offline_client, offline_statuses, "daily") is not None:
        _fail("T058_LIVE_OFFLINE_CLASSIFICATION_CALL_UNEXPECTED")
    offline_observation = offline_client.observations[0]
    if (
        offline_statuses != {"daily": "ERROR"}
        or offline_observation.error_code != "TRANSIENT"
        or offline_observation.capability_status != "ERROR"
    ):
        _fail("T058_LIVE_OFFLINE_CLASSIFICATION_MISMATCH")

    invalid_client = _PacedRecordingClient(_OfflineInvalidResponseClient())
    invalid_statuses: dict[str, str] = {}
    if _probe_call(invalid_client, invalid_statuses, "daily") is not None:
        _fail("T058_LIVE_OFFLINE_INVALID_RESPONSE_CALL_UNEXPECTED")
    invalid_observation = invalid_client.observations[0]
    if (
        invalid_statuses != {"daily": "ERROR"}
        or invalid_observation.error_code != "INVALID_RESPONSE"
        or invalid_observation.capability_status != "ERROR"
    ):
        _fail("T058_LIVE_OFFLINE_INVALID_RESPONSE_MISMATCH")

    operations = tuple(sorted(_CAPABILITY_OPERATIONS))
    for visible_status in sorted(_VISIBLE_BLOCK_STATUSES):
        for blocked_mask in range(1, 1 << len(operations)):
            statuses = {
                operation: visible_status if blocked_mask & (1 << index) else "READY"
                for index, operation in enumerate(operations)
            }
            _assert_application_remains_visibly_blocked(statuses, _shanghai_now())
    mixed_statuses = {
        operation: status
        for operation, status in zip(
            operations,
            ("BLOCKED_PERMISSION", "ERROR", "RATE_LIMITED", "READY", "READY"),
            strict=True,
        )
    }
    _assert_application_remains_visibly_blocked(mixed_statuses, _shanghai_now())

    for path in _REPORTS:
        if not path.is_file():
            _fail("T058_LIVE_REPORT_MISSING")

    english = _REPORTS[0].read_text(encoding="utf-8")
    chinese = _REPORTS[1].read_text(encoding="utf-8")
    if "Status:" not in english or "状态：" not in chinese:
        _fail("T058_LIVE_REPORT_STATUS_MISSING")
    for token in _REQUIRED_REPORT_TOKENS:
        if token not in english or token not in chinese:
            _fail("T058_LIVE_REPORT_PARITY_MISSING")
    for report in (english, chinese):
        if any(pattern.search(report) for pattern in _REPORT_SECRET_PATTERNS):
            _fail("T058_LIVE_REPORT_SECRET_MATERIAL_DETECTED")
    english_evidence = _canonical_evidence(english)
    chinese_evidence = _canonical_evidence(chinese)
    if english_evidence != chinese_evidence or english_evidence != _EXPECTED_CANONICAL_EVIDENCE:
        _fail("T058_LIVE_REPORT_EVIDENCE_MISMATCH")
    if str(request.config.getoption("markexpr")).strip() == "live":
        context = request.getfixturevalue("authorized_live_context")
        if not isinstance(context, _LiveContext):
            _fail("T058_LIVE_REPORT_SESSION_EVIDENCE_INVALID")
        if context.evidence.market_window_outcome == "NOT_RUN_MARKET_WINDOW":
            pytest.skip("T058_LIVE_NOT_RUN_MARKET_WINDOW")
        if _report_semantics(english_evidence) != _live_semantics(context):
            _fail("T058_LIVE_REPORT_SESSION_EVIDENCE_MISMATCH")
