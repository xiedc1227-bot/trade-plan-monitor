"""Update extraction retains private raw-patch evidence outside historical payloads."""

import asyncio
import json
from hashlib import sha256
from uuid import UUID

import pytest
from tests.unit.test_ai_plan_extraction_v4 import _config, _StaticProvider
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_plan_update_bindings import prior_review

from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_delta_wire import expand_delta_output
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateContext,
    PlanUpdateExtractionResult,
    extract_plan_update,
)
from trade_plan_monitor.ai.source_derivation import SourceDerivationEvidence
from trade_plan_monitor.ai.update_review import context_from_review
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_scope import scope_hash

_REQUEST_ID = UUID("a613157d-3ad0-4560-967f-62cc6334e343")


def _response_inputs():
    source, patch = delta("总持仓最多500股。", values={"max_qty": 500})
    context = context_from_review(prior_review(), "b" * 64)
    raw_json = " \n" + json.dumps(patch.model_dump(mode="json"), ensure_ascii=False,
                                  indent=2) + "\n\t"
    assert "draft" not in json.loads(raw_json)
    return source, context, patch, raw_json


def _extract(*, context=None):
    source, original_context, patch, raw_json = _response_inputs()
    context = context or original_context
    provider = _StaticProvider(raw_json)
    result = asyncio.run(extract_plan_update(
        request_id=_REQUEST_ID, source=source, context=context, config=_config(),
        provider=provider, compact=True,
    ))
    assert provider.request is not None
    assert result.status == PlanExtractionStatus.SUCCEEDED
    assert isinstance(result, PlanUpdateExtractionResult)
    assert result.output.draft.position.max_qty == 500
    return result, source, context, patch, raw_json


def _legacy_hash(result, source, context):
    return sha256(canonical_json({
        "domain": "monitor-loop-update-evidence-v1", "source_binding_hash": source.binding_hash,
        "context": context, "output": result.output,
    }).encode("utf-8")).hexdigest()


def test_delta_extraction_preserves_exact_raw_patch_and_actual_normalized_output():
    result, source, context, patch, raw_json = _extract()

    evidence = result.source_derivation
    assert isinstance(evidence, SourceDerivationEvidence)
    assert evidence.kind == "PREDECESSOR_PATCH"
    assert evidence.raw_json == raw_json
    assert evidence.raw_json != canonical(json.loads(raw_json))
    assert "draft" not in json.loads(evidence.raw_json)
    assert evidence.raw_hash == scope_hash(raw_json)
    assert evidence.source_hash == source.source_hash
    assert evidence.context_json == canonical(context.model_dump(mode="json"))
    assert evidence.context_hash == scope_hash(evidence.context_json)
    assert evidence.base_hash == context.base_hash
    assert [stage.phase for stage in evidence.stages] == ["DELTA_EXPANDED", "SOURCE_NORMALIZED"]
    assert evidence.stages[0].output_json == canonical(
        expand_delta_output(patch, context).model_dump(mode="json"))
    assert evidence.stages[1].output_json == canonical(result.output.model_dump(mode="json"))
    assert evidence.authority_granted is False
    assert result.derivation_issues == ()
    assert result.evidence_hash == _legacy_hash(result, source, context)


@pytest.mark.parametrize("deep", [False, True])
@pytest.mark.parametrize("update", [None, {"usage": None}])
def test_result_copies_keep_private_derivation_and_diagnostic(deep, update):
    result, _, _, _, _ = _extract()
    assert result.source_derivation is not None
    assert result.diagnostic is not None

    copied = result.model_copy(update=update, deep=deep)

    assert copied.source_derivation == result.source_derivation
    assert copied.derivation_issues == result.derivation_issues
    assert copied.diagnostic == result.diagnostic
    assert copied.evidence_hash == result.evidence_hash
    assert copied.model_dump_json() == result.model_dump_json()


def test_private_derivation_stays_outside_existing_result_and_preparation_payloads():
    result, source, context, _, _ = _extract()
    assert result.source_derivation is not None

    candidate = result.to_preparation_candidate()
    serialized = result.model_dump(mode="json")
    assert "source_derivation" not in serialized
    assert "derivation_issues" not in serialized
    assert "diagnostic" not in serialized
    assert json.loads(candidate.payload_json) == json.loads(canonical_json(result))
    assert candidate.evidence_hash == result.evidence_hash == _legacy_hash(result, source, context)
    assert candidate.validation == "UNRESOLVED"
    assert candidate.issues == ("UPDATE_MATERIALIZATION_REQUIRED",)
    assert "source-derivation-v1" not in candidate.payload_json


def test_old_result_json_without_private_fields_keeps_its_exact_historical_defaults():
    result, _, _, _, _ = _extract()
    historical_json = result.model_dump_json()

    restored = PlanUpdateExtractionResult.model_validate_json(historical_json)

    assert restored.source_derivation is None
    assert restored.derivation_issues == ()
    assert restored.model_dump_json() == historical_json
    assert restored.to_preparation_candidate().issues == ("UPDATE_MATERIALIZATION_REQUIRED",)


def test_private_derivation_failure_does_not_erase_a_legal_update_candidate(monkeypatch):
    def reject_unregistered_derivation(cls, **values):
        raise ValueError("unregistered private derivation representation")

    monkeypatch.setattr(SourceDerivationEvidence, "build",
                        classmethod(reject_unregistered_derivation))

    result, source, context, _, _ = _extract()

    assert result.source_derivation is None
    assert "SOURCE_NORMALIZATION_LOSS" in result.derivation_issues
    assert result.evidence_hash == _legacy_hash(result, source, context)
    assert "SOURCE_NORMALIZATION_LOSS" in result.to_preparation_candidate().issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"
    assert result.diagnostic is not None


def test_oversize_private_context_preserves_the_candidate_with_an_explicit_limit_issue():
    _, context, _, _ = _response_inputs()
    data = context.model_dump(mode="json")
    data["evidence"] = [{
        "path": "position.max_qty", "source_id": "first", "source_hash": "a" * 64,
        "clause_id": "synthetic-bounded-prior-evidence", "start": 0, "end": 512,
        "excerpt": "x" * 512,
    }] * 2000
    context = PlanUpdateContext.model_validate_json(canonical(data))
    assert len(canonical(context.model_dump(mode="json")).encode("utf-8")) > 1024 * 1024

    result, source, _, _, _ = _extract(context=context)

    assert result.source_derivation is None
    assert "SOURCE_COVERAGE_LIMIT_EXCEEDED" in result.derivation_issues
    assert result.evidence_hash == _legacy_hash(result, source, context)
    assert "SOURCE_COVERAGE_LIMIT_EXCEEDED" in result.to_preparation_candidate().issues
    assert result.to_preparation_candidate().validation == "UNRESOLVED"


def test_copy_keeps_failed_private_derivation_issues_without_serializing_them(monkeypatch):
    def reject_unregistered_derivation(cls, **values):
        raise ValueError("unregistered private derivation representation")

    monkeypatch.setattr(SourceDerivationEvidence, "build",
                        classmethod(reject_unregistered_derivation))
    result, _, _, _, _ = _extract()
    assert result.derivation_issues

    copied = result.model_copy(update={"usage": None}, deep=True)

    assert copied.derivation_issues == result.derivation_issues
    assert copied.source_derivation is None
    assert copied.diagnostic == result.diagnostic
    assert "derivation_issues" not in copied.model_dump(mode="json")
    assert set(result.derivation_issues) <= set(copied.to_preparation_candidate().issues)
