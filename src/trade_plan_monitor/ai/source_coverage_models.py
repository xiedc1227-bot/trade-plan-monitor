"""Versioned current source evidence; historical reviews retain their own verifier."""

import json
from collections import Counter
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Path = Annotated[str, Field(min_length=1, max_length=512)]
Codepoint = Annotated[int, Field(strict=True, ge=0, le=150_000)]
CoverageState = Literal[
    "MAPPED", "MAPPED_WITH_REGISTERED_SUPPLEMENT", "CONTEXT_VERIFIED", "SCOPE_EXCLUDED",
    "UNRESOLVED", "UNSUPPORTED", "CONFLICT",
]
COMPLETE_STATES = frozenset({
    "MAPPED", "MAPPED_WITH_REGISTERED_SUPPLEMENT", "CONTEXT_VERIFIED", "SCOPE_EXCLUDED",
})
MAX_PROOF_BYTES = 8 * 1024 * 1024


def _reject_number(value):
    raise ValueError("nonfinite JSON meaning")


def exact_json(value):
    if value is not None:
        parsed = json.loads(value, parse_constant=_reject_number)
        if canonical(parsed) != value:
            raise ValueError("meaning must be canonical JSON")
    return value


class CoverageIssue(DailyValue):
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")]
    path: Path = "source"
    start: Codepoint | None = None
    end: Codepoint | None = None
    message: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def span(self):
        if (self.start is None) != (self.end is None) or (
            self.start is not None and self.end <= self.start
        ):
            raise ValueError("coverage issue span is invalid")
        return self


class SourceObligation(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    version: Literal["source-obligation-v1"] = "source-obligation-v1"
    rules_version: Literal["source-coverage-rules-v1"] = "source-coverage-rules-v1"
    source_hash: Hash
    clause_id: Identifier
    start: Codepoint
    end: Codepoint
    excerpt: str = Field(min_length=1, max_length=512)
    kind: Literal[
        "DECLARATION", "PREDICATE", "RELATION", "CONTEXT", "SCOPE_EXCLUSION", "UNKNOWN",
    ]
    scope: Literal["PLAN", "BUY", "SELL", "RISK", "ALERT", "UNKNOWN"]
    state: CoverageState
    semantics_json: Annotated[str, Field(max_length=8192)] | None = None
    group_id: Hash | None = None
    relation_ids: tuple[Hash, ...] = Field(default=(), max_length=64)
    paths: tuple[Path, ...] = Field(default=(), max_length=512)
    obligation_id: Hash

    _meaning = field_validator("semantics_json")(exact_json)

    def identity(self):
        return daily_hash(self.version, self.model_dump(mode="json", exclude={
            "obligation_id", "state", "paths",
        }))

    @model_validator(mode="after")
    def verify(self):
        if self.end <= self.start or len(self.excerpt) != self.end - self.start:
            raise ValueError("obligation span does not match excerpt length")
        if self.obligation_id != self.identity():
            raise ValueError("source obligation hash mismatch")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, obligation_id="")
        return cls.model_validate(unsigned.model_dump(mode="json") | {
            "obligation_id": unsigned.identity(),
        })


class NormalizationChange(DailyValue):
    path: Path
    before_json: Annotated[str, Field(max_length=8192)]
    after_json: Annotated[str, Field(max_length=8192)]
    reason: Identifier

    _meaning = field_validator("before_json", "after_json")(exact_json)


class NormalizationTrace(DailyValue):
    version: Literal["source-normalization-v1"] = "source-normalization-v1"
    source_hash: Hash
    before_hash: Hash
    after_hash: Hash
    changes: tuple[NormalizationChange, ...] = Field(max_length=2000)
    evidence_hash: Hash

    @model_validator(mode="after")
    def verify(self):
        if self.evidence_hash != daily_hash(self.version,
                self.model_dump(mode="json", exclude={"evidence_hash"})):
            raise ValueError("normalization evidence hash mismatch")
        return self

    @classmethod
    def build(cls, **values):
        values["changes"] = tuple(NormalizationChange.model_validate(row)
                                  for row in values.get("changes", ()))
        unsigned = cls.model_construct(**values, evidence_hash="")
        return cls.model_validate(unsigned.model_dump(mode="json") | {
            "evidence_hash": daily_hash(unsigned.version,
                unsigned.model_dump(mode="json", exclude={"evidence_hash"})),
        })


class CoverageAssessment(DailyValue):
    version: Literal["source-coverage-v1"] = "source-coverage-v1"
    rules_version: Literal["source-coverage-rules-v1"] = "source-coverage-rules-v1"
    source_hash: Hash
    content_hash: Hash
    mapping_hash: Hash
    normalization_hash: Hash | None = None
    origin: Literal["AI_NEW", "AI_HISTORICAL", "HUMAN"]
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
        return (self.coverage_complete and self.origin == "AI_NEW" and bool(self.normalization_hash)
                and not any(row.state == "MAPPED_WITH_REGISTERED_SUPPLEMENT"
                            for row in self.obligations))

    @model_validator(mode="after")
    def verify(self):
        ids = [row.obligation_id for row in self.obligations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source obligation")
        if any(count > 64 for count in Counter(o.clause_id for o in self.obligations).values()):
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if any(o.source_hash != self.source_hash for o in self.obligations):
            raise ValueError("obligation belongs to another source")
        complete = bool(self.obligations) and not self.issues and all(
            o.state in COMPLETE_STATES for o in self.obligations
        ) and (self.origin != "AI_NEW" or self.normalization_hash is not None)
        if self.coverage_complete != complete:
            raise ValueError("source coverage status mismatch")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("source coverage evidence hash mismatch")
        return self

    @classmethod
    def build(cls, **values):
        obligations = tuple(values.get("obligations", ()))
        issues = tuple(values.get("issues", ()))
        if values.get("origin") == "AI_NEW" and values.get("normalization_hash") is None:
            issues += (CoverageIssue(code="SOURCE_NORMALIZATION_LOSS",
                message="New extraction requires its original normalization preimage."),)
        complete = bool(obligations) and not issues and all(
            o.state in COMPLETE_STATES for o in obligations
        )
        unsigned = cls.model_construct(**(values | dict(obligations=obligations, issues=issues)),
            status="COMPLETE" if complete else "BLOCKED", evidence_hash="")
        return cls.model_validate(unsigned.model_dump(mode="json") | {
            "evidence_hash": daily_hash(unsigned.version,
                unsigned.model_dump(mode="json", exclude={"evidence_hash"})),
        })
