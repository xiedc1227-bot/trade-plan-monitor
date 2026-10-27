"""Natural position directives cross the real full-wire/current-review boundary."""

import json
import sqlite3
from contextlib import closing

import pytest
from tests.integration.preparation_review_current_fixtures import current_collection
from tests.integration.test_plan_preparation_review import NOW, collection_review_command
from tests.unit.test_plan_update_bindings import current_update
from tests.unit.test_source_change_assurance import _NOW, _assemble, _parent
from tests.unit.test_source_change_composition import _assess

from trade_plan_monitor.ai.source_controls import parse_source_controls
from trade_plan_monitor.ai.source_obligations import declarations
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.preparation_current_assurance import (
    read_current_assurance,
    require_current_reviewed_preparation,
)


@pytest.mark.parametrize("cap", ["调整最大仓位为", "仅修改最大仓位", "仅修改最大仓位为"])
@pytest.mark.parametrize("tail", ["其余规则保留。", "其余规则不变。"])
def test_full_wire_source_modify_and_retention_get_inspectable_current_proof(tmp_path, cap, tail):
    text = f"{cap}300股，{tail}"
    store, record = current_collection(tmp_path, now=NOW, later_text=text)
    item = record.items[1]
    inputs = store.input_evidence(record.preparation_id, item.attempts[-1].attempt_id).inputs
    assert "draft" in json.loads(inputs.derivation.raw_json)
    assert len(inputs.derivation.stages) == 3

    with closing(sqlite3.connect(store.database_path)) as connection:
        parent, proof = read_current_assurance(connection, record)
    assert parent.coverage_complete and proof.coverage_complete
    assert proof.source_assessment.raw_delta_verified
    assert proof.source_assessment.provider_full_draft_supplied
    assert proof.current_automatic_fidelity_verified is False and proof.authority_granted is False
    assert proof.source_assessment.changed_paths == ("position.max_qty",)
    assert any(row.target == "position" and row.action == "MODIFY" and row.obligation_ids
               for row in proof.source_assessment.operations)
    declaration, = declarations(text)
    assert text[declaration.start:declaration.end] == f"{cap}300股，"
    assert all(text[row.start:row.end] == row.excerpt
               for row in proof.source_assessment.obligations)
    assert any(row.excerpt == tail and row.state == "MAPPED"
               for row in proof.source_assessment.obligations)
    reviewed = store.review_and_freeze(record.preparation_id,
        command=collection_review_command(record), idempotency_key="review-position-directive")
    with closing(sqlite3.connect(store.database_path)) as connection:
        receipt = require_current_reviewed_preparation(connection, reviewed)
    assert receipt.proofs == (parent, proof)


def _full_wire_case(text, *, action="MODIFY", quantity=300):
    base, parent = _parent()
    source, output = current_update(text)
    source = source.model_copy(update={"source_id": "position-source", "authored_at": _NOW,
        "available_at": _NOW, "effective_trade_date": _NOW.date()})
    draft = base.draft.model_copy(update={"position": base.draft.position.model_copy(
        update={"max_qty": quantity})})
    cap_clause = next(clause for clause in output.clauses
                      if "最大仓位" in clause.excerpt and "股" in clause.excerpt)
    bindings = tuple(row.model_copy(update={"clause_ids": (cap_clause.clause_id,),
        "value": quantity}) for row in output.bindings)
    clauses = tuple(row.model_copy(update={
        "disposition": "POLICY" if row.clause_id == cap_clause.clause_id else "CONTEXT",
        "semantic_role": None if row.clause_id == cap_clause.clause_id else "COMMENTARY",
        "paths": ("position.max_qty",) if row.clause_id == cap_clause.clause_id else (),
    }) for row in output.clauses)
    output = output.model_copy(update={"draft": draft, "bindings": bindings, "clauses": clauses,
        "operations": tuple(row.model_copy(update={"action": action,
            "clause_ids": (cap_clause.clause_id,)}) for row in output.operations)})
    context = context_from_review(base, parent.binding.candidate_hash)
    case = _assemble(base, parent, source, output, context)
    assert "draft" in json.loads(case[3].derivation.raw_json)
    assert len(case[3].derivation.stages) == 3
    return case


@pytest.mark.parametrize("text", [
    "调整最大仓位为300股，其余规则保留。\nOnly buy after the blue lantern turns green.",
    "如果明天站稳，调整最大仓位为300股，其余规则保留。",
    "如果明天站稳：\n调整最大仓位为300股，其余规则保留。",
    "“调整最大仓位为300股，其余规则保留。”",
    "不调整最大仓位为300股，其余规则保留。",
    "调整最大仓位为300股，其余规则保留。\n再取消原来的买入规则。",
])
def test_full_wire_background_labels_cannot_drop_qualified_quoted_or_extra_conditions(text):
    case = _full_wire_case(text)
    result = _assess(case)
    assert result.status == "BLOCKED" and not result.coverage_complete
    assert result.source_assessment.raw_delta_verified
    assert result.source_assessment.provider_full_draft_supplied
    assert result.source_assessment.issues
    assert any(row.scope == "UNKNOWN" or row.state not in {"MAPPED", "CONTEXT_VERIFIED"}
               for row in result.source_assessment.obligations)
    assert result.authority_granted is False


def test_full_wire_retain_operation_cannot_erase_an_explicit_position_change():
    case = _full_wire_case("调整最大仓位为300股，其余规则保留。", action="RETAIN")
    result = _assess(case)
    assert result.status == "BLOCKED" and result.source_assessment.raw_delta_verified
    assert case[2].review.draft.position.max_qty == case[5].draft.position.max_qty != 300
    assert any(row.code == "SOURCE_RELATION_MISMATCH" for row in result.source_assessment.issues)


def test_full_wire_modify_operation_preserves_original_parent_and_separate_retention_tail():
    case = _full_wire_case("仅修改最大仓位300股，其余规则不变。")
    result = _assess(case)
    assert result.coverage_complete
    assert result.parent_hash == case[6].evidence_hash
    assert result.source_assessment.changed_paths == ("position.max_qty",)
    controls = parse_source_controls(case[0], case[5], case[6])
    tail, = controls.controls
    assert tail.excerpt == "其余规则不变。" and tail.action == "RETAIN_UNMENTIONED"
    assert all(row.action == "RETAIN" for row in result.source_assessment.operations
               if row.target != "position")


def test_full_wire_retain_is_complete_only_when_the_declared_cap_matches_the_real_parent():
    case = _full_wire_case("仅修改最大仓位1000股，其余规则不变。", action="RETAIN", quantity=1000)
    result = _assess(case)
    assert result.coverage_complete and result.source_assessment.changed_paths == ()
    assert case[2].review.draft.position.max_qty == case[5].draft.position.max_qty == 1000
    assert all(row.action == "RETAIN" and row.before_hash == row.after_hash
               for row in result.source_assessment.operations)
    assert result.source_assessment.raw_delta_verified
    assert result.source_assessment.provider_full_draft_supplied
    assert result.current_automatic_fidelity_verified is False


def test_full_wire_cannot_replace_the_exact_source_quantity_with_another_valid_native_integer():
    with pytest.raises(ValueError):
        _full_wire_case("调整最大仓位为300股，其余规则保留。", quantity=400)
