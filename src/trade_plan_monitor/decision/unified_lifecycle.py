"""One reviewed signal grants one full simulation quantity in its explicit window."""

from datetime import datetime, time

from trade_plan_monitor.decision.daily_lifecycle import expire_daily_signal, next_session
from trade_plan_monitor.decision.unified_conditions import (
    evaluate_unified_condition,
    requires_daily,
    requires_minutes,
)
from trade_plan_monitor.domain.unified_plan_models import (
    AfterRuleCompleted,
    OncePerRule,
    UnifiedResetPolicy,
)
from trade_plan_monitor.state.daily_repository import daily_hash


def confirm_signal(
    plan,
    rule,
    *,
    series,
    facts,
    previous,
    session_dates,
    plan_version_id,
    review_id,
    bars=(),
    target=None,
    trading_calendar=(),
    linkage=None,
):
    from trade_plan_monitor.domain.market_linkage_models import MarketLinkedRule

    if isinstance(rule, MarketLinkedRule) and (
        linkage is None or linkage.rule_id != rule.rule_id
        or linkage.calculation.authorized_quantity <= 0
    ):
        return None
    daily = rule.confirmation.kind == "OFFICIAL_DAILY_CLOSE"
    staged = isinstance(rule.independent_signal, OncePerRule | AfterRuleCompleted)
    if staged and any(s["rule_id"] == rule.rule_id for s in previous):
        return None
    if isinstance(rule.independent_signal, AfterRuleCompleted) and not any(
        s["rule_id"] == rule.independent_signal.prior_rule_id
        and s["state"] == "SIMULATED"
        and s["simulated_qty"] == s["planned_qty"]
        for s in previous
    ):
        return None
    if daily and series is None or not daily and (target is None or not bars):
        return None
    day = series.bars[-1].trade_date if daily else target.date()
    if isinstance(rule, MarketLinkedRule):
        from trade_plan_monitor.decision.market_linkage import MarketLinkageDecision
        from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

        linkage = MarketLinkageDecision.model_validate_json(linkage.model_dump_json())
        if (linkage.content_hash != daily_plan_content_sha256(plan)
                or linkage.decision_session != day
                or linkage.calculation.base_quantity != rule.quantity_policy.base_quantity):
            return None
    if isinstance(rule.independent_signal, AfterRuleCompleted):
        predecessor = next(
            s
            for s in previous
            if s["rule_id"] == rule.independent_signal.prior_rule_id
            and s["state"] == "SIMULATED"
            and s["simulated_qty"] == s["planned_qty"]
        )
        if not predecessor.get("execution_date") or str(day) < predecessor["execution_date"]:
            return None
        # Intraday fills need a known completion timestamp; never backfill an
        # earlier bar merely because the predecessor is filled at evaluation time.
        if not daily and str(day) == predecessor["execution_date"]:
            completed = predecessor.get("simulated_at")
            if completed is None or datetime.fromisoformat(completed) >= target:
                return None
    if daily and requires_minutes(rule.condition) and (target is None or target.date() != day):
        return None
    if not daily and requires_daily(rule.condition):
        last_official_day = next(
            (
                session
                for session in reversed(session_dates)
                if datetime.combine(session, time(15), target.tzinfo) <= target
            ),
            None,
        )
        if series is None or series.bars[-1].trade_date != last_official_day:
            return None
    if rule.validity.mode == "DATE_RANGE" and not (
        rule.validity.start_date <= day <= rule.validity.end_date
    ):
        return None
    evidence = evaluate_unified_condition(
        rule.condition,
        series,
        facts=facts,
        macd_min_observations=500
        if plan.monitoring is None
        else plan.monitoring.macd_min_observations,
        bars=bars,
        target=target,
        trading_calendar=trading_calendar,
    )
    if evidence.outcome != "SATISFIED":
        return None
    if rule.zone is not None:
        zone = getattr(plan.levels, "low_buy" if rule.zone == "LOW_BUY" else "pressure")
        price = series.bars[-1].close if daily else bars[-1].close_fen
        if not zone.contains(price):
            return None
    old = () if staged else tuple(s for s in previous if s["side"] == rule.side)
    independent = None
    if old:
        prior = old[-1]
        if prior["state"] in {"CONFIRMED", "READY"}:
            return None
        if isinstance(rule.independent_signal, UnifiedResetPolicy):
            reset = prior.get("reset_trade_date")
            if reset is None or not prior["confirmed_trade_date"] < reset < str(day):
                return None
            independent = "reset:" + reset
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
    execution = next_session(day, session_dates) if daily else day
    packed = [evidence.model_dump(mode="json")]
    identity = daily_hash(
        "condition-signal-occurrence-v1",
        {
            "lineage": plan.plan_id,
            "symbol": plan.symbol,
            "rule_id": rule.rule_id,
            "side": rule.side,
            "independent": independent or "FIRST",
        },
    )
    return {
        **({"occurrence_mode": rule.independent_signal.mode} if staged else {}),
        "signal_id": identity,
        "rule_id": rule.rule_id,
        "side": rule.side,
        "bucket": rule.bucket,
        "lineage": plan.plan_id,
        "state": "CONFIRMED",
        "planned_qty": (linkage.calculation.candidate_quantity
                        if isinstance(rule, MarketLinkedRule) else rule.quantity),
        **({"market_linkage": linkage.model_dump(mode="json")}
           if isinstance(rule, MarketLinkedRule) else {}),
        "simulated_qty": 0,
        "confirmed_trade_date": str(day),
        "execution_date": None if execution is None else str(execution),
        "evidence_fingerprint": daily_hash("condition-signal-evidence-v1", packed),
        "evidence": packed,
        "plan_version_id": plan_version_id,
        "review_id": review_id,
        "basis_id": series.basis_id if series is not None else "minute-ta-v1",
        "executable_qty": 0,
        "blockers": [],
        "confirmation_kind": rule.confirmation.kind,
        "confirmed_at": None if daily else target.isoformat(),
        "execution_window": rule.execution_window,
    }


def check_execution(
    plan, signal, *, inventory, quote_fen, evaluated_at, tradable, risk_blocked, risk_known
):
    remaining = signal["planned_qty"] - signal["simulated_qty"]
    if remaining not in {0, signal["planned_qty"]}:
        raise ValueError("signal consumption must be atomic")
    signal = expire_daily_signal(signal, evaluated_at)
    state, blockers = signal["state"], []
    clock = evaluated_at.time().replace(tzinfo=None)
    if state in {"SIMULATED", "INVALIDATED", "EXPIRED"}:
        blockers.append(state)
    if str(evaluated_at.date()) != signal["execution_date"] or not (
        time(9, 30) <= clock < time(11, 30) or time(13) <= clock < time(15)
    ):
        blockers.append("OUTSIDE_EXECUTION_SESSION")
    if not tradable or quote_fen is None:
        blockers.append("TRADABILITY_OR_QUOTE_UNVERIFIED")
    rule = next((r for r in plan.ordinary_rules if r.rule_id == signal["rule_id"]), None)
    if rule is None:
        blockers.append("SIGNAL_RULE_REPLACED")
    elif rule.zone is not None and (
        quote_fen is None
        or not getattr(plan.levels, "low_buy" if rule.zone == "LOW_BUY" else "pressure").contains(
            quote_fen
        )
    ):
        blockers.append("OUTSIDE_PRICE_ZONE")
    if risk_blocked:
        blockers.append("HIGHER_PRIORITY_RISK")
    if signal.get("risk_invalidated"):
        blockers.append("CONFIRMED_RISK_INVALIDATED_ORDINARY_SIGNAL")
        if state != "SIMULATED":
            state = "INVALIDATED"
    if not risk_known:
        blockers.append("RISK_INPUT_UNKNOWN")
    if not inventory["known"]:
        blockers.append("POSITION_UNKNOWN")
    elif signal["side"] == "BUY":
        if plan.position.max_qty - inventory["total_qty"] < remaining:
            blockers.append("MAX_QUANTITY_CAPACITY")
    elif inventory.get("sellable_tactical") is None:
        blockers.append("SELLABLE_QUANTITY_UNKNOWN")
    elif min(inventory["tactical_qty"], inventory["sellable_tactical"]) < remaining:
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
