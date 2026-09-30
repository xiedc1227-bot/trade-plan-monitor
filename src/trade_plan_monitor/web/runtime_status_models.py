"""Closed monitor v2 status values; none of these views authorizes business work."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import UUID4, BaseModel, Field, field_validator, model_serializer, model_validator

from trade_plan_monitor.decision.models import ActionableSignalType, DataHealthStatus
from trade_plan_monitor.market_data.models import AShareSymbol, ShanghaiDatetime
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.web.routers.dashboard import (
    AuthoritativeDecisionView,
    DashboardCounts,
    IndexConditionEvidenceView,
    MarketIndexSnapshotView,
    MarketTurnoverSummaryView,
    SafeMonitorSequence,
    Sha256Hex,
    SymbolReferenceMarketView,
    SymbolSummaryView,
)
from trade_plan_monitor.web.routers.dashboard import ReadModel as ExistingReadModel
from trade_plan_monitor.web.routers.health import (
    DatabaseHealthView,
    DeliveryHealthView,
    ExecutorHealthView,
    ProviderHealthView,
    RuntimeGapView,
)
from trade_plan_monitor.web.routers.plans import ExplicitPlanRuntimeView
from trade_plan_monitor.web.routers.symbols import PositionLotView, SymbolDetailResponse


def _canonical_times(original: object, serialized: object) -> object:
    if isinstance(original, datetime):
        return original.isoformat(timespec="microseconds")
    if isinstance(original, BaseModel) and isinstance(serialized, dict):
        for name, field in type(original).model_fields.items():
            key = field.serialization_alias or field.alias or name
            if key not in serialized:
                key = name
            if key in serialized:
                serialized[key] = _canonical_times(getattr(original, name), serialized[key])
    elif isinstance(original, (tuple, list)) and isinstance(serialized, list):
        return [
            _canonical_times(value, wire) for value, wire in zip(original, serialized, strict=True)
        ]
    return serialized


class ReadModel(ExistingReadModel):
    """V2 emits six fractional digits, including reused nested v1 value schemas."""

    @model_serializer(mode="wrap")
    def serialize_canonical_times(self, handler, info):
        value = handler(self)
        return _canonical_times(self, value) if info.mode == "json" else value


RuntimeReason = Literal[
    "RUNTIME_STARTING",
    "RUNTIME_STOPPING",
    "RUNTIME_STOPPED",
    "RUNTIME_FAULT",
    "COORDINATOR_STALLED",
    "STORAGE_UNAVAILABLE",
    "BEFORE_FIRST_MINUTE",
    "SESSION_BREAK",
    "SESSION_CLOSED",
    "NO_ACTIVE_PLANS",
    "AWAITING_FIRST_EVALUATION",
    "CALENDAR_UNKNOWN",
    "REFERENCE_PENDING",
    "COVERAGE_INCOMPLETE",
    "CLOSE_PENDING",
    "PUBLICATION_PENDING",
    "PROVIDER_UNAVAILABLE",
    "RATE_LIMITED",
    "CREDENTIAL_MISSING",
    "PERMISSION_DENIED",
    "SEMANTICS_INCOMPATIBLE",
    "CONFIGURATION_INVALID",
    "HISTORY_UNAVAILABLE",
    "STATE_UNAVAILABLE",
    "GENERATION_CHANGED",
    "NEEDS_RESTART",
    "LEGACY_PLANS_REQUIRE_REVIEW",
    "SCOPED_DEPENDENCY_FAILURE",
]
PlanFamily = Literal["LEGACY_LOW_BUY", "EXPLICIT_RULES"]
ScopeState = Literal["WAITING", "RECOVERING", "READY", "BLOCKED"]


class IntradayTargetView(ReadModel):
    kind: Literal["INTRADAY"]
    target_end: ShanghaiDatetime


class OfficialCloseTargetView(ReadModel):
    kind: Literal["OFFICIAL_CLOSE"]
    trade_date: date


RequiredTargetView = Annotated[
    IntradayTargetView | OfficialCloseTargetView,
    Field(discriminator="kind"),
]


class ScopeProgressView(ReadModel):
    required_count: SafeMonitorSequence | None
    completed_count: SafeMonitorSequence | None

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if (self.required_count is None) != (self.completed_count is None):
            raise ValueError("progress counts must both be known or unknown")
        if self.required_count is not None and self.completed_count > self.required_count:
            raise ValueError("completed obligations cannot exceed required obligations")
        return self


class _ScopeView(ReadModel):
    scope_key: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
    status: ScopeState
    reason_code: RuntimeReason | None
    required_target: RequiredTargetView | None
    data_cutoff: ShanghaiDatetime | None
    next_retry_at: ShanghaiDatetime | None
    progress: ScopeProgressView

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if (self.status == "READY") != (self.reason_code is None):
            raise ValueError("only READY scopes omit a reason")
        if self.reason_code == "SCOPED_DEPENDENCY_FAILURE":
            raise ValueError("scope reasons must identify the actual cause")
        if self.status == "READY" and (
            self.next_retry_at is not None
            or self.progress.required_count != self.progress.completed_count
        ):
            raise ValueError("READY scopes cannot retain recovery obligations")
        return self


class PlanScopeView(_ScopeView):
    kind: Literal["PLAN"]
    symbol: AShareSymbol
    plan_family: PlanFamily
    plan_version_id: UUID
    plan_hash: Sha256Hex
    activation_revision: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
    read_only: bool

    @model_validator(mode="after")
    def validate_evaluation_readiness(self) -> Self:
        if self.plan_family == "EXPLICIT_RULES" and isinstance(
            self.required_target, OfficialCloseTargetView,
        ):
            raise ValueError("explicit rules do not have an official-close target")
        if not self.read_only and (
            self.status != "READY"
            or self.required_target is None
            or self.progress.required_count is None
        ):
            raise ValueError("evaluation readiness requires an exact complete target")
        return self


class IndexScopeView(_ScopeView):
    kind: Literal["INDEX"]
    index_code: MarketIndexCode


class ProviderScopeView(_ScopeView):
    kind: Literal["PROVIDER"]


class CalendarScopeView(_ScopeView):
    kind: Literal["CALENDAR"]


RuntimeScopeView = Annotated[
    PlanScopeView | IndexScopeView | ProviderScopeView | CalendarScopeView,
    Field(discriminator="kind"),
]


class CoordinatorStatusView(ReadModel):
    state: Literal["STARTING", "SCHEDULED", "WORKING", "STALLED", "STOPPED"]
    progress_due_at: ShanghaiDatetime | None


class RuntimeStatusView(ReadModel):
    lifecycle: Literal["STARTING", "RUNNING", "STOPPING", "STOPPED"]
    mode: Literal["RECOVERING", "MONITORING", "STANDBY", "DEGRADED", "BLOCKED"]
    reason_code: RuntimeReason | None
    next_wake_at: ShanghaiDatetime | None
    next_retry_at: ShanghaiDatetime | None
    last_progress_at: ShanghaiDatetime | None
    coordinator: CoordinatorStatusView
    scopes: tuple[RuntimeScopeView, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if (self.mode == "MONITORING") != (self.reason_code is None):
            raise ValueError("only MONITORING omits an aggregate reason")
        if self.lifecycle != "RUNNING" and self.mode != "BLOCKED":
            raise ValueError("non-running lifecycle cannot claim active monitoring")
        keys = tuple(scope.scope_key for scope in self.scopes)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("scopes must be unique and sorted by scopeKey")
        symbols = tuple(scope.symbol for scope in self.scopes if isinstance(scope, PlanScopeView))
        if len(symbols) != len(set(symbols)):
            raise ValueError("each symbol has exactly one active PLAN scope")
        state = self.coordinator.state
        if state in {"SCHEDULED", "WORKING", "STALLED"} and (
            self.coordinator.progress_due_at is None
        ):
            raise ValueError("owned progress requires its deadline")
        if state == "SCHEDULED" and self.next_wake_at is None:
            raise ValueError("scheduled progress requires the next reconsideration")
        if state == "STALLED" and (
            self.mode != "BLOCKED" or self.reason_code != "COORDINATOR_STALLED"
        ):
            raise ValueError("stalled coordination cannot claim business progress")
        if state == "STOPPED" and (
            self.lifecycle != "STOPPED"
            or self.mode != "BLOCKED"
            or self.reason_code != "RUNTIME_STOPPED"
            or self.next_wake_at is not None
            or self.next_retry_at is not None
            or self.coordinator.progress_due_at is not None
        ):
            raise ValueError("stopped ownership cannot retain an active schedule")
        if self.lifecycle == "STOPPED" and state != "STOPPED":
            raise ValueError("stopped lifecycle requires stopped coordination")
        if any(isinstance(scope, PlanScopeView) and not scope.read_only for scope in self.scopes):
            if self.lifecycle != "RUNNING" or state not in {"SCHEDULED", "WORKING"}:
                raise ValueError("plan readiness requires a live coordinator")
        return self


class RuntimeStatusEnvelope(ReadModel):
    monitor_contract_version: Literal[2]
    runtime_generation: UUID4 | None
    observed_at: ShanghaiDatetime
    runtime_status: RuntimeStatusView

    @field_validator("monitor_contract_version", mode="before")
    @classmethod
    def validate_version_integer(cls, value):
        if type(value) is not int or value != 2:
            raise ValueError("monitorContractVersion must be integer 2")
        return value

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        status = self.runtime_status
        if self.runtime_generation is None and status.lifecycle != "STOPPED":
            raise ValueError("an existing owner retains its generation")
        if status.last_progress_at is not None and status.last_progress_at > self.observed_at:
            raise ValueError("progress cannot be completed in the future")
        due, state = status.coordinator.progress_due_at, status.coordinator.state
        if due is not None and state in {"SCHEDULED", "WORKING", "STALLED"}:
            if (due < self.observed_at) != (state == "STALLED"):
                raise ValueError("expired owned progress must be marked STALLED")
        for scope in status.scopes:
            if scope.data_cutoff is not None and scope.data_cutoff > self.observed_at:
                raise ValueError("data cutoff cannot follow observation")
            target = scope.required_target
            if isinstance(target, IntradayTargetView) and target.target_end > self.observed_at:
                raise ValueError("required completed minute cannot be in the future")
            if (
                isinstance(target, OfficialCloseTargetView)
                and target.trade_date > self.observed_at.date()
            ):
                raise ValueError("required completed close cannot be in the future")
        return self


class SourceAlertView(ReadModel):
    event_id: UUID
    result_hash: Sha256Hex
    evaluated_at: ShanghaiDatetime
    data_cutoff: ShanghaiDatetime

    @model_validator(mode="after")
    def validate_source_times(self) -> Self:
        if self.data_cutoff > self.evaluated_at:
            raise ValueError("source cutoff cannot follow its evaluation")
        return self


class RuleEligibilityView(ReadModel):
    rule_id: Annotated[str, Field(min_length=1, max_length=128)]
    action: Literal["BUY", "SELL", "RISK_ALERT"]
    current_actionable: bool
    reason_code: (
        Literal[
            "NO_CURRENT_SIGNAL",
            "INTRADAY_EXPIRED",
            "RECOVERY_HOLD",
            "RISK_NO_LONGER_VALID",
            "CURRENT_STATE_UNVERIFIED",
            "CACHED_RESULT",
        ]
        | None
    )
    actionable_until: ShanghaiDatetime | None
    source_alert: SourceAlertView | None

    @model_validator(mode="after")
    def validate_eligibility(self) -> Self:
        if self.current_actionable:
            if self.reason_code is not None or self.source_alert is None:
                raise ValueError("current rules require a proven source and no failure reason")
            if (self.action in {"BUY", "SELL"}) != (self.actionable_until is not None):
                raise ValueError("rule deadlines must preserve existing delivery classes")
        elif self.reason_code is None or self.actionable_until is not None:
            raise ValueError("ineligible rules require a reason and no actionable deadline")
        return self


class _PlanEntryView(ReadModel):
    symbol: AShareSymbol
    name: Annotated[str, Field(min_length=1, max_length=128)]
    plan_family: PlanFamily
    plan_version_id: UUID
    plan_hash: Sha256Hex
    activation_revision: Annotated[int, Field(strict=True, ge=1, le=2**53 - 1)]
    observed_at: ShanghaiDatetime
    scope: PlanScopeView
    current_actionable: bool

    @field_validator("current_actionable", mode="before")
    @classmethod
    def validate_actionable_boolean(cls, value):
        if type(value) is not bool:
            raise ValueError("currentActionable must be a boolean")
        return value

    @model_validator(mode="after")
    def validate_scope_identity(self) -> Self:
        if any(
            getattr(self, field) != getattr(self.scope, field)
            for field in (
                "symbol",
                "plan_family",
                "plan_version_id",
                "plan_hash",
                "activation_revision",
            )
        ):
            raise ValueError("entry and scope must identify the same active plan")
        return self


class UnavailablePlanEntryView(_PlanEntryView):
    availability: Literal["UNAVAILABLE"]
    current_actionable: Literal[False]
    projection_state: Literal["WAITING", "RECOVERING", "BLOCKED"]
    reason_code: RuntimeReason

    @model_validator(mode="after")
    def validate_unavailable(self) -> Self:
        first = (
            self.scope.status == "READY"
            and self.projection_state == "WAITING"
            and self.reason_code == "AWAITING_FIRST_EVALUATION"
        )
        if not first and (
            self.projection_state != self.scope.status or self.reason_code != self.scope.reason_code
        ):
            raise ValueError("missing result must explain its actual scope state")
        return self


class LegacyPlanEntryView(_PlanEntryView):
    plan_family: Literal["LEGACY_LOW_BUY"]
    availability: Literal["CURRENT", "CACHED"]
    decision: AuthoritativeDecisionView
    risk_distance_fen: Annotated[int, Field(strict=True)] | None
    satisfied_condition_count: SafeMonitorSequence
    total_condition_count: SafeMonitorSequence
    reference_market: SymbolReferenceMarketView | None
    actionable_until: ShanghaiDatetime | None

    @model_validator(mode="after")
    def validate_legacy_result(self) -> Self:
        if self.decision.symbol != self.symbol or self.decision.plan_hash != self.plan_hash:
            raise ValueError("legacy result must match the active plan")
        if self.decision.evaluated_at > self.observed_at:
            raise ValueError("legacy result cannot follow observation")
        if self.satisfied_condition_count > self.total_condition_count:
            raise ValueError("satisfied conditions cannot exceed total conditions")
        if self.current_actionable:
            if self.availability != "CURRENT" or self.decision.signal_type.value not in {
                item.value for item in ActionableSignalType
            }:
                raise ValueError("only a current proven reminder may be actionable")
            intraday = self.decision.signal_type.value in {
                "BUY_CORE_READY",
                "BUY_TACTICAL_READY",
                "PRESSURE_REDUCE_READY",
            }
            if intraday != (self.actionable_until is not None):
                raise ValueError("legacy reminder deadline must preserve its delivery class")
            if self.actionable_until is not None and self.actionable_until <= self.observed_at:
                raise ValueError("expired reminder cannot be actionable")
        elif self.actionable_until is not None:
            raise ValueError("ineligible legacy entry has no actionable deadline")
        return self


class ExplicitPlanEntryView(_PlanEntryView):
    plan_family: Literal["EXPLICIT_RULES"]
    availability: Literal["CURRENT", "CACHED"]
    explicit_runtime: ExplicitPlanRuntimeView
    result_hash: Sha256Hex
    rule_eligibility: tuple[RuleEligibilityView, ...] = Field(min_length=1, max_length=3)
    actionable_rule_ids: tuple[str, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def validate_explicit_result(self) -> Self:
        result = self.explicit_runtime
        if result.status != "CURRENT" or any(
            getattr(self, field) != getattr(result, field)
            for field in ("symbol", "plan_version_id", "plan_hash", "activation_revision")
        ):
            raise ValueError("explicit result must match the active plan identity")
        if not result.target_bucket_end <= result.evaluated_at <= self.observed_at:
            raise ValueError("explicit result timestamps must precede observation")
        if self.availability == "CURRENT" and (
            not isinstance(self.scope.required_target, IntradayTargetView)
            or self.scope.required_target.target_end != result.target_bucket_end
        ):
            raise ValueError("current explicit result must match the exact intraday target")
        expected = tuple((rule.rule_id, rule.action) for rule in result.rule_outcomes)
        if len({rule[0] for rule in expected}) != len(expected) or expected != tuple(
            (rule.rule_id, rule.action) for rule in self.rule_eligibility
        ):
            raise ValueError("eligibility must match every persisted rule in order")
        actionable = tuple(
            rule.rule_id for rule in self.rule_eligibility if rule.current_actionable
        )
        if self.actionable_rule_ids != actionable or self.current_actionable != bool(actionable):
            raise ValueError("only explicitly eligible rules belong to the actionable subset")
        for rule in self.rule_eligibility:
            if self.availability == "CACHED" and (
                rule.current_actionable or rule.reason_code != "CACHED_RESULT"
            ):
                raise ValueError("cached rules cannot become current through presentation")
            if rule.source_alert is not None and rule.source_alert.evaluated_at > self.observed_at:
                raise ValueError("source reminder cannot be from the future")
            if rule.actionable_until is not None and rule.actionable_until <= self.observed_at:
                raise ValueError("expired rule cannot remain actionable")
        return self


PlanEntryView = UnavailablePlanEntryView | LegacyPlanEntryView | ExplicitPlanEntryView


def runtime_dashboard_counts(entries: tuple[PlanEntryView, ...]) -> DashboardCounts:
    """RS06 independent display counts, never an evaluation or command permission."""
    counts = dict.fromkeys(
        ("actionable", "low_zone_watch", "blocked", "risk", "stale", "normal"),
        0,
    )
    for entry in entries:
        blocked = entry.scope.status == "BLOCKED"
        counts["blocked"] += int(blocked)
        if entry.availability == "UNAVAILABLE":
            continue
        if entry.availability == "CACHED":
            counts["stale"] += 1
            continue
        risk = stale = watch = normal_candidate = False
        if isinstance(entry, LegacyPlanEntryView):
            decision = entry.decision
            data_blocked = decision.data_health.status in {
                DataHealthStatus.BLOCKED,
                DataHealthStatus.GAPPED,
            }
            counts["blocked"] += int(data_blocked and not blocked)
            blocked = blocked or data_blocked
            risk = decision.risk_status.value != "CLEAR"
            stale = decision.data_health.status is not DataHealthStatus.LIVE and not data_blocked
            watch = (
                entry.scope.status == "READY"
                and decision.data_health.status is DataHealthStatus.LIVE
                and decision.signal_type.value == "LOW_ZONE_WATCH"
            )
            normal_candidate = (
                decision.data_health.status is DataHealthStatus.LIVE
                and decision.signal_type.value not in {item.value for item in ActionableSignalType}
            )
        else:
            risk = any(
                rule.current_actionable and rule.action == "RISK_ALERT"
                for rule in entry.rule_eligibility
            )
            stale = any(rule.reason_code == "INTRADAY_EXPIRED" for rule in entry.rule_eligibility)
            normal_candidate = all(
                rule.reason_code == "NO_CURRENT_SIGNAL" for rule in entry.rule_eligibility
            )
        counts["actionable"] += int(entry.current_actionable)
        counts["risk"] += int(risk)
        counts["stale"] += int(stale)
        counts["low_zone_watch"] += int(watch)
        counts["normal"] += int(
            entry.scope.status == "READY"
            and normal_candidate
            and not (entry.current_actionable or blocked or risk or stale or watch)
        )
    return DashboardCounts(**counts)


class RuntimeDashboardResponse(RuntimeStatusEnvelope):
    sequence: SafeMonitorSequence
    counts: DashboardCounts
    symbols: tuple[PlanEntryView, ...] = Field(max_length=10)
    market_indexes: tuple[MarketIndexSnapshotView, ...] = Field(max_length=5)
    market_turnover: MarketTurnoverSummaryView | None

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        identities = tuple(row.symbol for row in self.symbols)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("dashboard active entries must be unique and sorted")
        scopes = {scope.scope_key: scope for scope in self.runtime_status.scopes}
        for row in self.symbols:
            if row.observed_at != self.observed_at or scopes.get(row.scope.scope_key) != row.scope:
                raise ValueError("snapshot entry must share the exact status observation")
            if row.current_actionable and self.runtime_status.coordinator.state in {
                "STARTING",
                "STALLED",
                "STOPPED",
            }:
                raise ValueError("absent coordinator authority cannot preserve current reminders")
        plan_scopes = tuple(scope for scope in scopes.values() if isinstance(scope, PlanScopeView))
        if {scope.symbol for scope in plan_scopes} != set(identities):
            raise ValueError("dashboard must include every active plan scope")
        if self.counts != runtime_dashboard_counts(self.symbols):
            raise ValueError("dashboard counts must match authoritative plan entries")
        codes = tuple(index.index_code for index in self.market_indexes)
        if codes != tuple(sorted(set(codes), key=str)):
            raise ValueError("market indexes must be unique and ordered")
        if any(index.observed_at > self.observed_at for index in self.market_indexes):
            raise ValueError("market index cannot follow observation")
        if (
            self.market_turnover is not None
            and self.market_turnover.completed_bucket_at > self.observed_at
        ):
            raise ValueError("turnover cutoff cannot follow observation")
        return self


def _validate_entry_observation(envelope: RuntimeStatusEnvelope, entry: PlanEntryView) -> None:
    if (
        entry.observed_at != envelope.observed_at
        or entry.scope not in envelope.runtime_status.scopes
    ):
        raise ValueError("entry must share its enclosing observation and exact scope")
    if entry.current_actionable and envelope.runtime_status.coordinator.state in {
        "STARTING",
        "STALLED",
        "STOPPED",
    }:
        raise ValueError("current reminders require coordinator authority")


class RuntimeSymbolCollectionResponse(RuntimeStatusEnvelope):
    sequence: SafeMonitorSequence
    items: tuple[PlanEntryView, ...] = Field(max_length=100)
    offset: Annotated[int, Field(strict=True, ge=0, le=10_000)]
    limit: Annotated[int, Field(strict=True, ge=1, le=100)]
    total: Annotated[int, Field(strict=True, ge=0, le=10)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if (
            len(self.items) > self.limit
            or self.items
            and self.offset + len(self.items) > self.total
        ):
            raise ValueError("page exceeds requested bounds")
        symbols = tuple(item.symbol for item in self.items)
        if symbols != tuple(sorted(set(symbols))):
            raise ValueError("page symbols must be unique and ordered")
        if (
            sum(isinstance(scope, PlanScopeView) for scope in self.runtime_status.scopes)
            != self.total
        ):
            raise ValueError("total must count active plan scopes")
        for entry in self.items:
            _validate_entry_observation(self, entry)
        return self


class RuntimeLegacyDetailsView(ReadModel):
    position_lots: tuple[PositionLotView, ...] = Field(max_length=200)
    reference_market: SymbolReferenceMarketView | None
    index_condition_evidence: tuple[IndexConditionEvidenceView, ...] = Field(max_length=50)


class RuntimeSymbolDetailResponse(RuntimeStatusEnvelope):
    sequence: SafeMonitorSequence
    summary: PlanEntryView
    legacy_details: RuntimeLegacyDetailsView | None

    @model_validator(mode="after")
    def validate_detail(self) -> Self:
        _validate_entry_observation(self, self.summary)
        if isinstance(self.summary, LegacyPlanEntryView):
            if self.legacy_details is None:
                raise ValueError("legacy results require their matching detail evidence")
            row = self.summary
            # Reuse the existing quantity/reference consistency rules; connected
            # here is only a required v1 value-model field, never a v2 authority.
            SymbolDetailResponse(
                summary=SymbolSummaryView(
                    symbol=row.symbol,
                    name=row.name,
                    observed_at=row.observed_at,
                    connected=False,
                    risk_distance_fen=row.risk_distance_fen,
                    satisfied_condition_count=row.satisfied_condition_count,
                    total_condition_count=row.total_condition_count,
                    decision=row.decision,
                    reference_market=row.reference_market,
                ),
                **self.legacy_details.model_dump(mode="python"),
            )
        elif self.legacy_details is not None:
            raise ValueError("explicit or unavailable entries cannot have legacy details")
        return self


class RuntimeInactiveSymbolResponse(RuntimeStatusEnvelope):
    sequence: SafeMonitorSequence
    symbol: AShareSymbol
    availability: Literal["UNAVAILABLE"]
    reason_code: Literal["NO_ACTIVE_PLAN"]

    @model_validator(mode="after")
    def validate_inactive(self) -> Self:
        if any(
            isinstance(scope, PlanScopeView) and scope.symbol == self.symbol
            for scope in self.runtime_status.scopes
        ):
            raise ValueError("an inactive symbol cannot have an active PLAN scope")
        return self


class RuntimeExplicitUnavailableEntryView(UnavailablePlanEntryView):
    plan_family: Literal["EXPLICIT_RULES"]


class RuntimeExplicitDetailResponse(RuntimeSymbolDetailResponse):
    summary: ExplicitPlanEntryView | RuntimeExplicitUnavailableEntryView
    legacy_details: None

    @model_validator(mode="after")
    def validate_explicit_family(self) -> Self:
        if self.summary.plan_family != "EXPLICIT_RULES":
            raise ValueError("explicit detail requires the explicit family")
        return self


class RuntimeSymbolHealthResponse(RuntimeStatusEnvelope):
    scope: PlanScopeView

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.scope not in self.runtime_status.scopes:
            raise ValueError("symbol health must use the exact authoritative PLAN scope")
        return self


class RuntimeHealthV2Response(RuntimeStatusEnvelope):
    started_at: ShanghaiDatetime | None
    stopped_at: ShanghaiDatetime | None
    last_completed_minute: ShanghaiDatetime | None
    last_completed_minute_age_seconds: SafeMonitorSequence | None
    latest_evaluation_at: ShanghaiDatetime | None
    latest_evaluation_age_seconds: SafeMonitorSequence | None
    gaps: tuple[RuntimeGapView, ...] = Field(max_length=2_400)
    cooldown_until: ShanghaiDatetime | None
    providers: tuple[ProviderHealthView, ...] = Field(max_length=5)
    executor: ExecutorHealthView
    database: DatabaseHealthView
    delivery: DeliveryHealthView

    @model_validator(mode="after")
    def validate_health(self) -> Self:
        if self.runtime_generation is not None and (
            (self.runtime_status.lifecycle == "STOPPED") != (self.stopped_at is not None)
        ):
            raise ValueError("a known stopped owner must retain its stop timestamp")
        if self.runtime_generation is None:
            if self.started_at is not None or self.stopped_at is not None:
                raise ValueError("absent owner cannot retain lifecycle timestamps")
        elif self.started_at is None or self.started_at > self.observed_at:
            raise ValueError("owner start must precede observation")
        if self.stopped_at is not None and (
            self.started_at is None
            or not self.started_at <= self.stopped_at <= self.observed_at
            or self.runtime_status.lifecycle != "STOPPED"
        ):
            raise ValueError("stoppedAt must belong to a stopped owner")
        for timestamp, age in (
            (self.last_completed_minute, self.last_completed_minute_age_seconds),
            (self.latest_evaluation_at, self.latest_evaluation_age_seconds),
        ):
            if (timestamp is None) != (age is None):
                raise ValueError("diagnostic time and age must appear together")
            if timestamp is not None and (
                timestamp > self.observed_at
                or int((self.observed_at - timestamp).total_seconds()) != age
            ):
                raise ValueError("diagnostic age must match this observation")
        gaps = tuple((gap.symbol, gap.bar_end) for gap in self.gaps)
        if gaps != tuple(sorted(set(gaps))) or any(
            gap.bar_end > self.observed_at for gap in self.gaps
        ):
            raise ValueError("gaps must be unique completed minutes in order")
        providers = tuple(provider.capability for provider in self.providers)
        if len(providers) != len(set(providers)) or any(
            provider.checked_at > self.observed_at for provider in self.providers
        ):
            raise ValueError("provider observations must be unique and not future dated")
        return self


class RuntimeHeartbeatFrame(RuntimeStatusEnvelope):
    type: Literal["heartbeat"]
    sequence: SafeMonitorSequence


class RuntimeSnapshotRequiredFrame(ReadModel):
    type: Literal["snapshot.required"]
    monitor_contract_version: Literal[2]
    sequence: SafeMonitorSequence
    reason: Literal["REPLAY_UNAVAILABLE"]

    @field_validator("monitor_contract_version", mode="before")
    @classmethod
    def validate_version(cls, value):
        return RuntimeStatusEnvelope.validate_version_integer(value)
