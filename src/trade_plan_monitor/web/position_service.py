"""Persistent backend authority for read-only historical position-lot queries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from functools import partial
from uuid import UUID
from zoneinfo import ZoneInfo

from anyio import to_thread

from trade_plan_monitor.state.repositories import (
    InventorySnapshot,
    PositionLotRecord,
    RepositoryError,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.routers.positions import (
    PositionInventoryView,
    PositionLotPage,
    PositionLotView,
    PositionOpeningBalanceView,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")






class _TradingCalendarUnavailableError(Exception):
    """The requested date has no authoritative stored exchange calendar row."""


class PersistentPositionOperationService:
    """Read historical registered inventory without granting current simulation authority."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(unit_of_work_factory):
            raise TypeError("unit_of_work_factory must be callable")
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock or (lambda: datetime.now(_SHANGHAI))

    async def get_position_inventory(
        self,
        *,
        symbol: str,
        as_of_trade_date: date,
    ) -> PositionInventoryView:
        try:
            return await to_thread.run_sync(
                partial(
                    self._get_position_inventory_sync,
                    symbol=symbol,
                    as_of_trade_date=as_of_trade_date,
                )
            )
        except RepositoryError:
            raise RuntimeError("persistent inventory read failed") from None


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





    def _get_position_inventory_sync(
        self,
        *,
        symbol: str,
        as_of_trade_date: date,
    ) -> PositionInventoryView:
        cutoff = self._clock()
        with self._unit_of_work_factory() as work:
            snapshot = work.positions.inventory_snapshot(
                symbol,
                as_of_trade_date=as_of_trade_date,
                cutoff=cutoff,
            )
        return _position_inventory_view(snapshot)


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


def _position_inventory_view(snapshot: InventorySnapshot) -> PositionInventoryView:
    return PositionInventoryView(
        symbol=snapshot.symbol,
        status=snapshot.status.value,
        as_of_trade_date=snapshot.as_of_trade_date,
        cutoff=snapshot.cutoff.astimezone(_SHANGHAI),
        inventory_revision=snapshot.inventory_revision,
        total_quantity=snapshot.total_qty,
        sellable_quantity=snapshot.sellable_qty,
        confirmation_id=(
            None if snapshot.confirmation_id is None else UUID(snapshot.confirmation_id)
        ),
        confirmed_at=(
            None if snapshot.confirmed_at is None else snapshot.confirmed_at.astimezone(_SHANGHAI)
        ),
        included_lot_ids=tuple(UUID(value) for value in snapshot.included_lot_ids),
        opening_balances=tuple(
            PositionOpeningBalanceView(
                opening_balance_id=UUID(balance.id),
                symbol=balance.symbol,
                original_quantity=balance.original_qty,
                remaining_quantity=balance.remaining_qty,
                sellable_from=balance.sellable_from,
                revision=balance.revision,
            )
            for balance in snapshot.opening_balances
        ),
        missing_reasons=snapshot.missing_reasons,
    )




def _shanghai_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryError("Stored position timestamp is invalid")
    return value.astimezone(_SHANGHAI)


__all__ = ["PersistentPositionOperationService"]
