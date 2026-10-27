"""Current-source change proof; inherited full-plan authority is a separate proof."""

from collections import Counter
from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_coverage_models import (
    COMPLETE_STATES,
    MAX_PROOF_BYTES,
    CoverageIssue,
    Hash,
    Path,
    SourceObligation,
)
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue


class SourceOperationProof(DailyValue):
    target: Path
    rule_id: str | None = Field(max_length=128)
    action: Literal["ADD", "MODIFY", "REVOKE", "RETAIN"]
    before_hash: Hash
    after_hash: Hash
    changed_paths: tuple[Path, ...] = Field(max_length=2000)
    obligation_ids: tuple[Hash, ...] = Field(max_length=4096)
    origin: Literal["SOURCE", "PRODUCT_RETENTION"]

    @model_validator(mode="after")
    def retention(self):
        if (self.origin == "PRODUCT_RETENTION" and self.action != "RETAIN") or (
            self.action == "RETAIN" and (self.before_hash != self.after_hash or self.changed_paths)
        ):
            raise ValueError("product retention cannot authorize an actual policy change")
        return self

    @property
    def operation_id(self):
        return daily_hash("source-operation-proof-v1", self.model_dump(mode="json"))


class SourceChangeAssessment(DailyValue):
    version: Literal["source-change-coverage-v1"] = "source-change-coverage-v1"
    rules_version: Literal["source-coverage-rules-v1"] = "source-coverage-rules-v1"
    origin: Literal["AI_DERIVED"] = "AI_DERIVED"
    binding: CandidateBinding
    source_hash: Hash
    source_binding_hash: Hash
    content_hash: Hash
    mapping_hash: Hash
    review_evidence_hash: Hash
    base_hash: Hash
    parent_assurance_hash: Hash
    inputs_hash: Hash | None
    derivation_hash: Hash | None
    raw_delta_verified: bool = Field(strict=True)
    provider_full_draft_supplied: bool = Field(strict=True)
    full_draft_fidelity_verified: bool = Field(strict=True)
    parent_verified: bool = Field(strict=True)
    operations: tuple[SourceOperationProof, ...] = Field(max_length=64)
    changed_paths: tuple[Path, ...] = Field(max_length=2000)
    obligations: tuple[SourceObligation, ...] = Field(max_length=4096)
    issues: tuple[CoverageIssue, ...] = Field(max_length=8192)
    status: Literal["COMPLETE", "BLOCKED"]
    authority_granted: Literal[False] = False
    evidence_hash: Hash

    @property
    def coverage_complete(self):
        return self.status == "COMPLETE"

    @property
    def automatic_fidelity_verified(self):
        return self.coverage_complete and self.full_draft_fidelity_verified

    @property
    def operation_ids(self):
        return tuple(row.operation_id for row in self.operations)

    def _complete(self):
        return (bool(self.obligations) and not self.issues and self.parent_verified
                and (self.raw_delta_verified or self.full_draft_fidelity_verified)
                and all(row.state in COMPLETE_STATES and row.scope != "UNKNOWN"
                        for row in self.obligations))

    @model_validator(mode="after")
    def verify(self):
        ids = {row.obligation_id for row in self.obligations}
        if len(ids) != len(self.obligations) or any(
            row.source_hash != self.source_hash for row in self.obligations
        ) or any(count > 64 for count in Counter(
            row.clause_id for row in self.obligations).values()
        ):
            raise ValueError("source change obligations differ or exceed their bound")
        if any(not set(row.obligation_ids) <= ids for row in self.operations):
            raise ValueError("operation refers to an absent current-source obligation")
        if not self.issues and any(row.action != "RETAIN" and not row.obligation_ids
                                   for row in self.operations):
            raise ValueError("a complete source operation requires its actual obligations")
        if len(self.operation_ids) != len(set(self.operation_ids)) or len(
            self.changed_paths) != len(set(self.changed_paths)):
            raise ValueError("duplicate source change identity")
        if self.full_draft_fidelity_verified and not self.provider_full_draft_supplied:
            raise ValueError("derived policy cannot claim provider full-draft fidelity")
        if (self.raw_delta_verified or self.provider_full_draft_supplied) and (
            self.derivation_hash is None or self.inputs_hash is None
        ):
            raise ValueError("observed raw evidence requires its exact private input")
        if self.binding.independent or (self.binding.source_binding_hash,
            self.binding.review_evidence_hash, self.binding.inputs_hash) != (
            self.source_binding_hash, self.review_evidence_hash, self.inputs_hash,
        ):
            raise ValueError("source change candidate binding differs")
        if set(self.changed_paths) != {
            path for row in self.operations for path in row.changed_paths
        }:
            raise ValueError("complete changed paths differ from operation proofs")
        if self.coverage_complete != bool(self._complete()):
            raise ValueError("source change status differs")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode()) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("source change hash differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, status="BLOCKED", evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        payload["status"] = "COMPLETE" if unsigned._complete() else "BLOCKED"
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        })
