"""Typed plan-version and review-only extraction HTTP adapters."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query, Request, status
from pydantic import Field, field_validator, model_validator

from trade_plan_monitor.ai.models import (
    AIUsageSnapshot,
    BindingKind,
    BindingOrigin,
    BindingUnit,
    ClauseDisposition,
    ExplicitPlanDraft,
    ExtractionIssue,
    FieldEvidence,
    PlanMapping,
    RequiredReviewIssue,
    ReviewResolutionKind,
    UnmappedText,
)
from trade_plan_monitor.ai.review import (
    build_server_review_snapshot,
    dump_explicit_plan_draft_json,
    explicit_draft_content_sha256,
    explicit_draft_sha256,
    load_explicit_plan_draft_json,
)
from trade_plan_monitor.domain.plan_codec import (
    MAX_PLAN_DOCUMENT_BYTES,
    dump_plan_json,
    load_plan_json,
    load_plan_yaml,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    AShareSymbol,
    ExecutableTradePlan,
    ExplicitTradePlan,
)
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
MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_ACTIVATION_EXPECTED_REVISION = MAX_SAFE_INTEGER - 2
_MAX_DEACTIVATION_EXPECTED_REVISION = MAX_SAFE_INTEGER - 1
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
PlanSymbolPath = Annotated[AShareSymbol, Path()]
NonNegativeSafeInteger = Annotated[
    int,
    Field(strict=True, ge=0, le=MAX_SAFE_INTEGER),
]
PositiveSafeInteger = Annotated[
    int,
    Field(strict=True, gt=0, le=MAX_SAFE_INTEGER),
]
ActivationExpectedRevision = Annotated[
    int,
    Field(strict=True, ge=0, le=_MAX_ACTIVATION_EXPECTED_REVISION),
]
DeactivationExpectedRevision = Annotated[
    int,
    Field(strict=True, ge=0, le=_MAX_DEACTIVATION_EXPECTED_REVISION),
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


class ExplicitPlanCapabilityView(ApiValue):
    """Backend-owned R10 capability state; this is not an activation grant."""

    schema_version: Literal[3] = 3
    execution_mode: Literal["EXPLICIT_RULES"] = "EXPLICIT_RULES"
    execution_version: Literal["explicit-rules-v1"] = "explicit-rules-v1"
    supported_actions: tuple[Literal["BUY", "SELL", "RISK_ALERT"], ...] = (
        "BUY",
        "SELL",
        "RISK_ALERT",
    )
    public_activation_available: Literal[False] = False
    isolated_trusted_review_only: Literal[True] = True
    pending_requirements: tuple[
        Literal["ORDINARY_PLAN_FORMS",],
        ...,
    ] = ("ORDINARY_PLAN_FORMS",)


class PlanExtractionOperationStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CANCELLED = "CANCELLED"


class PlanVersionSummary(ApiValue):
    """Bounded list projection for one immutable plan-version identity."""

    id: UUID
    plan_id: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
    version: PositiveSafeInteger
    symbol: AShareSymbol
    plan_hash: Sha256Hex
    status: PlanVersionStatus
    can_activate: bool = Field(strict=True)
    revision: NonNegativeSafeInteger
    created_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_active_state(self) -> Self:
        if self.status is PlanVersionStatus.ACTIVE and not self.can_activate:
            raise ValueError("an active version cannot contain an activation blocker")
        return self


class PlanVersionView(PlanVersionSummary):
    """One immutable, canonical plan version plus its review/validation state."""

    plan_json: PlanDocument
    source_text: PlanSourceText
    review_issues: tuple[DraftReviewIssue, ...] = Field(default=(), max_length=512)
    validation_issues: tuple[ValidationIssue, ...] = Field(default=(), max_length=512)
    content_hash: Sha256Hex | None = None
    source_hash: Sha256Hex | None = None
    review_evidence_hash: Sha256Hex | None = None
    review_revision: NonNegativeSafeInteger | None = None
    review_id: UUID | None = None
    mapping: PlanMappingView | None = None
    required_review_issues: tuple[RequiredReviewIssueView, ...] = Field(
        default=(),
        max_length=512,
    )
    resolved_issue_ids: tuple[str, ...] = Field(default=(), max_length=512)
    unresolved_review_issues: tuple[RequiredReviewIssueView, ...] = Field(
        default=(),
        max_length=512,
    )
    execution_readiness: Literal["NOT_EVALUATED"] | None = None

    @field_validator("source_text")
    @classmethod
    def validate_source_text(cls, value: str) -> str:
        return _valid_utf8_text(value, max_bytes=MAX_PLAN_DOCUMENT_BYTES)

    @model_validator(mode="after")
    def validate_canonical_plan_and_activation_state(self) -> Self:
        plan = _load_reviewable_plan(self.plan_json)
        canonical = (
            dump_explicit_plan_draft_json(plan)
            if isinstance(plan, ExplicitPlanDraft)
            else dump_plan_json(plan)
        )
        if canonical != self.plan_json:
            raise ValueError("plan_json must be canonical")
        actual_hash = (
            explicit_draft_sha256(plan)
            if isinstance(plan, ExplicitPlanDraft)
            else plan_sha256(plan)
        )
        if (
            plan.plan_id != self.plan_id
            or plan.version != self.version
            or plan.symbol != self.symbol
            or actual_hash != self.plan_hash
        ):
            raise ValueError("plan version identity must match its canonical document")
        if isinstance(plan, ExplicitPlanDraft):
            explicit_fields = (
                self.content_hash,
                self.source_hash,
                self.review_evidence_hash,
                self.review_revision,
                self.mapping,
                self.execution_readiness,
            )
            if any(value is None for value in explicit_fields):
                raise ValueError("explicit drafts require their current server review snapshot")
            assert self.mapping is not None
            snapshot = build_server_review_snapshot(
                draft=plan,
                mapping=self.mapping.to_domain(),
                source_text=self.source_text,
            )
            required_domain = tuple(
                RequiredReviewIssue.model_validate_json(item.model_dump_json(by_alias=False))
                for item in self.required_review_issues
            )
            if (
                self.content_hash != explicit_draft_content_sha256(plan)
                or self.source_hash != snapshot.source_hash
                or self.review_evidence_hash != snapshot.review_evidence_hash
                or required_domain != snapshot.required_issues
            ):
                raise ValueError("explicit review snapshot must match current content and source")
            required_ids = {item.issue_id for item in self.required_review_issues}
            resolved_ids = set(self.resolved_issue_ids)
            unresolved_ids = {item.issue_id for item in self.unresolved_review_issues}
            if (
                not resolved_ids <= required_ids
                or unresolved_ids != required_ids - resolved_ids
                or (self.review_id is not None) != (not unresolved_ids)
            ):
                raise ValueError("explicit review resolution state is inconsistent")
            expected_can_activate = (
                plan.to_executable() is not None
                and self.review_id is not None
                and not unresolved_ids
            )
            if self.can_activate != expected_can_activate:
                raise ValueError("can_activate must match the current explicit review snapshot")
            return self
        expected_can_activate = not any(
            issue.activation_blocking for issue in self.validation_issues
        ) and not any(not issue.resolved for issue in self.review_issues)
        if self.can_activate != expected_can_activate:
            raise ValueError("can_activate must match unresolved review and validation state")
        return self


class PlanVersionPage(ApiValue):
    items: tuple[PlanVersionSummary, ...] = Field(default=(), max_length=_MAX_LIMIT)
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
    base_plan_version_id: UUID | None = Field(default=None, strict=False)
    extraction_id: UUID | None = Field(default=None, strict=False)
    plan_json: PlanDocument
    source_text: PlanSourceText
    review_issues: tuple[DraftReviewIssue, ...] = Field(
        default=(),
        max_length=512,
        strict=False,
    )
    expected_revision: NonNegativeSafeInteger
    mapping: PlanMappingView | None = None

    @field_validator("plan_json")
    @classmethod
    def validate_plan_json(cls, value: str) -> str:
        _validate_web_plan(_load_reviewable_plan(value))
        return value

    @field_validator("source_text")
    @classmethod
    def validate_source_text(cls, value: str) -> str:
        return _valid_utf8_text(value, max_bytes=MAX_PLAN_DOCUMENT_BYTES)


class PlanImportCommand(ApiValue):
    symbol: AShareSymbol
    format: PlanDocumentFormat = Field(strict=False)
    document: PlanDocument
    expected_revision: NonNegativeSafeInteger

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        plan = (
            load_plan_json(self.document)
            if self.format is PlanDocumentFormat.JSON
            else load_plan_yaml(self.document)
        )
        _validate_web_plan(plan)
        if plan.symbol != self.symbol:
            raise ValueError("symbol must match the imported plan document")
        return self


class PlanExtractionCommand(ApiValue):
    provider_id: UUID = Field(strict=False)
    source_text: ExtractionSourceText
    expected_revision: NonNegativeSafeInteger

    @field_validator("source_text")
    @classmethod
    def validate_source_text(cls, value: str) -> str:
        return _valid_utf8_text(value)


class PlanActivationCommand(ApiValue):
    plan_version_id: UUID = Field(strict=False)
    review_id: UUID | None = Field(default=None, strict=False)
    content_hash: Sha256Hex | None = None
    expected_revision: ActivationExpectedRevision


class SourceClauseView(ApiValue):
    clause_id: str
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    excerpt: str = Field(strict=True, min_length=1, max_length=512)
    disposition: ClauseDisposition = Field(strict=False)
    paths: tuple[str, ...] = Field(default=(), max_length=256, strict=False)


class FieldBindingView(ApiValue):
    path: str
    value: bool | int | str | None
    unit: BindingUnit = Field(strict=False)
    origin: BindingOrigin = Field(strict=False)
    binding_kind: BindingKind = Field(default=BindingKind.VALUE, strict=False)
    clause_ids: tuple[str, ...] = Field(default=(), max_length=64, strict=False)
    supplement_id: str | None = None
    contract_id: str | None = None


class UserSupplementView(ApiValue):
    supplement_id: str
    path: str
    value: bool | int | str | None
    unit: BindingUnit = Field(strict=False)
    supplied_at: ShanghaiDatetime = Field(strict=False)
    label: Literal["human_confirmed_test_supplement", "human_confirmed_supplement"]


class SourceSpanView(ApiValue):
    clause_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    excerpt: str = Field(min_length=1, max_length=512)


class InventorySourceTreatmentView(ApiValue):
    kind: Literal["INVENTORY_ASSERTION"]
    treatment_id: str
    contract_id: Literal["independent-inventory-v1"]
    spans: tuple[SourceSpanView, ...] = Field(min_length=2, max_length=2, strict=False)
    symbol_span: SourceSpanView
    symbol: AShareSymbol
    total_quantity: NonNegativeSafeInteger
    sellable_quantity: NonNegativeSafeInteger
    settlement_basis: Literal["HELD_BEFORE_TEST_DATE_ALL_SELLABLE"]
    required_operation: Literal["/api/v1/position-inventory-confirmations"]
    ledger_effect: Literal["NONE_REQUIRES_INDEPENDENT_CONFIRMATION"]


class ProductSourceTreatmentView(ApiValue):
    kind: Literal["PRODUCT_GUARANTEE"]
    treatment_id: str
    contract_id: Literal["alert-position-isolation-v1"]
    spans: tuple[SourceSpanView, ...] = Field(min_length=2, max_length=2, strict=False)
    guarantee: Literal["ALERTS_AND_ACKNOWLEDGEMENTS_DO_NOT_CHANGE_POSITIONS"]


class SourceProcessingView(ApiValue):
    version: Literal["source-processing-v1"]
    treatments: tuple[
        Annotated[
            InventorySourceTreatmentView | ProductSourceTreatmentView, Field(discriminator="kind")
        ],
        ...,
    ] = Field(max_length=512, strict=False)


class PlanMappingView(ApiValue):
    mapping_version: Literal["plan-mapping-v1", "plan-mapping-v2"] = "plan-mapping-v1"
    source_clauses: tuple[SourceClauseView, ...] = Field(min_length=1, max_length=512, strict=False)
    field_bindings: tuple[FieldBindingView, ...] = Field(
        default=(), max_length=10_000, strict=False
    )
    user_supplements: tuple[UserSupplementView, ...] = Field(
        default=(), max_length=512, strict=False
    )
    source_processing: SourceProcessingView | None = None

    def to_domain(self) -> PlanMapping:
        return PlanMapping.model_validate_json(
            self.model_dump_json(by_alias=False),
        )

    @classmethod
    def from_domain(cls, value: PlanMapping) -> PlanMappingView:
        return cls.model_validate_json(value.model_dump_json())


class RequiredReviewIssueView(ApiValue):
    issue_id: str
    code: str
    path: str
    reason: str
    clause_id: str | None = None
    binding_path: str | None = None
    allowed_resolutions: tuple[ReviewResolutionKind, ...] = Field(max_length=3, strict=False)

    @classmethod
    def from_domain(cls, value: RequiredReviewIssue) -> RequiredReviewIssueView:
        return cls.model_validate_json(value.model_dump_json())


class PlanReviewResolution(ApiValue):
    issue_id: str
    resolution: ReviewResolutionKind = Field(strict=False)
    binding_path: str | None = None
    supplement_id: str | None = None


class PlanReviewConfirmationCommand(ApiValue):
    plan_version_id: UUID = Field(strict=False)
    content_hash: Sha256Hex
    source_hash: Sha256Hex
    review_evidence_hash: Sha256Hex
    expected_revision: NonNegativeSafeInteger
    resolutions: tuple[PlanReviewResolution, ...] = Field(default=(), max_length=512, strict=False)


class PlanReviewConfirmationView(ApiValue):
    plan_version_id: UUID
    review_id: UUID | None
    content_hash: Sha256Hex
    source_hash: Sha256Hex
    review_evidence_hash: Sha256Hex
    revision: NonNegativeSafeInteger
    confirmed_at: ShanghaiDatetime | None
    unresolved_issues: tuple[RequiredReviewIssueView, ...] = Field(default=(), max_length=512)
    can_activate: bool = Field(strict=True)


class PlanDeactivationCommand(ApiValue):
    symbol: AShareSymbol
    expected_revision: DeactivationExpectedRevision


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
    mapping: PlanMappingView | None = None
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
            if any(value is None for value in result_fields):
                raise ValueError("successful extraction requires complete review data")
            plan_json = cast(str, self.draft_plan_json)
            plan = _load_reviewable_plan(plan_json)
            canonical = (
                dump_explicit_plan_draft_json(plan)
                if isinstance(plan, ExplicitPlanDraft)
                else dump_plan_json(plan)
            )
            if canonical != plan_json:
                raise ValueError("draft_plan_json must be canonical")
            if self.prompt_version == "plan-extract-v4":
                if self.mapping is None or self.evidence or self.unmapped_text:
                    raise ValueError("v4 extraction requires only its bidirectional mapping")
            else:
                if not self.evidence or self.mapping is not None:
                    raise ValueError("legacy extraction requires field evidence")
                if any(len(item.excerpt) < 4 for item in self.evidence):
                    raise ValueError("extraction evidence excerpts require four characters")
            evidence_review = tuple(
                issue
                for issue in self.validation_issues
                if issue.code == "AI_EVIDENCE_REVIEW_REQUIRED"
                and issue.severity.value == "WARNING"
                and issue.activation_blocking
            )
            if self.prompt_version != "plan-extract-v4" and len(evidence_review) != 1:
                raise ValueError("successful extraction requires its evidence review blocker")
            if any(not item.material for item in self.unmapped_text):
                raise ValueError("unreviewed unmapped text must remain material")
        elif self.status in {
            PlanExtractionOperationStatus.INVALID_OUTPUT,
            PlanExtractionOperationStatus.PROVIDER_ERROR,
            PlanExtractionOperationStatus.CANCELLED,
        } and (any(value is not None for value in result_fields) or review_data or self.mapping):
            raise ValueError("failed extraction cannot expose draft or provider content")
        elif self.status in {
            PlanExtractionOperationStatus.QUEUED,
            PlanExtractionOperationStatus.RUNNING,
        } and (any(value is not None for value in result_fields) or review_data or self.mapping):
            raise ValueError("unfinished extraction cannot expose result content")
        return self


class ActivePlanView(ApiValue):
    symbol: AShareSymbol
    plan_version_id: UUID | None
    active: bool = Field(strict=True)
    revision: NonNegativeSafeInteger
    changed_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_active_identity(self) -> Self:
        if self.active != (self.plan_version_id is not None):
            raise ValueError("active state and plan version identity must agree")
        return self


class PlanExtractionService(Protocol):
    """Application-service contract for review-only configured AI operations."""

    async def submit_plan_extraction(
        self,
        *,
        command: PlanExtractionCommand,
        context: MutationContext,
    ) -> OperationReceipt: ...

    async def get_plan_extraction(self, *, operation_id: str) -> PlanExtractionView | None: ...


class PlanOperationService(PlanExtractionService, Protocol):
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

    async def get_plan_activation_state(self, *, symbol: str) -> ActivePlanView | None: ...

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

    async def confirm_plan_review(
        self,
        *,
        command: PlanReviewConfirmationCommand,
        context: MutationContext,
    ) -> PlanReviewConfirmationView: ...

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


def get_plan_extraction_service(request: Request) -> PlanExtractionService:
    service = getattr(request.app.state, "plan_extraction_service", None)
    if service is None:
        service = getattr(request.app.state, "plan_operation_service", None)
    if service is None:
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
    return cast(PlanExtractionService, service)


PlanExtractionServiceDependency = Annotated[
    PlanExtractionService,
    Depends(get_plan_extraction_service),
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


@router.get("/plan-activation-states/{symbol}", response_model=ActivePlanView)
async def get_plan_activation_state(
    symbol: PlanSymbolPath,
    service: PlanServiceDependency,
) -> ActivePlanView:
    value = await service.get_plan_activation_state(symbol=symbol)
    if value is None:
        value = ActivePlanView(
            symbol=symbol,
            plan_version_id=None,
            active=False,
            revision=0,
            changed_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
    result = validate_api_response(value, ActivePlanView)
    if result.symbol != symbol:
        raise RuntimeError("plan service returned a mismatched activation state")
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
    submitted_plan = _load_reviewable_plan(command.plan_json)
    expected_plan = (
        submitted_plan
        if command.base_plan_version_id is None
        else submitted_plan.model_copy(update={"version": result.version})
    )
    if not _matches_plan(result, expected_plan):
        raise RuntimeError("plan service returned a mismatched draft")
    if result.status is not PlanVersionStatus.DRAFT:
        raise RuntimeError("plan service returned a non-draft version")
    if result.source_text != command.source_text:
        raise RuntimeError("plan service returned mismatched draft provenance")
    unresolved_submitted = {
        (issue.kind, issue.path, issue.material)
        for issue in command.review_issues
        if not issue.resolved
    }
    returned_issues = {(issue.kind, issue.path, issue.material) for issue in result.review_issues}
    if not unresolved_submitted <= returned_issues:
        raise RuntimeError("plan service dropped an unresolved review issue")
    return result


@router.post("/plan-imports", response_model=PlanVersionView)
async def import_plan(
    command: PlanImportCommand,
    context: MutationContextDependency,
    service: PlanServiceDependency,
) -> PlanVersionView:
    imported = (
        load_plan_json(command.document)
        if command.format is PlanDocumentFormat.JSON
        else load_plan_yaml(command.document)
    )
    if isinstance(imported, ExplicitTradePlan):
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
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
    if result.symbol != command.symbol:
        raise RuntimeError("plan service returned an import for another symbol")
    if result.status is not PlanVersionStatus.DRAFT:
        raise RuntimeError("plan service returned a non-draft import")
    if result.review_issues:
        raise RuntimeError("manual import cannot acquire AI review state")
    if result.source_text != command.document:
        raise RuntimeError("plan service returned mismatched import provenance")
    return result


@router.get("/plan-capabilities", response_model=ExplicitPlanCapabilityView)
async def get_explicit_plan_capability() -> ExplicitPlanCapabilityView:
    return ExplicitPlanCapabilityView()


@router.post("/plan-review-confirmations", response_model=PlanReviewConfirmationView)
async def confirm_plan_review(
    command: PlanReviewConfirmationCommand,
    context: MutationContextDependency,
    service: PlanServiceDependency,
) -> PlanReviewConfirmationView:
    result = validate_api_response(
        await service.confirm_plan_review(command=command, context=context),
        PlanReviewConfirmationView,
    )
    if (
        result.plan_version_id != command.plan_version_id
        or result.content_hash != command.content_hash
        or result.source_hash != command.source_hash
        or result.review_evidence_hash != command.review_evidence_hash
    ):
        raise RuntimeError("plan review service returned a mismatched binding")
    if result.revision < command.expected_revision:
        raise RuntimeError("plan review service returned a stale revision")
    return result


@router.post(
    "/plan-extractions",
    response_model=OperationReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_plan_extraction(
    command: PlanExtractionCommand,
    context: MutationContextDependency,
    service: PlanExtractionServiceDependency,
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
    service: PlanExtractionServiceDependency,
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


def _load_reviewable_plan(document: str) -> ExecutableTradePlan | ExplicitPlanDraft:
    try:
        return load_explicit_plan_draft_json(document)
    except ValueError:
        return load_plan_json(document)


def _validate_web_plan(
    plan: ExecutableTradePlan | ExplicitPlanDraft,
) -> ExecutableTradePlan | ExplicitPlanDraft:
    if plan.version > MAX_SAFE_INTEGER:
        raise ValueError("plan version exceeds the Web safe-integer limit")
    return plan


def _matches_plan(result: PlanVersionView, plan: ExecutableTradePlan) -> bool:
    expected_hash = (
        explicit_draft_sha256(plan) if isinstance(plan, ExplicitPlanDraft) else plan_sha256(plan)
    )
    return (
        result.plan_id == plan.plan_id
        and result.version == plan.version
        and result.symbol == plan.symbol
        and result.plan_hash == expected_hash
    )


__all__ = [
    "ActivePlanView",
    "ExplicitPlanCapabilityView",
    "MAX_SAFE_INTEGER",
    "PlanActivationCommand",
    "PlanDeactivationCommand",
    "PlanDraftCommand",
    "PlanExtractionCommand",
    "PlanExtractionService",
    "PlanExtractionView",
    "PlanImportCommand",
    "PlanOperationService",
    "PlanReviewConfirmationCommand",
    "PlanReviewConfirmationView",
    "PlanReviewResolution",
    "PlanMappingView",
    "PlanVersionPage",
    "PlanVersionSummary",
    "PlanVersionView",
    "router",
]
