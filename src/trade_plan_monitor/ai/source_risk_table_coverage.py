"""Private non-executable table relationships require the exact upstream price owner."""

import json
from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_candidate_models import SourceCandidateAssurance, SourceOwner
from trade_plan_monitor.ai.source_coverage_models import MAX_PROOF_BYTES, CoverageIssue
from trade_plan_monitor.ai.source_risk_table_controls import parse_source_risk_table_controls
from trade_plan_monitor.ai.source_risk_table_models import (
    RiskTableFraming,
    SourceRiskTableAnalysis,
    StructuralRecoveryReference,
    risk_table_frame_id,
)
from trade_plan_monitor.ai.update_review import PlanCandidateReview, SourceBoundField
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.daily_scope import scope_hash


class RiskTablePriceDependency(DailyValue):
    reference: StructuralRecoveryReference
    price_owner: SourceOwner
    price_binding: SourceBoundField
    parent_binding: CandidateBinding
    authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def exact_price(self):
        role, owner, bound = self.reference, self.price_owner, self.price_binding
        if (owner.path != role.parent_price_path or bound.path != role.parent_price_path
                or owner.original_path != bound.original_path or owner.source_id != bound.source_id
                or owner.source_binding_hash != bound.source_hash or not owner.obligation_ids
                or owner.origin not in {"CURRENT", "BASE", "HUMAN"}
                or bound.binding.origin not in {
                    "SOURCE", "SOURCE_INTERPRETATION", "SOURCE_SEMANTIC", "HUMAN_SUPPLEMENT"}
                or type(bound.binding.value) is not int or bound.binding.value != role.price_fen
                or self.parent_binding.review_evidence_hash != role.base_review_hash):
            raise ValueError("structural reference differs from its actual complete price owner")
        return self


def _framing(source, analysis, references):
    selected = {row.reference.group_id for row in references}
    frames = {group.frame_id for group in analysis.groups if group.group_id in selected}
    owned = []
    for left, right in zip(analysis.framing, analysis.framing[1:], strict=False):
        if (left.kind != "HEADER" or right.kind != "SEPARATOR"
                or risk_table_frame_id(left, right) not in frames):
            continue
        owned.extend((left, right))
        owned.extend(row for row in analysis.framing if row.kind == "HEADING"
                     and row.end < left.start and source[row.end:left.start].isspace())
    return tuple(sorted(set(owned), key=lambda row: row.start))


class RiskTableCoverage(DailyValue):
    """Server-private evidence only; no executable fields or automatic authority."""

    analysis: SourceRiskTableAnalysis
    references: tuple[RiskTablePriceDependency, ...] = Field(max_length=64)
    framing: tuple[RiskTableFraming, ...] = Field(max_length=512)
    issues: tuple[CoverageIssue, ...] = Field(max_length=512)
    authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def complete_relationships(self):
        groups = {group.group_id: group for group in self.analysis.groups}
        ids = [row.reference.group_id for row in self.references]
        if (len(ids) != len(set(ids)) or any(identity not in groups for identity in ids)
                or any(row.reference != groups[row.reference.group_id].structural_reference
                       for row in self.references)
                or set(ids) != set(groups) and not self.issues
                or any(row not in self.analysis.framing for row in self.framing)):
            raise ValueError("mixed risk table lost its independent structural relationship")
        if len(canonical(self.model_dump(mode="json")).encode("utf-8")) > MAX_PROOF_BYTES:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        return self


def _price_dependency(group, base, parent):
    role = group.structural_reference
    owner = next((row for row in parent.owners if row.path == role.parent_price_path), None)
    bound = next((row for row in base.bindings if row.path == role.parent_price_path), None)
    if owner is None or bound is None:
        raise ValueError("structural reference has no actual price owner")
    dependency = RiskTablePriceDependency(reference=role, price_owner=owner, price_binding=bound,
                                         parent_binding=parent.binding)
    current = owner.proof_hash == parent.source_assessment.evidence_hash
    supplied = bound.binding.origin == "HUMAN_SUPPLEMENT"
    human = (owner.origin == "HUMAN" or supplied
             or current and parent.source_assessment.origin == "HUMAN")
    if human and not owner.human_receipt_hash:
        raise ValueError("structural price owner lost its human receipt")
    operation_hash = getattr(parent.source_assessment, "human_operation_hash", None)
    if current and operation_hash is not None and owner.human_receipt_hash != operation_hash:
        raise ValueError("structural price owner has another human receipt")
    if current:
        rows = {row.obligation_id: row for row in parent.source_assessment.obligations}
        expected = dict(path=bound.original_path, value=None,
                        supplement=bound.supplement.model_dump(mode="json")) if supplied else dict(
                            path=bound.original_path, value=role.price_fen)
        state = "MAPPED_WITH_REGISTERED_SUPPLEMENT" if supplied else "MAPPED"
        if not any((row := rows.get(identity)) is not None and row.state == state
                   and bound.original_path in row.paths and row.semantics_json is not None
                   and canonical(json.loads(row.semantics_json)) == canonical(expected)
                   for identity in owner.obligation_ids):
            raise ValueError("structural reference has no exact original price obligation")
    return dependency


def build_risk_table_coverage(source, base_review, verified_parent):
    """Freshly derive both meanings from the source and authenticated complete parent."""
    base = PlanCandidateReview.model_validate_json(base_review.model_dump_json())
    parent = SourceCandidateAssurance.model_validate_json(verified_parent.model_dump_json())
    analysis = parse_source_risk_table_controls(source, base, parent)
    references, issues = [], list(analysis.issues)
    for group in analysis.groups:
        try:
            dependency = _price_dependency(group, base, parent)
        except ValueError:
            role = group.structural_reference
            issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED",
                path=role.parent_price_path,
                start=role.start, end=role.end,
                message="The structural reference has no exact independently proven parent price."))
        else:
            references.append(dependency)
    return RiskTableCoverage(analysis=analysis, references=tuple(references),
        framing=_framing(source.text, analysis, references), issues=tuple(issues))


def validate_risk_table_coverage(value, source):
    """Validate exact source ownership without treating self-consistency as parent authority."""
    value = RiskTableCoverage.model_validate_json(value.model_dump_json())
    analysis = value.analysis
    spans = (*analysis.framing, *analysis.unresolved,
             *(group.scope_control for group in analysis.groups))
    if (analysis.source_hash != scope_hash(source) or analysis.source_length != len(source)
            or any(source[row.start:row.end] != row.excerpt for row in spans)
            or value.framing != _framing(source, analysis, value.references)):
        raise ValueError("risk table coverage differs from the complete original source")
    return value
