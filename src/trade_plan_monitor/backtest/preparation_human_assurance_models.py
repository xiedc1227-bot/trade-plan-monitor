"""Immutable human intent/checkpoints; self-hashes do not grant review authority."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, TypeAdapter, field_validator, model_validator

from trade_plan_monitor.ai.daily_review import DailyMapping
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef, source_prefix_hash
from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES, Hash
from trade_plan_monitor.ai.update_review import PlanCandidateReview
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationCandidate,
    PreparationCandidate,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    CollectionPreparationReviewCommand,
    PreparationReviewCommand,
)
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.market_linkage_validation import (
    LegacyCurrentPlanDraft as CurrentPlanDraft,
)
from trade_plan_monitor.market_data.models import ShanghaiDatetime

Revision = Annotated[int, Field(strict=True, ge=1, le=9_007_199_254_740_991)]
ItemIndex = Annotated[int, Field(strict=True, ge=0, le=511)]
_IDENTIFIER = TypeAdapter(Identifier)
_REVISION = TypeAdapter(Revision)
_ITEM_INDEX = TypeAdapter(ItemIndex)
_REVIEW_COMMAND = TypeAdapter(PreparationReviewCommand | CollectionPreparationReviewCommand)


def human_operation_key(preparation_id, item_index, after_candidate_revision):
    """The stable operation identity excludes time, intent and private content."""
    return daily_hash("preparation-human-operation-key-v1", dict(
        preparation_id=_IDENTIFIER.validate_python(preparation_id),
        item_index=_ITEM_INDEX.validate_python(item_index),
        after_candidate_revision=_REVISION.validate_python(after_candidate_revision)))


def human_operation_slot(item_index, after_candidate_revision):
    """A HUMAN_OPERATION-local SQL slot, explicitly separate from a provider attempt."""
    return (f"human-{_ITEM_INDEX.validate_python(item_index)}-"
            f"{_REVISION.validate_python(after_candidate_revision)}")


class PreparationHumanOperation(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    version: Literal["preparation-human-operation-v1"] = "preparation-human-operation-v1"
    kind: Literal["HUMAN_OPERATION"] = "HUMAN_OPERATION"
    operation: Literal["REVIEW_AND_FREEZE", "CORRECT_ITEM"]
    preparation_id: Identifier
    item_index: ItemIndex
    source: PreparationSource
    source_revision: Revision
    before_revision: Revision
    after_revision: Revision
    before_candidate_revision: Revision
    before_candidate_hash: Hash
    before_evidence_hash: Hash
    after_candidate_revision: Revision
    after_candidate_hash: Hash
    after_evidence_hash: Hash
    attempt_id: Identifier | None
    original_input_state: Literal["PRESENT", "MISSING"]
    original_input_key: Hash | None
    original_input_hash: Hash | None
    original_candidate: PreparationCandidate | CollectionPreparationCandidate
    original_candidate_revision: Revision
    command_json: str = Field(min_length=2, max_length=1024 * 1024)
    resolved_draft: CurrentPlanDraft
    resolved_mapping: DailyMapping
    resolved_update: PlanUpdateExtractionOutput | None = None
    resolved_review: PlanCandidateReview
    assessment_binding: CandidateBinding
    prefix: tuple[PrefixAssuranceRef, ...] = Field(default=(), max_length=512)
    prefix_hash: Hash
    parent_hash: Hash | None = None
    independent: bool = Field(strict=True)
    final_frozen_hash: Hash | None = None
    previous_human_ref: Hash | None = None
    command_id: Identifier | None = Field(default=None, strict=True,
        exclude_if=lambda value: value is None)
    command_request_hash: Hash | None = Field(default=None, strict=True,
        exclude_if=lambda value: value is None)
    after_record_hash: Hash | None = Field(default=None, strict=True,
        exclude_if=lambda value: value is None)
    created_at: ShanghaiDatetime
    authority_granted: Literal[False] = False
    evidence_key: Hash
    evidence_hash: Hash

    @property
    def source_hash(self):
        return self.source.source_hash

    @property
    def source_binding_hash(self):
        return self.source.binding_hash

    @property
    def slot(self):
        return human_operation_slot(self.item_index, self.after_candidate_revision)

    def intent(self):
        return self.model_dump(mode="json", exclude={"created_at", "evidence_hash"})

    @field_validator("command_json")
    @classmethod
    def bounded_command(cls, value):
        if len(value.encode("utf-8")) > 1024 * 1024:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        return value

    @model_validator(mode="after")
    def verify(self):
        registration = (self.command_id, self.command_request_hash, self.after_record_hash)
        if any(value is not None for value in registration) and any(
            value is None for value in registration
        ):
            raise ValueError("human operation registration binding is incomplete")
        if (self.after_revision != self.before_revision + 1
                or self.after_candidate_revision != self.before_candidate_revision + 1):
            raise ValueError("human operation revision transition differs")
        present = self.original_input_key is not None and self.original_input_hash is not None
        if (self.original_input_state == "PRESENT" and (not present or self.attempt_id is None)
                or self.original_input_state == "MISSING" and (
                    self.original_input_key is not None or self.original_input_hash is not None)):
            raise ValueError("human operation original input presence differs")
        if (self.original_candidate.source_revision, self.original_candidate.source_hash) != (
            self.source_revision, self.source.binding_hash,
        ):
            raise ValueError("human operation original checkpoint belongs to another source")
        command = (CollectionItemCorrectionCommand.model_validate_json(self.command_json)
                   if self.operation == "CORRECT_ITEM"
                   else _REVIEW_COMMAND.validate_json(self.command_json))
        if canonical_json(command) != self.command_json:
            raise ValueError("human operation command must use its canonical typed codec")
        if (self.assessment_binding.preparation_id, self.assessment_binding.item_index,
            self.assessment_binding.source_id, self.assessment_binding.source_revision,
            self.assessment_binding.source_binding_hash,
            self.assessment_binding.review_evidence_hash, self.assessment_binding.independent) != (
            self.preparation_id, self.item_index, self.source.source_id, self.source_revision,
            self.source.binding_hash, self.resolved_review.evidence_hash, self.independent,
        ) or (self.resolved_review.source_id, self.resolved_review.source_hash,
              self.resolved_review.available_at) != (
            self.source.source_id, self.source.binding_hash, self.source.execution_available_at,
        ):
            raise ValueError("human operation resolved source/review binding differs")
        proposed = self.resolved_update.draft if self.resolved_update is not None else (
            self.resolved_review.draft)
        if (self.resolved_draft != proposed
                or self.resolved_mapping.candidate_content_hash
                != daily_draft_content_sha256(self.resolved_draft)):
            raise ValueError("human operation proposed draft/mapping namespace differs")
        if self.prefix_hash != source_prefix_hash(self.prefix, self.assessment_binding):
            raise ValueError("human operation prefix differs")
        expected_parent = (None if self.independent or not self.prefix
                           else self.prefix[-1].assurance_hash)
        if self.parent_hash != expected_parent:
            raise ValueError("human operation parent differs")
        if self.evidence_key != human_operation_key(
            self.preparation_id, self.item_index, self.after_candidate_revision,
        ):
            raise ValueError("human operation identity differs")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("human operation hash differs")
        return self

    @classmethod
    def build(cls, **values):
        for name in ("command_id", "command_request_hash", "after_record_hash"):
            if values.get(name) is not None and type(values[name]) is not str:
                raise ValueError("human operation registration fields require strict strings")
        key = human_operation_key(values["preparation_id"], values["item_index"],
                                  values["after_candidate_revision"])
        unsigned = cls.model_construct(**values, evidence_key=key, evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return cls.model_validate_json(canonical(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        }))
