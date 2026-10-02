"""The unpublished daily API exposes whole-lot simulation, never broker controls."""

import pytest
from pydantic import ValidationError

from trade_plan_monitor.web.routers.daily_plans import DailyPositionCommand


def test_aggregate_initialization_contract():
    command = DailyPositionCommand.model_validate(
        {"symbol": "601021.SH", "core_qty": 100, "tactical_qty": 0, "expected_revision": 0}
    )
    assert command.core_qty == 100
    assert set(command.model_dump()) == {"symbol", "core_qty", "tactical_qty", "expected_revision"}


@pytest.mark.parametrize("quantity", [40, 60, 150, -100])
def test_initialization_rejects_nonwhole_units(quantity):
    with pytest.raises(ValidationError):
        DailyPositionCommand.model_validate(
            {"symbol": "601021.SH", "core_qty": quantity, "tactical_qty": 0,
             "expected_revision": 0}
        )
