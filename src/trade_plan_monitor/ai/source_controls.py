"""Finite whole-statement controls resolved solely against the trusted predecessor."""

import json
import re
from collections import Counter
from decimal import Decimal

from trade_plan_monitor.ai.source_candidate_models import SourceCandidateAssurance
from trade_plan_monitor.ai.source_context import positive_context
from trade_plan_monitor.ai.source_control_models import (
    SourceControl,
    SourceControlAnalysis,
    SourceControlSpan,
)
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_obligations import bounded_clauses, declarations
from trade_plan_monitor.ai.source_position_directives import parse_position_directive
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash

_JSON_CONTROL = re.compile(r"operations\[(0|[1-9][0-9]?)\][ \t]*=[ \t]*(.+)")
_ZONE_CONTROL = re.compile(
    r"原([0-9]+(?:\.[0-9]{1,2})?)[—–-]([0-9]+(?:\.[0-9]{1,2})?)低吸计划(?:正式)?取消。"
)
_SCALARS = {"activation", "levels", "position", "monitoring", "execution_policy",
            "trading_rules", "metadata"}
_BUSINESS = {
    "取消原来的买入规则。": ("REVOKE", "BUY"),
    "取消原买入指令。": ("REVOKE", "BUY"),
    "撤下原来的入场指令。": ("REVOKE", "BUY"),
    "此前那笔买单就此作废。": ("REVOKE", "BUY"),
    "上一版的买入安排就此作废。": ("REVOKE", "BUY"),
    "取消原来的卖出规则。": ("REVOKE", "SELL"),
    "不要撤销原买入指令。": ("RETAIN", "BUY"),
    "旧入场安排照常有效。": ("RETAIN", "BUY"),
}
_PLAN = {
    "今日没有新增指令。": "NO_NEW_INSTRUCTIONS",
    "今日休市，没有新增指令。": "NO_NEW_INSTRUCTIONS",
    "No new instructions today.": "NO_NEW_INSTRUCTIONS",
    "其余规则保留。": "RETAIN_UNMENTIONED",
    "其余规则不变。": "RETAIN_UNMENTIONED",
    "retain unmentioned.": "RETAIN_UNMENTIONED",
}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate source control JSON key")
        value[key] = item
    return value


def _invalid_number(value):
    raise ValueError("nonfinite source control JSON")


def _before(target, rule_id, draft):
    if target in {"ordinary_rules", "alert_rules"}:
        rows = [row for row in getattr(draft, target) if row.rule_id == rule_id]
        if len(rows) != 1:
            return None
        row = rows[0]
        return (row.side if target == "ordinary_rules" else "ALERT",
                row.model_dump(mode="json"))
    if target in _SCALARS and rule_id is None:
        value = getattr(draft, target)
        return "PLAN", value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return None


def _json_control(text, draft):
    match = _JSON_CONTROL.fullmatch(text)
    if match is None or int(match[1]) > 63:
        return None
    try:
        value = json.loads(match[2], object_pairs_hook=_unique_object,
                           parse_constant=_invalid_number)
    except (ValueError, RecursionError):
        return None
    if (not isinstance(value, dict) or set(value) != {"target", "rule_id", "action"}
            or not isinstance(value["action"], str) or value["action"] not in {"REVOKE", "RETAIN"}
            or not isinstance(value["target"], str)
            or value["rule_id"] is not None and not isinstance(value["rule_id"], str)):
        return None
    before = _before(value["target"], value["rule_id"], draft)
    if before is None or value["action"] == "REVOKE" and value["target"] in _SCALARS:
        return None
    return "EXACT_OPERATION_JSON_V1", value["action"], value["target"], value["rule_id"], before


def _natural_control(text, draft):
    if text in _PLAN:
        return "EXACT_PLAN_CONTROL_V1", _PLAN[text], "plan", None, (
            "PLAN", draft.model_dump(mode="json"))
    if text in _BUSINESS:
        action, side = _BUSINESS[text]
        rows = [row for row in draft.ordinary_rules if row.side == side]
        if len(rows) != 1:
            return None
        row = rows[0]
        return ("UNIQUE_ORDINARY_CONTROL_V1", action, "ordinary_rules", row.rule_id,
                (side, row.model_dump(mode="json")))
    matches = []
    for target in ("ordinary_rules", "alert_rules"):
        for row in getattr(draft, target):
            identifier = row.rule_id
            forms = {
                f"撤销规则{identifier}。": "REVOKE", f"取消规则{identifier}。": "REVOKE",
                f"Revoke rule {identifier}.": "REVOKE", f"保留规则{identifier}。": "RETAIN",
                f"Retain rule {identifier}.": "RETAIN",
                f"Do not revoke rule {identifier}.": "RETAIN",
            }
            if text in forms:
                matches.append(("EXACT_RULE_CONTROL_V1", forms[text], target, identifier,
                                _before(target, identifier, draft)))
    # A risk with the same ID is a competing interpretation even though risk
    # withdrawal itself is deliberately unsupported by this registry.
    from trade_plan_monitor.domain.risk_scope import risk_identity

    if any(text in {f"撤销规则{risk_identity(row)}。", f"取消规则{risk_identity(row)}。",
                    f"Revoke rule {risk_identity(row)}.", f"保留规则{risk_identity(row)}。",
                    f"Retain rule {risk_identity(row)}.",
                    f"Do not revoke rule {risk_identity(row)}."} for row in draft.risk_branches):
        return None
    if len(matches) == 1:
        return matches[0]
    if matches or (match := _ZONE_CONTROL.fullmatch(text)) is None:
        return None
    rows = [row for row in draft.ordinary_rules if row.side == "BUY"]
    zone = None if draft.levels is None else draft.levels.low_buy
    if len(rows) != 1 or rows[0].zone != "LOW_BUY" or zone is None or (
        Decimal(match[1]) * 100, Decimal(match[2]) * 100
    ) != (zone.low_fen, zone.high_fen):
        return None
    row = rows[0]
    return ("EXACT_LOW_BUY_CONTROL_V1", "REVOKE", "ordinary_rules", row.rule_id,
            ("BUY", row.model_dump(mode="json")))


def _units(source):
    pending, quotes = None, []
    openers = {"“": "”", "‘": "’", "「": "」", "『": "』", '"': '"', "'": "'"}
    for line in re.finditer(r"[^\r\n]+", source):
        start, end = line.start(), line.end()
        while start < end and source[start].isspace():
            start += 1
        while end > start and source[end - 1].isspace():
            end -= 1
        if start == end:
            continue
        literal = source[start:end]
        position = (parse_position_directive(literal) if pending is None and not quotes else None)
        if position is not None:
            yield start + position.start, start + position.cap_end
            yield start + position.tail_start, start + position.end
            continue
        # Complete declaration/context lines are atomic. An unfinished natural
        # preamble still owns subsequent lines, including otherwise valid JSON.
        if pending is None and not quotes and (literal.startswith("operations[")
                or declarations(literal) or positive_context(literal)):
            yield start, end
            continue
        cursor = start
        while cursor < end:
            character = source[cursor]
            if pending is None:
                if character.isspace():
                    cursor += 1
                    continue
                pending = cursor
            if quotes and character == "\\":
                cursor += 2
                continue
            if character == "`":
                stop = cursor + 1
                while stop < end and source[stop] == "`":
                    stop += 1
                marker = source[cursor:stop]
                if quotes and quotes[-1] == marker:
                    quotes.pop()
                else:
                    quotes.append(marker)
                cursor = stop
                continue
            if quotes and character == quotes[-1]:
                quotes.pop()
            elif character in openers:
                quotes.append(openers[character])
            elif not quotes and (character in "。！？!?" or character == "."
                                  and (cursor + 1 == end or source[cursor + 1].isspace())):
                boundary = cursor + 1
                if source[boundary:boundary + 2] == "**":
                    boundary += 2
                yield pending, boundary
                pending, cursor = None, boundary
                continue
            cursor += 1
    if pending is not None:
        yield pending, len(source.rstrip())


def parse_source_controls(source, base_review, verified_parent):
    """Recognize exact source controls; a proposed AI operation is never an input."""
    from trade_plan_monitor.ai.update_review import PlanCandidateReview

    text = source if isinstance(source, str) else source.text
    bounded_clauses(text)
    base = PlanCandidateReview.model_validate_json(base_review.model_dump_json())
    parent = SourceCandidateAssurance.model_validate_json(verified_parent.model_dump_json())
    if (parent.binding.review_evidence_hash != base.evidence_hash
            or parent.content_hash != daily_draft_content_sha256(base.draft)
            or parent.binding.source_id != base.source_id
            or parent.binding.source_binding_hash != base.source_hash):
        raise ValueError("source control predecessor differs from its verified exact parent")
    source_hash = scope_hash(text)
    controls, unresolved, issues, ordinals = [], [], [], {}

    def unknown(start, end):
        for cursor in range(start, end, 512):
            stop = min(cursor + 512, end)
            unresolved.append(SourceControlSpan(source_hash=source_hash,
                start=cursor, end=stop, excerpt=text[cursor:stop]))

    for start, end in _units(text):
        while start < end and text[start].isspace():
            start += 1
        if start == end:
            continue
        excerpt = text[start:end]
        normalized = excerpt[2:-2] if excerpt.startswith("**") and excerpt.endswith("**") else (
            excerpt)
        resolved = None if len(excerpt) > 512 else (
            _json_control(normalized, base.draft) or _natural_control(normalized, base.draft))
        if resolved is None:
            unknown(start, end)
            continue
        grammar, action, target, rule_id, (scope, before) = resolved
        control = SourceControl.build(source_hash=source_hash, start=start, end=end,
            excerpt=excerpt, grammar_id=grammar, action=action, target=target, rule_id=rule_id,
            scope=scope, parent_assurance_hash=parent.evidence_hash,
            before_hash=daily_hash("source-operation-value-v1", before))
        controls.append(control)
        if grammar == "EXACT_OPERATION_JSON_V1":
            ordinal = int(_JSON_CONTROL.fullmatch(normalized)[1])
            ordinals.setdefault(ordinal, []).append(control.control_id)
    counts = Counter((row.target, row.rule_id) for row in controls if row.target != "plan")
    conflict = {row.control_id for row in controls if row.target != "plan"
                and counts[row.target, row.rule_id] > 1}
    conflict.update(control_id for ids in ordinals.values() if len(ids) > 1 for control_id in ids)
    if any(row.action == "NO_NEW_INSTRUCTIONS" for row in controls) and any(
        row.action == "REVOKE" for row in controls
    ):
        conflict.update(row.control_id for row in controls
                        if row.action in {"NO_NEW_INSTRUCTIONS", "REVOKE"})
    if conflict:
        kept = []
        for row in controls:
            if row.control_id in conflict:
                unknown(row.start, row.end)
            else:
                kept.append(row)
        controls = kept
        issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
            message="Duplicate or contradictory source controls require explicit resolution."))
    if len(controls) > 64:
        raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
    return SourceControlAnalysis.build(source_hash=source_hash, source_length=len(text),
        parent_assurance_hash=parent.evidence_hash, base_review_hash=base.evidence_hash,
        parent_coverage_complete=parent.coverage_complete, controls=tuple(controls),
        unresolved=tuple(sorted(unresolved, key=lambda row: row.start)), issues=tuple(issues))
