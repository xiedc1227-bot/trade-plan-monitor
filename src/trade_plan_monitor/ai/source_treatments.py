"""Exact registered exclusions and explicit missing-value human supplements."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from trade_plan_monitor.ai.source_coverage_models import SourceObligation
from trade_plan_monitor.ai.source_obligations import MISSING, declared_value_at, value_at
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_scope import excluded_spans


@dataclass(frozen=True)
class SourcePart:
    clause_id: str
    start: int
    end: int
    excerpt: str
    excluded: bool = False
    limited: bool = False


def source_parts(source, clauses):
    """Partition from server-owned fragments; unknown remainders retain exact text."""
    result = []
    for clause in clauses:
        spans = excluded_spans(source, clause)
        parts, cursor = [], clause.start
        for start, end in (*spans, (clause.end, clause.end)):
            remainder = source[cursor:start]
            if remainder.strip(" 。；，,;、.!?！？\n\r\t"):
                parts.append(SourcePart(clause.clause_id, cursor, start, remainder))
            if start < end:
                parts.append(SourcePart(clause.clause_id, start, end, source[start:end], True))
            cursor = end
        if len(parts) > 64:
            parts = [SourcePart(clause.clause_id, clause.start, clause.end,
                source[clause.start:clause.end], limited=True)]
        result.extend(parts)
    if len(result) > 4096:
        return tuple(SourcePart(row.clause_id, row.start, row.end,
            source[row.start:row.end], limited=True) for row in clauses)
    return tuple(result)


def missing_value_supplement(declaration, draft, mapping):
    """A null parameter can be supplied; a known source value cannot be waived."""
    if declaration.value is not None:
        return None
    binding = next((row for row in mapping.bindings if row.path == declaration.path), None)
    if binding is None or binding.origin != "HUMAN_SUPPLEMENT" or binding.clause_ids:
        return None
    supplement = next((row for row in mapping.supplements
                       if row.supplement_id == binding.supplement_id), None)
    actual = value_at(draft.executable_payload(), declaration.path)
    if (supplement is None or actual is MISSING or actual is None
            or supplement.candidate_content_hash != mapping.candidate_content_hash
            or supplement.path != binding.path
            or canonical(actual) != canonical(binding.value)
            or canonical(actual) != canonical(supplement.value)):
        return None
    return supplement


def deadline_supplement(text, draft, mapping):
    """Retain the existing narrowly scoped explicit deadline conversion route."""
    match = re.fullmatch(r"本规则有效至(\d{4}-\d{2}-\d{2})。", text)
    if match is None or len(draft.ordinary_rules) != 1:
        return None
    try:
        date.fromisoformat(match[1])
    except ValueError:
        return None
    path = "ordinary_rules[0].validity.mode"
    binding = next((row for row in mapping.bindings if row.path == path), None)
    if (binding is None or binding.origin != "HUMAN_SUPPLEMENT" or binding.clause_ids
            or binding.value != "PLAN_ACTIVE"):
        return None
    supplement = next((row for row in mapping.supplements
                       if row.supplement_id == binding.supplement_id), None)
    if (supplement is None or supplement.path != path or supplement.value != "PLAN_ACTIVE"
            or supplement.candidate_content_hash != mapping.candidate_content_hash
            or value_at(draft.executable_payload(), path) != "PLAN_ACTIVE"
            or text not in supplement.reason
            or re.search(r"改为持续有效|convert to PLAN_ACTIVE", supplement.reason) is None):
        return None
    return supplement


def buy_suspension_parts(source, parts):
    """Join only a complete bounded guard sentence; preserve every unknown remainder.

    The existing canonical splitter separates Chinese/English commas. A persistent
    instruction therefore has one source-owned obligation anchored at its first
    clause, rather than treating its consequence/recovery as unrelated background.
    """
    from dataclasses import replace

    result = []
    index = 0
    while index < len(parts):
        part = parts[index]
        matched = None
        for last in range(index, min(index + 64, len(parts))):
            end = parts[last].end
            text = source[part.start:end]
            if (len(text) > 512 or "\n" in text or "\r" in text
                    or parts[last].excluded or parts[last].limited):
                break
            if _buy_suspension_meaning(text) is not None:
                matched = last, text
        if matched is None:
            result.append(part)
            index += 1
            continue
        last, text = matched
        split = part.start + len(text)
        result.append(replace(part, end=split, excerpt=text))
        index = last + 1
    return tuple(result)


def buy_suspension_obligation(part, source_hash):
    """Recognize only complete finite durable instructions, independently of the candidate.

    Unknown text/tails remain ordinary unresolved source obligations. In particular,
    waiting for a bottom is not asserted to mean reviewed activation without a human
    clarification of the fixed PBS scope/recovery interpretation.
    """
    meaning = _buy_suspension_meaning(part.excerpt)
    if meaning is None:
        return None
    return SourceObligation.build(source_hash=source_hash, clause_id=part.clause_id,
        start=part.start, end=part.end, excerpt=part.excerpt, kind="RELATION", scope="BUY",
        state="UNRESOLVED", semantics_json=canonical(meaning), paths=())


def _buy_suspension_meaning(text):
    text = text.replace("**", "").strip()
    text = re.sub(r"^(?:[0-9]+\.\s*|⑤\s*)", "", text)
    chinese = re.fullmatch(
        r"(?:如果)?再次跌破(?P<price>[0-9]+\.[0-9]{2})(?:创新低)?"
        r"(?:后|，则|：)(?:继续空仓)(?:，等待(?:新的|新)底部结构)?[。，；;]?", text)
    english = re.fullmatch(
        r"After one completed (?:(?P<period>5)-minute )?close (?:strictly )?below "
        r"(?P<price>[0-9]+\.[0-9]{2}), prohibit all further BUY under this plan until "
        r"exact activation of an independently reviewed replacement\.", text)
    match = chinese or english
    if match is None:
        return None
    return dict(treatment="PERSISTENT_BUY_SUSPENSION", price_fen=int(Decimal(match["price"])*100),
        timeframe_minutes=5 if english is not None and english["period"] else None,
        scope_recovery=("ALL_PLAN_BUY_REVIEWED_REPLACEMENT_ONLY" if english is not None
                        else "PENDING_NEW_STRUCTURE_REQUIRES_CLARIFICATION"))


def buy_suspension_coverage(obligation, draft, mapping, parsed, *, allow_clarifications):
    """Only this obligation's exact human supplements may supply its absent meaning."""
    import json

    from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256

    guard = getattr(draft, "buy_suspension", None)
    if draft.schema_version != 10 or guard is None:
        return "SOURCE_BUY_SUSPENSION_REQUIRED", ()
    meaning = json.loads(obligation.semantics_json)
    payload = draft.executable_payload()
    paths = ("buy_suspension.condition.type", "buy_suspension.condition.timeframe_minutes",
             "buy_suspension.condition.price_fen", "buy_suspension.effective_from")
    actual = {path: value_at(payload, path) for path in paths}
    if (actual[paths[0]] != "MINUTE_CLOSE_BELOW" or actual[paths[1]] != 5
            or actual[paths[2]] != meaning["price_fen"]):
        return "SOURCE_BUY_SUSPENSION_REQUIRED", ()
    supplements = []
    for supplement in mapping.supplements if allow_clarifications else ():
        if (supplement.source_hash != obligation.source_hash
                or supplement.obligation_id != obligation.obligation_id
                or supplement.candidate_content_hash != daily_draft_content_sha256(draft)
                or supplement.path not in actual
                or canonical(supplement.value) != canonical(actual[supplement.path])):
            continue
        binding = next((b for b in mapping.bindings if b.path == supplement.path), None)
        if (binding is not None and binding.origin == "HUMAN_SUPPLEMENT"
                and binding.supplement_id == supplement.supplement_id and not binding.clause_ids
                and canonical(binding.value) == canonical(supplement.value)):
            supplements.append(supplement)
    provided = {s.path for s in supplements}
    for path in (paths[1], paths[3]):
        declared = declared_value_at(parsed, path)
        if path == paths[1] and meaning["timeframe_minutes"] is not None:
            declared = meaning["timeframe_minutes"]
        if declared is not MISSING and declared is not None:
            if canonical(declared) != canonical(actual[path]):
                return "SOURCE_BUY_SUSPENSION_REQUIRED", ()
        elif path not in provided or actual[path] is None or actual[path] is MISSING:
            return "SOURCE_BUY_SUSPENSION_CLARIFICATION_REQUIRED", ()
    if meaning["scope_recovery"] == "PENDING_NEW_STRUCTURE_REQUIRES_CLARIFICATION" and not any(
            s.buy_suspension_clarification == "ALL_PLAN_BUY_REVIEWED_REPLACEMENT_ONLY"
            for s in supplements):
        return "SOURCE_BUY_SUSPENSION_CLARIFICATION_REQUIRED", ()
    return None, tuple(supplements)
