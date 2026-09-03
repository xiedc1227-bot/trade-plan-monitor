"""Persistent backend authority for manual position-lot Web operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from functools import partial
from uuid import UUID
from zoneinfo import ZoneInfo

from anyio import to_thread

from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.state.models import PlanVersionStatus
from trade_plan_monitor.state.repositories import (
    BoardLotViolationError,
    IdempotencyInProgressError,
    IdempotencyKeyReuseError,
    MaxPositionExceededError,
    PositionLotNotFoundError,
    PositionLotRecord,
    PositionReductionError,
    PositionT1LockedError,
    RepositoryError,
    RevisionConflictError,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.idempotency import claim_replay, complete_replay, operation_hash
from trade_plan_monitor.web.routers.positions import (
    PositionLotClosureCommand,
    PositionLotClosureView,
    PositionLotCreateCommand,
    PositionLotPage,
    PositionLotView,
)
from trade_plan_monitor.web.schemas import MutationContext

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _ActivePlanRequiredError(Exception):
    """The requested buy has no active plan-owned position policy."""


class _TradingCalendarConflictError(Exception):
    """The requested reduction is not authorized by a stored open trading day."""


class _TradingCalendarUnavailableError(Exception):
    """The requested date has no authoritative stored exchange calendar row."""


class PersistentPositionOperationService:
    """Apply all position policy inside one short persistent transaction."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
    ) -> None:
        if not callable(unit_of_work_factory):
            raise TypeError("unit_of_work_factory must be callable")
        self._unit_of_work_factory = unit_of_work_factory

    async def list_position_lots(
        self,
        *,
        symbol: str,
        as_of_trade_date: date,
        offset: int,
        limit: int,
    ) -> PositionLotPage:
        try:
            return await to_thread.run_sync(
                partial(
                    self._list_position_lots_sync,
                    symbol=symbol,
                    as_of_trade_date=as_of_trade_date,
                    offset=offset,
                    limit=limit,
                )
            )
        except _TradingCalendarUnavailableError:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE) from None
        except RepositoryError:
            raise RuntimeError("persistent position read failed") from None

    async def record_position_lot(
        self,
        *,
        command: PositionLotCreateCommand,
        context: MutationContext,
    ) -> PositionLotView:
        return await self._run_mutation(
            self._record_position_lot_sync,
            operation="RECORD_POSITION_LOT",
            command=command,
            context=context,
        )

    async def close_position_lot(
        self,
        *,
        command: PositionLotClosureCommand,
        context: MutationContext,
    ) -> PositionLotClosureView:
        return await self._run_mutation(
            self._close_position_lot_sync,
            operation="CLOSE_POSITION_LOT",
            command=command,
            context=context,
        )

    async def _run_mutation[ResultT](
        self,
        function: Callable[..., ResultT],
        *,
        operation: str,
        command: PositionLotCreateCommand | PositionLotClosureCommand,
        context: MutationContext,
    ) -> ResultT:
        request_hash = operation_hash(operation, command)
        try:
            return await to_thread.run_sync(
                partial(
                    function,
                    request_hash=request_hash,
                    context=context,
                    command=command,
                )
            )
        except IdempotencyKeyReuseError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        except PositionLotNotFoundError:
            raise ApiError(ApiErrorCode.NOT_FOUND) from None
        except BoardLotViolationError:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None
        except _TradingCalendarUnavailableError:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE) from None
        except (
            _ActivePlanRequiredError,
            _TradingCalendarConflictError,
            IdempotencyInProgressError,
            MaxPositionExceededError,
            PositionReductionError,
            PositionT1LockedError,
            RevisionConflictError,
        ):
            raise ApiError(ApiErrorCode.CONFLICT) from None
        except RepositoryError:
            raise RuntimeError("persistent position operation failed") from None

    def _list_position_lots_sync(
        self,
        *,
        symbol: str,
        as_of_trade_date: date,
        offset: int,
        limit: int,
    ) -> PositionLotPage:
        with self._unit_of_work_factory() as work:
            records, total = work.positions.list_lots(
                symbol,
                offset=offset,
                limit=limit,
            )
            previous_trade_date = _previous_open_trade_date(
                work,
                symbol=symbol,
                trade_date=as_of_trade_date,
            )
            items = tuple(
                _position_lot_view(
                    record,
                    sellable_quantity=(
                        record.remaining_qty
                        if previous_trade_date is not None
                        and record.acquired_trade_date <= previous_trade_date
                        else 0
                    ),
                )
                for record in records
            )
        return PositionLotPage(
            items=items,
            symbol=symbol,
            as_of_trade_date=as_of_trade_date,
            offset=offset,
            limit=limit,
            total=total,
        )

    def _record_position_lot_sync(
        self,
        *,
        request_hash: str,
        context: MutationContext,
        command: PositionLotCreateCommand,
    ) -> PositionLotView:
        with self._unit_of_work_factory() as work:
            replay = claim_replay(
                work,
                context=context,
                request_hash=request_hash,
                model_type=PositionLotView,
            )
            if replay is not None:
                return replay
            plan = _active_plan(work, command.symbol)
            record = work.positions.record_buy(
                symbol=command.symbol,
                bucket=command.bucket,
                quantity=command.quantity,
                acquired_trade_date=command.acquired_trade_date,
                cost_fen=command.cost_fen,
                board_lot=plan.position.lot_size,
                max_position_qty=plan.position.max_qty,
                related_alert_id=(
                    None if command.related_alert_id is None else str(command.related_alert_id)
                ),
            )
            result = _position_lot_view(record, sellable_quantity=0)
            complete_replay(
                work,
                context=context,
                request_hash=request_hash,
                response=result,
            )
            work.commit()
            return result

    def _close_position_lot_sync(
        self,
        *,
        request_hash: str,
        context: MutationContext,
        command: PositionLotClosureCommand,
    ) -> PositionLotClosureView:
        with self._unit_of_work_factory() as work:
            replay = claim_replay(
                work,
                context=context,
                request_hash=request_hash,
                model_type=PositionLotClosureView,
            )
            if replay is not None:
                return replay
            before = work.positions.get_lot(str(command.lot_id))
            previous_trade_date = _previous_open_trade_date(
                work,
                symbol=before.symbol,
                trade_date=command.trade_date,
            )
            if previous_trade_date is None or before.acquired_trade_date > previous_trade_date:
                raise _TradingCalendarConflictError
            after = work.positions.reduce_lot(
                str(command.lot_id),
                quantity=command.quantity,
                trade_date=command.trade_date,
                expected_revision=command.expected_revision,
                board_lot=100,
            )
            result = PositionLotClosureView(
                lot=_position_lot_view(
                    after,
                    sellable_quantity=after.remaining_qty,
                ),
                applied_quantity=command.quantity,
                trade_date=command.trade_date,
                before_remaining_quantity=after.remaining_qty + command.quantity,
                after_remaining_quantity=after.remaining_qty,
            )
            complete_replay(
                work,
                context=context,
                request_hash=request_hash,
                response=result,
            )
            work.commit()
            return result


def _active_plan(work: SqlAlchemyUnitOfWork, symbol: str) -> TradePlan:
    active = work.plans.get_active(symbol)
    if active is None:
        raise _ActivePlanRequiredError
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
        or plan.plan_id != details.plan_id
        or plan.version != details.version
        or plan.symbol != symbol
        or plan_sha256(plan) != details.plan_hash
    ):
        raise RepositoryError("Stored active plan identity is invalid")
    return plan


def _previous_open_trade_date(
    work: SqlAlchemyUnitOfWork,
    *,
    symbol: str,
    trade_date: date,
) -> date | None:
    rows = work.references.list_trading_days(
        _exchange_for_symbol(symbol),
        trade_date,
        trade_date,
    )
    if not rows:
        raise _TradingCalendarUnavailableError
    if len(rows) != 1 or rows[0].cal_date != trade_date:
        raise RepositoryError("Stored trading calendar is inconsistent")
    day = rows[0]
    return day.previous_trade_date if day.is_open else None


def _exchange_for_symbol(symbol: str) -> str:
    suffix = symbol.rsplit(".", maxsplit=1)[-1]
    try:
        return {"BJ": "BSE", "SH": "SSE", "SZ": "SZSE"}[suffix]
    except KeyError:
        raise ValueError("symbol exchange is invalid") from None


def _position_lot_view(
    record: PositionLotRecord,
    *,
    sellable_quantity: int,
) -> PositionLotView:
    return PositionLotView(
        lot_id=UUID(record.id),
        symbol=record.symbol,
        bucket=record.bucket,
        quantity=record.quantity,
        remaining_quantity=record.remaining_qty,
        sellable_quantity=sellable_quantity,
        acquired_trade_date=record.acquired_trade_date,
        cost_fen=record.cost_fen,
        related_alert_id=(
            None if record.related_alert_id is None else UUID(record.related_alert_id)
        ),
        closed_at=(None if record.closed_at is None else _shanghai_datetime(record.closed_at)),
        revision=(record.quantity - record.remaining_qty) // 100,
    )


def _shanghai_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryError("Stored position timestamp is invalid")
    return value.astimezone(_SHANGHAI)


__all__ = ["PersistentPositionOperationService"]
