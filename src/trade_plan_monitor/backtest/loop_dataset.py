"""One plan's immutable market selection at its frozen evidence cutoff.

Selection reads existing content-addressed artifacts. It adds no catalog rows;
run-input storage copies its referenced artifacts before acknowledging admission.
"""

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from typing import Literal, Self

from pydantic import Field, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import (
    check_cancelled,
    report_progress,
    validate_operation_controls,
)
from trade_plan_monitor.backtest.daily_basis import HistoricalAdjustmentFactor, factors_for_request
from trade_plan_monitor.backtest.dataset import (
    DatasetItem,
    DatasetScope,
    LoopFrozenSymbolDay,
    exchange_for_symbol,
)
from trade_plan_monitor.backtest.loop_input import MAX_LOOP_RECORDS
from trade_plan_monitor.backtest.market_linkage_input import (
    LinkedIndexReplaySource,
    freeze_linked_index,
)
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import (
    MAX_SCHEDULED_ENTRIES,
    LoopEndBoundary,
    LoopSchedule,
    LoopTimestamp,
    ScheduledLoopSchedule,
)
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.domain.daily_plan_models import required_daily_observations
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan, condition_leaves
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends

LOOP_DATASET_VERSION = "monitor-loop-dataset-v1"


class LoopDatasetRequirements(ResearchValue):
    requires_minutes: bool
    requires_daily: bool
    daily_observations: int = Field(ge=0, le=500)
    minute_observations: int = Field(ge=0, le=501)


def loop_dataset_requirements(plan: UnifiedTradePlan) -> LoopDatasetRequirements:
    roots = [branch.condition for branch in plan.risk_branches if branch.condition is not None]
    roots.extend(rule.condition for rule in plan.alert_rules)
    for rule in plan.ordinary_rules:
        roots.append(rule.condition)
        reset = getattr(rule.independent_signal, "reset_condition", None)
        if reset is not None:
            roots.append(reset)
    leaves = [leaf for root in roots for leaf in condition_leaves(root)]
    identified = (*plan.ordinary_rules, *plan.alert_rules)
    daily = (
        bool(plan.risk_branches)
        or any(rule.confirmation.kind == "OFFICIAL_DAILY_CLOSE" for rule in identified)
        or any(leaf.type.startswith("DAILY_") for leaf in leaves)
    )
    minutes = any(rule.confirmation.kind == "COMPLETED_BAR_CLOSE" for rule in identified) or any(
        leaf.type.startswith("MINUTE_") for leaf in leaves
    )
    daily_count = max(
        (
            required_daily_observations(leaf, plan.monitoring.macd_min_observations)
            for leaf in leaves
            if leaf.type.startswith("DAILY_")
        ),
        default=1 if daily else 0,
    )
    if plan.schema_version in {6, 7, 8}:
        daily_count = max(daily_count, 21)
    minute_count = max(
        (leaf.window_bars + 1 for leaf in leaves if leaf.type == "MINUTE_VOLUME_TO_MEAN_GTE"),
        default=1 if minutes else 0,
    )
    return LoopDatasetRequirements(
        requires_minutes=minutes,
        requires_daily=daily,
        daily_observations=daily_count,
        minute_observations=minute_count,
    )


def closed_minute_ends(day: date, cutoff: datetime, *, is_open: bool) -> tuple[datetime, ...]:
    return tuple(end for end in expected_minute_ends(day, is_open=is_open) if end <= cutoff)


class LoopDatasetRequest(ResearchValue):
    scope: DatasetScope
    schedule: LoopSchedule
    boundary: LoopEndBoundary

    @model_validator(mode="after")
    def one_bound_plan(self) -> Self:
        if (
            self.scope.symbols != (self.schedule.symbol,)
            or self.scope.start != self.boundary.started_at.date()
            or self.scope.end != self.boundary.resolved_end_date
        ):
            raise ValueError("loop dataset scope must bind this one plan and frozen boundary")
        if self.schedule.select(self.boundary.started_at) is None:
            raise ValueError("loop dataset start has no reviewed plan authority")
        return self


class ScheduledLoopDatasetRequest(ResearchValue):
    scope: DatasetScope
    schedule: ScheduledLoopSchedule
    boundary: LoopEndBoundary

    @model_validator(mode="after")
    def bound(self):
        LoopDatasetRequest.one_bound_plan(self)
        if self.scope.start != self.schedule.entries[0].effective_trade_date:
            raise ValueError("scheduled dataset must start with its initial account version")
        return self


def relevant_schedule_entries(schedule, boundary):
    return tuple(row for row in schedule.entries if row.effective_trade_date <=
                 boundary.resolved_end_date and max(row.version.available_at, datetime.combine(
                     row.effective_trade_date, time.min, SHANGHAI,
                 )) <= boundary.evidence_cutoff)


def scheduled_dataset_requirements(schedule, boundary):
    values = tuple(loop_dataset_requirements(row.version.snapshot)
                   for row in relevant_schedule_entries(schedule, boundary))
    return LoopDatasetRequirements(
        requires_minutes=any(value.requires_minutes for value in values),
        requires_daily=any(value.requires_daily for value in values),
        daily_observations=max((value.daily_observations for value in values), default=0),
        minute_observations=max((value.minute_observations for value in values), default=0),
    )


class LoopMinuteReference(ResearchValue):
    artifact_hash: Sha256Hex
    bar_end: LoopTimestamp
    available_at: LoopTimestamp

    @model_validator(mode="after")
    def availability(self) -> Self:
        if self.available_at < self.bar_end:
            raise ValueError("minute availability precedes its close")
        return self


class LoopDailyReference(ResearchValue):
    item: DatasetItem
    available_at: LoopTimestamp


class LoopDaySelection(ResearchValue):
    trade_date: date
    calendar: DatasetItem
    state: Literal["COMPLETE", "PARTIAL", "CLOSED", "WARMUP"]
    minutes: tuple[LoopMinuteReference, ...] = Field(max_length=MAX_LOOP_RECORDS)
    limits: tuple[LoopDailyReference, ...] = Field(max_length=MAX_LOOP_RECORDS)
    daily: tuple[LoopDailyReference, ...] = Field(max_length=MAX_LOOP_RECORDS)


class LoopDatasetManifest(ResearchValue):
    linked_index_source: LinkedIndexReplaySource | None = Field(
        default=None, exclude_if=lambda value: value is None)
    schema_version: Literal["monitor-loop-dataset-v1"] = LOOP_DATASET_VERSION
    dataset_hash: Sha256Hex
    scope: DatasetScope
    boundary: LoopEndBoundary
    plan_version_id: StableIdentifier
    plan_hash: Sha256Hex
    requirements: LoopDatasetRequirements
    days: tuple[LoopDaySelection, ...]
    warmup_blockers: tuple[str, ...] = ()
    adjustment_factors: tuple[HistoricalAdjustmentFactor, ...] = Field(
        default=(), max_length=2500, exclude_if=lambda value: not value,
    )

    @classmethod
    def build(cls, **values) -> Self:
        domain = cls.model_fields["schema_version"].default
        identity = {"schema_version": domain, **values}
        digest = sha256(
            (domain + "\0" + canonical_json(identity)).encode()
        ).hexdigest()
        return cls(dataset_hash=digest, **identity)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if (
            len(self.scope.symbols) != 1
            or self.scope.start != self.boundary.started_at.date()
            or self.scope.end != self.boundary.resolved_end_date
        ):
            raise ValueError("loop manifest must bind one scope and cutoff")
        expected_dates = tuple(
            self.scope.warmup_start + timedelta(days=offset)
            for offset in range((self.scope.end - self.scope.warmup_start).days + 1)
        )
        if tuple(day.trade_date for day in self.days) != expected_dates:
            raise ValueError("loop manifest must contain every calendar date in order")
        count = 0
        for day in self.days:
            if (
                day.calendar.kind != "CALENDAR"
                or day.calendar.trade_date != day.trade_date
                or day.calendar.symbol is not None
                or day.calendar.natural_key
                != f"CALENDAR:{exchange_for_symbol(self.scope.symbols[0])}:{day.trade_date}"
            ):
                raise ValueError("loop calendar reference is invalid")
            if day.minutes != tuple(
                sorted(
                    day.minutes,
                    key=lambda item: (item.available_at, item.bar_end, item.artifact_hash),
                )
            ) or len({item.artifact_hash for item in day.minutes}) != len(day.minutes):
                raise ValueError("loop minutes must be unique and availability ordered")
            canonical_ends = set(expected_minute_ends(day.trade_date, is_open=True))
            for minute in day.minutes:
                if (
                    minute.bar_end not in canonical_ends
                    or minute.available_at > self.boundary.evidence_cutoff
                ):
                    raise ValueError("loop minute exceeds date or cutoff")
            for references, kind in ((day.limits, "LIMIT"), (day.daily, "DAILY")):
                if len({ref.item.artifact_hash for ref in references}) != len(
                    references
                ) or references != tuple(
                    sorted(
                        references, key=lambda item: (item.available_at, item.item.artifact_hash)
                    )
                ):
                    raise ValueError("daily revisions must be availability ordered")
                if any(
                    ref.item.kind != kind
                    or ref.item.symbol != self.scope.symbols[0]
                    or ref.item.trade_date != day.trade_date
                    or ref.item.natural_key != f"{kind}:{self.scope.symbols[0]}:{day.trade_date}"
                    or ref.available_at > self.boundary.evidence_cutoff
                    or kind == "DAILY"
                    and ref.available_at < datetime.combine(day.trade_date, time(15), SHANGHAI)
                    for ref in references
                ):
                    raise ValueError("daily reference exceeds identity or cutoff")
            if day.state == "CLOSED" and (day.minutes or day.limits or day.daily):
                raise ValueError("closed day cannot contain market evidence")
            if day.state == "WARMUP" and day.trade_date >= self.scope.start:
                raise ValueError("warmup day must precede event range")
            if day.state in ("PARTIAL", "COMPLETE"):
                expected = set(
                    closed_minute_ends(day.trade_date, self.boundary.evidence_cutoff, is_open=True)
                )
                if (
                    day.trade_date < self.scope.start
                    or {m.bar_end for m in day.minutes} != expected
                ):
                    raise ValueError("event day requires every closed interval")
                if expected and not day.limits:
                    raise ValueError("event day requires available daily limits")
                complete = len(expected) == 240 and bool(day.daily)
                if (day.state == "COMPLETE") != complete:
                    raise ValueError("complete day requires full minutes and official close")
            count += len(day.minutes) + len(day.daily) + len(day.limits)
        if count > MAX_LOOP_RECORDS:
            raise ValueError("LOOP_EVIDENCE_RECORD_LIMIT_EXCEEDED")
        factor_dates = tuple(value.trade_date for value in self.adjustment_factors)
        if factor_dates != tuple(sorted(set(factor_dates))) or any(
            value.symbol != self.scope.symbols[0]
            or not self.scope.warmup_start <= value.trade_date <= self.scope.end
            or value.available_at > self.boundary.evidence_cutoff
            for value in self.adjustment_factors
        ):
            raise ValueError('loop daily basis must bind the symbol, scope and cutoff')
        identity = self.model_dump(mode="python", exclude={"dataset_hash"})
        expected_hash = sha256(
            (self.schema_version + "\0" + canonical_json(identity)).encode()
        ).hexdigest()
        if self.dataset_hash != expected_hash:
            raise ValueError("loop dataset identity is invalid")
        return self


class LoopDatasetPlanBinding(ResearchValue):
    effective_trade_date: date
    version_id: StableIdentifier
    plan_hash: Sha256Hex


class ScheduledLoopDatasetManifest(ResearchValue):
    linked_index_source: LinkedIndexReplaySource | None = Field(
        default=None, exclude_if=lambda value: value is None)
    schema_version: Literal["monitor-loop-dataset-v2"] = "monitor-loop-dataset-v2"
    dataset_hash: Sha256Hex
    scope: DatasetScope
    boundary: LoopEndBoundary
    plan_bindings: tuple[LoopDatasetPlanBinding, ...] = Field(
        min_length=1, max_length=MAX_SCHEDULED_ENTRIES,
    )
    requirements: LoopDatasetRequirements
    days: tuple[LoopDaySelection, ...]
    warmup_blockers: tuple[str, ...] = ()
    adjustment_factors: tuple[HistoricalAdjustmentFactor, ...] = Field(
        default=(), max_length=2500, exclude_if=lambda value: not value,
    )

    @classmethod
    def build(cls, **values):
        return LoopDatasetManifest.build.__func__(cls, **values)

    @model_validator(mode="after")
    def bound(self):
        LoopDatasetManifest.bound(self)
        dates = tuple(binding.effective_trade_date for binding in self.plan_bindings)
        if dates != tuple(sorted(set(dates))) or dates[0] != self.scope.start or (
            dates[-1] > self.scope.end
        ):
            raise ValueError("scheduled dataset bindings must match ordered relevant days")
        return self


class LoopDatasetFreezeResult(ResearchValue):
    ready: bool
    manifest: LoopDatasetManifest | ScheduledLoopDatasetManifest | None
    blockers: tuple[str, ...]

    @model_validator(mode="after")
    def outcome(self) -> Self:
        if self.ready != (self.manifest is not None) or self.ready == bool(self.blockers):
            raise ValueError("loop dataset readiness must match its evidence outcome")
        return self


def _market_rows(connection, key, kind, *, cutoff=None):
    import json

    from trade_plan_monitor.backtest.market_store import _validated_market_artifact

    rows = connection.execute(
        "SELECT artifact_hash, kind, provider, contract_version, natural_key, content_json "
        "FROM market_artifact WHERE natural_key = ? AND kind = ? ORDER BY artifact_hash",
        (key, kind),
    )
    for row in rows:
        if cutoff is not None:
            received = datetime.fromisoformat(json.loads(row[5])["received_at"])
            if received > cutoff:
                continue
        yield row, _validated_market_artifact(row, expected_key=key, expected_kind=kind)


def _minute_from_row(row, profile):
    import json

    from trade_plan_monitor.backtest.market_store import _content_hash, _decode_minute_payload

    content = _decode_minute_payload(row[3])
    bar = MinuteBar.model_validate_json(content)
    expected = _content_hash(
        {
            "kind": "MINUTE_BAR",
            "provider": "TUSHARE",
            "contract_version": profile.value,
            "symbol": bar.symbol,
            "bar_end": bar.bar_end.isoformat(),
            "content": json.loads(content),
        }
    )
    if (
        str(row[0]) != expected
        or str(row[1]) != bar.symbol
        or str(row[2]) != bar.bar_end.isoformat()
    ):
        raise RuntimeError("loop minute artifact identity is invalid")
    return bar


def _available_minute_warmup(days, at):
    count = 0
    for day in reversed(days):
        if day.state == "CLOSED" or day.trade_date > at.date():
            continue
        present = {ref.bar_end for ref in day.minutes if ref.available_at < at}
        ends = expected_minute_ends(day.trade_date, is_open=True)
        for offset in range(len(ends) - 5, -1, -5):
            group = ends[offset:offset + 5]
            if group[-1] >= at:
                continue
            if not all(end in present for end in group):
                return count
            count += 1
    return count


def select_loop_dataset(
    connection, request: LoopDatasetRequest, *, cancellation_token=None, progress_callback=None,
    adjustment_factors=(),
):
    """Read a stable caller-owned SQLite snapshot; do not publish or mutate it."""
    import json

    from trade_plan_monitor.backtest.market_store import (
        _calendar_chain_blockers,
        _decode_minute_payload,
    )

    scheduled = isinstance(request, ScheduledLoopDatasetRequest)
    request_type = ScheduledLoopDatasetRequest if scheduled else LoopDatasetRequest
    request = request_type.model_validate(request.model_dump(mode="python"))
    scope, boundary = request.scope, request.boundary
    symbol, exchange = scope.symbols[0], exchange_for_symbol(scope.symbols[0])
    requirements = (scheduled_dataset_requirements(request.schedule, boundary) if scheduled else
                    loop_dataset_requirements(request.schedule.entries[0].version.snapshot))
    days, calendars, blockers = [], [], []
    warmup_daily, warmup_groups = set(), []
    total_records = 0
    day = scope.warmup_start
    while day <= scope.end:
        check_cancelled(cancellation_token, "FREEZE_VERIFY")
        key = f"CALENDAR:{exchange}:{day.isoformat()}"
        head = connection.execute(
            "SELECT artifact_hash FROM market_head WHERE natural_key = ?", (key,)
        ).fetchone()
        if head is None:
            blockers.append(f"LOOP_CALENDAR_MISSING:{day}")
            day += timedelta(days=1)
            continue
        rows = _market_rows(connection, key, "CALENDAR")
        content = next((content for row, content in rows if row[0] == head[0]), None)
        if content is None:
            raise RuntimeError("loop calendar head has no verified artifact")
        calendar = TradingDay.model_validate_json(content)
        if (
            calendar.exchange != exchange
            or calendar.cal_date != day
            or calendar.is_open
            and day.weekday() >= 5
        ):
            raise ValueError("loop calendar identity is invalid")
        calendars.append(calendar)
        calendar_item = DatasetItem(
            natural_key=key, artifact_hash=head[0], kind="CALENDAR", trade_date=day
        )
        expected = closed_minute_ends(day, boundary.evidence_cutoff, is_open=calendar.is_open)
        minute_refs, limit_refs, daily_refs, known_limits = [], [], [], []
        if calendar.is_open:
            for kind, model, target in (
                ("LIMIT", DailyLimit, limit_refs),
                ("DAILY", DailyBar, daily_refs),
            ):
                natural_key = f"{kind}:{symbol}:{day.isoformat()}"
                for row, payload in _market_rows(
                    connection, natural_key, kind, cutoff=boundary.evidence_cutoff
                ):
                    value = model.model_validate_json(payload)
                    if value.symbol != symbol or value.trade_date != day:
                        raise RuntimeError("loop daily artifact identity is invalid")
                    if (
                        kind == "DAILY"
                        and value.is_official
                        and value.received_at < (datetime.combine(day, time(15), SHANGHAI))
                    ):
                        raise RuntimeError("official close precedes session close")
                    if (
                        value.received_at > boundary.evidence_cutoff
                        or kind == "DAILY"
                        and (
                            not value.is_official
                            or datetime.combine(day, time(15), SHANGHAI) > boundary.evidence_cutoff
                        )
                    ):
                        continue
                    item = DatasetItem(
                        natural_key=natural_key,
                        artifact_hash=row[0],
                        kind=kind,
                        symbol=symbol,
                        trade_date=day,
                    )
                    target.append(LoopDailyReference(item=item, available_at=value.received_at))
                    if total_records + len(limit_refs) + len(daily_refs) > MAX_LOOP_RECORDS:
                        raise ValueError("LOOP_EVIDENCE_RECORD_LIMIT_EXCEEDED")
                    if kind == "LIMIT":
                        known_limits.append((value.received_at, row[0], value))
                    if kind == "DAILY" and value.received_at < boundary.started_at:
                        warmup_daily.add(day)
                target.sort(key=lambda item: (item.available_at, item.item.artifact_hash))
            start, end = (
                datetime.combine(day, time.min, SHANGHAI),
                min(datetime.combine(day, time.max, SHANGHAI), boundary.evidence_cutoff),
            )
            rows = connection.execute(
                "SELECT artifact_hash, symbol, bar_end, content_json FROM market_minute_artifact "
                "WHERE symbol = ? AND bar_end >= ? AND bar_end <= ? "
                "ORDER BY bar_end, artifact_hash",
                (symbol, start.isoformat(), end.isoformat()),
            )
            known_limits.sort(key=lambda value: (value[0], value[1]))
            warmup_present = set()
            for index, row in enumerate(rows):
                if index % 1000 == 0:
                    check_cancelled(cancellation_token, "FREEZE_VERIFY")
                raw = json.loads(_decode_minute_payload(row[3]))
                received_at = datetime.fromisoformat(raw["received_at"])
                if received_at > boundary.evidence_cutoff:
                    continue
                bar = _minute_from_row(row, scope.historical_profile)
                if bar.bar_end not in expected:
                    raise RuntimeError("loop minute is not a canonical closed interval")
                eligible_limits = [
                    value for available, _, value in known_limits if available <= bar.received_at
                ]
                if eligible_limits:
                    limit = eligible_limits[-1]
                    if bar.low_fen < limit.down_limit_fen or bar.high_fen > limit.up_limit_fen:
                        blockers.append(f"PRICE_OUTSIDE_DAILY_LIMIT:{symbol}:{day}")
                minute_refs.append(
                    LoopMinuteReference(
                        artifact_hash=row[0], bar_end=bar.bar_end, available_at=bar.received_at
                    )
                )
                if total_records + len(minute_refs) > MAX_LOOP_RECORDS:
                    raise ValueError("LOOP_EVIDENCE_RECORD_LIMIT_EXCEEDED")
                if bar.received_at < boundary.started_at:
                    warmup_present.add(bar.bar_end)
            canonical_ends = expected_minute_ends(day, is_open=True)
            for offset in range(0, len(canonical_ends), 5):
                group = canonical_ends[offset : offset + 5]
                if group[-1] < boundary.started_at:
                    warmup_groups.append(all(end in warmup_present for end in group))
            minute_refs.sort(key=lambda item: (item.available_at, item.bar_end, item.artifact_hash))
            if day >= scope.start:
                present = {ref.bar_end for ref in minute_refs}
                blockers.extend(
                    f"LOOP_MINUTE_NOT_AVAILABLE:{symbol}:{end.isoformat()}"
                    for end in expected
                    if end not in present
                )
                if expected and not limit_refs:
                    blockers.append(f"LOOP_DAILY_LIMIT_NOT_AVAILABLE:{symbol}:{day}")
                if (
                    requirements.requires_daily
                    and boundary.evidence_cutoff >= datetime.combine(day, time(15), SHANGHAI)
                    and not daily_refs
                ):
                    blockers.append(f"LOOP_OFFICIAL_CLOSE_NOT_AVAILABLE:{symbol}:{day}")
        state = (
            "CLOSED"
            if not calendar.is_open
            else "WARMUP"
            if day < scope.start
            else "COMPLETE"
            if len({ref.bar_end for ref in minute_refs}) == 240 and daily_refs
            else "PARTIAL"
        )
        days.append(
            LoopDaySelection(
                trade_date=day,
                calendar=calendar_item,
                state=state,
                minutes=tuple(minute_refs),
                limits=tuple(limit_refs),
                daily=tuple(daily_refs),
            )
        )
        total_records += len(minute_refs) + len(limit_refs) + len(daily_refs)
        if total_records > MAX_LOOP_RECORDS:
            raise ValueError("LOOP_EVIDENCE_RECORD_LIMIT_EXCEEDED")
        report_progress(
            progress_callback,
            phase="FREEZE_VERIFY",
            completed_units=len(days),
            total_units=(scope.end - scope.warmup_start).days + 1,
        )
        day += timedelta(days=1)
    blockers.extend(_calendar_chain_blockers(calendars))
    linked_source = None
    linked_plan = next((row.version.snapshot for row in request.schedule.entries
                        if row.version.snapshot.schema_version in {6, 7, 8}), None)
    if linked_plan is not None:
        try:
            linked_source = freeze_linked_index(connection, plan=linked_plan, calendar=calendars,
                started_at=boundary.started_at, cutoff=boundary.evidence_cutoff)
        except ValueError as error:
            blockers.append(str(error))
    if scheduled:
        for row in relevant_schedule_entries(request.schedule, boundary):
            needed = loop_dataset_requirements(row.version.snapshot)
            activation = max(boundary.started_at, row.version.available_at, datetime.combine(
                row.effective_trade_date, time.min, SHANGHAI,
            ))
            available = sum(any(ref.available_at < activation for ref in day.daily) for day in days)
            if available < needed.daily_observations:
                blockers.append("LOOP_DAILY_WARMUP_INSUFFICIENT:"
                                f"{row.version.version_id}:{available}:{needed.daily_observations}")
    elif len(warmup_daily) < requirements.daily_observations:
        blockers.append(
            f"LOOP_DAILY_WARMUP_INSUFFICIENT:{len(warmup_daily)}:{requirements.daily_observations}"
        )
    if not blockers:
        request.schedule.preflight(
            tuple(calendars),
            started_at=boundary.started_at,
            evidence_cutoff=boundary.evidence_cutoff,
        )
    if blockers:
        return LoopDatasetFreezeResult(
            ready=False, manifest=None, blockers=tuple(sorted(set(blockers))[:100])
        )
    warmup_blockers = ()
    warmup_count = 0
    for complete in reversed(warmup_groups):
        if not complete:
            break
        warmup_count += 1
    initial_requirements = (loop_dataset_requirements(request.schedule.entries[0].version.snapshot)
                            if scheduled else requirements)
    if warmup_count < initial_requirements.minute_observations:
        warmup_blockers = (
            "LOOP_INITIAL_MINUTE_WARMUP_INSUFFICIENT:"
            f"{warmup_count}:{initial_requirements.minute_observations}",
        )
    if scheduled:
        for row in relevant_schedule_entries(request.schedule, boundary)[1:]:
            activation = max(row.version.available_at, datetime.combine(
                row.effective_trade_date, time.min, SHANGHAI,
            ))
            needed = loop_dataset_requirements(row.version.snapshot).minute_observations
            available = _available_minute_warmup(days, activation)
            if available < needed:
                warmup_blockers += ("LOOP_VERSION_MINUTE_WARMUP_INSUFFICIENT:"
                                    f"{row.version.version_id}:{available}:{needed}",)
    version = request.schedule.entries[0].version
    binding = dict(plan_version_id=version.version_id, plan_hash=version.plan_hash)
    manifest_type = LoopDatasetManifest
    if scheduled:
        manifest_type = ScheduledLoopDatasetManifest
        binding = dict(plan_bindings=tuple(LoopDatasetPlanBinding(
            effective_trade_date=row.effective_trade_date,
            version_id=row.version.version_id, plan_hash=row.version.plan_hash,
        ) for row in relevant_schedule_entries(request.schedule, boundary)))
    manifest = manifest_type.build(
        scope=scope,
        boundary=boundary,
        **binding,
        requirements=requirements,
        days=tuple(days),
        warmup_blockers=warmup_blockers,
        **({'adjustment_factors': adjustment_factors} if adjustment_factors else {}),
        **({'linked_index_source': linked_source} if linked_source is not None else {}),
    )
    return LoopDatasetFreezeResult(ready=True, manifest=manifest, blockers=())


def read_loop_day(
    connection, manifest: LoopDatasetManifest, selected: LoopDaySelection
) -> LoopFrozenSymbolDay:
    from trade_plan_monitor.backtest.market_store import _validated_market_artifact

    def artifact(item):
        row = connection.execute(
            "SELECT artifact_hash, kind, provider, contract_version, natural_key, content_json "
            "FROM market_artifact WHERE artifact_hash = ?",
            (item.artifact_hash,),
        ).fetchone()
        if row is None:
            raise RuntimeError("frozen loop artifact is missing")
        return _validated_market_artifact(
            row, expected_key=item.natural_key, expected_kind=item.kind
        )

    calendar = TradingDay.model_validate_json(artifact(selected.calendar))
    minutes, limits, daily = [], [], []
    for ref in selected.minutes:
        row = connection.execute(
            "SELECT artifact_hash, symbol, bar_end, content_json FROM market_minute_artifact "
            "WHERE artifact_hash = ?",
            (ref.artifact_hash,),
        ).fetchone()
        if row is None:
            raise RuntimeError("frozen loop minute is missing")
        bar = _minute_from_row(row, manifest.scope.historical_profile)
        if bar.bar_end != ref.bar_end or bar.received_at != ref.available_at:
            raise RuntimeError("frozen loop minute reference is invalid")
        minutes.append(bar)
    for refs, model, target in (
        (selected.limits, DailyLimit, limits),
        (selected.daily, DailyBar, daily),
    ):
        for ref in refs:
            value = model.model_validate_json(artifact(ref.item))
            if value.received_at != ref.available_at:
                raise RuntimeError("frozen loop availability reference is invalid")
            target.append(value)
    return LoopFrozenSymbolDay(
        symbol=manifest.scope.symbols[0],
        trade_date=selected.trade_date,
        trading_day=calendar,
        evidence_cutoff=manifest.boundary.evidence_cutoff,
        state=selected.state,
        minutes=tuple(minutes),
        daily_limits=tuple(limits),
        daily_bars=tuple(daily),
    )


def freeze_scheduled_loop_dataset(
    market_store, request, *, cancellation_token=None, progress_callback=None,
):
    """Use the existing market snapshot with the distinct scheduled request codec."""
    if not isinstance(request, ScheduledLoopDatasetRequest):
        raise TypeError("request must be ScheduledLoopDatasetRequest")
    request = ScheduledLoopDatasetRequest.model_validate_json(request.model_dump_json())
    validate_operation_controls(cancellation_token, progress_callback)
    with market_store._connect() as connection:
        connection.execute("BEGIN")
        result = select_loop_dataset(connection, request, cancellation_token=cancellation_token,
                                     progress_callback=progress_callback,
                                     adjustment_factors=factors_for_request(market_store, request))
        check_cancelled(cancellation_token, "FREEZE_VERIFY")
        connection.commit()
    return result


@contextmanager
def open_frozen_scheduled_loop_dataset(market_store, manifest):
    """Stream existing immutable artifacts; do not rewrite the legacy market catalog."""
    if not isinstance(manifest, ScheduledLoopDatasetManifest):
        raise TypeError("manifest must be ScheduledLoopDatasetManifest")
    manifest = ScheduledLoopDatasetManifest.model_validate_json(manifest.model_dump_json())
    with market_store._connect() as connection:
        connection.execute("BEGIN")
        yield (read_loop_day(connection, manifest, day) for day in manifest.days)
