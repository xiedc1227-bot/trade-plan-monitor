"""Replay local derivation instead of trusting self-consistent evidence hashes.

Fixtures are synthetic reviewed local policies. No provider, database, activation
or market evaluation is used, and derivation never grants trading authority.
"""

import importlib
import json
import socket
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy.engine import Engine
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_plan_update_bindings import current_update, prior_review
from tests.unit.test_source_tranches import tranche_plan
from tests.unit.test_unified_preparation_updates import buy_and_sell_plan

from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
from trade_plan_monitor.ai.preparation_wire import expand_compact_output
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.plan_updates import materialize_plan_update
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_scope import scope_hash


def _api():
    return importlib.import_module("trade_plan_monitor.ai.source_derivation_replay")


def _patch_case():
    source, patch = delta("总持仓最多500股。", values={"max_qty": 500})
    context = context_from_review(prior_review(), "b" * 64)
    expanded = expand_delta_output(patch, context)
    normalized = expand_compact_output(expanded, source, context=context)
    raw = json.dumps(patch.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    return source, context, raw, expanded, normalized


def _resign(evidence, **updates):
    values = evidence.model_dump(mode="python", exclude={
        "evidence_hash", "raw_hash", "context_hash",
    })
    return SourceDerivationEvidence.build(**(values | updates))


def _replace_stage(evidence, index, output):
    stages = list(evidence.stages)
    stages[index] = DerivationStage.build(phase=stages[index].phase, output_json=canonical(output))
    return _resign(evidence, stages=tuple(stages))


def _assert_hashes_valid(evidence):
    # The attack must reach deterministic replay after passing all hash checks.
    assert SourceDerivationEvidence.model_validate_json(evidence.model_dump_json()) == evidence


def test_original_delta_without_draft_replays_complete_outputs_and_exact_context():
    source, context, raw, expanded, normalized = _patch_case()
    assert "draft" not in json.loads(raw)

    output, evidence = _api().expand_update_with_evidence(raw, source, context)

    assert output == normalized
    assert evidence.kind == "PREDECESSOR_PATCH"
    assert evidence.raw_json == raw and evidence.raw_hash == scope_hash(raw)
    assert evidence.context_json == canonical(context.model_dump(mode="json"))
    assert evidence.base_hash == context.base_hash
    assert [stage.phase for stage in evidence.stages] == ["DELTA_EXPANDED", "SOURCE_NORMALIZED"]
    assert [stage.output_json for stage in evidence.stages] == [
        canonical(expanded.model_dump(mode="json")), canonical(normalized.model_dump(mode="json")),
    ]
    assert evidence.authority_granted is False
    assert _api().verify_update_derivation(evidence, source, context, normalized) == normalized


def test_raw_whitespace_is_preserved_without_changing_replayed_meaning():
    source, context, raw, _, _ = _patch_case()
    compact_raw = canonical(json.loads(raw))

    first, original = _api().expand_update_with_evidence(raw, source, context)
    second, compact = _api().expand_update_with_evidence(compact_raw, source, context)

    assert first == second and original.stages == compact.stages
    assert original.raw_json == raw and compact.raw_json == compact_raw
    assert original.raw_hash != compact.raw_hash
    assert original.evidence_hash != compact.evidence_hash


@pytest.mark.parametrize("change", ["source", "base_hash", "snapshot", "available_at"])
def test_current_source_or_any_trusted_predecessor_context_change_rejects_reuse(change):
    source, context, raw, _, _ = _patch_case()
    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    changed_source, changed_context = source, context
    if change == "source":
        changed_source = source.model_copy(update={"text": source.text + "\n新增条件。"})
    elif change == "base_hash":
        changed_context = context.model_copy(update={"base_hash": "c" * 64})
    elif change == "available_at":
        changed_context = context.model_copy(update={
            "available_at": context.available_at + timedelta(minutes=1),
        })
    else:
        position = context.snapshot.position.model_copy(update={"max_qty": 900})
        changed_context = context.model_copy(update={
            "snapshot": context.snapshot.model_copy(update={"position": position}),
        })

    with pytest.raises(ValueError):
        _api().verify_update_derivation(evidence, changed_source, changed_context, output)


def test_rehashing_a_forged_context_cannot_override_the_trusted_context_argument():
    source, context, raw, _, _ = _patch_case()
    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    forged_context = json.loads(evidence.context_json)
    forged_context["snapshot"]["position"]["max_qty"] = 900
    forged = _resign(evidence, context_json=canonical(forged_context))
    _assert_hashes_valid(forged)

    with pytest.raises(ValueError):
        _api().verify_update_derivation(forged, source, context, output)


@pytest.mark.parametrize("index", [0, 1], ids=["delta_expanded", "source_normalized"])
def test_rehashing_a_forged_stage_output_does_not_make_it_a_replayed_stage(index):
    source, context, raw, _, _ = _patch_case()
    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    proposed = json.loads(evidence.stages[index].output_json)
    proposed["draft"]["position"]["max_qty"] = 600
    forged = _replace_stage(evidence, index, proposed)
    _assert_hashes_valid(forged)

    with pytest.raises(ValueError):
        _api().verify_update_derivation(forged, source, context, output)


@pytest.mark.parametrize("field", ["operations", "bindings", "clauses", "warnings"])
def test_matching_forged_expected_output_and_stage_cannot_hide_nondraft_changes(field):
    source, context, raw, _, _ = _patch_case()
    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    proposed = output.model_dump(mode="json")
    if field == "operations":
        proposed["operations"][0]["action"] = "RETAIN"
    elif field == "bindings":
        proposed["bindings"] = []
    elif field == "clauses":
        proposed["clauses"][0]["reason"] = "Forged current meaning."
    else:
        proposed["warnings"] = [{"path": "position", "material": True,
                                  "message": "Forged warning added after extraction."}]
    changed_output = PlanUpdateExtractionOutput.model_validate_json(canonical(proposed))
    assert changed_output.draft == output.draft  # Comparing drafts alone would miss this attack.
    assert canonical(changed_output.model_dump(mode="json")) != canonical(
        output.model_dump(mode="json"))
    forged = _replace_stage(evidence, 1, changed_output.model_dump(mode="json"))
    _assert_hashes_valid(forged)

    with pytest.raises(ValueError):
        _api().verify_update_derivation(forged, source, context, changed_output)


def test_rehashing_changed_original_operations_replays_them_instead_of_trusting_old_outputs():
    source, context, raw, _, _ = _patch_case()
    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    changed_raw = json.loads(raw)
    changed_raw["operations"][0]["values"]["max_qty"] = 600
    forged = _resign(evidence, raw_json=canonical(changed_raw))
    _assert_hashes_valid(forged)

    with pytest.raises(ValueError):
        _api().verify_update_derivation(forged, source, context, output)


@pytest.mark.parametrize("operation", ["verify", "append"])
def test_a_valid_prefix_without_source_normalized_is_not_a_complete_derivation(operation):
    source, context, raw, _, _ = _patch_case()
    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    prefix = _resign(evidence, stages=evidence.stages[:1])
    _assert_hashes_valid(prefix)
    function = (_api().verify_update_derivation if operation == "verify"
                else _api().append_materialized_derivation)

    with pytest.raises(ValueError):
        function(prefix, source, context, output)


def test_materialization_appends_its_complete_replayed_result_without_granting_authority():
    source, context, raw, _, _ = _patch_case()
    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    expected = materialize_plan_update(context.snapshot, output)
    original = evidence.model_dump_json()

    extended = _api().append_materialized_derivation(evidence, source, context, output)

    assert evidence.model_dump_json() == original and len(evidence.stages) == 2
    assert extended.stages[:2] == evidence.stages
    assert extended.stages[-1].phase == "MATERIALIZED"
    assert extended.stages[-1].output_json == canonical(expected.model_dump(mode="json"))
    assert extended.authority_granted is False
    assert _api().verify_update_derivation(extended, source, context, output) == output
    assert _api().append_materialized_derivation(extended, source, context, output) == extended


@pytest.mark.parametrize("field", ["draft", "changes", "origins"])
def test_rehashing_the_materialized_stage_cannot_forge_draft_changes_or_field_origins(field):
    source, context, raw, _, _ = _patch_case()
    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    extended = _api().append_materialized_derivation(evidence, source, context, output)
    proposed = json.loads(extended.stages[2].output_json)
    if field == "draft":
        proposed["draft"]["position"]["max_qty"] = 600
    elif field == "changes":
        proposed["changes"][0]["action"] = "RETAIN"
    else:
        proposed["origins"][0]["origin"] = "CURRENT"
        proposed["origins"][0]["original_path"] = "forged.path"
    assert proposed != json.loads(extended.stages[2].output_json)
    forged = _replace_stage(extended, 2, proposed)
    _assert_hashes_valid(forged)

    with pytest.raises(ValueError):
        _api().verify_update_derivation(forged, source, context, output)


@pytest.mark.parametrize("field,value", [
    ("quantity", 200), ("status", None), ("independent_signal", {"mode": "ONCE_PER_RULE"}),
], ids=["quantity", "permission_unknown", "occurrence_policy"])
def test_rule_changes_preserve_exact_quantity_permission_and_occurrence_policy(field, value):
    base = prior_review(tranche_plan())
    target = base.draft.ordinary_rules[1].rule_id
    source, patch = delta("第二笔数量或许可策略按本次要求修改。",
        target="ordinary_rules", rule_id=target, values={field: value})
    context = context_from_review(base, "c" * 64)
    raw = canonical(patch.model_dump(mode="json"))

    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    extended = _api().append_materialized_derivation(evidence, source, context, output)

    observed = output.draft.ordinary_rules[1].model_dump(mode="json")
    assert observed[field] == value
    assert output.draft.ordinary_rules[0] == base.draft.ordinary_rules[0]
    materialized = json.loads(extended.stages[2].output_json)
    assert materialized["draft"]["ordinary_rules"][1][field] == value
    assert extended.authority_granted is False
    assert _api().verify_update_derivation(extended, source, context, output) == output


def test_canceling_first_rule_remaps_remaining_field_indices_to_the_exact_original_indices():
    base = prior_review(buy_and_sell_plan())
    source, patch = delta("取消原买单，其余卖单保留。", target="ordinary_rules",
        rule_id=base.draft.ordinary_rules[0].rule_id, action="REVOKE")
    context = context_from_review(base, "d" * 64)

    output, evidence = _api().expand_update_with_evidence(
        canonical(patch.model_dump(mode="json")), source, context)
    extended = _api().append_materialized_derivation(evidence, source, context, output)

    assert [rule.side for rule in output.draft.ordinary_rules] == ["SELL"]
    assert output.draft.ordinary_rules[0].quantity == 200
    image = json.loads(extended.stages[-1].output_json)
    origin = next(row for row in image["origins"] if row["path"] == "ordinary_rules[0].quantity")
    assert origin["origin"] == "BASE" and origin["original_path"] == "ordinary_rules[1].quantity"
    assert _api().verify_update_derivation(extended, source, context, output) == output
    forged_image = deepcopy(image)
    next(row for row in forged_image["origins"] if row["path"] == origin["path"])[
        "original_path"
    ] = "ordinary_rules[0].quantity"
    forged = _replace_stage(extended, 2, forged_image)
    _assert_hashes_valid(forged)
    with pytest.raises(ValueError):
        _api().verify_update_derivation(forged, source, context, output)


@pytest.mark.parametrize("protocol", ["compact_update", "typed_update"])
def test_existing_compact_and_full_update_protocols_record_their_actual_typing_stage(protocol):
    source, typed = current_update()
    context = context_from_review(prior_review(), "e" * 64)
    payload = typed.model_dump(mode="json")
    if protocol == "compact_update":
        payload["schema_version"] = "monitor-loop-update-wire-v1"
        payload["clauses"] = [dict(clause_id=c.clause_id, disposition="POLICY",
            reason="Explicit current source.") for c in typed.clauses]
        payload["bindings"] = [dict(path=b.path, clause_ids=list(b.clause_ids))
                               for b in typed.bindings]
        payload.pop("assumptions")
    raw = json.dumps(payload, ensure_ascii=False, indent=2)

    output, evidence = _api().expand_update_with_evidence(raw, source, context)

    first = json.loads(evidence.stages[0].output_json)
    assert first["schema_version"] == payload["schema_version"]
    assert first["draft"] == payload["draft"]
    assert evidence.raw_json == raw
    assert [stage.phase for stage in evidence.stages] == ["DELTA_EXPANDED", "SOURCE_NORMALIZED"]
    assert _api().verify_update_derivation(evidence, source, context, output) == output
    assert evidence.authority_granted is False


@pytest.mark.parametrize("raw", [None, "", "{}", "null", "[]",
    '{"schema_version":"unregistered-wire-v99","operations":[]}',
    '{"schema_version":"monitor-loop-delta-wire-v1","operations":[],"operations":[]}',
    '{"schema_version":"monitor-loop-delta-wire-v1","operations":[],"x":NaN}',
])
def test_missing_original_raw_ambiguous_json_or_unsupported_protocol_cannot_replay(raw):
    source, context, _, _, _ = _patch_case()

    with pytest.raises((TypeError, ValueError)):
        _api().expand_update_with_evidence(raw, source, context)


def test_reassessment_authority_cannot_be_replayed_as_an_enabled_new_trade():
    source, patch = delta("重新评估后再决定是否新增买单。", target="ordinary_rules",
        rule_id="new-buy", action="ADD", values=prior_review().draft.ordinary_rules[0].model_dump(
            mode="json") | {"rule_id": "new-buy"})
    payload = patch.model_dump(mode="json")
    payload["schema_version"] = "monitor-loop-delta-wire-v2"
    payload["operations"][0]["authority"] = "REASSESS_BEFORE_DECIDING"
    context = context_from_review(prior_review(), "f" * 64)

    with pytest.raises(ValueError):
        _api().expand_update_with_evidence(canonical(payload), source, context)


def test_all_derivation_steps_are_local_even_when_provider_network_and_database_are_forbidden(
    monkeypatch,
):
    source, context, raw, _, _ = _patch_case()

    def forbidden(*args, **kwargs):
        raise AssertionError("Derivation attempted provider, network or database I/O")

    monkeypatch.setattr(OpenAICompatibleProvider, "extract_plan", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(Engine, "connect", forbidden)

    output, evidence = _api().expand_update_with_evidence(raw, source, context)
    extended = _api().append_materialized_derivation(evidence, source, context, output)

    assert _api().verify_update_derivation(extended, source, context, output) == output
    assert extended.authority_granted is False
