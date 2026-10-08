"""ML-T13 publishes typed one-source contracts without approving a new digest."""

import json

import pytest
from pydantic import ValidationError
from tests.integration.test_plan_preparation_review import ready_preparation, review_command

from trade_plan_monitor.web.preparation_schemas import (
    PreparationFrozenView,
    PreparationReviewInput,
    PreparationView,
    project_preparation,
)

MAX_SAFE_INTEGER = 9_007_199_254_740_991


def test_candidate_schema_discriminates_extraction_frozen_and_unavailable():
    schema = PreparationView.model_json_schema(mode="serialization", by_alias=True)
    candidate = schema["properties"]["candidate"]["anyOf"][0]
    assert candidate["discriminator"]["propertyName"] == "kind"
    assert set(candidate["discriminator"]["mapping"]) == {"EXTRACTION", "FROZEN", "UNAVAILABLE"}
    for kind, reference in candidate["discriminator"]["mapping"].items():
        branch = schema["$defs"][reference.rsplit("/", 1)[1]]
        assert branch["properties"]["kind"]["const"] == kind
        if kind == "EXTRACTION":
            assert {"draft", "mapping", "openingAccount"} <= set(branch["required"])
            assert branch["properties"]["frozen"]["type"] == "null"
        elif kind == "FROZEN":
            assert "frozen" in branch["required"]
            assert branch["properties"]["draft"]["type"] == "null"
        else:
            assert branch["properties"]["validation"]["const"] == "INVALID"


@pytest.mark.parametrize(
    "case", ["missing-draft", "null-account", "frozen-missing", "unavailable-draft"]
)
def test_conflicting_candidate_variant_is_rejected(tmp_path, case):
    _store, record = ready_preparation(tmp_path)
    value = project_preparation(record).model_dump(mode="json", by_alias=True)
    candidate = value["candidate"]
    if case == "missing-draft":
        candidate.pop("draft")
    elif case == "null-account":
        candidate["openingAccount"] = None
    elif case == "frozen-missing":
        candidate.update(kind="FROZEN", draft=None, mapping=None, openingAccount=None)
    else:
        candidate.update(kind="UNAVAILABLE", validation="INVALID")
    with pytest.raises(ValidationError):
        PreparationView.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "field", ["expected_revision", "expected_source_revision", "expected_candidate_revision"]
)
def test_public_review_revision_rejects_unsafe_integer(tmp_path, field):
    _store, record = ready_preparation(tmp_path)
    review = review_command(record).model_dump(mode="json")
    review[field] = MAX_SAFE_INTEGER + 1
    with pytest.raises(ValidationError):
        PreparationReviewInput.model_validate_json(json.dumps({"review": review}))


def test_public_attempt_and_frozen_revision_schemas_are_safe():
    progress = PreparationView.model_json_schema(mode="serialization", by_alias=True)
    attempt_reference = progress["properties"]["attempts"]["items"]["$ref"]
    attempt = progress["$defs"][attempt_reference.rsplit("/", 1)[1]]
    assert attempt["properties"]["source_revision"]["maximum"] == MAX_SAFE_INTEGER
    frozen = PreparationFrozenView.model_json_schema(mode="serialization", by_alias=True)
    reference = frozen["properties"]["frozen"]["$ref"]
    manifest = frozen["$defs"][reference.rsplit("/", 1)[1]]
    for field in ("source_revision", "extraction_candidate_revision"):
        assert manifest["properties"][field]["maximum"] == MAX_SAFE_INTEGER
