"""Strict AI configuration, extraction, provenance, and result models.

Validation follows Pydantic URL/validator APIs and Python loopback semantics:
https://docs.pydantic.dev/latest/api/networks/
https://docs.pydantic.dev/latest/concepts/validators/
https://docs.pydantic.dev/latest/concepts/models/
https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Address.is_loopback
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from ipaddress import ip_address
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import (
    ActivationPolicy,
    AShareSymbol,
    ExplicitRepeatPolicy,
    ExplicitTradePlan,
    Market,
    PlanId,
    PlanMetadata,
    PlanName,
    PositiveBoardLotQuantity,
    PositiveVersion,
    TradePlan,
)
from trade_plan_monitor.domain.plan_validation import (
    DraftReviewIssue,
    ReviewIssueKind,
    ValidationIssue,
)

DisplayName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$"),
]
ModelName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]
PromptVersion = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
]
SecretKeyReference = Annotated[
    str,
    StringConstraints(
        min_length=13,
        max_length=140,
        pattern=r"^ai/provider/[A-Za-z0-9_-]{1,128}$",
    ),
]
ExtractionPath = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9_.\[\]-]+$",
    ),
]
EvidenceExcerpt = Annotated[str, StringConstraints(min_length=1, max_length=512)]
ExtractionMessage = Annotated[str, StringConstraints(min_length=1, max_length=512)]
SourceTextSha256 = Annotated[
    str,
    StringConstraints(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]


class _AIValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
        str_strip_whitespace=True,
    )


class AIProviderType(StrEnum):
    """Provider contracts supported by the first release."""

    OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"


class AIProviderProfile(StrEnum):
    """Request dialect selected by non-secret application configuration."""

    DEEPSEEK = "DEEPSEEK"
    OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"


class SecretReference(_AIValue):
    """Non-secret process-local store key."""

    key: SecretKeyReference


class AIProviderConfig(_AIValue):
    """Validated provider settings that never contain API-key material."""

    provider_id: UUID
    display_name: DisplayName
    provider_type: AIProviderType = AIProviderType.OPENAI_COMPATIBLE
    base_url: AnyHttpUrl
    model: ModelName
    secret_ref: SecretReference
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retries: int = Field(default=2, ge=0, le=2)
    max_input_chars: int = Field(default=50_000, ge=1, le=200_000)
    max_output_tokens: int = Field(default=4_096, ge=1, le=16_384)
    temperature: float = Field(default=0, ge=0, le=0.3)
    prompt_version: PromptVersion = "plan-extract-v4"
    allow_redirects: Literal[False] = False
    enabled: bool = True

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy provider configuration without bypassing URL and resource limits."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)

    @model_validator(mode="wrap")
    @classmethod
    def remove_validation_inputs(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> Self:
        safe_error: ValidationError | None = None
        try:
            return handler(value)
        except ValidationError as error:
            safe_error = _validation_error_without_inputs(error)
        if safe_error is not None:
            raise safe_error
        raise AssertionError("validation boundary completed without a result")

    @field_validator("base_url")
    @classmethod
    def require_safe_base_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if len(str(value)) > 2_048:
            raise ValueError("base_url must not exceed 2048 characters")
        if value.username is not None or value.password is not None:
            raise ValueError("base_url must not contain embedded credentials")
        if value.query is not None or value.fragment is not None:
            raise ValueError("base_url must not contain a query or fragment")
        if value.scheme == "http" and not _is_explicit_loopback(value.host):
            raise ValueError("base_url must use HTTPS unless the host is loopback")
        return value


class TradePlanDraft(TradePlan):
    """Validated, immutable plan candidate with no activation capability."""


class PartialCompletedCloseInRange(_AIValue):
    type: Literal["COMPLETED_CLOSE_IN_RANGE"] = "COMPLETED_CLOSE_IN_RANGE"
    low_fen: Annotated[int, Field(strict=True, gt=0)] | None
    high_fen: Annotated[int, Field(strict=True, gt=0)] | None
    include_low: Annotated[bool, Field(strict=True)] | None
    include_high: Annotated[bool, Field(strict=True)] | None


class PartialVolumeToMeanGte(_AIValue):
    type: Literal["VOLUME_TO_MEAN_GTE"] = "VOLUME_TO_MEAN_GTE"
    window_bars: Annotated[int, Field(strict=True, ge=1, le=500)] | None
    minimum_ratio: (
        Annotated[
            str,
            StringConstraints(pattern=r"^(?:0\.[0-9]*[1-9]|[1-9](?:\.[0-9]*[1-9])?|10)$"),
        ]
        | None
    )
    history_scope: Literal["CONTIGUOUS_TRADING_BARS"] | None


class PartialCompletedCloseBelow(_AIValue):
    type: Literal["COMPLETED_CLOSE_BELOW"] = "COMPLETED_CLOSE_BELOW"
    price_fen: Annotated[int, Field(strict=True, gt=0)] | None


class PartialManualEventRiskClear(_AIValue):
    type: Literal["MANUAL_EVENT_RISK_CLEAR"] = "MANUAL_EVENT_RISK_CLEAR"


class PartialExplicitAll(_AIValue):
    type: Literal["ALL"] = "ALL"
    conditions: tuple[PartialExplicitCondition, ...] = Field(min_length=1, max_length=50)


class PartialExplicitAny(_AIValue):
    type: Literal["ANY"] = "ANY"
    conditions: tuple[PartialExplicitCondition, ...] = Field(min_length=1, max_length=50)


PartialExplicitCondition = Annotated[
    PartialCompletedCloseInRange
    | PartialVolumeToMeanGte
    | PartialCompletedCloseBelow
    | PartialManualEventRiskClear
    | PartialExplicitAll
    | PartialExplicitAny,
    Field(discriminator="type"),
]

PartialExplicitAll.model_rebuild()
PartialExplicitAny.model_rebuild()


class PartialExplicitBuyAction(_AIValue):
    type: Literal["BUY"] = "BUY"
    quantity: PositiveBoardLotQuantity | None


class PartialExplicitSellAction(_AIValue):
    type: Literal["SELL"] = "SELL"
    quantity: PositiveBoardLotQuantity | None
    inventory_scope: Literal["ALL_REGISTERED"] | None


class PartialExplicitRiskAction(_AIValue):
    type: Literal["RISK_ALERT"] = "RISK_ALERT"


PartialExplicitAction = Annotated[
    PartialExplicitBuyAction | PartialExplicitSellAction | PartialExplicitRiskAction,
    Field(discriminator="type"),
]


class PartialExplicitPosition(_AIValue):
    inventory_scope: Literal["ALL_REGISTERED"] | None
    lot_size: Literal[100] | None
    max_qty: PositiveBoardLotQuantity | None


class PartialMonitoringPolicy(_AIValue):
    timeframe_minutes: Literal[5] | None
    indicator_formula_version: Literal["ta-v1"] | None


class PartialCompletedBarConfirmation(_AIValue):
    kind: Literal["COMPLETED_BAR_CLOSE"] | None
    timeframe_minutes: Literal[5] | None


class PartialExplicitConflictPolicy(_AIValue):
    trade_conflict: Literal["BLOCK_BOTH"] | None
    risk_conflict: Literal["RISK_ONLY", "RISK_WITH_SELL_BLOCK_BUY"] | None


class PartialExplicitRule(_AIValue):
    rule_id: PlanId
    condition: PartialExplicitCondition | None
    action: PartialExplicitAction
    confirmation: PartialCompletedBarConfirmation | None
    repeat_policy: ExplicitRepeatPolicy | None
    safety_conditions: PartialExplicitCondition | None


class ExplicitPlanDraft(_AIValue):
    """Bounded Schema-v3 draft that preserves unresolved typed nulls."""

    schema_version: Literal[3] = 3
    execution_mode: Literal["EXPLICIT_RULES"] = "EXPLICIT_RULES"
    execution_version: Literal["explicit-rules-v1"] = "explicit-rules-v1"
    plan_id: PlanId
    version: PositiveVersion
    symbol: AShareSymbol
    name: PlanName
    market: Market
    metadata: PlanMetadata
    activation: ActivationPolicy | None
    position: PartialExplicitPosition
    monitoring: PartialMonitoringPolicy
    rules: tuple[PartialExplicitRule, ...] = Field(min_length=1, max_length=3)
    conflict_policy: PartialExplicitConflictPolicy | None

    @model_validator(mode="after")
    def require_unique_rule_and_action_identities(self) -> Self:
        rule_ids = tuple(rule.rule_id for rule in self.rules)
        actions = tuple(rule.action.type for rule in self.rules)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("explicit draft rule_id values must be unique")
        if len(set(actions)) != len(actions):
            raise ValueError("explicit drafts allow at most one rule per action type")
        return self

    def to_executable(self) -> ExplicitTradePlan | None:
        """Return the strict executable sibling only when no required value is unresolved."""

        try:
            return ExplicitTradePlan.model_validate(self.model_dump(mode="python"))
        except ValidationError:
            return None


class ClauseDisposition(StrEnum):
    MAPPED = "MAPPED"
    UNRESOLVED = "UNRESOLVED"
    UNSUPPORTED = "UNSUPPORTED"


class BindingUnit(StrEnum):
    FEN = "FEN"
    SHARES = "SHARES"
    BARS = "BARS"
    MINUTES = "MINUTES"
    RATIO = "RATIO"
    NONE = "NONE"


class BindingOrigin(StrEnum):
    SOURCE = "SOURCE"
    USER_SUPPLEMENT = "USER_SUPPLEMENT"
    CONTRACT = "CONTRACT"


class BindingKind(StrEnum):
    VALUE = "VALUE"
    STRUCTURE = "STRUCTURE"


ClauseId = Annotated[
    str,
    StringConstraints(pattern=r"^clause-[0-9a-f]{16}$"),
]
SupplementId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]
BindingValue = bool | int | str | None


class SourceClause(_AIValue):
    clause_id: ClauseId
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    excerpt: EvidenceExcerpt
    disposition: ClauseDisposition
    paths: tuple[ExtractionPath, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def validate_span_and_paths(self) -> Self:
        if self.end <= self.start:
            raise ValueError("source clause end must be greater than start")
        if len(set(self.paths)) != len(self.paths):
            raise ValueError("source clause paths must be unique")
        if self.disposition is ClauseDisposition.MAPPED and not self.paths:
            raise ValueError("a mapped source clause requires destination paths")
        if self.disposition is not ClauseDisposition.MAPPED and self.paths:
            raise ValueError("unresolved or unsupported clauses cannot claim mapped paths")
        return self


class UserSupplement(_AIValue):
    supplement_id: SupplementId
    path: ExtractionPath
    value: BindingValue
    unit: BindingUnit
    supplied_at: datetime
    label: Literal["human_confirmed_test_supplement", "human_confirmed_supplement"]


class FieldBinding(_AIValue):
    path: ExtractionPath
    value: BindingValue
    unit: BindingUnit
    origin: BindingOrigin
    binding_kind: BindingKind = BindingKind.VALUE
    clause_ids: tuple[ClauseId, ...] = Field(default=(), max_length=64)
    supplement_id: SupplementId | None = None
    contract_id: SupplementId | None = None

    @model_validator(mode="after")
    def validate_origin_reference(self) -> Self:
        if len(set(self.clause_ids)) != len(self.clause_ids):
            raise ValueError("field binding clause references must be unique")
        if self.origin is BindingOrigin.SOURCE:
            valid = (
                bool(self.clause_ids) and self.supplement_id is None and self.contract_id is None
            )
        elif self.origin is BindingOrigin.USER_SUPPLEMENT:
            valid = (
                not self.clause_ids and self.supplement_id is not None and self.contract_id is None
            )
        else:
            valid = (
                not self.clause_ids and self.supplement_id is None and self.contract_id is not None
            )
            if valid and not _contract_binding_path(self.path):
                raise ValueError("CONTRACT cannot supply a trading parameter")
        if not valid:
            raise ValueError("field binding origin reference is inconsistent")
        if self.binding_kind is BindingKind.STRUCTURE and self.value not in {"ALL", "ANY"}:
            raise ValueError("structural bindings are limited to ALL or ANY")
        return self


def _contract_binding_path(path: str) -> bool:
    if path in {
        "schema_version",
        "execution_mode",
        "execution_version",
        "plan_id",
        "version",
        "name",
        "market",
        "metadata",
        "position.inventory_scope",
        "position.lot_size",
        "monitoring.indicator_formula_version",
    }:
        return True
    return path.endswith(".rule_id")


class SourceSpan(_AIValue):
    clause_id: ClauseId
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    excerpt: EvidenceExcerpt


class InventorySourceTreatment(_AIValue):
    kind: Literal["INVENTORY_ASSERTION"] = "INVENTORY_ASSERTION"
    treatment_id: SupplementId
    contract_id: Literal["independent-inventory-v1"] = "independent-inventory-v1"
    spans: tuple[SourceSpan, SourceSpan]
    symbol_span: SourceSpan
    symbol: AShareSymbol
    total_quantity: int = Field(strict=True, ge=0, le=9_007_199_254_740_991)
    sellable_quantity: int = Field(strict=True, ge=0, le=9_007_199_254_740_991)
    settlement_basis: Literal["HELD_BEFORE_TEST_DATE_ALL_SELLABLE"] = (
        "HELD_BEFORE_TEST_DATE_ALL_SELLABLE"
    )
    required_operation: Literal["/api/v1/position-inventory-confirmations"] = (
        "/api/v1/position-inventory-confirmations"
    )
    ledger_effect: Literal["NONE_REQUIRES_INDEPENDENT_CONFIRMATION"] = (
        "NONE_REQUIRES_INDEPENDENT_CONFIRMATION"
    )


class ProductSourceTreatment(_AIValue):
    kind: Literal["PRODUCT_GUARANTEE"] = "PRODUCT_GUARANTEE"
    treatment_id: SupplementId
    contract_id: Literal["alert-position-isolation-v1"] = "alert-position-isolation-v1"
    spans: tuple[SourceSpan, SourceSpan]
    guarantee: Literal["ALERTS_AND_ACKNOWLEDGEMENTS_DO_NOT_CHANGE_POSITIONS"] = (
        "ALERTS_AND_ACKNOWLEDGEMENTS_DO_NOT_CHANGE_POSITIONS"
    )


SourceTreatment = Annotated[
    InventorySourceTreatment | ProductSourceTreatment, Field(discriminator="kind")
]


class SourceProcessing(_AIValue):
    version: Literal["source-processing-v1"] = "source-processing-v1"
    treatments: tuple[SourceTreatment, ...] = Field(default=(), max_length=512)


class PlanMapping(_AIValue):
    mapping_version: Literal["plan-mapping-v1", "plan-mapping-v2"] = "plan-mapping-v1"
    source_clauses: tuple[SourceClause, ...] = Field(min_length=1, max_length=512)
    field_bindings: tuple[FieldBinding, ...] = Field(default=(), max_length=10_000)
    user_supplements: tuple[UserSupplement, ...] = Field(default=(), max_length=512)
    source_processing: SourceProcessing | None = None

    @model_validator(mode="after")
    def require_unique_identities(self) -> Self:
        if (self.mapping_version == "plan-mapping-v2") != (self.source_processing is not None):
            raise ValueError("v2 mapping requires versioned source processing; v1 forbids it")
        clauses = tuple(item.clause_id for item in self.source_clauses)
        bindings = tuple((item.binding_kind, item.path) for item in self.field_bindings)
        supplements = tuple(item.supplement_id for item in self.user_supplements)
        if len(set(clauses)) != len(clauses):
            raise ValueError("source clause identities must be unique")
        if len(set(bindings)) != len(bindings):
            raise ValueError("field binding identities must be unique")
        if len(set(supplements)) != len(supplements):
            raise ValueError("user supplement identities must be unique")
        return self


class ReviewResolutionKind(StrEnum):
    CONFIRM_MAPPING = "CONFIRM_MAPPING"
    CONFIRM_POLICY = "CONFIRM_POLICY"
    CONFIRM_SOURCE_TREATMENT = "CONFIRM_SOURCE_TREATMENT"
    REPLACED_BY_REVIEWED_CONTENT = "REPLACED_BY_REVIEWED_CONTENT"


class RequiredReviewIssue(_AIValue):
    issue_id: Annotated[str, StringConstraints(pattern=r"^issue-[0-9a-f]{24}$")]
    code: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
    path: ExtractionPath
    reason: ExtractionMessage
    clause_id: ClauseId | None = None
    binding_path: ExtractionPath | None = None
    allowed_resolutions: tuple[ReviewResolutionKind, ...] = Field(min_length=1, max_length=3)


class ReviewResolution(_AIValue):
    issue_id: Annotated[str, StringConstraints(pattern=r"^issue-[0-9a-f]{24}$")]
    resolution: ReviewResolutionKind
    binding_path: ExtractionPath | None = None
    supplement_id: SupplementId | None = None


class ServerReviewSnapshot(_AIValue):
    source_hash: SourceTextSha256
    content_hash: SourceTextSha256
    review_evidence_hash: SourceTextSha256
    mapping: PlanMapping
    required_issues: tuple[RequiredReviewIssue, ...] = Field(default=(), max_length=512)
    can_activate: bool


class PlanExtractionOutputV4(_AIValue):
    """Separate v4 AI envelope for partial explicit drafts and bidirectional evidence."""

    draft: ExplicitPlanDraft
    mapping_version: Literal["plan-mapping-v1"] = "plan-mapping-v1"
    source_clauses: tuple[SourceClause, ...] = Field(min_length=1, max_length=512)
    field_bindings: tuple[FieldBinding, ...] = Field(default=(), max_length=10_000)
    assumptions: tuple[ExtractionIssue, ...] = Field(default=(), max_length=256)
    warnings: tuple[ExtractionIssue, ...] = Field(default=(), max_length=256)

    def to_mapping(self) -> PlanMapping:
        return PlanMapping(
            source_clauses=self.source_clauses,
            field_bindings=self.field_bindings,
        )


class FieldEvidence(_AIValue):
    """One draft leaf mapped to a bounded source excerpt or exact location."""

    path: ExtractionPath
    excerpt: EvidenceExcerpt
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_complete_valid_location(self) -> FieldEvidence:
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must both be present or absent")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class ExtractionIssue(_AIValue):
    """Bounded AI-reported assumption or warning awaiting user review."""

    path: ExtractionPath
    message: ExtractionMessage
    material: bool


class UnmappedText(_AIValue):
    """Unsupported source text that cannot become an executable condition."""

    path: ExtractionPath
    excerpt: EvidenceExcerpt
    reason: ExtractionMessage
    material: bool
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_complete_valid_location(self) -> UnmappedText:
        if (self.start is None) != (self.end is None):
            raise ValueError("start and end must both be present or absent")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class PlanExtractionOutput(_AIValue):
    """Only JSON shape accepted from an untrusted AI provider."""

    draft: TradePlanDraft
    evidence: tuple[FieldEvidence, ...] = Field(max_length=10_000)
    assumptions: tuple[ExtractionIssue, ...] = Field(default=(), max_length=256)
    warnings: tuple[ExtractionIssue, ...] = Field(default=(), max_length=256)
    unmapped_text: tuple[UnmappedText, ...] = Field(default=(), max_length=256)


class PlanExtractionStatus(StrEnum):
    """Stable extraction outcomes; none grants activation authority."""

    SUCCEEDED = "SUCCEEDED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CANCELLED = "CANCELLED"


class AIUsageSnapshot(_AIValue):
    """Immutable copy of validated provider usage without transport coupling."""

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class PlanExtractionResult(_AIValue):
    """Review-only extraction receipt with draft provenance and local issues."""

    request_id: UUID
    provider_id: UUID
    model: ModelName
    prompt_version: PromptVersion
    source_text_sha256: SourceTextSha256
    draft: TradePlanDraft | ExplicitPlanDraft | None
    mapping: PlanMapping | None = None
    evidence: tuple[FieldEvidence, ...] = ()
    assumptions: tuple[ExtractionIssue, ...] = ()
    warnings: tuple[ExtractionIssue, ...] = ()
    unmapped_text: tuple[UnmappedText, ...] = ()
    validation_issues: tuple[ValidationIssue, ...] = ()
    usage: AIUsageSnapshot | None
    status: PlanExtractionStatus

    @model_validator(mode="after")
    def enforce_status_payload_consistency(self) -> PlanExtractionResult:
        if self.status is PlanExtractionStatus.SUCCEEDED:
            if self.draft is None or not self.evidence:
                if not isinstance(self.draft, ExplicitPlanDraft) or self.mapping is None:
                    raise ValueError("a succeeded extraction requires a draft and evidence")
            if self.prompt_version == "plan-extract-v4" and self.mapping is None:
                raise ValueError("a v4 extraction requires a plan mapping")
            if self.prompt_version != "plan-extract-v4" and self.mapping is not None:
                raise ValueError("legacy extraction versions cannot contain a v4 mapping")
            return self
        if (
            self.draft is not None
            or any((self.evidence, self.assumptions, self.warnings, self.unmapped_text))
            or self.mapping is not None
        ):
            raise ValueError("a non-succeeded extraction cannot expose draft content")
        return self


class PlanExtractionReview(_AIValue):
    """Server-owned activation review facts derived from one successful extraction."""

    extraction_id: UUID
    provider_id: UUID
    model: ModelName
    prompt_version: PromptVersion
    source_text_sha256: SourceTextSha256
    draft_sha256: SourceTextSha256
    review_issues: tuple[DraftReviewIssue, ...] = Field(max_length=512)
    mapping: PlanMapping | None = None
    content_hash: SourceTextSha256 | None = None
    review_evidence_hash: SourceTextSha256 | None = None
    required_issues: tuple[RequiredReviewIssue, ...] = Field(default=(), max_length=512)


def build_plan_extraction_review(result: PlanExtractionResult) -> PlanExtractionReview:
    """Derive the immutable issue set a client may resolve but cannot replace."""

    if not isinstance(result, PlanExtractionResult):
        raise TypeError("result must be a PlanExtractionResult")
    if result.status is not PlanExtractionStatus.SUCCEEDED or result.draft is None:
        raise ValueError("only a successful extraction can create a review snapshot")
    if isinstance(result.draft, ExplicitPlanDraft):
        if result.mapping is None:
            raise ValueError("a v4 explicit extraction requires its mapping")
        from trade_plan_monitor.ai.review import (
            build_server_review_snapshot,
            explicit_draft_sha256,
        )

        snapshot = build_server_review_snapshot(
            source_text_sha256=result.source_text_sha256,
            draft=result.draft,
            mapping=result.mapping,
        )
        return PlanExtractionReview(
            extraction_id=result.request_id,
            provider_id=result.provider_id,
            model=result.model,
            prompt_version=result.prompt_version,
            source_text_sha256=result.source_text_sha256,
            draft_sha256=explicit_draft_sha256(result.draft),
            review_issues=(),
            mapping=snapshot.mapping,
            content_hash=snapshot.content_hash,
            review_evidence_hash=snapshot.review_evidence_hash,
            required_issues=snapshot.required_issues,
        )
    review_issues = (
        *(
            DraftReviewIssue(
                kind=ReviewIssueKind.ASSUMPTION,
                path=issue.path,
                material=issue.material,
            )
            for issue in result.assumptions
        ),
        *(
            DraftReviewIssue(
                kind=ReviewIssueKind.WARNING,
                path=issue.path,
                material=issue.material,
            )
            for issue in result.warnings
        ),
        *(
            DraftReviewIssue(
                kind=ReviewIssueKind.UNMAPPED_TEXT,
                path=issue.path,
                material=True,
            )
            for issue in result.unmapped_text
        ),
        *(
            DraftReviewIssue(
                kind=ReviewIssueKind.MISSING_EVIDENCE,
                path=issue.path,
                material=True,
            )
            for issue in result.validation_issues
            if issue.code == "AI_EVIDENCE_REVIEW_REQUIRED" and issue.activation_blocking
        ),
    )
    return PlanExtractionReview(
        extraction_id=result.request_id,
        provider_id=result.provider_id,
        model=result.model,
        prompt_version=result.prompt_version,
        source_text_sha256=result.source_text_sha256,
        draft_sha256=plan_sha256(result.draft),
        review_issues=review_issues,
    )


def _is_explicit_loopback(host: str) -> bool:
    normalized = host.casefold().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validation_error_without_inputs(error: ValidationError) -> ValidationError:
    line_errors = error.errors(include_url=False)
    for line_error in line_errors:
        line_error.pop("input", None)
    return ValidationError.from_exception_data(
        error.title,
        line_errors,
        hide_input=True,
    )


__all__ = [
    "AIProviderConfig",
    "AIProviderProfile",
    "AIProviderType",
    "AIUsageSnapshot",
    "ExtractionIssue",
    "ExplicitPlanDraft",
    "FieldBinding",
    "FieldEvidence",
    "PlanExtractionOutputV4",
    "PlanExtractionOutput",
    "PlanExtractionReview",
    "PlanExtractionResult",
    "PlanExtractionStatus",
    "PlanMapping",
    "RequiredReviewIssue",
    "ReviewResolution",
    "SecretReference",
    "ServerReviewSnapshot",
    "SourceClause",
    "TradePlanDraft",
    "UnmappedText",
    "UserSupplement",
    "build_plan_extraction_review",
]
