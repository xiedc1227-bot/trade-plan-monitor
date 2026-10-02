"""Production daily transaction participant and current send-time authority."""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from pydantic import Field

from trade_plan_monitor.decision.daily_conditions import evaluate_daily_condition
from trade_plan_monitor.decision.daily_lifecycle import (
    check_daily_execution,
    confirm_daily_signal,
    expire_daily_signal,
    next_session,
)
from trade_plan_monitor.decision.daily_risk import advance_daily_risks, risk_execution
from trade_plan_monitor.domain.daily_plan_models import (
    DailyEnabledRule,
    DailyResetPolicy,
    DailyTradePlan,
    DailyValue,
)
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote, DailySeries
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.notifications.daily_models import DailyAlertPayload, daily_alert_key
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_repository import DailyRepository, daily_hash
from trade_plan_monitor.state.models import ActivePlan, PlanVersion


class DailyRuntimeInputs(DailyValue):
    evaluated_at: ShanghaiDatetime
    official_trade_date: date | None
    series: DailySeries | None
    # The production calendar is bounded to 3000 history days plus 32 future
    # days (inclusive). Keep this proof complete for recovery/next-session timing;
    # each separate DailySeries still carries only its own <=1000-date window.
    session_dates: tuple[date, ...] = Field(max_length=3033)
    suspended_dates: tuple[date, ...] = Field(max_length=3033)
    quote: DailyExecutionQuote | None
    data_blockers: tuple[str, ...] = Field(max_length=20)


class DailyRuntimeCycleResult(DailyValue):
    symbol: str
    plan_hash: str
    activation_revision: int
    evaluated_at: ShanghaiDatetime
    duplicate: bool
    snapshot: dict
    event_ids: tuple[str, ...]


def _eligible(plan, day):
    activation = plan.activation
    if activation.mode == "MANUAL":
        return True
    if activation.mode == "TRADING_DAY":
        return activation.trading_day == day
    return activation.start_date <= day <= activation.end_date


class DailyRuntimeEvaluationService:
    def __init__(
        self,
        unit_of_work_factory,
        *,
        prepare_inputs: Callable | None = None,
        committed_event_publisher=None,
        clock=None,
        commit_admission=None,
    ):
        self._work = unit_of_work_factory
        self._prepare = prepare_inputs
        self._publish = committed_event_publisher
        self._clock = clock
        self._admission = commit_admission
        self._current_inputs = {}

    def _binding(self, work, plan):
        active = work.plans.get_active(plan.symbol)
        if active is None:
            raise ValueError("daily plan is not active")
        version = work.plans.get_version_details(active.plan_version_id)
        review = work.daily.get("review-" + active.plan_version_id)
        if version is None or version.plan_hash != plan_sha256(plan) or review is None:
            raise ValueError("daily plan/review binding changed")
        binding = review["payload"]
        if not binding.get("confirmed") or binding["content_hash"] != daily_plan_content_sha256(
            plan
        ):
            raise ValueError("daily content is not currently reviewed")
        return active, binding

    async def run_target(self, *, plan, evaluated_at, official_trade_date=None, minutes=()):
        if self._prepare is None:
            raise RuntimeError("daily provider adapter is not composed")
        with self._work() as work:
            active, binding = self._binding(work, plan)
            revision = active.revision
            unsupported = DailyAccounting(work.daily).legacy_reason(plan.symbol)
        if unsupported:
            return self.run_inputs(plan=plan, inputs=DailyRuntimeInputs(evaluated_at=evaluated_at,
                official_trade_date=None, series=None, session_dates=(), suspended_dates=(),
                quote=None, data_blockers=(unsupported,)), expected_activation_revision=revision)
        inputs = await self._prepare(plan, evaluated_at, official_trade_date, minutes)
        result = self.run_inputs(plan=plan, inputs=inputs, expected_activation_revision=revision)
        if self._publish is not None:
            for event_id in result.event_ids:
                with self._work() as work:
                    from uuid import UUID

                    event = work.events.get(UUID(event_id))
                if event is not None:
                    value = self._publish(event)
                    from inspect import isawaitable

                    if isawaitable(value):
                        await value
        return result

    async def reevaluate_version(self, version_id):
        """Human facts reuse fresh certified inputs and recheck the active binding."""
        from sqlalchemy import select

        from trade_plan_monitor.domain.plan_codec import load_plan_json
        from trade_plan_monitor.state.models import TradingCalendar

        with self._work() as work:
            details = work.plans.get_version_details(str(version_id))
            if details is None:
                return None
            active = work.plans.get_active(details.symbol)
            if active is None or active.plan_version_id != details.id:
                return None
            plan = load_plan_json(details.payload_json)
            if not isinstance(plan, DailyTradePlan):
                return None
            now = self._clock()
            if DailyAccounting(work.daily).legacy_reason(plan.symbol):
                return None
            head = work.daily.get("evaluation-head-" + plan.symbol)
            data = {} if head is None else head["payload"]
            series = (
                None
                if data.get("daily_evidence") is None
                else DailySeries.model_validate(data["daily_evidence"])
            )
            calendars = work.daily.session.scalars(
                select(TradingCalendar)
                .where(TradingCalendar.exchange == plan.market, TradingCalendar.is_open.is_(True),
                    TradingCalendar.cal_date >= now.date() - timedelta(days=3000),
                    TradingCalendar.cal_date <= now.date() + timedelta(days=32))
                .order_by(TradingCalendar.cal_date)
            ).all()
            sessions = tuple(c.cal_date for c in calendars)
            facts = tuple(
                r["payload"]
                for r in work.daily.list(symbol=plan.symbol, kind="FACT")
                if r["payload"]["plan_version_id"] == details.id
                and r["payload"]["content_hash"] == details.content_hash
            )
            suspended = tuple(
                date.fromisoformat(f["trade_date"])
                for f in facts
                if f["kind"] == "FULL_SESSION_SUSPENSION"
            )
            quote = None
            if data.get("quote") is not None:
                verified = any(
                    f["kind"] == "TRADABILITY" and f["trade_date"] == str(now.date()) for f in facts
                )
                try:
                    quote = DailyExecutionQuote.model_validate(
                        {
                            **data["quote"],
                            "evaluated_at": now,
                            "special_state_verified": verified,
                            "tradable": now.date() in sessions and now.date() not in suspended,
                        }
                    )
                except ValueError:
                    pass
        inputs = DailyRuntimeInputs(
            evaluated_at=now,
            official_trade_date=None if series is None else series.bars[-1].trade_date,
            series=series,
            session_dates=sessions,
            suspended_dates=suspended,
            quote=quote,
            data_blockers=() if quote is not None else ("CURRENT_TRADABILITY_OR_QUOTE_MISSING",),
        )
        result = self.run_inputs(
            plan=plan, inputs=inputs, expected_activation_revision=active.revision
        )
        if self._publish is not None:
            for identity in result.event_ids:
                from inspect import isawaitable
                from uuid import UUID

                with self._work() as work:
                    event = work.events.get(UUID(identity))
                if event is not None:
                    sent = self._publish(event)
                    if isawaitable(sent):
                        await sent
        return result

    def run_inputs(
        self, *, plan: DailyTradePlan, inputs: DailyRuntimeInputs, expected_activation_revision=None
    ):
        inputs = DailyRuntimeInputs.model_validate(inputs.model_dump())
        now = inputs.evaluated_at
        series = inputs.series
        if series is not None and series.cutoff > now:
            raise ValueError("daily series cutoff follows evaluation")
        quote = inputs.quote
        if quote is not None:
            quote = quote.model_copy(update={"evaluated_at": now})
            if quote.symbol != plan.symbol:
                raise ValueError("quote symbol mismatch")
        if series is not None and series.symbol != plan.symbol:
            raise ValueError("daily series symbol mismatch")
        official = inputs.official_trade_date
        with self._work() as work:
            work.daily.lock_symbol(plan.symbol)
            active, binding = self._binding(work, plan)
            if (
                expected_activation_revision is not None
                and active.revision != expected_activation_revision
            ):
                raise ValueError("daily activation changed during acquisition")
            ordinary_eligible = _eligible(plan, now.date())
            historical_risks = (
                work.daily.list(symbol=plan.symbol, kind="RISK")
                if not DailyAccounting(work.daily).legacy_reason(plan.symbol)
                else ()
            )
            maintain_risk = any(r["payload"]["status"] in {"PENDING", "CONFIRMED", "FULFILLED"}
                or r["payload"].get("reassessment_id") for r in historical_risks)
            if (not ordinary_eligible and not maintain_risk) or (
                self._admission is not None and not self._admission()
            ):
                raise ValueError("daily runtime commit admission is closed")
            accounting = DailyAccounting(work.daily)
            if accounting.legacy_reason(plan.symbol):
                return DailyRuntimeCycleResult(
                    symbol=plan.symbol,
                    plan_hash=plan_sha256(plan),
                    activation_revision=active.revision,
                    evaluated_at=now,
                    duplicate=False,
                    snapshot={
                        "status": "UNSUPPORTED",
                        "reason": "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED",
                        "risks": list(accounting.obsolete_risks(plan.symbol)),
                    },
                    event_ids=(),
                )
            inventory = accounting.snapshot(plan.symbol, now.date())
            fact_rows = work.daily.list(symbol=plan.symbol, kind="FACT")
            facts = tuple(
                {**row["payload"], "id": row["id"]}
                for row in fact_rows
                if row["payload"]["plan_version_id"] == active.plan_version_id
                and row["payload"]["content_hash"] == binding["content_hash"]
                and datetime.fromisoformat(row["payload"]["verified_at"]) <= now
                and datetime.fromisoformat(row["payload"]["available_at"]) <= now
            )
            eligible_ids = {f["id"] for f in facts}
            risk_rows = work.daily.list(symbol=plan.symbol, kind="RISK")
            target = {
                "plan_hash": plan_sha256(plan),
                "activation_revision": active.revision,
                "review_id": binding["review_id"],
                "target": now.isoformat(),
                "official_trade_date": None if official is None else str(official),
                "quote": None if quote is None else quote.model_dump(mode="json"),
                "inventory_revision": inventory["revision"],
                "facts": [(r["id"], r["revision"]) for r in fact_rows if r["id"] in eligible_ids],
                "risk_revisions": [(r["id"], r["revision"]) for r in risk_rows],
                "basis": None if series is None else series.basis_id,
                "daily_evidence": None
                if series is None
                else daily_hash("daily-series-v1", series.model_dump(mode="json")),
            }
            identity = daily_hash("daily-decision-result-v1", target)
            existing = work.daily.get(identity)
            if existing is not None:
                return DailyRuntimeCycleResult(
                    symbol=plan.symbol,
                    plan_hash=plan_sha256(plan),
                    activation_revision=active.revision,
                    evaluated_at=now,
                    duplicate=True,
                    snapshot=existing["payload"],
                    event_ids=(),
                )
            previous_risks = tuple(r["payload"] for r in risk_rows)
            effective_start = active.activated_at.date()
            completed_series = (
                tuple(
                    series.model_copy(update={"bars": series.bars[: index + 1]})
                    for index, bar in enumerate(series.bars)
                    if now >= datetime.combine(bar.trade_date, time(15), now.tzinfo)
                )
                if series is not None
                else ()
            )
            risks = previous_risks
            for completed in completed_series or (None,):
                risks = advance_daily_risks(
                    plan,
                    previous=risks,
                    close_date=None if completed is None else completed.bars[-1].trade_date,
                    close_fen=None if completed is None else completed.bars[-1].close,
                    basis_id=None if completed is None else completed.basis_id,
                    session_dates=inputs.session_dates,
                    suspended_dates=inputs.suspended_dates,
                    facts=facts,
                    effective_start_date=effective_start,
                    allow_new_causes=ordinary_eligible,
                )
            fulfilled = []
            for risk in risks:
                if (
                    risk["status"] == "CONFIRMED"
                    and inventory["known"]
                    and inventory["tactical_qty"] <= risk["target_tactical_qty"]
                    and (
                        not risk["involves_core"]
                        or inventory["core_qty"] <= risk["target_core_qty"]
                    )
                ):
                    risk = {
                        **risk,
                        "status": "FULFILLED",
                        "fulfilled_at": now.isoformat(),
                        "cause_cutover_date": str(now.date()),
                        "cause_cutover_at": now.isoformat(),
                        "consumed_evidence_ids": sorted(
                            set(risk.get("consumed_evidence_ids", ())) | set(risk["evidence_ids"])
                        ),
                    }
                fulfilled.append(risk)
            risks = tuple(fulfilled)
            completed_series = tuple(
                s for s in completed_series if s.bars[-1].trade_date >= effective_start
            )
            saved_risks = []
            for risk in risks:
                risk_id = daily_hash(
                    "daily-risk-obligation-v1", {"symbol": plan.symbol, "kind": risk["kind"]}
                )
                old = work.daily.get(risk_id)
                risk = {**risk, "risk_id": risk_id}
                if old is None or old["payload"] != risk:
                    old = work.daily.save(
                        risk_id,
                        kind="RISK",
                        symbol=plan.symbol,
                        lineage=plan.symbol,
                        payload=risk,
                        expected_revision=0 if old is None else old["revision"],
                    )
                saved_risks.append({**risk, "revision": old["revision"]})
            risk_blocked = any(
                r["status"] in {"PENDING", "OBSERVATION", "CONFIRMED"} for r in risks
            )
            risk_known = series is not None
            # Plan IDs are display identities, never authority to reuse a consumed
            # stock/rule occurrence. Replacement needs independently verified evidence.
            signal_rows = work.daily.current_signals(symbol=plan.symbol)
            for row in signal_rows:
                signal = row["payload"]
                if signal["execution_date"] is None:
                    next_day = next_session(
                        date.fromisoformat(signal["confirmed_trade_date"]), inputs.session_dates
                    )
                    if next_day is not None:
                        signal = {**signal, "execution_date": str(next_day)}
                signal = expire_daily_signal(signal, now)
                if any(
                    r["status"] in {"CONFIRMED", "FULFILLED"}
                    and r.get("confirmed_trade_date", "") >= signal["confirmed_trade_date"]
                    for r in risks
                ):
                    signal = {
                        **signal,
                        "risk_invalidated": True,
                        "executable_qty": 0,
                        "state": signal["state"]
                        if signal["state"] in {"SIMULATED"}
                        else "INVALIDATED",
                    }
                rule = next(
                    (
                        r
                        for r in plan.ordinary_rules
                        if isinstance(r, DailyEnabledRule) and r.side == signal["side"]
                    ),
                    None,
                )
                if rule is not None and isinstance(rule.independent_signal, DailyResetPolicy):
                    for completed in completed_series:
                        if any(
                            r["status"] in {"CONFIRMED", "FULFILLED"}
                            and r.get("confirmed_trade_date", "")
                            >= str(completed.bars[-1].trade_date)
                            for r in risks
                        ):
                            continue
                        reset_day = str(completed.bars[-1].trade_date)
                        if (
                            signal["confirmed_trade_date"] < reset_day
                            and evaluate_daily_condition(
                                rule.independent_signal.reset_condition,
                                completed,
                                facts=facts,
                                macd_min_observations=plan.monitoring.macd_min_observations,
                            ).outcome
                            == "SATISFIED"
                        ):
                            signal = {**signal, "reset_trade_date": reset_day}
                if signal != row["payload"]:
                    work.daily.save(
                        row["id"],
                        kind="SIGNAL",
                        symbol=plan.symbol,
                        lineage=row["lineage"],
                        payload=signal,
                        expected_revision=row["revision"],
                    )
            signal_rows = work.daily.current_signals(symbol=plan.symbol)
            previous = tuple(r["payload"] for r in signal_rows)
            if completed_series and not risk_blocked and ordinary_eligible:
                for rule in plan.ordinary_rules:
                    if not isinstance(rule, DailyEnabledRule):
                        continue
                    for completed in completed_series:
                        if any(
                            r["status"] in {"CONFIRMED", "FULFILLED"}
                            and r.get("confirmed_trade_date", "")
                            >= str(completed.bars[-1].trade_date)
                            for r in risks
                        ):
                            continue
                        signal = confirm_daily_signal(
                            plan,
                            rule,
                            series=completed,
                            facts=facts,
                            previous=previous,
                            session_dates=inputs.session_dates,
                            plan_version_id=active.plan_version_id,
                            review_id=binding["review_id"],
                        )
                        if signal is not None and work.daily.get(signal["signal_id"]) is None:
                            work.daily.save(
                                signal["signal_id"],
                                kind="SIGNAL",
                                symbol=plan.symbol,
                                lineage=plan.plan_id,
                                payload=signal,
                                expected_revision=0,
                            )
                            previous = (*previous, expire_daily_signal(signal, now))
            signal_rows = work.daily.current_signals(symbol=plan.symbol)
            market_clock = now.time().replace(tzinfo=None)
            in_session = now.date() in inputs.session_dates and (
                time(9, 30) <= market_clock < time(11, 30) or time(13) <= market_clock < time(15)
            )
            tradable = (
                in_session
                and quote is not None
                and quote.tradable
                and quote.special_state_verified
                and quote.liquidity_available
            )
            signals = []
            for row in signal_rows:
                signal = row["payload"]
                if signal["execution_date"] is None:
                    next_day = next_session(
                        date.fromisoformat(signal["confirmed_trade_date"]), inputs.session_dates
                    )
                    if next_day is not None:
                        signal = {**signal, "execution_date": str(next_day)}
                if signal.get("plan_version_id") != active.plan_version_id:
                    signals.append(
                        {
                            **signal,
                            "executable_qty": 0,
                                "blockers": ["SUCCESSOR_EQUIVALENCE_REVIEW_REQUIRED"],
                            "revision": row["revision"],
                        }
                    )
                    continue
                if signal["state"] != "SIMULATED" and any(
                    f.get("kind") == "SIGNAL_INVALIDATION" and f.get("signal_id") == row["id"]
                    for f in facts
                ):
                    signal = {**signal, "state": "INVALIDATED"}
                if not ordinary_eligible and signal["state"] != "SIMULATED":
                    signal = {**signal, "state": "INVALIDATED", "executable_qty": 0,
                        "blockers": ["PLAN_ACTIVATION_WINDOW_ENDED"]}
                checked = check_daily_execution(
                    plan,
                    signal,
                    inventory=inventory,
                    quote_fen=None if quote is None else quote.price_fen,
                    evaluated_at=now,
                    tradable=tradable,
                    risk_blocked=risk_blocked,
                    risk_known=risk_known,
                )
                if checked != row["payload"]:
                    row = work.daily.save(
                        row["id"],
                        kind="SIGNAL",
                        symbol=plan.symbol,
                        lineage=plan.plan_id,
                        payload=checked,
                        expected_revision=row["revision"],
                    )
                signals.append({**checked, "revision": row["revision"]})
            ready = [s for s in signals if s["executable_qty"] > 0]
            if len({s["side"] for s in ready}) > 1:
                for s in signals:
                    s["executable_qty"] = 0
                    s["blockers"] = [*s["blockers"], "ORDINARY_CONFLICT_BLOCK_BOTH"]
            risk_action = risk_execution(
                saved_risks, plan=plan, inventory=inventory, evaluated_at=now, tradable=tradable
            )
            snapshot = {
                "symbol": plan.symbol,
                "plan_version_id": active.plan_version_id,
                "plan_hash": plan_sha256(plan),
                "content_hash": binding["content_hash"],
                "review_id": binding["review_id"],
                "activation_revision": active.revision,
                "evaluated_at": now.isoformat(),
                "official_trade_date": str(official) if official else None,
                "inventory": inventory,
                "fact_revisions": [{"id": i, "revision": r} for i, r in target["facts"]],
                "signals": signals,
                "risks": saved_risks,
                "risk_action": risk_action,
                "data_blockers": list(inputs.data_blockers),
                "daily_evidence": None if series is None else series.model_dump(mode="json"),
                "quote": None if quote is None else quote.model_dump(mode="json"),
                "next_action": "REVIEW_RISK_EXIT"
                if risk_action["status"] == "RISK_EXIT"
                else "CONFIRM_SIMULATED_TRADE"
                if any(s["executable_qty"] for s in signals)
                else "WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION",
            }
            events = []
            for signal in signals:
                if signal["executable_qty"]:
                    events.append(
                        self._enqueue(
                            work,
                            plan,
                            active,
                            binding,
                            now,
                            cause_id=signal["signal_id"],
                            side=signal["side"],
                            quantity=signal["executable_qty"],
                            simulated=signal["simulated_qty"],
                            confirmed=signal["confirmed_trade_date"],
                            execution=signal["execution_date"],
                            scope=None,
                            evidence=signal["evidence"],
                        )
                    )
            if risk_action["status"] == "RISK_EXIT":
                confirmed = next(r for r in saved_risks if r["kind"] == risk_action["branch"])
                quantities = [risk_action["core_qty"], risk_action["tactical_qty"]]
                quantity = None if any(q is None for q in quantities) else sum(quantities)
                if quantity is None or quantity > 0:
                    events.append(
                        self._enqueue(
                            work,
                            plan,
                            active,
                            binding,
                            now,
                            cause_id=confirmed["risk_id"],
                            side="RISK_EXIT",
                            quantity=quantity,
                            simulated=0,
                            confirmed=confirmed.get("confirmed_trade_date"),
                            execution=confirmed["earliest_execution_date"],
                            scope=risk_action,
                            evidence=[],
                        )
                    )
            work.daily.save(
                identity,
                kind="EVALUATION",
                symbol=plan.symbol,
                lineage=plan.plan_id,
                payload=snapshot,
                expected_revision=0,
            )
            head = work.daily.get("evaluation-head-" + plan.symbol)
            work.daily.save(
                "evaluation-head-" + plan.symbol,
                kind="EVALUATION",
                symbol=plan.symbol,
                lineage=plan.symbol,
                payload=snapshot,
                expected_revision=0 if head is None else head["revision"],
            )
            work.commit()
        self._current_inputs[plan.symbol] = inputs
        return DailyRuntimeCycleResult(
            symbol=plan.symbol,
            plan_hash=plan_sha256(plan),
            activation_revision=active.revision,
            evaluated_at=now,
            duplicate=False,
            snapshot=snapshot,
            event_ids=tuple(event for event in events if event is not None),
        )

    def _enqueue(
        self,
        work,
        plan,
        active,
        binding,
        now,
        *,
        cause_id,
        side,
        quantity,
        simulated,
        confirmed,
        execution,
        scope,
        evidence,
    ):
        key = daily_alert_key(
            cause_id, plan_sha256(plan), side, simulated, quantity, scope, confirmed
        )
        if work.alerts.has_dedup_key(key):
            return None
        event = work.alerts.enqueue_daily(
            DailyAlertPayload(
                event_id=uuid4(),
                dedup_key=key,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                plan_hash=plan_sha256(plan),
                plan_version_id=active.plan_version_id,
                review_id=binding["review_id"],
                activation_revision=active.revision,
                symbol=plan.symbol,
                name=plan.name,
                signal_type=side,
                severity="RISK" if side == "RISK_EXIT" else "ACTION",
                trading_date=now.date(),
                evaluated_at=now,
                cause_id=cause_id,
                confirmed_trade_date=confirmed,
                execution_date=execution,
                quantity=quantity,
                simulated_qty=simulated,
                risk_scope=scope,
                evidence=tuple(evidence),
                next_step="REVIEW_RISK_EXIT"
                if side == "RISK_EXIT"
                else "CONFIRM_SIMULATED_TRADE",
            )
        )
        return str(event.event_id)


def daily_delivery_allowed(session, event, now):
    """Recheck actual active binding, latest quantity, window and risk just before send."""
    active = session.get(ActivePlan, event.symbol)
    if (
        active is None
        or active.plan_version_id != event.plan_version_id
        or active.revision != event.activation_revision
    ):
        return False
    version = session.get(PlanVersion, active.plan_version_id)
    if version is None or version.plan_hash != event.plan_hash:
        return False
    repo = DailyRepository(session, clock=lambda: now, id_factory=lambda: str(uuid4()))
    if DailyAccounting(repo).legacy_reason(event.symbol):
        return False
    review = repo.get("review-" + event.plan_version_id)
    if (
        review is None
        or not review["payload"].get("confirmed")
        or review["payload"].get("review_id") != event.review_id
    ):
        return False
    if event.signal_type == "RISK_EXIT":
        risk = repo.get(event.cause_id)
        if (
            risk is None
            or risk["payload"]["status"] != "CONFIRMED"
            or risk["payload"].get("confirmed_trade_date") != str(event.confirmed_trade_date)
            or event.created_at > now
        ):
            return False
        head = repo.get("evaluation-head-" + event.symbol)
        if head is None or head["payload"]["plan_version_id"] != event.plan_version_id:
            return False
        quote_data = head["payload"].get("quote")
        try:
            quote = (
                None
                if quote_data is None
                else DailyExecutionQuote.model_validate({**quote_data, "evaluated_at": now})
            )
        except ValueError:
            return False
        market_clock = now.time().replace(tzinfo=None)
        in_session = time(9, 30) <= market_clock < time(11, 30) or time(13) <= market_clock < time(
            15
        )
        tradable = (
            in_session
            and quote is not None
            and quote.tradable
            and quote.special_state_verified
            and quote.liquidity_available
        )
        accounting = DailyAccounting(repo)
        inventory = accounting.snapshot(event.symbol, now.date())
        if not accounting.evaluation_current(head["payload"], plan_version_id=event.plan_version_id,
            content_hash=review["payload"]["content_hash"], inventory=inventory, now=now,
            require_daily_data=False):
            return False
        risks = tuple(
            {**r["payload"], "revision": r["revision"]}
            for r in repo.list(symbol=event.symbol, kind="RISK")
        )
        from trade_plan_monitor.domain.plan_codec import load_plan_json

        current = risk_execution(
            risks,
            plan=load_plan_json(version.payload_json),
            inventory=inventory,
            evaluated_at=now,
            tradable=tradable,
        )
        return (
            current == event.risk_scope
            and (event.quantity is None or event.quantity > 0)
            and (event.evaluated_at <= now < event.evaluated_at + timedelta(minutes=5))
        )
    signal = repo.get(event.cause_id)
    if signal is None or signal["payload"]["state"] not in {"READY"}:
        return False
    s = signal["payload"]
    if s["simulated_qty"] != event.simulated_qty or s.get("executable_qty") != event.quantity:
        return False
    if str(now.date()) != s["execution_date"] or not time(9, 30) <= now.time().replace(
        tzinfo=None
    ) < time(15):
        return False
    if time(11, 30) <= now.time().replace(tzinfo=None) < time(13):
        return False
    risks = repo.list(symbol=event.symbol, kind="RISK")
    if any(r["payload"]["status"] in {"PENDING", "OBSERVATION", "CONFIRMED"} for r in risks):
        return False
    inventory = DailyAccounting(repo).snapshot(event.symbol, now.date())
    if not inventory["known"]:
        return False
    head = repo.get("evaluation-head-" + event.symbol)
    if head is None or head["payload"]["plan_version_id"] != event.plan_version_id:
        return False
    if not DailyAccounting(repo).evaluation_current(head["payload"],
        plan_version_id=event.plan_version_id, content_hash=review["payload"]["content_hash"],
        inventory=inventory, now=now, require_daily_data=True):
        return False
    try:
        quote = DailyExecutionQuote.model_validate(
            {**head["payload"]["quote"], "evaluated_at": now}
        )
    except ValueError, TypeError:
        return False
    from trade_plan_monitor.domain.plan_codec import load_plan_json

    plan = load_plan_json(version.payload_json)
    checked = check_daily_execution(
        plan,
        s,
        inventory=inventory,
        quote_fen=quote.price_fen,
        evaluated_at=now,
        tradable=quote.tradable and quote.special_state_verified and quote.liquidity_available,
        risk_blocked=False,
        risk_known=head["payload"].get("daily_evidence") is not None,
    )
    return checked[
        "executable_qty"
    ] == event.quantity and event.evaluated_at <= now < event.evaluated_at + timedelta(minutes=5)
