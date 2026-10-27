"""Preparation worker retains private inputs across its JSON trust-boundary roundtrip.

Only disposable worker stores and local fake extractors are used. This proves
in-memory evidence carriage, not durable assurance, C03 acceptance or live accuracy.
"""

import json
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from tests.integration.test_plan_preparation_worker import (
    collection_update_result,
    collection_worker_setup,
    work_claim,
)
from tests.integration.test_source_coverage_authority_save import _ai_result
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_source_coverage_baseline import _baseline

from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionResult,
    OpeningAccountFacts,
    _missing_account_issues,
)
from trade_plan_monitor.ai.source_derivation_replay import (
    expand_update_with_evidence,
    verify_update_derivation,
)
from trade_plan_monitor.ai.update_review import materialize_extraction
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import CancellationToken
from trade_plan_monitor.backtest.jobs import BacktestJobRepository
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.backtest.preparation_worker import (
    PreparationCallOutcome,
    PreparationExtractor,
    run_attempt,
)
from trade_plan_monitor.domain.daily_hash import canonical

_NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _initial_setup(tmp_path, *, with_normalization=True):
    draft, text, mapping = _baseline()
    source = PreparationSource(source_id="private-initial", text=text,
        available_at=_NOW, effective_trade_date=_NOW.date())
    store = PreparationStore(tmp_path / "preparation.sqlite3", clock=lambda: _NOW)
    jobs = BacktestJobRepository(tmp_path / "results.sqlite3", clock=lambda: _NOW)
    initial = store.create(SinglePlanPreparationInput(preparation_id="one", sources=(source,)),
                           idempotency_key="create")
    claim = work_claim(jobs, initial)
    running = store.start_attempt("one", expected_revision=initial.revision,
                                  idempotency_key="start", work_claim=claim)
    current = _ai_result(draft, text, mapping, with_normalization=with_normalization)
    account = OpeningAccountFacts(inventory_quantity=None, lots=(), cash_fen=None, snapshot_at=None)
    evidence_hash = sha256(canonical_json(dict(domain="monitor-loop-extraction-evidence-v1",
        source_binding_hash=source.binding_hash, plan_mapping=mapping,
        opening_account=account)).encode()).hexdigest()
    result = LoopPlanExtractionResult(**(current.model_dump(mode="python") | dict(
        request_id=claim.generation,
        validation_issues=(*current.validation_issues, *_missing_account_issues(account, source)),
    )), coverage=current.coverage, normalization_trace=current.normalization_trace,
        source_id=source.source_id, source_binding_hash=source.binding_hash,
        authored_at=source.authored_at, available_at=source.available_at,
        effective_trade_date=source.effective_trade_date, opening_account=account,
        evidence_hash=evidence_hash)
    return store, jobs, running, result


def test_initial_worker_roundtrip_carries_real_normalization_and_coverage(tmp_path):
    store, jobs, running, original = _initial_setup(tmp_path)

    outcome = run_attempt(store, jobs, running,
        PreparationExtractor(lambda identity, source, token: original), CancellationToken())

    assert outcome.unknown is False and outcome.result is not None
    assert outcome.inputs is not None
    assert outcome.inputs.normalization == original.normalization_trace
    assert outcome.inputs.initial_coverage == original.coverage
    assert outcome.inputs.source_binding_hash == running.source.binding_hash
    assert outcome.inputs.source_hash == running.source.source_hash
    assert outcome.result.coverage == original.coverage
    assert outcome.result.normalization_trace == original.normalization_trace
    assert outcome.result.model_dump_json() == original.model_dump_json()
    prepared = outcome.candidate or outcome.result.to_preparation_candidate()
    expected = original.to_preparation_candidate()
    assert prepared.payload_json == expected.payload_json
    assert prepared.evidence_hash == expected.evidence_hash
    assert "coverage" not in json.loads(prepared.payload_json)
    assert "normalization_trace" not in json.loads(prepared.payload_json)
    assert outcome.inputs.authority_granted is False


def test_initial_missing_raw_normalization_does_not_manufacture_a_trace_from_the_final_draft(
    tmp_path,
):
    store, jobs, running, original = _initial_setup(tmp_path, with_normalization=False)
    assert original.coverage.status == "BLOCKED"

    outcome = run_attempt(store, jobs, running,
        PreparationExtractor(lambda identity, source, token: original), CancellationToken())

    assert outcome.unknown is False and outcome.result is not None
    assert outcome.result.normalization_trace is None
    assert outcome.inputs.normalization is None
    assert outcome.inputs.initial_coverage == original.coverage
    assert outcome.inputs.initial_coverage.automatic_fidelity_verified is False
    assert outcome.inputs.authority_granted is False


def _successor_outcome(tmp_path, *, issues=(), with_derivation=True):
    store, jobs, running, base, old_output = collection_worker_setup(tmp_path)
    observed = {}

    def extract(identity, source, token, *, context):
        # Use the actual current source and trusted context supplied by the
        # worker, never a future item or a regenerated predecessor hash.
        _, patch = delta(source.text, values={"max_qty": 300})
        raw = json.dumps(patch.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        output, derivation = expand_update_with_evidence(raw, source, context)
        if not with_derivation:
            output = old_output
        result = collection_update_result(base, source, output, identity, context)
        result = result.model_copy(update={
            "source_derivation": derivation if with_derivation else None,
            "derivation_issues": issues,
        })
        expected = materialize_extraction(base, context.base_hash, source, result)
        observed.update(raw=raw, context=context, source=source, result=result, expected=expected)
        return result

    outcome = run_attempt(store, jobs, running, PreparationExtractor(extract), CancellationToken())
    return outcome, observed, store, running


def test_successor_worker_retains_admitted_delta_and_materialized_derivation_inputs(tmp_path):
    outcome, observed, store, running = _successor_outcome(tmp_path)
    original, expected = observed["result"], observed["expected"]
    assert "draft" not in json.loads(observed["raw"])

    assert not outcome.unknown and outcome.error_code is None
    assert outcome.result is not None and outcome.inputs is not None
    assert outcome.result.source_derivation is not None
    assert outcome.result.source_derivation.raw_json == original.source_derivation.raw_json
    assert outcome.result.source_derivation.stages[:2] == original.source_derivation.stages
    assert outcome.inputs.source_hash == observed["source"].source_hash
    assert outcome.inputs.source_binding_hash == observed["source"].binding_hash
    proof = outcome.inputs.derivation
    assert proof is not None and proof.authority_granted is False
    assert [stage.phase for stage in proof.stages] == [
        "DELTA_EXPANDED", "SOURCE_NORMALIZED", "MATERIALIZED",
    ]
    assert proof.raw_json == observed["raw"]
    assert proof.context_json == canonical(observed["context"].model_dump(mode="json"))
    assert proof.base_hash == running.work_claim.base_hash
    assert verify_update_derivation(proof, observed["source"], observed["context"],
                                    original.output) == original.output
    expected_candidate = expected.to_preparation_candidate()
    assert outcome.candidate == expected_candidate
    assert outcome.candidate.validation == "VALID"
    payload = json.loads(outcome.candidate.payload_json)
    assert "source_derivation" not in canonical(payload)
    assert "derivation_issues" not in canonical(payload)
    assert outcome.result.model_dump_json() == original.model_dump_json()
    assert store.get(running.preparation_id).items[1].candidate is None
    assert len(original.source_derivation.stages) == 2  # No mutation of the original response.


@pytest.mark.parametrize("code", ["SOURCE_NORMALIZATION_LOSS", "SOURCE_COVERAGE_LIMIT_EXCEEDED"])
def test_successor_private_blockers_survive_json_roundtrip_and_remain_typed_input_issues(
    code, tmp_path,
):
    outcome, observed, _, _ = _successor_outcome(tmp_path, issues=(code,))

    assert not outcome.unknown and outcome.error_code is None
    assert outcome.result.derivation_issues == (code,)
    assert code in {issue.code for issue in outcome.inputs.derivation_issues}
    assert outcome.inputs.derivation.stages[-1].phase == "MATERIALIZED"
    assert outcome.inputs.authority_granted is False
    assert outcome.candidate.validation == "UNRESOLVED"
    assert code in outcome.candidate.issues
    assert outcome.candidate == observed["expected"].to_preparation_candidate()


def test_successor_without_original_derivation_does_not_invent_raw_or_normalization_inputs(
    tmp_path,
):
    outcome, observed, _, _ = _successor_outcome(tmp_path, with_derivation=False)

    assert not outcome.unknown and outcome.result is not None
    assert outcome.result.source_derivation is None
    assert outcome.inputs.derivation is None and outcome.inputs.normalization is None
    assert outcome.inputs.authority_granted is False
    expected = observed["expected"].to_preparation_candidate()
    assert outcome.candidate.payload_json == expected.payload_json


def test_wrong_source_binding_does_not_expose_private_inputs_or_a_candidate(tmp_path):
    store, jobs, running, original = _initial_setup(tmp_path)
    wrong = original.model_copy(update={"source_binding_hash": "0" * 64})

    outcome = run_attempt(store, jobs, running,
        PreparationExtractor(lambda identity, source, token: wrong), CancellationToken())

    assert outcome.unknown is True
    assert outcome.candidate is None and outcome.inputs is None


def test_no_result_outcome_has_no_private_input_by_default():
    assert PreparationCallOutcome().inputs is None
    assert PreparationCallOutcome(unknown=True).inputs is None
