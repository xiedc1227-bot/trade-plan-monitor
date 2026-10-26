"""Frozen arrival-time stream feeding an isolated instance of the current monitor."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta
from hashlib import sha256
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import check_cancelled
from trade_plan_monitor.backtest.dataset import DatasetManifest
from trade_plan_monitor.backtest.exception_replay import apply_frozen_exception
from trade_plan_monitor.backtest.market_linkage_input import LinkedIndexReplaySource
from trade_plan_monitor.backtest.research_input import ResearchAdjustmentProof
from trade_plan_monitor.backtest.research_report import (
    ResearchDecisionEvent,
    ResearchRuleEvidence,
    UnifiedReplayReport,
)
from trade_plan_monitor.backtest.research_session import ResearchSession
from trade_plan_monitor.backtest.research_valuation import ResearchValuation
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.backtest.time import SHANGHAI, format_shanghai_datetime
from trade_plan_monitor.decision.unified_conditions import (
    evaluate_unified_condition,
    requires_daily,
)
from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote, admit_qfq_daily
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs, _eligible
from trade_plan_monitor.state.daily_state_models import DailyInventoryView


def replay_current(
    reader,
    *,
    plan,
    initial_cash_fen,
    initial_lots,
    execution_config,
    manual_event_risk,
    plan_version_id,
    research_input,
    cancellation_token,
):
    run_input = BacktestRunInput.create(
        plan=plan,
        manifest=(reader.manifest if plan.schema_version in {6, 7, 8} else
                  DatasetManifest(dataset_hash=reader.dataset_hash, scope=reader.scope, items=())),
        initial_cash_fen=initial_cash_fen,
        initial_lots=initial_lots,
        execution_config=execution_config,
        manual_event_risk=manual_event_risk,
        plan_version_id=plan_version_id,
        research_input=research_input,
    )
    if plan.symbol not in reader.scope.symbols:
        raise ValueError("PLAN_SYMBOL_NOT_IN_DATASET")
    linked_source = None
    if plan.schema_version in {6, 7, 8}:
        from trade_plan_monitor.market_index.models import MarketIndexInterval
        linked_source = LinkedIndexReplaySource(
            reference_market=plan.reference_market,
            bars=tuple(
                sorted(
                    (
                        bar
                        for bar in reader.market_index_bars(plan.reference_market.index_code)
                        if bar.interval == MarketIndexInterval.OFFICIAL_DAILY
                    ),
                    key=lambda bar: (bar.observed_at, bar.bar_at, bar.provider_revision),
                )
            ),
        )
    with TemporaryDirectory(prefix="unified-research-") as temporary:
        directory = Path(temporary)
        with closing(sqlite3.connect(directory / "events.sqlite")) as spool:
            spool.execute("CREATE TABLE event(at TEXT, tie TEXT, kind TEXT, payload TEXT)")
            calendar = {}
            for day in reader:
                check_cancelled(cancellation_token, "RUN_DAY_TRANSITION")
                if day.symbol != plan.symbol:
                    continue
                calendar[day.trade_date] = day.trading_day
                for kind, values in (
                    ("MINUTE", day.minutes),
                    ("DAILY", () if day.daily_bar is None else (day.daily_bar,)),
                    ("LIMIT", () if day.daily_limit is None else (day.daily_limit,)),
                ):
                    for value in values:
                        _insert(
                            spool,
                            value.received_at,
                            kind,
                            kind + ":" + value.model_dump_json(),
                            value.model_dump_json(),
                        )
            for day in research_input.calendar_extension:
                if (
                    day.exchange != plan.market
                    or day.cal_date <= reader.scope.end
                    or day.cal_date > reader.scope.end + timedelta(days=32)
                ):
                    raise ValueError("RESEARCH_CALENDAR_EXTENSION_BINDING_MISMATCH")
                if day.cal_date in calendar and calendar[day.cal_date] != day:
                    raise ValueError("RESEARCH_CALENDAR_CONFLICT")
                calendar[day.cal_date] = day
            for proof in research_input.adjustment_proofs:
                _insert(spool, proof.received_at, "PROOF", proof.proof_id, proof.model_dump_json())
            if linked_source is not None:
                linked_source.validate_scope(binding=plan.reference_market,
                    session_dates=tuple(day.cal_date for day in calendar.values() if day.is_open),
                    started_at=research_input.started_at,
                    cutoff=datetime.combine(reader.scope.end, time.max, SHANGHAI))
                for bar in linked_source.bars:
                    _insert(
                        spool,
                        bar.observed_at,
                        "INDEX",
                        bar.model_dump_json(),
                        bar.model_dump_json(),
                    )
            for operation in research_input.operations:
                _insert(
                    spool,
                    operation.at,
                    "OPERATION",
                    f"{operation.order:05d}",
                    operation.operation_id,
                )
            for event in getattr(research_input, "exception_authorization_events", ()):
                _insert(spool, event.event.received_at, "EXCEPTION",
                        f"{event.order:05d}", event.envelope_hash)
            spool.commit()
            calendar = tuple(calendar[day] for day in sorted(calendar))
            session = ResearchSession(directory, run_input, calendar)
            try:
                return _Replay(
                    spool, session, calendar, cancellation_token, linked_source=linked_source
                ).run()
            finally:
                session.close()


def _insert(spool, at, kind, tie, payload):
    spool.execute(
        "INSERT INTO event VALUES (?, ?, ?, ?)", (format_shanghai_datetime(at), tie, kind, payload)
    )


class _Replay:
    def __init__(self, spool, session, calendar, cancellation, *, linked_source=None):
        self.spool = spool
        self.session, self.calendar, self.cancellation = session, calendar, cancellation
        self.plan = session.plan
        self.frozen = session.run_input.research_input
        self.end = datetime.combine(session.run_input.end, time.max, SHANGHAI)
        self.open_dates = tuple(day.cal_date for day in calendar if day.is_open)
        self.events, self.outcomes = [], []
        self.minutes, self.five_bars, self.raw_daily, self.limits = {}, {}, {}, {}
        self.latest_quote, self.proof, self.target = None, None, None
        self.operations = {o.operation_id: o for o in self.frozen.operations}
        self.exception_events = {e.envelope_hash: e for e in getattr(
            self.frozen, "exception_authorization_events", ())}
        self.exception_outcomes = []
        self.ended = False
        self.valuation = ResearchValuation(session.run_input)
        self.linked_source = linked_source

    def run(self):
        with closing(self.spool.execute("SELECT * FROM event ORDER BY at, tie")) as cursor:
            return self._run_events(cursor)

    def _run_events(self, cursor):
        for at, rows in groupby(cursor, key=lambda row: row[0]):
            now = datetime.fromisoformat(at)
            if now > self.end:
                break
            check_cancelled(
                self.cancellation,
                "RUN_EVALUATION",
                last_safe_event_id=None if not self.events else self.events[-1].event_id,
            )
            self.session.now = now
            group = tuple(rows)
            targets, official = [], None
            for _, _, kind, payload in group:
                if kind in {"OPERATION", "EXCEPTION"}:
                    continue
                new_target, new_official = self._market(kind, payload)
                if new_target is not None:
                    targets.append(new_target)
                if new_official is not None:
                    official = new_official
            if now < self.frozen.started_at:
                continue
            operations = [self.operations[row[3]] for row in group if row[2] == "OPERATION"]
            for operation in operations:
                if operation.kind in {"FACT", "DEACTIVATE", "REPLACE"}:
                    inputs = self.inputs(official, max(targets) if targets else self.target)
                    outcome = self.session.apply_evidence(operation, inputs)
                    self.outcomes.append(outcome)
                    if operation.kind in {"DEACTIVATE", "REPLACE"} and outcome.status == "APPLIED":
                        self.ended = True
            if (
                targets
                or official is not None
                or operations
                or any(r[2] == "EXCEPTION" for r in group)
                or any(r[2] in {"PROOF", "INDEX"} for r in group)
            ):
                self.evaluate(official, max(targets) if targets else self.target, group)
            for _, _, kind, payload in group:
                if kind == "EXCEPTION":
                    self.exception_outcomes.append(apply_frozen_exception(
                        self.session, self.exception_events[payload]))
                    self.evaluate(official, max(targets) if targets else self.target,
                                  ((at, "authorization-applied", kind, payload),))
                    self.events[-1] = self.events[-1].model_copy(update={
                        "exception_outcomes": (self.exception_outcomes[-1],)})
                elif kind == "OPERATION" and self.operations[payload].kind not in {
                    "FACT", "DEACTIVATE", "REPLACE"
                }:
                    self.outcomes.append(
                        self.valuation.operation(
                            self.session.apply_operation(self.operations[payload], ended=self.ended)
                        )
                    )
            if operations and self.events:
                with self.session.work() as work:
                    signals = tuple(
                        {**row["payload"], "revision": row["revision"]}
                        for row in work.daily.current_signals(symbol=self.plan.symbol)
                    )
                    risks = tuple(
                        {**row["payload"], "risk_id": row["id"], "revision": row["revision"]}
                        for row in work.daily.list(symbol=self.plan.symbol, kind="RISK")
                    )
                self.events[-1] = self.events[-1].model_copy(
                    update={
                        "resulting_signals": signals,
                        "resulting_risks": risks,
                        "inventory_after": DailyInventoryView.model_validate(
                            self.session.inventory()
                        ),
                    }
                )
            daily = self.raw_daily.get(now.date())
            price = (
                daily.close_fen
                if daily is not None
                else (
                    self.latest_quote.close_fen
                    if self.latest_quote is not None
                    and self.latest_quote.bar_end.date() == now.date()
                    else None
                )
            )
            self.valuation.mark(
                now, DailyInventoryView.model_validate(self.session.inventory()), price
            )
        self.session.now = self.end
        if not self.valuation.marks:
            self.valuation.mark(
                self.end, DailyInventoryView.model_validate(self.session.inventory()), None
            )
        limitations = [
            "ISOLATED_RESEARCH_AUTHORITY_NOT_HISTORICAL_REVIEW",
            "EXPLICIT_SIMULATION_ONLY_NO_BROKER",
            "NO_EXTERNAL_PROVIDER_OR_NOTIFICATION",
            "CERTIFIED_DAILY_EVIDENCE_REQUIRES_FROZEN_ADJUSTMENT_PROOF",
        ]
        if not self.frozen.inventory_known:
            limitations.extend(("UNKNOWN_INVENTORY", "VALUATION_EXCLUDES_UNKNOWN_HOLDINGS"))
        limitations.extend(
            sorted(
                {
                    blocker
                    for outcome in self.outcomes
                    for blocker in outcome.blockers
                    if blocker.endswith("UNSUPPORTED")
                }
            )
        )
        limitations.extend(self.valuation.blockers)
        if self.plan.schema_version in {7, 8}:
            from trade_plan_monitor.backtest.research_signal_projection import (
                compact_signal_evidence,
            )

            compacted = []
            for event in self.events:
                event = ResearchDecisionEvent.model_validate_json(event.model_dump_json())
                values = {name: getattr(event, name) for name in type(event).model_fields}
                compacted.append(ResearchDecisionEvent.model_validate(compact_signal_evidence(values)))
            self.events = compacted
            limitations.extend((
                "FROZEN_EXCEPTION_EVENTS_ONLY", "EXPLICIT_EXCEPTION_EXECUTION_ONLY"))
            limitations.extend(sorted({e.provenance for e in self.exception_events.values()}))
            if not self.exception_events:
                limitations.append("EXCEPTION_AUTHORIZATION_NOT_SUPPLIED")
        return UnifiedReplayReport.build(
            **({"exception_outcomes": tuple(self.exception_outcomes)}
               if self.plan.schema_version in {7, 8} else {}),
            run_id=self.session.run_input.run_id,
            plan_hash=self.session.run_input.plan_sha256,
            dataset_hash=self.session.run_input.dataset_hash,
            symbol=self.plan.symbol,
            start=self.session.run_input.start,
            end=self.session.run_input.end,
            execution_config=self.session.run_input.execution_config,
            current_events=tuple(self.events),
            operations=tuple(self.outcomes),
            final_inventory=DailyInventoryView.model_validate(self.session.inventory()),
            daily_equity=tuple(self.valuation.marks.values()),
            metrics=self.valuation.metrics(self.outcomes),
            limitations=tuple(dict.fromkeys(limitations)),
        )

    def _market(self, kind, payload):
        now = self.session.now
        if kind == "INDEX":
            return None, None
        if kind == "LIMIT":
            limit = DailyLimit.model_validate_json(payload)
            self.limits[limit.trade_date] = limit
            self.limits = dict(sorted(self.limits.items())[-512:])
            return None, None
        if kind == "PROOF":
            self.proof = ResearchAdjustmentProof.model_validate_json(payload)
            return None, None
        if kind == "DAILY":
            daily = DailyBar.model_validate_json(payload)
            if now < datetime.combine(daily.trade_date, time(15), SHANGHAI):
                raise ValueError("OFFICIAL_DAILY_VISIBLE_TOO_EARLY")
            self.raw_daily[daily.trade_date] = daily
            self.raw_daily = dict(sorted(self.raw_daily.items())[-500:])
            return (
                None,
                daily.trade_date if daily.trade_date >= self.frozen.started_at.date() else None,
            )
        minute = MinuteBar.model_validate_json(payload)
        self.minutes[minute.bar_end] = minute
        self.minutes = dict(sorted(self.minutes.items())[-2800:])
        with self.session.work() as work:
            work.history.upsert_minutes((minute,))
            work.commit()
        if self.latest_quote is None or minute.bar_end >= self.latest_quote.bar_end:
            self.latest_quote = minute
        target = minute.bar_end.replace(minute=((minute.bar_end.minute + 4) // 5) * 5 % 60)
        if target < minute.bar_end:
            target += timedelta(hours=1)
        if target > now:
            return None, None
        source = tuple(
            m for end, m in self.minutes.items() if target - timedelta(minutes=5) < end <= target
        )
        bar = aggregate_five_minute_bar(source, bucket_end=target, is_open=True)
        if bar is not None:
            self.five_bars[target] = bar
            self.five_bars = dict(sorted(self.five_bars.items())[-512:])
            with self.session.work() as work:
                work.history.upsert_five_minute(**bar.model_dump())
                work.commit()
        if target.date() < self.frozen.started_at.date():
            return None, None
        self.target = max(target, self.target) if self.target is not None else target
        return target, None

    def inputs(self, official, target):
        now = self.session.now
        calendar = _calendar_context(self.calendar, now.date())
        session_dates = tuple(day.cal_date for day in calendar if day.is_open)
        blockers, series = [], None
        daily_needed = bool(self.plan.risk_branches) or any(
            requires_daily(r.condition) for r in (*self.plan.ordinary_rules, *self.plan.alert_rules)
        )
        if self.proof is not None and self.raw_daily:
            try:
                series = admit_qfq_daily(
                    raw_bars=tuple(self.raw_daily.values()),
                    factors={factor.trade_date: factor.factor for factor in self.proof.factors},
                    adjustment_as_of=self.proof.adjustment_as_of,
                    quote_basis_factor=self.proof.quote_basis_factor,
                    provider=self.proof.provider,
                    session_dates=session_dates,
                    suspended_dates=(),
                    cutoff=now,
                )
            except ValueError as error:
                if daily_needed:
                    blockers.append(getattr(error, "code", "DAILY_SESSION_OR_BASIS_UNVERIFIED"))
        elif daily_needed:
            blockers.append("PRICE_BASIS_UNVERIFIED")
        if self.ended:
            blockers.append("ORDINARY_AUTHORITY_ENDED")
        elif not _eligible(self.plan, now.date()):
            blockers.append("PLAN_ACTIVATION_WINDOW_INACTIVE")
        prefix = tuple(
            m
            for end, m in self.minutes.items()
            if target is not None and end.date() == target.date() and end <= target
        )
        bars = tuple(
            bar for end, bar in self.five_bars.items() if target is not None and end <= target
        )
        if target is not None and (not bars or bars[-1].bar_end != target):
            blockers.append("CURRENT_DAY_MINUTE_PREFIX_MISSING")
            bars = ()
        quote = None
        minute = self.latest_quote
        if minute is not None and timedelta(0) <= now - minute.bar_end <= timedelta(minutes=5):
            quote = DailyExecutionQuote(
                symbol=self.plan.symbol,
                price_fen=minute.close_fen,
                quote_at=minute.bar_end,
                available_at=minute.received_at,
                evaluated_at=now,
                tradable=minute.volume_shares > 0,
                special_state_verified=now.date() in self.limits,
                liquidity_available=minute.volume_shares > 0,
            )
        return DailyRuntimeInputs(
            evaluated_at=now,
            official_trade_date=official,
            series=series,
            session_dates=session_dates,
            suspended_dates=(),
            quote=quote,
            data_blockers=tuple(blockers),
            minute_prefix=prefix,
            five_minute_bars=bars,
            minute_target=target,
            trading_calendar=calendar,
            linked_index=None
            if self.linked_source is None
            else self.linked_source.snapshot_at(now, session_dates),
        )

    def evaluate(self, official, target, group):
        if len(self.events) >= 70000:
            raise ValueError("RESEARCH_EVENT_LIMIT_EXCEEDED")
        inputs = self.inputs(official, target)
        before = DailyInventoryView.model_validate(self.session.inventory())
        result = self.session.runtime.run_inputs(
            plan=self.plan,
            inputs=inputs,
            ordinary_authority_ended=self.ended,
            allow_ineligible_observation=True,
        )
        with self.session.work() as work:
            facts = tuple(
                {**row["payload"], "id": row["id"]}
                for row in work.daily.list(symbol=self.plan.symbol, kind="FACT")
            )
        conditions = tuple(
            ResearchRuleEvidence(
                rule_id=rule.rule_id,
                evidence=evaluate_unified_condition(
                    rule.condition,
                    inputs.series,
                    facts=facts,
                    bars=inputs.five_minute_bars,
                    target=target,
                    trading_calendar=inputs.trading_calendar,
                    macd_min_observations=500
                    if self.plan.monitoring is None
                    else self.plan.monitoring.macd_min_observations,
                ),
            )
            for rule in (*self.plan.ordinary_rules, *self.plan.alert_rules)
        )
        self.events.append(
            ResearchDecisionEvent.model_validate(
                {
                    "event_id": sha256(
                        (
                            "unified-research-event-v1\0"
                            + canonical_json(
                                {
                                    "authority": self.session.run_input.authority_id,
                                    "at": self.session.now,
                                    "facts": tuple(
                                        (
                                            at,
                                            tie,
                                            kind,
                                            {
                                                key: value
                                                for key, value in json.loads(payload).items()
                                                if key != "dataset_hash"
                                            }
                                            if kind == "PROOF"
                                            else payload,
                                        )
                                        for at, tie, kind, payload in group
                                    ),
                                }
                            )
                        ).encode()
                    ).hexdigest(),
                    "at": self.session.now,
                    "evaluation_id": result.evaluation_id,
                    "official_trade_date": None if official is None else str(official),
                    "minute_target": target,
                    "signals": tuple(result.snapshot["signals"]),
                    "risks": tuple(result.snapshot["risks"]),
                    "alerts": tuple(result.snapshot.get("alerts", ())),
                    "resulting_signals": tuple(result.snapshot["signals"]),
                    "resulting_risks": tuple(result.snapshot["risks"]),
                    "risk_action": result.snapshot["risk_action"],
                    "conditions": conditions,
                    **({"market_linkage": tuple(result.snapshot["market_linkage"])}
                       if "market_linkage" in result.snapshot else {}),
                    "blockers": tuple(inputs.data_blockers),
                    "inventory_before": before,
                    "inventory_after": DailyInventoryView.model_validate(self.session.inventory()),
                }
            )
        )


def _calendar_context(calendar, trade_date):
    """Keep the declared 512-row context and only the first future open session."""
    past = tuple(day for day in calendar if day.cal_date <= trade_date)
    future = []
    for day in calendar:
        if day.cal_date <= trade_date:
            continue
        future.append(day)
        if day.is_open:
            break
    # Missing historical coverage remains missing to the daily admission gate.
    return (*past, *future)[-512:]
