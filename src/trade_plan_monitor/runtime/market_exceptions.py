"""Owned bridge from reviewed daily evidence to durable human-only authority."""

from datetime import datetime, time

from sqlalchemy import select

from trade_plan_monitor.decision.daily_lifecycle import next_session
from trade_plan_monitor.decision.market_exception_decision import (
    MarketExceptionDecision,
    grant_exception,
)
from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.risk_scope import blocks_new_entry
from trade_plan_monitor.domain.unified_plan_models import UnifiedResetPolicy
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.market_exception_models import (
    ExceptionBinding,
    ExceptionCandidate,
    ExceptionEvent,
    ExceptionSignalSeed,
    new_candidate,
)
from trade_plan_monitor.state.market_exception_repository import ExceptionRepository
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityContext,
    ExceptionAuthorityError,
    decide_exception,
    terminate_exception,
)
from trade_plan_monitor.state.market_linkage_authority import linked_index_current
from trade_plan_monitor.state.models import TradingCalendar


def candidate_shadow(candidate):
    """No actionable signal is stored before approval; this only fences recurrence."""
    b, seed = candidate.binding, candidate.signal_seed
    return dict(
        signal_id=b.occurrence_id, rule_id=b.rule_id, side="BUY", lineage=b.lineage,
        confirmed_trade_date=str(b.decision_session), execution_date=str(b.execution_date),
        state="CONFIRMED" if candidate.state in {"PENDING", "APPROVED"} else "INVALIDATED",
        planned_qty=0, simulated_qty=0,
        **({"occurrence_mode": seed.occurrence_mode} if seed and seed.occurrence_mode else {}))


def synchronize_candidates(work, plan, active, review, linkages, *, now, previous,
                           completed_series=(), facts=(), risks=(), source_missing=False):
    repo = ExceptionRepository(work.daily)
    shadows = []
    for row in repo.list(plan.symbol):
        candidate = ExceptionCandidate.model_validate(row["payload"])
        b = candidate.binding
        decision = linkages.get(b.rule_id)
        terminal = None
        if now >= b.expires_at:
            terminal = "EXPIRED"
        elif (not isinstance(plan, MarketExceptionTradePlan)
                or active.plan_version_id != b.plan_version_id
                or active.revision != b.activation_revision
                or review["review_id"] != b.review_id or review["content_hash"] != b.content_hash
                or not source_missing and (
                    decision is None or decision.consumed_hash != b.consumed_hash
                    or decision.calculation.route != b.route)):
            terminal = "INVALIDATED"
        if terminal:
            row = terminate_exception(work.daily, row["id"], state=terminal,
                reason="Original window or consumed authority changed", now=now)
            candidate = ExceptionCandidate.model_validate(row["payload"])
        if any(signal["signal_id"] == b.occurrence_id for signal in previous):
            continue
        shadow = candidate_shadow(candidate)
        rule = next((r for r in plan.ordinary_rules if r.rule_id == b.rule_id), None)
        if rule is not None and isinstance(rule.independent_signal, UnifiedResetPolicy):
            for series in completed_series:
                day = series.bars[-1].trade_date
                if any(r["status"] in {"CONFIRMED", "FULFILLED"}
                       and blocks_new_entry({**r, "status": "CONFIRMED"}, now.date())
                       and r.get("confirmed_trade_date", "") >= str(day) for r in risks):
                    continue
                if day > b.decision_session and evaluate_unified_condition(
                        rule.independent_signal.reset_condition, series, facts=facts,
                        macd_min_observations=(500 if plan.monitoring is None
                            else plan.monitoring.macd_min_observations)).outcome == "SATISFIED":
                    shadow["reset_trade_date"] = str(day)
        shadows.append(shadow)
    return (*previous, *shadows)


def exception_calendar_current(daily, binding):
    """The frozen next-session window must still match the owned exchange calendar."""
    exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[binding.symbol[-2:]]
    decision = daily.session.get(TradingCalendar, (exchange, binding.decision_session))
    next_day = daily.session.scalars(select(TradingCalendar).where(
        TradingCalendar.exchange == exchange,
        TradingCalendar.cal_date > binding.decision_session,
        TradingCalendar.is_open.is_(True),
    ).order_by(TradingCalendar.cal_date).limit(1)).first()
    return (decision is not None and decision.is_open and next_day is not None
        and next_day.cal_date == binding.execution_date
        and next_day.previous_trade_date == binding.decision_session)


def record_candidate(work, plan, active, review, decision, seed, *, sessions, now):
    if not isinstance(decision, MarketExceptionDecision) or decision.selection.blocker is not None:
        return None
    day = decision.decision_session
    execution = next_session(day, sessions)
    if execution is None or decision.quantity_rules is None:
        return None
    expires = datetime.combine(execution, time(15), now.tzinfo)
    if now >= expires:
        return None
    binding = ExceptionBinding(
        occurrence_id=seed["signal_id"], symbol=plan.symbol, lineage=plan.plan_id,
        rule_id=decision.rule_id, plan_version_id=active.plan_version_id,
        review_id=review["review_id"], activation_revision=active.revision,
        content_hash=review["content_hash"], route=decision.calculation.route,
        decision_session=day, evidence_cutoff=decision.evidence_cutoff,
        execution_date=execution, expires_at=expires, evidence_hash=decision.evidence_hash,
        consumed_hash=decision.consumed_hash, grid_hash=decision.quantity_rules.content_hash,
        base_quantity=decision.calculation.base_quantity, minimum=decision.quantity_rules.minimum,
        increment=decision.quantity_rules.increment)
    candidate = new_candidate(binding, now, signal_seed=ExceptionSignalSeed(
        signal_id=seed["signal_id"], basis_id=seed["basis_id"],
        evidence_fingerprint=seed["evidence_fingerprint"], evidence=seed["evidence"],
        **({"pretrade": seed["pretrade"]} if "pretrade" in seed else {}),
        occurrence_mode=seed.get("occurrence_mode")))
    return ExceptionRepository(work.daily).create(candidate)


def current_exception_authority(work, candidate, now):
    """Resolve every authority input locally, with no client-supplied market facts."""
    b = candidate.binding
    active = work.plans.get_active(b.symbol)
    details = work.plans.get_version_details(b.plan_version_id)
    review = work.daily.get("review-" + b.plan_version_id)
    head = work.daily.get("evaluation-head-" + b.symbol)
    if (active is None or details is None or review is None or head is None
            or active.plan_version_id != b.plan_version_id
            or active.revision != b.activation_revision
            or not review["payload"].get("confirmed")
            or review["payload"].get("review_id") != b.review_id
            or details.content_hash != b.content_hash or details.daily_issues):
        raise ExceptionAuthorityError("EXCEPTION_CURRENT_REVIEW_REQUIRED")
    plan = load_plan_json(details.payload_json)
    state = head["payload"]
    if not isinstance(plan, MarketExceptionTradePlan) or candidate.signal_seed is None:
        raise ExceptionAuthorityError("EXCEPTION_CURRENT_PLAN_REQUIRED")
    if not exception_calendar_current(work.daily, b):
        raise ExceptionAuthorityError("EXCEPTION_CALENDAR_CHANGED_OR_UNKNOWN")
    if (state["plan_version_id"] != b.plan_version_id or state["review_id"] != b.review_id
            or state["activation_revision"] != b.activation_revision
            or datetime.fromisoformat(state["evaluated_at"]) > now):
        raise ExceptionAuthorityError("EXCEPTION_CURRENT_EVALUATION_REQUIRED")
    decision = next((MarketExceptionDecision.model_validate(item)
        for item in state.get("market_linkage", ()) if item["rule_id"] == b.rule_id), None)
    if (decision is None or decision.consumed_hash != b.consumed_hash
            or decision.calculation.route != b.route or decision.selection.blocker is not None
            or not linked_index_current(work.daily.session, state, now)):
        raise ExceptionAuthorityError("EXCEPTION_EVIDENCE_CHANGED")
    accounting = DailyAccounting(work.daily)
    inventory = accounting.snapshot(b.symbol, now.date())
    if not accounting.evaluation_current(state, plan_version_id=b.plan_version_id,
            content_hash=b.content_hash, inventory=inventory, now=now, require_daily_data=False):
        raise ExceptionAuthorityError("EXCEPTION_CURRENT_FACTS_REQUIRED")
    risks = tuple(row["payload"] for row in work.daily.list(symbol=b.symbol, kind="RISK"))
    blockers = list(state.get("data_blockers", ()))
    # Missing a live execution quote before the next session does not erase D evidence.
    blockers = [code for code in blockers if code not in {
        "CURRENT_TRADABILITY_OR_QUOTE_MISSING", "OUTSIDE_TRADING_SESSION"}]
    if not state.get("risk_input_known"):
        blockers.append("RISK_INPUT_UNKNOWN")
    if any(blocks_new_entry(risk, now.date()) for risk in risks):
        blockers.append("HIGHER_PRIORITY_RISK")
    if now >= b.expires_at:
        blockers.append("EXCEPTION_WINDOW_EXPIRED")
    pretrade = None
    if plan.schema_version == 8:
        from trade_plan_monitor.state.p2_authority import P2EconomicsContext

        frozen = candidate.signal_seed.pretrade
        rule = next((r for r in plan.ordinary_rules if r.rule_id == b.rule_id), None)
        if (frozen is None or rule is None or frozen.content_hash != b.content_hash
                or frozen.policy != rule.pretrade_policy or frozen.sizing.q0 != b.base_quantity):
            raise ExceptionAuthorityError("P2_FROZEN_POLICY_CHANGED")
        if now.date() == b.decision_session:
            close = frozen.sizing.close_fen
            price = int(close) if close is not None and close == int(close) else None
        else:
            quote = state.get("quote")
            price = quote["price_fen"] if quote is not None else None
        pretrade = P2EconomicsContext(policy=frozen.policy.economics,
            entry_fen=price, symbol=plan.symbol, session=now.date())
    context = ExceptionAuthorityContext(
        **({"pretrade": pretrade} if pretrade is not None else {}),
        binding_hash=candidate.binding_hash, inventory_revision=inventory["revision"],
        evaluation_revision=head["revision"], authority_hash=daily_hash(
            "exception-current-authority-v1", {"consumed_hash": decision.consumed_hash,
                "fact_revisions": state["fact_revisions"], "risks": risks}),
        capacity=(plan.position.max_qty-inventory["total_qty"] if inventory["known"] else None),
        blockers=tuple(blockers))
    return context


def apply_exception_decision(work, command, *, now):
    result = decide_exception(work.daily, command,
        current=lambda candidate: current_exception_authority(work, candidate, now), now=now)
    candidate = result.candidate
    if candidate.state != "APPROVED":
        return result
    # A replay of an earlier approval never recreates a revoked/consumed signal.
    live = ExceptionCandidate.model_validate(
        ExceptionRepository(work.daily).get(candidate.candidate_id)["payload"])
    if live.state != "APPROVED" or work.daily.get(candidate.binding.occurrence_id) is not None:
        return result
    context = current_exception_authority(work, candidate, now)
    head = work.daily.get("evaluation-head-" + candidate.binding.symbol)["payload"]
    decision = next(MarketExceptionDecision.model_validate(item)
        for item in head["market_linkage"] if item["rule_id"] == candidate.binding.rule_id)
    granted = grant_exception(decision, candidate, result.event, capacity=context.capacity)
    seed, b = candidate.signal_seed, candidate.binding
    signal = dict(
        **({"pretrade": seed.pretrade.model_dump(mode="json")}
           if seed.pretrade is not None else {}),
        signal_id=b.occurrence_id, rule_id=b.rule_id, side="BUY", bucket="TACTICAL",
        lineage=b.lineage, state="CONFIRMED", planned_qty=candidate.frozen_quantity,
        simulated_qty=0, executable_qty=0, blockers=[],
        confirmed_trade_date=str(b.decision_session),
        execution_date=str(b.execution_date), evidence_fingerprint=seed.evidence_fingerprint,
        evidence=[item.model_dump(mode="json") for item in seed.evidence],
        plan_version_id=b.plan_version_id, review_id=b.review_id, basis_id=seed.basis_id,
        confirmation_kind="OFFICIAL_DAILY_CLOSE", confirmed_at=None,
        execution_window="NEXT_EXCHANGE_SESSION_ONLY",
        market_linkage=granted.model_dump(mode="json"))
    if seed.occurrence_mode is not None:
        signal["occurrence_mode"] = seed.occurrence_mode
    work.daily.save(b.occurrence_id, kind="SIGNAL", symbol=b.symbol, lineage=b.lineage,
                    payload=signal, expected_revision=0)
    return result


def exception_signal_current(daily, signal, now):
    evidence = signal.get("market_linkage") or {}
    approval = evidence.get("calculation", {}).get("approval")
    if approval is None:
        return not (evidence.get("calculation", {}).get("route") is not None)
    event = ExceptionEvent.model_validate(approval)
    row = ExceptionRepository(daily).get(event.candidate_id)
    if row is None:
        return False
    candidate = ExceptionCandidate.model_validate(row["payload"])
    original = daily.get(event.event_id)
    return (candidate.state == "APPROVED" and candidate.approval_id == event.event_id
        and original is not None and original["payload"] == event.model_dump(mode="json")
        and exception_calendar_current(daily, candidate.binding)
        and candidate.binding.occurrence_id == signal["signal_id"]
        and candidate.frozen_quantity == signal["planned_qty"]
        and candidate.binding.plan_version_id == signal["plan_version_id"]
        and candidate.binding.review_id == signal["review_id"]
        and candidate.binding.consumed_hash == evidence["consumed_hash"]
        and candidate.created_at <= now < candidate.binding.expires_at)


def exception_reminder_current(daily, event, now):
    from datetime import timedelta

    row = ExceptionRepository(daily).get(event.cause_id)
    head = daily.get("evaluation-head-" + event.symbol)
    if row is None or head is None:
        return False
    candidate = ExceptionCandidate.model_validate(row["payload"])
    b = candidate.binding
    decisions = head["payload"].get("market_linkage", ())
    return (candidate.state == "PENDING" and b.plan_version_id == event.plan_version_id
        and b.review_id == event.review_id and b.rule_id == event.rule_id
        and b.activation_revision == event.activation_revision
        and str(b.decision_session) == str(event.confirmed_trade_date)
        and now < b.expires_at
        and event.evaluated_at <= now < event.evaluated_at+timedelta(minutes=5)
        and linked_index_current(daily.session, head["payload"], now)
        and head["payload"].get("risk_input_known") is True
        and not any(blocks_new_entry(row["payload"], now.date()) for row in daily.list(
            symbol=event.symbol, kind="RISK"))
        and DailyAccounting(daily).evaluation_current(head["payload"],
            plan_version_id=b.plan_version_id, content_hash=b.content_hash,
            inventory=DailyAccounting(daily).snapshot(b.symbol, now.date()), now=now,
            require_daily_data=False)
        and any(item["rule_id"] == b.rule_id and item["consumed_hash"] == b.consumed_hash
                and item["selection"]["blocker"] is None for item in decisions))
