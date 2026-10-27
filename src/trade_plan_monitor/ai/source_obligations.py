"""Finite source declarations and exact spans, independent of provider labels."""

import json
import re
from dataclasses import dataclass

from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_scope import scope_hash

_PATH = re.compile(r"[A-Za-z_]\w*(?:(?:\.[A-Za-z_]\w*)|(?:\[\d+\]))*")
_DECLARATION = re.compile(r"\s*(" + _PATH.pattern + r")\s*=\s*(.+?)\s*\Z")
MISSING = object()


@dataclass(frozen=True)
class SourceDeclaration:
    start: int
    end: int
    path: str
    value: object
    group_id: str


def bounded_clauses(source):
    if not isinstance(source, str) or not source.strip() or len(source) > 150_000:
        raise ValueError("source must be nonblank bounded text")
    clauses = server_source_clauses(source)
    if len(clauses) > 512:
        raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")
    return clauses


def _invalid_number(value):
    raise ValueError("nonfinite source JSON")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate source JSON key")
        result[key] = value
    return result


def declarations(source):
    """Consume whole path=JSON lines; any unexplained suffix stays unrecognized."""
    digest = scope_hash(source)
    result = []
    for line in re.finditer(r"[^\r\n]+", source):
        match = _DECLARATION.fullmatch(line.group())
        if match is None:
            continue
        try:
            value = json.loads(match[2], parse_constant=_invalid_number,
                               object_pairs_hook=_unique_object)
        except (ValueError, RecursionError):
            continue
        result.append(SourceDeclaration(line.start(), line.end(), match[1], value,
            daily_hash("source-declaration-v1", dict(source_hash=digest,
                start=line.start(), end=line.end(), path=match[1], value=value))))
    return tuple(result)


def value_at(payload, path):
    if _PATH.fullmatch(path) is None:
        return MISSING
    value = payload
    try:
        for token in re.findall(r"[A-Za-z_]\w*|\[\d+\]", path):
            value = value[int(token[1:-1])] if token.startswith("[") else value[token]
    except (KeyError, IndexError, TypeError):
        return MISSING
    return value


def source_scope(path, payload):
    match = re.match(r"ordinary_rules\[(\d+)\]", path)
    if match:
        side = value_at(payload, f"ordinary_rules[{match[1]}].side")
        return side if side in {"BUY", "SELL"} else "UNKNOWN"
    if path.startswith("risk_branches"):
        return "RISK"
    if path.startswith("alert_rules"):
        return "ALERT"
    return "PLAN"
