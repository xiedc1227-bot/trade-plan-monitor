"""Server-only source evidence must survive compact expansion and result wrapping.

Static responses exercise local parsing only; no test represents live-model
accuracy, grants authority, or accesses a database.
"""

import asyncio
import json
from datetime import date
from hashlib import sha256

import pytest
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_ai_plan_extraction_v4 import _REQUEST_ID, _config, _StaticProvider
from tests.unit.test_plan_update_bindings import current_update, prior_review
from tests.unit.test_preparation_wire import wire
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.ai.extraction import _parse_untrusted_output, _review_current_output
from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult, extract_loop_plan
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.preparation_wire import (
    build_compact_prompt,
    expand_compact_output,
    response_model,
)
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_normalization import validate_normalization
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.preparation_models import PreparationSource
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

_PINNED_SOURCE = PreparationSource(
    source_id="pma-compact-contract", text="003043.SZ仅当五分钟收盘价高于10元时买入100股。",
    effective_trade_date=date(2026, 10, 27),
)
_INITIAL_SCHEMA_SHA256 = "0e5e209d77286d6a561ef0a36bb7f6637f8723cef2de2b9861572cb98d7db417"
_UPDATE_SCHEMA_SHA256 = "0554058d52831172f0833a29869edef2f0a77e7c803894988098e7546f75cccc"
_PROMPT_SHA256 = "7ae551d602c502ddbb93a608f91a9a7679011c138b58501cf5caae75f8bb6632"


def _compact_case(*, semantic=True, evaluation_only=False):
    draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(unified_payload()))
    text, mapping = source_mapping(draft)
    if evaluation_only:
        text += "\n再重新设置低吸区并评估第一笔。"
    source = PreparationSource(source_id="pma-compact-static", text=text,
        effective_trade_date=date(2026, 10, 27))
    clauses = [dict(clause_id=c.clause_id, disposition="POLICY",
                    reason="Exact fixture declaration.", **({"meaning": "DIRECTIVE"}
                    if semantic else {})) for c in mapping.clauses]
    if evaluation_only:
        clauses.append(dict(clause_id=server_source_clauses(text)[-1].clause_id,
            disposition="UNRESOLVED", reason="Evaluation grants no buy authority."))
    return source, dict(
        schema_version="monitor-loop-wire-v2" if semantic else "monitor-loop-wire-v1",
        draft=draft.model_dump(mode="json"), clauses=clauses,
        bindings=[dict(path=b.path, clause_ids=list(b.clause_ids)) for b in mapping.bindings],
        opening_account=dict(inventory_quantity=None, lots=[], cash_fen=None, snapshot_at=None),
    )


def _parse(payload, *, update=False):
    return _parse_untrusted_output(canonical(payload),
        prompt_version="monitor-loop-update-extract-v1" if update else "monitor-loop-extract-v1",
        output_model=response_model(update=update)).root


def _extract(source, payload):
    provider = _StaticProvider(canonical(payload))
    result = asyncio.run(extract_loop_plan(
        request_id=_REQUEST_ID, source=source, compact=True, provider=provider,
        config=_config().model_copy(update={"max_input_chars": 200_000}),
    ))
    assert provider.request is not None
    return result


def _review(output, source):
    config = _config().model_copy(update={"prompt_version": "monitor-loop-update-extract-v1"})
    raw = RawAIResponse(request_id=_REQUEST_ID, provider_id=config.provider_id,
        model=config.model, content=canonical(output.model_dump(mode="json")),
        finish_reason="stop", usage=None, attempts=1)
    return _review_current_output(output, source.text, _REQUEST_ID, config, raw)


def _patch_case(*, scoped_risk=False):
    base = prior_review(UnifiedTradePlan.model_validate(unified_payload()))
    source, old = current_update()
    context = context_from_review(base, "a" * 64)
    draft = base.draft.model_dump(mode="json")
    if not scoped_risk:
        draft["position"]["max_qty"] = 300
        draft["levels"] = None  # Unmentioned values must be restored from the verified base.
    operations = [operation.model_dump(mode="json") for operation in old.operations]
    references = [dict(path=b.path, clause_ids=list(b.clause_ids)) for b in old.bindings]
    if scoped_risk:
        draft["risk_branches"][0]["holding_scope"] = None
        operations = [dict(target="risk_branches", action="REVOKE",
            rule_id=draft["risk_branches"][0]["kind"], clause_ids=[old.clauses[0].clause_id],
            scope_assessment="PARTIAL_RULE", scope_change="EXISTING_POSITIONS_ONLY")]
        references = []
    payload = dict(schema_version="monitor-loop-update-wire-v2", draft=draft,
        scope="EXPLICIT_CHANGES", scope_clause_ids=list(old.scope_clause_ids),
        retain_unmentioned=True, operations=operations, account_context=None,
        clauses=[dict(clause_id=c.clause_id, disposition="POLICY", meaning="DIRECTIVE",
                      reason="Explicit current update.") for c in old.clauses], bindings=references)
    return source, payload, base, context


def test_server_private_carriers_preserve_both_compact_wire_schemas_and_prompt():
    initial = canonical(response_model().model_json_schema())
    update = canonical(response_model(update=True).model_json_schema())

    assert sha256(initial.encode("utf-8")).hexdigest() == _INITIAL_SCHEMA_SHA256
    assert sha256(update.encode("utf-8")).hexdigest() == _UPDATE_SCHEMA_SHA256
    prompt_hash = sha256(build_compact_prompt(_PINNED_SOURCE).encode("utf-8")).hexdigest()
    assert prompt_hash == _PROMPT_SHA256
    assert "_source_preimage_json" not in initial + update


@pytest.mark.parametrize("schema", ["monitor-loop-wire-v1", "monitor-loop-wire-v2"])
def test_root_model_retains_the_raw_compact_draft_before_whitespace_normalization(schema):
    payload = wire(_PINNED_SOURCE)
    payload["schema_version"] = schema
    payload["draft"]["name"] = "  Compact 原始候选  "
    before = canonical(payload["draft"])

    parsed = _parse_untrusted_output(canonical(payload),
        prompt_version="monitor-loop-extract-v1", output_model=response_model())

    assert parsed.root.draft.name == "Compact 原始候选"
    assert parsed.root._source_preimage_json == before
    assert "_source_preimage_json" not in parsed.model_dump(mode="json")


@pytest.mark.parametrize("semantic", [False, True], ids=["legacy", "semantic"])
def test_expansion_passes_the_original_provider_image_through_the_new_output(semantic):
    source, payload = _compact_case(semantic=semantic)
    payload["draft"]["name"] = "  Raw compact before expansion  "
    before = canonical(payload["draft"])
    output = _parse(payload)

    expanded = expand_compact_output(output, source)

    assert expanded._source_preimage_json == before == output._source_preimage_json
    assert json.loads(before)["name"] == "  Raw compact before expansion  "
    assert expanded.draft.name == "Raw compact before expansion"
    assert expanded._source_preimage_json != canonical(expanded.draft.model_dump(mode="json"))
    assert "_source_preimage_json" not in expanded.model_dump(mode="json")


def test_mock_compact_extraction_keeps_the_complete_original_trace_after_loop_result_wrapping():
    source, payload = _compact_case()
    payload["draft"]["name"] = "  Raw compact display  "

    result = _extract(source, payload)

    assert isinstance(result, LoopPlanExtractionResult)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.coverage is not None and result.normalization_trace is not None
    trace = result.normalization_trace
    assert trace.before_hash == daily_hash("source-normalization-candidate-v1", payload["draft"])
    assert trace.after_hash == daily_hash(
        "source-normalization-candidate-v1", result.draft.model_dump(mode="json"),
    )
    assert trace.before_hash != trace.after_hash
    assert [change.path for change in trace.changes] == ["name"]
    assert validate_normalization(trace, result.draft, source.text) == payload["draft"]
    assert result.coverage.normalization_hash == trace.evidence_hash
    assert result.coverage.origin == "AI_NEW" and result.coverage.authority_granted is False
    # Existing independent field/account blockers remain visible. Raw fidelity
    # preservation must not claim this synthetic compact plan is ready to trade.
    assert result.validation_issues
    assert "SOURCE_NORMALIZATION_LOSS" not in {i.code for i in result.coverage.issues}
    for candidate in (result, result.model_copy(update={"warnings": result.warnings})):
        assert candidate.coverage == result.coverage
        assert candidate.normalization_trace == trace
        assert "coverage" not in candidate.model_dump(mode="json")
        assert "normalization_trace" not in candidate.model_dump(mode="json")
        prepared = json.loads(candidate.to_preparation_candidate().payload_json)
        assert "normalization_trace" not in prepared


def test_evaluation_only_rewrite_retains_candidate_and_original_buy_obligations_as_blocked():
    source, payload = _compact_case(semantic=False, evaluation_only=True)
    original = canonical(payload["draft"])
    assert payload["draft"]["ordinary_rules"]

    result = _extract(source, payload)

    assert isinstance(result, LoopPlanExtractionResult)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft.ordinary_rules == ()
    assert result.daily_mapping.clauses[-1].excerpt == "再重新设置低吸区并评估第一笔。"
    assert result.coverage.status == "BLOCKED"
    assert result.coverage.automatic_fidelity_verified is False
    assert result.coverage.authority_granted is False
    trace = result.normalization_trace
    assert any(change.path == "ordinary_rules" for change in trace.changes)
    assert canonical(validate_normalization(trace, result.draft, source.text)) == original
    assert trace.before_hash != trace.after_hash
    assert canonical(payload["draft"]) == original
    assert any(i.code == "SOURCE_NORMALIZATION_LOSS" for i in result.coverage.issues)
    assert any(i.code == "SOURCE_NORMALIZATION_LOSS" and i.activation_blocking
               for i in result.validation_issues)
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_direct_compact_model_validation_without_admitted_raw_image_cannot_fabricate_fidelity():
    source, payload = _compact_case()
    output = response_model().model_validate_json(canonical(payload)).root

    expanded = expand_compact_output(output, source)
    result = _review(expanded, source)

    assert expanded._source_preimage_json is None
    assert result.normalization_trace is None
    assert result.coverage.origin == "AI_NEW"
    assert result.coverage.automatic_fidelity_verified is False
    assert any(i.code == "SOURCE_NORMALIZATION_LOSS" for i in result.coverage.issues)


@pytest.mark.parametrize("deep", [False, True])
def test_update_copy_and_inheritance_restore_fields_without_replacing_the_provider_preimage(deep):
    source, payload, base, context = _patch_case()
    original = canonical(payload["draft"])
    assert payload["draft"]["levels"] is None and base.draft.levels is not None
    output = _parse(payload, update=True)
    copied = output.model_copy(update={"operations": output.operations}, deep=deep)
    assert copied._source_preimage_json == output._source_preimage_json == original

    expanded = expand_compact_output(copied, source, context=context)
    result = _review(expanded, source)

    assert expanded.draft.levels == base.draft.levels
    assert expanded._source_preimage_json == original
    assert json.loads(expanded._source_preimage_json)["levels"] is None
    assert result.normalization_trace.before_hash != result.normalization_trace.after_hash
    assert validate_normalization(result.normalization_trace, result.draft, source.text) == payload[
        "draft"
    ]
    assert any(change.path == "levels" for change in result.normalization_trace.changes)
    # Valid predecessor restoration belongs to materialization review; it cannot
    # become proof that the AI supplied those inherited values in its raw draft.
    assert result.coverage.automatic_fidelity_verified is False
    assert result.coverage.authority_granted is False
    assert context.base_hash == "a" * 64
    assert canonical(payload["draft"]) == original


def test_scoped_risk_operation_rewrite_does_not_overwrite_the_original_nested_scope():
    source, payload, _, context = _patch_case(scoped_risk=True)
    original = canonical(payload["draft"])
    assert payload["draft"]["risk_branches"][0]["holding_scope"] is None
    output = _parse(payload, update=True)

    expanded = expand_compact_output(output, source, context=context)

    assert expanded.operations[0].action == "MODIFY"
    scope = expanded.draft.risk_branches[0].holding_scope
    assert scope.mode == "BEFORE_TRADE_DATE" and scope.trade_date == source.effective_trade_date
    assert expanded._source_preimage_json == output._source_preimage_json == original
    assert json.loads(original)["risk_branches"][0]["holding_scope"] is None
    assert canonical(payload["draft"]) == original
