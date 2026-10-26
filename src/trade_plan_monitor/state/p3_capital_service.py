"""Explicit reviewed simulated opening costs never initialize holdings or approval."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from trade_plan_monitor.decision.p3_basis import CapitalLot
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import (
    DailyValue,
    Identifier,
    PositiveWholeQty,
    Text,
)
from trade_plan_monitor.domain.p2_policy_models import MAX_SAFE, SafeFen
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.state.p3_capital_repository import CapitalCommandConflict, CapitalRepository
from trade_plan_monitor.state.p3_models import CapitalBook
from trade_plan_monitor.state.repositories import RevisionConflictError


class CapitalOpeningError(ValueError):
    def __init__(self, reason, status=409):
        self.reason, self.status = reason, status
        super().__init__(reason)


class CapitalInventoryLot(DailyValue):
    lot_id: Identifier
    bucket: Literal["CORE", "TACTICAL"]
    quantity: PositiveWholeQty


class CapitalOpeningLot(CapitalInventoryLot):
    retained_basis_fen: SafeFen


class CapitalOpeningCommand(DailyValue):
    plan_version_id: UUID = Field(strict=False)
    expected_inventory_revision: int = Field(strict=True, gt=0, le=MAX_SAFE)
    expected_book_revision: SafeFen
    observed_at: ShanghaiDatetime
    source: Text
    excerpt: Text
    reason: Text
    confirmed: bool = Field(strict=True)
    lots: tuple[CapitalOpeningLot, ...] = Field(max_length=500)

    @model_validator(mode="after")
    def confirmed_complete(self):
        if not self.confirmed:
            raise ValueError("Explicit local budget confirmation is required")
        if len({(p.lot_id, p.bucket) for p in self.lots}) != len(self.lots):
            raise ValueError("duplicate opening lot")
        if sum(p.retained_basis_fen for p in self.lots) > MAX_SAFE:
            raise ValueError("opening cost total overflows safe integer bounds")
        return self


class CapitalOpeningContext(DailyValue):
    plan_version_id: UUID = Field(strict=False)
    symbol: AShareSymbol
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed: bool = Field(strict=True)
    inventory_known: bool = Field(strict=True)
    inventory_revision: int = Field(strict=True, ge=0, le=MAX_SAFE)
    lots: tuple[CapitalInventoryLot, ...] = Field(max_length=500)
    blockers: tuple[str, ...]


def confirm_capital_opening(session, command, *, command_id, now, current):
    """Caller owns the transaction and server-only current-review/inventory loader."""
    request_hash = daily_hash("capital-opening-command-v1", command.model_dump(mode="json"))
    repo = CapitalRepository(session)
    previous = repo.event(command_id)
    if previous is not None:
        if previous.request_hash != request_hash or previous.kind not in {
            "OPENING",
            "RECONCILIATION",
        }:
            raise CapitalCommandConflict("CAPITAL_IDEMPOTENCY_CONFLICT")
        return previous
    context = current(command)
    if (
        context is None
        or not context.reviewed
        or context.plan_version_id != command.plan_version_id
        or context.blockers
    ):
        raise CapitalOpeningError("CAPITAL_REVIEW_REQUIRED")
    if not context.inventory_known:
        raise CapitalOpeningError("CAPITAL_POSITION_UNKNOWN")
    if context.inventory_revision != command.expected_inventory_revision:
        raise RevisionConflictError(context.inventory_revision)
    if command.observed_at > now:
        raise CapitalOpeningError("CAPITAL_OBSERVATION_FUTURE", 422)

    def quantities(values):
        return {(p.lot_id, p.bucket): p.quantity for p in values}

    if quantities(command.lots) != quantities(context.lots):
        raise CapitalOpeningError("CAPITAL_LOTS_CHANGED")
    before = repo.get(context.symbol)
    revision = 0 if before is None else before.revision
    if revision != command.expected_book_revision:
        raise RevisionConflictError(revision)
    if before is not None and now < before.updated_at:
        raise CapitalOpeningError("CAPITAL_CLOCK_REVERSED")
    book = CapitalBook.build(
        symbol=context.symbol,
        revision=revision + 1,
        inventory_revision=context.inventory_revision,
        updated_at=now,
        lots=tuple(CapitalLot(**p.model_dump(), provenance_ref=command_id) for p in command.lots),
    )
    return repo.write(
        book,
        expected_revision=revision,
        command_id=command_id,
        request_hash=request_hash,
        kind="OPENING" if before is None else "RECONCILIATION",
        now=now,
        details={
            "plan_version_id": str(context.plan_version_id),
            "content_hash": context.content_hash,
            "review_binding_hash": context.review_binding_hash,
            "observed_at": command.observed_at.isoformat(),
            "source": command.source,
            "excerpt": command.excerpt,
            "reason": command.reason,
            "confirmed": True,
            "classification": "HUMAN_CONFIRMED",
        },
    )
