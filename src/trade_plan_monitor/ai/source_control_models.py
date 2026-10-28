"""Exact source control claims; neither recognition nor a hash grants authority."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from trade_plan_monitor.ai.source_coverage_models import (
    MAX_PROOF_BYTES,
    Codepoint,
    CoverageIssue,
    Hash,
)
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier

ControlTarget = Literal[
    "ordinary_rules", "alert_rules", "activation", "levels", "position", "monitoring",
    "execution_policy", "trading_rules", "metadata", "plan",
]


class _ExactSpan(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    source_hash: Hash
    start: Codepoint
    end: Codepoint
    excerpt: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def exact_span(self):
        if self.end <= self.start or self.end - self.start != len(self.excerpt):
            raise ValueError("source control span differs from its exact excerpt")
        return self


class SourceControlSpan(_ExactSpan):
    """Unrecognized by this finite control registry; other source grammars may apply."""

    scope: Literal["UNKNOWN"] = "UNKNOWN"


class SourceControl(_ExactSpan):
    version: Literal["source-control-v1"] = "source-control-v1"
    grammar_id: Identifier
    scope: Literal["PLAN", "BUY", "SELL", "ALERT"]
    action: Literal[
        "REVOKE", "RETAIN", "NO_NEW_INSTRUCTIONS", "RETAIN_UNMENTIONED", "FULL_REPLACEMENT",
    ]
    target: ControlTarget
    rule_id: Identifier | None
    parent_assurance_hash: Hash
    before_hash: Hash
    authority_granted: Literal[False] = False
    control_id: Hash

    @model_validator(mode="after")
    def coherent(self):
        if self.target == "ordinary_rules":
            valid = (self.rule_id is not None and self.scope in {"BUY", "SELL"}
                     and self.action in {"REVOKE", "RETAIN"})
        elif self.target == "alert_rules":
            valid = (self.rule_id is not None and self.scope == "ALERT"
                     and self.action in {"REVOKE", "RETAIN"})
        elif self.target == "plan":
            valid = (self.rule_id is None and self.scope == "PLAN"
                     and self.action in {
                         "NO_NEW_INSTRUCTIONS", "RETAIN_UNMENTIONED", "FULL_REPLACEMENT"})
        else:
            valid = self.rule_id is None and self.scope == "PLAN" and self.action == "RETAIN"
        if not valid:
            raise ValueError("source control action, target, identity and scope differ")
        if self.control_id != daily_hash(self.version,
                self.model_dump(mode="json", exclude={"control_id"})):
            raise ValueError("source control identity differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, control_id="")
        payload = unsigned.model_dump(mode="json", exclude={"control_id"})
        return cls.model_validate(payload | {"control_id": daily_hash(unsigned.version, payload)})


class SourceControlAnalysis(DailyValue):
    """A bounded control parse, deliberately distinct from full source coverage."""

    version: Literal["source-control-analysis-v1"] = "source-control-analysis-v1"
    source_hash: Hash
    source_length: int = Field(strict=True, ge=1, le=150_000)
    parent_assurance_hash: Hash
    base_review_hash: Hash
    parent_coverage_complete: bool = Field(strict=True)
    controls: tuple[SourceControl, ...] = Field(max_length=64)
    unresolved: tuple[SourceControlSpan, ...] = Field(max_length=4096)
    issues: tuple[CoverageIssue, ...] = Field(default=(), max_length=512)
    authority_granted: Literal[False] = False
    evidence_hash: Hash

    @model_validator(mode="after")
    def verify(self):
        spans = (*self.controls, *self.unresolved)
        if any(row.source_hash != self.source_hash or row.end > self.source_length
               for row in spans) or any(row.parent_assurance_hash != self.parent_assurance_hash
                                       for row in self.controls):
            raise ValueError("source control belongs to another exact source or parent")
        ordered = sorted(spans, key=lambda row: row.start)
        if any(left.end > right.start for left, right in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("source control spans overlap")
        if len({row.control_id for row in self.controls}) != len(self.controls):
            raise ValueError("duplicate source control identity")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("source control analysis hash differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        })
