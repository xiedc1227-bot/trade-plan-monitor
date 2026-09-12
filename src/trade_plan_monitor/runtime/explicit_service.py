"""Activation- and revision-fenced SQLite runtime for the bounded R09 BUY mode."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from trade_plan_monitor.decision.explicit_rules import (
    ExplicitEvaluationResult,
    ExplicitInventorySnapshot,
    evaluate_explicit_rules,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.notifications.identity import explicit_alert_event_id
from trade_plan_monitor.notifications.models import (
    ExplicitAlertEvent,
    build_explicit_alert_payload,
)
from trade_plan_monitor.state.repositories import ManualEventRiskStatus
from trade_plan_monitor.state.unit_of_work import UnitOfWork


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class StaleExplicitDecisionError(RuntimeError):
    """A consumed activation or mutable safety fact changed before commit."""

    code = "STALE_EXPLICIT_DECISION"


class ExplicitRuntimeCycleStatus(StrEnum):
    COMMITTED = "COMMITTED"
    DUPLICATE = "DUPLICATE"


class ExplicitRuntimeCycleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: ExplicitRuntimeCycleStatus
    evaluation_result: ExplicitEvaluationResult
    committed_events: tuple[ExplicitAlertEvent, ...]


class _CapturedContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    activation_revision: int
    inventory: ExplicitInventorySnapshot
    bars: tuple[FiveMinuteBar, ...]
    trading_calendar: tuple[object, ...]
    manual_event_risk: bool | None
    manual_event_risk_revision: int | None


class ExplicitRuntimeEvaluationService:
    """Read only declared facts, evaluate purely, then persist under fresh revision guards."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        after_evaluate: Callable[[ExplicitEvaluationResult], None] | None = None,
    ) -> None:
        if not callable(unit_of_work_factory):
            raise TypeError("unit_of_work_factory must be callable")
        if after_evaluate is not None and not callable(after_evaluate):
            raise TypeError("after_evaluate must be callable")
        self._work = unit_of_work_factory
        self._after_evaluate = after_evaluate

    def run_intraday(
        self,
        *,
        plan: ExplicitTradePlan,
        target_bucket_end: datetime,
        evaluated_at: datetime,
    ) -> ExplicitRuntimeCycleResult:
        if type(plan) is not ExplicitTradePlan:
            raise TypeError("plan must be an ExplicitTradePlan")
        captured = self._capture(plan, target_bucket_end)
        with self._work() as work:
            existing = work.explicit_rules.get(
                plan_hash=plan_sha256(plan),
                symbol=plan.symbol,
                target_bucket_end=target_bucket_end,
                activation_revision=captured.activation_revision,
            )
        if existing is not None:
            return ExplicitRuntimeCycleResult(
                status=ExplicitRuntimeCycleStatus.DUPLICATE,
                evaluation_result=existing,
                committed_events=(),
            )
        result = evaluate_explicit_rules(
            plan=plan,
            bars=captured.bars,
            trading_calendar=captured.trading_calendar,
            target_bucket_end=target_bucket_end,
            evaluated_at=evaluated_at,
            activation_revision=captured.activation_revision,
            inventory=captured.inventory,
            rule_states=self._load_rule_states(plan, captured.activation_revision),
            manual_event_risk=captured.manual_event_risk,
            manual_event_risk_revision=captured.manual_event_risk_revision,
        )
        if self._after_evaluate is not None:
            self._after_evaluate(result)

        committed: list[ExplicitAlertEvent] = []
        with self._work() as work:
            self._require_active(work, plan, captured.activation_revision)
            current_inventory = work.positions.inventory_snapshot(
                plan.symbol,
                as_of_trade_date=target_bucket_end.date(),
                cutoff=target_bucket_end,
            )
            if (
                current_inventory.inventory_revision != result.inventory_revision
                or current_inventory.status.value != captured.inventory.status
                or current_inventory.total_qty != captured.inventory.total_qty
            ):
                raise StaleExplicitDecisionError("inventory changed before BUY commit")
            if captured.manual_event_risk_revision is not None:
                current_value, current_revision = _manual_risk_value(
                    work.manual_event_risk.get(plan.symbol),
                    plan_hash=result.plan_hash,
                    trade_date=target_bucket_end.date(),
                    cutoff=target_bucket_end,
                )
                if (
                    current_revision != captured.manual_event_risk_revision
                    or current_value != captured.manual_event_risk
                ):
                    raise StaleExplicitDecisionError(
                        "manual event risk changed before BUY commit"
                    )
            record = work.explicit_rules.persist(result)
            if record.created:
                for signal in result.signal_intents:
                    payload = build_explicit_alert_payload(
                        event_id=explicit_alert_event_id(signal),
                        plan=plan,
                        result=result,
                        signal=signal,
                    )
                    committed.append(work.alerts.enqueue_explicit(payload))
            work.commit()
        return ExplicitRuntimeCycleResult(
            status=(
                ExplicitRuntimeCycleStatus.COMMITTED
                if record.created
                else ExplicitRuntimeCycleStatus.DUPLICATE
            ),
            evaluation_result=result,
            committed_events=tuple(committed),
        )

    def _capture(self, plan: ExplicitTradePlan, target: datetime) -> _CapturedContext:
        digest = plan_sha256(plan)
        with self._work() as work:
            active = self._require_active(work, plan, None)
            inventory = work.positions.inventory_snapshot(
                plan.symbol,
                as_of_trade_date=target.date(),
                cutoff=target,
            )
            rows = work.history.list_five_minute(
                plan.symbol,
                start=target - timedelta(days=60),
                end=target,
                formula_version=plan.monitoring.indicator_formula_version,
            )
            calendar = work.references.list_trading_days(
                plan.market,
                target.date() - timedelta(days=366),
                target.date(),
            )
            manual_declared = any(
                _contains_manual_risk(rule.safety_conditions) for rule in plan.rules
            )
            manual_value, manual_revision = (
                _manual_risk_value(
                    work.manual_event_risk.get(plan.symbol),
                    plan_hash=digest,
                    trade_date=target.date(),
                    cutoff=target,
                )
                if manual_declared
                else (None, None)
            )
        bars = tuple(
            FiveMinuteBar(
                symbol=row.symbol,
                bar_end=row.bar_end,
                formula_version=row.formula_version,
                open_fen=row.open_fen,
                high_fen=row.high_fen,
                low_fen=row.low_fen,
                close_fen=row.close_fen,
                volume_shares=row.volume_shares,
                amount_yuan=row.amount_yuan,
            )
            for row in rows
        )
        return _CapturedContext(
            activation_revision=active.revision,
            inventory=ExplicitInventorySnapshot(
                status=inventory.status.value,
                total_qty=inventory.total_qty,
                inventory_revision=inventory.inventory_revision,
            ),
            bars=bars,
            trading_calendar=calendar,
            manual_event_risk=manual_value,
            manual_event_risk_revision=manual_revision,
        )

    def _load_rule_states(self, plan: ExplicitTradePlan, revision: int):
        with self._work() as work:
            return work.explicit_rules.states(
                plan_hash=plan_sha256(plan),
                symbol=plan.symbol,
                activation_revision=revision,
            )

    @staticmethod
    def _require_active(work: UnitOfWork, plan: ExplicitTradePlan, revision: int | None):
        active = work.plans.get_active(plan.symbol)
        version = work.plans.get_version(plan.plan_id, plan.version)
        if (
            active is None
            or version is None
            or active.plan_version_id != version.id
            or version.plan_hash != plan_sha256(plan)
            or (revision is not None and active.revision != revision)
        ):
            raise StaleExplicitDecisionError("explicit plan activation changed")
        return active


def _contains_manual_risk(condition: object) -> bool:
    if condition is None:
        return False
    if getattr(condition, "type", None) == "MANUAL_EVENT_RISK_CLEAR":
        return True
    return any(_contains_manual_risk(child) for child in getattr(condition, "conditions", ()))


def _manual_risk_value(
    record: object,
    *,
    plan_hash: str,
    trade_date: date,
    cutoff: datetime,
) -> tuple[bool | None, int]:
    if record is None:
        return None, 0
    revision = record.revision
    if (
        record.plan_hash != plan_hash
        or record.expires_on < trade_date
        or record.confirmed_at > cutoff
    ):
        return None, revision
    return record.status is ManualEventRiskStatus.RISK_PRESENT, revision


__all__ = [
    "ExplicitRuntimeCycleResult",
    "ExplicitRuntimeCycleStatus",
    "ExplicitRuntimeEvaluationService",
    "StaleExplicitDecisionError",
]
