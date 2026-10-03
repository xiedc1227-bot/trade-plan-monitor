"""Frozen inputs captured on the runtime's owning loop before SQLite reads.

The provider is an internal composition boundary, never a request payload. An
unknown obligation set deliberately cannot certify readiness or current data.
"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from trade_plan_monitor.decision.models import (
    IntradayEvaluationTarget,
    OfficialCloseEvaluationTarget,
)
from trade_plan_monitor.runtime.progress import ProgressSnapshot


@dataclass(frozen=True, slots=True)
class ExplicitInputStamp:
    formula_version: str
    bars_fingerprint: str
    calendar_fingerprint: str
    inventory_fingerprint: str | None
    manual_risk_fingerprint: str | None
    rule_state_fingerprint: str


@dataclass(frozen=True, slots=True)
class LegacyInputStamp:
    formula_version: str
    minute_and_five_minute_fingerprint: str
    official_history_fingerprint: str
    calendar_fingerprint: str
    daily_limit_fingerprint: str | None
    inventory_fingerprint: str
    manual_risk_fingerprint: str | None
    risk_and_episode_fingerprint: str
    index_fingerprint: str | None
    close_history_fingerprint: str


@dataclass(frozen=True, slots=True)
class ConditionInputStamp:
    immutable_record_id: str
    calendar_start: date
    calendar_end: date
    calendar_fingerprint: str
    minute_fingerprint: str
    five_minute_fingerprint: str
    state_fingerprint: str


@dataclass(frozen=True, slots=True)
class PlanCompletionProof:
    runtime_generation: UUID
    configuration_revision: str
    symbol: str
    plan_family: str
    plan_version_id: str
    plan_hash: str
    activation_revision: int
    target: IntradayEvaluationTarget | OfficialCloseEvaluationTarget
    result_hash: str
    input_stamp: ExplicitInputStamp | LegacyInputStamp | ConditionInputStamp


@dataclass(frozen=True, slots=True)
class PlanReadAuthority:
    symbol: str
    plan_version_id: str
    plan_hash: str
    activation_revision: int
    plan_family: str
    target: IntradayEvaluationTarget | OfficialCloseEvaluationTarget | None = None
    required_minute_ends: tuple[datetime, ...] | None = None
    # Only an actual completed pipeline validation/persistence unit may publish
    # this proof, binding all applicable reference/calendar/close/state checks.
    completion: PlanCompletionProof | None = None
    evaluation_due: bool = False
    pending_reason: str = "AWAITING_FIRST_EVALUATION"
    recovery_pending: bool = False
    blocked: bool = False
    next_retry_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DependencyReadAuthority:
    """Actual desired operation/coverage facts frozen on the owner loop."""

    scope_key: str
    kind: str
    status: str
    reason_code: str | None
    target: IntradayEvaluationTarget | OfficialCloseEvaluationTarget | None = None
    data_cutoff: datetime | None = None
    next_retry_at: datetime | None = None
    required_count: int | None = None
    completed_count: int | None = None
    index_code: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeReadAuthority:
    """A missing value is unavailable authority, not authoritative owner absence."""

    token: object
    lifecycle: str
    progress: ProgressSnapshot | None
    health: object
    configuration_revision: str = ""
    plans: tuple[PlanReadAuthority, ...] = ()
    dependencies: tuple[object, ...] = ()
    owner_absent: bool = False
    standby_reason: str = "NO_ACTIVE_PLANS"
    block_reason: str | None = None

    @property
    def generation(self) -> UUID | None:
        return None if self.progress is None else self.progress.runtime_generation

    def __post_init__(self):
        if self.progress is None and not self.owner_absent:
            raise ValueError("Missing progress is not authoritative owner absence")
        if self.owner_absent and (self.progress is not None or self.lifecycle != "STOPPED"):
            raise ValueError("Owner absence cannot retain ownership")
        if len({plan.symbol for plan in self.plans}) != len(self.plans):
            raise ValueError("Duplicate plan authority")


def _fingerprint(domain, values):
    """Canonical local fingerprints include a fixed domain and typed source values."""
    import dataclasses
    import json
    from datetime import date
    from decimal import Decimal
    from enum import Enum
    from hashlib import sha256

    from pydantic import BaseModel

    def normalized(value):
        if isinstance(value, BaseModel):
            return normalized(value.model_dump(mode="python"))
        if dataclasses.is_dataclass(value):
            return normalized(dataclasses.asdict(value))
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, (Decimal, UUID)):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, (tuple, list)):
            return [normalized(item) for item in value]
        if isinstance(value, dict):
            return {str(key): normalized(item) for key, item in value.items()}
        return value

    document = json.dumps(
        normalized(values),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return sha256((domain + ":" + document).encode("utf-8")).hexdigest()


def _read_positions(session, now):
    from uuid import uuid4

    from trade_plan_monitor.state.events import MonitorEventLog
    from trade_plan_monitor.state.models import PositionInventoryState
    from trade_plan_monitor.state.repositories import PositionRepository

    class ReadOnlyPositions(PositionRepository):
        def _inventory_revision(self, symbol, *, lock=False):
            if lock:
                raise ValueError("Read-only inventory cannot acquire write admission")
            row = session.get(PositionInventoryState, symbol)
            return 0 if row is None else row.revision

    return ReadOnlyPositions(
        session,
        clock=lambda: now,
        id_factory=lambda: str(uuid4()),
        events=MonitorEventLog(session, clock=lambda: now),
    )


def capture_input_stamp(session, *, plan, result, now):
    """Re-read actual declared inputs in the caller's existing snapshot, without writes."""
    from datetime import timedelta
    from uuid import uuid4

    from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
    from trade_plan_monitor.runtime.explicit_service import (
        _contains_manual_risk,
        _manual_risk_value,
    )
    from trade_plan_monitor.state.explicit_rules import ExplicitDecisionRepository
    from trade_plan_monitor.state.repositories import (
        ManualEventRiskRepository,
        MarketHistoryRepository,
        MarketReferenceRepository,
    )

    history = MarketHistoryRepository(session)
    references = MarketReferenceRepository(session)
    positions = _read_positions(session, now)
    if type(plan) is not ExplicitTradePlan:
        return _legacy_input_stamp(session, plan, result, now, history, references, positions)
    target = result.target_bucket_end
    if result.evaluated_at > now:
        return None
    pending = [rule.condition_evidence for rule in result.rule_results]
    pending.extend(
        rule.safety_evidence for rule in result.rule_results if rule.safety_evidence is not None
    )
    while pending:
        evidence = pending.pop()
        if evidence.missing_inputs or evidence.outcome.value == "MISSING_INPUT":
            return None
        pending.extend(evidence.children)
    if any(
        any("UNKNOWN" in blocker or "INPUT_MISSING" in blocker for blocker in rule.blockers)
        for rule in result.rule_results
    ):
        return None
    formula = plan.monitoring.indicator_formula_version
    bars = history.list_five_minute(
        plan.symbol, start=target - timedelta(days=60), end=target, formula_version=formula
    )
    if not bars or bars[-1].bar_end != target:
        return None
    calendar = references.list_trading_days(
        plan.market, target.date() - timedelta(days=366), target.date()
    )
    if not any(day.cal_date == target.date() and day.is_open for day in calendar):
        return None
    inventory = None
    if result.inventory_revision is not None:
        inventory = positions.inventory_snapshot(
            plan.symbol, as_of_trade_date=target.date(), cutoff=target
        )
        if (
            inventory.status.value != "KNOWN"
            or inventory.inventory_revision != result.inventory_revision
        ):
            return None
    manual = None
    if any(_contains_manual_risk(rule.safety_conditions) for rule in plan.rules):
        manual = ManualEventRiskRepository(
            session, clock=lambda: now, id_factory=lambda: str(uuid4())
        ).get(plan.symbol)
        value, revision = _manual_risk_value(
            manual, plan_hash=result.plan_hash, trade_date=target.date(), cutoff=target
        )
        if value is None or revision != result.manual_event_risk_revision:
            return None
    states = ExplicitDecisionRepository(session).states(
        plan_hash=result.plan_hash,
        symbol=plan.symbol,
        activation_revision=result.activation_revision,
    )
    by_id = {state.rule_id: state for state in states}
    for rule in result.rule_results:
        transition = rule.state_transition
        if transition is not None:
            state = by_id.get(rule.rule_id)
            if (
                state is None
                or state.revision != transition.next_revision
                or (state.last_emitted_bucket_end != transition.last_emitted_bucket_end)
            ):
                return None
    return ExplicitInputStamp(
        formula,
        _fingerprint("explicit-bars-v1", bars),
        _fingerprint("explicit-calendar-v1", calendar),
        None if inventory is None else _fingerprint("explicit-inventory-v1", inventory),
        None if manual is None else _fingerprint("explicit-manual-v1", manual),
        _fingerprint("explicit-rule-state-v1", states),
    )


def _legacy_input_stamp(session, plan, result, now, history, references, positions):
    from datetime import date, time, timedelta

    from sqlalchemy import select

    from trade_plan_monitor.market_data.sessions import expected_minute_ends
    from trade_plan_monitor.market_index.requirements import plan_index_fact_requests
    from trade_plan_monitor.runtime.historical_close_evidence import LegacyHistoricalCloseReader
    from trade_plan_monitor.state.models import (
        ManualEventRisk,
        PendingOfficialClose,
        RiskState,
        ZoneEpisode,
    )
    from trade_plan_monitor.state.projections import ProjectionRepository

    snapshot = result.snapshot
    if snapshot.evaluated_at > now or not snapshot.data_health.required_data_complete:
        return None
    pending = list(snapshot.condition_evidence)
    while pending:
        item = pending.pop()
        if item.missing_inputs or item.outcome.value == "MISSING_INPUT":
            return None
        pending.extend(getattr(item, "children", ()))
    identity = result.evaluation_identity
    intraday = hasattr(identity, "bucket_end")
    day = identity.bucket_end.date() if intraday else identity.official_trade_date
    cutoff = identity.bucket_end if intraday else datetime.combine(day, time(15), now.tzinfo)
    formula = plan.monitoring.indicator_formula_version
    calendar = references.list_trading_days(plan.market, day - timedelta(days=366), day)
    if not any(item.cal_date == day and item.is_open for item in calendar):
        return None
    daily = tuple(
        bar
        for bar in history.list_daily_bars(
            plan.symbol, start=date.min, end=day - timedelta(days=1) if intraday else day
        )
        if bar.is_official
    )[-499 if intraday else -501 :]
    if not daily or (not intraday and daily[-1].trade_date != day):
        return None
    minutes, bars = (), ()
    if intraday:
        start = datetime.combine(day, time(9, 31), now.tzinfo)
        minutes = history.list_minutes(plan.symbol, start=start, end=cutoff)
        required = tuple(end for end in expected_minute_ends(day, is_open=True) if end <= cutoff)
        if tuple(bar.bar_end for bar in minutes) != required:
            return None
        bars = history.list_five_minute(
            plan.symbol, start=start, end=cutoff, formula_version=formula
        )
        if not bars or bars[-1].bar_end != cutoff:
            return None
    limits = tuple(item for item in references.list_daily_limits(day) if item.symbol == plan.symbol)
    lots = positions.list_open_lots(plan.symbol)
    openings = positions.list_opening_balances(plan.symbol)
    inventory = positions.inventory_snapshot(
        plan.symbol, as_of_trade_date=day, cutoff=snapshot.evaluated_at
    )
    if openings and inventory.status.value != "KNOWN":
        return None
    if sum(lot.remaining_qty for lot in lots) + sum(item.remaining_qty for item in openings) != (
        snapshot.position.total_quantity
    ):
        return None

    def row_values(row):
        return (
            None
            if row is None
            else {column.name: getattr(row, column.name) for column in row.__table__.columns}
        )

    risk = session.get(RiskState, plan.symbol)
    if risk is not None and (
        risk.plan_hash != snapshot.plan_hash
        or risk.revision != snapshot.risk.revision
        or risk.status != snapshot.risk.status.value
        or risk.breach_trade_date != snapshot.risk.breach_trade_date
        or risk.prior_close_fen != snapshot.risk.prior_close_fen
    ):
        return None
    episodes = session.scalars(
        select(ZoneEpisode)
        .where(ZoneEpisode.symbol == plan.symbol)
        .order_by(ZoneEpisode.id)
        .limit(257)
    ).all()
    if len(episodes) > 256:
        return None
    if snapshot.episode is not None:
        expected = snapshot.episode
        episode = next((row for row in episodes if row.id == expected.episode_id), None)
        if (
            episode is None
            or any(
                getattr(episode, name) != getattr(expected, name)
                for name in (
                    "symbol",
                    "plan_hash",
                    "episode_low_fen",
                    "bars_since_low",
                    "status",
                    "alerted_signal",
                )
            )
            or (
                datetime.fromisoformat(episode.started_at) != expected.started_at
                or datetime.fromisoformat(episode.last_processed_bucket_end)
                != expected.last_processed_bucket_end
            )
        ):
            return None
    manual = session.get(ManualEventRisk, plan.symbol)
    requested = plan_index_fact_requests(plan)
    index = None
    if requested:
        reference = snapshot.reference_market
        if reference is None:
            return None
        record = ProjectionRepository(session).get_market_index_snapshot(reference.snapshot_hash)
        if record is None or record.snapshot.completed_bucket_at != reference.data_at:
            return None
        index = (requested, record.snapshot)
    if (
        session.scalar(
            select(PendingOfficialClose).where(PendingOfficialClose.symbol == plan.symbol)
        )
        is not None
    ):
        return None
    missing = LegacyHistoricalCloseReader.missing_targets_in_session(session, plan.symbol, now)
    if missing != ():
        return None
    # Include every immutable official-close completion, not just the boolean
    # absence of pending work; changes invalidate the published proof.
    from trade_plan_monitor.state.models import EvaluationResult as ResultRow

    closes = session.scalars(
        select(ResultRow)
        .where(
            ResultRow.symbol == plan.symbol,
            ResultRow.plan_hash == snapshot.plan_hash,
            ResultRow.evaluation_kind == "OFFICIAL_CLOSE",
        )
        .order_by(ResultRow.target_value)
        .limit(513)
    ).all()
    if len(closes) > 512:
        return None
    return LegacyInputStamp(
        formula,
        _fingerprint("legacy-minute-five-v1", (minutes, bars)),
        _fingerprint("legacy-official-v1", daily),
        _fingerprint("legacy-calendar-v1", calendar),
        None if not limits else _fingerprint("legacy-limits-v1", limits),
        _fingerprint("legacy-inventory-v1", (lots, openings, inventory)),
        None if manual is None else _fingerprint("legacy-manual-v1", row_values(manual)),
        _fingerprint("legacy-state-v1", (row_values(risk), tuple(map(row_values, episodes)))),
        None if index is None else _fingerprint("legacy-index-v1", index),
        _fingerprint("legacy-close-v1", tuple(map(row_values, closes))),
    )


def capture_completion_proof(
    session, *, plan, result, runtime_generation, configuration_revision, now, consumed_inputs=None
):
    """Owner-only factory after a real COMMITTED unit; never called by a GET."""
    from trade_plan_monitor.domain.plan_hash import plan_sha256
    from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.state.explicit_rules import ExplicitDecisionRepository
    from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanVersion
    from trade_plan_monitor.state.projections import ProjectionRepository

    if isinstance(plan, UnifiedTradePlan):
        return capture_condition_completion_proof(
            session,
            plan=plan,
            result=result,
            runtime_generation=runtime_generation,
            configuration_revision=configuration_revision,
            now=now,
            consumed_inputs=consumed_inputs,
        )
    active = session.get(ActivePlan, plan.symbol)
    state = session.get(PlanActivationState, plan.symbol)
    version = None if active is None else session.get(PlanVersion, active.plan_version_id)
    if (
        active is None
        or state is None
        or version is None
        or state.revision != active.revision
        or state.plan_version_id != active.plan_version_id
        or version.plan_hash != plan_sha256(plan)
    ):
        return None
    explicit = type(plan) is ExplicitTradePlan
    if explicit:
        stored = ExplicitDecisionRepository(session).latest(
            symbol=plan.symbol, plan_hash=version.plan_hash, activation_revision=active.revision
        )
        target = IntradayEvaluationTarget(bucket_end=result.target_bucket_end)
    else:
        head = ProjectionRepository(session).get_decision_head(plan.symbol)
        stored = (
            None if head is None or head.activation_revision != active.revision else head.result
        )
        identity = result.evaluation_identity
        target = (
            IntradayEvaluationTarget(bucket_end=identity.bucket_end)
            if hasattr(identity, "bucket_end")
            else OfficialCloseEvaluationTarget(trade_date=identity.official_trade_date)
        )
    if stored is None or stored.result_hash != result.result_hash:
        return None
    stamp = capture_input_stamp(session, plan=plan, result=result, now=now)
    if stamp is None:
        return None
    if consumed_inputs is not None:
        if explicit:
            if consumed_inputs.activation_revision != active.revision:
                return None
            from trade_plan_monitor.decision.explicit_rules import ExplicitRuleStateSnapshot

            expected_states = {item.rule_id: item for item in consumed_inputs.rule_states}
            if len(expected_states) != len(consumed_inputs.rule_states):
                return None
            for rule in result.rule_results:
                transition = rule.state_transition
                if transition is None:
                    continue
                before = expected_states.get(rule.rule_id)
                if transition.expected_revision != (0 if before is None else before.revision):
                    return None
                expected_states[rule.rule_id] = ExplicitRuleStateSnapshot(
                    rule_id=rule.rule_id,
                    activation_revision=active.revision,
                    revision=transition.next_revision,
                    has_emitted=True,
                    last_emitted_bucket_end=transition.last_emitted_bucket_end,
                )
            if stamp.rule_state_fingerprint != _fingerprint(
                "explicit-rule-state-v1",
                tuple(sorted(expected_states.values(), key=lambda item: item.rule_id)),
            ):
                return None
            current_inventory = _read_positions(session, now).inventory_snapshot(
                plan.symbol, as_of_trade_date=target.bucket_end.date(), cutoff=target.bucket_end
            )
            if any(
                getattr(consumed_inputs.inventory, name) != getattr(current_inventory, name)
                for name in (
                    "status",
                    "total_qty",
                    "sellable_qty",
                    "inventory_revision",
                    "missing_reasons",
                )
            ):
                return None
            if consumed_inputs.manual_event_risk_revision != result.manual_event_risk_revision:
                return None
            if stamp.bars_fingerprint != _fingerprint("explicit-bars-v1", consumed_inputs.bars):
                return None
            if stamp.calendar_fingerprint != _fingerprint(
                "explicit-calendar-v1", consumed_inputs.trading_calendar
            ):
                return None
        else:
            if not _legacy_consumed_inputs_match(session, plan, result, consumed_inputs, now):
                return None
            if stamp.calendar_fingerprint != _fingerprint(
                "legacy-calendar-v1", consumed_inputs.trading_calendar
            ):
                return None
            consumed_daily = consumed_inputs.official_daily_bars
            if isinstance(target, OfficialCloseEvaluationTarget):
                # Official context keeps prior history and the current official
                # source bar separately. Both were consumed by the evaluator.
                source_bar = consumed_inputs.daily_indicator_snapshot.source_bar
                consumed_daily = (*consumed_daily, source_bar)
            if stamp.official_history_fingerprint != _fingerprint(
                "legacy-official-v1", consumed_daily
            ):
                return None
            if stamp.minute_and_five_minute_fingerprint != _fingerprint(
                "legacy-minute-five-v1",
                (consumed_inputs.current_day_minutes, consumed_inputs.complete_5m_bars),
            ):
                return None
    return PlanCompletionProof(
        runtime_generation,
        configuration_revision,
        plan.symbol,
        "EXPLICIT_RULES" if explicit else "LEGACY_LOW_BUY",
        active.plan_version_id,
        version.plan_hash,
        active.revision,
        target,
        result.result_hash,
        stamp,
    )


def _legacy_consumed_inputs_match(session, plan, result, inputs, now):
    """Bind post-commit proof to the facts the evaluator actually consumed.

    Risk/episode transitions intentionally change during the commit and are
    validated against the persisted result by capture_input_stamp instead.
    """
    from trade_plan_monitor.decision.models import PositionLotSnapshot
    from trade_plan_monitor.market_index.requirements import plan_index_fact_requests
    from trade_plan_monitor.runtime.production_context import _manual_event_risk_for_plan
    from trade_plan_monitor.state.projections import ProjectionRepository
    from trade_plan_monitor.state.repositories import (
        ManualEventRiskRepository,
        MarketReferenceRepository,
    )

    day = inputs.trade_date
    positions = _read_positions(session, now)
    lots = positions.list_open_lots(plan.symbol)
    openings = positions.list_opening_balances(plan.symbol)
    fresh_lots = tuple(
        PositionLotSnapshot(
            lot_id=lot.id,
            symbol=lot.symbol,
            bucket=lot.bucket,
            quantity=lot.quantity,
            remaining_quantity=lot.remaining_qty,
            acquired_trade_date=lot.acquired_trade_date,
            cost_fen=lot.cost_fen,
        )
        for lot in lots
    )
    if (
        inputs.positions != fresh_lots
        or inputs.opening_quantity != sum(item.remaining_qty for item in openings)
        or inputs.opening_sellable_quantity
        != sum(item.remaining_qty for item in openings if item.sellable_from <= day)
    ):
        return False
    if inputs.target.kind == "INTRADAY":
        limit = next(
            (
                item
                for item in MarketReferenceRepository(session).list_daily_limits(day)
                if item.symbol == plan.symbol
            ),
            None,
        )
        if inputs.daily_limit != limit:
            return False
        from uuid import uuid4

        manual = ManualEventRiskRepository(
            session, clock=lambda: now, id_factory=lambda: str(uuid4())
        ).get(plan.symbol)
        if inputs.manual_event_risk != _manual_event_risk_for_plan(
            manual, plan_hash=inputs.plan_hash, trade_date=day, cutoff=inputs.target_cutoff
        ):
            return False
    if plan_index_fact_requests(plan):
        reference = result.snapshot.reference_market
        stored = (
            None
            if reference is None
            else ProjectionRepository(session).get_market_index_snapshot(reference.snapshot_hash)
        )
        if stored is None or inputs.reference_market_snapshot != stored.snapshot:
            return False
    return True


def _condition_state(session, symbol):
    from sqlalchemy import select

    from trade_plan_monitor.state.daily_models import DailyRecord

    return tuple(
        (row.id, row.kind, row.revision, row.payload_json)
        for row in session.scalars(
            select(DailyRecord)
            .where(
                DailyRecord.symbol == symbol,
                DailyRecord.kind.in_(("POSITION", "FACT", "SIGNAL", "RISK")),
            )
            .order_by(DailyRecord.id)
        )
    )


def _condition_sources(session, snapshot, start, end):
    from trade_plan_monitor.state.repositories import (
        MarketHistoryRepository,
        MarketReferenceRepository,
    )

    symbol = snapshot["symbol"]
    market = {"SZ": "SZSE", "SH": "SSE", "BJ": "BSE"}[symbol[-2:]]
    calendar = MarketReferenceRepository(session).list_trading_days(market, start, end)
    history = MarketHistoryRepository(session)
    prefix = snapshot.get("minute_prefix", ())
    minutes = (
        ()
        if not prefix
        else history.list_minutes(
            symbol,
            start=datetime.fromisoformat(prefix[0]["bar_end"]),
            end=datetime.fromisoformat(prefix[-1]["bar_end"]),
        )
    )
    five = snapshot.get("five_minute_bars", ())
    bars = (
        ()
        if not five
        else history.list_five_minute(
            symbol,
            start=datetime.fromisoformat(five[0]["bar_end"]),
            end=datetime.fromisoformat(five[-1]["bar_end"]),
            formula_version="ta-v1",
        )
    )
    return calendar, minutes, bars


def condition_completion_matches(session, *, proof, snapshot, now):
    """Revalidate the committed current source proof in a read-only SQLite snapshot."""
    import json

    from trade_plan_monitor.state.daily_models import DailyRecord

    if proof is None or not isinstance(proof.input_stamp, ConditionInputStamp):
        return False
    stamp = proof.input_stamp
    result_hash = _fingerprint("condition-result-v1", snapshot)
    if proof.result_hash != result_hash:
        return False
    row = session.get(DailyRecord, stamp.immutable_record_id)
    if (
        row is None
        or row.kind != "EVALUATION"
        or row.symbol != proof.symbol
        or row.id.startswith("evaluation-head-")
        or json.loads(row.payload_json) != snapshot
    ):
        return False
    from trade_plan_monitor.runtime.daily_service import minute_source_current

    if snapshot.get("minute_target") and not minute_source_current(session, snapshot, now):
        return False
    if datetime.fromisoformat(snapshot["evaluated_at"]) > now:
        return False
    calendar, minutes, bars = _condition_sources(
        session, snapshot, stamp.calendar_start, stamp.calendar_end
    )
    return (
        stamp.calendar_fingerprint == _fingerprint("condition-calendar-v1", calendar)
        and stamp.minute_fingerprint == _fingerprint("condition-minute-v1", minutes)
        and stamp.five_minute_fingerprint == _fingerprint("condition-five-v1", bars)
        and stamp.state_fingerprint
        == _fingerprint("condition-state-v1", _condition_state(session, proof.symbol))
    )


def capture_condition_completion_proof(
    session, *, plan, result, runtime_generation, configuration_revision, now, consumed_inputs
):
    """Only a new committed schema5 evaluation with exact consumed sources installs proof."""
    import json

    from trade_plan_monitor.domain.plan_hash import plan_sha256
    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanVersion

    if (
        result.duplicate
        or consumed_inputs is None
        or result.snapshot.get("data_blockers")
        or not condition_status_eligible(session, plan=plan, now=now)
    ):
        return None
    snapshot = result.snapshot
    active = session.get(ActivePlan, plan.symbol)
    state = session.get(PlanActivationState, plan.symbol)
    version = None if active is None else session.get(PlanVersion, active.plan_version_id)
    head = session.get(DailyRecord, "evaluation-head-" + plan.symbol)
    immutable = (
        None if result.evaluation_id is None else session.get(DailyRecord, result.evaluation_id)
    )
    if (
        active is None
        or state is None
        or version is None
        or head is None
        or state.plan_version_id != active.plan_version_id
        or state.revision != active.revision
        or snapshot["activation_revision"] != active.revision
        or snapshot["plan_version_id"] != active.plan_version_id
        or version.plan_hash != plan_sha256(plan)
        or snapshot["runtime_generation"] != str(runtime_generation)
        or json.loads(head.payload_json) != snapshot
        or immutable is None
        or immutable.kind != "EVALUATION"
        or immutable.id.startswith("evaluation-head-")
        or json.loads(immutable.payload_json) != snapshot
    ):
        return None
    from trade_plan_monitor.runtime.daily_service import minute_source_current

    if snapshot.get("minute_target") and not minute_source_current(session, snapshot, now):
        return None
    calendar = consumed_inputs.trading_calendar
    if not calendar:
        return None
    start, end = calendar[0].cal_date, calendar[-1].cal_date
    fresh_calendar, minutes, bars = _condition_sources(session, snapshot, start, end)
    if (
        _fingerprint("condition-calendar-v1", fresh_calendar)
        != _fingerprint("condition-calendar-v1", calendar)
        or _fingerprint("condition-minute-v1", minutes)
        != _fingerprint("condition-minute-v1", consumed_inputs.minute_prefix)
        or _fingerprint("condition-five-v1", bars)
        != _fingerprint("condition-five-v1", consumed_inputs.five_minute_bars)
        or snapshot.get("daily_evidence")
        != (
            None
            if consumed_inputs.series is None
            else consumed_inputs.series.model_dump(mode="json")
        )
    ):
        return None
    minute = snapshot.get("minute_target")
    official = snapshot.get("official_trade_date")
    if minute is None and official is None:
        return None
    from datetime import date

    target = (
        IntradayEvaluationTarget(bucket_end=datetime.fromisoformat(minute))
        if minute
        else OfficialCloseEvaluationTarget(trade_date=date.fromisoformat(official))
    )
    stamp = ConditionInputStamp(
        immutable.id,
        start,
        end,
        _fingerprint("condition-calendar-v1", fresh_calendar),
        _fingerprint("condition-minute-v1", minutes),
        _fingerprint("condition-five-v1", bars),
        _fingerprint("condition-state-v1", _condition_state(session, plan.symbol)),
    )
    return PlanCompletionProof(
        runtime_generation,
        configuration_revision,
        plan.symbol,
        "CONDITION_PLAN",
        active.plan_version_id,
        version.plan_hash,
        active.revision,
        target,
        _fingerprint("condition-result-v1", snapshot),
        stamp,
    )


def condition_status_eligible(session, *, plan, now):
    """Respect the activation window, with the existing non-alert locked-risk extension."""
    from trade_plan_monitor.domain.plan_models import activation_is_eligible_on
    from trade_plan_monitor.runtime.daily_service import _alert_only
    from trade_plan_monitor.runtime.production import _daily_risk_monitoring_required

    return activation_is_eligible_on(plan.activation, now.date()) or (
        not _alert_only(plan) and _daily_risk_monitoring_required(session, plan, now)
    )


def condition_status_target(session, *, plan, now, proof=None):
    """Latest applicable completed condition target from the stored exchange calendar."""
    from datetime import time, timedelta

    from trade_plan_monitor.runtime.production import _unified_minute_required
    from trade_plan_monitor.runtime.recovery_targets import (
        completed_minute_ends,
        derive_recovery_target,
    )
    from trade_plan_monitor.state.repositories import MarketReferenceRepository

    if not condition_status_eligible(session, plan=plan, now=now):
        return None
    days = MarketReferenceRepository(session).list_trading_days(
        plan.market, now.date() - timedelta(days=366), now.date()
    )
    calendar = {day.cal_date: day.is_open for day in days}
    if now.date() not in calendar:
        return None
    minute = _unified_minute_required(plan)
    if minute:
        capture = derive_recovery_target(now=now, is_open_on=calendar.get)
        bucket = next(
            (end for end in reversed(completed_minute_ends(capture)) if end.minute % 5 == 0), None
        )
        if bucket is None:
            return None
        if (
            proof is not None
            and isinstance(proof.target, OfficialCloseEvaluationTarget)
            and bucket.time() == time(15)
            and bucket.date() == proof.target.trade_date
        ):
            return proof.target
        return IntradayEvaluationTarget(bucket_end=bucket)
    official = next(
        (
            day.cal_date
            for day in reversed(days)
            if day.is_open and datetime.combine(day.cal_date, time(15), now.tzinfo) <= now
        ),
        None,
    )
    return None if official is None else OfficialCloseEvaluationTarget(trade_date=official)
