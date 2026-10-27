"""Two independent meanings of a finite mixed risk row, without a coverage verdict."""

from datetime import date
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from trade_plan_monitor.ai.source_coverage_models import (
    MAX_PROOF_BYTES,
    Codepoint,
    CoverageIssue,
    Hash,
)
from trade_plan_monitor.ai.source_risk_control_models import (
    SourceRiskControl,
    SourceRiskControlSpan,
)
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier


class _TableSpan(DailyValue):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    source_hash: Hash
    start: Codepoint
    end: Codepoint
    excerpt: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def exact_span(self):
        if self.end <= self.start or self.end - self.start != len(self.excerpt):
            raise ValueError("risk table span differs from its exact excerpt")
        return self


class RiskTableFraming(_TableSpan):
    """Syntax ownership only, never a context/mandatory-condition waiver."""

    kind: Literal["HEADING", "HEADER", "SEPARATOR"]
    authority_granted: Literal[False] = False


def risk_table_frame_id(header, separator):
    return daily_hash("source-risk-table-frame-v1", dict(
        header=header.model_dump(mode="json"), separator=separator.model_dump(mode="json")))


def risk_table_group_id(frame_id, control_id, price_fen, parent_price_path):
    return daily_hash("source-risk-table-group-v1", dict(frame_id=frame_id,
        scope_control_id=control_id, price_fen=price_fen, parent_price_path=parent_price_path))


class StructuralRecoveryReference(_TableSpan):
    version: Literal["source-structural-recovery-reference-v1"] = (
        "source-structural-recovery-reference-v1")
    source_id: Identifier
    source_binding_hash: Hash
    parent_assurance_hash: Hash
    base_review_hash: Hash
    group_id: Hash
    scope_control_id: Hash
    role: Literal["STRUCTURAL_RECOVERY_REFERENCE"] = "STRUCTURAL_RECOVERY_REFERENCE"
    price_fen: int = Field(strict=True, gt=0, le=9_007_199_254_740_991)
    unit: Literal["FEN"] = "FEN"
    parent_price_path: Annotated[str, Field(pattern=(
        r"^(?:levels\.risk_line_fen|risk_branches\[(?:0|[1-9][0-9]*)\]\.risk_line_fen)$"))]
    authority_granted: Literal[False] = False
    atom_id: Hash

    @model_validator(mode="after")
    def coherent(self):
        payload = self.model_dump(mode="json", exclude={"atom_id"})
        if len(canonical(payload).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.atom_id != daily_hash(self.version, payload):
            raise ValueError("structural reference identity differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, atom_id="")
        payload = unsigned.model_dump(mode="json", exclude={"atom_id"})
        return cls.model_validate(payload | {"atom_id": daily_hash(unsigned.version, payload)})


class SourceRiskTableGroup(DailyValue):
    frame_id: Hash
    group_id: Hash
    scope_control: SourceRiskControl
    structural_reference: StructuralRecoveryReference
    authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self):
        control, role = self.scope_control, self.structural_reference
        same = ("source_id", "source_hash", "source_binding_hash", "parent_assurance_hash",
                "base_review_hash", "start", "end", "excerpt")
        if (any(getattr(control, key) != getattr(role, key) for key in same)
                or control.action != "MODIFY" or control.scope_change != "EXISTING_POSITIONS_ONLY"
                or control.before.kind != "ORDINARY_TECHNICAL"
                or role.scope_control_id != control.control_id
                or role.group_id != self.group_id
                or self.group_id != risk_table_group_id(self.frame_id, control.control_id,
                                                        role.price_fen, role.parent_price_path)):
            raise ValueError("mixed risk row lost an exact independent meaning or binding")
        if (control.before.risk_line_fen is not None and (
            control.before.risk_line_fen != role.price_fen
            or not role.parent_price_path.startswith("risk_branches[")
        ) or control.before.risk_line_fen is None
                and role.parent_price_path != "levels.risk_line_fen"):
            raise ValueError("structural reference differs from its selected parent price owner")
        return self


class SourceRiskTableAnalysis(DailyValue):
    """A source ledger, deliberately without complete/status/approval fields."""

    version: Literal["source-risk-table-analysis-v1"] = "source-risk-table-analysis-v1"
    source_id: Identifier
    source_hash: Hash
    source_binding_hash: Hash
    source_length: int = Field(strict=True, ge=1, le=150_000)
    effective_trade_date: date | None
    parent_assurance_hash: Hash
    base_review_hash: Hash
    framing: tuple[RiskTableFraming, ...] = Field(max_length=512)
    groups: tuple[SourceRiskTableGroup, ...] = Field(max_length=64)
    unresolved: tuple[SourceRiskControlSpan, ...] = Field(max_length=4096)
    issues: tuple[CoverageIssue, ...] = Field(default=(), max_length=512)
    authority_granted: Literal[False] = False
    evidence_hash: Hash

    @model_validator(mode="after")
    def coherent(self):
        controls = tuple(row.scope_control for row in self.groups)
        spans = (*self.framing, *self.unresolved, *controls)
        if any(row.source_hash != self.source_hash or row.end > self.source_length
               for row in spans):
            raise ValueError("risk table ledger refers to another source")
        ordered = sorted(spans, key=lambda row: row.start)
        if any(left.end > right.start for left, right in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("risk table ledger ownership overlaps")
        expected = (self.source_id, self.source_binding_hash, self.effective_trade_date,
                    self.parent_assurance_hash, self.base_review_hash)
        if any((row.source_id, row.source_binding_hash, row.effective_trade_date,
                row.parent_assurance_hash, row.base_review_hash) != expected for row in controls):
            raise ValueError("risk table group has another source binding or parent")
        frames = {risk_table_frame_id(left, right)
                  for left, right in zip(self.framing, self.framing[1:], strict=False)
                  if left.kind == "HEADER" and right.kind == "SEPARATOR"}
        if any(group.frame_id not in frames for group in self.groups):
            raise ValueError("risk table group lost its exact header/separator owner")
        if len({group.group_id for group in self.groups}) != len(self.groups):
            raise ValueError("duplicate mixed risk row identity")
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        if len(canonical(payload).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if self.evidence_hash != daily_hash(self.version, payload):
            raise ValueError("risk table analysis identity differs")
        return self

    @classmethod
    def build(cls, **values):
        unsigned = cls.model_construct(**values, evidence_hash="")
        payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
        return cls.model_validate(payload | {
            "evidence_hash": daily_hash(unsigned.version, payload),
        })
