"""Typed secret-free runtime and per-symbol health read routes."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Path
from pydantic import UUID4, Field, model_validator

from trade_plan_monitor.decision.models import DataHealthStatus
from trade_plan_monitor.market_data.models import (
    AShareSymbol,
    ProviderCapabilityStatus,
    ShanghaiDatetime,
)
from trade_plan_monitor.runtime.health import (
    LEGACY_RUNTIME_GENERATION,
    HealthErrorCode,
    HealthName,
    RuntimeResourceStatus,
    RuntimeServiceStatus,
    SymbolHealthErrorCode,
)
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.dashboard import (
    ReadModel,
    ReadServiceDependency,
    validate_read_response,
)

router = APIRouter(prefix="/api/v1", tags=["health"])

NonNegativeInteger = Annotated[int, Field(strict=True, ge=0)]
SymbolPath = Annotated[AShareSymbol, Path()]


class RuntimeGapView(ReadModel):
    symbol: AShareSymbol
    bar_end: ShanghaiDatetime


class RecoveryIssueView(ReadModel):
    symbol: AShareSymbol
    reason: HealthErrorCode
    next_retry_at: ShanghaiDatetime


class ProviderHealthView(ReadModel):
    capability: HealthName
    status: ProviderCapabilityStatus
    checked_at: ShanghaiDatetime
    latency_ms: NonNegativeInteger
    error_code: HealthErrorCode | None
    next_retry_at: ShanghaiDatetime | None

    @model_validator(mode="after")
    def validate_provider(self) -> Self:
        neutral = {
            ProviderCapabilityStatus.READY,
            ProviderCapabilityStatus.UNVERIFIED,
        }
        if self.status in neutral and (
            self.error_code is not None or self.next_retry_at is not None
        ):
            raise ValueError("ready provider health cannot retain an error or retry")
        if self.status not in neutral and self.error_code is None:
            raise ValueError("non-ready provider health requires an error code")
        if self.next_retry_at is not None and self.next_retry_at < self.checked_at:
            raise ValueError("provider retry cannot precede its observation")
        return self


class ExecutorHealthView(ReadModel):
    max_workers: Annotated[int, Field(strict=True, ge=1, le=2)]
    active_count: Annotated[int, Field(strict=True, ge=0, le=2)]
    waiting_count: Annotated[int, Field(strict=True, ge=0, le=32)]

    @model_validator(mode="after")
    def validate_executor(self) -> Self:
        if self.active_count > self.max_workers:
            raise ValueError("active work cannot exceed max workers")
        return self


class DatabaseHealthView(ReadModel):
    status: RuntimeResourceStatus
    wal_status: RuntimeResourceStatus
    last_checkpoint_at: ShanghaiDatetime | None
    last_backup_at: ShanghaiDatetime | None
    error_code: HealthErrorCode | None

    @model_validator(mode="after")
    def validate_database(self) -> Self:
        ready = (
            self.status is RuntimeResourceStatus.READY
            and self.wal_status is RuntimeResourceStatus.READY
        )
        neutral = self.status in {
            RuntimeResourceStatus.UNVERIFIED,
            RuntimeResourceStatus.STOPPED,
        } and self.wal_status in {
            RuntimeResourceStatus.UNVERIFIED,
            RuntimeResourceStatus.STOPPED,
        }
        if (ready or neutral) and self.error_code is not None:
            raise ValueError("ready database health cannot retain an error")
        if not ready and not neutral and self.error_code is None:
            raise ValueError("non-ready database health requires an error code")
        return self


class DeliveryHealthView(ReadModel):
    status: RuntimeResourceStatus
    pending_count: NonNegativeInteger
    failed_count: NonNegativeInteger
    last_delivered_at: ShanghaiDatetime | None
    next_retry_at: ShanghaiDatetime | None
    error_code: HealthErrorCode | None

    @model_validator(mode="after")
    def validate_delivery(self) -> Self:
        neutral = self.status in {
            RuntimeResourceStatus.READY,
            RuntimeResourceStatus.UNVERIFIED,
            RuntimeResourceStatus.STOPPED,
        }
        if neutral and (
            self.failed_count != 0 or self.next_retry_at is not None or self.error_code is not None
        ):
            raise ValueError("ready delivery health cannot retain a failure")
        if not neutral and self.error_code is None:
            raise ValueError("non-ready delivery health requires an error code")
        return self


class RuntimeHealthResponse(ReadModel):
    status: RuntimeServiceStatus
    read_only: bool = Field(strict=True)
    block_reason: Literal["LEGACY_PLANS_REQUIRE_REVIEW"] | None = None
    degraded_reason: HealthErrorCode | None = None
    runtime_generation: UUID4 = Field(default=LEGACY_RUNTIME_GENERATION, exclude=True)
    observed_at: ShanghaiDatetime
    started_at: ShanghaiDatetime
    stopped_at: ShanghaiDatetime | None
    last_completed_minute: ShanghaiDatetime | None
    last_completed_minute_age_seconds: NonNegativeInteger | None
    latest_evaluation_at: ShanghaiDatetime | None
    latest_evaluation_age_seconds: NonNegativeInteger | None
    gaps: tuple[RuntimeGapView, ...] = Field(default=(), max_length=2_400)
    recovery_issues: tuple[RecoveryIssueView, ...] = Field(default=(), max_length=10)
    next_retry_at: ShanghaiDatetime | None
    cooldown_until: ShanghaiDatetime | None
    providers: tuple[ProviderHealthView, ...] = Field(default=(), max_length=5)
    executor: ExecutorHealthView
    database: DatabaseHealthView
    delivery: DeliveryHealthView
    next_poll_at: ShanghaiDatetime | None

    @model_validator(mode="after")
    def validate_runtime(self) -> Self:
        if self.status is RuntimeServiceStatus.RUNNING and self.read_only:
            raise ValueError("RUNNING health requires readOnly=false")
        if self.status is RuntimeServiceStatus.DEGRADED and not self.read_only:
            raise ValueError("DEGRADED health requires readOnly=true")
        if self.status is not RuntimeServiceStatus.DEGRADED and self.degraded_reason is not None:
            raise ValueError("only DEGRADED health may carry a degraded reason")
        if (self.status is RuntimeServiceStatus.BLOCKED) != (
            self.block_reason is not None
        ):
            raise ValueError("BLOCKED health requires exactly one block reason")
        if self.status is RuntimeServiceStatus.BLOCKED and not self.read_only:
            raise ValueError("BLOCKED health requires readOnly=true")
        if self.started_at > self.observed_at:
            raise ValueError("health observation cannot precede startup")
        if (self.status is RuntimeServiceStatus.STOPPED) != (self.stopped_at is not None):
            raise ValueError("only stopped health requires stoppedAt")
        if self.stopped_at is not None and not (
            self.started_at <= self.stopped_at <= self.observed_at
        ):
            raise ValueError("stoppedAt must belong to the observed lifecycle")
        self._validate_age(
            self.last_completed_minute,
            self.last_completed_minute_age_seconds,
            "last completed minute",
        )
        self._validate_age(
            self.latest_evaluation_at,
            self.latest_evaluation_age_seconds,
            "latest evaluation",
        )
        gaps = tuple((gap.symbol, gap.bar_end) for gap in self.gaps)
        if gaps != tuple(sorted(set(gaps))):
            raise ValueError("health gaps must be unique and ordered")
        recovery_symbols = tuple(issue.symbol for issue in self.recovery_issues)
        if recovery_symbols != tuple(sorted(set(recovery_symbols))):
            raise ValueError("recovery issues must be unique and ordered")
        capabilities = tuple(provider.capability for provider in self.providers)
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("provider capabilities must be unique")
        if any(provider.checked_at > self.observed_at for provider in self.providers):
            raise ValueError("provider health cannot be observed in the future")
        return self

    def _validate_age(
        self,
        timestamp: ShanghaiDatetime | None,
        age_seconds: int | None,
        label: str,
    ) -> None:
        if (timestamp is None) != (age_seconds is None):
            raise ValueError(f"{label} and age must appear together")
        if timestamp is None:
            return
        age = self.observed_at - timestamp
        if age < timedelta(0) or int(age.total_seconds()) != age_seconds:
            raise ValueError(f"{label} age must match observation")


class SymbolHealthResponse(ReadModel):
    symbol: AShareSymbol
    observed_at: ShanghaiDatetime
    target_end: ShanghaiDatetime
    status: DataHealthStatus
    latest_bar_end: ShanghaiDatetime | None
    data_age_seconds: NonNegativeInteger | None
    required_data_complete: bool = Field(strict=True)
    fresh: bool = Field(strict=True)
    gaps: tuple[ShanghaiDatetime, ...] = Field(default=(), max_length=240)
    consecutive_incomplete_buckets: NonNegativeInteger
    last_required_bucket_end: ShanghaiDatetime | None = None
    error_code: SymbolHealthErrorCode | None
    actionable: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_symbol_health(self) -> Self:
        if self.observed_at < self.target_end:
            raise ValueError("health observation cannot precede target")
        if (
            self.last_required_bucket_end is not None
            and self.last_required_bucket_end > self.target_end
        ):
            raise ValueError("last required bucket cannot follow target")
        if self.consecutive_incomplete_buckets > 0 and self.last_required_bucket_end is None:
            raise ValueError("an incomplete streak requires its last required bucket")
        if (self.latest_bar_end is None) != (self.data_age_seconds is None):
            raise ValueError("latest bar and age must appear together")
        if self.latest_bar_end is not None:
            age = self.observed_at - self.latest_bar_end
            if age < timedelta(0) or int(age.total_seconds()) != self.data_age_seconds:
                raise ValueError("symbol data age must match observation")
        if self.fresh and self.latest_bar_end is None:
            raise ValueError("fresh health requires a latest bar")
        if self.status is DataHealthStatus.LIVE and (
            not self.fresh or not self.required_data_complete or self.latest_bar_end is None
        ):
            raise ValueError("LIVE health requires fresh complete data")
        if self.status is DataHealthStatus.STALE and self.fresh:
            raise ValueError("STALE health cannot be fresh")
        if self.status in {DataHealthStatus.GAPPED, DataHealthStatus.BLOCKED} and (
            self.required_data_complete
        ):
            raise ValueError("gapped or blocked health cannot be complete")
        live = self.status is DataHealthStatus.LIVE and self.required_data_complete and self.fresh
        if self.actionable != live:
            raise ValueError("actionable must match LIVE complete fresh health")
        if live and (self.gaps or self.error_code is not None):
            raise ValueError("actionable health cannot retain gaps or an error")
        if not live and self.error_code is None:
            raise ValueError("non-actionable health requires an error code")
        if self.gaps != tuple(sorted(set(self.gaps))):
            raise ValueError("symbol health gaps must be unique and ordered")
        return self


@router.get("/health", response_model=RuntimeHealthResponse)
async def get_health(
    service: ReadServiceDependency,
) -> RuntimeHealthResponse:
    return validate_read_response(await service.get_health(), RuntimeHealthResponse)


@router.get("/health/symbols/{symbol}", response_model=SymbolHealthResponse)
async def get_symbol_health(
    symbol: SymbolPath,
    service: ReadServiceDependency,
) -> SymbolHealthResponse:
    value = await service.get_symbol_health(symbol=symbol)
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    response = validate_read_response(value, SymbolHealthResponse)
    if response.symbol != symbol:
        raise ValueError("service response symbol does not match the requested symbol")
    return response


__all__ = ["router"]
