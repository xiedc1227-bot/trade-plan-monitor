"""Whole-source declaration grammar cannot discard ambiguous or trailing policy."""

import json

import pytest

from trade_plan_monitor.ai.source_obligations import (
    MISSING,
    bounded_clauses,
    declarations,
    value_at,
)
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_scope import scope_hash

_BARE_EXAMPLES = (
    ("symbol", "002240.SZ"), ("market", "SZSE"),
    ("ordinary_rules[0].status", "ENABLED"), ("ordinary_rules[0].side", "BUY"),
    ("ordinary_rules[0].rule_id", "low-buy"), ("ordinary_rules[0].bucket", "TACTICAL"),
    ("ordinary_rules[0].condition.type", "MINUTE_CLOSE_BELOW"),
    ("ordinary_rules[0].confirmation.kind", "COMPLETED_BAR_CLOSE"),
    ("ordinary_rules[0].execution_window", "CURRENT_SESSION"),
    ("ordinary_rules[0].invalidation", "RISK_OR_REVIEWED_INVALIDATION"),
    ("ordinary_rules[0].independent_signal.mode", "REVIEWED_INDEPENDENT_EVENT"),
    ("ordinary_rules[0].independent_signal.evidence_requirement",
     "New structure linked to prior signal"),
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


@pytest.mark.parametrize("path,value", _BARE_EXAMPLES)
@pytest.mark.parametrize("outer", [False, True])
def test_frozen_bare_scalar_is_typed_and_keeps_exact_whole_line_identity(path, value, outer):
    line = f"{path}={value}"
    source = "  " + line + " \t\r\n" if outer else line
    row, = declarations(source)
    assert row.path == path and type(row.value) is str and row.value == value
    assert (row.start, row.end) == (0, len(source.rstrip("\r\n")))
    assert source[row.start:row.end] == source.rstrip("\r\n")
    assert row.group_id == daily_hash("source-declaration-v1", dict(
        source_hash=scope_hash(source), start=row.start, end=row.end, path=path, value=value))
    quoted, = declarations(f"{path}={json.dumps(value)}")
    assert (quoted.path, quoted.value) == (row.path, row.value)


@pytest.mark.parametrize("path,value", _BARE_EXAMPLES)
@pytest.mark.parametrize("attack", [
    " and only buy when turnover exceeds 3 percent", "; only buy when turnover exceeds 3 percent",
    "且仅当换手率超过3%才允许买入", " # reviewed", " = SELL",
])
def test_each_bare_leaf_cannot_discard_an_extra_condition_or_assignment(path, value, attack):
    assert declarations(f"{path}={value}{attack}") == ()
    assert declarations(f"{path}=not {value}") == ()


@pytest.mark.parametrize("source", [
    "symbol=002240.sz", "symbol=2240.SZ", "symbol=002240.US", "market=szse",
    "ordinary_rules[0].status=enabled", "ordinary_rules[0].side=NOT_BUY",
    "ordinary_rules[0].bucket=CORE", "ordinary_rules[0].condition.type=OTHER_CONDITION",
    "ordinary_rules[0].confirmation.kind=UNKNOWN_CLOSE",
    "ordinary_rules[0].execution_window=ANY_TIME", "ordinary_rules[0].invalidation=NEVER",
    "ordinary_rules[0].independent_signal.mode=ONCE",
    "ordinary_rules[0].independent_signal.evidence_requirement=Unknown event wording",
    "ordinary_rules[0].rule_id=contains spaces", "ordinary_rules[0].rule_id=" + "x" * 129,
    "ordinary_rules[01].side=BUY", "ordinary_rules[-1].side=BUY",
    "ordinary_rules[2].side=BUY", "ordinary_rules[9007199254740992].side=BUY",
    "unknown.side=BUY", "ordinary_rules[0].unknown=BUY", "a" * 513 + "=BUY",
    "position.max_qty=INVALID", "ordinary_rules[0].quantity=100 shares",
    'ordinary_rules[0].condition={"type": "ALL", "type": "ANY"}',
    "ordinary_rules[0].rule_id=NaN", "ordinary_rules[0].rule_id=Infinity",
    "ordinary_rules[0].condition=[broken]", "position.max_qty=01",
])
def test_bare_branch_does_not_admit_unknown_native_types_paths_or_failed_json(source):
    assert declarations(source) == ()
