"""Current admission is exact; historical extraction envelopes remain closed."""

import json
from typing import Annotated

import pytest
from pydantic import Field, TypeAdapter, ValidationError
from tests.unit.test_plan_buy_suspension_contract import suspension_payload

from trade_plan_monitor.ai.plan_extraction import (
    CurrentPlanExtractionOutput,
    CurrentPlanExtractionResult,
)
from trade_plan_monitor.domain.market_linkage_validation import (
    CurrentPlanDraft,
    parse_current_draft,
)
from trade_plan_monitor.domain.plan_codec import (
    PlanDocumentError,
    dump_plan_json,
    dump_plan_yaml,
    load_plan_json,
    load_plan_yaml,
)
from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft


def test_new_public_executable_codecs_and_current_draft_dispatch_roundtrip():
    raw = suspension_payload()
    plan = load_plan_json(json.dumps(raw))
    assert type(plan) is BuySuspensionTradePlan
    assert load_plan_json(dump_plan_json(plan)) == plan
    assert load_plan_yaml(dump_plan_yaml(plan)) == plan
    draft = parse_current_draft(raw)
    assert type(draft) is BuySuspensionPlanDraft
    assert draft.to_executable() == plan
    assert TypeAdapter(CurrentPlanDraft).validate_python(raw) == draft


@pytest.mark.parametrize("schema,version", [(10, "condition-plan-v1"), (5, "condition-plan-v6"),
    (9, "condition-plan-v6"), (10, "condition-plan-v5")])
def test_public_dispatch_rejects_mismatched_schema_and_execution_version(schema, version):
    raw = suspension_payload()
    raw.update(schema_version=schema, execution_version=version)
    with pytest.raises(PlanDocumentError):
        load_plan_json(json.dumps(raw))
    with pytest.raises(ValidationError):
        parse_current_draft(raw)


@pytest.mark.parametrize("envelope", [CurrentPlanExtractionOutput, CurrentPlanExtractionResult])
@pytest.mark.parametrize("native", [False, True])
def test_legacy_extraction_draft_field_rejects_schema10_without_changing_its_wire_schema(
    envelope, native,
):
    # Validate the actual envelope field to isolate its admission from unrelated evidence fields.
    field = envelope.model_fields["draft"]
    adapter = TypeAdapter(Annotated[field.annotation, Field(discriminator=field.discriminator)])
    raw = suspension_payload()
    value = BuySuspensionPlanDraft.model_validate(raw) if native else raw
    with pytest.raises(ValidationError):
        adapter.validate_python(value)
    schema = envelope.model_json_schema()["properties"]["draft"]
    assert set(schema["discriminator"]["mapping"]) == {"5", "6", "7", "8", "9"}


def test_schema10_rejection_never_discards_guard_or_family_fields():
    raw = suspension_payload()
    raw["reference_market"] = None
    with pytest.raises(PlanDocumentError):
        load_plan_json(json.dumps(raw))
    with pytest.raises(ValidationError):
        parse_current_draft(raw)
    assert raw["buy_suspension"]["condition"]["price_fen"] == 2420
