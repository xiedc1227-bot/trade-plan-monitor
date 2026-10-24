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
from trade_plan_monitor.domain.market_linkage_validation import (
    CurrentPlanDraft,
    parse_current_draft,
)
from trade_plan_monitor.domain.risk_scope import restrict_scope, risk_identity
from trade_plan_monitor.domain.unified_plan_validation import unified_plan_issues

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
    draft: CurrentPlanDraft
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


def build_initial_review(draft: CurrentPlanDraft, mapping: DailyMapping, source: PreparationSource):
    """Validate first-source plan evidence; account validation remains a separate prerequisite."""
    source = PreparationSource.model_validate(source.model_dump(mode="python"))
    draft = parse_current_draft(draft.model_dump(mode="python"))
    review = build_daily_review(draft, mapping, source.text)
    issues = [f"{i.code}: {i.path}" for i in review.issues]
    if source.execution_available_at is None:
        issues.append("LOOP_SOURCE_TIME_REQUIRED")
    if unsupported_loop_source_spans(source.text):
        issues.append("LOOP_SOURCE_UNSUPPORTED")
    return PlanCandidateReview(
        source_id=source.source_id,
        source_hash=source.binding_hash,
        available_at=source.execution_available_at,
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


def _natural_rule_pattern(op, base):
    """Resolve a business name only when it identifies one predecessor rule."""
    if base is None or op.target != "ordinary_rules":
        return None
    rules = base.draft.ordinary_rules
    rule = next((rule for rule in rules if rule.rule_id == op.rule_id), None)
    if rule is None or sum(other.side == rule.side for other in rules) != 1:
        return None
    side = "买入|买进" if rule.side == "BUY" else "卖出|减仓"
    pattern = (
        r"(?:原来(?:的)?|原有(?:的)?|此前(?:的)?|上一份(?:计划)?(?:的)?)?(?:"
        + side + r")(?:规则|条件|计划)"
    )
    zone = base.draft.levels.low_buy if base.draft.levels else None
    if rule.side == "BUY" and zone is not None:
        def price_pattern(fen):
            value = f"{fen // 100}.{fen % 100:02d}"
            return re.escape(value.rstrip("0").rstrip(".")) + (
                r"(?:\.0{1,2})?" if fen % 100 == 0 else r"0?" if fen % 10 == 0 else ""
            )
        pattern += (
            r"|原?(?<![\d.])" + price_pattern(zone.low_fen) + r"\s*[—–~至-]\s*"
            + price_pattern(zone.high_fen) + r"\s*低吸(?:规则|条件|计划)"
        )
    return "(?:" + pattern + ")"


def _operation_prefix(op, draft):
    if op.rule_id is None:
        return op.target
    return next((f"{op.target}[{index}]" for index, rule in enumerate(getattr(draft, op.target))
                 if (risk_identity(rule) if op.target == "risk_branches" else rule.rule_id)
                 == op.rule_id), None)


def _in_prefix(path, prefix):
    return prefix is not None and (path == prefix or path.startswith(prefix + "."))


def _restated_operation(op, base, output, current):
    """A validated current policy statement can identify an addition/modification.

    This never authorizes cancellation. Retention additionally requires the exact
    same rule, and all selected fields still undergo complete provenance checks.
    """
    if current is None or base is None or op.action == "REVOKE":
        return False
    excerpts = " ".join(c.excerpt for c in output.clauses if c.clause_id in op.clause_ids)
    if re.search(
        r"假设|假想|假定|示例|待确认|不确定|"
        r"(?:不|未|不要|无需|不能|不应).{0,12}(?:修改|调整|改为|保留|新增|增加)|"
        r"\bnot\b|hypothetical|example", excerpts, re.I,
    ):
        return False
    prefix = _operation_prefix(op, output.draft)
    if prefix is None:
        return False
    if op.action == "RETAIN":
        old_prefix = _operation_prefix(op, base.draft)
        before = {p.removeprefix(old_prefix): v for p, v in semantic_values(base.draft).items()
                  if old_prefix and _in_prefix(p, old_prefix)}
        after = {p.removeprefix(prefix): v for p, v in semantic_values(output.draft).items()
                 if _in_prefix(p, prefix)}
        if before != after:
            return False
    invalid = {issue.path for issue in current.issues}
    return any(
        _in_prefix(binding.path, prefix) and binding.path not in invalid
        and binding.origin in {"SOURCE", "SOURCE_INTERPRETATION"}
        and set(binding.clause_ids) & set(op.clause_ids)
        and not binding.path.endswith((".rule_id", ".status", ".type", ".mode"))
        for binding in current.mapping.bindings
    )


def _covered_retention(base, output, current):
    """Every unmentioned policy leaf must be restated or a fixed product constant."""
    if base is None or current is None:
        return False
    touched = [_operation_prefix(op, base.draft) for op in output.operations]
    current_values = semantic_values(output.draft)
    bindings = {binding.path: binding for binding in current.mapping.bindings}
    invalid = {issue.path for issue in current.issues}
    risk_retained = (
        output.draft.risk_branches == base.draft.risk_branches
        and not any(op.target == "risk_branches" for op in output.operations)
        and any(re.fullmatch(r"不能因为随后反弹就直接取消风控[，。；]*", c.excerpt.strip())
                for c in output.clauses)
    )
    for path, value in semantic_values(base.draft).items():
        if risk_retained and path.startswith("risk_branches["):
            continue
        # An explicit ADD replaces the empty collection's [] sentinel. It does
        # not leave an unmentioned old rule whose retention needs evidence.
        if (path in {"ordinary_rules", "risk_branches", "alert_rules"} and value == []
                and any(op.target == path and op.action == "ADD" for op in output.operations)):
            continue
        if any(_in_prefix(path, prefix) for prefix in touched):
            continue
        binding = bindings.get(path)
        if (path in invalid or binding is None or path not in current_values
                or type(current_values[path]) is not type(value) or current_values[path] != value
                or binding.origin not in {"SOURCE", "SOURCE_INTERPRETATION", "PRODUCT_CONTRACT"}):
            return False
    return True


def _scope_issues(output, base=None, current=None, *, historical=False):
    from trade_plan_monitor.ai.risk_withdrawal_scope import risk_scope_issue

    scope_issues = [] if historical else [f"{code}: risk_branches.{op.rule_id}"
                    for op in output.operations if (code := risk_scope_issue(op))]
    if output.inheritance_mode == "PREDECESSOR_PATCH":
        # Retention is the user's preparation contract, not a sentence the
        # current author must repeat. AI interprets intent; exact citations,
        # values, rule identity and the final human review remain independent.
        issues = list(scope_issues)
        from trade_plan_monitor.ai.semantic_validation import semantic_representation_issues

        issues.extend(f"{code}: {path}" for code, path in
                      semantic_representation_issues(output.draft))
        if output.scope == "UNRESOLVED" or any(
            op.intent == "AMBIGUOUS" for op in output.operations
        ) or (not historical and any(clause.semantic_role == "AMBIGUOUS"
                                     for clause in output.clauses)):
            issues.append("UPDATE_SOURCE_AMBIGUITY")
        if any((op.intent not in {"ASSERTED", "AMBIGUOUS"}
                and op.scope_assessment != "PARTIAL_RULE") or not op.rationale
               for op in output.operations):
            issues.append("UPDATE_CHANGE_ASSESSMENT_REQUIRED")
        return issues
    clauses = {c.clause_id: c for c in output.clauses}
    scope = [clauses[key].excerpt for key in output.scope_clause_ids]
    issues = list(scope_issues)
    if output.scope == "UNRESOLVED":
        issues.append("UPDATE_SCOPE_UNRESOLVED")
    elif output.scope == "FULL_REPLACEMENT":
        if not any(re.search(_REPLACEMENT, text, re.I) and not _AMBIGUOUS.search(text)
                   for text in scope):
            issues.append("UPDATE_REPLACEMENT_EVIDENCE_REQUIRED")
    elif output.retain_unmentioned and not (
        any(re.search(_RETAIN, text, re.I) and not _AMBIGUOUS.search(text) for text in scope)
        or _covered_retention(base, output, current)
    ):
        issues.append("UPDATE_RETENTION_EVIDENCE_REQUIRED")
    labels = {
        "position": r"仓位|持仓|position",
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
        if (historical and op.target == "risk_branches" and op.action == "REVOKE"
                and op.scope_assessment is None):
            # Pre-scope frozen approvals must remain readable with their exact
            # original mapping/hash. Current predecessor/composition validation
            # never uses historical=True and rejects the missing scope audit.
            continue
        if _restated_operation(op, base, output, current):
            continue
        text = " ".join(clauses[key].excerpt for key in op.clause_ids)
        target = re.escape(op.rule_id) if op.rule_id else labels[op.target]
        natural = _natural_rule_pattern(op, base)
        if natural:
            target = "(?:" + target + "|" + natural + ")"
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


def _pure_scope_clause(clause, output, base=None):
    """Only a complete narrow control sentence may be resolved without policy field paths."""
    if clause.disposition == "UNSUPPORTED" or clause.remainders or clause.exclusions:
        return False
    if output.inheritance_mode == "PREDECESSOR_PATCH":
        for op in output.operations:
            if (op.scope_assessment == "PARTIAL_RULE" and op.rationale
                    and clause.clause_id in op.clause_ids):
                return True  # Covered by the explicit non-executable scope limitation.
            if op.intent != "ASSERTED" or not op.rationale or clause.clause_id not in op.clause_ids:
                continue
            if op.action in {"REVOKE", "RETAIN"}:
                return True
            if base and op.action == "MODIFY":
                old, new = _operation_prefix(op, base.draft), _operation_prefix(op, output.draft)
                before = {p.removeprefix(old): v for p, v in semantic_values(base.draft).items()
                          if old and _in_prefix(p, old)}
                after = {p.removeprefix(new): v for p, v in semantic_values(output.draft).items()
                         if new and _in_prefix(p, new)}
                if before and before == after:
                    return True
        return False
    from trade_plan_monitor.ai.source_resolution import plain

    text = plain(clause.excerpt).strip(" 。；;.!\n\r\t")
    patterns = []
    if clause.clause_id in output.scope_clause_ids:
        patterns.extend((_REPLACEMENT, _RETAIN))
    for op in output.operations:
        if clause.clause_id in op.clause_ids and op.rule_id and op.action in {"REVOKE", "RETAIN"}:
            verb = r"撤销|取消|删除|revoke|remove" if op.action == "REVOKE" else r"保留|retain|keep"
            patterns.append(r"(?:" + verb + r")\s*(?:规则\s*)?" + re.escape(op.rule_id))
            natural = _natural_rule_pattern(op, base)
            if natural:
                patterns.append(r"(?:" + verb + r")\s*" + natural)
                patterns.append(natural + r"(?:正式)?(?:" + verb + r")")
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


def _blocking_warnings(output):
    """Do not turn already represented unknown conditions into extraction errors."""
    from trade_plan_monitor.domain.unified_plan_models import condition_leaves

    for warning in output.warnings:
        if not warning.material:
            continue
        if (warning.path == "levels.low_buy" and output.draft.levels is not None
                and output.draft.levels.low_buy is None):
            continue
        if (warning.path == "levels.risk_line_fen"
                and output.draft.levels is not None
                and output.draft.levels.risk_line_fen is None):
            continue
        match = re.fullmatch(r"ordinary_rules\[(\d+)\]\.condition", warning.path)
        if match and int(match[1]) < len(output.draft.ordinary_rules):
            condition = output.draft.ordinary_rules[int(match[1])].condition
            if condition is not None and any(
                leaf.type == "REVIEWED_FACT" for leaf in condition_leaves(condition)
            ):
                continue
        return True
    return False


def build_update_review(
    base: PlanCandidateReview,
    source: PreparationSource,
    output: PlanUpdateExtractionOutput,
    *,
    mapping: DailyMapping | None = None,
    historical: bool = False,
) -> PlanCandidateReview:
    """Recompute from a validated base; a mapping override is an explicit human correction."""
    base = PlanCandidateReview.model_validate(base.model_dump(mode="python"))
    source = PreparationSource.model_validate(source.model_dump(mode="python"))
    output = PlanUpdateExtractionOutput.model_validate(output.model_dump(mode="python"))
    context = context_from_review(base, base.evidence_hash)
    if (source.execution_available_at is None
            or context.available_at > source.execution_available_at):
        raise ValueError("predecessor context is unavailable at the current source")
    validate_update_evidence(output, source, context)
    materialized = materialize_plan_update(context.snapshot, output, historical=historical)
    current = (
        output.review(source.text)
        if mapping is None
        else build_daily_review(output.draft, mapping, source.text)
    )
    current_fields = _bound_fields(current.mapping, source)
    base_fields = {b.path: b for b in base.bindings}
    bindings = []
    issues = _scope_issues(output, base, current, historical=historical)
    if not historical:
        for operation in output.operations:
            if operation.scope_change is None:
                continue
            prefix = _operation_prefix(operation, materialized.draft)
            branch = next((r for r in materialized.draft.risk_branches
                           if risk_identity(r) == operation.rule_id), None)
            scope = None if branch is None else branch.holding_scope
            expected = ("BEFORE_TRADE_DATE" if operation.scope_change ==
                        "EXISTING_POSITIONS_ONLY" else "FROM_TRADE_DATE")
            previous = next((b for b in base.draft.risk_branches
                             if risk_identity(b) == operation.rule_id), None)
            expected_scope = (restrict_scope(previous.holding_scope if previous else None,
                expected, source.effective_trade_date) if source.effective_trade_date else None)
            if prefix is None or scope is None or scope != expected_scope:
                issues.append("UPDATE_SCOPE_DIRECTION_REQUIRED: risk_branches."
                              + operation.rule_id)
    selected = set()
    materialized_values = semantic_values(materialized.draft)
    for origin in materialized.origins:
        available = base_fields if origin.origin == "BASE" else current_fields
        if origin.origin == "CURRENT":
            selected.add(origin.original_path)
        bound = available.get(origin.original_path)
        # A section-level modification does not require re-quoting an unchanged
        # field. Keep its exact predecessor evidence when the current source has
        # no binding. Changed and nullified values still need current evidence.
        previous = base_fields.get(origin.path)
        if (bound is None and output.scope == "EXPLICIT_CHANGES"
                and origin.path.split(".", 1)[0] in {"position", "levels", "activation",
                                                      "monitoring", "execution_policy",
                                                      "trading_rules", "metadata"}
                and origin.origin == "CURRENT" and previous is not None
                and materialized_values.get(origin.path) == previous.binding.value
                and type(materialized_values.get(origin.path))
                is type(previous.binding.value)):
            bound = previous
            selected.discard(origin.original_path)
        if bound is None:
            issues.append("UPDATE_SOURCE_BINDING_REQUIRED: " + origin.path)
        else:
            bindings.append(bound.model_copy(update={"path": origin.path}))
    clauses = {c.clause_id: c for c in current.mapping.clauses}
    # A generic restatement of retained rules need not repeat their numbers.
    # Only a current literal amount/price can conflict with an inherited value.
    explicit_current_paths = set()
    if output.inheritance_mode == "PREDECESSOR_PATCH":
        for clause in output.clauses:
            if clause.semantic_role != "DIRECTIVE":
                continue
            for path in clause.paths:
                if not path.startswith(("levels.", "position.")):
                    continue  # Collection citations may also span unchanged sibling rules.
                shares = path.endswith(("_qty", ".quantity")) and re.search(
                    r"\d+\s*(?:股|shares\b)", clause.excerpt, re.I)
                price = path.endswith(("_fen", ".reference.value")) and re.search(
                    r"\d+\.\d+|\d+\s*(?:元|yuan\b)", clause.excerpt, re.I)
                if shares or price:
                    explicit_current_paths.add(path)
    for issue in current.issues:
        if issue.path.startswith("source."):
            clause = clauses.get(issue.path.removeprefix("source."))
            if clause is None or not _pure_scope_clause(clause, output, base):
                issues.append(f"{issue.code}: {issue.path}")
        elif (
            issue.path in selected | explicit_current_paths
            and issue.code == "DAILY_SOURCE_BINDING_REQUIRED"
        ):
            issues.append(f"{issue.code}: {issue.path}")
    issues.extend(f"{i['code']}: {i['path']}" for i in unified_plan_issues(materialized.draft))
    if unsupported_loop_source_spans(source.text):
        issues.append("LOOP_SOURCE_UNSUPPORTED")
    if output.assumptions or _blocking_warnings(output):
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
        available_at=source.execution_available_at,
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

    @classmethod
    def model_validate_json(cls, json_data, **kwargs):
        import json

        from trade_plan_monitor.ai.candidate_storage import unpack_evidence
        from trade_plan_monitor.ai.extraction import MAX_EXTRACTION_OUTPUT_BYTES

        encoded = json_data.encode("utf-8") if isinstance(json_data, str) else json_data
        if len(encoded) > MAX_EXTRACTION_OUTPUT_BYTES:
            raise ValueError("candidate JSON exceeds byte limit")
        value = json.loads(json_data)
        if isinstance(value, dict) and "storage_encoding" in value:
            json_data = canonical_json(unpack_evidence(value))
        return super().model_validate_json(json_data, **kwargs)

    def to_preparation_candidate(self):
        from trade_plan_monitor.ai.candidate_storage import pack_evidence

        payload = (canonical_json(pack_evidence(self.model_dump(mode="json")))
                   if self.extraction.output.inheritance_mode == "PREDECESSOR_PATCH"
                   else canonical_json(self))
        # A compact write must also be readable within the same expansion bound.
        # Invalid provider attribution is a processing correction, never a VALID
        # candidate that later fails only when the user tries to review it.
        type(self).model_validate_json(payload)
        return PreparationCandidateInput(
            payload_json=payload,
            evidence_hash=self.review.evidence_hash,
            validation="UNRESOLVED" if self.review.issues else "VALID",
            issues=self.review.issues,
        )


def materialize_extraction(base, base_hash, source, extraction, *, historical=False):
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
        review=build_update_review(base, source, extraction.output, historical=historical),
    )
