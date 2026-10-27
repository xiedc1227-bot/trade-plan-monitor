"""Bounded, self-verifying values for the independent current assurance sidecar."""

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from trade_plan_monitor.ai.source_coverage_models import (
    MAX_PROOF_BYTES,
    CoverageAssessment,
    CoverageIssue,
    Hash,
    NormalizationTrace,
)
from trade_plan_monitor.ai.source_derivation import SourceDerivationEvidence
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier
from trade_plan_monitor.market_data.models import ShanghaiDatetime


class _Signed(DailyValue):
    evidence_hash: Hash

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        })

    @model_validator(mode="after")
    def signed(self):
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode()) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("source coverage sidecar hash mismatch")
        return self


class CoverageInstallation(_Signed):
    version: Literal["source-coverage-installation-v1"] = "source-coverage-installation-v1"
    installation_id: Identifier
    installed_at: ShanghaiDatetime
    member_count: int = Field(strict=True, ge=0, le=9_007_199_254_740_991)
    membership_hash: Hash


class CoverageCutover(_Signed):
    version: Literal["source-coverage-cutover-v1"] = "source-coverage-cutover-v1"
    installation_id: Identifier
    plan_version_id: Identifier
    plan_hash: Hash
    source_hash: Hash
    legacy_identity: dict[str, JsonValue] = Field(max_length=32)


class CoverageInputs(_Signed):
    version: Literal["source-coverage-inputs-v1"] = "source-coverage-inputs-v1"
    source_hash: Hash
    source_binding_hash: Hash | None = None
    initial_coverage: CoverageAssessment | None = None
    normalization: NormalizationTrace | None = None
    derivation: SourceDerivationEvidence | None = None
    derivation_issues: tuple[CoverageIssue, ...] = Field(default=(), max_length=16)
    authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def source_correspondence(self):
        if any(value is not None and value.source_hash != self.source_hash for value in (
            self.initial_coverage, self.normalization, self.derivation,
        )):
            raise ValueError("private coverage input belongs to another source")
        return self


def coverage_request_hash(version_id, revision, assessment, inputs):
    return daily_hash("source-coverage-command-v1", dict(
        plan_version_id=version_id, expected_revision=revision,
        assessment_hash=assessment.evidence_hash,
        inputs_hash=None if inputs is None else inputs.evidence_hash,
    ))


class StoredCoverage(_Signed):
    version: Literal["source-coverage-record-v1"] = "source-coverage-record-v1"
    plan_version_id: Identifier
    revision: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    before_hash: Hash | None
    command_id: Identifier
    request_hash: Hash
    assessment: CoverageAssessment
    inputs: CoverageInputs | None = None
    created_at: ShanghaiDatetime
    authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self):
        if (self.before_hash is None) != (self.revision == 1):
            raise ValueError("coverage history transition is inconsistent")
        if self.request_hash != coverage_request_hash(
            self.plan_version_id, self.revision - 1, self.assessment, self.inputs,
        ):
            raise ValueError("coverage request identity differs")
        if self.inputs is not None and self.inputs.source_hash != self.assessment.source_hash:
            raise ValueError("coverage input source differs")
        if self.assessment.normalization_hash is not None and (
            self.inputs is None or self.inputs.normalization is None
            or self.inputs.normalization.evidence_hash != self.assessment.normalization_hash
        ):
            raise ValueError("coverage normalization input is absent or differs")
        return self


class CoverageReviewReceipt(_Signed):
    version: Literal["source-coverage-review-v1"] = "source-coverage-review-v1"
    plan_version_id: Identifier
    review_id: Identifier
    review_revision: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    coverage_revision: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    coverage_evidence_hash: Hash
    coverage_bundle_hash: Hash
    coverage_rules_version: Literal["source-coverage-rules-v1"] = "source-coverage-rules-v1"
    source_hash: Hash
    content_hash: Hash
    mapping_hash: Hash
    original_review_evidence_hash: Hash
    confirmed_at: ShanghaiDatetime
    authority_granted: Literal[False] = False
