"""Private preparation proof identity is distinct from the immutable old payload."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest.preparation_assurance_store import PreparationInputEvidence
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

NOW = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def proof(**changes):
    values = dict(preparation_id="preparation-1", item_index=0, attempt_id="attempt-1",
        source_binding_hash="b" * 64, candidate_hash="c" * 64,
        inputs=CoverageInputs.build(source_hash="a" * 64, source_binding_hash="b" * 64),
        created_at=NOW)
    return PreparationInputEvidence.build(**(values | changes))


def test_attempt_key_is_stable_but_complete_proof_includes_its_capture_time():
    original = proof()
    later = proof(created_at=NOW + timedelta(seconds=1))
    assert original.evidence_key == later.evidence_key
    assert original.evidence_hash != later.evidence_hash
    assert original.authority_granted is False
    assert original.kind == "INPUT"
    assert type(original).model_validate_json(original.model_dump_json()) == original


@pytest.mark.parametrize("field,value", [
    ("preparation_id", "different"), ("item_index", 1), ("attempt_id", "different"),
])
def test_attempt_identity_changes_the_server_key(field, value):
    assert proof(**{field: value}).evidence_key != proof().evidence_key


def test_same_attempt_different_private_input_changes_proof_without_changing_key():
    different = CoverageInputs.build(source_hash="f" * 64, source_binding_hash="b" * 64)
    assert proof(inputs=different).evidence_key == proof().evidence_key
    assert proof(inputs=different).evidence_hash != proof().evidence_hash


def test_source_metadata_binding_must_match_the_captured_input():
    with pytest.raises(ValueError, match="binding"):
        proof(source_binding_hash="0" * 64)


@pytest.mark.parametrize("field,value", [("evidence_hash", "0" * 64),
                                        ("evidence_key", "0" * 64), ("item_index", True)])
def test_signed_fields_and_strict_item_identity_are_verified(field, value):
    raw = proof().model_dump(mode="json") | {field: value}
    with pytest.raises(ValueError):
        PreparationInputEvidence.model_validate(raw)
