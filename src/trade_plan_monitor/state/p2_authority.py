"""Server-owned inputs for exact-quantity exception economics."""

from datetime import date
from typing import Annotated

from pydantic import Field

from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.p2_policy_models import (
    EconomicsPreview,
    NoEconomics,
    PositiveFen,
    RequiredEconomics,
)


class P2EconomicsContext(DailyValue):
    policy: Annotated[NoEconomics | EconomicsPreview | RequiredEconomics,
                      Field(discriminator="mode")]
    entry_fen: PositiveFen | None
    symbol: str
    session: date
