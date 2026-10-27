"""Private multi-source references; original single-source obligations retain identity."""

from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding as CandidateBinding
from trade_plan_monitor.ai.source_change_models import SourceChangeAssessment
from trade_plan_monitor.ai.source_coverage_models import (
    COMPLETE_STATES,
    MAX_PROOF_BYTES,
    CoverageAssessment,
    CoverageIssue,
    CoverageState,
    Hash,
    Path,
)
from trade_plan_monitor.ai.source_human_change_models import HumanSourceChangeAssessment
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier


class AssuranceSourceRef(DailyValue):
    source_id: Identifier
    source_hash: Hash
    source_binding_hash: Hash
    proof_hash: Hash
    proof_kind: Literal["INITIAL", "CHANGE"]


class SourceOwner(DailyValue):
    path: Path
    original_path: Path
    source_id: Identifier
    source_hash: Hash
    source_binding_hash: Hash
    proof_hash: Hash
    origin: Literal["CURRENT", "BASE", "PRODUCT_CONTRACT", "HUMAN"]
    obligation_ids: tuple[Hash, ...] = Field(default=(), max_length=64)
    human_receipt_hash: Hash | None = None


class SourceObligationRef(DailyValue):
    source_id: Identifier
    source_hash: Hash
    source_binding_hash: Hash
    proof_hash: Hash
    obligation_id: Hash
    scope: Literal["PLAN", "BUY", "SELL", "RISK", "ALERT", "UNKNOWN"]
    state: CoverageState


class PrefixAssuranceRef(DailyValue):
    binding: CandidateBinding
    assurance_hash: Hash


def source_prefix_hash(prefix, binding):
    return daily_hash("source-assurance-prefix-v1", dict(
        prefix=[row.model_dump(mode="json") for row in prefix],
        current=binding.model_dump(mode="json"),
    ))


class SourceCandidateAssurance(DailyValue):
    version: Literal["source-candidate-assurance-v1"] = "source-candidate-assurance-v1"
    binding: CandidateBinding
    content_hash: Hash
    source_assessment: CoverageAssessment | HumanSourceChangeAssessment | SourceChangeAssessment
    source_refs: tuple[AssuranceSourceRef, ...] = Field(min_length=1, max_length=512)
    owners: tuple[SourceOwner, ...] = Field(max_length=2000)
    global_obligations: tuple[SourceObligationRef, ...] = Field(default=(), max_length=4096)
    prefix: tuple[PrefixAssuranceRef, ...] = Field(default=(), max_length=512)
    prefix_hash: Hash
    parent_hash: Hash | None = None
    issues: tuple[CoverageIssue, ...] = Field(default=(), max_length=8192)
    status: Literal["COMPLETE", "BLOCKED"]
    authority_granted: Literal[False] = False
    evidence_hash: Hash

    @property
    def coverage_complete(self):
        return self.status == "COMPLETE"

    @property
    def current_automatic_fidelity_verified(self):
        return self.coverage_complete and self.source_assessment.automatic_fidelity_verified

    def _complete(self):
        return (bool(self.owners) and self.source_assessment.coverage_complete
                and not self.issues) and (
            all(row.scope != "UNKNOWN" and row.state in COMPLETE_STATES
                for row in self.global_obligations)
        ) and all(row.origin != "HUMAN" or row.human_receipt_hash for row in self.owners)

    @model_validator(mode="after")
    def verify(self):
        if self.prefix_hash != source_prefix_hash(self.prefix, self.binding):
            raise ValueError("source assurance prefix differs")
        expected_parent = (None if self.binding.independent or not self.prefix
                           else self.prefix[-1].assurance_hash)
        if self.parent_hash != expected_parent:
            raise ValueError("source assurance policy parent differs")
        if len({row.path for row in self.owners}) != len(self.owners):
            raise ValueError("duplicate source owner path")
        if len({row.source_id for row in self.source_refs}) != len(self.source_refs):
            raise ValueError("duplicate source proof identity")
        current = self.source_refs[-1]
        if (current.source_id, current.source_binding_hash, current.source_hash,
            current.proof_hash, self.content_hash) != (
            self.binding.source_id, self.binding.source_binding_hash,
            self.source_assessment.source_hash,
            self.source_assessment.evidence_hash, self.source_assessment.content_hash,
        ):
            raise ValueError("current source assurance differs from its exact source proof")
        refs = {row.source_id: row for row in self.source_refs}
        for row in (*self.owners, *self.global_obligations):
            ref = refs.get(row.source_id)
            if ref is None or (row.source_hash, row.source_binding_hash, row.proof_hash) != (
                ref.source_hash, ref.source_binding_hash, ref.proof_hash,
            ):
                raise ValueError("source ownership refers to another source proof")
        current_ids = {row.obligation_id for row in self.source_assessment.obligations}
        if any(row.source_id == current.source_id and not set(row.obligation_ids) <= current_ids
               for row in self.owners) or any(
            row.source_id == current.source_id and row.obligation_id not in current_ids
            for row in self.global_obligations
        ):
            raise ValueError("current source obligation reference is absent")
        if self.coverage_complete != bool(self._complete()):
            raise ValueError("source candidate assurance status differs")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode()) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("source candidate assurance hash differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, status="BLOCKED", evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        payload["status"] = "COMPLETE" if unsigned._complete() else "BLOCKED"
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        })
