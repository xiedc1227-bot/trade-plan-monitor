"""Bounded, self-verifying values for the independent current assurance sidecar."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from trade_plan_monitor.ai.source_coverage_models import (
    MAX_PROOF_BYTES,
    CoverageAssessment,
    CoverageIssue,
    Hash,
    NormalizationTrace,
)
from trade_plan_monitor.ai.source_derivation import SourceDerivationEvidence
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier, Text
from trade_plan_monitor.domain.unified_plan_models import BuySuspensionDefinition
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


class BuySuspensionReplacementIntent(DailyValue):
    """Human source-bound proposal; it carries no predecessor or activation authority."""

    source_hash: Hash
    candidate_content_hash: Hash
    source_start: int = Field(strict=True, ge=0, le=150_000)
    source_end: int = Field(strict=True, gt=0, le=150_000)
    excerpt: str = Field(min_length=1, max_length=512)
    replacement_reason: Text
    retire_predecessor_guard: bool = Field(strict=True)
    acknowledge_unverified_predecessor: bool = Field(strict=True)
    strategy_effective_from: ShanghaiDatetime
    authority_granted: Literal[False] = False

    @field_validator("strategy_effective_from", mode="before")
    @classmethod
    def explicit_exchange_start(cls, value):
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.utcoffset() != timedelta(hours=8):
            raise ValueError("replacement strategy start must explicitly use +08:00")
        return value

    @model_validator(mode="after")
    def exact_span(self):
        if self.source_end - self.source_start != len(self.excerpt):
            raise ValueError("replacement intent must bind an exact source span")
        return self


class BuySuspensionReplacementBinding(_Signed):
    """Bounded reviewed receipt; only the activation writer can apply its decision."""

    version: Literal["buy-suspension-replacement-v1"] = "buy-suspension-replacement-v1"
    symbol: Identifier
    predecessor_plan_version_id: Identifier
    predecessor_plan_id: Identifier
    predecessor_plan_version: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    predecessor_plan_hash: Hash
    predecessor_content_hash: Hash
    predecessor_source_hash: Hash
    predecessor_review_id: Identifier
    predecessor_review_revision: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    predecessor_activation_revision: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    predecessor_guard: BuySuspensionDefinition
    predecessor_state_hash: Hash
    predecessor_state_revision: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    predecessor_unresolved_from: ShanghaiDatetime | None
    predecessor_unresolved_through: ShanghaiDatetime | None
    new_plan_version_id: Identifier
    new_plan_id: Identifier
    new_plan_version: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    new_plan_hash: Hash
    new_content_hash: Hash
    new_source_hash: Hash
    new_review_id: Identifier
    new_review_revision: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    new_guard: BuySuspensionDefinition | None
    intent: BuySuspensionReplacementIntent
    confirmed_at: ShanghaiDatetime
    authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def exact_replacement(self):
        if (self.intent.source_hash, self.intent.candidate_content_hash) != (
                self.new_source_hash, self.new_content_hash):
            raise ValueError("replacement intent differs from the reviewed new source")
        if self.predecessor_plan_version_id == self.new_plan_version_id:
            raise ValueError("replacement must identify a new exact plan version")
        if self.new_guard is None and not self.intent.retire_predecessor_guard:
            raise ValueError("omission is not explicit retirement")
        if self.predecessor_unresolved_from is not None and (
                not self.intent.acknowledge_unverified_predecessor
                or self.predecessor_unresolved_through is not None
                and self.predecessor_unresolved_through < self.predecessor_unresolved_from):
            raise ValueError("replacement must acknowledge the actual unresolved interval")
        if self.predecessor_unresolved_from is None and (
                self.predecessor_unresolved_through is not None):
            raise ValueError("unresolved interval requires its actual start")
        return self
