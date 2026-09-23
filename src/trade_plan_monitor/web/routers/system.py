"""Local, reviewed legacy-plan maintenance while monitoring is blocked."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator

from trade_plan_monitor.state.legacy_plan_invalidation import (
    LegacyMaintenanceUnavailable,
    LegacyPlanInvalidationConflict,
)
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.lifespan import get_runtime_lifecycle
from trade_plan_monitor.web.schemas import ApiValue

router = APIRouter(prefix="/api/v1/system", tags=["system"])
RuntimeDependency = Annotated[object, Depends(get_runtime_lifecycle)]
Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]


class LegacyPlanItemView(ApiValue):
    symbol: str
    plan_version_id: str
    revision: int = Field(ge=0)


class LegacyPlanPreviewResponse(ApiValue):
    available: bool
    plans: tuple[LegacyPlanItemView, ...] = Field(default=(), max_length=10)
    fingerprint: Fingerprint | None = None

    @model_validator(mode="after")
    def validate_availability(self):
        if self.available != (bool(self.plans) and self.fingerprint is not None):
            raise ValueError("legacy preview availability is inconsistent")
        return self


class LegacyPlanInvalidateCommand(ApiValue):
    fingerprint: Fingerprint
    confirmation: Literal["INVALIDATE_LEGACY_PLANS"]


class LegacyPlanInvalidateResult(ApiValue):
    symbols: tuple[str, ...] = Field(min_length=1, max_length=10)
    restart_required: Literal[True] = True


@router.get("/legacy-plan-invalidation", response_model=LegacyPlanPreviewResponse)
async def get_legacy_plan_invalidation(
    runtime: RuntimeDependency,
) -> LegacyPlanPreviewResponse:
    preview_method = getattr(runtime, "preview_legacy_invalidation", None)
    if not callable(preview_method):
        return LegacyPlanPreviewResponse(available=False)
    try:
        preview = await preview_method()
    except LegacyMaintenanceUnavailable:
        return LegacyPlanPreviewResponse(available=False)
    except (LegacyPlanInvalidationConflict, RepositoryError):
        raise ApiError(ApiErrorCode.CONFLICT) from None
    if not preview.plans:
        return LegacyPlanPreviewResponse(available=False)
    return LegacyPlanPreviewResponse(
        available=True,
        plans=tuple(
            LegacyPlanItemView(
                symbol=item.symbol,
                plan_version_id=item.plan_version_id,
                revision=item.revision,
            )
            for item in preview.plans
        ),
        fingerprint=preview.fingerprint,
    )


@router.post("/legacy-plan-invalidation", response_model=LegacyPlanInvalidateResult)
async def confirm_legacy_plan_invalidation(
    command: LegacyPlanInvalidateCommand,
    runtime: RuntimeDependency,
) -> LegacyPlanInvalidateResult:
    invalidate_method = getattr(runtime, "invalidate_legacy_plans", None)
    if not callable(invalidate_method):
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    try:
        symbols = await invalidate_method(expected_fingerprint=command.fingerprint)
    except (LegacyPlanInvalidationConflict, RepositoryError):
        raise ApiError(ApiErrorCode.CONFLICT) from None
    return LegacyPlanInvalidateResult(symbols=symbols)
