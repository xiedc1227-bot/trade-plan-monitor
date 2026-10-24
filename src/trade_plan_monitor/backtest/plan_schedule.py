"""Frozen research time boundaries and one immutable plan's activation."""

from datetime import date, datetime, time, timedelta
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, field_validator, model_validator

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.research_input import (
    ResearchReview,
    ResearchTimestamp,
    ResearchValue,
)
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.domain.daily_plan_models import Identifier, Text, WholeQty
from trade_plan_monitor.domain.market_exception_models import MarketExceptionTradePlan
from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.models import TradingDay

MAX_SCHEDULE_ENTRIES = 1
MAX_PLAN_SOURCE_HASHES = 256
MAX_SCHEDULED_ENTRIES = 256


def require_loop_timestamp(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(hours=8):
        raise ValueError("loop timestamps require explicit +08:00")
    return value.astimezone(SHANGHAI)


LoopTimestamp = Annotated[ResearchTimestamp, AfterValidator(require_loop_timestamp)]


class LoopEndBoundary(ResearchValue):
    """Resolve only within submission reservation; later readers use stored values."""

    started_at: LoopTimestamp
    submitted_at: LoopTimestamp
    requested_end_date: date | None
    resolved_end_date: date
    origin: Literal["EXPLICIT", "DEFAULTED"]
    evidence_cutoff: LoopTimestamp

    @classmethod
    def resolve(
        cls,
        *,
        started_at: datetime,
        submitted_at: datetime,
        end_date: date | None = None,
    ) -> Self:
        if submitted_at.tzinfo is None or submitted_at.utcoffset() is None:
            raise ValueError("submission clock must be timezone-aware")
        submitted_at = submitted_at.astimezone(SHANGHAI)
        resolved = end_date if end_date is not None else submitted_at.date()
        cutoff = (
            submitted_at
            if resolved == submitted_at.date()
            else datetime.combine(resolved, time.max, SHANGHAI)
        )
        return cls(
            started_at=started_at,
            submitted_at=submitted_at,
            requested_end_date=end_date,
            resolved_end_date=resolved,
            origin="DEFAULTED" if end_date is None else "EXPLICIT",
            evidence_cutoff=cutoff,
        )

    @model_validator(mode="after")
    def coherent(self) -> Self:
        resolved = self.requested_end_date or self.submitted_at.date()
        if not self.started_at.date() <= resolved <= self.submitted_at.date():
            raise ValueError("end date must be between start and submission dates")
        cutoff = (
            self.submitted_at
            if resolved == self.submitted_at.date()
            else datetime.combine(resolved, time.max, SHANGHAI)
        )
        if self.started_at > cutoff:
            raise ValueError("start follows the frozen evidence cutoff")
        if self.resolved_end_date != resolved or self.evidence_cutoff != cutoff:
            raise ValueError("frozen end/cutoff does not match submission resolution")
        if self.origin != ("DEFAULTED" if self.requested_end_date is None else "EXPLICIT"):
            raise ValueError("frozen end origin does not match requested date")
        return self


class LoopPlanReview(ResearchReview):
    """Explicit content approval also binds the original sources and evidence."""

    source_hashes: tuple[Sha256Hex, ...] = Field(min_length=1, max_length=MAX_PLAN_SOURCE_HASHES)
    evidence_hash: Sha256Hex


class LoopPlanVersion(ResearchValue):
    """Reviewed immutable snapshot; availability is the declared research timeline."""

    version_id: StableIdentifier
    plan_hash: Sha256Hex
    snapshot: MarketExceptionTradePlan | MarketLinkedTradePlan | UnifiedTradePlan
    source_hashes: tuple[Sha256Hex, ...] = Field(min_length=1, max_length=MAX_PLAN_SOURCE_HASHES)
    evidence_hash: Sha256Hex
    authored_at: LoopTimestamp | None = None
    authored_date: date | None = None
    available_at: LoopTimestamp
    information_cutoff: LoopTimestamp
    review: LoopPlanReview

    @model_validator(mode="after")
    def bound(self) -> Self:
        if self.plan_hash != plan_sha256(self.snapshot):
            raise ValueError("plan hash does not match the immutable snapshot")
        if self.review.content_hash != daily_plan_content_sha256(self.snapshot):
            raise ValueError("review content hash does not match the snapshot")
        if (self.review.source_hashes, self.review.evidence_hash) != (
            self.source_hashes,
            self.evidence_hash,
        ):
            raise ValueError("review does not match the frozen sources/evidence")
        if len(set(self.source_hashes)) != len(self.source_hashes):
            raise ValueError("source hashes must be unique")
        if self.authored_at is not None and self.authored_date not in (
            None,
            self.authored_at.date(),
        ):
            raise ValueError("authoring date and timestamp disagree")
        if self.information_cutoff > self.available_at:
            raise ValueError("future source evidence cannot precede research availability")
        return self

    @property
    def retrospective(self) -> bool:
        if self.authored_at is not None:
            return self.authored_at > self.available_at
        return self.authored_date is not None and self.authored_date > self.available_at.date()

    def permits_date(self, day: date) -> bool:
        """Scheduling cannot widen the plan's activation envelope or rule validity."""
        activation = self.snapshot.activation
        if activation.mode == "TRADING_DAY":
            return day == activation.trading_day
        if activation.mode == "DATE_RANGE":
            return activation.start_date <= day <= activation.end_date
        return True


class LoopScheduleEntry(ResearchValue):
    effective_trade_date: date
    version: LoopPlanVersion

    @model_validator(mode="after")
    def permitted(self) -> Self:
        if not self.version.permits_date(self.effective_trade_date):
            raise ValueError("schedule row is outside plan activation")
        return self


class LoopPlanSelection(ResearchValue):
    version: LoopPlanVersion
    effective_trade_date: date
    activated_at: LoopTimestamp
    continued: bool

    @property
    def authority_id(self) -> str:
        # Dataset revisions and run policies do not rename the frozen activation.
        payload = dict(
            plan_hash=self.version.plan_hash,
            activated_at=self.activated_at,
            source_hashes=self.version.source_hashes,
            evidence_hash=self.version.evidence_hash,
        )
        return sha256(
            ("monitor-loop-authority-v1\0" + canonical_json(payload)).encode()
        ).hexdigest()


class LoopSchedule(ResearchValue):
    entries: tuple[LoopScheduleEntry, ...] = Field(min_length=1, max_length=MAX_SCHEDULE_ENTRIES)

    @model_validator(mode="after")
    def available(self) -> Self:
        row = self.entries[0]
        if row.version.available_at.date() > row.effective_trade_date:
            raise ValueError("plan availability follows its effective date")
        return self

    @property
    def symbol(self) -> str:
        return self.entries[0].version.snapshot.symbol

    def select(self, at: datetime) -> LoopPlanSelection | None:
        """Continue the same activation while its frozen authority remains valid."""
        at = require_loop_timestamp(at)
        row = self.entries[0]
        boundary = datetime.combine(row.effective_trade_date, time.min, SHANGHAI)
        activated_at = max(boundary, row.version.available_at)
        if at < activated_at or not row.version.permits_date(at.date()):
            return None
        return LoopPlanSelection(
            version=row.version,
            effective_trade_date=row.effective_trade_date,
            activated_at=activated_at,
            continued=at.date() > row.effective_trade_date,
        )

    def preflight(
        self,
        calendar: tuple[TradingDay, ...],
        *,
        started_at: datetime,
        evidence_cutoff: datetime,
    ) -> None:
        """Reject closed/unknown dates using supplied evidence, without provider access."""
        started_at = require_loop_timestamp(started_at)
        evidence_cutoff = require_loop_timestamp(evidence_cutoff)
        if started_at > evidence_cutoff:
            raise ValueError("start follows evidence cutoff")
        exchange = self.entries[0].version.snapshot.market
        days = {day.cal_date: day for day in calendar if day.exchange == exchange}
        if len(days) != sum(day.exchange == exchange for day in calendar):
            raise ValueError("duplicate calendar dates")
        for row in self.entries:
            day = days.get(row.effective_trade_date)
            if day is None or not day.is_open:
                raise ValueError("effective date must be a known trading day")
        if self.select(started_at) is None:
            raise ValueError("uncovered run start")


class LoopAccountContext(ResearchValue):
    """Reviewed source assertions to compare with the ledger, never opening inventory."""

    core_qty: WholeQty | None = None
    tactical_qty: WholeQty | None = None
    dependent_rule_ids: tuple[Identifier, ...] = Field(default=(), max_length=2)
    evidence: Text

    @model_validator(mode="after")
    def explicit(self) -> Self:
        if self.core_qty is None and self.tactical_qty is None:
            raise ValueError("account context requires an explicit quantity")
        if len(set(self.dependent_rule_ids)) != len(self.dependent_rule_ids):
            raise ValueError("account-dependent rule IDs must be unique")
        return self


class ScheduledPlanVersion(ResearchValue):
    # Distinct models prevent v1 serializers from silently dropping v2 account context.
    version_id: StableIdentifier
    plan_hash: Sha256Hex
    snapshot: MarketExceptionTradePlan | MarketLinkedTradePlan | UnifiedTradePlan
    source_hashes: tuple[Sha256Hex, ...] = Field(min_length=1, max_length=MAX_PLAN_SOURCE_HASHES)
    evidence_hash: Sha256Hex
    authored_at: LoopTimestamp | None = None
    authored_date: date | None = None
    available_at: LoopTimestamp
    information_cutoff: LoopTimestamp
    review: LoopPlanReview
    account_context: LoopAccountContext | None = None

    @model_validator(mode="after")
    def bound(self) -> Self:
        return LoopPlanVersion.bound(self)

    @property
    def retrospective(self) -> bool:
        return LoopPlanVersion.retrospective.fget(self)

    def permits_date(self, day: date) -> bool:
        return LoopPlanVersion.permits_date(self, day)

    @model_validator(mode="after")
    def context_bound(self) -> Self:
        if self.account_context is not None:
            rules = {rule.rule_id for rule in self.snapshot.ordinary_rules}
            if not set(self.account_context.dependent_rule_ids) <= rules:
                raise ValueError("account context names an absent ordinary rule")
        return self

    @property
    def causal_hash(self) -> str:
        # Review authorizes replay today; it is not a fact available in historical time.
        value = self.model_dump(mode="python", exclude={"review"})
        return sha256(("monitor-loop-version-v2\0" + canonical_json(value)).encode()).hexdigest()


class ScheduledScheduleEntry(ResearchValue):
    effective_trade_date: date
    version: ScheduledPlanVersion

    @model_validator(mode="after")
    def permitted(self) -> Self:
        return LoopScheduleEntry.permitted(self)


class ScheduledLoopPlanSelection(ResearchValue):
    version: ScheduledPlanVersion
    effective_trade_date: date
    activated_at: LoopTimestamp
    continued: bool

    @property
    def authority_id(self) -> str:
        value = {"version": self.version.causal_hash, "activated_at": self.activated_at}
        return sha256(("monitor-loop-authority-v2\0" + canonical_json(value)).encode()).hexdigest()


class ScheduledLoopSchedule(ResearchValue):
    """Opt-in daily chain; the original LoopSchedule codec remains single-version."""

    entries: tuple[ScheduledScheduleEntry, ...] = Field(
        min_length=1, max_length=MAX_SCHEDULED_ENTRIES,
    )

    @property
    def symbol(self) -> str:
        return self.entries[0].version.snapshot.symbol

    @field_validator("entries")
    @classmethod
    def ordered(cls, value):
        return tuple(sorted(value, key=lambda row: row.effective_trade_date))

    @model_validator(mode="after")
    def available(self) -> Self:
        dates, versions = set(), {}
        first = self.entries[0]
        for index, row in enumerate(self.entries):
            version = row.version
            if row.effective_trade_date in dates:
                raise ValueError("duplicate effective trading day")
            dates.add(row.effective_trade_date)
            if (version.snapshot.symbol, version.snapshot.market) != (
                first.version.snapshot.symbol, first.version.snapshot.market,
            ):
                raise ValueError("scheduled versions require one symbol and market")
            if version.version_id in versions and versions[version.version_id] != version:
                raise ValueError("version ID is bound to different immutable content")
            versions[version.version_id] = version
            if version.available_at.date() > row.effective_trade_date:
                raise ValueError("plan availability follows its effective date")
            if index and version.available_at > datetime.combine(
                row.effective_trade_date, time(9, 30), SHANGHAI,
            ):
                raise ValueError("successor availability follows the exchange session opening")
        return self

    def select(self, at: datetime) -> ScheduledLoopPlanSelection | None:
        at = require_loop_timestamp(at)
        active = None
        for row in self.entries:
            if row.effective_trade_date > at.date():
                break
            if active is None or active.version.version_id != row.version.version_id:
                active = row
        if active is None:
            return None
        activated = max(
            datetime.combine(active.effective_trade_date, time.min, SHANGHAI),
            active.version.available_at,
        )
        if at < activated or not active.version.permits_date(at.date()):
            return None
        return ScheduledLoopPlanSelection(
            version=active.version,
            effective_trade_date=active.effective_trade_date,
            activated_at=activated,
            continued=at.date() > active.effective_trade_date,
        )

    def preflight(self, calendar, *, started_at, evidence_cutoff) -> None:
        started_at = require_loop_timestamp(started_at)
        evidence_cutoff = require_loop_timestamp(evidence_cutoff)
        if started_at > evidence_cutoff:
            raise ValueError("start follows evidence cutoff")
        exchange = self.entries[0].version.snapshot.market
        days = {day.cal_date: day for day in calendar if day.exchange == exchange}
        if len(days) != sum(day.exchange == exchange for day in calendar):
            raise ValueError("duplicate calendar dates")
        for row in self.entries:
            if row.effective_trade_date > evidence_cutoff.date():
                break
            day = days.get(row.effective_trade_date)
            if day is None or not day.is_open:
                raise ValueError("effective date must be a known trading day")
        if self.select(started_at) is None:
            raise ValueError("uncovered run start")
