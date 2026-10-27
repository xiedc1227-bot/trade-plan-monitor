"""Immutable current review evidence, independent of historical review codecs."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from trade_plan_monitor.ai.source_candidate_models import (
    PrefixAssuranceRef,
    SourceCandidateAssurance,
)
from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES, Hash
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier
from trade_plan_monitor.market_data.models import ShanghaiDatetime

PositiveRevision = Annotated[int, Field(strict=True, ge=1, le=9_007_199_254_740_991)]
_REVISION = TypeAdapter(PositiveRevision)
_IDENTIFIER = TypeAdapter(Identifier)


def review_assurance_key(preparation_id, review_revision):
    """Stable indexed identity; times, commands and proof changes do not change this slot."""
    return daily_hash("preparation-review-assurance-key-v1", dict(
        preparation_id=_IDENTIFIER.validate_python(preparation_id),
        review_revision=_REVISION.validate_python(review_revision)))


class PreparationReviewAssurance(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    version: Literal["preparation-review-assurance-v1"] = "preparation-review-assurance-v1"
    kind: Literal["REVIEW"] = "REVIEW"
    preparation_id: Identifier
    command_id: Identifier
    command_request_hash: Hash
    previous_revision: PositiveRevision
    reviewed_revision: PositiveRevision
    review_revision: PositiveRevision
    original_review_hash: Hash
    frozen_manifest_hash: Hash
    proofs: tuple[SourceCandidateAssurance, ...] = Field(min_length=1, max_length=512)
    created_at: ShanghaiDatetime
    authority_granted: Literal[False] = False
    evidence_key: Hash
    evidence_hash: Hash

    def identity(self):
        return review_assurance_key(self.preparation_id, self.review_revision)

    def intent(self):
        return self.model_dump(mode="json", exclude={"created_at", "evidence_hash"})

    @model_validator(mode="after")
    def verify(self):
        if self.evidence_key != self.identity():
            raise ValueError("preparation review assurance identity differs")
        if self.reviewed_revision != self.previous_revision + 1:
            raise ValueError("preparation review assurance revision differs")
        prefix = []
        sources = set()
        for index, proof in enumerate(self.proofs):
            if (not proof.coverage_complete or proof.binding.preparation_id != self.preparation_id
                    or proof.binding.item_index != index or proof.prefix != tuple(prefix)
                    or proof.binding.source_id in sources):
                raise ValueError("preparation review requires its complete exact proof prefix")
            sources.add(proof.binding.source_id)
            prefix.append(PrefixAssuranceRef(binding=proof.binding,
                                            assurance_hash=proof.evidence_hash))
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(self.model_dump(mode="json")).encode()) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("preparation review assurance hash differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, evidence_key="", evidence_hash="")
        unsigned = cls.model_construct(**values, evidence_key=unsigned.identity(), evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        })
