"""Opt-in monitor v2 reads from one committed SQLite snapshot and frozen owner."""

from types import SimpleNamespace
from uuid import UUID, uuid4

from anyio import to_thread
from sqlalchemy import select

from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_index.identity import MAPPING_VERSION
from trade_plan_monitor.market_index.turnover import (
    MARKET_TURNOVER_INDEX_CODES,
    build_market_turnover_summary,
)
from trade_plan_monitor.notifications.recovery_eligibility import RecoveryBarrierEvidence
from trade_plan_monitor.runtime.market_indexes import ALWAYS_ON_INDEX_CODES, DASHBOARD_INDEX_CODES
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority, capture_input_stamp
from trade_plan_monitor.state.events import MonitorEventLog
from trade_plan_monitor.state.explicit_rules import ExplicitDecisionRepository
from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanVersion
from trade_plan_monitor.state.projections import ProjectionError, ProjectionRepository
from trade_plan_monitor.state.recovery_read_session import require_owned_recovery_session
from trade_plan_monitor.state.repositories import MarketHistoryRepository, PlanRepository
from trade_plan_monitor.web import runtime_status_models as views
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.persistent_monitor_read_service import (
    _active_plan_details,
    _complete_symbol_projection,
    _dashboard_market_indexes,
    _list_plan_details,
    _observed_at,
    _pagination,
)
from trade_plan_monitor.web.runtime_status_eligibility import (
    explicit_rule_eligibility,
    legacy_eligibility,
)


def _repositories(session, observed):
    events = MonitorEventLog(session, clock=lambda: observed)
    return SimpleNamespace(
        events=events,
        projections=ProjectionRepository(session),
        plans=PlanRepository(
            session, clock=lambda: observed, id_factory=lambda: str(uuid4()), events=events
        ),
        explicit_rules=ExplicitDecisionRepository(session),
        history=MarketHistoryRepository(session),
    )


def build_dependency_scopes(dependencies):
    """Convert frozen actual owner facts; never discover, schedule or repair work."""
    from trade_plan_monitor.decision.models import IntradayEvaluationTarget
    from trade_plan_monitor.market_index.models import MarketIndexCode
    from trade_plan_monitor.runtime.status_authority import DependencyReadAuthority

    scopes = []
    for item in dependencies:
        if type(item) is not DependencyReadAuthority:
            raise TypeError("Expected frozen dependency authority")
        target = (
            None
            if item.target is None
            else views.IntradayTargetView(kind="INTRADAY", target_end=item.target.bucket_end)
            if isinstance(item.target, IntradayEvaluationTarget)
            else views.OfficialCloseTargetView(
                kind="OFFICIAL_CLOSE", trade_date=item.target.trade_date
            )
        )
        common = dict(
            scope_key=item.scope_key,
            kind=item.kind,
            status=item.status,
            reason_code=item.reason_code,
            required_target=target,
            data_cutoff=item.data_cutoff,
            next_retry_at=item.next_retry_at,
            progress=views.ScopeProgressView(
                required_count=item.required_count, completed_count=item.completed_count
            ),
        )
        if item.kind == "INDEX":
            scope = views.IndexScopeView(**common, index_code=MarketIndexCode(item.index_code))
        elif item.kind == "PROVIDER" and item.index_code is None:
            scope = views.ProviderScopeView(**common)
        elif item.kind == "CALENDAR" and item.index_code is None:
            scope = views.CalendarScopeView(**common)
        else:
            raise ValueError("Unknown dependency authority")
        scopes.append(scope)
    return tuple(scopes)


def _identity_rows(session):
    return tuple(
        session.execute(
            select(
                ActivePlan.symbol,
                ActivePlan.plan_version_id,
                ActivePlan.revision,
                PlanVersion.plan_hash,
                ActivePlan.activated_at,
                PlanActivationState.plan_version_id,
                PlanActivationState.revision,
                PlanActivationState.changed_at,
            )
            .join(PlanVersion, ActivePlan.plan_version_id == PlanVersion.id)
            .outerjoin(PlanActivationState, ActivePlan.symbol == PlanActivationState.symbol)
            .order_by(ActivePlan.symbol)
        ).all()
    )


class RuntimeStatusReadService:
    """The authority provider is called only on the async caller's owning loop."""

    monitor_contract_version = 2

    def __init__(self, session_factory, authority_provider, *, clock, legacy_read_service=None):
        self._sessions = session_factory
        self._authority = authority_provider
        self._clock = clock
        self._legacy_read_service = legacy_read_service

    async def _read(self):
        try:
            for _attempt in range(2):
                authority = self._authority()
                if type(authority) is not RuntimeReadAuthority:
                    raise ProjectionError("Runtime authority is unavailable")
                observed = _observed_at(self._clock())
                result, identity = await to_thread.run_sync(
                    lambda authority=authority, observed=observed: self._assemble(
                        authority, observed
                    ),
                )
                identity_after = await to_thread.run_sync(self._identities)
                after = self._authority()
                if (
                    type(after) is RuntimeReadAuthority
                    and after.token == authority.token
                    and after.generation == authority.generation
                    and after.configuration_revision == authority.configuration_revision
                    and after.lifecycle == authority.lifecycle
                    and after.block_reason == authority.block_reason
                    and after.standby_reason == authority.standby_reason
                    and after.owner_absent == authority.owner_absent
                    and after.plans == authority.plans
                    and after.dependencies == authority.dependencies
                    and (None if after.progress is None else after.progress.state)
                    == (None if authority.progress is None else authority.progress.state)
                    and identity == identity_after
                ):
                    return result
            raise ProjectionError("Runtime authority changed during projection")
        except ApiError:
            raise
        except Exception:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE) from None

    def _identities(self):
        session = self._sessions()
        require_owned_recovery_session(session, (ActivePlan, PlanVersion, PlanActivationState))
        with session, session.begin():
            return _identity_rows(session)

    def _assemble(self, authority, observed):
        session = self._sessions()
        require_owned_recovery_session(session, (ActivePlan, PlanVersion, PlanActivationState))
        with session, session.begin():
            work = _repositories(session, observed)
            sequence = work.events.current_sequence()
            details = _list_plan_details(work)
            active = _active_plan_details(work, details)
            scopes, entries, legacy_details, projections = [], [], {}, []
            identities = _identity_rows(session)
            for detail in active:
                plan = load_plan_json(detail.payload_json)
                pointer = work.plans.get_active(plan.symbol)
                activation = work.plans.get_activation_state(plan.symbol)
                if (
                    activation is None
                    or activation.revision != pointer.revision
                    or activation.plan_version_id != pointer.plan_version_id
                    or pointer.activated_at > observed
                    or activation.changed_at > observed
                ):
                    raise ProjectionError("Persisted activation identity is inconsistent")
                evidence = next(
                    (item for item in authority.plans if item.symbol == plan.symbol), None
                )
                if evidence is not None and (
                    evidence.plan_version_id != detail.id
                    or evidence.plan_hash != detail.plan_hash
                    or evidence.activation_revision != pointer.revision
                ):
                    raise ProjectionError("Plan authority crossed activation identity")
                if type(plan) is not UnifiedTradePlan:
                    family = (
                        "EXPLICIT_RULES" if type(plan) is ExplicitTradePlan else "LEGACY_LOW_BUY"
                    )
                    scope = views.PlanScopeView(
                        scope_key=f"plan:{plan.symbol}",
                        kind="PLAN",
                        symbol=plan.symbol,
                        plan_family=family,
                        plan_version_id=UUID(detail.id),
                        plan_hash=detail.plan_hash,
                        activation_revision=pointer.revision,
                        status="BLOCKED",
                        reason_code="LEGACY_PLANS_REQUIRE_REVIEW",
                        required_target=None,
                        data_cutoff=None,
                        next_retry_at=None,
                        progress=views.ScopeProgressView(required_count=None, completed_count=None),
                        read_only=True,
                    )
                    scopes.append(scope)
                    entries.append(
                        views.UnavailablePlanEntryView(
                            symbol=plan.symbol,
                            name=plan.name,
                            plan_family=family,
                            plan_version_id=UUID(detail.id),
                            plan_hash=detail.plan_hash,
                            activation_revision=pointer.revision,
                            observed_at=observed,
                            scope=scope,
                            availability="UNAVAILABLE",
                            current_actionable=False,
                            projection_state="BLOCKED",
                            reason_code="LEGACY_PLANS_REQUIRE_REVIEW",
                        )
                    )
                    continue
                if isinstance(plan, UnifiedTradePlan):
                    scope, entry = _condition_entry(
                        session, authority, evidence, plan, detail, pointer, observed
                    )
                    scopes.append(scope)
                    entries.append(entry)
                    continue
                explicit = type(plan) is ExplicitTradePlan
                if explicit:
                    result = work.explicit_rules.latest(
                        plan_hash=detail.plan_hash,
                        activation_revision=pointer.revision,
                        symbol=plan.symbol,
                    )
                    projection = None
                else:
                    projection = _complete_symbol_projection(
                        work, detail, observed_at=observed, runtime_identity=None
                    )
                    head = work.projections.get_decision_head(plan.symbol)
                    result = None if projection is None else head.result
                    if projection is not None:
                        projections.append(projection)
                scope, current, barrier = _plan_scope(
                    session,
                    authority,
                    evidence,
                    plan,
                    detail,
                    pointer,
                    result,
                    observed,
                )
                scopes.append(scope)
                common = dict(
                    symbol=plan.symbol,
                    name=plan.name,
                    plan_family="EXPLICIT_RULES" if explicit else "LEGACY_LOW_BUY",
                    plan_version_id=UUID(detail.id),
                    plan_hash=detail.plan_hash,
                    activation_revision=pointer.revision,
                    observed_at=observed,
                    scope=scope,
                )
                if result is None:
                    entry = views.UnavailablePlanEntryView(
                        **common,
                        availability="UNAVAILABLE",
                        current_actionable=False,
                        projection_state="WAITING" if scope.status == "READY" else scope.status,
                        reason_code="AWAITING_FIRST_EVALUATION"
                        if scope.status == "READY"
                        else scope.reason_code,
                    )
                elif explicit:
                    entry = _explicit_entry(
                        session, plan, result, authority, barrier, current, observed, common
                    )
                else:
                    summary = projection.summary
                    actionable, deadline = legacy_eligibility(
                        session=session,
                        plan=plan,
                        result=result,
                        generation=authority.generation,
                        barrier=barrier,
                        now=observed,
                        current=current,
                    )
                    entry = views.LegacyPlanEntryView(
                        **common,
                        availability="CURRENT" if current else "CACHED",
                        current_actionable=actionable,
                        actionable_until=deadline,
                        decision=summary.decision,
                        risk_distance_fen=summary.risk_distance_fen,
                        satisfied_condition_count=summary.satisfied_condition_count,
                        total_condition_count=summary.total_condition_count,
                        reference_market=summary.reference_market,
                    )
                    legacy_details[plan.symbol] = views.RuntimeLegacyDetailsView(
                        position_lots=projection.detail.position_lots,
                        reference_market=projection.detail.reference_market,
                        index_condition_evidence=projection.detail.index_condition_evidence,
                    )
                entries.append(entry)
            status = _runtime_status(authority, scopes)
            indexes = tuple(
                row.snapshot
                for row in work.projections.list_latest_market_index_snapshots(
                    mapping_version=MAPPING_VERSION, index_codes=ALWAYS_ON_INDEX_CODES
                )
            )
            display = tuple(item for item in indexes if item.index_code in DASHBOARD_INDEX_CODES)
            turnover = build_market_turnover_summary(
                tuple(item for item in indexes if item.index_code in MARKET_TURNOVER_INDEX_CODES)
            )
            from trade_plan_monitor.web.routers.dashboard import MarketTurnoverSummaryView

            turnover_view = (
                None
                if turnover is None
                else MarketTurnoverSummaryView.model_validate(
                    {
                        **turnover.model_dump(mode="python", round_trip=True),
                        "benchmark_codes": MARKET_TURNOVER_INDEX_CODES,
                    }
                )
            )
            dashboard = views.RuntimeDashboardResponse(
                monitor_contract_version=2,
                sequence=sequence,
                runtime_generation=authority.generation,
                observed_at=observed,
                runtime_status=status,
                counts=_counts(entries),
                symbols=tuple(entries),
                market_indexes=_dashboard_market_indexes(
                    tuple(projections), display_snapshots=display
                ),
                market_turnover=turnover_view,
            )
            return (dashboard, legacy_details, details, authority), tuple(identities)

    async def get_dashboard(self):
        return (await self._read())[0]

    async def list_symbol_bars(self, **kwargs):
        if self._legacy_read_service is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        return await self._legacy_read_service.list_symbol_bars(**kwargs)

    async def list_symbol_events(self, **kwargs):
        if self._legacy_read_service is None:
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)
        return await self._legacy_read_service.list_symbol_events(**kwargs)

    async def list_symbols(self, *, offset, limit):
        _pagination(offset, limit)
        dashboard = await self.get_dashboard()
        return views.RuntimeSymbolCollectionResponse(
            **_envelope(dashboard),
            items=dashboard.symbols[offset : offset + limit],
            offset=offset,
            limit=limit,
            total=len(dashboard.symbols),
        )

    async def get_symbol(self, *, symbol):
        dashboard, details, known, _ = await self._read()
        entry = next((item for item in dashboard.symbols if item.symbol == symbol), None)
        if entry is None:
            if not any(item.symbol == symbol for item in known):
                return None
            return views.RuntimeInactiveSymbolResponse(
                **_envelope(dashboard),
                symbol=symbol,
                availability="UNAVAILABLE",
                reason_code="NO_ACTIVE_PLAN",
            )
        return views.RuntimeSymbolDetailResponse(
            **_envelope(dashboard), summary=entry, legacy_details=details.get(symbol)
        )

    async def get_explicit_plan_runtime(self, *, symbol):
        result = await self.get_symbol(symbol=symbol)
        if isinstance(result, views.RuntimeSymbolDetailResponse):
            return result if result.summary.plan_family == "EXPLICIT_RULES" else None
        return result

    async def get_symbol_health(self, *, symbol):
        dashboard = await self.get_dashboard()
        scope = next((item.scope for item in dashboard.symbols if item.symbol == symbol), None)
        return (
            None
            if scope is None
            else views.RuntimeSymbolHealthResponse(
                **_envelope(dashboard, sequence=False), scope=scope
            )
        )

    async def get_health(self):
        dashboard, _, _, authority = await self._read()
        values = authority.health.model_dump(mode="python")
        names = (
            "started_at",
            "stopped_at",
            "last_completed_minute",
            "last_completed_minute_age_seconds",
            "latest_evaluation_at",
            "latest_evaluation_age_seconds",
            "gaps",
            "cooldown_until",
            "providers",
            "executor",
            "database",
            "delivery",
        )
        fields = {name: values[name] for name in names}
        if authority.owner_absent:
            fields["started_at"] = fields["stopped_at"] = None
        return views.RuntimeHealthV2Response(**_envelope(dashboard, sequence=False), **fields)


def _envelope(dashboard, *, sequence=True):
    fields = dict(
        monitor_contract_version=2,
        runtime_generation=dashboard.runtime_generation,
        observed_at=dashboard.observed_at,
        runtime_status=dashboard.runtime_status,
    )
    if sequence:
        fields["sequence"] = dashboard.sequence
    return fields


def _plan_scope(session, authority, evidence, plan, detail, pointer, result, observed):
    from dataclasses import fields
    from datetime import datetime, time

    from trade_plan_monitor.decision.models import IntradayEvaluationTarget

    progress = authority.progress
    live = (
        authority.lifecycle == "RUNNING"
        and authority.block_reason is None
        and progress is not None
        and progress.state in {"SCHEDULED", "WORKING"}
    )
    target_value = None if evidence is None else evidence.target
    target = (
        None
        if target_value is None
        else target_value.bucket_end
        if isinstance(target_value, IntradayEvaluationTarget)
        else datetime.combine(target_value.trade_date, time(15), observed.tzinfo)
    )
    proof = None if evidence is None else evidence.completion
    family = "EXPLICIT_RULES" if type(plan) is ExplicitTradePlan else "LEGACY_LOW_BUY"
    known = (
        proof is not None
        and proof.runtime_generation == authority.generation
        and proof.configuration_revision == authority.configuration_revision
        and proof.symbol == plan.symbol
        and proof.plan_family == family
        and evidence.plan_family == family
        and proof.plan_version_id == detail.id
        and proof.plan_hash == detail.plan_hash
        and proof.activation_revision == pointer.revision
        and proof.target == target_value
        and result is not None
        and proof.result_hash == result.result_hash
    )
    complete, cutoff, completed, required_count = False, None, None, None
    if known:
        stamp = capture_input_stamp(session, plan=plan, result=result, now=observed)
        obligations = tuple(
            field.name
            for field in fields(proof.input_stamp)
            if field.name.endswith("_fingerprint")
            and getattr(proof.input_stamp, field.name) is not None
        )
        required_count = len(obligations)
        completed = sum(
            stamp is not None and getattr(stamp, name, None) == getattr(proof.input_stamp, name)
            for name in obligations
        )
        complete = stamp == proof.input_stamp
        cutoff = target if complete else None
    result_target = (
        None
        if result is None
        else result.target_bucket_end
        if type(plan) is ExplicitTradePlan
        else getattr(result.evaluation_identity, "bucket_end", None)
        or datetime.combine(
            result.evaluation_identity.official_trade_date, time(15), observed.tzinfo
        )
    )
    if result is not None:
        evaluated = (
            result.evaluated_at if type(plan) is ExplicitTradePlan else result.snapshot.evaluated_at
        )
        if evaluated > observed:
            raise ProjectionError("Persisted result is newer than observation")
    current = live and complete and result_target == target
    status = (
        "READY"
        if complete
        else (
            "BLOCKED"
            if evidence is not None and evidence.blocked
            else "RECOVERING"
            if evidence is not None and evidence.recovery_pending
            else "WAITING"
        )
    )
    reason = (
        None
        if complete
        else ("AWAITING_FIRST_EVALUATION" if evidence is None else evidence.pending_reason)
    )
    scope = views.PlanScopeView(
        scope_key=f"plan:{plan.symbol}",
        kind="PLAN",
        symbol=plan.symbol,
        plan_family="EXPLICIT_RULES" if type(plan) is ExplicitTradePlan else "LEGACY_LOW_BUY",
        plan_version_id=UUID(detail.id),
        plan_hash=detail.plan_hash,
        activation_revision=pointer.revision,
        status=status,
        reason_code=reason,
        required_target=(
            None
            if target_value is None
            else views.IntradayTargetView(kind="INTRADAY", target_end=target)
            if isinstance(target_value, IntradayEvaluationTarget)
            else views.OfficialCloseTargetView(
                kind="OFFICIAL_CLOSE", trade_date=target_value.trade_date
            )
        ),
        data_cutoff=cutoff,
        next_retry_at=None if complete or evidence is None else evidence.next_retry_at,
        progress=views.ScopeProgressView(required_count=required_count, completed_count=completed),
        read_only=not (current and evidence.evaluation_due),
    )
    barrier = (
        None
        if not current
        else RecoveryBarrierEvidence(
            symbol=plan.symbol,
            plan_hash=detail.plan_hash,
            activation_revision=pointer.revision,
            runtime_generation=authority.generation,
            target_bucket_end=target,
            reconciled_through=target,
            pending_obligations=0,
            observed_at=observed,
        )
    )
    return scope, current, barrier


def _runtime_status(authority, plans):
    scopes = tuple(sorted((*plans, *authority.dependencies), key=lambda item: item.scope_key))
    progress = authority.progress
    state = "STOPPED" if progress is None else progress.state
    if state == "STOPPED":
        mode, reason = "BLOCKED", "RUNTIME_STOPPED"
    elif state == "STALLED":
        mode, reason = "BLOCKED", "COORDINATOR_STALLED"
    elif authority.lifecycle != "RUNNING":
        mode, reason = "BLOCKED", f"RUNTIME_{authority.lifecycle}"
    elif authority.block_reason is not None:
        mode, reason = "BLOCKED", authority.block_reason
    elif any(item.status == "BLOCKED" for item in scopes):
        mode = "DEGRADED" if any(item.status != "BLOCKED" for item in scopes) else "BLOCKED"
        reason = "SCOPED_DEPENDENCY_FAILURE"
    elif any(item.status == "RECOVERING" for item in scopes):
        mode, reason = (
            "RECOVERING",
            next(item.reason_code for item in scopes if item.status == "RECOVERING"),
        )
    elif any(not item.read_only for item in plans):
        mode, reason = "MONITORING", None
    else:
        mode, reason = "STANDBY", authority.standby_reason
    return views.RuntimeStatusView(
        lifecycle=authority.lifecycle,
        mode=mode,
        reason_code=reason,
        next_wake_at=None if progress is None else progress.next_wake_at,
        next_retry_at=None
        if state == "STOPPED"
        else min(
            (item.next_retry_at for item in scopes if item.next_retry_at is not None), default=None
        ),
        last_progress_at=None if progress is None else progress.last_progress_at,
        coordinator=views.CoordinatorStatusView(
            state=state, progress_due_at=None if progress is None else progress.progress_due_at
        ),
        scopes=scopes,
    )


def _explicit_entry(session, plan, result, authority, barrier, current, observed, common):
    from trade_plan_monitor.web.plan_service import _explicit_evidence_view
    from trade_plan_monitor.web.routers.plans import (
        ExplicitPlanRuntimeView,
        ExplicitRuleOutcomeView,
    )

    eligibility = explicit_rule_eligibility(
        session=session,
        plan=plan,
        result=result,
        generation=authority.generation,
        barrier=barrier,
        now=observed,
        current=current,
    )
    rules = tuple(views.RuleEligibilityView(**item) for item in eligibility)
    ids = tuple(item.rule_id for item in rules if item.current_actionable)
    runtime = ExplicitPlanRuntimeView(
        symbol=plan.symbol,
        plan_version_id=common["plan_version_id"],
        plan_hash=result.plan_hash,
        activation_revision=result.activation_revision,
        status="CURRENT",
        evaluated_at=result.evaluated_at,
        target_bucket_end=result.target_bucket_end,
        rule_outcomes=tuple(
            ExplicitRuleOutcomeView(
                rule_id=item.rule_id,
                action=item.action.type,
                condition_code=item.condition_evidence.condition.type,
                condition_evidence=_explicit_evidence_view(item.condition_evidence),
                outcome=item.condition_evidence.outcome.value,
                missing_inputs=tuple(
                    value.value for value in item.condition_evidence.missing_inputs
                ),
                blockers=item.blockers,
                suppression_reason=item.suppression_reason,
            )
            for item in result.rule_results
        ),
    )
    return views.ExplicitPlanEntryView(
        **common,
        availability="CURRENT" if current else "CACHED",
        current_actionable=bool(ids),
        explicit_runtime=runtime,
        result_hash=result.result_hash,
        rule_eligibility=rules,
        actionable_rule_ids=ids,
    )


def _counts(entries):
    from trade_plan_monitor.web.routers.dashboard import DashboardCounts

    counts = dict(actionable=0, blocked=0, stale=0, risk=0, low_zone_watch=0, normal=0)
    for entry in entries:
        blocked = entry.scope.status == "BLOCKED"
        stale, risk, low, normal = entry.availability == "CACHED", False, False, False
        if entry.availability == "CURRENT":
            if entry.plan_family == "LEGACY_LOW_BUY":
                decision = entry.decision
                health = decision.data_health.status.value
                blocked |= health in {"BLOCKED", "GAPPED"}
                stale |= health not in {"LIVE", "BLOCKED", "GAPPED"}
                risk = decision.risk_status.value != "CLEAR"
                low = (
                    entry.scope.status == "READY"
                    and health == "LIVE"
                    and decision.signal_type.value == "LOW_ZONE_WATCH"
                )
                from trade_plan_monitor.decision.models import ActionableSignalType

                normal = health == "LIVE" and decision.signal_type.value not in {
                    item.value for item in ActionableSignalType
                }
            elif entry.plan_family == "CONDITION_PLAN":
                risk = any(r.status != "CLEAR" for r in entry.plan_runtime.risks)
                stale |= bool(entry.plan_runtime.data_blockers)
                normal = not entry.current_actionable
            else:
                stale |= any(
                    item.reason_code == "INTRADAY_EXPIRED" for item in entry.rule_eligibility
                )
                risk = any(
                    item.action == "RISK_ALERT" and item.current_actionable
                    for item in entry.rule_eligibility
                )
                normal = all(
                    item.reason_code == "NO_CURRENT_SIGNAL" for item in entry.rule_eligibility
                )
            normal &= (
                entry.scope.status == "READY"
                and not entry.current_actionable
                and not (blocked or stale or risk or low)
            )
        for name, value in dict(
            actionable=entry.current_actionable,
            blocked=blocked,
            stale=stale,
            risk=risk,
            low_zone_watch=low,
            normal=normal,
        ).items():
            counts[name] += int(value)
    return DashboardCounts(**counts)


def _condition_entry(session, authority, evidence, plan, detail, pointer, observed):
    import json
    from datetime import timedelta

    from trade_plan_monitor.state.daily_accounting import DailyAccounting
    from trade_plan_monitor.state.daily_repository import DailyRepository
    from trade_plan_monitor.web.routers.daily_plans import DailyEvaluationApiView

    repo = DailyRepository(session, clock=lambda: observed, id_factory=lambda: str(uuid4()))
    head = repo.get("evaluation-head-" + plan.symbol)
    snapshot = None if head is None else head["payload"]
    reviewed = isinstance(plan, UnifiedTradePlan)
    bound = (
        reviewed
        and snapshot is not None
        and (
            snapshot["plan_version_id"] == detail.id
            and snapshot["plan_hash"] == detail.plan_hash
            and snapshot["activation_revision"] == pointer.revision
        )
    )
    from trade_plan_monitor.runtime.status_authority import (
        condition_completion_matches,
        condition_status_target,
    )

    proof = None if evidence is None else evidence.completion
    desired = condition_status_target(session, plan=plan, now=observed, proof=proof)
    current = (
        bound
        and proof is not None
        and snapshot.get("runtime_generation") == str(authority.generation)
        and proof.runtime_generation == authority.generation
        and proof.configuration_revision == authority.configuration_revision
        and proof.plan_version_id == detail.id
        and proof.plan_hash == detail.plan_hash
        and proof.activation_revision == pointer.revision
        and proof.target == desired
        and evidence.target == desired
        and desired is not None
        and authority.lifecycle == "RUNNING"
        and authority.block_reason is None
        and condition_completion_matches(session, proof=proof, snapshot=snapshot, now=observed)
    )
    alert_only = bool(plan.alert_rules) and not plan.ordinary_rules and not plan.risk_branches
    inventory = (
        {"symbol": plan.symbol, "revision": 0}
        if alert_only
        else DailyAccounting(repo).snapshot(plan.symbol, observed.date())
    )
    current = current and DailyAccounting(repo).evaluation_current(
        snapshot,
        plan_version_id=detail.id,
        content_hash=detail.content_hash,
        inventory=inventory,
        now=observed,
        require_daily_data=not alert_only,
    )
    if current and snapshot.get("minute_target"):
        cutoff = __import__("datetime").datetime.fromisoformat(snapshot["minute_target"])
        current = cutoff <= observed < cutoff + timedelta(seconds=90)
    status = "READY" if current else "BLOCKED" if not reviewed else "WAITING"
    reason = (
        None
        if current
        else "LEGACY_PLANS_REQUIRE_REVIEW"
        if not reviewed
        else ("AWAITING_FIRST_EVALUATION" if not bound else "STATE_UNAVAILABLE")
    )
    target = (
        None
        if desired is None
        else views.IntradayTargetView(kind="INTRADAY", target_end=desired.bucket_end)
        if desired.kind == "INTRADAY"
        else views.OfficialCloseTargetView(kind="OFFICIAL_CLOSE", trade_date=desired.trade_date)
    )
    scope = views.PlanScopeView(
        scope_key="plan:" + plan.symbol,
        kind="PLAN",
        symbol=plan.symbol,
        plan_family="CONDITION_PLAN",
        plan_version_id=UUID(detail.id),
        plan_hash=detail.plan_hash,
        activation_revision=pointer.revision,
        status=status,
        reason_code=reason,
        required_target=target,
        data_cutoff=None,
        next_retry_at=None,
        progress=views.ScopeProgressView(required_count=1, completed_count=int(current)),
        read_only=not current or target is None,
    )
    common = dict(
        symbol=plan.symbol,
        name=plan.name,
        plan_family="CONDITION_PLAN",
        plan_version_id=UUID(detail.id),
        plan_hash=detail.plan_hash,
        activation_revision=pointer.revision,
        observed_at=observed,
        scope=scope,
    )
    if not bound:
        return scope, views.UnavailablePlanEntryView(
            **common,
            availability="UNAVAILABLE",
            current_actionable=False,
            projection_state=status,
            reason_code=reason,
        )
    runtime = DailyEvaluationApiView.model_validate_json(json.dumps(snapshot))
    actionable = (
        current
        and not scope.read_only
        and (
            any(s.executable_qty > 0 for s in runtime.signals)
            or runtime.risk_action.status == "RISK_EXIT"
            and ((runtime.risk_action.core_qty or 0) + (runtime.risk_action.tactical_qty or 0) > 0)
        )
    )
    return scope, views.ConditionPlanEntryView(
        **common,
        availability="CURRENT" if current else "CACHED",
        current_actionable=bool(actionable),
        plan_runtime=runtime,
    )
