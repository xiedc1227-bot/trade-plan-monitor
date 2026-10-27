"""Oversized or inexact meaning remains an inspectable blocking source."""

import json

import pytest
from tests.unit.test_source_coverage_baseline import _baseline

from trade_plan_monitor.ai.daily_review import DailyClause
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_obligations import declarations


def test_large_unknown_declaration_returns_a_limit_blocker_instead_of_losing_the_candidate():
    draft, source, mapping = _baseline()
    text = "unknown = " + json.dumps("x" * 9000)
    changed = source + "\n" + text
    extra = server_source_clauses(changed)[len(mapping.clauses):]
    mapping = mapping.model_copy(update={"clauses": (*mapping.clauses, *(
        DailyClause.model_validate(row.model_dump() | dict(disposition="CONTEXT", paths=(),
            semantic_role="COMMENTARY", reason="Untrusted context")) for row in extra
    ))})
    result = assess_source_coverage(draft, mapping, changed)
    assert not result.coverage_complete
    assert "SOURCE_COVERAGE_LIMIT_EXCEEDED" in {row.code for row in result.issues}
    assert result.authority_granted is False
    assert all(row.excerpt == changed[row.start:row.end] for row in result.obligations)


@pytest.mark.parametrize("number", ["1e999", "1e-999", "9007199254740993.0"])
def test_source_number_cannot_overflow_underflow_or_round_into_another_meaning(number):
    assert declarations("unknown = " + number) == ()


def test_excessive_source_path_stays_unrecognized():
    assert declarations("a" * 513 + " = 0") == ()
