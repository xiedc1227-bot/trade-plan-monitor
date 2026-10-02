"""One daily confirmation grants one immutable quantity for the next session."""

from datetime import date, time

from trade_plan_monitor.decision.daily_conditions import evaluate_daily_condition
from trade_plan_monitor.domain.daily_plan_models import DailyEnabledRule, DailyResetPolicy
from trade_plan_monitor.state.daily_repository import daily_hash


def next_session(day: date, session_dates: tuple[date, ...]) -> date | None:
    """Use certified exchange dates, never guessed weekdays."""
    return next((d for d in session_dates if d > day), None)


def expire_daily_signal(signal, evaluated_at):
    """Maintain historical authority without ever granting execution under a successor."""
    day = signal.get("execution_date")
    if day is not None and (
        str(evaluated_at.date()) > day
        or (
            str(evaluated_at.date()) == day and evaluated_at.time().replace(tzinfo=None) >= time(15)
        )
    ):
        state = signal["state"]
        if state not in {"SIMULATED", "INVALIDATED"}:
            state = "EXPIRED"
        return {
            **signal,
            "state": state,
            "executable_qty": 0,
            "blockers": list(
                dict.fromkeys([*signal.get("blockers", ()), "ORDINARY_WINDOW_EXPIRED"])
            ),
        }
    return signal


def confirm_daily_signal(
    plan, rule, *, series, facts, previous, session_dates, plan_version_id, review_id
):
    if series is None or not isinstance(rule, DailyEnabledRule):
        return None
    day = series.bars[-1].trade_date
    if not rule.validity.start_date <= day <= rule.validity.end_date:
        return None
    evidence = tuple(
        evaluate_daily_condition(
            root, series, facts=facts, macd_min_observations=plan.monitoring.macd_min_observations
        )
        for root in (
            rule.price_structure,
            rule.volume_or_candle,
            rule.technical,
            *rule.prerequisites,
        )
    )
    if any(e.outcome != "SATISFIED" for e in evidence):
        return None
    zone = plan.levels.low_buy if rule.side == "BUY" else plan.levels.pressure
    if not zone.contains(series.bars[-1].close):
        return None
    execution_date = next_session(day, session_dates)
    old = tuple(s for s in previous if s["side"] == rule.side)
    independent = None
    if old:
        prior = old[-1]
        if prior["state"] in {"CONFIRMED", "READY"}:
            return None
        if isinstance(rule.independent_signal, DailyResetPolicy):
            reset_date = prior.get("reset_trade_date")
            if reset_date is None or not prior["confirmed_trade_date"] < reset_date < str(day):
                return None
            independent = "reset:" + reset_date
        else:
            event = next(
                (
                    f
                    for f in facts
                    if f.get("kind") == "INDEPENDENT_EVENT"
                    and f.get("prior_signal_id") == prior["signal_id"]
                    and f.get("trade_date") == str(day)
                    and f.get("verified") is True
                ),
                None,
            )
            if event is None:
                return None
            independent = event["id"]
    fingerprint = daily_hash(
        "daily-signal-evidence-v1", [e.model_dump(mode="json") for e in evidence]
    )
    identity = daily_hash(
        "daily-signal-occurrence-v1",
        {
            "lineage": plan.plan_id,
            "symbol": plan.symbol,
            "side": rule.side,
            "independent": independent or "FIRST",
        },
    )
    return {
        "signal_id": identity,
        "rule_id": rule.rule_id,
        "side": rule.side,
        "bucket": rule.bucket,
        "lineage": plan.plan_id,
        "state": "CONFIRMED",
        "planned_qty": rule.quantity,
        "simulated_qty": 0,
        "confirmed_trade_date": str(day),
        "execution_date": None if execution_date is None else str(execution_date),
        "evidence_fingerprint": fingerprint,
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "plan_version_id": plan_version_id,
        "review_id": review_id,
        "basis_id": series.basis_id,
        "executable_qty": 0,
        "blockers": [],
    }


def check_daily_execution(
    plan, signal, *, inventory, quote_fen, evaluated_at, tradable, risk_blocked, risk_known
):
    state = signal["state"]
    remaining = signal["planned_qty"] - signal["simulated_qty"]
    if remaining < 0:
        raise ValueError("signal consumption exceeds immutable quantity")
    blockers = []
    day = str(evaluated_at.date())
    clock = evaluated_at.time().replace(tzinfo=None)
    if signal["execution_date"] is None:
        return {
            **signal,
            "executable_qty": 0,
            "blockers": ["TRADING_CALENDAR_MISSING"],
        }
    if day > signal["execution_date"] or (day == signal["execution_date"] and clock >= time(15)):
        if state not in {"SIMULATED", "INVALIDATED"}:
            state = "EXPIRED"
        blockers.append("ORDINARY_WINDOW_EXPIRED")
    if state in {"SIMULATED", "INVALIDATED", "EXPIRED"}:
        blockers.append(state)
    if day != signal["execution_date"] or not (
        time(9, 30) <= clock < time(11, 30) or time(13) <= clock < time(15)
    ):
        blockers.append("OUTSIDE_EXECUTION_SESSION")
    if not tradable:
        blockers.append("TRADABILITY_OR_QUOTE_UNVERIFIED")
    zone = plan.levels.low_buy if signal["side"] == "BUY" else plan.levels.pressure
    if quote_fen is None or not zone.contains(quote_fen):
        blockers.append("OUTSIDE_PRICE_ZONE")
    if risk_blocked:
        blockers.append("HIGHER_PRIORITY_RISK")
    if signal.get("risk_invalidated"):
        blockers.append("CONFIRMED_RISK_INVALIDATED_ORDINARY_SIGNAL")
        if state not in {"SIMULATED"}:
            state = "INVALIDATED"
    if not risk_known:
        blockers.append("RISK_INPUT_UNKNOWN")
    if not inventory["known"]:
        blockers.append("POSITION_UNKNOWN")
    elif signal["side"] == "BUY":
        if plan.position.max_qty - inventory["total_qty"] < remaining:
            blockers.append("MAX_QUANTITY_CAPACITY")
    else:
        sellable = inventory.get("sellable_tactical")
        if sellable is None:
            blockers.append("SELLABLE_QUANTITY_UNKNOWN")
        elif min(inventory["tactical_qty"], sellable) < remaining:
            blockers.append("TACTICAL_SELLABLE_INSUFFICIENT")
    if not blockers:
        state = "READY"
    elif state == "READY":
        state = "CONFIRMED"
    return {
        **signal,
        "state": state,
        "executable_qty": remaining if not blockers else 0,
        "blockers": blockers,
    }
