"""Opt-in historical official inputs and their exact commit-time fences."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from trade_plan_monitor.decision.models import (
    DataHealthSnapshot,
    DataHealthStatus,
    EvaluationContext,
    OfficialCloseEvaluationTarget,
    PositionLotSnapshot,
    RiskStateSnapshot,
    RiskStatus,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.runtime.historical_close_evidence import (
    LegacyHistoricalCloseReader,
    ProvenHistoricalClose,
    UnknownHistoricalClose,
)
from trade_plan_monitor.state.repositories import PositionLotRecord, RiskStateRecord
from trade_plan_monitor.state.unit_of_work import UnitOfWork

if TYPE_CHECKING:
    from trade_plan_monitor.runtime.service import OfficialCloseMarketFacts


class HistoricalCloseUnavailableError(RuntimeError):
    """Required historical facts are not yet proven; do not claim an evaluation."""


class StaleHistoricalCloseError(RuntimeError):
    """Prepared evidence changed; discard the result and reconstruct before retry."""


def _position_inputs(lots: tuple[PositionLotRecord, ...]) -> tuple[PositionLotSnapshot, ...]:
    return tuple(PositionLotSnapshot(
        lot_id=lot.id, symbol=lot.symbol, bucket=lot.bucket, quantity=lot.quantity,
        remaining_quantity=lot.remaining_qty, acquired_trade_date=lot.acquired_trade_date,
        cost_fen=lot.cost_fen,
    ) for lot in lots)


@dataclass(frozen=True)
class HistoricalOfficialContext:
    """One trusted builder's prepared inputs, never a notification-send permit."""

    context: EvaluationContext
    position_lots: tuple[PositionLotRecord, ...]
    inventory_revision: int
    current_risk: RiskStateRecord | None
    activation_revision: int
    high_water_sequence: int

    def __post_init__(self):
        if not isinstance(self.context.target, OfficialCloseEvaluationTarget):
            raise ValueError("Historical context requires an official target")
        for value in (self.inventory_revision, self.high_water_sequence):
            if type(value) is not int or value < 0:
                raise ValueError("Historical context requires nonnegative revision fences")
        if type(self.activation_revision) is not int or self.activation_revision < 1:
            raise ValueError("Historical context requires actual activation revision")
        if (type(self.position_lots) is not tuple
                or any(type(lot) is not PositionLotRecord or lot.remaining_qty <= 0
                       or lot.closed_at is not None for lot in self.position_lots)
                or len({lot.id for lot in self.position_lots}) != len(self.position_lots)
                or _position_inputs(self.position_lots) != self.context.positions):
            raise ValueError("Historical context must retain exactly its evaluated lots")
        revision = 0 if self.current_risk is None else self.current_risk.revision
        if self.context.risk_state.revision != revision:
            raise ValueError("Historical context must preserve physical risk revision")

    def require_current(self, work: UnitOfWork, activation_revision: int) -> None:
        """Run inside the claiming transaction, including results without transitions.

        The application engine's explicit BEGIN means a concurrent writer after
        these reads prevents upgrading the old snapshot to a committing writer.
        The caller must discard/retry that transaction, never reuse this proof.
        """
        symbol = self.context.plan.symbol
        active = work.plans.get_active(symbol)
        if (self.activation_revision != activation_revision
                or active is None or active.revision != self.activation_revision
                or active.activated_at != self.context.activated_at
                or work.positions.get_inventory_revision(symbol) != self.inventory_revision
                or work.risk.get(symbol) != self.current_risk
                or work.events.current_sequence() != self.high_water_sequence):
            raise StaleHistoricalCloseError(
                "Historical close inputs changed; reconstruct and retry",
            )


class HistoricalOfficialContextBuilder:
    """Connect durable historical evidence to the existing pure legacy evaluator."""

    def __init__(self, reader: LegacyHistoricalCloseReader):
        self._reader = reader

    def __call__(
        self, plan: TradePlan, facts: OfficialCloseMarketFacts,
    ) -> HistoricalOfficialContext:
        proof = self.prepare_target(plan, facts.trade_date, facts.evaluated_at)
        risk = proof.risk_state
        if risk is None:
            if not facts.official_daily_bars:
                raise HistoricalCloseUnavailableError(
                    "Historical close requires prior official bar",
                )
            prior = facts.official_daily_bars[-1]
            risk = RiskStateSnapshot(
                symbol=plan.symbol, plan_hash=plan_sha256(plan), status=RiskStatus.CLEAR,
                breach_trade_date=None, prior_close_fen=prior.close_fen,
                revision=0 if proof.current_risk is None else proof.current_risk.revision,
                updated_at=datetime.combine(prior.trade_date, time(15), facts.source_as_of.tzinfo),
            )
        # Projection storage already requires this canonical acquisition order.
        lots = tuple(sorted(proof.inventory.position_lots,
                            key=lambda lot: (lot.acquired_trade_date, lot.id)))
        context = EvaluationContext(
            evaluated_at=facts.evaluated_at,
            target=OfficialCloseEvaluationTarget(trade_date=facts.trade_date),
            plan=plan, plan_hash=plan_sha256(plan), plan_active=True,
            activated_at=proof.scope.activated_at,
            current_day_minutes=(), complete_5m_bars=(), five_minute_indicators=None,
            official_daily_bars=facts.official_daily_bars,
            daily_indicator_snapshot=facts.daily_indicator_snapshot,
            close_reconciliation=facts.close_reconciliation,
            trading_calendar=proof.trading_calendar, daily_limit=None,
            data_health=DataHealthSnapshot(
                symbol=plan.symbol, status=DataHealthStatus.STALE, latest_bar_end=None,
                data_age_seconds=None, required_data_complete=True, fresh=False,
            ),
            positions=_position_inputs(lots), low_zone_episode=None,
            risk_state=risk, manual_event_risk=None,
        )
        return HistoricalOfficialContext(
            context, lots, proof.inventory.current_revision, proof.current_risk,
            proof.scope.activation_revision, proof.high_water_sequence,
        )

    def prepare_target(
        self, plan: TradePlan, trade_date: date, observed_at: datetime,
    ) -> ProvenHistoricalClose:
        """Reject out-of-order work before provider/pending-state side effects.

        This early proof is deliberately not cached: after market-data persistence,
        __call__ reconstructs a fresh snapshot and its commit fences.
        """
        proof = self._reader.prepare(plan.symbol, trade_date, observed_at)
        if isinstance(proof, UnknownHistoricalClose):
            raise HistoricalCloseUnavailableError(f"Historical close unavailable: {proof.reason}")
        if proof.scope.plan != plan:
            raise StaleHistoricalCloseError(
                "Historical close inputs changed; reconstruct and retry",
            )
        if proof.inventory.opening_balances:
            raise HistoricalCloseUnavailableError(
                "Historical legacy close cannot represent opening balances as position lots",
            )
        return proof
