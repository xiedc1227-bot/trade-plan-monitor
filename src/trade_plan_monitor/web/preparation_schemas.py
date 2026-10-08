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


class PreparationReviewInput(ApiValue):
    review: PreparationReviewCommand

    @field_validator("review", mode="before")
    @classmethod
    def parse_review(cls, value):
        return _embedded(PreparationReviewCommand, value)


class PreparationRecoveryCommand(PreparationRevisionCommand):
    generation: StableIdentifier
    confirmed_ended: Annotated[Literal[True], BeforeValidator(_confirmed)]


class PreparationCandidateView(ApiValue):
    kind: Literal["EXTRACTION", "FROZEN", "UNAVAILABLE"]
    candidate_hash: Sha256Hex
    evidence_hash: Sha256Hex
    validation: Literal["VALID", "INVALID", "UNRESOLVED"]
    issues: tuple[Annotated[str, Field(max_length=512)], ...] = Field(max_length=128)
    draft: UnifiedPlanDraft | None = None
    mapping: DailyMapping | None = None
    opening_account: OpeningAccountFacts | None = None
    frozen: FrozenPreparedPlan | None = None


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
    attempts: tuple[PreparationAttempt, ...] = Field(max_length=3)
    work_phase: Literal["READY", "CALLING", "UNKNOWN", "ENDED"] | None
    generation: StableIdentifier | None
    candidate: PreparationCandidateView | None

    @model_validator(mode="after")
    def bounded(self):
        if len(self.model_dump_json().encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("preparation projection exceeds 2 MiB")
        return self


class PreparationFrozenView(ApiValue):
    preparation_id: StableIdentifier
    manifest_hash: Sha256Hex
    frozen: FrozenPreparedPlan


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
                candidate = PreparationCandidateView(
                    kind="FROZEN", frozen=frozen_preparation(record), **values
                )
            else:
                extracted = LoopPlanExtractionResult.model_validate_json(stored.payload_json)
                candidate = PreparationCandidateView(
                    kind="EXTRACTION",
                    draft=extracted.draft,
                    mapping=extracted.daily_mapping,
                    opening_account=extracted.opening_account,
                    **values,
                )
        except ValueError:
            candidate = PreparationCandidateView(
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
