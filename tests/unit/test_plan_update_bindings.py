"""Provenance remains at its original source when a later plan changes one section."""

import json
from hashlib import sha256
from uuid import UUID

import pytest
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_monitor_loop_schedule import at
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def prior_review(plan=None):
    from trade_plan_monitor.ai.update_review import build_initial_review

    draft = UnifiedPlanDraft.from_executable(plan or research_plan())
    text = "Synthetic human-reviewed supplements for this fixture."
    source = PreparationSource(
        source_id="first",
        text=text,
        available_at=at(19),
        authored_at=at(19),
        effective_trade_date=at(19).date(),
    )
    return build_initial_review(draft, reviewed_mapping(draft, source=text), source)


def current_update(text="仅修改最大仓位为300股，其余规则保留。"):
    source = PreparationSource(
        source_id="second",
        text=text,
        available_at=at(20),
        authored_at=at(20),
        effective_trade_date=at(20).date(),
    )
    raw = research_plan().model_dump(mode="json")
    raw["position"]["max_qty"] = 300
    clauses = server_source_clauses(text)
    output = PlanUpdateExtractionOutput.model_validate_json(
        json.dumps(
            {
                "schema_version": "monitor-loop-update-extraction-v1",
                "draft": raw,
                "scope": "EXPLICIT_CHANGES",
                "retain_unmentioned": True,
                "scope_clause_ids": [c.clause_id for c in clauses],
                "operations": [
                    {
                        "target": "position",
                        "action": "MODIFY",
                        "rule_id": None,
                        "clause_ids": [clauses[0].clause_id],
                    }
                ],
                "clauses": [
                    c.model_dump(mode="json")
                    | {
                        "disposition": "POLICY" if i == 0 else "UNRESOLVED",
                        "paths": ["position.max_qty"] if i == 0 else [],
                        "reason": "Explicit change",
                    }
                    for i, c in enumerate(clauses)
                ],
                "bindings": [
                    {
                        "path": "position.max_qty",
                        "value": 300,
                        "origin": "SOURCE",
                        "unit": "SHARES",
                        "clause_ids": [clauses[0].clause_id],
                        "supplement_id": None,
                    }
                ],
                "assumptions": [],
                "warnings": [],
                "account_context": None,
            }
        )
    )
    return source, output


def test_inherited_fields_keep_original_binding_supplement_and_candidate_hash():
    from trade_plan_monitor.ai.update_review import build_update_review

    base = prior_review()
    source, output = current_update()
    result = build_update_review(base, source, output)
    assert result.issues == ()
    assert result.draft.position.max_qty == 300
    before = next(b for b in base.bindings if b.path == "ordinary_rules[0].quantity")
    inherited = next(b for b in result.bindings if b.path == "ordinary_rules[0].quantity")
    assert inherited == before
    assert inherited.source_id == "first"
    assert inherited.supplement.candidate_content_hash == before.supplement.candidate_content_hash
    current = next(b for b in result.bindings if b.path == "position.max_qty")
    assert current.source_id == "second"
    assert current.source_hash == source.binding_hash
    assert current.binding.value == 300
    assert current.clauses[0].excerpt == "仅修改最大仓位为300股，"
    assert result.to_preparation_candidate().validation == "VALID"
    assert "confirmed" not in json.loads(result.to_preparation_candidate().payload_json)


@pytest.mark.parametrize("text", ["最大仓位300股。", "仅修改最大仓位300股，其他规则尚待确认。"])
def test_model_scope_label_cannot_resolve_missing_source_retention_scope(text):
    from trade_plan_monitor.ai.update_review import build_update_review

    source, output = current_update(text)
    result = build_update_review(prior_review(), source, output)
    assert result.issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_wrong_current_amount_and_forged_clause_never_acquire_inherited_evidence():
    from trade_plan_monitor.ai.update_review import build_update_review

    source, output = current_update()
    data = output.model_dump(mode="json")
    data["draft"]["position"]["max_qty"] = 400
    data["bindings"][0]["value"] = 400
    with pytest.raises(ValueError):
        build_update_review(
            prior_review(), source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(data))
        )
    data = output.model_dump(mode="json")
    data["clauses"][0]["excerpt"] = "Forged evidence"
    with pytest.raises(ValueError):
        build_update_review(
            prior_review(), source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(data))
        )


def test_unresolved_predecessor_blocks_dependents_and_future_source_never_changes_past_hash():
    from trade_plan_monitor.ai.update_review import build_update_review

    base = prior_review()
    digest = base.evidence_hash
    source, output = current_update()
    missing = output.model_copy(update={"bindings": ()})
    unresolved = build_update_review(base, source, missing)
    assert unresolved.issues
    next_source = source.model_copy(update={"source_id": "third", "available_at": at(21)})
    with pytest.raises(ValueError):
        build_update_review(unresolved, next_source, output)
    assert base.evidence_hash == digest


@pytest.mark.parametrize("text", ["不是完整替换此前计划。", "假设完整替换此前计划。"])
def test_negated_or_hypothetical_scope_cannot_be_approved_by_policy_paths(text):
    from trade_plan_monitor.ai.update_review import build_update_review

    source, output = current_update(text)
    raw = output.model_dump(mode="json")
    raw.update(scope="FULL_REPLACEMENT", retain_unmentioned=False, operations=[], bindings=[])
    output = PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
    # Even explicitly supplied field corrections cannot attest a contradicted scope.
    result = build_update_review(
        prior_review(), source, output, mapping=reviewed_mapping(output.draft, source=text)
    )
    assert result.issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def account_update(quantity, *, dependent_rule_id=None):
    source, output = current_update(
        f"仅修改最大仓位为300股，其余规则保留。TACTICAL持仓{quantity}股。"
    )
    raw = output.model_dump(mode="json")
    clause = raw["clauses"][-1]
    clause.update(
        disposition="INVENTORY_ASSERTION",
        reason="Synthetic stated holdings used only for comparison against the running ledger.",
    )
    raw["account_context"] = {
        "tactical_qty": {
            "value": quantity,
            "start": clause["start"],
            "end": clause["end"],
            "excerpt": clause["excerpt"],
        },
        "dependent_rule_ids": [dependent_rule_id] if dependent_rule_id else [],
        "dependency_clause_ids": [clause["clause_id"]] if dependent_rule_id else [],
    }
    return source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("quantity", [0, 200])
def test_later_holdings_are_comparison_context_without_account_reset_or_trade_change(quantity):
    from trade_plan_monitor.ai.update_review import build_update_review

    base = prior_review()
    source, output = account_update(quantity)
    result = build_update_review(base, source, output)
    assert result.issues == ()
    assert result.account_context.tactical_qty.value == quantity
    assert result.account_context.dependent_rule_ids == ()
    assert result.draft.ordinary_rules == base.draft.ordinary_rules
    assert result.draft.ordinary_rules[0].quantity == 100
    payload = json.loads(result.to_preparation_candidate().payload_json)
    assert not {"opening_account", "initial_cash_fen", "initial_lots", "confirmed"} & payload.keys()


def test_holdings_statement_alone_cannot_make_fixed_quantity_rule_account_dependent():
    from trade_plan_monitor.ai.update_review import build_update_review

    source, output = account_update(
        200, dependent_rule_id=research_plan().ordinary_rules[0].rule_id
    )
    result = build_update_review(prior_review(), source, output)
    assert result.issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_account_dependency_cannot_name_a_nonexistent_materialized_rule():
    from trade_plan_monitor.ai.update_review import build_update_review

    source, output = account_update(200, dependent_rule_id="not-a-rule")
    with pytest.raises(ValueError, match="nonexistent"):
        build_update_review(prior_review(), source, output)


def test_explicit_account_dependency_preserves_exact_rule_and_quantity_evidence():
    from trade_plan_monitor.ai.update_review import build_update_review

    identity = research_plan().ordinary_rules[0].rule_id
    source, output = account_update(200)
    source = source.model_copy(
        update={
            "text": source.text + f"规则{identity}仅当TACTICAL持仓200股时执行。",
        }
    )
    clause = server_source_clauses(source.text)[-1]
    raw = output.model_dump(mode="json")
    raw["clauses"].append(
        clause.model_dump(mode="json")
        | {
            "disposition": "UNRESOLVED",
            "paths": [],
            "reason": "Explicit holdings dependency",
        }
    )
    raw["account_context"].update(
        dependent_rule_ids=[identity],
        dependency_clause_ids=[clause.clause_id],
    )
    output = PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
    result = build_update_review(prior_review(), source, output)
    assert result.issues == ()
    assert result.account_context.dependent_rule_ids == (identity,)
    assert result.draft.ordinary_rules[0].quantity == 100


def extraction_for(base, source, output):
    from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionResult
    from trade_plan_monitor.ai.update_review import context_from_review
    from trade_plan_monitor.backtest.canonical import canonical_json

    context = context_from_review(base, "b" * 64)
    digest = sha256(
        canonical_json(
            {
                "domain": "monitor-loop-update-evidence-v1",
                "source_binding_hash": source.binding_hash,
                "context": context,
                "output": output,
            }
        ).encode()
    ).hexdigest()
    return PlanUpdateExtractionResult(
        request_id=UUID(int=1),
        provider_id=UUID(int=2),
        model="synthetic-offline-provider",
        source_id=source.source_id,
        source_text_sha256=source.source_hash,
        source_binding_hash=source.binding_hash,
        base_hash=context.base_hash,
        authored_at=source.authored_at,
        available_at=source.available_at,
        effective_trade_date=source.effective_trade_date,
        output=output,
        evidence_hash=digest,
        usage=None,
    )


def test_materialization_binds_exact_extraction_source_predecessor_and_evidence():
    from trade_plan_monitor.ai.update_review import materialize_extraction

    base = prior_review()
    source, output = current_update()
    extraction = extraction_for(base, source, output)
    result = materialize_extraction(base, "b" * 64, source, extraction)
    assert result.to_preparation_candidate().validation == "VALID"
    assert result.review.draft.position.max_qty == 300
    assert extraction.to_preparation_candidate().validation == "UNRESOLVED"
    for changed in (
        {"base_hash": "c" * 64},
        {"evidence_hash": "0" * 64},
        {"source_id": "another-source"},
        {"available_at": at(21)},
        {"output": output.model_copy(update={"scope_clause_ids": (output.scope_clause_ids[0],)})},
    ):
        with pytest.raises(ValueError):
            materialize_extraction(base, "b" * 64, source, extraction.model_copy(update=changed))
    with pytest.raises(ValueError):
        materialize_extraction(base, "c" * 64, source, extraction)
    with pytest.raises(ValueError):
        materialize_extraction(
            base,
            "b" * 64,
            source.model_copy(update={"text": source.text + "新增事实。"}),
            extraction,
        )


def test_revocation_keeps_original_source_and_supplement_when_rule_indices_move():
    from trade_plan_monitor.ai.update_review import build_update_review

    plan = research_plan()
    first = plan.ordinary_rules[0]
    second = first.model_copy(update={"rule_id": "keep-sell", "side": "SELL", "quantity": 200})
    plan = plan.model_copy(update={"ordinary_rules": (first, second)})
    base = prior_review(plan)
    source, output = current_update(f"撤销规则{first.rule_id}。其余规则保留。")
    raw = output.model_dump(mode="json")
    raw.update(draft=plan.model_dump(mode="json"), bindings=[])
    raw["operations"] = [
        {
            "target": "ordinary_rules",
            "action": "REVOKE",
            "rule_id": first.rule_id,
            "clause_ids": [raw["clauses"][0]["clause_id"]],
        }
    ]
    for clause in raw["clauses"]:
        clause.update(disposition="UNRESOLVED", paths=[])
    result = build_update_review(
        base, source, PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
    )
    assert result.issues == ()
    assert [rule.rule_id for rule in result.draft.ordinary_rules] == ["keep-sell"]
    old = next(item for item in base.bindings if item.path == "ordinary_rules[1].quantity")
    moved = next(item for item in result.bindings if item.path == "ordinary_rules[0].quantity")
    assert moved == old.model_copy(update={"path": "ordinary_rules[0].quantity"})
    assert moved.original_path == moved.supplement.path == "ordinary_rules[1].quantity"
    assert moved.source_id == "first"


def test_retention_control_cannot_hide_unprocessed_technical_remainder():
    from trade_plan_monitor.ai.update_review import build_update_review

    source, output = current_update("仅修改最大仓位为300股，其余规则保留但跌破10元必须卖出。")
    result = build_update_review(prior_review(), source, output)
    assert any("DAILY_SOURCE_CLAUSE_REQUIRED" in issue for issue in result.issues)
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_complete_replacement_missing_condition_remains_visible_and_unresolved():
    from trade_plan_monitor.ai.update_review import build_update_review

    source, output = current_update("完整替换此前计划。")
    raw = output.model_dump(mode="json")
    raw.update(scope="FULL_REPLACEMENT", retain_unmentioned=False, operations=[], bindings=[])
    raw["draft"]["ordinary_rules"][0]["condition"] = None
    output = PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
    result = build_update_review(
        prior_review(), source, output, mapping=reviewed_mapping(output.draft, source=source.text)
    )
    assert result.draft.ordinary_rules[0].condition is None
    assert result.draft.to_executable() is None
    assert any("condition" in issue for issue in result.issues)
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_bounded_materialized_evidence_survives_existing_document_store_restart(tmp_path):
    from trade_plan_monitor.ai.update_review import (
        MaterializedUpdateCandidate,
        materialize_extraction,
    )
    from trade_plan_monitor.backtest.preparation_models import SinglePlanPreparationInput
    from trade_plan_monitor.backtest.preparation_store import PreparationStore

    base = prior_review()
    source, output = current_update()
    candidate = materialize_extraction(base, "b" * 64, source, extraction_for(base, source, output))
    path = tmp_path / "evidence.sqlite3"
    store = PreparationStore(path)
    initial = store.create(
        SinglePlanPreparationInput(preparation_id="evidence", sources=(source,)),
        idempotency_key="create",
    )
    started = store.start_attempt(
        "evidence", expected_revision=initial.revision, idempotency_key="start"
    )
    finished = store.finish_attempt(
        "evidence",
        expected_revision=started.revision,
        attempt_id=started.attempts[-1].attempt_id,
        idempotency_key="finish",
        candidate=candidate.to_preparation_candidate(),
    )
    restored = PreparationStore(path).get("evidence")
    assert restored == finished and restored.review is None
    decoded = MaterializedUpdateCandidate.model_validate_json(restored.candidate.payload_json)
    assert decoded == candidate
    assert decoded.review.evidence_hash == restored.candidate.evidence_hash
    assert decoded.extraction.base_hash == "b" * 64
    assert {b.source_id for b in decoded.review.bindings} == {"first", "second"}
