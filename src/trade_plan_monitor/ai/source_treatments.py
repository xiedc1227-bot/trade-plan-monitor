"""Exact registered exclusions and explicit missing-value human supplements."""

import re
from dataclasses import dataclass
from datetime import date

from trade_plan_monitor.ai.source_obligations import MISSING, value_at
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
