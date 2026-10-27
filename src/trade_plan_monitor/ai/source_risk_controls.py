"""Independent, finite whole-unit risk controls against an exact trusted parent."""

import json
import re
from collections import Counter

from pydantic import ValidationError

from trade_plan_monitor.ai.source_candidate_models import SourceCandidateAssurance
from trade_plan_monitor.ai.source_coverage_models import CoverageIssue
from trade_plan_monitor.ai.source_obligations import bounded_clauses
from trade_plan_monitor.ai.source_risk_control_models import (
    SourceRiskControl,
    SourceRiskControlAnalysis,
    SourceRiskControlSpan,
)
from trade_plan_monitor.ai.update_review import PlanCandidateReview
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.risk_scope import restrict_scope, risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedRiskBranch

_JSON = re.compile(r"operations\[(0|[1-9][0-9]?)\][ \t]*=[ \t]*(.+)")
_DIRECTIONS = {"EXISTING_POSITIONS_ONLY", "NEW_POSITIONS_ONLY"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate risk control key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite risk control JSON")


def _json_control(text):
    match = _JSON.fullmatch(text)
    if match is None or int(match[1]) > 63:
        return None
    try:
        value = json.loads(match[2], object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return None
    if (not isinstance(value, dict) or value.get("target") != "risk_branches"
            or not isinstance(value.get("rule_id"), str)):
        return None
    keys = {"target", "rule_id", "action", "scope_assessment"}
    if value.get("action") == "MODIFY":
        valid = (set(value) == keys | {"scope_change"}
                 and value.get("scope_assessment") == "PARTIAL_RULE"
                 and isinstance(value.get("scope_change"), str)
                 and value["scope_change"] in _DIRECTIONS)
    else:
        valid = (set(value) == keys and isinstance(value.get("action"), str)
                 and value["action"] in {"REVOKE", "RETAIN"}
                 and value.get("scope_assessment") == "ENTIRE_RULE")
    if not valid:
        return None
    return ("RISK_OPERATION_JSON_V1", value["rule_id"], value["action"],
            value.get("scope_change"), int(match[1]))


def _natural_control(text, draft):
    matches = []
    for row in draft.risk_branches:
        identifier = risk_identity(row)
        forms = {
            f"旧持仓继续执行风险规则{identifier}，新开仓位不适用该规则。":
                ("RISK_OLD_ONLY_ZH_V1", "MODIFY", "EXISTING_POSITIONS_ONLY"),
            f"风险规则{identifier}仅适用于旧持仓，不适用于新开仓位。":
                ("RISK_OLD_ONLY_ZH_V1", "MODIFY", "EXISTING_POSITIONS_ONLY"),
            f"Risk rule {identifier} continues for existing lots; exclude new holdings.":
                ("RISK_OLD_ONLY_EN_V1", "MODIFY", "EXISTING_POSITIONS_ONLY"),
            f"新开仓位继续执行风险规则{identifier}，旧持仓不适用该规则。":
                ("RISK_NEW_ONLY_ZH_V1", "MODIFY", "NEW_POSITIONS_ONLY"),
            f"Risk rule {identifier} continues for new holdings; exclude existing lots.":
                ("RISK_NEW_ONLY_EN_V1", "MODIFY", "NEW_POSITIONS_ONLY"),
            f"对全部新旧持仓一并废止风险规则{identifier}，今后不再执行该规则。":
                ("RISK_REVOKE_ALL_ZH_V1", "REVOKE", None),
            f"Revoke risk rule {identifier} for all existing and future holdings.":
                ("RISK_REVOKE_ALL_EN_V1", "REVOKE", None),
            f"保留风险规则{identifier}，新旧持仓均按原规则执行。":
                ("RISK_RETAIN_ALL_ZH_V1", "RETAIN", None),
            f"Retain risk rule {identifier} for all existing and future holdings.":
                ("RISK_RETAIN_ALL_EN_V1", "RETAIN", None),
            f"Do not revoke risk rule {identifier} for all existing and future holdings.":
                ("RISK_RETAIN_ALL_EN_V1", "RETAIN", None),
        }
        if text in forms:
            grammar, action, direction = forms[text]
            matches.append((grammar, identifier, action, direction, None))
    return matches[0] if len(matches) == 1 else None


def _units(text):
    """Keep unfinished preambles and quoted content attached to following lines."""
    pending, quotes = None, []
    openers = {"“": "”", "‘": "’", "「": "」", "『": "』", '"': '"', "'": "'"}
    for line in re.finditer(r"[^\r\n]+", text):
        start, end = line.start(), line.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start == end:
            continue
        if pending is None and not quotes and text[start:end].startswith("operations["):
            yield start, end
            continue
        cursor = start
        while cursor < end:
            character = text[cursor]
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
                while stop < end and text[stop] == "`":
                    stop += 1
                marker = text[cursor:stop]
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
                                  and (cursor + 1 == end or text[cursor + 1].isspace())):
                yield pending, cursor + 1
                pending = None
            cursor += 1
    if pending is not None:
        yield pending, len(text.rstrip())


def _derive(source, base, parent, parsed, start, end):
    grammar, identifier, action, direction, _ = parsed
    rows = [row for row in base.draft.risk_branches if risk_identity(row) == identifier]
    if len(rows) != 1:
        return None
    before = UnifiedRiskBranch.model_validate(rows[0].model_dump(mode="json"))
    derived = None
    if action == "MODIFY":
        if source.effective_trade_date is None:
            raise ValueError("partial risk applicability requires the confirmed effective day")
        mode = "BEFORE_TRADE_DATE" if direction == "EXISTING_POSITIONS_ONLY" else "FROM_TRADE_DATE"
        derived = restrict_scope(before.holding_scope, mode, source.effective_trade_date)
        after = before.model_copy(update={"holding_scope": derived})
    else:
        after = before if action == "RETAIN" else None
    previous = before.model_dump(mode="json")
    final = None if after is None else after.model_dump(mode="json")
    return SourceRiskControl.build(grammar_id=grammar, source_id=source.source_id,
        source_hash=source.source_hash, source_binding_hash=source.binding_hash,
        effective_trade_date=source.effective_trade_date, base_review_hash=base.evidence_hash,
        parent_assurance_hash=parent.evidence_hash, start=start, end=end,
        excerpt=source.text[start:end], rule_id=identifier, action=action,
        scope_assessment="PARTIAL_RULE" if action == "MODIFY" else "ENTIRE_RULE",
        scope_change=direction, before=before, after=after, derived_holding_scope=derived,
        before_hash=daily_hash("source-operation-value-v1", previous),
        after_hash=daily_hash("source-operation-value-v1", final),
        preserved_policy_hash=daily_hash("source-risk-policy-v1",
            {key: value for key, value in previous.items() if key != "holding_scope"}))


def derive_source_risk_control(source, base_review, verified_parent, *, grammar_id,
                               rule_id, action, scope_change, start, end):
    """Build value evidence after a caller independently recognizes a complete form.

    This is not a recognizer or an authority boundary. Callers must validate the
    exact source/parent and retain all other source meanings independently.
    """
    return _derive(source, base_review, verified_parent,
                   (grammar_id, rule_id, action, scope_change, None), start, end)


def parse_source_risk_controls(source, base_review, verified_parent):
    """Parse evidence only; upstream owns parent authentication and final authority.

    No AI proposal/role/reason is accepted. Unknown text, including mixed table
    rows, is retained. Complete source-to-predicate coverage is a separate stage.
    """
    source = PreparationSource.model_validate_json(source.model_dump_json())
    bounded_clauses(source.text)
    base = PlanCandidateReview.model_validate_json(base_review.model_dump_json())
    parent = SourceCandidateAssurance.model_validate_json(verified_parent.model_dump_json())
    if (parent.binding.review_evidence_hash != base.evidence_hash
            or parent.content_hash != daily_draft_content_sha256(base.draft)
            or parent.binding.source_id != base.source_id
            or parent.binding.source_binding_hash != base.source_hash):
        raise ValueError("risk source control differs from its exact verified parent")
    controls, unresolved, issues, ordinals = [], [], [], {}

    def unknown(start, end):
        for cursor in range(start, end, 512):
            stop = min(cursor + 512, end)
            unresolved.append(SourceRiskControlSpan(source_hash=source.source_hash,
                start=cursor, end=stop, excerpt=source.text[cursor:stop]))
            if len(unresolved) > 4096:
                raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")

    if not parent.coverage_complete:
        issues.append(CoverageIssue(code="SOURCE_COVERAGE_REQUIRED",
            message="Risk source controls require a complete current predecessor proof."))
    for start, end in _units(source.text):
        text = source.text[start:end]
        parsed = None if len(text) > 512 or not parent.coverage_complete else (
            _json_control(text) or _natural_control(text, base.draft))
        if parsed is None:
            unknown(start, end)
            continue
        try:
            control = _derive(source, base, parent, parsed, start, end)
        except ValueError as error:
            limit = "SOURCE_COVERAGE_LIMIT_EXCEEDED"
            if str(error) == limit or isinstance(error, ValidationError) and any(
                str(row.get("ctx", {}).get("error")) == limit
                for row in error.errors(include_input=False, include_url=False)
            ):
                raise ValueError(limit) from error
            unknown(start, end)
            issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH", path="risk_branches",
                start=start, end=end,
                message="The exact risk applicability restriction could not be derived."))
            continue
        if control is None:
            unknown(start, end)
            continue
        controls.append(control)
        if len(controls) > 64:
            raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        if parsed[4] is not None:
            ordinals.setdefault(parsed[4], []).append(control.control_id)
    counts = Counter(row.rule_id for row in controls)
    conflict = {row.control_id for row in controls if counts[row.rule_id] > 1}
    conflict.update(control_id for ids in ordinals.values() if len(ids) > 1 for control_id in ids)
    if conflict:
        kept = []
        for row in controls:
            if row.control_id in conflict:
                unknown(row.start, row.end)
            else:
                kept.append(row)
        controls = kept
        issues.append(CoverageIssue(code="SOURCE_RELATION_MISMATCH",
            message="Duplicate or contradictory risk controls require explicit resolution."))
    return SourceRiskControlAnalysis.build(source_id=source.source_id,
        source_hash=source.source_hash, source_binding_hash=source.binding_hash,
        source_length=len(source.text), effective_trade_date=source.effective_trade_date,
        parent_assurance_hash=parent.evidence_hash, base_review_hash=base.evidence_hash,
        controls=tuple(controls), unresolved=tuple(sorted(unresolved, key=lambda row: row.start)),
        issues=tuple(issues))
