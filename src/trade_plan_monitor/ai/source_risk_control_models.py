"""Finite risk-control evidence, distinct from coverage or execution authority."""

from datetime import date
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
from trade_plan_monitor.domain.risk_scope import RiskHoldingScope, restrict_scope, risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedRiskBranch


class _RiskSourceSpan(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    source_hash: Hash
    start: Codepoint
    end: Codepoint
    excerpt: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def exact_span(self):
        if self.end <= self.start or self.end - self.start != len(self.excerpt):
            raise ValueError("risk source span differs from its exact excerpt")
        return self


class SourceRiskControlSpan(_RiskSourceSpan):
    scope: Literal["UNKNOWN"] = "UNKNOWN"


class SourceRiskControl(_RiskSourceSpan):
    version: Literal["source-risk-control-v1"] = "source-risk-control-v1"
    grammar_id: Identifier
    source_id: Identifier
    source_binding_hash: Hash
    effective_trade_date: date | None
    base_review_hash: Hash
    parent_assurance_hash: Hash
    target: Literal["risk_branches"] = "risk_branches"
    rule_id: Identifier
    scope: Literal["RISK"] = "RISK"
    action: Literal["MODIFY", "REVOKE", "RETAIN"]
    scope_assessment: Literal["PARTIAL_RULE", "ENTIRE_RULE"]
    scope_change: Literal["EXISTING_POSITIONS_ONLY", "NEW_POSITIONS_ONLY"] | None
    before: UnifiedRiskBranch
    after: UnifiedRiskBranch | None
    derived_holding_scope: RiskHoldingScope | None
    before_hash: Hash
    after_hash: Hash
    preserved_policy_hash: Hash
    authority_granted: Literal[False] = False
    control_id: Hash

    @model_validator(mode="after")
    def coherent(self):
        before = self.before.model_dump(mode="json")
        after = None if self.after is None else self.after.model_dump(mode="json")
        if risk_identity(self.before) != self.rule_id:
            raise ValueError("risk control identifies another predecessor branch")
        if self.action == "MODIFY":
            if (self.scope_assessment != "PARTIAL_RULE" or self.scope_change is None
                    or self.effective_trade_date is None):
                raise ValueError("partial risk control requires its bound date and direction")
            mode = ("BEFORE_TRADE_DATE" if self.scope_change == "EXISTING_POSITIONS_ONLY"
                    else "FROM_TRADE_DATE")
            expected = restrict_scope(self.before.holding_scope, mode, self.effective_trade_date)
            if self.derived_holding_scope != expected or canonical(after) != canonical(
                before | {"holding_scope": expected.model_dump(mode="json")}
            ):
                raise ValueError("partial risk control must preserve every non-scope field")
        elif (self.scope_assessment != "ENTIRE_RULE" or self.scope_change is not None
              or self.derived_holding_scope is not None
              or (self.action == "REVOKE" and self.after is not None)
              or (self.action == "RETAIN" and canonical(after) != canonical(before))):
            raise ValueError("whole risk control differs from its exact retain or revoke value")
        policy = {key: value for key, value in before.items() if key != "holding_scope"}
        if (self.before_hash != daily_hash("source-operation-value-v1", before)
                or self.after_hash != daily_hash("source-operation-value-v1", after)
                or self.preserved_policy_hash != daily_hash("source-risk-policy-v1", policy)):
            raise ValueError("risk control values differ from their complete hashes")
        payload = self.model_dump(mode="json", exclude={"control_id"})
        if len(canonical(payload).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.control_id != daily_hash(self.version, payload):
            raise ValueError("risk control identity differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, control_id="")
        payload = unsigned.model_dump(mode="json", exclude={"control_id"})
        return cls.model_validate(payload | {"control_id": daily_hash(unsigned.version, payload)})


class SourceRiskControlAnalysis(DailyValue):
    """A bounded parse only; no complete/status verdict or independent authority."""

    version: Literal["source-risk-control-analysis-v1"] = "source-risk-control-analysis-v1"
    source_id: Identifier
    source_hash: Hash
    source_binding_hash: Hash
    source_length: int = Field(strict=True, ge=1, le=150_000)
    effective_trade_date: date | None
    parent_assurance_hash: Hash
    base_review_hash: Hash
    controls: tuple[SourceRiskControl, ...] = Field(max_length=64)
    unresolved: tuple[SourceRiskControlSpan, ...] = Field(max_length=4096)
    issues: tuple[CoverageIssue, ...] = Field(default=(), max_length=512)
    authority_granted: Literal[False] = False
    evidence_hash: Hash

    @model_validator(mode="after")
    def coherent(self):
        spans = (*self.controls, *self.unresolved)
        if any(row.source_hash != self.source_hash or row.end > self.source_length
               for row in spans):
            raise ValueError("risk control span belongs to another source")
        expected = (self.source_id, self.source_binding_hash, self.effective_trade_date,
                    self.parent_assurance_hash, self.base_review_hash)
        if any((row.source_id, row.source_binding_hash, row.effective_trade_date,
                row.parent_assurance_hash, row.base_review_hash) != expected
               for row in self.controls):
            raise ValueError("risk control belongs to another source binding or parent")
        ordered = sorted(spans, key=lambda row: row.start)
        if any(left.end > right.start for left, right in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("risk source spans overlap")
        if len({row.control_id for row in self.controls}) != len(self.controls):
            raise ValueError("duplicate risk control identity")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("risk control analysis identity differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        })
