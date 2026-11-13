"""Private read-only projection of existing native records and owner proofs.

New owned snapshots retain actual ordinary-rule roots and leaves. Legacy or
unobserved evaluations stay UNKNOWN. This module never runs a trading evaluator or
rescans historical cutover membership to manufacture a positive observation.
"""

from dataclasses import asdict
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from uuid import UUID

from trade_plan_monitor.decision.models import (
    IntradayEvaluationTarget,
    OfficialCloseEvaluationTarget,
)
from trade_plan_monitor.decision.unified_conditions import (
    UnifiedConditionEvidence,
    requires_daily,
    requires_minutes,
)
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_models import activation_is_eligible_on
from trade_plan_monitor.domain.risk_scope import blocks_new_entry, risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan, condition_leaves
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.runtime.status_authority import (
    ConditionInputStamp,
    RuntimeReadAuthority,
    condition_confirmation_inputs,
    condition_daily_admission_matches,
    condition_market_completion_matches,
    condition_status_target,
)
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.daily_state_models import (
    DailyEvaluationState,
    DailyRiskState,
    DailySignalState,
)
from trade_plan_monitor.state.events import MonitorEventLog
from trade_plan_monitor.state.p3_accounting import capital_storage_ready
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.p3_current import current_capital_inputs
from trade_plan_monitor.state.readiness_fact_inputs import (
    recorded_fact_inputs_current,
    recorded_quote_controls_current,
    recorded_signal_facts_current,
)
from trade_plan_monitor.state.readiness_notification_reads import read_owned_notifications
from trade_plan_monitor.state.repositories import MarketReferenceRepository, PlanRepository
from trade_plan_monitor.state.risk_origin_reads import read_risk_origin
from trade_plan_monitor.state.source_action_authority import _condition_evidence_matches
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.web.plan_readiness_models import (
    AxisReadiness,
    ConditionReadiness,
    ExpectedConfirmation,
    ReadinessContext,
    ReadinessDeliveryAttempt,
    ReadinessExecutionState,
    ReadinessMoneyFacts,
    ReadinessNotificationChannel,
    ReadinessNotificationFacts,
    ReadinessObservation,
    ReadinessRiskFacts,
    ReadinessRiskObligation,
    ReadinessRiskOrigin,
    ReadinessSnapshot,
    RuleReadinessFacts,
)
from trade_plan_monitor.web.plan_readiness_summary import (
    inventory_requirements,
    summarize_readiness,
)
from trade_plan_monitor.web.source_coverage_read import read_source_coverage

MAX_READINESS_BYTES = 1024 * 1024


def _bounded_until(now, required):
    """Every applicable bound must be known; absence is never an infinite lease."""
    if not required or any(value is None or value <= now for value in required):
        return None
    return min(required)


def _rule_expiry(now, *, context_expiry, target, daily_event, daily_required,
                 quote, quote_required):
    limits = [context_expiry]
    if target.kind == "INTRADAY":
        limits.append(target.bucket_end + timedelta(seconds=90))
    if daily_required:
        limits.append(datetime.combine(now.date(), time(15), now.tzinfo)
            if daily_event is not None else
            datetime.combine(now.date() + timedelta(days=1), time(), now.tzinfo))
    if quote_required:
        limits.append(None if quote is None else quote.quote_at + timedelta(minutes=5))
    return _bounded_until(now, limits)


def _no_write_identity():
    raise RuntimeError("Readiness cannot allocate business identities")


def authority_identity(authority):
    """The existing runtime read fence, without renewing owner progress."""
    if type(authority) is not RuntimeReadAuthority:
        return None
    return (authority.token, authority.generation, authority.configuration_revision,
            authority.lifecycle, authority.block_reason, authority.standby_reason,
            authority.owner_absent, authority.plans, authority.dependencies,
            authority.notification_configuration,
            authority.notification_service,
            None if authority.progress is None else (
                authority.progress.state, authority.progress.last_progress_at,
                authority.progress.progress_due_at, authority.progress.next_wake_at))


def _owner_current(authority, now):
    if type(authority) is not RuntimeReadAuthority:
        return False
    progress = authority.progress
    return bool(authority.lifecycle == "RUNNING" and not authority.owner_absent
                and authority.block_reason is None and progress is not None
                and progress.state in {"SCHEDULED", "WORKING"}
                and progress.observed_at <= now and progress.last_progress_at is not None
                and progress.last_progress_at <= now and progress.progress_due_at is not None
                and now < progress.progress_due_at)


def _owners(plan):
    return (
        *(("ORDINARY_RULE", rule.rule_id, rule.side, rule)
          for rule in plan.ordinary_rules),
        *(("ALERT_RULE", rule.rule_id, None, rule) for rule in plan.alert_rules),
        *(("RISK_BRANCH", risk_identity(rule), "SELL", rule) for rule in plan.risk_branches),
    )


def _unverified_daily_dependency(plan, kind, rule, now):
    """These native dependencies require independent current daily admission checks.

    Match the native acquisition/admission dependencies, not the presence of
    another rule's daily data. Alerts are independent of ordinary risk admission.
    """
    confirmation = getattr(rule, "confirmation", None)
    condition = getattr(rule, "condition", None)
    reset = getattr(getattr(rule, "independent_signal", None), "reset_condition", None)
    return bool(confirmation and confirmation.kind == "OFFICIAL_DAILY_CLOSE"
        or kind == "RISK_BRANCH"
        or condition is not None and requires_daily(condition)
        or reset is not None and requires_daily(reset)
        or kind == "ORDINARY_RULE" and any(blocks_new_entry({
            "status": "PENDING", "holding_scope": branch.holding_scope}, now.date())
            for branch in plan.risk_branches))


def _validated_evidence(condition, evidence):
    if evidence is None:
        return None
    try:
        value = UnifiedConditionEvidence.model_validate_json(canonical(evidence))
        if not _condition_evidence_matches(condition, value):
            return None
        return value.model_dump(mode="json")
    except (ValueError, TypeError, RecursionError):
        return None


def _current_quote(value, now):
    """Validate the already admitted quote's original times, without extending them."""
    if (not value.current or not value.owner_current or value.native.quote is None
            or not value.quote_controls_current):
        return None
    quote = value.native.quote
    if quote.symbol != value.plan.symbol or quote.quote_at.date() != now.date():
        return None
    try:
        return DailyExecutionQuote.model_validate({**quote.model_dump(), "evaluated_at": now})
    except ValueError:
        return None


def _rule_sources_current(value, kind, rule, now):
    return bool(value.current and value.source.summary.current_review_bound and (
        not _unverified_daily_dependency(value.plan, kind, rule, now)
        or value.daily_current) and value.fact_current.get((kind,
            risk_identity(rule) if kind == "RISK_BRANCH" else rule.rule_id), False))


def _inventory_matches(value):
    return bool(value.native is not None and value.inventory is not None
        and value.native.inventory.model_dump(mode="json") == value.inventory)


def _completed_predecessor(value, rule, target, evaluated_at):
    """Verify the predecessor consumed by this FALSE using existing point reads."""
    prior_id = rule.independent_signal.prior_rule_id
    prior_rules = tuple(prior for prior in value.plan.ordinary_rules
                        if prior.rule_id == prior_id)
    candidates = tuple(signal for signal in value.native.signals
                       if signal.rule_id == prior_id)
    if (len(prior_rules) != 1 or len(candidates) != 1
            or prior_rules[0].independent_signal.mode != "ONCE_PER_RULE"):
        return False
    prior, observed = prior_rules[0], candidates[0]
    row = value.signals.get(observed.signal_id)
    if (row is None or row["id"] != observed.signal_id or row["kind"] != "SIGNAL"
            or row["symbol"] != value.plan.symbol or row["lineage"] != value.plan.plan_id
            or observed.lineage != value.plan.plan_id or observed.side != prior.side
            or observed.plan_version_id != value.details.id
            or observed.review_id != value.details.review_id
            or observed.occurrence_mode != "ONCE_PER_RULE"
            or datetime.fromisoformat(row["updated_at"]) > evaluated_at):
        return False
    try:
        current = DailySignalState.model_validate_json(canonical({**row["payload"],
                                                                "revision": row["revision"]}))
    except ValueError:
        return False
    if (current != observed or current.state != "SIMULATED"
            or not current.simulated_qty == current.planned_qty > 0
            or current.executable_qty != 0 or current.execution_date is None):
        return False
    day = target.trade_date if target.kind == "OFFICIAL_CLOSE" else target.bucket_end.date()
    # SIGNAL has no simulated_at. updated_at only fences later changes; it cannot
    # prove the native same-day minute completion-time requirement.
    return day >= current.execution_date and (
        target.kind == "OFFICIAL_CLOSE" or day > current.execution_date)


def _risk_inputs_match(value):
    for identity, row in value.risks.items():
        if row is None:
            return False
        original = [risk for risk in value.native.risks if risk_identity(risk) == identity]
        if len(original) != 1:
            return False
        current = DailyRiskState.model_validate_json(canonical({**row["payload"],
                                                                "revision": row["revision"]}))
        if current != original[0]:
            return False
        branch = next(rule for kind, key, _, rule in value.owners
            if kind == "RISK_BRANCH" and key == identity)
        if (getattr(branch, "condition", None) is not None
                and not value.fact_current.get(("RISK_BRANCH", identity), False)):
            return False
    return not value.risks or value.native.risk_input_known is True


def _money_inputs_ready(value, requirements, rule, now, *, kind):
    """Input availability is independent of a native monetary predicate's verdict."""
    if not requirements.required:
        return True
    inventory = value.inventory
    if not inventory or not inventory["known"]:
        return False
    if requirements.sellability and any(inventory[name] is None
            for name in ("sellable_core", "sellable_tactical")):
        return False
    if requirements.quote and (not _rule_sources_current(value, kind, rule, now)
                              or _current_quote(value, now) is None):
        return False
    if requirements.cost_basis and value.capital_inputs["retained_basis_fen"] is None:
        return False
    schedules = []
    if requirements.cost_basis:
        schedules.append(value.plan.position.limit.capital_policy.buy_cost_schedule)
    policy = getattr(rule, "pretrade_policy", None)
    if requirements.economics:
        schedules.append(policy.economics.fee_schedule)
        frozen = tuple(item for item in value.native.pretrade or ()
                       if item.rule_id == rule.rule_id)
        if (len(frozen) != 1 or frozen[0].content_hash != value.details.content_hash
                or frozen[0].policy != policy or frozen[0].cutoff > value.native.evaluated_at
                or frozen[0].cutoff.date() != now.date()
                or frozen[0].economics is None
                or frozen[0].economics.outcome not in {"PASS", "FAIL"}):
            return False
    return all(value.plan.symbol in schedule.symbols
               and schedule.effective_from <= now.date() <= schedule.effective_through
               for schedule in schedules)


def _money_results(value, kind, rule, requirements, execution, now):
    """Copy only native results whose exact phase inputs still match this read."""
    policy = getattr(rule, "pretrade_policy", None)
    if (kind != "ORDINARY_RULE" or rule.side != "BUY" or policy is None
            or not _rule_sources_current(value, kind, rule, now)
            or requirements.inventory and not _inventory_matches(value)
            or _current_quote(value, now) is None):
        return None, None
    native = value.native
    if execution.signal_id is not None:
        signal = next((item for item in native.signals
                       if item.signal_id == execution.signal_id), None)
        if signal is None or signal.revision != execution.signal_revision:
            return None, None
        frozen, capital, economics = (signal.pretrade, signal.capital_execution,
                                      signal.pretrade_execution)
        phase, day, quantity, price = (
            "EXECUTION", now.date(), signal.planned_qty, native.quote.price_fen)
        original_day = signal.confirmed_trade_date
    else:
        decisions = tuple(item for item in native.market_linkage or ()
                          if item.rule_id == rule.rule_id)
        prepared = tuple(item for item in native.pretrade or () if item.rule_id == rule.rule_id)
        if len(decisions) != 1 or len(prepared) != 1 or native.daily_evidence is None:
            return None, None
        decision, frozen = decisions[0], prepared[0]
        day = native.daily_evidence.bars[-1].trade_date
        if (decision.content_hash != value.details.content_hash or decision.decision_session != day
                or decision.evidence_cutoff != native.evaluated_at
                or frozen.cutoff != native.evaluated_at):
            return None, None
        phase, original_day = "CONFIRMATION", day
        quantity, price = (decision.calculation.candidate_quantity,
                           native.daily_evidence.bars[-1].close)
        capital, economics = getattr(decision.calculation, "capital", None), frozen.economics
    if (frozen is None or frozen.rule_id != rule.rule_id
            or frozen.content_hash != value.details.content_hash or frozen.policy != policy
            or frozen.decision_session != original_day or frozen.cutoff > native.evaluated_at):
        return None, None
    schedules = ([value.plan.position.limit.capital_policy.buy_cost_schedule]
                 if requirements.cost_basis else [])
    if requirements.economics:
        schedules.append(policy.economics.fee_schedule)
    if any(value.plan.symbol not in schedule.symbols
           or not schedule.effective_from <= day <= schedule.effective_through
           or not schedule.effective_from <= now.date() <= schedule.effective_through
           for schedule in schedules):
        return None, None
    if capital is not None and (
            capital.phase != phase or capital.quantity != (quantity or None)
            or capital.price_fen != price
            or capital.mode != value.plan.position.limit.capital_policy.mode
            or capital.policy_hash != daily_hash("capital-policy-v1",
                value.plan.position.limit.model_dump(mode="json"))
            or capital.total_qty != (
                value.inventory["total_qty"] if value.inventory["known"] else None)
            or capital.inventory_revision != value.inventory["revision"]
            or requirements.cost_basis and (
                capital.book_revision != value.capital_inputs["book_revision"]
                or capital.outcome in {"PASS", "FAIL"}
                and capital.before_fen != value.capital_inputs["retained_basis_fen"])):
        capital = None
    if economics is not None and (
            (economics.outcome == "NONE") != (policy.economics.mode == "NONE")
            or economics.quantity is not None and economics.quantity != quantity):
        economics = None
    return capital, economics


def _execution(value, kind, identity, side, rule, now, *, inputs_ready, observe, context_expiry):
    """Copy one exact original occurrence; old executable quantity grants nothing."""
    unknown = ReadinessExecutionState()
    if (kind != "ORDINARY_RULE" or not value.active or not value.owner_current
            or value.native is None or not value.source.summary.current_review_bound):
        return unknown
    candidates = tuple(signal for signal in value.native.signals if signal.rule_id == identity)
    if len(candidates) != 1:
        return unknown
    original = candidates[0]
    row = value.signals.get(original.signal_id)
    if (row is None or row["kind"] != "SIGNAL" or row["symbol"] != value.plan.symbol
            or row["lineage"] != value.plan.plan_id):
        return unknown
    try:
        signal = DailySignalState.model_validate_json(canonical({**row["payload"],
                                                                 "revision": row["revision"]}))
    except ValueError:
        return unknown
    immutable = ("signal_id", "rule_id", "side", "bucket", "lineage", "planned_qty",
        "confirmed_trade_date", "execution_date", "evidence_fingerprint", "plan_version_id",
        "review_id", "basis_id", "confirmation_kind", "execution_window", "confirmed_at")
    if (any(getattr(original, key) != getattr(signal, key) for key in immutable)
            or signal.side != side or signal.lineage != value.plan.plan_id
            or signal.plan_version_id != value.details.id
            or signal.review_id != value.details.review_id
            or signal.confirmed_at is not None and signal.confirmed_at > now
            or signal.confirmed_trade_date > now.date()):
        return unknown
    consumed = signal.simulated_qty == signal.planned_qty
    clock = now.time().replace(tzinfo=None)
    window = ("UNKNOWN" if signal.execution_date is None or value.calendar_open is None else "OPEN"
        if signal.execution_date == now.date()
        and value.calendar_open
        and (time(9, 30) <= clock < time(11, 30) or time(13) <= clock < time(15)) else "CLOSED")
    eligible, reason = None, None
    if consumed or signal.state in {"EXPIRED", "INVALIDATED"} or signal.risk_invalidated:
        eligible, reason = False, signal.state
    elif window == "CLOSED":
        eligible, reason = False, "OUTSIDE_EXECUTION_SESSION"
    elif (window == "OPEN" and _rule_sources_current(value, kind, rule, now) and inputs_ready
            and _current_quote(value, now) is not None and signal == original
            and _inventory_matches(value) and _risk_inputs_match(value)
            and value.signal_fact_current.get(signal.signal_id, False)
            and value.exception_current.get(signal.signal_id, False)):
        complete = True
        if side == "BUY" and value.plan.schema_version == 9:
            capital = signal.capital_execution
            complete = bool(capital is not None and capital.phase == "EXECUTION"
                and capital.policy_hash == daily_hash("capital-policy-v1",
                    value.plan.position.limit.model_dump(mode="json"))
                and capital.quantity == signal.planned_qty
                and capital.price_fen == value.native.quote.price_fen
                and capital.total_qty == value.inventory["total_qty"]
                and capital.inventory_revision == value.inventory["revision"]
                and (capital.mode != "OPEN_COST_CAP"
                     or capital.book_revision == value.capital_inputs["book_revision"])
                and capital.outcome in {"PASS", "FAIL"})
        policy = getattr(rule, "pretrade_policy", None)
        if policy is not None:
            complete = bool(complete and signal.pretrade is not None
                and signal.pretrade.content_hash == value.details.content_hash
                and signal.pretrade.policy == policy
                and signal.pretrade_execution is not None
                and signal.pretrade_execution.outcome in {"NONE", "PASS", "FAIL"})
        if complete:
            eligible = bool(signal.state == "READY" and not signal.blockers
                            and signal.executable_qty == signal.planned_qty)
            reason = None if eligible else next(iter(signal.blockers), "DEPENDENCY_UNVERIFIED")
    current = bool(_rule_sources_current(value, kind, rule, now) and signal == original
                   and eligible is not None)
    expiry = (_rule_expiry(now, context_expiry=context_expiry, target=value.target,
        daily_event=value.confirmation[0],
        daily_required=_unverified_daily_dependency(value.plan, kind, rule, now),
        quote=value.native.quote, quote_required=True) if current else None)
    return ReadinessExecutionState(approved_quantity=signal.planned_qty, consumed=consumed,
        execution_window=signal.execution_window, window_state=window,
        eligible=eligible, reason=reason,
        signal_id=signal.signal_id, signal_revision=row["revision"],
        execution_date=signal.execution_date, blockers=signal.blockers,
        observation=observe(row["id"], availability="CURRENT" if current else "CACHED",
                            as_of=datetime.fromisoformat(row["updated_at"]), expires=expiry))


def _leaves(condition, path, evidence=None, *, reason="DEPENDENCY_UNVERIFIED", reference=None):
    """Copy actual leaf outcomes; do not recompute ALL/ANY or predicate truth."""
    raw = condition.model_dump(mode="json")
    evidence = _validated_evidence(condition, evidence)
    children = raw.get("conditions")
    if children is not None:
        proofs = () if evidence is None else evidence.get("children", ())
        if len(proofs) != len(children):
            proofs = (None,) * len(children)
        return tuple(leaf for index, child in enumerate(condition.conditions)
                     for leaf in _leaves(child, f"{path}.conditions[{index}]", proofs[index],
                                         reason=reason, reference=reference))
    if evidence is None:
        return (ConditionReadiness(condition_path=path, state="UNKNOWN", reason=reason),)
    outcome = evidence["outcome"]
    if outcome == "MISSING_INPUT":
        return (ConditionReadiness(condition_path=path, state="MISSING_INPUT",
            reason="HUMAN_EVIDENCE_REQUIRED" if raw["type"] == "REVIEWED_FACT"
            else "MISSING_DATA"),)
    return (ConditionReadiness(condition_path=path,
        state="CONDITION_TRUE" if outcome == "SATISFIED" else "CONDITION_FALSE",
        evidence_refs=(reference,)),)


def _recorded_fact_sources(work, details, plan, owners, native, now):
    current, bindings = {}, []
    for kind, identity, _, rule in owners:
        root, target = None, None
        if kind == "ORDINARY_RULE":
            rows = [row for row in native.ordinary_evaluations or () if row.rule_id == identity]
            if len(rows) == 1:
                root, target = rows[0].evidence, rows[0].target
            elif not rows:
                decisions = [row for row in native.market_linkage or () if row.rule_id == identity]
                if len(decisions) == 1:
                    decision = decisions[0]
                    if (decision.confirmation
                            and decision.content_hash == details.content_hash
                            and decision.evidence_cutoff == native.evaluated_at
                            and rule.confirmation.kind == "OFFICIAL_DAILY_CLOSE"
                            and native.daily_evidence is not None
                            and decision.decision_session
                            == native.daily_evidence.bars[-1].trade_date):
                        root = decision.confirmation[0]
                        target = OfficialCloseEvaluationTarget(trade_date=decision.decision_session)
        elif kind == "ALERT_RULE":
            rows = [row for row in native.alerts if row.rule_id == identity]
            if len(rows) == 1 and len(rows[0].evidence) == 1:
                root = UnifiedConditionEvidence.model_validate_json(canonical(rows[0].evidence[0]))
                target = (OfficialCloseEvaluationTarget(trade_date=rows[0].confirmed_trade_date)
                    if rule.confirmation.kind == "OFFICIAL_DAILY_CLOSE" else
                    IntradayEvaluationTarget(bucket_end=rows[0].confirmed_at))
        elif kind == "RISK_BRANCH" and rule.kind == "SEVERE_TECHNICAL":
            rows = [row for row in native.risk_evaluations or ()
                if row.risk_identity == identity and row.kind == rule.kind]
            if len(rows) == 1:
                root, target = rows[0].evidence, rows[0].target
        condition = getattr(rule, "condition", None)
        has_reviewed_fact = bool(condition is not None and any(
            node.type == "REVIEWED_FACT" for node in condition_leaves(condition)))
        # Staged native rules may skip confirmation once their signal exists.
        # An absent root cannot create a current condition observation, but a
        # pure market rule has no manual inputs to invalidate that signal.
        valid, binding = ((True, ()) if (kind == "RISK_BRANCH"
            and rule.kind == "ORDINARY_TECHNICAL") or (
                condition is not None and not has_reviewed_fact) else
            (False, ()) if condition is None or root is None else
            recorded_fact_inputs_current(work, details=details, owner_kind=kind,
                owner_id=identity, condition=condition, evidence=root, snapshot=native,
                target=target, now=now))
        current[(kind, identity)] = valid
        bindings.append((kind, identity, valid, binding))
    return current, tuple(bindings)


def _exception_sources(work, reads, signals, now):
    from trade_plan_monitor.runtime.market_exceptions import exception_signal_current

    current, bindings = {}, []
    for identity, row in signals.items():
        if row is None:
            current[identity] = False
            continue
        payload = row["payload"]
        calculation = (payload.get("market_linkage") or {}).get("calculation", {})
        approval = calculation.get("approval")
        refs = ()
        if approval is not None:
            if not approval.get("candidate_id") or not approval.get("event_id"):
                current[identity] = False
                continue
            refs = tuple(reads.daily(approval[key]) for key in ("candidate_id", "event_id"))
        current[identity] = exception_signal_current(work.daily, payload, now)
        bindings.append((identity, current[identity], canonical(refs)))
    return current, tuple(bindings)


def _load(session, authority, version_id, now):
    work = SimpleNamespace(
        daily=DailyRepository(session, clock=lambda: now, id_factory=_no_write_identity),
        plans=PlanRepository(session, clock=lambda: now, id_factory=_no_write_identity,
                             events=MonitorEventLog(session, clock=lambda: now)),
    )
    source = read_source_coverage(work, version_id)
    if source is None:
        return None
    details = source.details
    plan = load_plan_json(details.payload_json)
    if not isinstance(plan, UnifiedTradePlan):
        raise ValueError("Readiness requires a supported native saved plan")
    owners = _owners(plan)
    requirements = tuple(inventory_requirements(plan, owner_kind=kind, owner_id=identity)
                         for kind, identity, _, _ in owners)
    reads = ActionOwnerReader(work)
    active, activation = reads.active(plan.symbol), reads.activation(plan.symbol)
    bound_active = bool(active and activation and active.plan_version_id == version_id
        and activation.plan_version_id == version_id and active.revision == activation.revision
        and active.activated_at == activation.changed_at and active.activated_at <= now
        and details.status == "ACTIVE")
    inventory = (DailyAccounting(work.daily).snapshot(plan.symbol, now.date())
                 if any(req.inventory for req in requirements) else None)
    calendar = MarketReferenceRepository(session).list_trading_days(
        plan.market, now.date(), now.date())
    calendar_open = None if not calendar else calendar[0].is_open
    book = (CapitalRepository(session).get(plan.symbol)
            if any(req.simulation_book for req in requirements) and capital_storage_ready(session)
            else None)
    capital_inputs = (current_capital_inputs(DailyAccounting(work.daily), plan.symbol, now)
        if any(req.cost_basis for req in requirements) else None)
    head = reads.daily("evaluation-head-" + plan.symbol)
    payload = None if head is None else head["payload"]
    if authority is not None and len(authority.plans) > 10:
        raise ValueError("Readiness exceeds the existing active-symbol admission bound")
    evidence = next((item for item in (() if authority is None else authority.plans)
                     if item.symbol == plan.symbol), None)
    owner_current = bool(bound_active and _owner_current(authority, now)
        and evidence is not None and evidence.plan_version_id == version_id
        and evidence.plan_hash == details.plan_hash
        and evidence.activation_revision == active.revision
        and evidence.plan_family == "CONDITION_PLAN")
    proof = None if evidence is None else evidence.completion
    # The expired locked-risk extension has no bounded readiness proof in this slice.
    target = (condition_status_target(session, plan=plan, now=now, proof=proof)
              if activation_is_eligible_on(plan.activation, now.date()) else None)
    bound_head = bool(bound_active and payload and payload["plan_version_id"] == version_id
        and payload["plan_hash"] == details.plan_hash
        and payload["content_hash"] == details.content_hash
        and payload["review_id"] == details.review_id
        and payload["activation_revision"] == active.revision)
    # Validate the native shape without accepting a client-supplied evaluation.
    native = (None if not bound_head
              else DailyEvaluationState.model_validate_json(canonical(payload)))
    signals = {}
    if native is not None:
        # Only exact, unambiguous current ordinary owners need point reads.
        # Native snapshots allow history; that is not permission to select one.
        for kind, identity, side, _ in owners:
            if kind != "ORDINARY_RULE":
                continue
            candidates = tuple(signal for signal in native.signals if signal.rule_id == identity)
            if len(candidates) != 1:
                continue
            signal = candidates[0]
            if (signal.side == side and signal.lineage == plan.plan_id
                    and signal.plan_version_id == version_id
                    and signal.review_id == details.review_id):
                signals[signal.signal_id] = reads.daily(signal.signal_id)
    # Read only the existing exact risk IDs. These references are retained as
    # unverified historical evidence; matching an active branch is not provenance.
    risks = {identity: reads.daily(daily_hash("daily-risk-obligation-v1", {
        "symbol": plan.symbol, "kind": identity}))
        for kind, identity, _, _ in owners if kind == "RISK_BRANCH"}
    risk_origins = {identity: None if row is None else read_risk_origin(
        work, cause_id=row["id"], now=now) for identity, row in risks.items()}
    current = bool(native and owner_current and proof is not None
        and proof.symbol == plan.symbol and proof.plan_family == "CONDITION_PLAN"
        and proof.plan_version_id == version_id and proof.plan_hash == details.plan_hash
        and proof.activation_revision == active.revision
        and proof.runtime_generation == authority.generation
        and native.runtime_generation == str(authority.generation)
        and proof.configuration_revision == authority.configuration_revision
        and target is not None and proof.target == evidence.target == target
        and condition_market_completion_matches(session, proof=proof, snapshot=payload, now=now))
    prior_current = current
    fact_current, fact_binding = (_recorded_fact_sources(work, details, plan, owners, native, now)
        if current else ({}, ()))
    quote_controls_current, quote_binding = (recorded_quote_controls_current(work,
        details=details, snapshot=native, now=now) if current and (
            native.signals or any(req.quote for req in requirements)) else (False, ()))
    exception_current, exception_binding = _exception_sources(work, reads, signals, now)
    signal_fact_current, signal_fact_binding = {}, []
    for identity, row in signals.items():
        valid, binding = ((False, ()) if row is None or native is None else
            recorded_signal_facts_current(work, plan=plan, signal=row["payload"], snapshot=native))
        signal_fact_current[identity] = valid
        signal_fact_binding.append((identity, valid, binding))
    daily_current = bool(native and native.daily_evidence is not None
        and condition_daily_admission_matches(proof=proof, snapshot=payload, now=now,
            admission=None if evidence is None else evidence.daily_admission))
    if current and native.minute_target is not None:
        current = native.minute_target <= now < native.minute_target + timedelta(seconds=90)
    confirmation = (condition_confirmation_inputs(session, plan=plan, now=now)
                    if bound_active else (None, None, None, False, ()))
    # These are existing values for the second read, not a new proof/hash domain.
    binding = (source.summary.model_dump_json(), details.payload_json, details.revision,
        details.status, details.review_id, details.review_revision, details.review_confirmed_at,
        active, activation, canonical(inventory), None if book is None else book.model_dump_json(),
        None if head is None else (head["id"], head["revision"], canonical(payload)),
        current, target, confirmation, canonical(capital_inputs), canonical(signals),
        canonical(signal_fact_binding),
        calendar_open, fact_binding, quote_binding, exception_binding,
        tuple((identity, None if origin is None else origin.binding)
              for identity, origin in risk_origins.items()),
        tuple((identity, None if row is None else (row["revision"], canonical(row["payload"])))
              for identity, row in risks.items()))
    value = SimpleNamespace(source=source, details=details, plan=plan, owners=owners,
        requirements=requirements, active=bound_active, inventory=inventory, book=book,
        capital_inputs=capital_inputs,
        signals=signals,
        calendar_open=calendar_open,
        native=native, payload=payload, proof=proof, target=target,
        current=current, prior_current=prior_current,
        confirmation=confirmation, binding=binding,
        owner_current=owner_current,
        fact_current=fact_current, quote_controls_current=quote_controls_current,
        exception_current=exception_current,
        signal_fact_current=signal_fact_current,
        daily_current=daily_current,
        activation_revision=active.revision if bound_active else None, risks=risks,
        risk_origins=risk_origins)
    value.notifications, notification_binding = read_owned_notifications(
        work, value=value, authority=authority, now=now)
    value.binding = (*binding, notification_binding)
    return value


def _notification(value, authority, kind, identity, *, observe):
    """Current configuration and exact historical receipts are independent facts."""
    from trade_plan_monitor.notifications.channels import DeliveryChannel

    configuration = None if authority is None else authority.notification_configuration
    configured = {} if configuration is None else {
        item.channel: item for item in configuration.channels}
    original = value.notifications.get((kind, identity))
    event = None if original is None else original.event
    classification = None if original is None else original.classification
    attempts = {}
    for item in (() if original is None else original.attempts):
        try:
            attempts[item.channel] = ReadinessDeliveryAttempt(**asdict(item))
        except TypeError, ValueError:
            continue
    channels = tuple(ReadinessNotificationChannel(channel=channel,
        configured=None if configuration is None else channel in configured,
        enabled=None if channel not in configured else configured[channel].enabled,
        historical_status=None if classification is None else classification.status,
        historical_updated_at=None if classification is None else classification.updated_at,
        latest_attempt=attempts.get(channel)) for channel in DeliveryChannel
        if configuration is not None or classification is not None or channel in attempts)
    if event is None:
        return None if not channels else ReadinessNotificationFacts(channels=channels,
            observation=observe("runtime:" + str(authority.generation),
                availability="PERSISTED_ONLY"))
    try:
        return ReadinessNotificationFacts(event_id=event.event_id, cause_id=event.cause_id,
            target=original.target, created_at=event.created_at, channels=channels,
            observation=observe(str(event.event_id), availability="PERSISTED_ONLY",
                as_of=event.created_at))
    except ValueError:
        return None if configuration is None else ReadinessNotificationFacts(
            observation=observe("runtime:" + str(authority.generation),
                availability="PERSISTED_ONLY"), channels=tuple(item.model_copy(update={
                    "historical_status": None, "historical_updated_at": None,
                    "latest_attempt": None}) for item in channels))


def _alert_notification_fulfilled(value, rule, alert):
    """An exact latest native receipt fulfills this obligation, never a new send."""
    from trade_plan_monitor.notifications.channels import DeliveryChannel
    from trade_plan_monitor.notifications.dispatcher import DeliveryAttemptStatus

    original = value.notifications.get(("ALERT_RULE", alert.rule_id))
    if (original is None or original.event is None or original.target is None
            or original.target != rule.facts.evaluated_target
            or original.target != rule.facts.expected_target
            or original.event.cause_id != alert.cause_id
            or original.event.rule_id != alert.rule_id):
        return False
    attempts = tuple(item for item in original.attempts if item.channel is DeliveryChannel.IN_APP)
    return bool(len(attempts) == 1 and attempts[0].event_id == original.event.event_id
        and attempts[0].status is DeliveryAttemptStatus.DELIVERED
        and attempts[0].delivered_at is not None and attempts[0].error_code is None
        and attempts[0].next_retry_at is None)


def _notification_service_axis(value, authority, result, now, *, observe, expiry):
    """Prove only exact alert fulfillment or native Schema5 empty-signal FALSE."""
    from trade_plan_monitor.runtime.daily_service import _alert_only

    service = None if authority is None else authority.notification_service
    native = value.native
    if (service is None or not value.current or not value.owner_current
            or native is None
            or service.runtime_generation != authority.generation
            or service.configuration_revision != authority.configuration_revision
            or service.storage.configuration != authority.notification_configuration
            or value.proof not in service.completions
            or not native.evaluated_at <= service.storage.started_at <= (
                service.storage.completed_at) <= now < service.valid_until
            or native.signals or native.risks or native.exception_candidates
            or native.risk_action.status != "NONE"
            or any(getattr(native.risk_action, field) is not None
                   for field in ("branch", "cause_id", "cause_revision"))
            or len(native.alerts) != len(value.plan.alert_rules)
            or len({alert.rule_id for alert in native.alerts}) != len(native.alerts)
            or {alert.rule_id for alert in native.alerts} != {
                rule.rule_id for rule in value.plan.alert_rules}
            or not result.rules
            or any(axis.state not in {"PASS", "NOT_APPLICABLE"} for axis in result.axes
                   if axis.axis != "NOTIFICATION_DELIVERY")):
        return None
    if _alert_only(value.plan):
        rules = {rule.facts.owner_id: rule for rule in result.rules}
        for alert in native.alerts:
            rule = rules.get(alert.rule_id)
            if rule is None or rule.facts.owner_kind != "ALERT_RULE":
                return None
            if alert.outcome == "UNSATISFIED" and rule.state == "CONDITION_FALSE":
                continue
            if (alert.outcome != "SATISFIED" or rule.state != "CONDITION_TRUE"
                    or not _alert_notification_fulfilled(value, rule, alert)):
                return None
    elif (value.plan.schema_version != 5 or not value.plan.ordinary_rules
            or value.plan.risk_branches
            or any(rule.state != "CONDITION_FALSE" for rule in result.rules)
            or any(alert.outcome != "UNSATISFIED" for alert in native.alerts)):
        return None
    bound = _bounded_until(now, (expiry, service.valid_until, service.progress_due_at))
    if bound is None:
        return None
    return AxisReadiness(axis="NOTIFICATION_DELIVERY", state="PASS",
        observation=observe("runtime:" + str(authority.generation),
            as_of=service.storage.completed_at, expires=bound))


def _risk_facts(value, identity, rule, now, *, observe, context_expiry, review_ok):
    """Copy exact native observations; maintenance also needs the current cause fence."""
    row = value.risks.get(identity)
    state, obligation, origin = None, None, None
    verified_origin = value.risk_origins.get(identity)
    if row is not None and row["kind"] == "RISK" and row["symbol"] == value.plan.symbol:
        state = DailyRiskState.model_validate_json(canonical({**row["payload"],
            "revision": row["revision"]}))
        if (state.risk_id == row["id"] and risk_identity(state) == identity
                and state.kind == rule.kind):
            obligation = ReadinessRiskObligation(risk_id=row["id"], revision=row["revision"],
                kind=state.kind, status=state.status,
                confirmed_trade_date=state.confirmed_trade_date,
                earliest_execution_date=state.earliest_execution_date,
                fulfilled_at=state.fulfilled_at, blockers=state.blockers)
        else:
            state, verified_origin = None, None
    if verified_origin is not None and obligation is not None:
        original = verified_origin.origin
        origin = ReadinessRiskOrigin(evaluation_id=verified_origin.cause.origin_evaluation_id,
            plan_version_id=original.plan_version_id, content_hash=original.content_hash,
            review_id=original.review_id, activation_revision=original.activation_revision,
            evaluated_at=original.evaluated_at, birth=verified_origin.birth)
    current = None
    minutes_required = rule.condition is not None and requires_minutes(rule.condition)
    sources = bool(review_ok and value.prior_current and value.daily_current
        and (not minutes_required or value.current)
        and value.fact_current.get(("RISK_BRANCH", identity), False))
    if sources:
        rows = tuple(item for item in value.native.risk_evaluations or ()
            if (item.risk_identity, item.kind) == (identity, rule.kind))
        if len(rows) == 1:
            candidate = rows[0]
            # DailyEvaluationState already verifies native owner, dates, consumed
            # source/target, price/basis and time. Severe trees still need the
            # exact current plan's structure, never old technical_evidence.
            if (candidate.ordinary_close is not None or candidate.evidence is not None
                    and _validated_evidence(rule.condition,
                        candidate.evidence.model_dump(mode="json")) is not None):
                current = candidate
    same_state = bool(state is not None and value.native is not None and len([
        item for item in value.native.risks if risk_identity(item) == identity]) == 1
        and next(item for item in value.native.risks if risk_identity(item) == identity) == state)
    skip = False
    if (sources and current is None and state is not None and same_state and origin is not None
            and rule.kind == "ORDINARY_TECHNICAL" and state.status in {"CONFIRMED", "FULFILLED"}
            and not any(item.risk_identity == identity for item in (
                *(value.native.risk_evaluations or ()), *(value.native.risk_births or ())))):
        # The owned production proof guarantees the native capture path ran.
        # FULFILLED resets to a new cause after cutover; that is never a skip.
        close = value.native.daily_evidence.bars[-1].trade_date
        cutover = state.cause_cutover_at
        skip = (state.status == "CONFIRMED" or cutover is not None
            and datetime.combine(close, time(15), now.tzinfo) <= cutover)
    complete = current is not None
    if current is not None and current.ordinary_close is not None:
        complete = not current.ordinary_close.blockers
    elif current is not None:
        pending = [current.evidence]
        while pending:
            proof = pending.pop()
            complete = complete and proof.outcome != "MISSING_INPUT"
            pending.extend(proof.children)
    maintained = bool(sources and same_state and _inventory_matches(value)
        and (state.status == "CLEAR" or origin is not None) and (current is not None or skip))
    maintained = maintained and (complete or skip)
    target = (None if value.native is None or value.native.daily_evidence is None else
        value.target if minutes_required else OfficialCloseEvaluationTarget(
            trade_date=value.native.daily_evidence.bars[-1].trade_date))
    expiry = (None if not maintained else _rule_expiry(now, context_expiry=context_expiry,
        target=target, daily_event=value.confirmation[0], daily_required=True,
        quote=None, quote_required=False))
    stamp = None if value.native is None else value.native.evaluated_at
    refs = ("risk-inputs-unverified",) if row is None else (row["id"],)
    if value.proof is not None and isinstance(value.proof.input_stamp, ConditionInputStamp):
        refs += (value.proof.input_stamp.immutable_record_id,)
    maintenance = AxisReadiness(axis="DATA_EVALUATION",
        state="PASS" if maintained else "UNKNOWN",
        reason=None if maintained else "DEPENDENCY_UNVERIFIED",
        observation=observe(*refs, availability="CURRENT" if maintained else
            "CACHED" if value.native else "UNAVAILABLE", as_of=stamp, expires=expiry))
    return ReadinessRiskFacts(current=current, obligation=obligation, origin=origin,
        maintenance=maintenance)


def read_readiness_binding(session, authority, version_id, now):
    with session.no_autoflush:
        loaded = _load(session, authority, version_id, now)
        return None if loaded is None else loaded.binding


def read_plan_readiness(session, authority, version_id, now):
    """Assemble all native owners in one caller-owned SQLite read transaction."""
    with session.no_autoflush:
        value = _load(session, authority, version_id, now)
        if value is None:
            return None, None
        summary = value.source.summary
        context = ReadinessContext(plan_version_id=UUID(version_id),
            content_hash=value.details.content_hash, source_hash=summary.source_hash,
            coverage_hash=summary.coverage_evidence_hash,
            review_receipt_hash=summary.coverage_review_receipt_hash,
            activation_revision=value.activation_revision,
            runtime_generation=None if authority is None else authority.generation,
            inventory_revision=None if value.inventory is None else value.inventory["revision"],
            book_revision=(value.capital_inputs["book_revision"] if value.capital_inputs is not None
                           else None if value.book is None else value.book.revision))
        day_end = datetime.combine(now.date() + timedelta(days=1), time(), now.tzinfo)
        owner_expiry = (authority.progress.progress_due_at if value.owner_current else None)
        context_expiry = _bounded_until(now, (owner_expiry, day_end))

        def observation(*refs, availability="CURRENT", expires=None, as_of=None):
            return ReadinessObservation(context=context, availability=availability,
                observed_at=now, as_of=as_of, expires_at=expires,
                evidence_refs=tuple(refs))

        source_observation = observation("plan:" + version_id,
            "coverage:" + (summary.coverage_bundle_hash or "unavailable"),
            expires=context_expiry)
        upgrade = summary.reason == "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        source_axis = AxisReadiness(axis="SOURCE_COVERAGE",
            state="UNKNOWN" if upgrade else "PASS" if summary.coverage_complete else "BLOCKED",
            reason="UPGRADE_REQUIRED" if upgrade else None if summary.coverage_complete
            else "SOURCE_REVIEW_REQUIRED", observation=source_observation)
        review_ok = value.active and summary.current_review_bound
        review_axis = AxisReadiness(axis="REVIEW_ACTIVATION",
            state="UNKNOWN" if upgrade else "PASS" if review_ok else "BLOCKED",
            reason="UPGRADE_REQUIRED" if upgrade else None if review_ok
            else "SOURCE_REVIEW_REQUIRED", observation=source_observation)
        owner_ok = value.owner_current
        runtime_axis = AxisReadiness(axis="RUNTIME_OWNERSHIP",
            state="PASS" if owner_ok else "UNKNOWN",
            reason=None if owner_ok else "AUTHORITY_UNAVAILABLE",
            observation=observation("runtime:" + str(context.runtime_generation),
                availability="CURRENT" if owner_ok else "PERSISTED_ONLY",
                expires=authority.progress.progress_due_at if owner_ok else None))
        evaluated_at = None if value.native is None else value.native.evaluated_at
        availability = "CURRENT" if value.current else "CACHED" if value.native else "UNAVAILABLE"
        expiry = (_bounded_until(now, (context_expiry,
            value.native.minute_target + timedelta(seconds=90)))
            if value.current and value.native.minute_target else context_expiry
            if value.current else None)
        evaluation_ref = (None if value.proof is None
                          or not isinstance(value.proof.input_stamp, ConditionInputStamp) else
                          value.proof.input_stamp.immutable_record_id)
        data_observation = observation(evaluation_ref or "evaluation-head-" + value.plan.symbol,
            availability=availability, expires=expiry, as_of=evaluated_at)
        axes = [source_axis, review_axis, runtime_axis, AxisReadiness(axis="DATA_EVALUATION",
            state="PASS" if value.current else "UNKNOWN",
            reason=None if value.current else "AUTHORITY_UNAVAILABLE",
            observation=data_observation)]
        applicable = any(req.required for req in value.requirements)
        money_ready = tuple(_money_inputs_ready(value, req, rule, now, kind=kind)
            for (kind, _, _, rule), req in zip(value.owners, value.requirements, strict=True))
        inventory_ok = all(money_ready)
        money_expiry = _bounded_until(now, (context_expiry, *(
            (None if value.native is None or value.native.quote is None else
             value.native.quote.quote_at + timedelta(minutes=5),)
            if any(req.quote for req in value.requirements) else ())))
        axes.append(AxisReadiness(axis="INVENTORY_CAPITAL",
            state="NOT_APPLICABLE" if not applicable else "PASS" if inventory_ok else "UNKNOWN",
            reason=None if inventory_ok else "DEPENDENCY_UNVERIFIED",
            observation=observation("inventory:" + str(context.inventory_revision),
                                    expires=money_expiry)))
        # Existing global IN_APP counts certify neither a rule's selected channel
        # nor its exact successful receipt/configuration. No test send is attempted.
        axes.append(AxisReadiness(axis="NOTIFICATION_DELIVERY", state="UNKNOWN",
                                  reason="DELIVERY_UNVERIFIED"))
        rules = []
        for (kind, identity, side, rule), requirements, inputs_ready in zip(
                value.owners, value.requirements, money_ready, strict=True):
            evidence, root = None, None
            actual_target, actual_time = None, None
            matching = None
            risk = None
            rule_target = value.target
            confirmation = getattr(rule, "confirmation", None)
            if (confirmation is not None and rule_target is not None
                    and (confirmation.kind == "OFFICIAL_DAILY_CLOSE")
                    != (rule_target.kind == "OFFICIAL_CLOSE")):
                rule_target = None
            if (confirmation is not None and confirmation.kind == "OFFICIAL_DAILY_CLOSE"
                    and value.prior_current and value.native.daily_evidence is not None):
                # The existing completion proof binds this exact consumed series,
                # including a daily confirmation inside a mixed intraday cycle.
                rule_target = OfficialCloseEvaluationTarget(
                    trade_date=value.native.daily_evidence.bars[-1].trade_date)
            if kind == "ORDINARY_RULE" and value.prior_current and review_ok:
                matching = next((row for row in value.native.ordinary_evaluations or ()
                                 if row.rule_id == identity), None)
                if matching is not None and matching.target == rule_target:
                    evidence = _validated_evidence(
                        rule.condition, matching.evidence.model_dump(mode="json"))
                    if evidence is not None:
                        root = evidence["outcome"]
                        actual_target, actual_time = matching.target, matching.evaluated_at
                elif (matching is None and rule_target is not None
                        and rule_target.kind == "OFFICIAL_CLOSE"):
                    # Market admission can record S0 before a monetary early return.
                    decisions = tuple(row for row in value.native.market_linkage or ()
                                      if row.rule_id == identity)
                    if len(decisions) == 1:
                        decision = decisions[0]
                        if (decision.content_hash == value.details.content_hash
                                and decision.decision_session == rule_target.trade_date
                                and decision.evidence_cutoff == value.native.evaluated_at
                                and decision.confirmation):
                            evidence = _validated_evidence(rule.condition,
                                decision.confirmation[0].model_dump(mode="json"))
                            if evidence is not None:
                                root = evidence["outcome"]
                                actual_target, actual_time = rule_target, decision.evidence_cutoff
            if kind == "ALERT_RULE" and value.prior_current and review_ok:
                matching = next((alert for alert in value.native.alerts
                                 if alert.rule_id == identity), None)
                target_matches = bool(matching and rule_target is not None
                    and matching.confirmation_kind == confirmation.kind
                    and matching.confirmed_at is not None
                    and (matching.confirmed_trade_date == rule_target.trade_date
                         if rule_target.kind == "OFFICIAL_CLOSE" else
                         matching.confirmed_at == rule_target.bucket_end
                         and matching.confirmed_trade_date == rule_target.bucket_end.date()))
                if target_matches and len(matching.evidence) == 1:
                    proposed = _validated_evidence(rule.condition, matching.evidence[0])
                    if proposed is not None and proposed["outcome"] == matching.outcome:
                        evidence, root = proposed, matching.outcome
                        actual_target, actual_time = rule_target, evaluated_at
            if kind == "RISK_BRANCH":
                risk = _risk_facts(value, identity, rule, now, observe=observation,
                    context_expiry=context_expiry, review_ok=review_ok)
                matching = risk.current
                if matching is not None:
                    actual_target, actual_time = matching.target, matching.evaluated_at
                    rule_target = matching.target
                    if matching.evidence is not None:
                        evidence = matching.evidence.model_dump(mode="json")
                        root = matching.evidence.outcome
            condition = getattr(rule, "condition", None)
            daily_unverified = (actual_target is not None
                and _unverified_daily_dependency(value.plan, kind, rule, now)
                and not value.daily_current)
            fact_unverified = (actual_target is not None
                and not value.fact_current.get((kind, identity), False))
            if daily_unverified or fact_unverified:
                # Keep actual target/time as historical observation metadata,
                # but do not promote its old root/leaves into CURRENT truth.
                evidence, root = None, None
            if condition is None:
                leaves = ()
            else:
                leaves = _leaves(condition, "condition",
                    evidence, reference=evaluation_ref)
            rule_observation = None if value.native is None else data_observation
            expected_confirmation = None
            if actual_target is not None and not daily_unverified and not fact_unverified:
                rule_observation = observation(evaluation_ref,
                    availability="CURRENT" if value.current or risk is not None
                        and risk.current is not None else "CACHED",
                    expires=_rule_expiry(now, context_expiry=context_expiry, target=actual_target,
                        daily_event=value.confirmation[0], daily_required=
                        _unverified_daily_dependency(value.plan, kind, rule, now),
                        quote=value.native.quote, quote_required=requirements.quote),
                    as_of=actual_time)
                future = (value.confirmation[0] if confirmation.kind == "OFFICIAL_DAILY_CLOSE"
                          else value.confirmation[1]) if confirmation is not None else None
                if kind == "RISK_BRANCH":
                    future = None  # Risk comparisons do not use ordinary entry-rule wait policy.
                later = bool(future is not None and (
                    future.trade_date > actual_target.trade_date
                    if future.kind == actual_target.kind == "OFFICIAL_CLOSE" else
                    not value.current and future.kind == actual_target.kind == "INTRADAY"
                    and future.bucket_end > actual_target.bucket_end))
                # An actual complete FALSE proves this rule reached evaluation.
                # No occurrence/predecessor/admission early return becomes a wait.
                simple_inputs = (not any((requirements.quote, requirements.simulation_book,
                    requirements.cost_basis, requirements.fees, requirements.economics))
                    and (not requirements.inventory or bool(value.inventory
                        and value.inventory["known"]
                        and (not requirements.sellability or all(value.inventory[name] is not None
                            for name in ("sellable_core", "sellable_tactical"))))))
                future_day = (None if future is None else future.trade_date
                              if future.kind == "OFFICIAL_CLOSE" else future.bucket_end.date())
                validity = getattr(rule, "validity", None)
                date_valid = bool(validity is None or validity.mode != "DATE_RANGE"
                    or future_day is not None
                    and validity.start_date <= future_day <= validity.end_date)
                simple_gate = (kind == "ALERT_RULE" or kind == "ORDINARY_RULE"
                    and value.plan.schema_version == 5
                    and (rule.independent_signal.mode == "ONCE_PER_RULE"
                        or rule.independent_signal.mode == "AFTER_RULE_COMPLETED"
                        and _completed_predecessor(value, rule, actual_target, actual_time)))
                no_occurrence = not any(signal.rule_id == identity
                                        for signal in value.native.signals)
                complete_leaves = bool(leaves and all(leaf.state in {
                    "CONDITION_TRUE", "CONDITION_FALSE"} for leaf in leaves))
                no_manual = condition is not None and not any(leaf.type == "REVIEWED_FACT"
                                    for leaf in condition_leaves(condition))
                if later and complete_leaves and not (
                        simple_gate and date_valid and no_occurrence
                        and no_manual and simple_inputs):
                    rule_observation = observation(evaluation_ref, availability="CACHED",
                                                   as_of=actual_time)
                if (later and date_valid and simple_gate and root == "UNSATISFIED" and simple_inputs
                        and complete_leaves and no_manual and no_occurrence):
                    rule_target = future
                    partial_complete = (future.kind == "OFFICIAL_CLOSE" or value.confirmation[3])
                    event_at = (datetime.combine(future.trade_date, time(15), now.tzinfo)
                                if future.kind == "OFFICIAL_CLOSE" else future.bucket_end)
                    wait_observation = observation(evaluation_ref,
                        "confirmation-inputs:" + value.confirmation[2], as_of=actual_time,
                        expires=_bounded_until(now, (context_expiry, event_at)))
                    rule_observation = wait_observation
                    leaves = tuple(ConditionReadiness(condition_path=leaf.condition_path,
                        state="UNKNOWN" if partial_complete else "MISSING_INPUT",
                        reason="EXPECTED_CONFIRMATION" if partial_complete else "MISSING_DATA",
                        evidence_refs=leaf.evidence_refs) for leaf in leaves)
                    if partial_complete:
                        expected_confirmation = ExpectedConfirmation(target=future,
                            expected_at=event_at, calendar_reference=value.confirmation[2],
                            prior_inputs_complete=True,
                            observation=wait_observation.model_copy(update={
                                "calendar_reference": value.confirmation[2]}))
            if daily_unverified:
                rule_observation = observation(evaluation_ref,
                    "current-daily-and-factor-owner-unverified", availability="CACHED",
                    as_of=actual_time)
            elif fact_unverified:
                rule_observation = observation(evaluation_ref,
                    "recorded-fact-inputs-unverified", availability="CACHED", as_of=actual_time)
            if (risk is not None and risk.current is not None
                    and risk.current.ordinary_close is not None
                    and risk.maintenance.state == "PASS"):
                close = risk.current.ordinary_close
                future = value.confirmation[0]
                if (close.status_after == "PENDING" and not close.blockers
                        and future is not None
                        and close.second_close_date_after == future.trade_date
                        and future.trade_date > close.close_date
                        and close.current_basis_id == value.native.daily_evidence.basis_id):
                    # Use only today's existing owner/calendar event. No later
                    # session or missing prefix is invented from a PENDING flag.
                    event_at = datetime.combine(future.trade_date, time(15), now.tzinfo)
                    if event_at > now and value.owner_current:
                        rule_target = future
                        expected_confirmation = ExpectedConfirmation(target=future,
                            expected_at=event_at, calendar_reference=value.confirmation[2],
                            prior_inputs_complete=True, observation=observation(evaluation_ref,
                                expires=_bounded_until(now, (context_expiry, event_at)),
                                as_of=actual_time).model_copy(update={
                                    "calendar_reference": value.confirmation[2]}))
            if (kind == "RISK_BRANCH" and risk.current is None
                    and value.risks.get(identity) is not None):
                row = value.risks[identity]
                rule_observation = observation("risk:" + row["id"], availability="CACHED")
            execution = _execution(value, kind, identity, side, rule, now,
                inputs_ready=inputs_ready, observe=observation, context_expiry=context_expiry)
            capital, economics = _money_results(value, kind, rule, requirements, execution, now)
            money_current = not requirements.quote or (
                _rule_sources_current(value, kind, rule, now)
                and _current_quote(value, now) is not None)
            input_observation = (None if not requirements.required else observation(
                "inventory:" + str(context.inventory_revision),
                availability=("CURRENT" if money_current else
                              "CACHED" if value.native else "UNAVAILABLE"),
                as_of=evaluated_at if requirements.quote else None,
                expires=_bounded_until(now, (context_expiry, *(
                    (None if value.native is None or value.native.quote is None else
                     value.native.quote.quote_at + timedelta(minutes=5),)
                    if requirements.quote else ()))) if money_current else None))
            money = ReadinessMoneyFacts(inputs=AxisReadiness(axis="INVENTORY_CAPITAL",
                state="NOT_APPLICABLE" if not requirements.required else
                    "PASS" if inputs_ready else "UNKNOWN",
                reason=None if inputs_ready else "DEPENDENCY_UNVERIFIED",
                observation=input_observation), capital=capital, economics=economics)
            rules.append(RuleReadinessFacts(owner_kind=kind, owner_id=identity, side=side,
                requirements=requirements, expected_target=rule_target,
                evaluated_target=actual_target,
                evaluated_at=actual_time,
                observation=rule_observation,
                root_outcome=root, leaves=leaves, expected_confirmation=expected_confirmation,
                execution=execution, money=money, risk=risk,
                notification=_notification(value, authority, kind, identity, observe=observation)))
        if value.current and any(
                rule.risk.maintenance.state != "PASS" if rule.risk is not None else
                rule.root_outcome is None or rule.observation is None
                or rule.observation.availability != "CURRENT" for rule in rules):
            axes = [AxisReadiness(axis="DATA_EVALUATION", state="UNKNOWN",
                    reason="DEPENDENCY_UNVERIFIED", observation=data_observation)
                    if axis.axis == "DATA_EVALUATION" else axis for axis in axes]
        if any(rule.expected_confirmation is not None for rule in rules):
            only_future = all(rule.expected_confirmation is not None or (
                    rule.risk is not None and rule.risk.maintenance.state == "PASS") or (
                    value.current and rule.root_outcome is not None
                    and rule.observation is not None and rule.observation.availability == "CURRENT")
                    and all(leaf.state in {"CONDITION_TRUE", "CONDITION_FALSE"}
                            for leaf in rule.leaves) for rule in rules)
            axes = [AxisReadiness(axis="DATA_EVALUATION",
                    state="WAIT" if only_future else "UNKNOWN",
                    reason="EXPECTED_CONFIRMATION" if only_future else "DEPENDENCY_UNVERIFIED",
                    observation=observation(
                        evaluation_ref, expires=context_expiry, as_of=evaluated_at))
                if axis.axis == "DATA_EVALUATION" else axis for axis in axes]
        alert = any(kind == "ALERT_RULE" for kind, *_ in value.owners)
        trade = any(kind != "ALERT_RULE" for kind, *_ in value.owners)
        result = summarize_readiness(ReadinessSnapshot(computed_at=now, context=context,
            scope="MIXED" if alert and trade else "ALERT_ONLY" if alert else "TRADE_RULES",
            axes=tuple(axes), rules=tuple(rules)))
        notification_service = _notification_service_axis(
            value, authority, result, now, observe=observation, expiry=expiry)
        if notification_service is not None:
            result = summarize_readiness(result.snapshot.model_copy(update={"axes": tuple(
                notification_service if axis.axis == "NOTIFICATION_DELIVERY" else axis
                for axis in result.snapshot.axes)}))
        if len(result.model_dump_json(by_alias=True).encode("utf-8")) > MAX_READINESS_BYTES:
            raise ValueError("Readiness exceeds the complete 1MiB view bound")
        return result, value.binding


def changed_readiness(result):
    """Retain all owners/axes after exhausted context retries, with no current claim."""
    axes = tuple(AxisReadiness(axis=axis.axis, state="UNKNOWN", reason="CONTEXT_CHANGED")
                 for axis in result.snapshot.axes)
    rules = tuple(rule.model_copy(update={"observation": None, "root_outcome": None,
        "evaluated_at": None if rule.risk is not None else rule.evaluated_at,
        "evaluated_target": None if rule.risk is not None else rule.evaluated_target,
        "expected_confirmation": None if rule.risk is not None else rule.expected_confirmation,
        "risk": None if rule.risk is None else rule.risk.model_copy(update={"current": None,
            "origin": None,
            "maintenance": AxisReadiness(axis="DATA_EVALUATION", state="UNKNOWN",
                                         reason="CONTEXT_CHANGED")}),
        "execution": ReadinessExecutionState(),
        # Exhausted retries no longer establish this event's owner/context.
        "notification": None,
        "money": None if rule.money is None else ReadinessMoneyFacts(inputs=AxisReadiness(
            axis="INVENTORY_CAPITAL", state="UNKNOWN" if rule.requirements.required
                else "NOT_APPLICABLE",
            reason="CONTEXT_CHANGED" if rule.requirements.required else None)),
        "leaves": tuple(leaf.model_copy(update={"state": "UNKNOWN", "reason": "CONTEXT_CHANGED",
                                              "evidence_refs": ()}) for leaf in rule.leaves)})
        for rule in result.snapshot.rules)
    changed = summarize_readiness(result.snapshot.model_copy(update={"axes": axes, "rules": rules}))
    if len(changed.model_dump_json(by_alias=True).encode("utf-8")) > MAX_READINESS_BYTES:
        raise ValueError("Readiness exceeds the complete 1MiB view bound")
    return changed
