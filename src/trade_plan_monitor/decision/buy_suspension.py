"""Pure bounded suspension checking; neither market truth nor BUY commit authority.

Runtime must bind inputs to committed SQL and invalidate coverage transactionally.
Engineering replay supplies the same bounded inputs in chronological order.
"""

from datetime import datetime, time, timedelta
from typing import Literal

from pydantic import Field, TypeAdapter, model_validator

from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier
from trade_plan_monitor.market_data.aggregation import (
    aggregate_five_minute_bar,
    five_minute_bucket_end,
)
from trade_plan_monitor.market_data.models import MinuteBar, ShanghaiDatetime, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends, session_for_minute_end
from trade_plan_monitor.market_index.canonical import canonical_value
from trade_plan_monitor.state.daily_state_models import (
    BuySuspensionCoverage,
    BuySuspensionPriceBasis,
    BuySuspensionTrigger,
    DailyBuySuspensionState,
    reviewed_fact_observation_source_hash,
)

InvalidationReason = Literal["PROOF_INVALIDATED", "GENERATION_CHANGED", "BATCH_BUDGET_EXHAUSTED"]
_IDENTIFIER = TypeAdapter(Identifier)
_INVALIDATIONS = {"PROOF_INVALIDATED", "GENERATION_CHANGED", "BATCH_BUDGET_EXHAUSTED"}


class BuySuspensionBatch(DailyValue):
    """One private same-day interval, at most 240 actual minute identities.

    A batch may end at the following midnight, permitting closed-day progress.
    The existing full-day HistoricalMinuteBatch contract remains unchanged.
    """

    start: ShanghaiDatetime
    through: ShanghaiDatetime
    minutes: tuple[MinuteBar, ...] = Field(max_length=240)
    calendar: TradingDay | None
    basis: BuySuspensionPriceBasis | None
    generation: Identifier

    @model_validator(mode="after")
    def finite_interval(self):
        following_midnight = datetime.combine(
            self.start.date() + timedelta(days=1), time(), self.start.tzinfo)
        if not self.start <= self.through <= following_midnight:
            raise ValueError("suspension batch must remain within one calendar date")
        if any(value.minute % 5 or value.second or value.microsecond
               for value in (self.start, self.through)):
            raise ValueError("suspension batch boundaries must be exact five-minute boundaries")
        return self


def transition_buy_suspension(
    state: DailyBuySuspensionState, *, target: datetime, evaluated_at: datetime,
    generation: str, batch: BuySuspensionBatch | None = None,
    invalidate: InvalidationReason | None = None,
) -> DailyBuySuspensionState:
    """Check one bounded batch or invalidate clear proof, preserving any latch.

    No cursor or supplied hash grants authority. The storage adapter owns proof
    freshness and commit fencing; this function only checks supplied content.
    """
    state = DailyBuySuspensionState.model_validate(state.model_dump(mode="python"))
    generation = _IDENTIFIER.validate_python(generation)
    if invalidate is not None and invalidate not in _INVALIDATIONS:
        raise ValueError("unsupported suspension invalidation")
    # Validate cutoffs before returning even an already latched state.
    if target < state.target or evaluated_at < state.evaluated_at:
        raise ValueError("suspension observation cannot move backwards")
    coverage = state.coverage
    reason = invalidate
    if coverage is not None and coverage.generation != generation:
        reason = "GENERATION_CHANGED"
    if reason in {"PROOF_INVALIDATED", "GENERATION_CHANGED"}:
        coverage = None

    def result(*, proof=coverage, trigger=state.trigger, blocker=reason):
        return state.model_copy(update={"target": target, "evaluated_at": evaluated_at,
            "coverage": proof, "trigger": trigger, "blocker": blocker})

    # A later correction can never erase the original valid observed breach.
    if state.trigger is not None:
        return result(blocker=None)
    if target < state.definition.effective_from:
        return result(proof=None, blocker="START_NOT_REACHED")
    if batch is None:
        if reason == "BATCH_BUDGET_EXHAUSTED" and (
                coverage is not None and coverage.through == target):
            reason = None
        return result(blocker=reason or (
            None if coverage is not None and coverage.through == target else "HISTORY_PENDING"))

    batch = BuySuspensionBatch.model_validate(batch.model_dump(mode="python"))
    if (batch.through > target or batch.start < state.definition.effective_from
            or batch.generation != generation):
        raise ValueError("suspension batch crosses its actual interval or process generation")
    # The state validator checks target <= evaluation time and its exact boundary.
    result(blocker=reason or (
        None if coverage is not None and coverage.through == target else "HISTORY_PENDING"))

    def blocked(blocker):
        # A failed recheck of an already covered interval invalidates that proof.
        # A missing subsequent batch retains its genuine earlier partial prefix.
        proof = coverage
        if proof is not None and (batch.start < proof.through or proof.through == target):
            proof = None
        return result(proof=proof, blocker=reason or blocker)

    ends = tuple(row.bar_end for row in batch.minutes)
    if len(set(ends)) != len(ends):
        raise ValueError("suspension minutes require unique identities")
    if any(row.symbol != state.symbol or row.bar_end > batch.through
           or row.bar_end.date() != batch.start.date()
           or session_for_minute_end(row.bar_end) is None for row in batch.minutes):
        raise ValueError("suspension minutes cross their actual symbol or interval")
    if any(row.received_at > evaluated_at for row in batch.minutes):
        return blocked("SOURCE_UNVERIFIED")

    calendar = batch.calendar
    if calendar is None:
        return blocked("CALENDAR_UNVERIFIED")
    exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[state.symbol[-2:]]
    if calendar.cal_date != batch.start.date() or calendar.exchange != exchange:
        raise ValueError("suspension calendar crosses its actual date or exchange")
    if calendar.is_open and calendar.cal_date.weekday() >= 5:
        return blocked("CALENDAR_UNVERIFIED")
    if not calendar.is_open and batch.minutes:
        return blocked("CALENDAR_UNVERIFIED")

    # Enumerating a single date is bounded to 240 minute identities. No missing
    # session or holiday is skipped merely because no bar was returned.
    expected = tuple(end for end in expected_minute_ends(calendar.cal_date,
                     is_open=calendar.is_open)
        if batch.start < five_minute_bucket_end(end) <= batch.through
        and five_minute_bucket_end(end) - timedelta(minutes=5)
        >= state.definition.effective_from)
    basis = batch.basis
    if expected:
        if basis is None or not basis.comparable or basis.verified_at > evaluated_at:
            return blocked("PRICE_BASIS_UNVERIFIED")
        if basis.trade_date != calendar.cal_date:
            raise ValueError("suspension basis crosses its actual source date")
        # A later actual anchor date with the same actual factor preserves price
        # comparability. Factor/content revisions still require SQL invalidation.
        if (coverage is not None and coverage.anchor_factor is not None
                and coverage.anchor_factor != basis.anchor_factor):
            coverage, reason = None, "PROOF_INVALIDATED"

    expected_set = set(expected)
    source = {row.bar_end: row for row in batch.minutes if row.bar_end in expected_set}
    for end in sorted({five_minute_bucket_end(value) for value in source}):
        minutes = tuple(source[key] for key in sorted(source)
                        if five_minute_bucket_end(key) == end)
        bar = aggregate_five_minute_bar(minutes, bucket_end=end, is_open=calendar.is_open)
        if bar is not None and bar.close_fen < state.definition.condition.price_fen:
            trigger = BuySuspensionTrigger(bar_end=end, close_fen=bar.close_fen,
                source_hash=reviewed_fact_observation_source_hash(minutes, bar),
                basis=basis, observed_at=evaluated_at)
            return result(proof=coverage, trigger=trigger, blocker=None)

    cursor = state.definition.effective_from if coverage is None else coverage.through
    if tuple(sorted(source)) != expected:
        return blocked("MINUTE_GAP")
    if coverage is not None and batch.through <= cursor:
        return result(proof=coverage, blocker=None if cursor == target else "HISTORY_PENDING")
    if batch.start != cursor:
        return result(proof=coverage, blocker=reason or "MINUTE_GAP")

    content_hash = daily_hash("buy-suspension-coverage-v1", canonical_value({
        "definition_hash": state.definition_hash,
        "previous_hash": None if coverage is None else coverage.content_hash,
        "start": batch.start, "through": batch.through, "calendar": calendar,
        "basis": basis if expected else None, "generation": generation,
        "minutes": [source[key].model_dump(mode="python", exclude={"received_at"})
                    for key in expected],
    }))
    proof = BuySuspensionCoverage(through=batch.through, content_hash=content_hash,
        anchor_date=basis.anchor_date if expected else (
            None if coverage is None else coverage.anchor_date),
        anchor_factor=basis.anchor_factor if expected else (
            None if coverage is None else coverage.anchor_factor), generation=generation)
    return result(proof=proof, blocker=None if batch.through == target else "HISTORY_PENDING")
