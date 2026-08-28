"""Typed plan-version and review-only extraction HTTP adapters."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import Field, field_validator, model_validator

from trade_plan_monitor.ai.models import (
    AIUsageSnapshot,
    ExtractionIssue,
    FieldEvidence,
    UnmappedText,
)
from trade_plan_monitor.domain.plan_codec import (
    MAX_PLAN_DOCUMENT_BYTES,
    dump_plan_json,
    load_plan_json,
    load_plan_yaml,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import AShareSymbol, TradePlan
from trade_plan_monitor.domain.plan_validation import DraftReviewIssue, ValidationIssue
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.models import PlanVersionStatus
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.schemas import (
    ApiValue,
    MutationContext,
    MutationContextDependency,
    OperationKind,
    OperationReceipt,
    validate_api_response,
)

router = APIRouter(prefix="/api/v1", tags=["plans"])

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_MAX_ROWS = 10_000
_MAX_SOURCE_CHARS = 200_000
_MAX_EXPECTED_REVISION = 9_223_372_036_854_775_806
_PLAN_VERSION_COLLECTION_QUERY_FIELDS = frozenset(
    {"symbol", "status", "canActivate", "offset", "limit"}
)

OffsetQuery = Annotated[int, Query(ge=0, le=_MAX_ROWS)]
LimitQuery = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
PlanSymbolQuery = Annotated[
    str | None,
    Query(min_length=9, max_length=9, pattern=r"^[0-9]{6}\.(?:SH|SZ|BJ)$"),
]
PlanStatusQuery = Annotated[PlanVersionStatus | None, Query()]
CanActivateQuery = Annotated[
    Literal["true", "false"] | None,
    Query(alias="canActivate"),
]
ResourceIdPath = Annotated[UUID, Path()]
NonNegativeRevision = Annotated[
    int,
    Field(strict=True, ge=0, le=_MAX_EXPECTED_REVISION),
]
PlanDocument = Annotated[
    str,
    Field(strict=True, min_length=2, max_length=MAX_PLAN_DOCUMENT_BYTES),
]
PlanSourceText = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=MAX_PLAN_DOCUMENT_BYTES),
]
ExtractionSourceText = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=_MAX_SOURCE_CHARS),
]
Sha256Hex = Annotated[
    str,
    Field(strict=True, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]


class PlanDocumentFormat(StrEnum):
    JSON = "JSON"
    YAML = "YAML"


class PlanExtractionOperationStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CANCELLED = "CANCELLED"


class PlanVersionView(ApiValue):
    """One immutable, canonical plan version plus its review/validation state."""

    id: UUID
    plan_id: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    version: Annotated[int, Field(strict=True, gt=0)]
    symbol: AShareSymbol
    plan_hash: Sha256Hex
    status: PlanVersionStatus
    plan_json: PlanDocument
    source_text: PlanSourceText
    review_issues: tuple[DraftReviewIssue, ...] = Field(default=(), max_length=512)
    validation_issues: tuple[ValidationIssue, ...] = Field(default=(), max_length=512)
    can_activate: bool = Field(strict=True)
    revision: NonNegativeRevision
    created_at: ShanghaiDatetime

    @field_validator("source_text")
    @classmethod
    def validate_source_text(cls, value: str) -> str:
        return _valid_utf8_text(value, max_bytes=MAX_PLAN_DOCUMENT_BYTES)

    @model_validator(mode="after")
    def validate_canonical_plan_and_activation_state(self) -> Self:
        plan = load_plan_json(self.plan_json)
        if dump_plan_json(plan) != self.plan_json:
            raise ValueError("plan_json must be canonical")
        if (
            plan.plan_id != self.plan_id
            or plan.version != self.version
            or plan.symbol != self.symbol
            or plan_sha256(plan) != self.plan_hash
        ):
            raise ValueError("plan version identity must match its canonical document")
        expected_can_activate = not any(
            issue.activation_blocking for issue in self.validation_issues
        ) and not any(not issue.resolved for issue in self.review_issues)
        if self.can_activate != expected_can_activate:
            raise ValueError("can_activate must match unresolved review and validation state")
        if self.status is PlanVersionStatus.ACTIVE and not self.can_activate:
            raise ValueError("an active version cannot contain an activation blocker")
        return self


class PlanVersionPage(ApiValue):
    items: tuple[PlanVersionView, ...] = Field(default=(), max_length=_MAX_LIMIT)
    offset: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]
    limit: Annotated[int, Field(strict=True, ge=1, le=_MAX_LIMIT)]
    total: Annotated[int, Field(strict=True, ge=0, le=_MAX_ROWS)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.limit or (
            self.items and self.offset + len(self.items) > self.total
        ):
            raise ValueError("plan page metadata is inconsistent")
        identities = tuple(item.id for item in self.items)
        if len(set(identities)) != len(identities):
            raise ValueError("plan page identities must be unique")
        return self


class PlanDraftCommand(ApiValue):
    plan_json: PlanDocument
    source_text: PlanSourceText
    review_issues: tuple[DraftReviewIssue, ...] = Field(
        default=(),
        max_length=512,
        strict=False,
    )
    expected_revision: NonNegativeRevision

    @field_validator("plan_json")
    @classmethod
    def validate_plan_json(cls, value: str) -> str:
        load_plan_json(value)
        return value

    @field_validator("source_text")
    @classmethod
    def validate_source_text(cls, value: str) -> str:
        return _valid_utf8_text(value, max_bytes=MAX_PLAN_DOCUMENT_BYTES)


class PlanImportCommand(ApiValue):
    format: PlanDocumentFormat = Field(strict=False)
    document: PlanDocument
    expected_revision: NonNegativeRevision

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        if self.format is PlanDocumentFormat.JSON:
            load_plan_json(self.document)
        else:
            load_plan_yaml(self.document)
        return self


class PlanExtractionCommand(ApiValue):
    provider_id: UUID = Field(strict=False)
    source_text: ExtractionSourceText
    expected_revision: NonNegativeRevision

    @field_validator("source_text")
    @classmethod
    def validate_source_text(cls, value: str) -> str:
        return _valid_utf8_text(value)


class PlanActivationCommand(ApiValue):
    plan_version_id: UUID = Field(strict=False)
    expected_revision: NonNegativeRevision


class PlanDeactivationCommand(ApiValue):
    symbol: AShareSymbol
    expected_revision: NonNegativeRevision


class AIUsageView(ApiValue):
    prompt_tokens: Annotated[int, Field(strict=True, ge=0)]
    completion_tokens: Annotated[int, Field(strict=True, ge=0)]
    total_tokens: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total_tokens < self.prompt_tokens + self.completion_tokens:
            raise ValueError("total token count cannot be smaller than its components")
        AIUsageSnapshot(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
        )
        return self


class PlanExtractionView(ApiValue):
    """Bounded operation status containing only validated review data."""

    id: UUID
    provider_id: UUID
    status: PlanExtractionOperationStatus
    submitted_at: ShanghaiDatetime
    started_at: ShanghaiDatetime | None = None
    completed_at: ShanghaiDatetime | None = None
    source_text_sha256: Sha256Hex | None = None
    model: Annotated[str, Field(strict=True, min_length=1, max_length=200)] | None = None
    prompt_version: (
        Annotated[
            str,
            Field(strict=True, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
        ]
        | None
    ) = None
    draft_plan_json: PlanDocument | None = None
    evidence: tuple[FieldEvidence, ...] = Field(default=(), max_length=10_000)
    assumptions: tuple[ExtractionIssue, ...] = Field(default=(), max_length=256)
    warnings: tuple[ExtractionIssue, ...] = Field(default=(), max_length=256)
    unmapped_text: tuple[UnmappedText, ...] = Field(default=(), max_length=256)
    validation_issues: tuple[ValidationIssue, ...] = Field(default=(), max_length=512)
    usage: AIUsageView | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        if self.started_at is not None and self.started_at < self.submitted_at:
            raise ValueError("extraction cannot start before submission")
        if (
            self.completed_at is not None
            and self.started_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("extraction completion cannot precede its start")
        result_fields = (
            self.source_text_sha256,
            self.model,
            self.prompt_version,
            self.draft_plan_json,
            self.usage,
        )
        review_data = any((self.evidence, self.assumptions, self.warnings, self.unmapped_text))
        if self.status is PlanExtractionOperationStatus.QUEUED:
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError("queued extraction cannot have execution timestamps")
        elif self.status is PlanExtractionOperationStatus.RUNNING:
            if self.started_at is None or self.completed_at is not None:
                raise ValueError("running extraction requires only a start time")
        elif self.status is not PlanExtractionOperationStatus.CANCELLED and (
            self.started_at is None or self.completed_at is None
        ):
            raise ValueError("completed extraction requires start and completion times")
        elif self.status is PlanExtractionOperationStatus.CANCELLED and self.completed_at is None:
            raise ValueError("cancelled extraction requires completion time")
        if self.status is PlanExtractionOperationStatus.SUCCEEDED:
            if any(value is None for value in result_fields) or not self.evidence:
                raise ValueError("successful extraction requires complete review data")
            plan_json = cast(str, self.draft_plan_json)
            if dump_plan_json(load_plan_json(plan_json)) != plan_json:
                raise ValueError("draft_plan_json must be canonical")
            if any(len(item.excerpt) < 4 for item in self.evidence):
                raise ValueError("extraction evidence excerpts require four characters")
            evidence_review = tuple(
                issue
                for issue in self.validation_issues
                if issue.code == "AI_EVIDENCE_REVIEW_REQUIRED"
                and issue.severity.value == "WARNING"
                and issue.activation_blocking
            )
            if len(evidence_review) != 1:
                raise ValueError("successful extraction requires its evidence review blocker")
            if any(not item.material for item in self.unmapped_text):
                raise ValueError("unreviewed unmapped text must remain material")
        elif self.status in {
            PlanExtractionOperationStatus.INVALID_OUTPUT,
            PlanExtractionOperationStatus.PROVIDER_ERROR,
            PlanExtractionOperationStatus.CANCELLED,
        } and (any(value is not None for value in result_fields) or review_data):
            raise ValueError("failed extraction cannot expose draft or provider content")
        elif self.status in {
            PlanExtractionOperationStatus.QUEUED,
            PlanExtractionOperationStatus.RUNNING,
        } and (any(value is not None for value in result_fields) or review_data):
            raise ValueError("unfinished extraction cannot expose result content")
        return self


class ActivePlanView(ApiValue):
    symbol: AShareSymbol
    plan_version_id: UUID | None
    active: bool = Field(strict=True)
    revision: NonNegativeRevision
    changed_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_active_identity(self) -> Self:
        if self.active != (self.plan_version_id is not None):
            raise ValueError("active state and plan version identity must agree")
        return self


class PlanOperationService(Protocol):
    """Application-service contract for atomic idempotency, revision, and audit work."""

    async def list_plan_versions(
        self,
        *,
        offset: int,
        limit: int,
        symbol: str | None,
        status: PlanVersionStatus | None,
        can_activate: bool | None,
    ) -> PlanVersionPage: ...

    async def get_plan_version(self, *, version_id: str) -> PlanVersionView | None: ...

    async def save_plan_draft(
        self,
        *,
        command: PlanDraftCommand,
        context: MutationContext,
    ) -> PlanVersionView: ...

    async def import_plan(
        self,
        *,
        command: PlanImportCommand,
        context: MutationContext,
    ) -> PlanVersionView: ...

    async def submit_plan_extraction(
        self,
        *,
        command: PlanExtractionCommand,
        context: MutationContext,
    ) -> OperationReceipt: ...

    async def get_plan_extraction(self, *, operation_id: str) -> PlanExtractionView | None: ...

    async def activate_plan(
        self,
        *,
        command: PlanActivationCommand,
        context: MutationContext,
    ) -> ActivePlanView: ...

    async def deactivate_plan(
        self,
        *,
        command: PlanDeactivationCommand,
        context: MutationContext,
    ) -> ActivePlanView: ...


def get_plan_operation_service(request: Request) -> PlanOperationService:
    service = getattr(request.app.state, "plan_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(PlanOperationService, service)


PlanServiceDependency = Annotated[
    PlanOperationService,
    Depends(get_plan_operation_service),
]


def require_plan_version_collection_query(request: Request) -> None:
    names = tuple(name for name, _value in request.query_params.multi_items())
    counts = Counter(names)
    if not counts.keys() <= _PLAN_VERSION_COLLECTION_QUERY_FIELDS or any(
        count != 1 for count in counts.values()
    ):
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)


PlanVersionCollectionQueryDependency = Annotated[
    None,
    Depends(require_plan_version_collection_query),
]


@router.get("/plan-versions", response_model=PlanVersionPage)
async def list_plan_versions(
    _query: PlanVersionCollectionQueryDependency,
    service: PlanServiceDependency,
    symbol: PlanSymbolQuery = None,
    status: PlanStatusQuery = None,
    can_activate: CanActivateQuery = None,
    offset: OffsetQuery = 0,
    limit: LimitQuery = _DEFAULT_LIMIT,
) -> PlanVersionPage:
    can_activate_value = None if can_activate is None else can_activate == "true"
    page = validate_api_response(
        await service.list_plan_versions(
            offset=offset,
            limit=limit,
            symbol=symbol,
            status=status,
            can_activate=can_activate_value,
        ),
        PlanVersionPage,
    )
    if page.offset != offset or page.limit != limit:
        raise RuntimeError("plan service returned mismatched pagination")
    for item in page.items:
        if symbol is not None and item.symbol != symbol:
            raise RuntimeError("plan service returned a mismatched symbol filter")
        if status is not None and item.status is not status:
            raise RuntimeError("plan service returned a mismatched status filter")
        if can_activate_value is not None and item.can_activate != can_activate_value:
            raise RuntimeError("plan service returned a mismatched activation filter")
    return page


@router.get("/plan-versions/{version_id}", response_model=PlanVersionView)
async def get_plan_version(
    version_id: ResourceIdPath,
    service: PlanServiceDependency,
) -> PlanVersionView:
    value = await service.get_plan_version(version_id=str(version_id))
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    result = validate_api_response(value, PlanVersionView)
    if result.id != version_id:
        raise RuntimeError("plan service returned a mismatched version")
    return result


@router.post("/plan-drafts", response_model=PlanVersionView)
async def save_plan_draft(
    command: PlanDraftCommand,
    context: MutationContextDependency,
    service: PlanServiceDependency,
) -> PlanVersionView:
    result = validate_api_response(
        await service.save_plan_draft(command=command, context=context),
        PlanVersionView,
    )
    if not _matches_plan(result, load_plan_json(command.plan_json)):
        raise RuntimeError("plan service returned a mismatched draft")
    if result.status is not PlanVersionStatus.DRAFT:
        raise RuntimeError("plan service returned a non-draft version")
    if result.review_issues != command.review_issues:
        raise RuntimeError("plan service returned mismatched review state")
    if result.source_text != command.source_text:
        raise RuntimeError("plan service returned mismatched draft provenance")
    return result


@router.post("/plan-imports", response_model=PlanVersionView)
async def import_plan(
    command: PlanImportCommand,
    context: MutationContextDependency,
    service: PlanServiceDependency,
) -> PlanVersionView:
    result = validate_api_response(
        await service.import_plan(command=command, context=context),
        PlanVersionView,
    )
    plan = (
        load_plan_json(command.document)
        if command.format is PlanDocumentFormat.JSON
        else load_plan_yaml(command.document)
    )
    if not _matches_plan(result, plan):
        raise RuntimeError("plan service returned a mismatched import")
    if result.status is not PlanVersionStatus.DRAFT:
        raise RuntimeError("plan service returned a non-draft import")
    if result.review_issues:
        raise RuntimeError("manual import cannot acquire AI review state")
    if result.source_text != command.document:
        raise RuntimeError("plan service returned mismatched import provenance")
    return result


@router.post(
    "/plan-extractions",
    response_model=OperationReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_plan_extraction(
    command: PlanExtractionCommand,
    context: MutationContextDependency,
    service: PlanServiceDependency,
) -> OperationReceipt:
    receipt = validate_api_response(
        await service.submit_plan_extraction(command=command, context=context),
        OperationReceipt,
    )
    if receipt.kind is not OperationKind.PLAN_EXTRACTION:
        raise RuntimeError("plan service returned a mismatched operation kind")
    return receipt


@router.get("/plan-extractions/{operation_id}", response_model=PlanExtractionView)
async def get_plan_extraction(
    operation_id: ResourceIdPath,
    service: PlanServiceDependency,
) -> PlanExtractionView:
    value = await service.get_plan_extraction(operation_id=str(operation_id))
    if value is None:
        raise ApiError(ApiErrorCode.NOT_FOUND)
    result = validate_api_response(value, PlanExtractionView)
    if result.id != operation_id:
        raise RuntimeError("plan service returned a mismatched extraction")
    return result


@router.post("/plan-activations", response_model=ActivePlanView)
async def activate_plan(
    command: PlanActivationCommand,
    context: MutationContextDependency,
    service: PlanServiceDependency,
) -> ActivePlanView:
    result = validate_api_response(
        await service.activate_plan(command=command, context=context),
        ActivePlanView,
    )
    if not result.active or result.plan_version_id != command.plan_version_id:
        raise RuntimeError("activation service returned a mismatched active plan")
    if result.revision != command.expected_revision + 1:
        raise RuntimeError("activation service returned a stale revision")
    return result


@router.post("/plan-deactivations", response_model=ActivePlanView)
async def deactivate_plan(
    command: PlanDeactivationCommand,
    context: MutationContextDependency,
    service: PlanServiceDependency,
) -> ActivePlanView:
    result = validate_api_response(
        await service.deactivate_plan(command=command, context=context),
        ActivePlanView,
    )
    if result.active or result.symbol != command.symbol:
        raise RuntimeError("deactivation service returned a mismatched active plan")
    if result.revision != command.expected_revision + 1:
        raise RuntimeError("deactivation service returned a stale revision")
    return result


def _valid_utf8_text(value: str, *, max_bytes: int | None = None) -> str:
    if not value.strip():
        raise ValueError("source text must not be blank")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("source text must be valid UTF-8") from None
    if max_bytes is not None and len(encoded) > max_bytes:
        raise ValueError("source text exceeds its UTF-8 byte limit")
    return value


def _matches_plan(result: PlanVersionView, plan: TradePlan) -> bool:
    return (
        result.plan_id == plan.plan_id
        and result.version == plan.version
        and result.symbol == plan.symbol
        and result.plan_hash == plan_sha256(plan)
    )


__all__ = [
    "ActivePlanView",
    "PlanActivationCommand",
    "PlanDeactivationCommand",
    "PlanDraftCommand",
    "PlanExtractionCommand",
    "PlanExtractionView",
    "PlanImportCommand",
    "PlanOperationService",
    "PlanVersionPage",
    "PlanVersionView",
    "router",
]
