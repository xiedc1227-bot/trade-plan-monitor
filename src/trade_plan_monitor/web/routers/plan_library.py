"""Prepare one source and compose server-owned reviewed versions."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BeforeValidator, Field

from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import LoopTimestamp
from trade_plan_monitor.backtest.preparation_models import (
    PreparedPlanCompositionInput,
    ReviewedPlanReference,
    SingleSourcePreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.web.preparation_schemas import (
    CollectionPreparationFrozenView,
    CollectionPreparationView,
    _embedded,
    project_collection_frozen,
)
from trade_plan_monitor.web.routers.backtest_preparations import Service, _invoke, _view
from trade_plan_monitor.web.schemas import ApiValue, MutationContextDependency

router = APIRouter(prefix="/api/v1/backtest-plan-library", tags=["backtest-plan-library"])


class ReviewedPlanLibraryIdentity(ApiValue):
    source_hash: Sha256Hex
    plan_hash: Sha256Hex
    plan_version_id: StableIdentifier
    reviewed_version_hash: Sha256Hex


class ReviewedPlanLibraryItem(ApiValue):
    preparation_id: StableIdentifier
    manifest_hash: Sha256Hex
    source_id: StableIdentifier
    effective_trade_date: date
    symbol: str = Field(max_length=32)
    name: str = Field(max_length=256)
    reviewed_base: ReviewedPlanReference | None
    reviewed_at: LoopTimestamp
    identity: ReviewedPlanLibraryIdentity | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


class ReviewedPlanLibraryPage(ApiValue):
    items: tuple[ReviewedPlanLibraryItem, ...] = Field(max_length=100)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


@router.get("", response_model=ReviewedPlanLibraryPage)
async def list_plans(
    service: Service,
    response: Response,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    response.headers["Cache-Control"] = "no-store"
    page = await _invoke(service.list_reviewed(offset=offset, limit=limit))
    return ReviewedPlanLibraryPage(**page)


@router.post("/preparations", response_model=CollectionPreparationView, status_code=201)
async def prepare_one(
    command: Annotated[
        SingleSourcePreparationInput,
        BeforeValidator(lambda value: _embedded(SingleSourcePreparationInput, value)),
    ],
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    return _view(
        await _invoke(service.library_write(command, idempotency_key=context.idempotency_key)),
        response,
    )


@router.post("/compositions", response_model=CollectionPreparationFrozenView, status_code=201)
async def compose(
    command: Annotated[
        PreparedPlanCompositionInput,
        BeforeValidator(lambda value: _embedded(PreparedPlanCompositionInput, value)),
    ],
    context: MutationContextDependency,
    service: Service,
    response: Response,
):
    record = await _invoke(service.library_write(command, idempotency_key=context.idempotency_key))
    response.headers["Cache-Control"] = "no-store"
    return project_collection_frozen(frozen_preparation(record))
