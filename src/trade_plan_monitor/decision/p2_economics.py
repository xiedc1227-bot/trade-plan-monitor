"""Frozen scenario economics, never account cash or execution authority."""

from fractions import Fraction
from typing import Literal

from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.p2_policy_models import MAX_SAFE, NoEconomics, RequiredEconomics


class EconomicsResult(DailyValue):
    version: Literal["p2-economics-v1"] = "p2-economics-v1"
    outcome: Literal["NONE", "PASS", "FAIL", "UNKNOWN"]
    reason: str | None = None
    blockers: tuple[str, ...] = ()
    quantity: int | None = None
    entry_debit_fen: int | None = None
    target_proceeds_fen: int | None = None
    risk_proceeds_fen: int | None = None
    net_reward_fen: int | None = None
    planned_loss_fen: int | None = None
    total_cost_fen: int | None = None
    spread_numerator: int | None = None
    spread_denominator: int | None = None
    entry_fees: dict[str, int] | None = None
    target_fees: dict[str, int] | None = None
    risk_fees: dict[str, int] | None = None


def _fees(schedule, side, notional):
    def fee(rate):
        value = Fraction(notional) * Fraction(rate)
        return -(-value.numerator // value.denominator)

    result = {"COMMISSION": max(schedule.minimum_commission_fen, fee(schedule.commission_rate))}
    result.update({c.id: fee(c.rate) for c in schedule.components
                   if c.side in {side, "BOTH"} and c.included_in is None})
    return result


def calculate_economics(policy, *, quantity, entry_fen, symbol, session):
    """Use exact integer fees and cross-multiplied gates, no rounded ratio veto."""
    required = isinstance(policy, RequiredEconomics)

    def unknown(reason):
        return EconomicsResult(outcome="UNKNOWN", reason=reason,
                               blockers=(reason,) if required else ())

    if isinstance(policy, NoEconomics):
        return EconomicsResult(outcome="NONE")
    f = policy.fee_schedule
    if symbol not in f.symbols or not f.effective_from <= session <= f.effective_through:
        return unknown("FEE_SCHEDULE_NOT_APPLICABLE")
    if (type(quantity) is not int or not 0 < quantity <= MAX_SAFE or quantity % 100
            or type(entry_fen) is not int or not 0 < entry_fen <= MAX_SAFE):
        return unknown("ECONOMICS_INPUT_UNKNOWN")
    if not policy.risk_price_fen < entry_fen < policy.target_price_fen:
        return unknown("ECONOMICS_PRICE_ORDER")
    buy_price = entry_fen + f.buy_slippage_fen
    target_price = policy.target_price_fen - f.sell_slippage_fen
    risk_price = policy.risk_price_fen - f.sell_slippage_fen
    if min(target_price, risk_price) <= 0:
        return unknown("ECONOMICS_SLIPPAGE_PRICE")
    b, t, z = (quantity * p for p in (buy_price, target_price, risk_price))
    bf, tf, zf = _fees(f, "BUY", b), _fees(f, "SELL", t), _fees(f, "SELL", z)
    debit, target, risk = b + sum(bf.values()), t - sum(tf.values()), z - sum(zf.values())
    reward, loss = target - debit, debit - risk
    cost = sum(bf.values()) + sum(tf.values()) + quantity * (
        f.buy_slippage_fen + f.sell_slippage_fen)
    if any(abs(v) > MAX_SAFE for v in (b, t, z, debit, target, risk, reward, loss, cost)):
        return unknown("ECONOMICS_OVERFLOW")
    if loss <= 0:
        return unknown("ECONOMICS_RISK_UNDEFINED")
    failed = required and (
        policy.gates.min_net_reward_fen is not None and reward < policy.gates.min_net_reward_fen
        or policy.gates.min_reward_risk_ratio is not None
        and Fraction(reward, loss) < Fraction(policy.gates.min_reward_risk_ratio))
    spread = Fraction(cost, quantity)
    return EconomicsResult(outcome="FAIL" if failed else "PASS", quantity=quantity,
        blockers=("ECONOMICS_GATE_UNMET",) if failed else (),
        entry_debit_fen=debit, target_proceeds_fen=target, risk_proceeds_fen=risk,
        net_reward_fen=reward, planned_loss_fen=loss, total_cost_fen=cost,
        spread_numerator=spread.numerator, spread_denominator=spread.denominator,
        entry_fees=bf, target_fees=tf, risk_fees=zf)
