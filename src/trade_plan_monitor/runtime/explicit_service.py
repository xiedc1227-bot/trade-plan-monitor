"""Activation- and revision-fenced SQLite runtime for the bounded R09 BUY mode."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from inspect import isawaitable
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
from trade_plan_monitor.state.events import MonitorEvent, MonitorEventType
from trade_plan_monitor.state.repositories import ManualEventRiskStatus
from trade_plan_monitor.state.unit_of_work import UnitOfWork


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class StaleExplicitDecisionError(RuntimeError):
    """A consumed activation or mutable safety fact changed before commit."""

    code = "STALE_EXPLICIT_DECISION"


class PlanCycleStale(StrEnum):
    """Closed reasons produced only by known pre-commit guards."""

    LEGACY = "STALE_ACTIVATION_GENERATION"
    EXPLICIT = "STALE_EXPLICIT_DECISION"


@dataclass(frozen=True)
class _PrecommitStale:
    reason: PlanCycleStale


def _stale_explicit(message: str, account_stale: bool) -> _PrecommitStale:
    if account_stale:
        return _PrecommitStale(PlanCycleStale.EXPLICIT)
    raise StaleExplicitDecisionError(message)


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
        committed_event_publisher: Callable[[MonitorEvent], object] | None = None,
        recovery_delivery: bool = False,
        commit_admission: Callable[[], bool] | None = None,
    ) -> None:
        if type(recovery_delivery) is not bool:
            raise TypeError("recovery_delivery must be a bool")
        if not callable(unit_of_work_factory):
            raise TypeError("unit_of_work_factory must be callable")
        if after_evaluate is not None and not callable(after_evaluate):
            raise TypeError("after_evaluate must be callable")
        if committed_event_publisher is not None and not callable(committed_event_publisher):
            raise TypeError("committed_event_publisher must be callable")
        if commit_admission is not None and not callable(commit_admission):
            raise TypeError("commit_admission must be callable")
        self._work = unit_of_work_factory
        self._after_evaluate = after_evaluate
        self._publisher = committed_event_publisher
        # Storage-only opt-in; the existing dispatcher does not enforce this HOLD.
        self._recovery_delivery = recovery_delivery
        self._commit_admission = commit_admission or (lambda: True)

    async def run_intraday_and_publish(
        self,
        *,
        plan: ExplicitTradePlan,
        target_bucket_end: datetime,
        evaluated_at: datetime,
        expected_activation_revision: int | None = None,
    ) -> ExplicitRuntimeCycleResult:
        """Evaluate once, then publish only the durable alert invalidations."""

        result = self.run_intraday(
            plan=plan,
            target_bucket_end=target_bucket_end,
            evaluated_at=evaluated_at,
            expected_activation_revision=expected_activation_revision,
        )
        return await self._publish_result(result)

    async def run_intraday_associated_and_publish(
        self,
        *,
        plan: ExplicitTradePlan,
        target_bucket_end: datetime,
        evaluated_at: datetime,
        expected_activation_revision: int,
    ) -> ExplicitRuntimeCycleResult | _PrecommitStale:
        """Keep guard disposition separate from every commit/publication error."""
        if type(expected_activation_revision) is not int or expected_activation_revision < 1:
            raise ValueError("strict explicit evaluation requires an activation revision")
        result = self._run_intraday(
            plan=plan, target_bucket_end=target_bucket_end, evaluated_at=evaluated_at,
            expected_activation_revision=expected_activation_revision, account_stale=True,
        )
        if isinstance(result, _PrecommitStale):
            return result
        return await self._publish_result(result)

    async def _publish_result(
        self, result: ExplicitRuntimeCycleResult,
    ) -> ExplicitRuntimeCycleResult:
        if self._publisher is None or not result.committed_events:
            return result
        with self._work() as work:
            monitor_events = tuple(
                work.events.get(event.event_id) for event in result.committed_events
            )
        if any(
            event is None or event.event_type is not MonitorEventType.ALERT_CREATED
            for event in monitor_events
        ):
            raise RuntimeError("committed explicit alert event is unavailable")
        for event in monitor_events:
            if event is None:  # pragma: no cover - guarded above for type narrowing
                continue
            publication = self._publisher(event)
            if isawaitable(publication):
                await publication
        return result

    def run_intraday(
        self,
        *,
        plan: ExplicitTradePlan,
        target_bucket_end: datetime,
        evaluated_at: datetime,
        expected_activation_revision: int | None = None,
    ) -> ExplicitRuntimeCycleResult:
        result = self._run_intraday(
            plan=plan, target_bucket_end=target_bucket_end, evaluated_at=evaluated_at,
            expected_activation_revision=expected_activation_revision, account_stale=False,
        )
        if not isinstance(result, ExplicitRuntimeCycleResult):
            raise RuntimeError("standalone explicit evaluation returned a stale disposition")
        return result

    def _run_intraday(
        self, *, plan: ExplicitTradePlan, target_bucket_end: datetime, evaluated_at: datetime,
        expected_activation_revision: int | None, account_stale: bool,
    ) -> ExplicitRuntimeCycleResult | _PrecommitStale:
        if type(plan) is not ExplicitTradePlan:
            raise TypeError("plan must be an ExplicitTradePlan")
        if expected_activation_revision is not None and (
            type(expected_activation_revision) is not int or expected_activation_revision < 1
        ):
            raise ValueError("expected activation revision must be a positive integer")
        captured = self._capture(
            plan, target_bucket_end, expected_activation_revision, account_stale=account_stale,
        )
        if isinstance(captured, _PrecommitStale):
            return captured
        with self._work() as work:
            existing = work.explicit_rules.get(
                plan_hash=plan_sha256(plan),
                symbol=plan.symbol,
                target_bucket_end=target_bucket_end,
                activation_revision=captured.activation_revision,
            )
        if existing is not None:
            self._validate_result_identity(plan, target_bucket_end, captured, existing)
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
        self._validate_result_identity(plan, target_bucket_end, captured, result)
        if self._after_evaluate is not None:
            self._after_evaluate(result)

        committed: list[ExplicitAlertEvent] = []
        with self._work() as work:
            active = self._require_active(
                work, plan, captured.activation_revision, account_stale=account_stale,
            )
            if isinstance(active, _PrecommitStale):
                return active
            current_inventory = work.positions.inventory_snapshot(
                plan.symbol,
                as_of_trade_date=target_bucket_end.date(),
                cutoff=target_bucket_end,
            )
            if result.inventory_revision is not None and (
                current_inventory.inventory_revision != result.inventory_revision
                or current_inventory.status.value != captured.inventory.status
                or current_inventory.total_qty != captured.inventory.total_qty
                or current_inventory.sellable_qty != captured.inventory.sellable_qty
                or current_inventory.missing_reasons != captured.inventory.missing_reasons
            ):
                return _stale_explicit("inventory changed before trade commit", account_stale)
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
                    return _stale_explicit(
                        "manual event risk changed before BUY commit", account_stale,
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
                    committed.append(
                        work.alerts.enqueue_recoverable(payload)
                        if self._recovery_delivery
                        else work.alerts.enqueue_explicit(payload)
                    )
            if record.created and not self._commit_admission():
                raise RuntimeError("runtime decision commit admission revoked")
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

    @staticmethod
    def _validate_result_identity(
        plan: ExplicitTradePlan, target: datetime, captured: _CapturedContext,
        result: ExplicitEvaluationResult,
    ) -> None:
        if (
            not isinstance(result, ExplicitEvaluationResult)
            or result.symbol != plan.symbol
            or result.plan_hash != plan_sha256(plan)
            or result.target_bucket_end != target
            or result.activation_revision != captured.activation_revision
            or result.execution_version != plan.execution_version
        ):
            raise RuntimeError("explicit result identity differs from captured plan")

    def _capture(
        self, plan: ExplicitTradePlan, target: datetime,
        expected_activation_revision: int | None = None, *, account_stale: bool = False,
    ) -> _CapturedContext | _PrecommitStale:
        digest = plan_sha256(plan)
        with self._work() as work:
            active = self._require_active(
                work, plan, expected_activation_revision, account_stale=account_stale,
            )
            if isinstance(active, _PrecommitStale):
                return active
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
                sellable_qty=inventory.sellable_qty,
                inventory_revision=inventory.inventory_revision,
                missing_reasons=inventory.missing_reasons,
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
    def _require_active(
        work: UnitOfWork, plan: ExplicitTradePlan, revision: int | None,
        *, account_stale: bool = False,
    ):
        active = work.plans.get_active(plan.symbol)
        version = work.plans.get_version(plan.plan_id, plan.version)
        if (
            active is None
            or version is None
            or active.plan_version_id != version.id
            or version.plan_hash != plan_sha256(plan)
            or (revision is not None and active.revision != revision)
        ):
            return _stale_explicit("explicit plan activation changed", account_stale)
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
