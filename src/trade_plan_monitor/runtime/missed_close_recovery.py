"""Read-only, bounded discovery of legacy official-close occurrence obligations.

PROVEN attributes a committed occurrence; even a BLOCKED_DATA result can qualify.
It never proves historical business state complete, replay readiness or permission
to send. There is no persistence adapter or scheduler integration in this module.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from trade_plan_monitor.decision.models import EvaluationResult, OfficialCloseEvaluationIdentity
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan, activation_is_eligible_on
from trade_plan_monitor.domain.plan_validation import ALL_MARKET_EVIDENCE, validate_trade_plan
from trade_plan_monitor.market_data.models import ShanghaiDatetime
from trade_plan_monitor.market_data.sessions import SHANGHAI
from trade_plan_monitor.runtime.scheduler import DEFAULT_OFFICIAL_CLOSE_ATTEMPTS


class _Value(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class MissedCloseScope(_Value):
    """One caller-certified actual activation and synchronous observation."""

    plan: TradePlan
    plan_version_id: str = Field(min_length=1, max_length=100)
    activation_revision: int = Field(ge=1)
    activated_at: ShanghaiDatetime
    observed_at: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        plan = TradePlan.model_validate(self.plan.model_dump(mode="python", round_trip=True))
        if not validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE).can_save:
            raise ValueError("plan must pass cross-field semantic validation")
        if self.activated_at > self.observed_at:
            raise ValueError("activation cannot follow observation")
        return self


class CompletionStatus(StrEnum):
    ABSENT = "ABSENT"
    PROVEN = "PROVEN"
    UNKNOWN = "UNKNOWN"


class OfficialCloseCompletion(_Value):
    """An adapter's exact-scope read, never proof manufactured from a hash lookup.

    ABSENT certifies no occurrence or conflicting existing identity claim. Any
    hash-only claim or uncertain attribution must be UNKNOWN. For PROVEN the
    adapter must certify committed publication AND actual activation provenance
    with committed_publication=True; full result validation alone cannot prove DB
    commit/activation attribution. None from the adapter also means UNKNOWN.
    """

    identity: OfficialCloseEvaluationIdentity
    plan_version_id: str = Field(min_length=1, max_length=100)
    activation_revision: int = Field(ge=1)
    activated_at: ShanghaiDatetime
    observed_at: ShanghaiDatetime
    status: CompletionStatus
    result: EvaluationResult | None = None
    committed_publication: bool = False


@dataclass(frozen=True)
class MissedCloseCandidate:
    identity: OfficialCloseEvaluationIdentity
    source_cutoff: datetime
    status: CompletionStatus
    reason: str
    causal_history_gap: bool


@dataclass(frozen=True)
class MissedCloseWindow:
    """Only this calendar window was inspected; no global completion assertion.

    next_window_start continues enumeration only. Cross-window causal history,
    absent obligations and unknowns must be retained and checked by the caller.
    No continuation cursor clears earlier gaps or makes any candidate replayable.
    """

    scope: MissedCloseScope
    window_start: date
    window_end: date
    candidates: tuple[MissedCloseCandidate, ...]
    next_window_start: date | None


def discover_missed_closes(
    *,
    scope: MissedCloseScope,
    is_open_on: Callable[[date], bool | None],
    completion_on: Callable[[OfficialCloseEvaluationIdentity], OfficialCloseCompletion | None],
    window_start: date | None = None,
    max_calendar_days: int = 32,
) -> MissedCloseWindow:
    """Inspect at most 32 dates and 32 completion reads, preserving later rows.

    Source callbacks must be read-only; their storage/programming failures propagate.
    No weekday inference, CLOSE_PENDING prerequisite, evaluator or provider call.
    A same-day obligation is due at the scheduler's first official-close attempt.
    """

    if not isinstance(scope, MissedCloseScope):
        raise TypeError("scope must be a MissedCloseScope")
    scope = MissedCloseScope.model_validate(scope.model_dump(mode="python", round_trip=True))
    if type(max_calendar_days) is not int or not 1 <= max_calendar_days <= 32:
        raise ValueError("max_calendar_days must be an integer between 1 and 32")
    if not callable(is_open_on) or not callable(completion_on):
        raise TypeError("discovery sources must be callable")
    start = scope.activated_at.date() if window_start is None else window_start
    today = scope.observed_at.date()
    if type(start) is not date:
        raise TypeError("window_start must be a date")
    if not scope.activated_at.date() <= start <= today:
        raise ValueError("window_start must lie within observed activation history")
    days = min(max_calendar_days, (today - start).days + 1)
    end = start + timedelta(days=days - 1)
    digest = plan_sha256(scope.plan)
    candidates = []
    earlier_absent = earlier_unknown = False
    for offset in range(days):
        day = start + timedelta(days=offset)
        cutoff = datetime.combine(day, time(15), SHANGHAI)
        if (
            scope.activated_at > cutoff
            or not activation_is_eligible_on(scope.plan.activation, day)
            or (day == today and scope.observed_at.time() < DEFAULT_OFFICIAL_CLOSE_ATTEMPTS[0])
        ):
            continue
        is_open = is_open_on(day)
        if is_open is False:
            continue
        identity = OfficialCloseEvaluationIdentity(
            plan_hash=digest, symbol=scope.plan.symbol, official_trade_date=day,
            formula_version=scope.plan.monitoring.indicator_formula_version,
        )
        if is_open is not True:
            status, reason = CompletionStatus.UNKNOWN, "calendar_unknown"
        else:
            status, reason = _completion_status(scope, identity, cutoff, completion_on(identity))
        gap = (earlier_absent and status is not CompletionStatus.ABSENT) or (
            earlier_unknown and status is CompletionStatus.PROVEN
        )
        candidates.append(MissedCloseCandidate(identity, cutoff, status, reason, gap))
        earlier_absent |= status is CompletionStatus.ABSENT
        earlier_unknown |= status is CompletionStatus.UNKNOWN
    return MissedCloseWindow(
        scope, start, end, tuple(candidates), end + timedelta(days=1) if end < today else None,
    )


def _completion_status(
    scope: MissedCloseScope,
    identity: OfficialCloseEvaluationIdentity,
    cutoff: datetime,
    evidence: OfficialCloseCompletion | None,
) -> tuple[CompletionStatus, str]:
    if evidence is None:
        return CompletionStatus.UNKNOWN, "completion_unknown"
    if not isinstance(evidence, OfficialCloseCompletion):
        raise TypeError("completion source must return typed evidence or None")
    try:
        evidence = OfficialCloseCompletion.model_validate(
            evidence.model_dump(mode="python", round_trip=True),
        )
    except ValidationError:
        return CompletionStatus.UNKNOWN, "invalid_completion_evidence"
    if (
        evidence.identity != identity
        or evidence.plan_version_id != scope.plan_version_id
        or evidence.activation_revision != scope.activation_revision
        or evidence.activated_at != scope.activated_at
        or evidence.observed_at != scope.observed_at
    ):
        return CompletionStatus.UNKNOWN, "completion_scope_mismatch"
    if evidence.status is CompletionStatus.ABSENT:
        if evidence.result is not None or evidence.committed_publication:
            return CompletionStatus.UNKNOWN, "conflicting_absence_evidence"
        return CompletionStatus.ABSENT, "no_committed_occurrence"
    if evidence.status is CompletionStatus.UNKNOWN:
        return CompletionStatus.UNKNOWN, "completion_unknown"
    result = evidence.result
    if not evidence.committed_publication or result is None:
        return CompletionStatus.UNKNOWN, "unproven_publication"
    if (
        result.evaluation_identity != identity
        or result.snapshot.plan_id != scope.plan.plan_id
        or result.snapshot.plan_version != scope.plan.version
        or not cutoff <= result.snapshot.evaluated_at <= scope.observed_at
        or result.snapshot.market_data_at not in (None, cutoff)
    ):
        return CompletionStatus.UNKNOWN, "result_scope_mismatch"
    return CompletionStatus.PROVEN, "committed_occurrence_only"
