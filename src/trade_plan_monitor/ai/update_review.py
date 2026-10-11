"""Per-field source provenance across deterministic updates, without review authority."""

import re
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyFieldBinding,
    DailyMapping,
    DailySupplement,
    build_daily_review,
    semantic_values,
)
from trade_plan_monitor.ai.loop_plan_extraction import unsupported_loop_source_spans
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateContext,
    PlanUpdateExtractionOutput,
    PlanUpdateExtractionResult,
    PriorPlanEvidence,
    UpdateAccountContext,
    validate_update_evidence,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import LoopTimestamp
from trade_plan_monitor.backtest.plan_updates import PlanChange, materialize_plan_update
from trade_plan_monitor.backtest.preparation_models import (
    PreparationCandidateInput,
    PreparationSource,
)
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft, unified_plan_issues

_AMBIGUOUS = re.compile(
    r"待确认|不确定|不要|无需|并非|尚未|不是|不能|不应|假设|假想|假定|示例|"
    r"(?:不|未)(?:完整|全部)?(?:替换|修改|调整|撤销|取消|保留|新增|增加)|"
    r"\bnot\b|unknown|uncertain|hypothetical|example|\bif\b",
    re.I,
)
_REPLACEMENT = (
    r"完整替换(?:此前|原有|之前)?(?:计划)?|全部替换(?:此前|原有|之前)?(?:计划)?|full replacement"
)
_RETAIN = r"(?:其余|其他|未提及)(?:的)?(?:规则|内容|部分)?(?:全部)?(?:保留|不变)|retain unmentioned"


class SourceBoundField(ResearchValue):
    """Keep the original binding and human supplement unchanged when its path moves."""

    path: str = Field(min_length=1, max_length=512)
    original_path: str = Field(min_length=1, max_length=512)
    source_id: StableIdentifier
    source_hash: Sha256Hex
    candidate_content_hash: Sha256Hex
    binding: DailyFieldBinding
    clauses: tuple[DailyClause, ...] = Field(max_length=50)
    supplement: DailySupplement | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.binding.path != self.original_path:
            raise ValueError("inherited binding must retain its original path")
        if tuple(c.clause_id for c in self.clauses) != self.binding.clause_ids:
            raise ValueError("bound source clauses differ from original binding")
        if self.binding.origin == "HUMAN_SUPPLEMENT":
            if self.supplement is None or (
                self.supplement.supplement_id != self.binding.supplement_id
                or self.supplement.candidate_content_hash != self.candidate_content_hash
                or self.supplement.path != self.original_path
                or self.supplement.value != self.binding.value
            ):
                raise ValueError("inherited supplement differs from original candidate")
        elif self.supplement is not None:
            raise ValueError("source/product binding cannot acquire a human supplement")
        return self


class PlanCandidateReview(ResearchValue):
    """Validation evidence, never a human confirmation or frozen replay input."""

    schema_version: Literal["monitor-loop-candidate-evidence-v1"] = (
        "monitor-loop-candidate-evidence-v1"
    )
    source_id: StableIdentifier
    source_hash: Sha256Hex
    available_at: LoopTimestamp | None
    draft: UnifiedPlanDraft
    bindings: tuple[SourceBoundField, ...] = Field(max_length=2000)
    changes: tuple[PlanChange, ...] = Field(default=(), max_length=64)
    account_context: UpdateAccountContext | None = None
    issues: tuple[str, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def coherent(self):
        values = semantic_values(self.draft)
        seen = set()
        for bound in self.bindings:
            if bound.path in seen or bound.path not in values:
                raise ValueError("candidate binding path is duplicated or absent")
            actual = values[bound.path]
            if type(actual) is not type(bound.binding.value) or actual != bound.binding.value:
                raise ValueError("candidate binding differs from materialized policy")
            seen.add(bound.path)
        if not self.issues and (
            seen != values.keys() or self.draft.to_executable() is None or self.available_at is None
        ):
            raise ValueError("candidate cannot be validated without complete policy and evidence")
        return self

    @property
    def evidence_hash(self):
        return sha256(
            ("monitor-loop-candidate-evidence-v1\0" + canonical_json(self)).encode()
        ).hexdigest()

    def to_preparation_candidate(self):
        return PreparationCandidateInput(
            payload_json=canonical_json(self),
            evidence_hash=self.evidence_hash,
            validation="UNRESOLVED" if self.issues else "VALID",
            issues=self.issues,
        )


def _issues(values):
    unique = tuple(dict.fromkeys(value[:512] for value in values))
    return unique if len(unique) <= 128 else (*unique[:127], "ADDITIONAL_REVIEW_ISSUES")


def _bound_fields(mapping, source):
    clauses = {c.clause_id: c for c in mapping.clauses}
    supplements = {s.supplement_id: s for s in mapping.supplements}
    return {
        b.path: SourceBoundField(
            path=b.path,
            original_path=b.path,
            source_id=source.source_id,
            source_hash=source.binding_hash,
            candidate_content_hash=mapping.candidate_content_hash,
            binding=b,
            clauses=tuple(clauses[key] for key in b.clause_ids),
            supplement=supplements.get(b.supplement_id),
        )
        for b in mapping.bindings
    }


def build_initial_review(draft: UnifiedPlanDraft, mapping: DailyMapping, source: PreparationSource):
    """Validate first-source plan evidence; account validation remains a separate prerequisite."""
    source = PreparationSource.model_validate(source.model_dump(mode="python"))
    draft = UnifiedPlanDraft.model_validate(draft.model_dump(mode="python"))
    review = build_daily_review(draft, mapping, source.text)
    issues = [f"{i.code}: {i.path}" for i in review.issues]
    if source.available_at is None:
        issues.append("LOOP_SOURCE_TIME_REQUIRED")
    if unsupported_loop_source_spans(source.text):
        issues.append("LOOP_SOURCE_UNSUPPORTED")
    return PlanCandidateReview(
        source_id=source.source_id,
        source_hash=source.binding_hash,
        available_at=source.available_at,
        draft=draft,
        bindings=tuple(_bound_fields(review.mapping, source).values()),
        issues=_issues(issues),
    )


def context_from_review(base: PlanCandidateReview, base_hash: str) -> PlanUpdateContext:
    base = PlanCandidateReview.model_validate(base.model_dump(mode="python"))
    if base.issues:
        raise ValueError("unresolved predecessor blocks dependent work")
    evidence = tuple(
        PriorPlanEvidence(
            path=bound.path,
            source_id=bound.source_id,
            source_hash=bound.source_hash,
            clause_id=clause.clause_id,
            start=clause.start,
            end=clause.end,
            excerpt=clause.excerpt,
        )
        for bound in base.bindings
        for clause in bound.clauses
    )
    return PlanUpdateContext(
        base_hash=base_hash,
        snapshot=base.draft.to_executable(),
        available_at=base.available_at,
        evidence=evidence,
    )


def _scope_issues(output):
    clauses = {c.clause_id: c for c in output.clauses}
    scope = " ".join(clauses[key].excerpt for key in output.scope_clause_ids)
    issues = []
    if output.scope == "UNRESOLVED" or _AMBIGUOUS.search(scope):
        issues.append("UPDATE_SCOPE_UNRESOLVED")
    elif output.scope == "FULL_REPLACEMENT":
        if not re.search(_REPLACEMENT, scope, re.I):
            issues.append("UPDATE_REPLACEMENT_EVIDENCE_REQUIRED")
    elif output.retain_unmentioned and not re.search(_RETAIN, scope, re.I):
        issues.append("UPDATE_RETENTION_EVIDENCE_REQUIRED")
    labels = {
        "position": r"仓位|position",
        "activation": r"生效|激活|activation",
        "levels": r"价位|价格|levels",
        "monitoring": r"监控|monitoring",
        "execution_policy": r"执行|execution",
        "trading_rules": r"交易规则|trading",
        "metadata": r"元数据|metadata",
    }
    verbs = {
        "ADD": r"新增|增加|add",
        "MODIFY": r"修改|调整|改为|modify|change",
        "REVOKE": r"撤销|取消|删除|revoke|remove",
        "RETAIN": r"保留|不变|retain|keep",
    }
    for op in output.operations:
        text = " ".join(clauses[key].excerpt for key in op.clause_ids)
        target = re.escape(op.rule_id) if op.rule_id else labels[op.target]
        if (
            _AMBIGUOUS.search(text)
            or not re.search(target, text, re.I)
            or not re.search(
                verbs[op.action],
                text,
                re.I,
            )
        ):
            issues.append(f"UPDATE_OPERATION_EVIDENCE_REQUIRED: {op.target}.{op.rule_id or ''}")
    return issues


def _pure_scope_clause(clause, output):
    """Only a complete narrow control sentence may be resolved without policy field paths."""
    if clause.disposition == "UNSUPPORTED" or clause.remainders or clause.exclusions:
        return False
    text = clause.excerpt.strip(" 。；;.!\n\r\t")
    patterns = []
    if clause.clause_id in output.scope_clause_ids:
        patterns.extend((_REPLACEMENT, _RETAIN))
    for op in output.operations:
        if clause.clause_id in op.clause_ids and op.rule_id and op.action in {"REVOKE", "RETAIN"}:
            verb = r"撤销|取消|删除|revoke|remove" if op.action == "REVOKE" else r"保留|retain|keep"
            patterns.append(r"(?:" + verb + r")\s*(?:规则\s*)?" + re.escape(op.rule_id))
    return any(re.fullmatch(pattern, text, re.I) for pattern in patterns) or bool(
        _account_dependencies(clause, output)
    )


def _account_dependencies(clause, output):
    """Recognize only complete literal account prerequisites, keeping other wording unresolved."""
    account = output.account_context
    if account is None or clause.clause_id not in account.dependency_clause_ids:
        return ()
    text = clause.excerpt.strip(" 。；;.!\n\r\t")
    matched = []
    for identity in account.dependent_rule_ids:
        for field, labels in (("core_qty", "CORE|核心仓"), ("tactical_qty", "TACTICAL|机动仓")):
            fact = getattr(account, field)
            if fact is None:
                continue
            pattern = (
                r"(?:规则)?"
                + re.escape(identity)
                + r"\s*(?:仅当|只有在|requires)\s*(?:"
                + labels
                + r")\s*(?:持仓|持有|库存|holdings|inventory)\s*"
                + str(fact.value)
                + r"\s*(?:股|shares)(?:时执行|才能执行)?"
            )
            if re.fullmatch(pattern, text, re.I):
                matched.append(identity)
    return tuple(matched)


def build_update_review(
    base: PlanCandidateReview,
    source: PreparationSource,
    output: PlanUpdateExtractionOutput,
    *,
    mapping: DailyMapping | None = None,
) -> PlanCandidateReview:
    """Recompute from a validated base; a mapping override is an explicit human correction."""
    base = PlanCandidateReview.model_validate(base.model_dump(mode="python"))
    source = PreparationSource.model_validate(source.model_dump(mode="python"))
    output = PlanUpdateExtractionOutput.model_validate(output.model_dump(mode="python"))
    context = context_from_review(base, base.evidence_hash)
    if source.available_at is None or context.available_at > source.available_at:
        raise ValueError("predecessor context is unavailable at the current source")
    validate_update_evidence(output, source, context)
    materialized = materialize_plan_update(context.snapshot, output)
    current = (
        output.review(source.text)
        if mapping is None
        else build_daily_review(output.draft, mapping, source.text)
    )
    current_fields = _bound_fields(current.mapping, source)
    base_fields = {b.path: b for b in base.bindings}
    bindings = []
    issues = _scope_issues(output)
    selected = set()
    for origin in materialized.origins:
        available = base_fields if origin.origin == "BASE" else current_fields
        if origin.origin == "CURRENT":
            selected.add(origin.original_path)
        bound = available.get(origin.original_path)
        if bound is None:
            issues.append("UPDATE_SOURCE_BINDING_REQUIRED: " + origin.path)
        else:
            bindings.append(bound.model_copy(update={"path": origin.path}))
    clauses = {c.clause_id: c for c in current.mapping.clauses}
    for issue in current.issues:
        if issue.path.startswith("source."):
            clause = clauses.get(issue.path.removeprefix("source."))
            if clause is None or not _pure_scope_clause(clause, output):
                issues.append(f"{issue.code}: {issue.path}")
        elif issue.path in selected and issue.code == "DAILY_SOURCE_BINDING_REQUIRED":
            issues.append(f"{issue.code}: {issue.path}")
    issues.extend(f"{i['code']}: {i['path']}" for i in unified_plan_issues(materialized.draft))
    if unsupported_loop_source_spans(source.text):
        issues.append("LOOP_SOURCE_UNSUPPORTED")
    if output.assumptions or output.warnings:
        issues.append("UPDATE_ASSUMPTIONS_REQUIRE_REVIEW")
    if output.account_context is not None:
        rules = {r.rule_id for r in materialized.draft.ordinary_rules}
        if not set(output.account_context.dependent_rule_ids) <= rules:
            raise ValueError("account dependency refers to a nonexistent materialized rule")
        supported = {
            identity
            for key in output.account_context.dependency_clause_ids
            for identity in _account_dependencies(clauses[key], output)
        }
        for identity in output.account_context.dependent_rule_ids:
            if identity not in supported:
                issues.append("UPDATE_ACCOUNT_DEPENDENCY_REQUIRED: " + identity)
    return PlanCandidateReview(
        source_id=source.source_id,
        source_hash=source.binding_hash,
        available_at=source.available_at,
        draft=materialized.draft,
        bindings=tuple(bindings),
        changes=materialized.changes,
        account_context=output.account_context,
        issues=_issues(issues),
    )


class MaterializedUpdateCandidate(ResearchValue):
    schema_version: Literal["monitor-loop-materialized-update-v1"] = (
        "monitor-loop-materialized-update-v1"
    )
    extraction: PlanUpdateExtractionResult
    review: PlanCandidateReview

    def to_preparation_candidate(self):
        return PreparationCandidateInput(
            payload_json=canonical_json(self),
            evidence_hash=self.review.evidence_hash,
            validation="UNRESOLVED" if self.review.issues else "VALID",
            issues=self.review.issues,
        )


def materialize_extraction(base, base_hash, source, extraction):
    """Bind the semantic result to the exact predecessor and current provider response."""
    extraction = PlanUpdateExtractionResult.model_validate(extraction.model_dump(mode="python"))
    context = context_from_review(base, base_hash)
    expected = sha256(
        canonical_json(
            {
                "domain": "monitor-loop-update-evidence-v1",
                "source_binding_hash": source.binding_hash,
                "context": context,
                "output": extraction.output,
            }
        ).encode()
    ).hexdigest()
    if (
        extraction.base_hash != base_hash
        or extraction.source_binding_hash != source.binding_hash
        or extraction.source_id != source.source_id
        or extraction.source_text_sha256 != source.source_hash
        or extraction.evidence_hash != expected
        or extraction.available_at != source.available_at
        or extraction.authored_at != source.authored_at
        or extraction.effective_trade_date != source.effective_trade_date
    ):
        raise ValueError("update extraction differs from current source or predecessor")
    return MaterializedUpdateCandidate(
        extraction=extraction,
        review=build_update_review(base, source, extraction.output),
    )
