"""Current AI coverage keeps inspectable candidates without changing the v12 wire.

All extraction responses are deterministic in-memory test doubles. These tests
prove the local trust boundary, never real-model extraction accuracy or authority.
"""

import asyncio
from hashlib import sha256

import pytest
from tests.unit.test_ai_plan_extraction_v4 import _REQUEST_ID, _config, _StaticProvider
from tests.unit.test_source_coverage_baseline import _append_as_context, _baseline

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.ai.extraction import (
    _parse_untrusted_output,
    _review_current_output,
    extract_plan,
)
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_extraction import (
    CurrentPlanExtractionOutput,
    CurrentPlanExtractionResult,
    build_current_plan_prompt,
)
from trade_plan_monitor.ai.provider import RawAIResponse
from trade_plan_monitor.ai.source_coverage_models import CoverageAssessment, NormalizationTrace
from trade_plan_monitor.ai.source_normalization import validate_normalization
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.daily_scope import scope_hash

_PINNED_SOURCE = "003043.SZ仅当五分钟收盘价高于10元时买入100股。"
# Captured before adding server-only coverage/preimage carriers in PMA-T06.
_V12_SCHEMA_SHA256 = "7a7d35473a44ebb8de02d6fea035b005c5b3d0774644f68aebc1ef455653c3f4"
_V12_PROMPT_SHA256 = "6649fd2feca4ad6d7384838ee66ede890afbdc647c9e54d39728abd571084b6f"
_CONTEXT_DECISION = dict(disposition="CONTEXT", paths=[], reason="Background commentary")


def _payload(draft, mapping):
    return dict(
        draft=draft.model_dump(mode="json"),
        clauses=[clause.model_dump(mode="json") for clause in mapping.clauses],
        bindings=[binding.model_dump(mode="json") for binding in mapping.bindings],
    )


def _current_config():
    # The complete existing P3 fixture needs more than the fixture's default
    # 60,000-character prompt budget. This remains below the product hard bound.
    return _config().model_copy(update={
        "prompt_version": "plan-extract-v12", "max_input_chars": 200_000,
    })


def _extract(source, payload):
    provider = _StaticProvider(canonical(payload))
    result = asyncio.run(extract_plan(
        request_id=_REQUEST_ID, source_text=source, config=_current_config(), provider=provider,
    ))
    assert provider.request is not None  # No accidental input-budget early exit.
    assert provider.request.config.prompt_version == "plan-extract-v12"
    return result


def test_server_only_coverage_keeps_the_exact_v12_prompt_and_output_schema():
    schema = canonical(CurrentPlanExtractionOutput.model_json_schema())
    prompt = build_current_plan_prompt(_PINNED_SOURCE)

    assert sha256(schema.encode("utf-8")).hexdigest() == _V12_SCHEMA_SHA256
    assert sha256(prompt.encode("utf-8")).hexdigest() == _V12_PROMPT_SHA256
    assert "_source_preimage_json" not in schema
    assert "normalization_trace" not in schema


def test_parser_keeps_the_admitted_original_draft_before_model_normalization():
    draft, _, mapping = _baseline()
    payload = _payload(draft, mapping)
    payload["draft"]["name"] = "  AI 原始显示名称  "
    original = canonical(payload["draft"])

    output = _parse_untrusted_output(canonical(payload), prompt_version="plan-extract-v12")

    assert output.draft.name == "AI 原始显示名称"
    assert output._source_preimage_json == original
    assert canonical(output.draft.model_dump(mode="json")) != original
    assert "_source_preimage_json" not in output.model_dump(mode="json")


def test_complete_new_ai_extraction_exposes_inspectable_server_coverage_and_raw_hashes():
    draft, source, mapping = _baseline()
    payload = _payload(draft, mapping)

    result = _extract(source, payload)

    assert isinstance(result, CurrentPlanExtractionResult)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft == draft
    assert result.daily_mapping == mapping
    assert result.validation_issues == ()
    assert isinstance(result.coverage, CoverageAssessment)
    assert isinstance(result.normalization_trace, NormalizationTrace)
    assert result.coverage.origin == "AI_NEW"
    assert result.coverage.coverage_complete is True
    assert result.coverage.automatic_fidelity_verified is True
    assert result.coverage.authority_granted is False
    assert result.coverage.source_hash == scope_hash(source)
    assert result.coverage.content_hash == daily_draft_content_sha256(result.draft)
    assert result.coverage.mapping_hash == daily_hash(
        "source-coverage-mapping-v1", result.daily_mapping.model_dump(mode="json"),
    )
    trace = result.normalization_trace
    assert trace.before_hash == daily_hash("source-normalization-candidate-v1", payload["draft"])
    assert trace.after_hash == trace.before_hash
    assert trace.changes == ()
    assert trace.evidence_hash == result.coverage.normalization_hash
    assert validate_normalization(trace, result.draft, source) == payload["draft"]


def test_actual_raw_display_normalization_is_audited_instead_of_fabricating_identity():
    draft, source, mapping = _baseline()
    payload = _payload(draft, mapping)
    payload["draft"]["name"] = "  AI 原始显示名称  "

    result = _extract(source, payload)

    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft.name == "AI 原始显示名称"
    trace = result.normalization_trace
    assert trace.before_hash == daily_hash("source-normalization-candidate-v1", payload["draft"])
    assert trace.after_hash != trace.before_hash
    assert [change.path for change in trace.changes] == ["name"]
    assert validate_normalization(trace, result.draft, source) == payload["draft"]
    assert result.coverage.automatic_fidelity_verified is True
    assert result.coverage.authority_granted is False


@pytest.mark.parametrize("text", [
    "Only buy when turnover exceeds 3 percent.",
    "仅当换手率超过3%时才允许买入。",
], ids=["english", "chinese"])
@pytest.mark.parametrize("role", ["COMMENTARY", "HISTORICAL", "ACCOUNT"])
def test_mandatory_condition_mislabeled_context_retains_candidate_and_blocks_review(text, role):
    draft, source, mapping = _baseline()
    changed_source, changed_mapping = _append_as_context(
        source, mapping, text, semantic_role=role, misclassification=_CONTEXT_DECISION,
    )
    assert build_daily_review(draft, changed_mapping, changed_source).issues == ()

    result = _extract(changed_source, _payload(draft, changed_mapping))

    assert isinstance(result, CurrentPlanExtractionResult)
    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft == draft
    assert result.source_text_sha256 == scope_hash(changed_source)
    assert result.daily_mapping == changed_mapping
    assert result.daily_mapping.clauses[-1].excerpt == text
    assert result.daily_mapping.clauses[-1].semantic_role == role
    assert result.coverage.status == "BLOCKED"
    assert result.coverage.coverage_complete is False
    assert result.coverage.automatic_fidelity_verified is False
    assert result.coverage.authority_granted is False
    assert any(
        issue.start >= len(source) + 1 and issue.end <= len(changed_source)
        for issue in result.coverage.issues
    )
    source_blockers = [issue for issue in result.validation_issues
                       if issue.code.startswith("SOURCE_")]
    assert source_blockers
    assert all(issue.activation_blocking for issue in source_blockers)
    assert "AI_FIELD_EVIDENCE_INVALID" not in {i.code for i in result.validation_issues}


def test_missing_original_preimage_never_becomes_automatic_fidelity_or_historical_origin():
    draft, source, mapping = _baseline()
    payload = _payload(draft, mapping)
    # Deliberately bypass the admitted raw JSON parser: this must not manufacture
    # an identity trace from the already normalized candidate.
    output = CurrentPlanExtractionOutput.model_validate_json(canonical(payload))
    config = _current_config()
    raw = RawAIResponse(
        request_id=_REQUEST_ID, provider_id=config.provider_id, model=config.model,
        content=canonical(payload), finish_reason="stop", usage=None, attempts=1,
    )

    result = _review_current_output(output, source, _REQUEST_ID, config, raw)

    assert result.status is PlanExtractionStatus.SUCCEEDED
    assert result.draft == draft and result.daily_mapping == mapping
    assert result.normalization_trace is None
    assert result.coverage.origin == "AI_NEW"
    assert result.coverage.status == "BLOCKED"
    assert result.coverage.automatic_fidelity_verified is False
    assert result.coverage.authority_granted is False
    assert any(i.code == "SOURCE_NORMALIZATION_LOSS" for i in result.coverage.issues)
    assert any(i.code == "SOURCE_NORMALIZATION_LOSS" and i.activation_blocking
               for i in result.validation_issues)


@pytest.mark.parametrize("copy_mode", ["shallow", "deep", "update"])
def test_internal_proof_survives_result_copies_without_entering_existing_payload(copy_mode):
    draft, source, mapping = _baseline()
    result = _extract(source, _payload(draft, mapping))
    if copy_mode == "update":
        copied = result.model_copy(update={"warnings": result.warnings})
    else:
        copied = result.model_copy(deep=copy_mode == "deep")

    assert copied.coverage == result.coverage
    assert copied.normalization_trace == result.normalization_trace
    assert copied.coverage.automatic_fidelity_verified is True
    for candidate in (result, copied):
        dumped = candidate.model_dump(mode="json")
        assert "coverage" not in dumped
        assert "normalization_trace" not in dumped
        assert "_source_preimage_json" not in dumped


@pytest.mark.parametrize("field", [
    "_source_preimage_json", "coverage", "normalization_trace", "origin",
])
def test_ai_cannot_supply_server_proof_or_select_a_historical_origin(field):
    draft, source, mapping = _baseline()
    payload = _payload(draft, mapping)
    payload[field] = "AI_HISTORICAL" if field == "origin" else "FORGED_SERVER_PROOF"

    result = _extract(source, payload)

    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert getattr(result, "coverage", None) is None
    assert getattr(result, "normalization_trace", None) is None
    assert "FORGED_SERVER_PROOF" not in result.model_dump_json()


@pytest.mark.parametrize("attack", ["changed_source_span", "wrong_binding_value", "extra_draft"])
def test_structurally_tampered_output_still_fails_instead_of_becoming_a_blocked_candidate(attack):
    draft, source, mapping = _baseline()
    payload = _payload(draft, mapping)
    if attack == "changed_source_span":
        payload["clauses"][0]["excerpt"] = "TAMPERED_SOURCE"
    elif attack == "wrong_binding_value":
        binding = next(item for item in payload["bindings"] if item["path"] == "symbol")
        binding["value"] = "600000.SH"
    else:
        payload["draft"]["execute_python"] = "TAMPERED_SOURCE"

    result = _extract(source, payload)

    assert result.status is PlanExtractionStatus.INVALID_OUTPUT
    assert result.draft is None
    assert getattr(result, "daily_mapping", None) is None
    assert getattr(result, "coverage", None) is None
    assert "TAMPERED_SOURCE" not in result.model_dump_json()
