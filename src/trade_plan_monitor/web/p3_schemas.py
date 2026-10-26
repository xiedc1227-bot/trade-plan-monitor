"""Closed capital commands and explicitly non-authorizing resource views."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from trade_plan_monitor.decision.p3_capital import CapitalAssessment
from trade_plan_monitor.domain.p2_evidence import FrozenPretrade
from trade_plan_monitor.domain.p2_policy_models import SafeFen
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.state.p3_capital_service import (
    CapitalInventoryLot,
    CapitalOpeningCommand,
    CapitalOpeningLot,
)
from trade_plan_monitor.state.p3_models import CapitalBook, CapitalBookEvent
from trade_plan_monitor.web.schemas import ApiValue


class CapitalBookView(ApiValue):
    computed_at: ShanghaiDatetime
    symbol: str
    inventory_known: bool
    inventory_revision: SafeFen
    retained_basis_fen: SafeFen | None
    book_revision: SafeFen | None
    book: CapitalBook | None
    inventory_lots: tuple[CapitalInventoryLot, ...] = Field(max_length=500)
    authority_granted: Literal[False] = False


class CapitalOpeningApiCommand(CapitalOpeningCommand, ApiValue):
    observed_at: ShanghaiDatetime = Field(strict=False)
    lots: tuple[CapitalOpeningLot, ...] = Field(max_length=500, strict=False)


class CapitalOpeningReceipt(ApiValue):
    event: CapitalBookEvent
    inventory_changed: Literal[False] = False
    authority_granted: Literal[False] = False


class CapitalPreviewCommand(ApiValue):
    plan_version_id: UUID = Field(strict=False)
    rule_id: str = Field(min_length=1, max_length=128)
    occurrence_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proposed_quantity: int | None = Field(default=None, strict=True, gt=0,
                                          le=9_007_199_254_740_991)


class CapitalPreviewView(ApiValue):
    computed_at: ShanghaiDatetime
    plan_version_id: str
    rule_id: str
    quantity: int | None
    evidence: FrozenPretrade
    assessment: CapitalAssessment
    authority_granted: Literal[False] = False
