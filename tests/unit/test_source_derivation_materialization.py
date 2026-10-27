"""Materialization retains private replay proof without rewriting historic review bytes.

All fixtures and derivation steps are local. These tests neither access a
provider/database nor confirm, activate or grant authority to a trading plan.
"""

import json
import socket
from datetime import timedelta
from hashlib import sha256

import pytest
from sqlalchemy.engine import Engine
from tests.unit.test_plan_delta_wire import delta
from tests.unit.test_plan_update_bindings import extraction_for, prior_review

from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionResult
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_derivation_replay import (
    expand_update_with_evidence,
    verify_update_derivation,
)
from trade_plan_monitor.ai.update_review import (
    MaterializedUpdateCandidate,
    build_update_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.plan_updates import materialize_plan_update
from trade_plan_monitor.domain.daily_hash import canonical

_BASE_HASH = "b" * 64
# Independent old review/serialization, captured before this PMA-T06 thin slice.
_LEGACY_REVIEW_HASH = "9ba1b6f53963a79efad4e34e3c590a3a987ae8d1aa66d3c11f766b4624b3e25e"
_LEGACY_EXTRACTION_HASH = "ac5028b092473cd707bcd1dc62c7a71d28507b0bb3ea9a4e02cdca0be6ed57db"
_LEGACY_PAYLOAD_SHA256 = "1d960d8289aac365f1bcd8523c815520c358f166586c2a5e72b38de7da653625"


def _case():
    base = prior_review()
    source, patch = delta("总持仓最多500股。", values={"max_qty": 500})
    context = context_from_review(base, _BASE_HASH)
    output, evidence = expand_update_with_evidence(
        canonical(patch.model_dump(mode="json")), source, context)
    extraction = extraction_for(base, source, output).model_copy(update={
        "source_derivation": evidence,
    })
    return base, source, context, extraction


def _resign(evidence, **updates):
    values = evidence.model_dump(mode="python", exclude={
        "evidence_hash", "raw_hash", "context_hash",
    })
    return SourceDerivationEvidence.build(**(values | updates))


def _assert_retained_but_blocked(candidate, base, source, extraction, code):
    expected_review = build_update_review(base, source, extraction.output)
    assert expected_review.issues == ()
    assert candidate.review == expected_review
    assert candidate.review.draft.position.max_qty == 500
    assert candidate.extraction.evidence_hash == extraction.evidence_hash
    prepared = candidate.to_preparation_candidate()
    assert prepared.validation == "UNRESOLVED"
    assert any(code in issue for issue in prepared.issues)
    assert any(code in issue for issue in candidate.extraction.derivation_issues)
    assert prepared.evidence_hash == expected_review.evidence_hash


def test_materialization_retains_and_verifies_the_original_proof_then_appends_its_stage():
    base, source, context, extraction = _case()

    candidate = materialize_extraction(base, _BASE_HASH, source, extraction)

    assert extraction.source_derivation is not None
    assert len(extraction.source_derivation.stages) == 2
    assert candidate.extraction.source_derivation is not None
    assert [stage.phase for stage in candidate.extraction.source_derivation.stages] == [
        "DELTA_EXPANDED", "SOURCE_NORMALIZED", "MATERIALIZED",
    ]
    proof = candidate.extraction.source_derivation
    assert proof.stages[:2] == extraction.source_derivation.stages
    assert proof.raw_json == extraction.source_derivation.raw_json
    assert proof.context_json == canonical(context.model_dump(mode="json"))
    assert proof.stages[2].output_json == canonical(
        materialize_plan_update(context.snapshot, extraction.output).model_dump(mode="json"))
    assert proof.authority_granted is False
    assert verify_update_derivation(proof, source, context, extraction.output) == extraction.output
    assert candidate.review == build_update_review(base, source, extraction.output)
    assert candidate.to_preparation_candidate().validation == "VALID"


def test_private_derivation_does_not_change_old_review_extraction_hash_or_frozen_payload():
    base, source, _, extraction = _case()
    old_extraction = PlanUpdateExtractionResult.model_validate(extraction.model_dump(mode="python"))
    old_review = build_update_review(base, source, old_extraction.output)
    old_candidate = MaterializedUpdateCandidate(extraction=old_extraction, review=old_review)
    old_payload = old_candidate.to_preparation_candidate().payload_json

    candidate = materialize_extraction(base, _BASE_HASH, source, extraction)
    prepared = candidate.to_preparation_candidate()

    assert candidate.review == old_review
    assert candidate.review.evidence_hash == _LEGACY_REVIEW_HASH
    assert candidate.extraction.evidence_hash == _LEGACY_EXTRACTION_HASH
    assert prepared.payload_json == old_payload
    assert sha256(prepared.payload_json.encode("utf-8")).hexdigest() == _LEGACY_PAYLOAD_SHA256
    assert len(prepared.payload_json.encode("utf-8")) == 32760
    encoded_extraction = candidate.model_dump(mode="json")["extraction"]
    assert "source_derivation" not in encoded_extraction
    assert "derivation_issues" not in encoded_extraction


def test_repeated_materialization_revalidates_three_stages_without_changing_history():
    base, source, _, extraction = _case()
    first = materialize_extraction(base, _BASE_HASH, source, extraction)

    repeated = materialize_extraction(base, _BASE_HASH, source, first.extraction)

    assert repeated.extraction.source_derivation is not None
    assert len(repeated.extraction.source_derivation.stages) == 3
    assert repeated.extraction.source_derivation == first.extraction.source_derivation
    assert repeated.review == first.review
    assert repeated.to_preparation_candidate() == first.to_preparation_candidate()


@pytest.mark.parametrize("copy_mode", ["shallow", "deep", "update"])
def test_materialized_candidate_copies_keep_nested_private_proof_and_blockers(copy_mode):
    base, source, _, extraction = _case()
    extraction = extraction.model_copy(update={"derivation_issues": ("SOURCE_NORMALIZATION_LOSS",)})
    candidate = materialize_extraction(base, _BASE_HASH, source, extraction)

    if copy_mode == "update":
        copied = candidate.model_copy(update={"review": candidate.review})
    else:
        copied = candidate.model_copy(deep=copy_mode == "deep")

    assert copied.extraction.source_derivation is not None
    assert copied.extraction.source_derivation == candidate.extraction.source_derivation
    assert copied.extraction.derivation_issues == candidate.extraction.derivation_issues
    assert copied.to_preparation_candidate().validation == "UNRESOLVED"
    assert "SOURCE_NORMALIZATION_LOSS" in copied.to_preparation_candidate().issues


@pytest.mark.parametrize("attack", ["stage", "raw_operations", "context", "broken_hash"])
def test_illegal_private_proof_retains_valid_review_but_blocks_preparation(attack):
    base, source, _, extraction = _case()
    proof = extraction.source_derivation
    if attack == "stage":
        stages = list(proof.stages)
        changed = json.loads(stages[1].output_json)
        changed["operations"][0]["action"] = "RETAIN"  # Draft and old evidence stay unchanged.
        stages[1] = DerivationStage.build(phase="SOURCE_NORMALIZED", output_json=canonical(changed))
        forged = _resign(proof, stages=tuple(stages))
    elif attack == "raw_operations":
        changed = json.loads(proof.raw_json)
        changed["operations"][0]["values"]["max_qty"] = 600
        forged = _resign(proof, raw_json=canonical(changed))
    elif attack == "context":
        changed = json.loads(proof.context_json)
        changed["snapshot"]["position"]["max_qty"] = 900
        forged = _resign(proof, context_json=canonical(changed))
    else:
        forged = proof.model_copy(deep=True)
        # Model a corrupt internally loaded sidecar, bypassing constructor checks
        # only in this test. Public extraction identity is still valid.
        object.__setattr__(forged, "evidence_hash", "0" * 64)
    if attack != "broken_hash":
        assert SourceDerivationEvidence.model_validate_json(forged.model_dump_json()) == forged
    object.__setattr__(extraction, "source_derivation", forged)

    candidate = materialize_extraction(base, _BASE_HASH, source, extraction)

    _assert_retained_but_blocked(candidate, base, source, extraction, "SOURCE_NORMALIZATION_LOSS")
    assert extraction.source_derivation == forged  # No repair or mutation of the input proof.


def test_rehashed_public_extraction_still_checks_the_full_output_against_original_private_proof():
    base, source, _, extraction = _case()
    changed_output = extraction.output.model_copy(update={
        "warnings": ({"path": "position", "material": False,
                      "message": "Later output addition absent from the original response."},),
    })
    assert changed_output.draft == extraction.output.draft
    changed_extraction = extraction_for(base, source, changed_output).model_copy(update={
        "source_derivation": extraction.source_derivation,
    })
    assert changed_extraction.evidence_hash != extraction.evidence_hash

    candidate = materialize_extraction(base, _BASE_HASH, source, changed_extraction)

    _assert_retained_but_blocked(
        candidate, base, source, changed_extraction, "SOURCE_NORMALIZATION_LOSS")


@pytest.mark.parametrize("with_proof", [False, True])
@pytest.mark.parametrize("code", ["SOURCE_NORMALIZATION_LOSS", "SOURCE_COVERAGE_LIMIT_EXCEEDED"])
def test_existing_derivation_blockers_survive_reconstruction_even_with_valid_proof(
    code, with_proof,
):
    base, source, _, extraction = _case()
    extraction = extraction.model_copy(update={
        "derivation_issues": (code,),
        "source_derivation": extraction.source_derivation if with_proof else None,
    })

    candidate = materialize_extraction(base, _BASE_HASH, source, extraction)

    _assert_retained_but_blocked(candidate, base, source, extraction, code)
    assert code in candidate.extraction.derivation_issues


def test_materialization_evidence_limit_failure_keeps_candidate_and_a_limit_blocker(monkeypatch):
    import trade_plan_monitor.ai.source_derivation_replay as replay

    base, source, _, extraction = _case()

    def reject_expansion(*args, **kwargs):
        raise ValueError("SOURCE_COVERAGE_LIMIT_EXCEEDED")

    monkeypatch.setattr(replay, "append_materialized_derivation", reject_expansion)

    candidate = materialize_extraction(base, _BASE_HASH, source, extraction)

    _assert_retained_but_blocked(
        candidate, base, source, extraction, "SOURCE_COVERAGE_LIMIT_EXCEEDED")


@pytest.mark.parametrize("field", [
    "source_id", "effective_trade_date", "available_at", "authored_at",
])
def test_same_text_with_different_source_metadata_still_fails_the_existing_outer_binding(field):
    base, source, _, extraction = _case()
    if field == "source_id":
        value = "different-same-text-source"
    elif field == "effective_trade_date":
        value = source.effective_trade_date + timedelta(days=1)
    elif field == "available_at":
        value = source.available_at + timedelta(minutes=1)
    else:
        value = source.authored_at - timedelta(minutes=1)
    changed_source = source.model_copy(update={field: value})
    assert changed_source.text == source.text
    assert changed_source.source_hash == source.source_hash
    assert changed_source.binding_hash != source.binding_hash

    with pytest.raises(ValueError, match="source or predecessor"):
        materialize_extraction(base, _BASE_HASH, changed_source, extraction)


@pytest.mark.parametrize("attack", ["extraction_hash", "base_hash", "provider_output"])
def test_private_proof_does_not_waive_original_public_extraction_integrity(attack):
    base, source, _, extraction = _case()
    if attack == "extraction_hash":
        extraction = extraction.model_copy(update={"evidence_hash": "0" * 64})
    elif attack == "base_hash":
        extraction = extraction.model_copy(update={"base_hash": "c" * 64})
    else:
        changed = extraction.output.model_copy(update={
            "warnings": ({"path": "position", "material": True,
                          "message": "Changed after the original public evidence hash."},),
        })
        extraction = extraction.model_copy(update={"output": changed})

    with pytest.raises(ValueError, match="source or predecessor"):
        materialize_extraction(base, _BASE_HASH, source, extraction)


@pytest.mark.parametrize("historical", [False, True])
def test_legacy_payload_with_no_private_fields_keeps_original_defaults_and_review(historical):
    base, source, _, extraction = _case()
    legacy = PlanUpdateExtractionResult.model_validate_json(extraction.model_dump_json())
    assert legacy.source_derivation is None and legacy.derivation_issues == ()

    candidate = materialize_extraction(base, _BASE_HASH, source, legacy, historical=historical)
    prepared = candidate.to_preparation_candidate()
    decoded = MaterializedUpdateCandidate.model_validate_json(prepared.payload_json)

    assert candidate.extraction.source_derivation is None
    assert candidate.extraction.derivation_issues == ()
    assert decoded == candidate
    assert decoded.to_preparation_candidate().validation == prepared.validation == "VALID"
    assert candidate.review.evidence_hash == _LEGACY_REVIEW_HASH
    assert sha256(prepared.payload_json.encode("utf-8")).hexdigest() == _LEGACY_PAYLOAD_SHA256


def test_materialization_and_preparation_do_not_call_provider_network_or_database(monkeypatch):
    base, source, _, extraction = _case()

    def forbidden(*args, **kwargs):
        raise AssertionError("Materialization attempted provider, network or database I/O")

    monkeypatch.setattr(OpenAICompatibleProvider, "extract_plan", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(Engine, "connect", forbidden)

    candidate = materialize_extraction(base, _BASE_HASH, source, extraction)

    assert candidate.extraction.source_derivation is not None
    assert candidate.extraction.source_derivation.authority_granted is False
    assert candidate.to_preparation_candidate().evidence_hash == _LEGACY_REVIEW_HASH
