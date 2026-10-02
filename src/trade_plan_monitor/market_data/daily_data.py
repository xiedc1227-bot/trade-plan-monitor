"""Official daily QFQ admission; raw DailyBar is deliberately insufficient."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal, Self

from pydantic import Field, model_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue, Fen, Number, Qty, Text
from trade_plan_monitor.market_data.models import DailyBar, ShanghaiDatetime


class CertifiedDailyBar(DailyValue):
    bar_id: Text
    symbol: str
    trade_date: date
    open: Number
    high: Number
    low: Number
    close: Number
    volume_shares: Qty
    official: Literal[True]
    provider: Text
    price_basis: Literal["QFQ"] = "QFQ"
    basis_id: Text
    adjustment_as_of: date
    received_at: ShanghaiDatetime
    available_at: ShanghaiDatetime

    @model_validator(mode="after")
    def valid_ohlc(self) -> Self:
        if (
            not 0
            < self.low
            <= min(self.open, self.close)
            <= max(self.open, self.close)
            <= self.high
        ):
            raise ValueError("invalid adjusted OHLC")
        close_time = datetime.combine(self.trade_date, time(15), self.available_at.tzinfo)
        if self.available_at < close_time or self.received_at < self.available_at:
            raise ValueError("daily data predates its official close")
        if self.adjustment_as_of < self.trade_date:
            raise ValueError("adjustment basis predates the bar")
        return self


class DailySeries(DailyValue):
    symbol: str
    bars: tuple[CertifiedDailyBar, ...] = Field(min_length=1, max_length=500)
    basis_id: Text
    adjustment_as_of: date
    provider: Text
    quote_comparable: Literal[True]
    session_dates: tuple[date, ...] = Field(min_length=1, max_length=1000)
    suspended_dates: tuple[date, ...] = Field(max_length=1000)
    cutoff: ShanghaiDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.adjustment_as_of > self.cutoff.date():
            raise ValueError("future adjustment basis cannot enter evaluation")
        dates = tuple(b.trade_date for b in self.bars)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("daily observations must increase strictly")
        if self.session_dates != tuple(sorted(set(self.session_dates))):
            raise ValueError("certified calendar dates must increase strictly")
        if set(self.suspended_dates) & set(dates):
            raise ValueError("suspension cannot also contain a bar")
        expected = tuple(
            d
            for d in self.session_dates
            if dates[0] <= d <= dates[-1] and d not in self.suspended_dates
        )
        if expected != dates:
            raise ValueError("scheduled daily observations are missing or uncertified")
        for bar in self.bars:
            if (bar.symbol, bar.provider, bar.basis_id, bar.adjustment_as_of) != (
                self.symbol,
                self.provider,
                self.basis_id,
                self.adjustment_as_of,
            ):
                raise ValueError("daily series mixes identities or adjustment bases")
            if bar.available_at > self.cutoff or bar.received_at > self.cutoff:
                raise ValueError("daily data is unavailable at evaluation cutoff")
        return self


class DailyAdmissionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def admit_qfq_daily(
    *,
    raw_bars: tuple[DailyBar, ...],
    factors: dict[date, Decimal],
    adjustment_as_of: date,
    quote_basis_factor: Decimal,
    provider: str,
    session_dates: tuple[date, ...],
    suspended_dates: tuple[date, ...],
    cutoff: datetime,
) -> DailySeries:
    """Apply verified same-provider corporate-action factors without tick rounding.

    The quote basis factor is separately obtained for the current adjustment date;
    a missing factor or incompatible current basis never becomes a raw fallback.
    """
    anchor = factors.get(adjustment_as_of)
    if not raw_bars or anchor is None or anchor <= 0 or anchor != quote_basis_factor:
        raise DailyAdmissionError("PRICE_BASIS_UNVERIFIED")
    # The price basis denotes the common normalization anchor, not a growing
    # dataset. Equal anchors stay comparable across consecutive official closes.
    # Individual certified bar identities still retain every factor/proof input.
    fingerprint = sha256(
        (provider + raw_bars[0].symbol + str(anchor.normalize())).encode()
    ).hexdigest()
    factor_proof = sha256(
        (str(adjustment_as_of) + repr(sorted(factors.items()))).encode()
    ).hexdigest()
    bars = []
    for bar in raw_bars:
        factor = factors.get(bar.trade_date)
        if not bar.is_official or factor is None or factor <= 0 or not factor.is_finite():
            raise DailyAdmissionError("PRICE_BASIS_UNVERIFIED")
        scale = factor / anchor
        bars.append(
            CertifiedDailyBar(
                bar_id=sha256(
                    (bar.model_dump_json() + fingerprint + factor_proof).encode()
                ).hexdigest(),
                symbol=bar.symbol,
                trade_date=bar.trade_date,
                open=Decimal(bar.open_fen) * scale,
                high=Decimal(bar.high_fen) * scale,
                low=Decimal(bar.low_fen) * scale,
                close=Decimal(bar.close_fen) * scale,
                volume_shares=bar.volume_shares,
                official=True,
                provider=provider,
                basis_id=fingerprint,
                adjustment_as_of=adjustment_as_of,
                received_at=bar.received_at,
                available_at=bar.received_at,
            )
        )
    try:
        return DailySeries(
            symbol=raw_bars[0].symbol,
            bars=tuple(bars),
            provider=provider,
            basis_id=fingerprint,
            adjustment_as_of=adjustment_as_of,
            quote_comparable=True,
            session_dates=session_dates,
            suspended_dates=suspended_dates,
            cutoff=cutoff,
        )
    except ValueError as error:
        raise DailyAdmissionError("DAILY_SESSION_OR_BASIS_UNVERIFIED") from error


class DailyExecutionQuote(DailyValue):
    symbol: str
    price_fen: Fen
    quote_at: ShanghaiDatetime
    available_at: ShanghaiDatetime
    evaluated_at: ShanghaiDatetime
    tradable: bool = Field(strict=True)
    special_state_verified: bool = Field(strict=True)
    liquidity_available: bool = Field(strict=True)

    @model_validator(mode="after")
    def fresh(self) -> Self:
        if (
            not self.quote_at <= self.available_at <= self.evaluated_at
            or self.evaluated_at - self.quote_at > timedelta(minutes=5)
        ):
            raise ValueError("execution quote is not fresh")
        return self
