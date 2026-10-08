"""Bounded preparation transport; embedded research contracts retain their field names."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from trade_plan_monitor.ai.daily_review import DailyMapping
from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult, OpeningAccountFacts
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.preparation_models import (
    PreparationAttempt,
    PreparationRecord,
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import (
    FrozenPreparedPlan,
    PreparationReviewCommand,
    frozen_preparation,
)
from trade_plan_monitor.backtest.research_input import _confirmed
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.web.schemas import ApiValue

Revision = Annotated[int, Field(strict=True, ge=1, le=9_007_199_254_740_991)]


def _embedded[T: BaseModel](model: type[T], value: object) -> T:
    if isinstance(value, model):
        return value
    if isinstance(value, BaseModel):
        return model.model_validate_json(value.model_dump_json())
    return model.model_validate_json(json.dumps(value, ensure_ascii=False, allow_nan=False))


class PreparationCreateCommand(ApiValue):
    input: SinglePlanPreparationInput

    @field_validator("input", mode="before")
    @classmethod
    def parse_input(cls, value):
        return _embedded(SinglePlanPreparationInput, value)


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
        if len(self.model_dump_json().encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("preparation projection exceeds 2 MiB")
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
                candidate = PreparationFrozenCandidate(
                    kind="FROZEN", frozen=frozen_preparation(record), **values
                )
            else:
                extracted = LoopPlanExtractionResult.model_validate_json(stored.payload_json)
                candidate = PreparationExtractionCandidate(
                    kind="EXTRACTION",
                    draft=extracted.draft,
                    mapping=extracted.daily_mapping,
                    opening_account=extracted.opening_account,
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
