"""Reconstruct current legacy risk authority from one committed SQLite snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.models import (
    OfficialCloseEvaluationIdentity,
    PositionLotSnapshot,
    SignalType,
)
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.notifications.legacy_recovery_eligibility import (
    ActiveLegacyPlan,
    LegacyCurrentEvidence,
    LegacyInventoryEvidence,
)
from trade_plan_monitor.notifications.recovery_eligibility import RecoveryBarrierEvidence
from trade_plan_monitor.notifications.recovery_provenance import (
    LegacyAlertOriginReader,
    ProvenLegacyAlertOrigin,
)
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
from trade_plan_monitor.state.models import (
    ActivePlan,
    PendingOfficialClose,
    PlanActivationState,
    PlanVersion,
    RiskState,
    TradingCalendar,
)
from trade_plan_monitor.state.models import AlertEvent as AlertRow
from trade_plan_monitor.state.models import EvaluationResult as ResultRow
from trade_plan_monitor.state.position_inventory_history import (
    PositionInventoryHistoryReader,
    ProvenInventoryHistory,
)
from trade_plan_monitor.state.projections import ProjectionRepository, _result_from_row

_RISK_STAGES = {
    SignalType.RISK_BREACH, SignalType.RISK_EXIT_READY,
    SignalType.RISK_EXIT_PENDING_SETTLEMENT, SignalType.RISK_RECOVERED,
}


@dataclass(frozen=True, slots=True)
class LegacyDeliveryFacts:
    origin: ProvenLegacyAlertOrigin
    active: ActiveLegacyPlan
    current: LegacyCurrentEvidence
    barrier: RecoveryBarrierEvidence
    target_bucket_end: datetime


def read_legacy_delivery_facts(
    session: Session,
    *,
    event_id: UUID,
    now: datetime,
    runtime_generation: UUID,
) -> LegacyDeliveryFacts | None:
    """Return complete facts or unknown; never infer absence from a failed read."""

    origin = LegacyAlertOriginReader(lambda: session).read_in_session(session, event_id)
    if type(origin) is not ProvenLegacyAlertOrigin:
        return None
    active = _active_legacy(session, origin.event.symbol, now)
    if active is None:
        return None
    # The origin reader has already validated the immutable historical result.
    origin_version = session.get(PlanVersion, origin.plan_version_id)
    if origin_version is None:
        return None
    origin_plan = load_plan_json(origin_version.payload_json)
    if type(origin_plan) is not TradePlan:
        return None
    projection = ProjectionRepository(session)
    origin_result = projection.get_evaluation_result(origin.evaluation_identity)
    if origin_result is None or origin_result.result_hash != origin.result_hash:
        return None
    latest_day, settlement_day = _current_official_and_settlement_day(
        session, active.plan.market, now,
    )
    if latest_day is None or settlement_day is None:
        return None
    target = datetime.combine(latest_day, time(15), SHANGHAI)
    missing = LegacyHistoricalCloseReader.missing_targets_in_session(
        session, origin.event.symbol, now,
    )
    if missing != () or session.scalar(select(PendingOfficialClose).where(
        PendingOfficialClose.symbol == origin.event.symbol,
    )) is not None:
        return None
    identity = OfficialCloseEvaluationIdentity(
        plan_hash=plan_sha256(active.plan), symbol=origin.event.symbol,
        official_trade_date=latest_day,
        formula_version=active.plan.monitoring.indicator_formula_version,
    )
    latest = projection.get_evaluation_result(identity)
    if latest is None:
        return None
    risk = session.get(RiskState, origin.event.symbol)
    if risk is None or (
        risk.plan_hash != identity.plan_hash
        or risk.status != latest.snapshot.risk.status.value
        or risk.breach_trade_date != latest.snapshot.risk.breach_trade_date
        or risk.revision != latest.snapshot.risk.revision
    ):
        return None
    stage = _latest_risk_stage(session, active, latest_day)
    if stage is None:
        return None
    holdings = PositionInventoryHistoryReader.read_in_session(
        session, origin.event.symbol, cutoff=now, observed_at=now,
    )
    if type(holdings) is not ProvenInventoryHistory or (
        holdings.inventory_revision != holdings.current_revision
    ):
        return None
    selected = _selected_lot(holdings, active.plan.position.lot_size)
    opening_quantity = sum(item.remaining_qty for item in holdings.opening_balances)
    opening_sellable_quantity = sum(
        item.remaining_qty for item in holdings.opening_balances
        if item.sellable_from <= settlement_day
    )
    inventory = LegacyInventoryEvidence(
        symbol=origin.event.symbol, plan_hash=identity.plan_hash,
        activation_revision=active.activation_revision,
        target_bucket_end=target, observed_at=now,
        settlement_trade_date=settlement_day, selected_target=selected,
        sellable=(
            opening_sellable_quantity >= active.plan.position.lot_size
            if selected is None and opening_quantity else
            None if selected is None else selected.acquired_trade_date < settlement_day
        ),
        opening_quantity=opening_quantity,
        opening_sellable_quantity=opening_sellable_quantity,
    )
    barrier = RecoveryBarrierEvidence(
        symbol=origin.event.symbol, plan_hash=identity.plan_hash,
        activation_revision=active.activation_revision,
        runtime_generation=runtime_generation, target_bucket_end=target,
        reconciled_through=target, pending_obligations=0, observed_at=now,
    )
    latest_occurrence = _latest_exit_occurrence(
        session, origin, latest, now,
    )
    current = LegacyCurrentEvidence(
        origin_plan=origin_plan, origin_result=origin_result, latest=latest,
        latest_stage=stage, activation_revision=active.activation_revision,
        target_bucket_end=target, latest_official_trade_date=latest_day,
        observed_at=now, inventory=inventory, latest_occurrence=latest_occurrence,
    )
    return LegacyDeliveryFacts(origin, active, current, barrier, target)


def _active_legacy(session: Session, symbol: str, now: datetime) -> ActiveLegacyPlan | None:
    active = session.get(ActivePlan, symbol)
    if active is None:
        return None
    version = session.get(PlanVersion, active.plan_version_id)
    state = session.get(PlanActivationState, symbol)
    if (
        version is None or state is None or state.plan_version_id != active.plan_version_id
        or state.revision != active.revision or version.status != "ACTIVE"
        or version.symbol != symbol
    ):
        return None
    plan = load_plan_json(version.payload_json)
    if type(plan) is not TradePlan or plan_sha256(plan) != version.plan_hash:
        return None
    return ActiveLegacyPlan(
        plan=plan, plan_version_id=version.id, activation_revision=active.revision,
        activated_at=datetime.fromisoformat(active.activated_at), observed_at=now,
    )


def _current_official_and_settlement_day(
    session: Session, exchange: str, now: datetime,
) -> tuple[date | None, date | None]:
    start = now.date() - timedelta(days=7)
    rows = session.scalars(select(TradingCalendar).where(
        TradingCalendar.exchange == exchange,
        TradingCalendar.cal_date >= start,
        TradingCalendar.cal_date <= now.date(),
    )).all()
    calendar = {row.cal_date: row for row in rows}
    today = calendar.get(now.date())
    if today is None:
        return None, None
    settlement = now.date() if today.is_open else None
    official = now.date() if today.is_open and now.time() >= time(15) else None
    day = now.date() - timedelta(days=1)
    while day >= start and (settlement is None or official is None):
        row = calendar.get(day)
        if row is None:
            return None, None
        if row.is_open:
            settlement = settlement or day
            official = official or day
        day -= timedelta(days=1)
    return official, settlement


def _latest_risk_stage(session: Session, active: ActiveLegacyPlan, latest_day: date):
    rows = session.scalars(select(ResultRow).where(
        ResultRow.plan_hash == plan_sha256(active.plan),
        ResultRow.symbol == active.plan.symbol,
        ResultRow.evaluation_kind == "OFFICIAL_CLOSE",
        ResultRow.target_value <= latest_day.isoformat(),
    ).order_by(ResultRow.target_value.desc()).limit(257)).all()
    if len(rows) > 256:
        return None
    for row in rows:
        result = _result_from_row(row)
        if result.snapshot.evaluated_at < active.activated_at:
            break
        if result.snapshot.signal_type in _RISK_STAGES:
            return result
    return None


def _selected_lot(holdings: ProvenInventoryHistory, lot_size: int) -> PositionLotSnapshot | None:
    eligible = [lot for lot in holdings.position_lots if lot.remaining_qty >= lot_size]
    tactical = [lot for lot in eligible if lot.bucket == "TACTICAL"]
    candidates = tactical or [lot for lot in eligible if lot.bucket == "CORE"]
    if not candidates:
        return None
    lot = sorted(candidates, key=lambda item: (-item.acquired_trade_date.toordinal(), item.id))[0]
    return PositionLotSnapshot(
        lot_id=lot.id, symbol=lot.symbol, bucket=lot.bucket,
        quantity=lot.quantity, remaining_quantity=lot.remaining_qty,
        acquired_trade_date=lot.acquired_trade_date, cost_fen=lot.cost_fen,
    )


def _latest_exit_occurrence(session: Session, origin, latest, now):
    if latest.snapshot.signal_type is not SignalType.RISK_EXIT_READY or (
        latest.evaluation_identity.official_trade_date <= origin.event.trading_date
    ):
        return None
    rows = session.scalars(select(AlertRow.id).where(
        func.json_extract(AlertRow.payload_json, "$.symbol") == origin.event.symbol,
        func.json_extract(AlertRow.payload_json, "$.plan_hash") == origin.event.plan_hash,
        func.json_extract(AlertRow.payload_json, "$.signal_type") == "RISK_EXIT_READY",
        func.json_extract(AlertRow.payload_json, "$.trading_date")
        == latest.evaluation_identity.official_trade_date.isoformat(),
    ).limit(2)).all()
    if len(rows) != 1:
        return None
    occurrence = LegacyAlertOriginReader(lambda: session).read_in_session(
        session, UUID(rows[0]),
    )
    return occurrence if type(occurrence) is ProvenLegacyAlertOrigin else None
