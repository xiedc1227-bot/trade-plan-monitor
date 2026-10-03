"""Persistent authority for scoped manual event-risk confirmations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from functools import partial
from uuid import UUID
from zoneinfo import ZoneInfo

from anyio import to_thread

from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.state.models import PlanVersionStatus
from trade_plan_monitor.state.repositories import (
    ManualEventRiskRecord,
    RepositoryError,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.routers.manual_event_risk import (
    ManualEventRiskUnknownReason,
    ManualEventRiskView,
    ManualEventRiskViewStatus,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")






class PersistentManualEventRiskOperationService:
    """Resolve and mutate manual risk only against the server-owned active plan."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
        clock: Callable[[], datetime],
    ) -> None:
        if not callable(unit_of_work_factory) or not callable(clock):
            raise TypeError("unit_of_work_factory and clock must be callable")
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    async def get_manual_event_risk(self, *, symbol: str) -> ManualEventRiskView:
        try:
            return await to_thread.run_sync(partial(self._get_sync, symbol=symbol))
        except RepositoryError:
            raise RuntimeError("manual event risk read failed") from None


    def _get_sync(self, *, symbol: str) -> ManualEventRiskView:
        now = _shanghai_datetime(self._clock())
        with self._unit_of_work_factory() as work:
            scope = _active_scope(work, symbol)
            record = work.manual_event_risk.get(symbol)
        return _view(symbol=symbol, scope=scope, record=record, as_of=now)



class _ActivePlanScope:
    def __init__(self, *, symbol: str, plan_hash: str, version_id: str) -> None:
        self.symbol = symbol
        self.plan_hash = plan_hash
        self.version_id = version_id


def _active_scope(work: SqlAlchemyUnitOfWork, symbol: str) -> _ActivePlanScope | None:
    active = work.plans.get_active(symbol)
    if active is None:
        return None
    details = work.plans.get_version_details(active.plan_version_id)
    if details is None:
        raise RepositoryError("Active plan version is missing")
    try:
        plan = load_plan_json(details.payload_json)
        status = PlanVersionStatus(details.status)
    except TypeError, ValueError:
        raise RepositoryError("Stored active plan is invalid") from None
    if (
        status is not PlanVersionStatus.ACTIVE
        or details.id != active.plan_version_id
        or details.symbol != symbol
        or plan.symbol != symbol
        or plan_sha256(plan) != details.plan_hash
    ):
        raise RepositoryError("Stored active plan identity is invalid")
    return _ActivePlanScope(symbol=symbol, plan_hash=details.plan_hash, version_id=details.id)


def _view(
    *,
    symbol: str,
    scope: _ActivePlanScope | None,
    record: ManualEventRiskRecord | None,
    as_of: datetime,
) -> ManualEventRiskView:
    if scope is None:
        return ManualEventRiskView(
            symbol=symbol,
            plan_version_id=None,
            status=ManualEventRiskViewStatus.UNKNOWN,
            reason=ManualEventRiskUnknownReason.NO_ACTIVE_PLAN,
            expires_on=None,
            confirmed_at=None,
            revision=0,
        )
    if record is None:
        return ManualEventRiskView(
            symbol=scope.symbol,
            plan_version_id=UUID(scope.version_id),
            status=ManualEventRiskViewStatus.UNKNOWN,
            reason=ManualEventRiskUnknownReason.MISSING_CONFIRMATION,
            expires_on=None,
            confirmed_at=None,
            revision=0,
        )
    status = ManualEventRiskViewStatus(record.status.value)
    reason = None
    if record.plan_hash != scope.plan_hash:
        status = ManualEventRiskViewStatus.UNKNOWN
        reason = ManualEventRiskUnknownReason.PLAN_CHANGED
    elif record.expires_on < as_of.date():
        status = ManualEventRiskViewStatus.UNKNOWN
        reason = ManualEventRiskUnknownReason.EXPIRED
    return ManualEventRiskView(
        symbol=record.symbol,
        plan_version_id=UUID(scope.version_id),
        status=status,
        reason=reason,
        expires_on=record.expires_on,
        confirmed_at=_shanghai_datetime(record.confirmed_at),
        revision=record.revision,
    )


def _shanghai_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryError("manual event risk clock is invalid")
    return value.astimezone(_SHANGHAI)


__all__ = ["PersistentManualEventRiskOperationService"]
