"""Whole-source declaration grammar cannot discard ambiguous or trailing policy."""

import pytest

from trade_plan_monitor.ai.source_obligations import (
    MISSING,
    bounded_clauses,
    declarations,
    value_at,
)


def test_declaration_keeps_the_entire_json_meaning_and_original_span():
    source = '  ordinary_rules[0].condition = {"type": "ALL", "conditions": []}\r\n'
    row, = declarations(source)
    assert row.path == "ordinary_rules[0].condition"
    assert row.value == {"type": "ALL", "conditions": []}
    assert source[row.start:row.end] == source.rstrip("\r\n")


@pytest.mark.parametrize("source", [
    'position = {"max_qty": 300, "max_qty": 400}',
    'position.max_qty = 300 and only buy when turnover exceeds 3 percent',
    'position.max_qty = NaN',
    'position.max_qty = 300; only buy when turnover exceeds 3 percent',
])
def test_ambiguous_or_partially_consumed_declaration_remains_unrecognized(source):
    assert declarations(source) == ()


def test_source_bound_preserves_originals_and_rejects_clause_overflow():
    with pytest.raises(ValueError, match="LIMIT_EXCEEDED"):
        bounded_clauses("\n".join("x" for _ in range(513)))
    with pytest.raises(ValueError, match="bounded"):
        bounded_clauses("x" * 150001)


def test_path_reader_is_structural_and_never_evaluates_source():
    assert value_at({"ordinary_rules": [{"quantity": 100}]},
                    "ordinary_rules[0].quantity") == 100
    assert value_at({}, "__import__('os').system('anything')") is MISSING
