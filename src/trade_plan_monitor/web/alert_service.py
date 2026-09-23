"""Persistent backend authority for alert-center Web operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from functools import partial
from zoneinfo import ZoneInfo

from anyio import to_thread

from trade_plan_monitor.decision.models import ActionableSignalType
from trade_plan_monitor.notifications.models import AlertEvent, ExplicitAlertEvent
from trade_plan_monitor.notifications.outbox import (
    AlertNotFoundError,
    AlertRevisionConflictError,
    OutboxError,
)
from trade_plan_monitor.state.repositories import (
    IdempotencyInProgressError,
    IdempotencyKeyReuseError,
    RepositoryError,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.idempotency import claim_replay, complete_replay, operation_hash
from trade_plan_monitor.web.routers.alerts import (
    AlertAcknowledgementCommand,
    AlertRecord,
    AlertRecordPage,
    DiagnosticEvaluationCommand,
    DiagnosticEvaluationRecord,
    PositionPrefillAction,
    PositionPrefillView,
)
from trade_plan_monitor.web.schemas import MutationContext

_SHANGHAI = ZoneInfo("Asia/Shanghai")
Clock = Callable[[], datetime]


class PersistentAlertOperationService:
    """Query and acknowledge canonical alerts in the shared local transaction boundary."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
        clock: Clock | None = None,
    ) -> None:
        if not callable(unit_of_work_factory):
            raise TypeError("unit_of_work_factory must be callable")
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock or (lambda: datetime.now(_SHANGHAI))

    async def list_alerts(
        self,
        *,
        symbol: str | None,
        signal_type: str | None,
        acknowledged: bool | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> AlertRecordPage:
        try:
            return await to_thread.run_sync(
                partial(
                    self._list_alerts_sync,
                    symbol=symbol,
                    signal_type=signal_type,
                    acknowledged=acknowledged,
                    start_at=start_at,
                    end_at=end_at,
                    offset=offset,
                    limit=limit,
                )
            )
        except OutboxError:
            raise RuntimeError("persistent alert read failed") from None

    async def acknowledge_alert(
        self,
        *,
        command: AlertAcknowledgementCommand,
        context: MutationContext,
    ) -> AlertRecord:
        request_hash = operation_hash("ACKNOWLEDGE_ALERT", command)
        try:
            return await to_thread.run_sync(
                partial(
                    self._acknowledge_alert_sync,
                    command=command,
                    context=context,
                    request_hash=request_hash,
                )
            )
        except IdempotencyKeyReuseError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        except AlertNotFoundError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        except (AlertRevisionConflictError, IdempotencyInProgressError):
            raise ApiError(ApiErrorCode.CONFLICT) from None
        except (OutboxError, RepositoryError):
            raise RuntimeError("persistent alert acknowledgement failed") from None

    async def evaluate_diagnostic(
        self,
        *,
        command: DiagnosticEvaluationCommand,
        context: MutationContext,
    ) -> DiagnosticEvaluationRecord:
        del command, context
        raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)

    def _list_alerts_sync(
        self,
        *,
        symbol: str | None,
        signal_type: str | None,
        acknowledged: bool | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> AlertRecordPage:
        market_date = self._current_market_date()
        with self._unit_of_work_factory() as work:
            events, total = work.alerts.list_events(
                symbol=symbol,
                signal_type=signal_type,
                acknowledged=acknowledged,
                start_at=start_at,
                end_at=end_at,
                offset=offset,
                limit=limit,
            )
            records = tuple(
                _alert_record(
                    event,
                    current_actionable=work.alerts.is_current_actionable(
                        event,
                        market_date=market_date,
                    ),
                )
                for event in events
            )
        return AlertRecordPage(
            items=records,
            symbol=symbol,
            signal_type=signal_type,
            acknowledged=acknowledged,
            start_at=start_at,
            end_at=end_at,
            offset=offset,
            limit=limit,
            total=total,
        )

    def _acknowledge_alert_sync(
        self,
        *,
        command: AlertAcknowledgementCommand,
        context: MutationContext,
        request_hash: str,
    ) -> AlertRecord:
        with self._unit_of_work_factory() as work:
            replay = claim_replay(
                work,
                context=context,
                request_hash=request_hash,
                model_type=AlertRecord,
            )
            if replay is not None:
                return _alert_record(
                    replay.event,
                    current_actionable=work.alerts.is_current_actionable(
                        replay.event,
                        market_date=self._current_market_date(),
                    ),
                )
            event = work.alerts.acknowledge(
                command.alert_id,
                expected_revision=command.expected_revision,
            )
            result = _alert_record(
                event,
                current_actionable=work.alerts.is_current_actionable(
                    event,
                    market_date=self._current_market_date(),
                ),
            )
            complete_replay(
                work,
                context=context,
                request_hash=request_hash,
                response=result,
            )
            work.commit()
            return result

    def _current_market_date(self) -> date:
        current = self._clock()
        if (
            not isinstance(current, datetime)
            or current.tzinfo is None
            or current.utcoffset() is None
        ):
            raise RuntimeError("alert clock must return an aware datetime")
        return current.astimezone(_SHANGHAI).date()


def _alert_record(
    event: AlertEvent | ExplicitAlertEvent,
    *,
    current_actionable: bool,
) -> AlertRecord:
    return AlertRecord(
        event=event,
        revision=0 if event.acknowledged_at is None else 1,
        current_actionable=current_actionable,
        position_prefill=_position_prefill(event) if current_actionable else None,
    )


def _position_prefill(
    event: AlertEvent | ExplicitAlertEvent,
) -> PositionPrefillView | None:
    if isinstance(event, ExplicitAlertEvent):
        return None
    buys = {
        ActionableSignalType.BUY_CORE_READY,
        ActionableSignalType.BUY_TACTICAL_READY,
    }
    closures = {
        ActionableSignalType.PRESSURE_REDUCE_READY,
        ActionableSignalType.RISK_EXIT_READY,
    }
    if event.signal_type not in buys | closures:
        return None
    if event.signal_type is ActionableSignalType.RISK_EXIT_READY and event.bucket is None:
        # An opening balance is a confirmed holding, not a fabricated lot.
        # The operator chooses the actual inventory source when recording a sale.
        return None
    if event.quantity is None or event.bucket is None:
        raise RuntimeError("canonical alert is missing position prefill data")
    return PositionPrefillView(
        action=(
            PositionPrefillAction.BUY
            if event.signal_type in buys
            else PositionPrefillAction.CLOSE
        ),
        symbol=event.symbol,
        bucket=event.bucket,
        quantity=event.quantity,
        target_lot_id=event.target_lot_id,
        related_alert_id=event.event_id,
    )


__all__ = ["PersistentAlertOperationService"]
