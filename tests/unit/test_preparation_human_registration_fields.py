"""Additive registration bindings preserve every byte of unregistered artifacts.

The temporary storage fixtures retain actual server before/after checkpoints.
These fields prove structural correspondence only; the state adapter owns actual
command/response authentication and no model field is a registration permission.
"""

from datetime import timedelta
from hashlib import sha256
from itertools import combinations

import pytest
from pydantic import ValidationError
from tests.integration.test_preparation_human_assurance_storage import _operation, _values

from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation

_REGISTRATION = dict(command_id="synthetic-current-human-command",
                     command_request_hash="a" * 64, after_record_hash="b" * 64)
_BASELINES = {
    "present": (162485, "720ba4a7ded9eb79566a1b927bdfd4d85d31cb17dd1a05004440f8d67ffb8c4d",
                "91b84f9c934332e7b082a4a0cedbced82565cfe7b1ff20733bba16511c72934e"),
    "missing": (162299, "7d5da232c0141a70c4a0245ba8ee4c1211b7fdd4056dff6c8a08c09e04c33515",
                "87cb168ccef75c5b07ece263efffcb797f51ac0df4fcf9b3fbf3277105237815"),
    "present_later": (162485, "fac779d8391d43f4f18b05d6679a8c167abc99a1fd9583bebbe774c5e60df4be",
                      "706cc840207b7c914476a92f052b17635afe62ca4186d638840b4577b1b83b20"),
    "missing_later": (162299, "47bcf4e554d15cfda78f1a0f6faf8ef44f7f2f1d807926d3a85d68d72889a9b6",
                      "eb352fd0e5374325c33d8e1038d67d3a81428448928450f95dc44137b48b26ae"),
}


def _replace(value, **updates):
    return PreparationHumanOperation.build(**(
        {name: getattr(value, name) for name in type(value).model_fields
         if name not in {"evidence_key", "evidence_hash"}} | updates))


def _legacy(tmp_path, kind="present"):
    if kind.startswith("present"):
        _, value = _operation(tmp_path)
    else:
        _, values = _values(tmp_path, missing=True)
        value = PreparationHumanOperation.build(**values)
    return (_replace(value, created_at=value.created_at + timedelta(minutes=1))
            if kind.endswith("later") else value)


@pytest.mark.parametrize("kind", _BASELINES)
def test_frozen_legacy_full_json_and_evidence_hash_are_byte_identical(kind, tmp_path):
    """Frozen before adding any registration field to the production model."""
    value = _legacy(tmp_path, kind)
    wire = value.model_dump_json().encode()
    length, wire_hash, evidence_hash = _BASELINES[kind]

    assert len(wire) == length and sha256(wire).hexdigest() == wire_hash
    assert value.evidence_hash == evidence_hash
    restored = PreparationHumanOperation.model_validate_json(wire)
    assert restored.model_dump_json().encode() == wire
    assert _REGISTRATION.keys().isdisjoint(value.model_dump(mode="json"))


def test_all_three_registration_fields_are_structural_and_included_in_the_full_proof(tmp_path):
    legacy = _legacy(tmp_path)

    bound = _replace(legacy, **_REGISTRATION)

    assert bound.command_id == _REGISTRATION["command_id"]
    assert bound.command_request_hash == _REGISTRATION["command_request_hash"]
    assert bound.after_record_hash == _REGISTRATION["after_record_hash"]
    assert bound.evidence_key == legacy.evidence_key and bound.evidence_hash != legacy.evidence_hash
    assert bound.original_candidate == legacy.original_candidate
    assert bound.original_input_state == legacy.original_input_state
    assert bound.authority_granted is False
    assert bound.version == legacy.version == "preparation-human-operation-v1"


@pytest.mark.parametrize("field", _REGISTRATION)
def test_builder_cannot_turn_python_bytes_into_a_valid_registration_string(tmp_path, field):
    legacy = _legacy(tmp_path)
    changes = _REGISTRATION | {field: _REGISTRATION[field].encode()}

    with pytest.raises(ValueError):
        _replace(legacy, **changes)


@pytest.mark.parametrize("present", [
    names for count in (1, 2) for names in combinations(_REGISTRATION, count)
])
def test_registration_fields_must_be_present_together_or_absent_together(tmp_path, present):
    legacy = _legacy(tmp_path)

    with pytest.raises(ValueError, match="registration binding is incomplete"):
        _replace(legacy, **{name: _REGISTRATION[name] for name in present})


def test_explicit_all_none_is_legacy_and_is_not_serialized_even_in_python_mode(tmp_path):
    legacy = _legacy(tmp_path)

    explicit = _replace(legacy, **dict.fromkeys(_REGISTRATION))

    assert explicit.evidence_hash == legacy.evidence_hash
    assert explicit.model_dump_json() == legacy.model_dump_json()
    assert all(getattr(explicit, name) is None for name in _REGISTRATION)
    assert _REGISTRATION.keys().isdisjoint(explicit.model_dump(mode="python"))


@pytest.mark.parametrize("field", _REGISTRATION)
@pytest.mark.parametrize("bad", [True, 42, 1.5, [], {}, b"bytes-are-not-json-strings"])
def test_registration_json_field_types_are_strict_before_hash_validation(tmp_path, field, bad):
    legacy = _legacy(tmp_path)
    payload = legacy.model_dump(mode="python") | _REGISTRATION | {field: bad}

    with pytest.raises(ValidationError) as error:
        PreparationHumanOperation.model_validate(payload)

    assert any(row["loc"] == (field,) for row in error.value.errors())
    with pytest.raises(ValueError, match="strict strings"):
        _replace(legacy, **(_REGISTRATION | {field: bad}))


@pytest.mark.parametrize("field,bad", [
    ("command_id", ""), ("command_id", "invalid command id"), ("command_id", "c" * 129),
    ("command_request_hash", "a" * 63), ("command_request_hash", "A" * 64),
    ("after_record_hash", "b" * 65), ("after_record_hash", "g" * 64),
])
def test_registration_identifier_and_hash_constraints_are_preserved(tmp_path, field, bad):
    legacy = _legacy(tmp_path)

    with pytest.raises(ValidationError) as error:
        PreparationHumanOperation.model_validate(
            legacy.model_dump(mode="python") | _REGISTRATION | {field: bad})

    assert any(row["loc"] == (field,) for row in error.value.errors())


def test_fields_are_included_in_intent_but_cannot_claim_registration_or_authority(tmp_path):
    legacy = _legacy(tmp_path)
    bound = _replace(legacy, **_REGISTRATION)
    assert all(bound.intent()[name] == value for name, value in _REGISTRATION.items())
    assert bound.authority_granted is False
    assert {"registered", "registration_verified", "status", "coverage_complete"}.isdisjoint(
        type(bound).model_fields)
    for change in ({"authority_granted": True}, {"registered": True}):
        with pytest.raises(ValueError):
            PreparationHumanOperation.model_validate(bound.model_dump(mode="python") | change)


@pytest.mark.parametrize("field", _REGISTRATION)
def test_changed_registration_changes_intent_and_proof_but_not_the_legacy_slot(tmp_path, field):
    legacy = _legacy(tmp_path)
    bound = _replace(legacy, **_REGISTRATION)
    changed = _replace(bound, **{
        field: "another-command" if field == "command_id" else "c" * 64})

    assert bound.evidence_key == changed.evidence_key == legacy.evidence_key
    assert bound.evidence_hash != changed.evidence_hash and bound.intent() != changed.intent()
    assert bound.original_candidate == changed.original_candidate
    assert bound.resolved_review == changed.resolved_review
    assert bound.prefix == changed.prefix
    assert bound.original_input_state == changed.original_input_state
