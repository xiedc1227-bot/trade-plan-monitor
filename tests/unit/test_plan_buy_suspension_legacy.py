"""Old frozen preparation DTOs cannot acquire the new ordinary guard capability."""

from typing import Annotated

import pytest
from pydantic import Field, TypeAdapter, ValidationError
from tests.unit.test_plan_buy_suspension_contract import suspension_payload

from trade_plan_monitor.backtest.plan_updates import MaterializedPlanUpdate
from trade_plan_monitor.backtest.preparation_human_assurance_models import PreparationHumanOperation
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    PreparationReviewCommand,
)
from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft
from trade_plan_monitor.web.preparation_schemas import PreparationExtractionCandidate


@pytest.mark.parametrize("owner,field_name", [
    (MaterializedPlanUpdate, "draft"),
    (PreparationHumanOperation, "resolved_draft"),
    (PreparationReviewCommand, "draft"),
    (CollectionItemCorrectionCommand, "draft"),
    (PreparationExtractionCandidate, "draft"),
])
@pytest.mark.parametrize("native", [False, True])
def test_frozen_preparation_rejects_new_draft_at_its_real_field_boundary(owner, field_name, native):
    field = owner.model_fields[field_name]
    annotation = field.rebuild_annotation()
    if field.discriminator is not None:
        annotation = Annotated[annotation, Field(discriminator=field.discriminator)]
    adapter = TypeAdapter(annotation)
    raw = suspension_payload()
    value = BuySuspensionPlanDraft.model_validate(raw) if native else raw
    with pytest.raises(ValidationError):
        adapter.validate_python(value)
