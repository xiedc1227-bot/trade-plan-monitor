"""P2 preparation feeds unchanged market policies without rewriting source plans."""

from trade_plan_monitor.decision.market_exception_decision import (
    MarketExceptionDecision,
    _seal_calculation,
    _seal_decision,
    evaluate_market_exception,
)
from trade_plan_monitor.decision.p2_economics import EconomicsResult, calculate_economics
from trade_plan_monitor.decision.p2_sizing import SizingResult, calculate_sizing
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.market_exception_models import MarketExceptionRule
from trade_plan_monitor.domain.market_quantity_rules import official_buy_grid
from trade_plan_monitor.domain.p2_policy_models import FixedSizing
from trade_plan_monitor.market_data.daily_indicators import calculate_daily_ta_v2


class P2Decision(DailyValue):
    sizing: SizingResult
    economics: EconomicsResult | None
    decision: MarketExceptionDecision | None


def prepare_p2_rule(plan, rule, *, series, decision_session, cutoff):
    """Use only completed, available, admitted data for the exact decision day."""
    grid = official_buy_grid(plan.symbol, decision_session)
    current = (series is not None and series.symbol == plan.symbol
               and series.bars[-1].trade_date == decision_session
               and all(bar.available_at <= cutoff for bar in series.bars))
    atr = calculate_daily_ta_v2(series)[-1]["ATR14"] if current else None
    sizing = calculate_sizing(rule.pretrade_policy.sizing,
        atr_fen=None if atr is None else atr*100,
        close_fen=series.bars[-1].close if current else None,
        minimum=None if grid is None else grid.minimum,
        increment=None if grid is None else grid.increment,
        fixed_q0=(rule.quantity_policy.base_quantity
                  if isinstance(rule.pretrade_policy.sizing, FixedSizing) else None))
    if sizing.q0 is None:
        return None, sizing
    raw = rule.model_dump(mode="json", exclude={"pretrade_policy"})
    raw["quantity_policy"] = raw["quantity_policy"] | {
        "mode": "MARKET_FACTOR", "base_quantity": sizing.q0}
    return MarketExceptionRule.model_validate(raw), sizing


def evaluate_p2_market(plan, rule, **inputs):
    effective, sizing = prepare_p2_rule(plan, rule, series=inputs["series"],
        decision_session=inputs["decision_session"], cutoff=inputs["cutoff"])
    if effective is None:
        return P2Decision(sizing=sizing, economics=None, decision=None)
    decision = evaluate_market_exception(plan, effective, **inputs)
    close = sizing.close_fen
    economics = calculate_economics(rule.pretrade_policy.economics,
        quantity=decision.calculation.candidate_quantity,
        entry_fen=int(close) if close is not None and close == int(close) else None,
        symbol=plan.symbol, session=inputs["decision_session"])
    # BROKEN_STRONG has no proposed quantity yet; economics is checked once the
    # human enters the exact quantity, never used to choose one automatically.
    if economics.blockers and decision.calculation.route is None:
        calculation = decision.calculation.model_dump(mode="json")
        calculation.update(authorized_quantity=0,
            blockers=list(dict.fromkeys([*calculation["blockers"], *economics.blockers])))
        decision = _seal_decision(decision.model_dump(mode="json") | {
            "calculation": _seal_calculation(calculation).model_dump(mode="json")})
    return P2Decision(sizing=sizing, economics=economics, decision=decision)
