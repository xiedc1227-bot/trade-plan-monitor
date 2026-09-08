"""Assemble live evaluation inputs from committed local facts only."""

from datetime import date, datetime, time, timedelta

from trade_plan_monitor.decision.models import (
    DailyIndicatorSnapshot,
    DataHealthSnapshot,
    DataHealthStatus,
    EvaluationContext,
    IntradayEvaluationTarget,
    OfficialCloseEvaluationTarget,
    PositionLotSnapshot,
    RiskStateSnapshot,
    RiskStatus,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.market_data.indicators import calculate_ta_v1
from trade_plan_monitor.market_data.models import DailyBar
from trade_plan_monitor.market_data.reconciliation import reconcile_daily_close
from trade_plan_monitor.runtime.service import (
    IntradayMarketFacts,
    OfficialCloseMarketFacts,
    StaleActivationGenerationError,
    UnitOfWorkFactory,
)
from trade_plan_monitor.state.repositories import RiskStateRecord


def _risk_snapshot_for_plan(
    *,
    risk: RiskStateRecord | None,
    plan_hash: str,
    history: tuple[DailyBar, ...],
    symbol: str,
    cutoff: datetime,
) -> RiskStateSnapshot:
    """Restore risk only when it belongs to the exact active plan content."""

    if risk is not None and risk.plan_hash == plan_hash:
        return RiskStateSnapshot(**{**risk.model_dump(), "status": RiskStatus(risk.status)})
    prior = history[-1]
    return RiskStateSnapshot(
        symbol=symbol,
        plan_hash=plan_hash,
        status=RiskStatus.CLEAR,
        breach_trade_date=None,
        prior_close_fen=prior.close_fen,
        revision=0 if risk is None else risk.revision,
        updated_at=datetime.combine(prior.trade_date, time(15), cutoff.tzinfo),
    )


class ProductionContextBuilder:
    """Read one consistent state boundary, then construct validated immutable inputs."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._work = unit_of_work_factory

    def __call__(
        self, plan: TradePlan, facts: IntradayMarketFacts | OfficialCloseMarketFacts
    ) -> EvaluationContext:
        intraday = isinstance(facts, IntradayMarketFacts)
        trade_date = facts.bucket_end.date() if intraday else facts.trade_date
        cutoff = facts.source_as_of
        digest = plan_sha256(plan)
        with self._work() as work:
            active = work.plans.get_active(plan.symbol)
            if active is None:
                raise StaleActivationGenerationError(plan.symbol)
            version = work.plans.get_version_details(active.plan_version_id)
            if version is None or version.plan_hash != digest or active.activated_at > cutoff:
                raise StaleActivationGenerationError(plan.symbol)
            history = (
                tuple(
                    bar
                    for bar in work.history.list_daily_bars(
                        plan.symbol, start=date.min, end=trade_date - timedelta(days=1)
                    )
                    if bar.is_official
                )[-499:]
                if intraday
                else facts.official_daily_bars
            )
            calendar = work.references.list_trading_days(
                plan.market, trade_date - timedelta(days=366), trade_date
            )
            limits = work.references.list_daily_limits(trade_date)
            positions = work.positions.list_open_lots(plan.symbol)
            risk = work.risk.get(plan.symbol)
            head = work.projections.get_decision_head(plan.symbol)
        if not history:
            raise RuntimeError("official reference history is unavailable")
        episode = (
            head.result.snapshot.episode
            if head is not None and head.result.evaluation_identity.plan_hash == digest
            else None
        )
        risk_snapshot = _risk_snapshot_for_plan(
            risk=risk,
            plan_hash=digest,
            history=history,
            symbol=plan.symbol,
            cutoff=cutoff,
        )
        minutes = facts.current_day_minutes if intraday else ()
        bars = facts.complete_five_minute_bars if intraday else ()
        age = int((facts.evaluated_at - cutoff).total_seconds()) if intraday else None
        fresh = intraday and age <= 90
        reconciliation = (
            reconcile_daily_close(
                symbol=plan.symbol,
                current_trade_date=trade_date,
                daily_bars=(facts.provisional_daily_bar,),
            )
            if intraday
            else facts.close_reconciliation
        )
        daily_snapshot = (
            DailyIndicatorSnapshot(
                series=calculate_ta_v1((*history, facts.provisional_daily_bar)),
                provenance=facts.provenance,
                source_as_of=cutoff,
                source_bar=facts.provisional_daily_bar,
            )
            if intraday
            else facts.daily_indicator_snapshot
        )
        return EvaluationContext(
            evaluated_at=facts.evaluated_at,
            target=(
                IntradayEvaluationTarget(bucket_end=cutoff)
                if intraday
                else OfficialCloseEvaluationTarget(trade_date=trade_date)
            ),
            plan=plan,
            plan_hash=digest,
            plan_active=True,
            activated_at=active.activated_at,
            current_day_minutes=minutes,
            complete_5m_bars=bars,
            official_daily_bars=history,
            five_minute_indicators=calculate_ta_v1(bars) if bars else None,
            daily_indicator_snapshot=daily_snapshot,
            close_reconciliation=reconciliation,
            trading_calendar=calendar,
            daily_limit=next((row for row in limits if row.symbol == plan.symbol), None),
            data_health=DataHealthSnapshot(
                symbol=plan.symbol,
                status=DataHealthStatus.LIVE if fresh else DataHealthStatus.STALE,
                latest_bar_end=cutoff if intraday else None,
                data_age_seconds=age,
                required_data_complete=True,
                fresh=fresh,
            ),
            positions=tuple(
                PositionLotSnapshot(
                    lot_id=lot.id,
                    symbol=lot.symbol,
                    bucket=lot.bucket,
                    quantity=lot.quantity,
                    remaining_quantity=lot.remaining_qty,
                    acquired_trade_date=lot.acquired_trade_date,
                    cost_fen=lot.cost_fen,
                )
                for lot in positions
            ),
            low_zone_episode=episode,
            risk_state=risk_snapshot,
            manual_event_risk=None,
        )
