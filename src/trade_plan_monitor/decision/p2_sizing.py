"""Exact tier selection; no clocks, providers, approval or capacity clipping."""

from decimal import Decimal
from fractions import Fraction

from trade_plan_monitor.domain.daily_plan_models import DailyValue, PositiveWholeQty
from trade_plan_monitor.domain.market_linkage_models import legal_quantity_floor
from trade_plan_monitor.domain.p2_policy_models import FixedSizing, TierSizing


class SizingResult(DailyValue):
    q0: PositiveWholeQty | None
    tier_index: int | None
    atr_fen: Decimal | None
    close_fen: Decimal | None
    blocker: str | None


def calculate_sizing(sizing, *, atr_fen, close_fen, minimum, increment, fixed_q0=None):
    """Compare rational ratios without context-dependent Decimal division."""
    def result(q0=None, tier=None, blocker=None):
        return SizingResult(q0=q0, tier_index=tier, atr_fen=atr_fen,
                            close_fen=close_fen, blocker=blocker)

    if isinstance(sizing, FixedSizing):
        return result(q0=fixed_q0)
    if not isinstance(sizing, TierSizing):
        raise TypeError("unsupported sizing policy")
    if minimum is None or increment is None:
        return result(blocker="MARKET_RULES_UNKNOWN")
    if (atr_fen is None or close_fen is None or not atr_fen.is_finite()
            or not close_fen.is_finite() or atr_fen < 0 or close_fen <= 0):
        return result(blocker="VOLATILITY_INPUT_UNKNOWN")
    ratio = Fraction(atr_fen) / Fraction(close_fen)
    index, band = next((i, t) for i, t in enumerate(sizing.tiers)
                      if Fraction(t.lower) <= ratio
                      and (t.upper is None or ratio < Fraction(t.upper)))
    ceiling = Fraction(sizing.base_qty) * Fraction(band.multiplier)
    q0 = legal_quantity_floor(ceiling.numerator // ceiling.denominator,
                              minimum=minimum, increment=increment)
    return result(q0=q0, tier=index, blocker=None if q0 else "VOLATILITY_BELOW_MINIMUM")
