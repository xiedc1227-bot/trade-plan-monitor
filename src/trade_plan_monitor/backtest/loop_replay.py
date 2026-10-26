"""Availability-ordered frozen facts driving the native single-plan monitor loop."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta
from hashlib import sha256
from itertools import groupby
from pathlib import Path
from tempfile import TemporaryDirectory

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import BacktestProgress, CancellationToken
from trade_plan_monitor.backtest.loop_dataset import loop_dataset_requirements
from trade_plan_monitor.backtest.loop_input import ScheduledLoopInput
from trade_plan_monitor.backtest.loop_publication import stage_loop_report
from trade_plan_monitor.backtest.loop_report import LoopReportWriter, decode_loop_event
from trade_plan_monitor.backtest.loop_runner import LoopFrame, LoopRunner
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.time import SHANGHAI, format_shanghai_datetime
from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.market_data.daily_data import (
    DailyAdmissionError,
    DailyExecutionQuote,
    admit_qfq_daily,
)
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs


def run_frozen_loop(store, reference, *, cancellation_token: CancellationToken, progress_callback):
    """Use only result-owned copies; temporary files close before the worker returns."""
    cancellation_token.raise_if_cancelled("RUN_DAY_TRANSITION")
    stored = store.get_loop_input(reference)
    with TemporaryDirectory(prefix=".loop-worker-", dir=store.database_path.parent) as temporary:
        directory = Path(temporary)
        with closing(sqlite3.connect(directory / "arrival.sqlite")) as spool:
            spool.execute(
                "CREATE TABLE arrival(at TEXT, identity TEXT PRIMARY KEY, kind TEXT, payload TEXT)"
            )
            calendar = []
            with store.loop_input_store.open_dataset(reference) as reader:
                for index, day in enumerate(reader):
                    cancellation_token.raise_if_cancelled("RUN_DAY_TRANSITION")
                    calendar.append(day.trading_day)
                    _insert(
                        spool,
                        datetime.combine(day.trade_date, time.min, SHANGHAI),
                        "DAY",
                        day.trade_date.isoformat(),
                    )
                    selection = stored.dataset.days[index]
                    for kind, values, refs in (
                        ("MINUTE", day.minutes, selection.minutes),
                        ("LIMIT", day.daily_limits, selection.limits),
                        ("DAILY", day.daily_bars, selection.daily),
                    ):
                        for value, ref in zip(values, refs, strict=True):
                            cancellation_token.raise_if_cancelled("RUN_DAY_TRANSITION")
                            identity = (
                                ref.artifact_hash if kind == "MINUTE" else ref.item.artifact_hash
                            )
                            _insert(
                                spool,
                                value.received_at,
                                kind,
                                value.model_dump_json(),
                                identity=identity,
                            )
            run = stored.run_input
            linked_source = stored.dataset.linked_index_source
            for row in run.schedule.entries:
                if row.version.snapshot.schema_version in {6, 7, 8} and (
                    linked_source is None
                    or linked_source.reference_market != row.version.snapshot.reference_market
                ):
                    raise ValueError("LINKED_INDEX_REPLAY_HISTORY_MISSING")
            if linked_source is not None:
                for bar in linked_source.bars:
                    _insert(spool, bar.observed_at, "INDEX", bar.model_dump_json())
            for factor in stored.dataset.adjustment_factors:
                _insert(
                    spool,
                    factor.available_at,
                    "BASIS",
                    str(factor.trade_date),
                    identity=factor.evidence_hash,
                )
            for at in (run.boundary.started_at, run.boundary.evidence_cutoff):
                _insert(spool, at, "BOUNDARY", "")
            if run.exception_program is not None:
                for event in run.exception_program.exception_authorization_events:
                    _insert(spool, event.event.received_at, "EXCEPTION", event.envelope_hash)
                for operation in run.exception_program.operations:
                    _insert(spool, operation.at, "EXCEPTION_OPERATION", operation.operation_id)
            spool.commit()
            with LoopSession(directory, run, tuple(calendar)) as session:
                with (directory / "audit.ndjson").open(
                    "w+", encoding="utf-8", newline="\n"
                ) as audit:
                    writer = LoopReportWriter(
                        session, sink=lambda event: audit.write(canonical_json(event) + "\n")
                    )
                    frames = _Frames(
                        spool,
                        session.plan,
                        run,
                        tuple(calendar),
                        cancellation_token,
                        progress_callback,
                        adjustment_factors=stored.dataset.adjustment_factors,
                        linked_source=linked_source,
                    )
                    cycle = LoopRunner(session, report_writer=writer).run(
                        frames, cancellation_token=cancellation_token
                    )
                    report = writer.finish(cycle)
                    audit.flush()
                    audit.seek(0)
                    stage_loop_report(
                        store,
                        reference=reference,
                        report=report,
                        events=(decode_loop_event(line) for line in audit),
                        cancellation_token=cancellation_token,
                    )
                    progress_callback(
                        BacktestProgress(
                            phase="RUN_REPORT_HANDOFF",
                            completed_units=frames.total_units,
                            total_units=frames.total_units,
                        )
                    )
            return report


def _insert(spool, at, kind, payload, *, identity=None):
    identity = (
        identity
        or sha256(
            (kind + "\0" + payload + "\0" + format_shanghai_datetime(at)).encode()
        ).hexdigest()
    )
    spool.execute(
        "INSERT OR IGNORE INTO arrival VALUES (?, ?, ?, ?)",
        (format_shanghai_datetime(at), identity, kind, payload),
    )


class _Frames:
    """One bounded rolling context, with no scripted trade/fact/response operations."""

    def __init__(
        self,
        spool,
        plan,
        run,
        calendar,
        token,
        progress,
        *,
        adjustment_factors=(),
        linked_source=None,
    ):
        self.spool, self.plan, self.run, self.calendar = spool, plan, run, calendar
        self.token, self.progress = token, progress
        self.minutes, self.fives, self.limits = {}, {}, {}
        self.daily = {}
        self.adjustment_factors = adjustment_factors
        self.linked_source = linked_source
        self.latest, self.target = None, None
        self.daily_needed = loop_dataset_requirements(plan).requires_daily

    def __iter__(self):
        total = int(
            self.spool.execute(
                "SELECT COUNT(DISTINCT at) FROM arrival WHERE at >= ? AND at <= ?",
                (
                    format_shanghai_datetime(self.run.boundary.started_at),
                    format_shanghai_datetime(self.run.boundary.evidence_cutoff),
                ),
            ).fetchone()[0]
        )
        self.total_units = max(total, 1)
        completed = 0
        with closing(
            self.spool.execute("SELECT at, kind, payload FROM arrival ORDER BY at, kind, identity")
        ) as cursor:
            for text, rows in groupby(cursor, key=lambda row: row[0]):
                now = datetime.fromisoformat(text)
                self.token.raise_if_cancelled("RUN_EVALUATION")
                if now > self.run.boundary.evidence_cutoff:
                    break
                official, arrived = None, []
                for _, kind, payload in rows:
                    if kind == "MINUTE":
                        minute = MinuteBar.model_validate_json(payload)
                        self._minute(minute, now)
                        arrived.append(minute)
                    elif kind == "LIMIT":
                        limit = DailyLimit.model_validate_json(payload)
                        self.limits[limit.trade_date] = limit
                        self.limits = dict(sorted(self.limits.items())[-512:])
                    elif kind == "DAILY":
                        daily = DailyBar.model_validate_json(payload)
                        self.daily[daily.trade_date] = daily
                        self.daily = dict(sorted(self.daily.items())[-500:])
                        official = daily.trade_date
                    elif kind == "BASIS" and self.daily:
                        official = max(self.daily)
                if now < self.run.boundary.started_at:
                    continue
                minute = max(arrived, key=lambda value: value.bar_end, default=None)
                # All same-time facts are available before monitoring; choose a current,
                # fresh execution quote without rewinding to a delayed historical interval.
                if minute is not None and minute != self.latest:
                    minute = None
                runtime = self._inputs(now, official)
                if minute is not None and (
                    runtime.quote is None or runtime.quote.quote_at != minute.bar_end
                ):
                    minute = None
                completed += 1
                self.progress(
                    BacktestProgress(
                        phase="RUN_EVALUATION", completed_units=completed, total_units=max(total, 1)
                    )
                )
                yield LoopFrame(
                    runtime=runtime,
                    minute=minute,
                    daily_limit=None if minute is None else self.limits.get(minute.bar_end.date()),
                )

    def _minute(self, minute, now):
        prior = self.minutes.get(minute.bar_end)
        if prior is not None and prior.received_at > minute.received_at:
            return
        self.minutes[minute.bar_end] = minute
        self.minutes = dict(sorted(self.minutes.items())[-2800:])
        if self.latest is None or (minute.bar_end, minute.received_at) >= (
            self.latest.bar_end,
            self.latest.received_at,
        ):
            self.latest = minute
        target = minute.bar_end.replace(minute=((minute.bar_end.minute + 4) // 5) * 5 % 60)
        if target < minute.bar_end:
            target += timedelta(hours=1)
        if target > now:
            return
        source = tuple(
            value
            for end, value in self.minutes.items()
            if target - timedelta(minutes=5) < end <= target
        )
        five = aggregate_five_minute_bar(source, bucket_end=target, is_open=True)
        if five is not None:
            self.fives[target] = five
            self.fives = dict(sorted(self.fives.items())[-512:])
            self.target = max(self.target, target) if self.target is not None else target

    def _inputs(self, now, official):
        if isinstance(self.run, ScheduledLoopInput):
            selection = self.run.schedule.select(now)
            self.daily_needed = (
                selection is not None
                and loop_dataset_requirements(selection.version.snapshot).requires_daily
            )
            if selection is not None:
                self.plan = selection.version.snapshot
        past = tuple(day for day in self.calendar if day.cal_date <= now.date())
        future = []
        for day in self.calendar:
            if day.cal_date > now.date():
                future.append(day)
                if day.is_open:
                    break
        calendar = (*past, *future)[-512:]
        target = (
            self.target if self.target is not None and self.target.date() == now.date() else None
        )
        prefix = tuple(
            value
            for end, value in self.minutes.items()
            if target is not None and end.date() == target.date() and end <= target
        )
        quote = None
        minute = self.latest
        if minute is not None and timedelta(0) <= now - minute.bar_end <= timedelta(minutes=5):
            quote = DailyExecutionQuote(
                symbol=self.plan.symbol,
                price_fen=minute.close_fen,
                quote_at=minute.bar_end,
                available_at=minute.received_at,
                evaluated_at=now,
                tradable=minute.volume_shares > 0,
                liquidity_available=minute.volume_shares > 0,
                special_state_verified=minute.bar_end.date() in self.limits,
            )
        series, blockers = self._daily_series(now, calendar)
        return DailyRuntimeInputs(
            evaluated_at=now,
            official_trade_date=official,
            series=series,
            session_dates=tuple(day.cal_date for day in calendar if day.is_open),
            suspended_dates=(),
            quote=quote,
            data_blockers=blockers if self.daily_needed else (),
            minute_prefix=prefix,
            five_minute_bars=()
            if target is None
            else tuple(bar for end, bar in self.fives.items() if end <= target),
            minute_target=target,
            trading_calendar=calendar,
            linked_index=(
                self.linked_source.snapshot_at(
                    now, tuple(day.cal_date for day in calendar if day.is_open)
                )
                if self.plan.schema_version in {6, 7, 8} and self.linked_source is not None
                else None
            ),
        )

    def _daily_series(self, now, calendar):
        sessions = tuple(
            day.cal_date for day in calendar if day.is_open and day.cal_date <= now.date()
        )
        eligible = {
            p.trade_date: p.factor
            for p in self.adjustment_factors
            if p.symbol == self.plan.symbol and p.available_at <= now and p.trade_date <= now.date()
        }
        if not sessions or sessions[-1] not in eligible or not self.daily:
            return None, ("PRICE_BASIS_UNVERIFIED",)
        try:
            series = admit_qfq_daily(
                raw_bars=tuple(self.daily.values()),
                factors=eligible,
                adjustment_as_of=sessions[-1],
                quote_basis_factor=eligible[sessions[-1]],
                provider="TUSHARE",
                session_dates=sessions,
                suspended_dates=(),
                cutoff=now,
            )
        except DailyAdmissionError as error:
            return None, (error.code,)
        return series, ()
