"""Pure provisional-versus-official daily-close reconciliation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trade_plan_monitor.market_data.models import AShareSymbol, DailyBar


class CloseReconciliationStatus(StrEnum):
    """Whether the current trading date has an official close ready for evaluation."""

    CLOSE_PENDING = "CLOSE_PENDING"
    OFFICIAL_READY = "OFFICIAL_READY"


class CloseReconciliationIntent(BaseModel):
    """Immutable evidence and authorization boundary for close-risk evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    symbol: AShareSymbol
    trade_date: Annotated[date, Field(strict=True)]
    status: CloseReconciliationStatus
    provisional_bar: DailyBar | None
    official_bar: DailyBar | None
    close_delta_fen: Annotated[int, Field(strict=True)] | None
    advance_close_risk: Annotated[bool, Field(strict=True)]

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        """Copy the intent while revalidating public updates."""

        if not update:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)

    @model_validator(mode="after")
    def validate_intent(self) -> Self:
        for bar in (self.provisional_bar, self.official_bar):
            if bar is None:
                continue
            if bar.symbol != self.symbol:
                raise ValueError("daily bar symbol must match reconciliation symbol")
            if bar.trade_date != self.trade_date:
                raise ValueError("daily bar must match the current trading date")

        if self.provisional_bar is not None and self.provisional_bar.is_official:
            raise ValueError("provisional_bar must not be official")
        if self.official_bar is not None and not self.official_bar.is_official:
            raise ValueError("official_bar must be official")

        if self.official_bar is None:
            if self.status is not CloseReconciliationStatus.CLOSE_PENDING:
                raise ValueError("missing official bar must remain CLOSE_PENDING")
            if self.advance_close_risk:
                raise ValueError("missing official bar cannot advance close risk")
            if self.close_delta_fen is not None:
                raise ValueError("missing official bar cannot have a close delta")
            return self

        if self.status is not CloseReconciliationStatus.OFFICIAL_READY:
            raise ValueError("current official bar must be OFFICIAL_READY")
        if not self.advance_close_risk:
            raise ValueError("current official bar must advance close risk")
        expected_delta = (
            None
            if self.provisional_bar is None
            else self.official_bar.close_fen - self.provisional_bar.close_fen
        )
        if self.close_delta_fen != expected_delta:
            raise ValueError("close_delta_fen must match official minus provisional close")
        return self


def reconcile_daily_close(
    *,
    symbol: str,
    current_trade_date: date,
    daily_bars: tuple[DailyBar, ...],
) -> CloseReconciliationIntent:
    """Return the deterministic current-date reconciliation intent for one symbol."""

    if type(daily_bars) is not tuple:
        raise TypeError("daily_bars must be a tuple")
    if len(daily_bars) > 2:
        raise ValueError("daily_bars must contain at most 2 rows")
    if any(not isinstance(bar, DailyBar) for bar in daily_bars):
        raise TypeError("daily_bars must contain only DailyBar values")

    provisional: DailyBar | None = None
    official: DailyBar | None = None
    for bar in daily_bars:
        if bar.symbol != symbol:
            raise ValueError("daily bar symbol must match reconciliation symbol")
        if bar.trade_date != current_trade_date:
            raise ValueError("daily bar must match the current trading date")
        if bar.is_official:
            if official is not None:
                raise ValueError("daily_bars must contain at most one official bar")
            official = bar
        else:
            if provisional is not None:
                raise ValueError("daily_bars must contain at most one provisional bar")
            provisional = bar

    if official is None:
        return CloseReconciliationIntent(
            symbol=symbol,
            trade_date=current_trade_date,
            status=CloseReconciliationStatus.CLOSE_PENDING,
            provisional_bar=provisional,
            official_bar=None,
            close_delta_fen=None,
            advance_close_risk=False,
        )

    return CloseReconciliationIntent(
        symbol=symbol,
        trade_date=current_trade_date,
        status=CloseReconciliationStatus.OFFICIAL_READY,
        provisional_bar=provisional,
        official_bar=official,
        close_delta_fen=(
            None if provisional is None else official.close_fen - provisional.close_fen
        ),
        advance_close_risk=True,
    )


__all__ = [
    "CloseReconciliationIntent",
    "CloseReconciliationStatus",
    "reconcile_daily_close",
]
