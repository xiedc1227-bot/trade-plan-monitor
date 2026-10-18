"""Bounded preparation transport; embedded research contracts retain their field names."""

import json
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from trade_plan_monitor.ai.daily_review import DailyMapping
from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult, OpeningAccountFacts
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateExtractionOutput,
    PlanUpdateExtractionResult,
)
from trade_plan_monitor.ai.update_review import MaterializedUpdateCandidate, PlanCandidateReview
from trade_plan_monitor.backtest.loop_input import LoopAccountInput
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import LoopAccountContext, LoopTimestamp
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationAttempt,
    CollectionPreparationRecord,
    PlanCollectionPreparationInput,
    PreparationAttempt,
    PreparationItemReview,
    PreparationRecord,
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    CollectionPreparationReviewCommand,
    FrozenPreparedPlan,
    PreparationReviewCommand,
    frozen_preparation,
)
from trade_plan_monitor.backtest.research_input import _confirmed
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.web.preparation_confirmations import (
    PreparationConfirmationSummary,
    confirmation_summary,
)
from trade_plan_monitor.web.schemas import ApiValue

Revision = Annotated[int, Field(strict=True, ge=1, le=9_007_199_254_740_991)]


def _embedded[T: BaseModel](model: type[T], value: object) -> T:
    if isinstance(value, model):
        return value
    if isinstance(value, BaseModel):
        return model.model_validate_json(value.model_dump_json())
    return model.model_validate_json(json.dumps(value, ensure_ascii=False, allow_nan=False))


class CollectionPreparationCreateInput(PlanCollectionPreparationInput):
    """HTTP callers must opt into collections; the stored codec keeps its default."""

    schema_version: Literal["backtest-preparation-v2"]


class PreparationCreateCommand(ApiValue):
    input: SinglePlanPreparationInput | CollectionPreparationCreateInput

    @field_validator("input", mode="before")
    @classmethod
    def parse_input(cls, value):
        schema = (
            value.get("schema_version")
            if isinstance(value, dict)
            else getattr(
                value,
                "schema_version",
                None,
            )
        )
        model = (
            CollectionPreparationCreateInput
            if schema == "backtest-preparation-v2"
            else (SinglePlanPreparationInput)
        )
        return _embedded(model, value)


class PreparationRevisionCommand(ApiValue):
    expected_revision: Revision


class PreparationSourceCommand(PreparationRevisionCommand):
    source: PreparationSource

    @field_validator("source", mode="before")
    @classmethod
    def parse_source(cls, value):
        return _embedded(PreparationSource, value)


class PreparationReviewDeclaration(PreparationReviewCommand):
    expected_revision: Revision
    expected_source_revision: Revision
    expected_candidate_revision: Revision


class PreparationReviewInput(ApiValue):
    review: PreparationReviewDeclaration

    @field_validator("review", mode="before")
    @classmethod
    def parse_review(cls, value):
        return _embedded(PreparationReviewDeclaration, value)


class PreparationRecoveryCommand(PreparationRevisionCommand):
    generation: StableIdentifier
    confirmed_ended: Annotated[Literal[True], BeforeValidator(_confirmed)]


class PreparationAttemptView(PreparationAttempt):
    source_revision: Revision


class PreparationFrozenManifest(FrozenPreparedPlan):
    source_revision: Revision
    extraction_candidate_revision: Revision


class _PreparationCandidateBase(ApiValue):
    confirmation_summary: PreparationConfirmationSummary | None = None
    candidate_hash: Sha256Hex
    evidence_hash: Sha256Hex
    validation: Literal["VALID", "INVALID", "UNRESOLVED"]
    issues: tuple[Annotated[str, Field(max_length=512)], ...] = Field(max_length=128)
    draft: UnifiedPlanDraft | None = None
    mapping: DailyMapping | None = None
    opening_account: OpeningAccountFacts | None = None
    frozen: PreparationFrozenManifest | None = None

    @field_validator("frozen", mode="before")
    @classmethod
    def parse_frozen(cls, value):
        return None if value is None else _embedded(PreparationFrozenManifest, value)


class PreparationExtractionCandidate(_PreparationCandidateBase):
    kind: Literal["EXTRACTION"]
    draft: UnifiedPlanDraft
    mapping: DailyMapping
    opening_account: OpeningAccountFacts
    frozen: None = None


class PreparationFrozenCandidate(_PreparationCandidateBase):
    kind: Literal["FROZEN"]
    draft: None = None
    mapping: None = None
    opening_account: None = None
    frozen: PreparationFrozenManifest


class PreparationUnavailableCandidate(_PreparationCandidateBase):
    kind: Literal["UNAVAILABLE"]
    validation: Literal["INVALID"]
    draft: None = None
    mapping: None = None
    opening_account: None = None
    frozen: None = None


PreparationCandidateView = Annotated[
    PreparationExtractionCandidate | PreparationFrozenCandidate | PreparationUnavailableCandidate,
    Field(discriminator="kind"),
]


class PreparationView(ApiValue):
    preparation_id: StableIdentifier
    revision: Revision
    source_revision: Revision
    candidate_revision: Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]
    review_revision: Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]
    status: Literal[
        "DRAFT", "EXTRACTING", "CANCEL_REQUESTED", "CANDIDATE", "REVIEWED", "FAILED", "CANCELLED"
    ]
    source: PreparationSource
    source_edit_pending: bool
    attempts: tuple[PreparationAttemptView, ...] = Field(max_length=3)
    work_phase: Literal["READY", "CALLING", "UNKNOWN", "ENDED"] | None
    generation: StableIdentifier | None
    candidate: PreparationCandidateView | None

    @field_validator("attempts", mode="before")
    @classmethod
    def parse_attempts(cls, value):
        return tuple(_embedded(PreparationAttemptView, attempt) for attempt in value)

    @model_validator(mode="after")
    def bounded(self):
        encoded = self.model_dump_json()
        if len(encoded.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("preparation projection exceeds 2 MiB")
        pending = [(json.loads(encoded), 0)]
        nodes = 1
        while pending:
            value, depth = pending.pop()
            children = value.values() if isinstance(value, dict) else value
            if not isinstance(value, (dict, list)):
                continue
            for child in children:
                nodes += 1
                if nodes > 50_000 or depth + 1 > 32:
                    raise ValueError("preparation projection exceeds JSON node/depth budget")
                pending.append((child, depth + 1))
        return self


class PreparationFrozenView(ApiValue):
    preparation_id: StableIdentifier
    manifest_hash: Sha256Hex
    frozen: PreparationFrozenManifest

    @field_validator("frozen", mode="before")
    @classmethod
    def parse_frozen(cls, value):
        return _embedded(PreparationFrozenManifest, value)


def project_preparation(record: PreparationRecord) -> PreparationView:
    if isinstance(record, CollectionPreparationRecord):
        return project_collection(record)
    candidate = None
    if record.candidate is not None:
        stored = record.candidate
        values = dict(
            candidate_hash=stored.candidate_hash,
            evidence_hash=stored.evidence_hash,
            validation=stored.validation,
            issues=stored.issues,
        )
        try:
            if record.status == "REVIEWED":
                manifest = frozen_preparation(record)
                candidate = PreparationFrozenCandidate(
                    kind="FROZEN",
                    frozen=manifest,
                    **{**values, "candidate_hash": manifest.manifest_hash},
                )
            else:
                extracted = LoopPlanExtractionResult.model_validate_json(stored.payload_json)
                candidate = PreparationExtractionCandidate(
                    kind="EXTRACTION",
                    draft=extracted.draft,
                    mapping=extracted.daily_mapping,
                    opening_account=extracted.opening_account,
                    confirmation_summary=confirmation_summary(
                        record.source,
                        extracted.draft,
                        extracted.daily_mapping,
                        extracted.validation_issues,
                        extracted.opening_account,
                    ),
                    **values,
                )
        except ValueError:
            candidate = PreparationUnavailableCandidate(
                kind="UNAVAILABLE",
                **{
                    **values,
                    "validation": "INVALID",
                    "issues": ("CANDIDATE_PAYLOAD_UNAVAILABLE",),
                },
            )
    claim = record.work_claim
    return PreparationView(
        preparation_id=record.preparation_id,
        revision=record.revision,
        source_revision=record.source_revision,
        candidate_revision=record.candidate_revision,
        review_revision=record.review_revision,
        status=record.status,
        source=record.source,
        source_edit_pending=record.source_edit_pending,
        attempts=record.attempts,
        work_phase=claim.phase if claim else None,
        generation=claim.generation if claim else None,
        candidate=candidate,
    )


class CollectionRevisionCommand(PreparationRevisionCommand):
    schema_version: Literal["backtest-preparation-v2"]


class CollectionSourceCommand(CollectionRevisionCommand):
    source: PreparationSource | None = None
    source_order: tuple[StableIdentifier, ...] | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )

    @field_validator("source", mode="before")
    @classmethod
    def parse_source(cls, value):
        return None if value is None else _embedded(PreparationSource, value)

    @field_validator("source_order", mode="before")
    @classmethod
    def parse_order(cls, value):
        if value is not None and not isinstance(value, (tuple, list)):
            raise ValueError("sourceOrder must be an array")
        return None if value is None else tuple(value)

    @model_validator(mode="after")
    def complete(self):
        if self.source is None and self.source_order is None:
            raise ValueError("source or sourceOrder is required")
        if self.source_order is not None and len(set(self.source_order)) != len(self.source_order):
            raise ValueError("sourceOrder must contain unique existing source IDs")
        return self


class CollectionExtractionCommand(CollectionRevisionCommand):
    source_id: StableIdentifier | None = None
    expected_source_revision: Revision | None = None
    expected_base_hash: Sha256Hex | None = None

    @model_validator(mode="after")
    def complete(self):
        fields = {"source_id", "expected_source_revision", "expected_base_hash"}
        supplied = self.model_fields_set & fields
        if supplied and (
            supplied != fields or self.source_id is None or self.expected_source_revision is None
        ):
            raise ValueError("selected extraction requires all source/base revision fields")
        return self


class CollectionRecoveryCommand(PreparationRecoveryCommand):
    schema_version: Literal["backtest-preparation-v2"]


class CollectionItemReviewDeclaration(PreparationItemReview):
    source_revision: Revision
    candidate_revision: Revision


class CollectionCorrectionDeclaration(CollectionItemCorrectionCommand):
    expected_revision: Revision
    binding: CollectionItemReviewDeclaration


class CollectionChainReviewDeclaration(CollectionPreparationReviewCommand):
    expected_revision: Revision
    items: tuple[CollectionItemReviewDeclaration, ...] = Field(min_length=1, max_length=256)


class CollectionItemCorrectionInput(ApiValue):
    schema_version: Literal["backtest-preparation-v2"]
    kind: Literal["ITEM_CORRECTION"]
    review: CollectionCorrectionDeclaration

    @field_validator("review", mode="before")
    @classmethod
    def parse_review(cls, value):
        return _embedded(CollectionCorrectionDeclaration, value)


class CollectionReviewInput(ApiValue):
    schema_version: Literal["backtest-preparation-v2"]
    kind: Literal["CHAIN_REVIEW"]
    review: CollectionChainReviewDeclaration

    @field_validator("review", mode="before")
    @classmethod
    def parse_review(cls, value):
        return _embedded(CollectionChainReviewDeclaration, value)


class CollectionVersionView(ApiValue):
    source_id: StableIdentifier
    source_revision: Revision
    candidate_revision: Revision
    version_id: StableIdentifier
    plan_hash: Sha256Hex
    evidence_hash: Sha256Hex
    effective_trade_date: date
    available_at: LoopTimestamp
    account_context: LoopAccountContext | None


class CollectionPreparationFrozenView(ApiValue):
    schema_version: Literal["prepared-loop-plan-v2"] = "prepared-loop-plan-v2"
    preparation_id: StableIdentifier
    manifest_hash: Sha256Hex
    revision: Revision
    account: LoopAccountInput
    account_origin: Literal["SOURCE", "HUMAN_REVIEW"]
    reviewed_at: LoopTimestamp
    versions: tuple[CollectionVersionView, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def bounded(self):
        return PreparationView.bounded(self)


class CollectionItemSummary(ApiValue):
    source_id: StableIdentifier
    source_revision: Revision
    candidate_revision: Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]
    base_hash: Sha256Hex | None
    status: Literal[
        "WAITING",
        "DRAFT",
        "EXTRACTING",
        "CANCEL_REQUESTED",
        "CANDIDATE",
        "FAILED",
        "CANCELLED",
    ]
    candidate_hash: Sha256Hex | None
    evidence_hash: Sha256Hex | None
    validation: Literal["VALID", "INVALID", "UNRESOLVED"] | None
    attempt_count: Annotated[int, Field(strict=True, ge=0, le=3)]
    effective_trade_date: date | None


class CollectionPreparationView(ApiValue):
    workflow: Literal["LEGACY", "SINGLE", "COMPOSITION"] = "LEGACY"
    editable_source_id: StableIdentifier | None = None
    base_account: LoopAccountInput | None = None
    schema_version: Literal["backtest-preparation-v2"] = "backtest-preparation-v2"
    preparation_id: StableIdentifier
    revision: Revision
    review_revision: Annotated[int, Field(strict=True, ge=0, le=9_007_199_254_740_991)]
    status: Literal[
        "DRAFT",
        "EXTRACTING",
        "CANCEL_REQUESTED",
        "CANDIDATE",
        "REVIEWED",
        "FAILED",
        "CANCELLED",
    ]
    item_count: Annotated[int, Field(strict=True, ge=1, le=256)]
    items: tuple[CollectionItemSummary, ...] = Field(min_length=1, max_length=256)
    work_phase: Literal["READY", "CALLING", "UNKNOWN", "ENDED"] | None
    generation: StableIdentifier | None
    current_source_id: StableIdentifier | None
    frozen: CollectionPreparationFrozenView | None

    @model_validator(mode="after")
    def bounded(self):
        return PreparationView.bounded(self)


class CollectionCandidateView(ApiValue):
    confirmation_summary: PreparationConfirmationSummary | None = None
    kind: Literal["INITIAL", "UPDATE", "MATERIALIZED", "CORRECTED", "UNAVAILABLE"]
    candidate_hash: Sha256Hex
    evidence_hash: Sha256Hex
    validation: Literal["VALID", "INVALID", "UNRESOLVED"]
    issues: tuple[Annotated[str, Field(max_length=512)], ...] = Field(max_length=128)
    draft: UnifiedPlanDraft | None = None
    mapping: DailyMapping | None = None
    opening_account: OpeningAccountFacts | None = None
    update: PlanUpdateExtractionOutput | None = None
    review: PlanCandidateReview | None = None


class CollectionAttemptView(CollectionPreparationAttempt):
    source_revision: Revision


class CollectionItemView(CollectionItemSummary):
    source: PreparationSource
    attempts: tuple[CollectionAttemptView, ...] = Field(max_length=3)
    candidate: CollectionCandidateView | None

    @field_validator("attempts", mode="before")
    @classmethod
    def parse_attempts(cls, values):
        return tuple(_embedded(CollectionAttemptView, value) for value in values)


class CollectionItemsPage(ApiValue):
    preparation_id: StableIdentifier
    revision: Revision
    offset: Annotated[int, Field(strict=True, ge=0, le=255)]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    total: Annotated[int, Field(strict=True, ge=1, le=256)]
    next_offset: Annotated[int, Field(strict=True, ge=0, le=255)] | None
    items: tuple[CollectionItemView, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def bounded(self):
        return PreparationView.bounded(self)


def project_collection_frozen(frozen):
    return CollectionPreparationFrozenView(
        preparation_id=frozen.preparation_id,
        manifest_hash=frozen.manifest_hash,
        revision=frozen.revision,
        account=frozen.account,
        account_origin=frozen.account_origin,
        reviewed_at=frozen.reviewed_at,
        versions=tuple(
            CollectionVersionView(
                source_id=item.source.source_id,
                source_revision=item.source_revision,
                candidate_revision=item.extraction_candidate_revision,
                version_id=row.version.version_id,
                plan_hash=row.version.plan_hash,
                evidence_hash=row.version.evidence_hash,
                effective_trade_date=row.effective_trade_date,
                available_at=row.version.available_at,
                account_context=row.version.account_context,
            )
            for item, row in zip(frozen.items, frozen.schedule.entries, strict=True)
        ),
    )


def _item_summary(item):
    candidate = item.candidate
    return CollectionItemSummary(
        source_id=item.source.source_id,
        source_revision=item.source_revision,
        candidate_revision=item.candidate_revision,
        base_hash=item.base_hash,
        status=item.status,
        candidate_hash=None if candidate is None else candidate.candidate_hash,
        evidence_hash=None if candidate is None else candidate.evidence_hash,
        validation=None if candidate is None else candidate.validation,
        attempt_count=len(item.attempts),
        effective_trade_date=item.source.effective_trade_date,
    )


def project_collection(record):
    claim = record.work_claim
    return CollectionPreparationView(
        workflow=record.workflow,
        base_account=record.base_account,
        editable_source_id=(
            record.items[-1].source.source_id
            if record.workflow == "SINGLE" and record.status != "REVIEWED"
            else None
        ),
        preparation_id=record.preparation_id,
        revision=record.revision,
        review_revision=record.review_revision,
        status=record.status,
        item_count=len(record.items),
        items=tuple(_item_summary(item) for item in record.items),
        work_phase=None if claim is None else claim.phase,
        generation=None if claim is None else claim.generation,
        current_source_id=None if claim is None else claim.source_id,
        frozen=project_collection_frozen(frozen_preparation(record))
        if record.status == "REVIEWED"
        else None,
    )


def _collection_candidate(item):
    candidate = item.candidate
    if candidate is None:
        return None
    values = dict(
        candidate_hash=candidate.candidate_hash,
        evidence_hash=candidate.evidence_hash,
        validation=candidate.validation,
        issues=candidate.issues,
    )
    try:
        schema = json.loads(candidate.payload_json).get("schema_version")
        if schema == "monitor-loop-extraction-v1":
            value = LoopPlanExtractionResult.model_validate_json(candidate.payload_json)
            return CollectionCandidateView(
                kind="INITIAL",
                draft=value.draft,
                mapping=value.daily_mapping,
                opening_account=value.opening_account,
                confirmation_summary=confirmation_summary(
                    item.source,
                    value.draft,
                    value.daily_mapping,
                    value.validation_issues,
                    value.opening_account,
                ),
                **values,
            )
        if schema == "monitor-loop-update-extraction-v1":
            value = PlanUpdateExtractionResult.model_validate_json(candidate.payload_json)
            return CollectionCandidateView(
                kind="UPDATE",
                update=value.output,
                confirmation_summary=confirmation_summary(
                    item.source, value.output.draft, None, values["issues"]
                ),
                **values,
            )
        if schema == "monitor-loop-materialized-update-v1":
            value = MaterializedUpdateCandidate.model_validate_json(candidate.payload_json)
            return CollectionCandidateView(
                kind="MATERIALIZED",
                update=value.extraction.output,
                review=value.review,
                confirmation_summary=confirmation_summary(
                    item.source, value.review.draft, None, values["issues"]
                ),
                **values,
            )
        value = PlanCandidateReview.model_validate_json(candidate.payload_json)
        return CollectionCandidateView(kind="CORRECTED", review=value, **values)
    except ValueError:
        return CollectionCandidateView(
            kind="UNAVAILABLE",
            **{
                **values,
                "validation": "INVALID",
                "issues": ("CANDIDATE_PAYLOAD_UNAVAILABLE",),
            },
        )


def project_collection_items(record, *, offset, limit):
    """Bound encoded pages without truncating any item's original text or evidence."""
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    items = []
    result = CollectionItemsPage(
        preparation_id=record.preparation_id,
        revision=record.revision,
        offset=offset,
        limit=limit,
        total=len(record.items),
        next_offset=None,
        items=(),
    )
    for index in range(offset, min(len(record.items), offset + limit)):
        item = record.items[index]
        projected = CollectionItemView(
            **_item_summary(item).model_dump(),
            source=item.source,
            attempts=item.attempts,
            candidate=_collection_candidate(item),
        )
        try:
            result = result.model_copy(
                update={
                    "items": (*items, projected),
                    "next_offset": index + 1 if index + 1 < len(record.items) else None,
                }
            )
        except ValueError:
            if not items:
                raise PreparationConflictError("PREPARATION_ITEM_PROJECTION_TOO_LARGE") from None
            break
        items.append(projected)
    return result


PreparationProgressView = PreparationView | CollectionPreparationView
