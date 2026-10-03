"""Production daily transaction participant and current send-time authority."""

import json
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from pydantic import Field, model_validator

from trade_plan_monitor.decision.daily_conditions import evaluate_daily_condition
from trade_plan_monitor.decision.daily_lifecycle import (
    check_daily_execution,
    confirm_daily_signal,
    expire_daily_signal,
    next_session,
)
from trade_plan_monitor.decision.daily_risk import advance_daily_risks, risk_execution
from trade_plan_monitor.decision.unified_conditions import (
    evaluate_unified_condition,
    requires_daily,
    requires_minutes,
)
from trade_plan_monitor.decision.unified_lifecycle import check_execution, confirm_signal
from trade_plan_monitor.domain.daily_plan_models import (
    DailyEnabledRule,
    DailyResetPolicy,
    DailyTradePlan,
    DailyValue,
)
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.domain.unified_plan_models import (
    UnifiedResetPolicy,
    UnifiedRule,
    UnifiedTradePlan,
    condition_leaves,
)
from trade_plan_monitor.market_data.aggregation import (
    FiveMinuteBar,
    aggregate_five_minute_bar,
    expected_five_minute_ends,
)
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote, DailySeries
from trade_plan_monitor.market_data.models import MinuteBar, ShanghaiDatetime, TradingDay
from trade_plan_monitor.notifications.daily_models import DailyAlertPayload, daily_alert_key
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_repository import DailyRepository, daily_hash
from trade_plan_monitor.state.models import ActivePlan, PlanVersion
from trade_plan_monitor.state.repositories import MarketHistoryRepository


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
    minute_prefix: tuple[MinuteBar, ...] = Field(default=(), max_length=240)
    five_minute_bars: tuple[FiveMinuteBar, ...] = Field(default=(), max_length=1000)
    trading_calendar: tuple[TradingDay, ...] = Field(default=(), max_length=3033)
    minute_target: ShanghaiDatetime | None = None
    runtime_generation: str | None = None

    @model_validator(mode="after")
    def exact_minute_evidence(self):
        if self.minute_target is None:
            if self.minute_prefix or self.five_minute_bars:
                raise ValueError("minute evidence requires its exact completed target")
            return self
        if self.minute_target > self.evaluated_at:
            raise ValueError("minute target follows evaluation")
        if self.five_minute_bars:
            expected = expected_five_minute_ends(self.minute_target)
            ends = tuple(m.bar_end for m in self.minute_prefix)
            if (ends != tuple(sorted(set(ends))) or not set(expected).issubset(ends)
                or any(m.bar_end > self.minute_target or m.received_at > self.evaluated_at
                    for m in self.minute_prefix)):
                raise ValueError("minute conditions require their complete available source bucket")
            symbols = {m.symbol for m in self.minute_prefix}
            if len(symbols) != 1 or any(b.symbol not in symbols for b in self.five_minute_bars):
                raise ValueError("minute evidence symbol mismatch")
            ends = tuple(b.bar_end for b in self.five_minute_bars)
            if ends != tuple(sorted(set(ends))) or ends[-1] != self.minute_target:
                raise ValueError("minute history must end at the exact ordered target")
            expected_bucket = expected_five_minute_ends(self.minute_target)
            selected = tuple(m for m in self.minute_prefix if m.bar_end in expected_bucket)
            if (
                aggregate_five_minute_bar(selected, bucket_end=self.minute_target, is_open=True)
                != self.five_minute_bars[-1]
            ):
                raise ValueError("minute close must agree with exact normalized source minutes")
        return self


class DailyActivationChangedError(ValueError):
    """A reviewed activation changed between source acquisition and commit."""


class DailyRuntimeCycleResult(DailyValue):
    symbol: str
    plan_hash: str
    activation_revision: int
    evaluated_at: ShanghaiDatetime
    duplicate: bool
    snapshot: dict
    event_ids: tuple[str, ...]
    evaluation_id: str | None = None


def _eligible(plan, day):
    activation = plan.activation
    if activation.mode == "MANUAL":
        return True
    if activation.mode == "TRADING_DAY":
        return activation.trading_day == day
    return activation.start_date <= day <= activation.end_date


def _alert_only(plan):
    return (isinstance(plan, UnifiedTradePlan) and bool(plan.alert_rules)
            and not plan.ordinary_rules and not plan.risk_branches)


def _alert_inventory(symbol):
    return {"symbol": symbol, "revision": 0, "known": False,
            "total_qty": None, "core_qty": None, "tactical_qty": None,
            "sellable_core": None, "sellable_tactical": None}


def minute_source_current(session, snapshot, now, *, required_history=None):
    """Keep every consumed five-minute bar tied to its persisted source minutes."""
    raw_target = snapshot.get("minute_target")
    if raw_target is None:
        return required_history is None
    try:
        target = datetime.fromisoformat(raw_target)
        expected = expected_five_minute_ends(target)
        recorded = tuple(MinuteBar.model_validate_json(json.dumps(value))
            for value in snapshot.get("minute_prefix", ()))
        if tuple(bar.bar_end for bar in recorded) != expected:
            return False
        bars = tuple(FiveMinuteBar.model_validate_json(json.dumps(value))
            for value in snapshot.get("five_minute_bars", ()))
        if required_history is not None:
            if len(bars) < required_history + 1:
                return False
            bars = bars[-(required_history + 1):]
        if not bars or bars[-1].bar_end != target or len(bars) > 501:
            return False
        history = MarketHistoryRepository(session)
        persisted = history.list_minutes(snapshot["symbol"],
            start=expected_five_minute_ends(bars[0].bar_end)[0], end=target)
        by_end = {bar.bar_end: bar for bar in persisted if bar.received_at <= now}
        if tuple(by_end.get(end) for end in expected) != recorded:
            return False
        prior = history.list_five_minute(snapshot["symbol"],
            start=bars[0].bar_end, end=target - timedelta(minutes=1),
            formula_version="ta-v1") if len(bars) > 1 else ()
        stored = {bar.bar_end: bar for bar in prior}
        for bar in bars:
            source = tuple(by_end.get(end) for end in expected_five_minute_ends(bar.bar_end))
            if any(item is None for item in source):
                return False
            aggregate = aggregate_five_minute_bar(source, bucket_end=bar.bar_end, is_open=True)
            if aggregate is None or aggregate != bar:
                return False
            if (bar.bar_end != target
                and (stored.get(bar.bar_end) is None or
                    stored[bar.bar_end].model_dump(mode="json") != bar.model_dump(mode="json"))):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


class DailyRuntimeEvaluationService:
    def __init__(
        self,
        unit_of_work_factory,
        *,
        prepare_inputs: Callable | None = None,
        committed_event_publisher=None,
        committed_result_observer=None,
        clock=None,
        commit_admission=None,
    ):
        self._work = unit_of_work_factory
        self._prepare = prepare_inputs
        self._publish = committed_event_publisher
        self._observe = committed_result_observer
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

    async def run_target(
        self,
        *,
        plan,
        evaluated_at,
        official_trade_date=None,
        minutes=(),
        expected_activation_revision=None,
    ):
        if self._prepare is None:
            raise RuntimeError("daily provider adapter is not composed")
        with self._work() as work:
            if expected_activation_revision is not None:
                current = work.plans.get_active(plan.symbol)
                if current is None or current.revision != expected_activation_revision:
                    return None
            active, binding = self._binding(work, plan)
            revision = active.revision
            if (
                expected_activation_revision is not None
                and revision != expected_activation_revision
            ):
                return None
            unsupported = (None if _alert_only(plan)
                else DailyAccounting(work.daily).legacy_reason(plan.symbol))
        if unsupported:
            try:
                return self.run_inputs(
                    plan=plan,
                    inputs=DailyRuntimeInputs(
                        evaluated_at=evaluated_at,
                        official_trade_date=None,
                        series=None,
                        session_dates=(),
                        suspended_dates=(),
                        quote=None,
                        data_blockers=(unsupported,),
                    ),
                    expected_activation_revision=revision,
                )
            except DailyActivationChangedError:
                return None
        inputs = await self._prepare(plan, evaluated_at, official_trade_date, minutes)
        try:
            result = self.run_inputs(plan=plan, inputs=inputs,
                expected_activation_revision=revision)
        except DailyActivationChangedError:
            return None
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
            if not _alert_only(plan) and DailyAccounting(work.daily).legacy_reason(plan.symbol):
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
                .where(
                    TradingCalendar.exchange == plan.market,
                    TradingCalendar.is_open.is_(True),
                    TradingCalendar.cal_date >= now.date() - timedelta(days=3000),
                    TradingCalendar.cal_date <= now.date() + timedelta(days=32),
                )
                .order_by(TradingCalendar.cal_date)
            ).all()
            sessions = tuple(c.cal_date for c in calendars)
            trading_calendar = tuple(TradingDay(exchange=c.exchange, cal_date=c.cal_date,
                is_open=c.is_open, previous_trade_date=c.previous_trade_date) for c in calendars)
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
            minute_target=None
            if data.get("minute_target") is None
            else datetime.fromisoformat(data["minute_target"]),
            minute_prefix=tuple(
                MinuteBar.model_validate_json(json.dumps(m))
                for m in data.get("minute_prefix", ())
            ),
            five_minute_bars=tuple(
                FiveMinuteBar.model_validate_json(json.dumps(b))
                for b in data.get("five_minute_bars", ())
            ),
            trading_calendar=trading_calendar,
            runtime_generation=data.get("runtime_generation"),
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
        self, *, plan: DailyTradePlan | UnifiedTradePlan, inputs: DailyRuntimeInputs,
        expected_activation_revision=None,
        ordinary_authority_ended=False,
        allow_ineligible_observation=False,
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
            if expected_activation_revision is not None:
                current = work.plans.get_active(plan.symbol)
                if current is None or current.revision != expected_activation_revision:
                    raise DailyActivationChangedError(
                        "daily activation changed during acquisition")
            active, binding = self._binding(work, plan)
            if (
                expected_activation_revision is not None
                and active.revision != expected_activation_revision
            ):
                raise DailyActivationChangedError("daily activation changed during acquisition")
            ordinary_eligible = _eligible(plan, now.date()) and not ordinary_authority_ended
            historical_risks = (
                work.daily.list(symbol=plan.symbol, kind="RISK")
                if not _alert_only(plan)
                and not DailyAccounting(work.daily).legacy_reason(plan.symbol)
                else ()
            )
            maintain_risk = any(
                r["payload"]["status"] in {"PENDING", "CONFIRMED", "FULFILLED"}
                or r["payload"].get("reassessment_id")
                for r in historical_risks
            )
            if (not ordinary_eligible and not maintain_risk and not ordinary_authority_ended
                and not allow_ineligible_observation) or (
                self._admission is not None and not self._admission()
            ):
                raise ValueError("daily runtime commit admission is closed")
            accounting = DailyAccounting(work.daily)
            if not _alert_only(plan) and accounting.legacy_reason(plan.symbol):
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
            inventory = (_alert_inventory(plan.symbol) if _alert_only(plan)
                else accounting.snapshot(plan.symbol, now.date()))
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
            risk_rows = (() if _alert_only(plan)
                else work.daily.list(symbol=plan.symbol, kind="RISK"))
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
                "minute_target": None
                if inputs.minute_target is None
                else inputs.minute_target.isoformat(),
                "minute_prefix": [m.model_dump(mode="json") for m in inputs.minute_prefix],
                "daily_evidence": None
                if series is None
                else daily_hash("daily-series-v1", series.model_dump(mode="json")),
            }
            if ordinary_authority_ended:
                target["ordinary_authority_ended"] = True
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
                severe = next((b for b in plan.risk_branches
                    if b.kind == "SEVERE_TECHNICAL"), None)
                severe_minute_target = (inputs.minute_target
                    if completed is not None and inputs.minute_target is not None
                    and inputs.minute_target.date() == completed.bars[-1].trade_date
                    else None)
                severe_evidence = (evaluate_unified_condition(severe.condition, completed,
                    facts=facts, bars=inputs.five_minute_bars
                        if severe_minute_target is not None else (),
                    target=severe_minute_target,
                    trading_calendar=inputs.trading_calendar,
                    macd_min_observations=(500 if plan.monitoring is None
                        else plan.monitoring.macd_min_observations))
                    if isinstance(plan, UnifiedTradePlan) and severe is not None else None)
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
                    severe_evidence=severe_evidence,
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
            risk_known = series is not None or not plan.risk_branches
            if isinstance(plan, UnifiedTradePlan) and plan.risk_branches:
                severe = next((b for b in plan.risk_branches
                    if b.kind == "SEVERE_TECHNICAL"), None)
                if severe is not None:
                    risk_minute_target = (inputs.minute_target
                        if series is not None and inputs.minute_target is not None
                        and inputs.minute_target.date() == series.bars[-1].trade_date
                        else None)
                    risk_known = risk_known and evaluate_unified_condition(severe.condition,
                        series, facts=facts,
                        bars=inputs.five_minute_bars if risk_minute_target is not None else (),
                        target=risk_minute_target, trading_calendar=inputs.trading_calendar,
                        macd_min_observations=(500 if plan.monitoring is None
                            else plan.monitoring.macd_min_observations)).outcome != "MISSING_INPUT"
            # Plan IDs are display identities, never authority to reuse a consumed
            # stock/rule occurrence. Replacement needs independently verified evidence.
            signal_rows = (() if _alert_only(plan)
                else work.daily.current_signals(symbol=plan.symbol))
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
                        if isinstance(r, (DailyEnabledRule, UnifiedRule))
                        and r.side == signal["side"]
                    ),
                    None,
                )
                if rule is not None and isinstance(
                    rule.independent_signal, (DailyResetPolicy, UnifiedResetPolicy)
                ):
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
                            and (
                                evaluate_unified_condition
                                if isinstance(plan, UnifiedTradePlan)
                                else evaluate_daily_condition
                            )(
                                rule.independent_signal.reset_condition,
                                completed,
                                facts=facts,
                                macd_min_observations=500
                                if plan.monitoring is None
                                else plan.monitoring.macd_min_observations,
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
            signal_rows = (() if _alert_only(plan)
                else work.daily.current_signals(symbol=plan.symbol))
            previous = tuple(r["payload"] for r in signal_rows)
            if not risk_blocked and ordinary_eligible:
                for rule in plan.ordinary_rules:
                    if isinstance(plan, UnifiedTradePlan):
                        daily_rule = rule.confirmation.kind == "OFFICIAL_DAILY_CLOSE"
                        confirmations = completed_series if daily_rule else (series,)
                    elif isinstance(rule, DailyEnabledRule):
                        daily_rule, confirmations = True, completed_series
                    else:
                        continue
                    for completed in confirmations:
                        confirmation_day = (
                            completed.bars[-1].trade_date
                            if daily_rule and completed is not None
                            else now.date()
                        )
                        if any(
                            r["status"] in {"CONFIRMED", "FULFILLED"}
                            and r.get("confirmed_trade_date", "") >= str(confirmation_day)
                            for r in risks
                        ):
                            continue
                        extra = (
                            {}
                            if not isinstance(plan, UnifiedTradePlan)
                            else {
                                "bars": inputs.five_minute_bars,
                                "target": inputs.minute_target,
                                "trading_calendar": inputs.trading_calendar,
                            }
                        )
                        signal = (
                            confirm_signal
                            if isinstance(plan, UnifiedTradePlan)
                            else confirm_daily_signal
                        )(
                            plan,
                            rule,
                            series=completed,
                            facts=facts,
                            previous=previous,
                            session_dates=inputs.session_dates,
                            plan_version_id=active.plan_version_id,
                            review_id=binding["review_id"],
                            **extra,
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
            signal_rows = (() if _alert_only(plan)
                else work.daily.current_signals(symbol=plan.symbol))
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
                    signal = {
                        **signal,
                        "state": "INVALIDATED",
                        "executable_qty": 0,
                        "blockers": ["PLAN_ACTIVATION_WINDOW_ENDED"],
                    }
                checked = (
                    check_execution if isinstance(plan, UnifiedTradePlan) else check_daily_execution
                )(
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
            alerts = []
            if (isinstance(plan, UnifiedTradePlan) and not ordinary_authority_ended
                    and (not allow_ineligible_observation or _eligible(plan, now.date()))):
                latest_official = next((day for day in reversed(inputs.session_dates)
                    if datetime.combine(day, time(15), now.tzinfo) <= now), None)
                for rule in plan.alert_rules:
                    daily = rule.confirmation.kind == "OFFICIAL_DAILY_CLOSE"
                    alert_series = completed_series[-1] if completed_series else None
                    minute_target = inputs.minute_target
                    day = (None if alert_series is None else alert_series.bars[-1].trade_date)
                    if not daily:
                        day = None if minute_target is None else minute_target.date()
                    period_valid = (
                        (alert_series is not None and day == latest_official and (
                            not requires_minutes(rule.condition)
                            or minute_target is not None and minute_target.date() == day))
                        if daily else (
                            minute_target is not None and bool(inputs.five_minute_bars)
                            and (not requires_daily(rule.condition)
                                or alert_series is not None
                                and alert_series.bars[-1].trade_date == latest_official)
                        )
                    )
                    evidence = (evaluate_unified_condition(rule.condition, alert_series,
                        facts=facts, bars=inputs.five_minute_bars,
                        target=minute_target if not daily or minute_target is not None
                            and minute_target.date() == day else None,
                        trading_calendar=inputs.trading_calendar,
                        macd_min_observations=500 if plan.monitoring is None
                            else plan.monitoring.macd_min_observations)
                        if period_valid else None)
                    outcome = "MISSING_INPUT" if evidence is None else evidence.outcome
                    cause_id = (None if day is None else daily_hash(
                        "condition-alert-occurrence-v1", {
                            "plan_version_id": active.plan_version_id,
                            "rule_id": rule.rule_id,
                            "confirmation": (str(day) if daily
                                else minute_target.isoformat()),
                        }))
                    alerts.append({
                        "rule_id": rule.rule_id, "cause_id": cause_id,
                        "alert_kind": rule.kind,
                        "outcome": outcome,
                        "confirmation_kind": rule.confirmation.kind,
                        "confirmed_trade_date": None if day is None else str(day),
                        "confirmed_at": None if day is None else (
                            datetime.combine(day, time(15), now.tzinfo).isoformat()
                            if daily else minute_target.isoformat()),
                        "evidence": [] if evidence is None else [evidence.model_dump(mode="json")],
                    })
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
                "alerts": alerts,
                "risks": saved_risks,
                "risk_action": risk_action,
                "risk_input_known": risk_known,
                "data_blockers": list(inputs.data_blockers),
                "daily_evidence": None if series is None else series.model_dump(mode="json"),
                "runtime_generation": inputs.runtime_generation,
                "minute_target": None
                if inputs.minute_target is None
                else inputs.minute_target.isoformat(),
                "minute_prefix": [m.model_dump(mode="json") for m in inputs.minute_prefix],
                "five_minute_bars": [b.model_dump(mode="json") for b in inputs.five_minute_bars],
                "quote": None if quote is None else quote.model_dump(mode="json"),
                "next_action": "REVIEW_RISK_EXIT"
                if risk_action["status"] == "RISK_EXIT"
                else "CONFIRM_SIMULATED_TRADE"
                if any(s["executable_qty"] for s in signals)
                else "WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION",
            }
            events = []
            for alert in alerts:
                if alert["outcome"] == "SATISFIED" and alert["cause_id"] is not None:
                    events.append(self._enqueue(work, plan, active, binding, now,
                        cause_id=alert["cause_id"], side="REMINDER", quantity=None,
                        simulated=0, confirmed=alert["confirmed_trade_date"],
                        execution=None, scope=None, evidence=alert["evidence"],
                        rule_id=alert["rule_id"], alert_kind=alert["alert_kind"]))
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
            if self._admission is not None and not self._admission():
                raise RuntimeError("daily runtime commit admission changed")
            work.commit()
        self._current_inputs[plan.symbol] = inputs
        result = DailyRuntimeCycleResult(
            symbol=plan.symbol,
            plan_hash=plan_sha256(plan),
            activation_revision=active.revision,
            evaluated_at=now,
            duplicate=False,
            snapshot=snapshot,
            event_ids=tuple(event for event in events if event is not None),
            evaluation_id=identity,
        )
        if self._observe is not None:
            self._observe(plan, result, inputs)
        return result

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
        rule_id=None,
        alert_kind=None,
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
                severity="RISK" if side in {"RISK_EXIT", "REMINDER"} else "ACTION",
                trading_date=now.date(),
                evaluated_at=now,
                cause_id=cause_id,
                rule_id=rule_id,
                alert_kind=alert_kind,
                confirmed_trade_date=confirmed,
                execution_date=execution,
                quantity=quantity,
                simulated_qty=simulated,
                risk_scope=scope,
                evidence=tuple(evidence),
                next_step="REVIEW_RISK_EXIT" if side == "RISK_EXIT" else
                    "REVIEW_ALERT" if side == "REMINDER" else "CONFIRM_SIMULATED_TRADE",
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
    from trade_plan_monitor.domain.plan_codec import load_plan_json
    plan = load_plan_json(version.payload_json)
    if not isinstance(plan, UnifiedTradePlan):
        return False
    repo = DailyRepository(session, clock=lambda: now, id_factory=lambda: str(uuid4()))
    if event.signal_type != "REMINDER" and DailyAccounting(repo).legacy_reason(event.symbol):
        return False
    review = repo.get("review-" + event.plan_version_id)
    if (
        review is None
        or not review["payload"].get("confirmed")
        or review["payload"].get("review_id") != event.review_id
    ):
        return False
    if event.signal_type == "REMINDER":
        head = repo.get("evaluation-head-" + event.symbol)
        if head is None or head["payload"].get("plan_version_id") != event.plan_version_id:
            return False
        rule = next((item for item in plan.alert_rules if item.rule_id == event.rule_id), None)
        if rule is None:
            return False
        daily_required = requires_daily(rule.condition)
        if daily_required:
            if set(head["payload"].get("data_blockers", ())) & {
                "OFFICIAL_DAILY_SESSION_UNVERIFIED",
                "DAILY_QFQ_PROVIDER_UNAVAILABLE",
                "CURRENT_QUOTE_BASIS_UNVERIFIED",
                "PRICE_BASIS_UNVERIFIED",
            }:
                return False
            evidence = head["payload"].get("daily_evidence")
            if evidence is None:
                return False
            try:
                series = DailySeries.model_validate(evidence)
            except ValueError:
                return False
            if (series.cutoff > event.evaluated_at
                or head["payload"].get("official_trade_date") != str(
                    series.bars[-1].trade_date)
                or rule.confirmation.kind == "OFFICIAL_DAILY_CLOSE" and
                    str(series.bars[-1].trade_date) != str(event.confirmed_trade_date)):
                return False
        minute_required = (rule.confirmation.kind == "COMPLETED_BAR_CLOSE"
            or requires_minutes(rule.condition))
        required_history = max((leaf.window_bars for leaf in condition_leaves(rule.condition)
            if leaf.type == "MINUTE_VOLUME_TO_MEAN_GTE"), default=0)
        accounting = DailyAccounting(repo)
        inventory = (_alert_inventory(event.symbol) if _alert_only(plan)
            else accounting.snapshot(event.symbol, now.date()))
        if not accounting.evaluation_current(
            head["payload"], plan_version_id=event.plan_version_id,
            content_hash=review["payload"]["content_hash"], inventory=inventory,
            now=now, require_daily_data=False,
        ) or minute_required and not minute_source_current(
            session, head["payload"], now, required_history=required_history):
            return False
        return (
            any(alert.get("cause_id") == event.cause_id
                and alert.get("rule_id") == event.rule_id
                and alert.get("alert_kind") == event.alert_kind
                and alert.get("outcome") == "SATISFIED"
                and alert.get("confirmed_trade_date") == str(event.confirmed_trade_date)
                for alert in head["payload"].get("alerts", ()))
            and event.evaluated_at <= now < event.evaluated_at + timedelta(minutes=5)
        )
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
        if not accounting.evaluation_current(
            head["payload"],
            plan_version_id=event.plan_version_id,
            content_hash=review["payload"]["content_hash"],
            inventory=inventory,
            now=now,
            require_daily_data=False,
        ):
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
    if not DailyAccounting(repo).evaluation_current(
        head["payload"],
        plan_version_id=event.plan_version_id,
        content_hash=review["payload"]["content_hash"],
        inventory=inventory,
        now=now,
        require_daily_data=True,
    ):
        return False
    try:
        quote = DailyExecutionQuote.model_validate(
            {**head["payload"]["quote"], "evaluated_at": now}
        )
    except ValueError, TypeError:
        return False
    from trade_plan_monitor.domain.plan_codec import load_plan_json

    plan = load_plan_json(version.payload_json)
    checked = (check_execution if isinstance(plan, UnifiedTradePlan) else check_daily_execution)(
        plan,
        s,
        inventory=inventory,
        quote_fen=quote.price_fen,
        evaluated_at=now,
        tradable=quote.tradable and quote.special_state_verified and quote.liquidity_available,
        risk_blocked=False,
        risk_known=head["payload"].get("risk_input_known",
            head["payload"].get("daily_evidence") is not None or not plan.risk_branches),
    )
    return checked[
        "executable_qty"
    ] == event.quantity and event.evaluated_at <= now < event.evaluated_at + timedelta(minutes=5)
