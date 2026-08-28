"""Strict durable-job values for the local backtest coordinator boundary."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from trade_plan_monitor.backtest.dataset import BacktestDatasetCoverage, DatasetScope
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.backtest.time import SHANGHAI, format_shanghai_datetime
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.models import AShareSymbol

MAX_JOB_REQUEST_BYTES = 256 * 1024
MAX_JOB_ERROR_CHARACTERS = 512
MAX_QUEUED_JOBS = 100
JOB_IDEMPOTENCY_DAYS = 14

Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
JobIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]


class BacktestJobKind(StrEnum):
    DATA_SYNC = "DATA_SYNC"
    DATASET_VERIFY = "DATASET_VERIFY"
    BACKTEST_RUN = "BACKTEST_RUN"


class BacktestJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BacktestJobPhase(StrEnum):
    QUEUED = "QUEUED"
    VALIDATING_INPUT = "VALIDATING_INPUT"
    SYNCING_DATA = "SYNCING_DATA"
    VERIFYING_DATASET = "VERIFYING_DATASET"
    REPLAYING = "REPLAYING"
    MATERIALIZING_RESULTS = "MATERIALIZING_RESULTS"
    FINALIZING = "FINALIZING"
    TERMINAL = "TERMINAL"


class BacktestProgressUnit(StrEnum):
    ITEMS = "ITEMS"
    SYMBOL_DAYS = "SYMBOL_DAYS"
    EVENTS = "EVENTS"
    ROWS = "ROWS"


class _JobValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class BacktestDatasetScopeRequest(_JobValue):
    """Path-free typed dataset identity used by durable job requests."""

    symbols: tuple[AShareSymbol, ...]
    start: Annotated[date, Field(strict=True)]
    end: Annotated[date, Field(strict=True)]
    warmup_start: Annotated[date, Field(strict=True)]
    historical_profile: Literal[HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1]
    adjustment_policy: Literal["NONE"] = "NONE"

    @model_validator(mode="after")
    def validate_dataset_bounds(self) -> Self:
        validated = DatasetScope(
            symbols=self.symbols,
            start=self.start,
            end=self.end,
            warmup_start=self.warmup_start,
            historical_profile=self.historical_profile,
            adjustment_policy=self.adjustment_policy,
        )
        if validated.symbols != self.symbols:
            raise ValueError("symbols must already be in canonical sorted order")
        return self


class DataSyncJobRequest(_JobValue):
    kind: Literal[BacktestJobKind.DATA_SYNC] = BacktestJobKind.DATA_SYNC
    scope: BacktestDatasetScopeRequest
    refresh: Annotated[bool, Field(strict=True)]
    allow_network: Literal[True]


class DatasetVerifyJobRequest(_JobValue):
    kind: Literal[BacktestJobKind.DATASET_VERIFY] = BacktestJobKind.DATASET_VERIFY
    scope: BacktestDatasetScopeRequest


class BacktestRunJobRequest(_JobValue):
    kind: Literal[BacktestJobKind.BACKTEST_RUN] = BacktestJobKind.BACKTEST_RUN
    run_input: BacktestRunInput


type BacktestJobRequest = DataSyncJobRequest | DatasetVerifyJobRequest | BacktestRunJobRequest


def _canonical_business_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("job time must be timezone-aware")
    if value.utcoffset() != SHANGHAI.utcoffset(value):
        raise ValueError("job time must use Asia/Shanghai or explicit +08:00")
    return value.astimezone(SHANGHAI)


class BacktestJobProgress(_JobValue):
    phase: BacktestJobPhase
    completed_units: NonNegativeInteger = 0
    total_units: NonNegativeInteger | None = None
    unit: BacktestProgressUnit = BacktestProgressUnit.ITEMS
    updated_at: datetime

    _normalize_updated_at = field_validator("updated_at")(_canonical_business_time)

    @field_serializer("updated_at", when_used="json")
    def serialize_updated_at(self, value: datetime) -> str:
        return format_shanghai_datetime(value)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.total_units is not None and self.completed_units > self.total_units:
            raise ValueError("completed_units cannot exceed total_units")
        return self


class BacktestRunJobResult(_JobValue):
    kind: Literal[BacktestJobKind.BACKTEST_RUN] = BacktestJobKind.BACKTEST_RUN
    run_id: Sha256Hex
    report_hash: Sha256Hex
    reused: Annotated[bool, Field(strict=True)]


class BacktestDataSyncJobResult(_JobValue):
    kind: Literal[BacktestJobKind.DATA_SYNC] = BacktestJobKind.DATA_SYNC
    calendar_rows: NonNegativeInteger
    minute_days: NonNegativeInteger
    daily_limit_rows: NonNegativeInteger
    daily_bar_rows: NonNegativeInteger
    network_calls: NonNegativeInteger


class BacktestDatasetVerificationJobResult(_JobValue):
    kind: Literal[BacktestJobKind.DATASET_VERIFY] = BacktestJobKind.DATASET_VERIFY
    ready: Annotated[bool, Field(strict=True)]
    dataset_hash: Sha256Hex | None = None
    coverage: BacktestDatasetCoverage
    blockers: Annotated[tuple[str, ...], Field(max_length=100)]

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if self.ready != (self.dataset_hash is not None):
            raise ValueError("ready verification result and dataset_hash must agree")
        if self.blockers != tuple(sorted(set(self.blockers))):
            raise ValueError("blockers must be ordered and unique")
        return self


type BacktestJobResult = (
    BacktestDataSyncJobResult | BacktestDatasetVerificationJobResult | BacktestRunJobResult
)


class BacktestJobReceipt(_JobValue):
    job_id: JobIdentifier
    kind: BacktestJobKind
    status: BacktestJobStatus
    run_id: Sha256Hex | None = None
    dataset_hash: Sha256Hex | None = None
    attempt: Annotated[int, Field(strict=True, ge=0, le=3)] = 0
    revision: NonNegativeInteger = 0
    reused: Annotated[bool, Field(strict=True)] = False
    submitted_at: datetime

    _normalize_submitted_at = field_validator("submitted_at")(_canonical_business_time)

    @field_serializer("submitted_at", when_used="json")
    def serialize_submitted_at(self, value: datetime) -> str:
        return format_shanghai_datetime(value)

    @model_validator(mode="after")
    def validate_identity_shape(self) -> Self:
        if self.kind is BacktestJobKind.BACKTEST_RUN:
            if self.run_id is None or self.dataset_hash is None:
                raise ValueError("BACKTEST_RUN receipt requires run_id and dataset_hash")
        elif self.run_id is not None:
            raise ValueError("non-run receipt cannot expose run_id")
        if self.kind is BacktestJobKind.DATA_SYNC and self.dataset_hash is not None:
            raise ValueError("DATA_SYNC receipt cannot expose dataset_hash")
        if self.reused and self.status is not BacktestJobStatus.COMPLETED:
            raise ValueError("only a completed receipt may be reused")
        return self


class BacktestJobView(_JobValue):
    job_id: JobIdentifier
    kind: BacktestJobKind
    status: BacktestJobStatus
    request_hash: Sha256Hex
    run_id: Sha256Hex | None = None
    dataset_hash: Sha256Hex | None = None
    progress: BacktestJobProgress
    result: BacktestJobResult | None = None
    attempt: Annotated[int, Field(strict=True, ge=0, le=3)] = 0
    revision: NonNegativeInteger = 0
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    finished_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    reused: Annotated[bool, Field(strict=True)] = False
    error_code: Annotated[str, Field(strict=True, min_length=1, max_length=128)] | None = None
    error_message: (
        Annotated[
            str,
            Field(strict=True, min_length=1, max_length=MAX_JOB_ERROR_CHARACTERS),
        ]
        | None
    ) = None

    @field_validator(
        "created_at",
        "started_at",
        "updated_at",
        "finished_at",
        "cancel_requested_at",
    )
    @classmethod
    def normalize_times(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _canonical_business_time(value)

    @field_serializer(
        "created_at",
        "started_at",
        "updated_at",
        "finished_at",
        "cancel_requested_at",
        when_used="json",
    )
    def serialize_times(self, value: datetime | None) -> str | None:
        return None if value is None else format_shanghai_datetime(value)

    @model_validator(mode="after")
    def validate_closed_shape(self) -> Self:
        terminal = self.status in {
            BacktestJobStatus.COMPLETED,
            BacktestJobStatus.FAILED,
            BacktestJobStatus.CANCELLED,
        }
        if terminal != (self.finished_at is not None):
            raise ValueError("terminal status and finished_at must agree")
        if terminal != (self.progress.phase is BacktestJobPhase.TERMINAL):
            raise ValueError("terminal status and progress phase must agree")
        if self.status is BacktestJobStatus.COMPLETED:
            if self.result is None or self.error_code is not None or self.error_message is not None:
                raise ValueError("completed job requires result and no error")
        elif self.result is not None:
            raise ValueError("only a completed job may expose a result")
        if self.result is not None and self.result.kind is not self.kind:
            raise ValueError("job result kind must match the outer job kind")
        if (self.error_code is None) != (self.error_message is None):
            raise ValueError("error_code and error_message must be present together")
        if self.kind is BacktestJobKind.BACKTEST_RUN:
            if self.run_id is None or self.dataset_hash is None:
                raise ValueError("BACKTEST_RUN job requires run_id and dataset_hash")
        elif self.run_id is not None:
            raise ValueError("non-run job cannot expose run_id")
        if self.kind is BacktestJobKind.DATA_SYNC and self.dataset_hash is not None:
            raise ValueError("DATA_SYNC job cannot expose dataset_hash")
        if (
            isinstance(self.result, BacktestDatasetVerificationJobResult)
            and self.dataset_hash != self.result.dataset_hash
        ):
            raise ValueError("verification job and result dataset_hash must agree")
        if isinstance(self.result, BacktestRunJobResult) and self.run_id != self.result.run_id:
            raise ValueError("run job and result run_id must agree")
        if self.reused and self.status is not BacktestJobStatus.COMPLETED:
            raise ValueError("only a completed job may be reused")
        return self


__all__ = [
    "JOB_IDEMPOTENCY_DAYS",
    "MAX_JOB_ERROR_CHARACTERS",
    "MAX_JOB_REQUEST_BYTES",
    "MAX_QUEUED_JOBS",
    "BacktestDatasetScopeRequest",
    "BacktestDatasetVerificationJobResult",
    "BacktestDataSyncJobResult",
    "BacktestJobKind",
    "BacktestJobPhase",
    "BacktestJobProgress",
    "BacktestJobReceipt",
    "BacktestJobResult",
    "BacktestJobRequest",
    "BacktestJobStatus",
    "BacktestJobView",
    "BacktestProgressUnit",
    "BacktestRunJobRequest",
    "BacktestRunJobResult",
    "DataSyncJobRequest",
    "DatasetVerifyJobRequest",
]
