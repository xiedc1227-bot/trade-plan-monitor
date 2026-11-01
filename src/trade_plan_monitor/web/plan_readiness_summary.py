"""Pure dependency and readiness projection over already owned observations."""

from trade_plan_monitor.domain.p3_policy_models import OpenCostCap, P3TradePlan
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.web.plan_readiness_models import (
    AxisReadiness,
    InventoryRequirements,
    ReadinessAssessment,
    ReadinessSnapshot,
    RuleReadiness,
)


def inventory_requirements(plan: UnifiedTradePlan, *, owner_kind, owner_id):
    """Use the actual native owner; never infer dependencies from stored accounts."""
    if not isinstance(plan, UnifiedTradePlan):
        raise ValueError("readiness requires a supported current native plan")
    if owner_kind == "ALERT_RULE":
        matches = tuple(rule for rule in plan.alert_rules if rule.rule_id == owner_id)
    elif owner_kind == "ORDINARY_RULE":
        matches = tuple(rule for rule in plan.ordinary_rules if rule.rule_id == owner_id)
    elif owner_kind == "RISK_BRANCH":
        matches = tuple(
            branch for branch in plan.risk_branches if risk_identity(branch) == owner_id)
    else:
        raise ValueError("unknown native rule owner kind")
    if len(matches) != 1:
        raise ValueError("dependency owner must identify one actual native rule")
    if owner_kind == "ALERT_RULE":
        return InventoryRequirements()
    rule = matches[0]
    buy = owner_kind == "ORDINARY_RULE" and rule.side == "BUY"
    economics = getattr(getattr(rule, "pretrade_policy", None), "economics", None)
    has_economics = economics is not None and economics.mode != "NONE"
    capital = buy and isinstance(plan, P3TradePlan)
    return InventoryRequirements(
        inventory=True, sellability=not buy, quote=capital or has_economics,
        simulation_book=capital,
        cost_basis=capital and isinstance(plan.position.limit.capital_policy, OpenCostCap),
        fees=has_economics or (
            capital and isinstance(plan.position.limit.capital_policy, OpenCostCap)),
        economics=has_economics,
    )


def _observation_reason(observation, context, computed_at, *, inventory=False, book=False):
    if observation is None or observation.availability != "CURRENT":
        return "AUTHORITY_UNAVAILABLE"
    excluded = {"inventory_revision", "book_revision"}
    if (observation.context.model_dump(exclude=excluded) != context.model_dump(exclude=excluded)
            or inventory and observation.context.inventory_revision != context.inventory_revision
            or book and observation.context.book_revision != context.book_revision):
        return "CONTEXT_CHANGED"
    if observation.observed_at > computed_at:
        return "AUTHORITY_UNAVAILABLE"
    if observation.expires_at is not None:
        if observation.expires_at <= computed_at:
            return "EVIDENCE_EXPIRED"
    elif observation.observed_at != computed_at:
        # A timeless stored success cannot become a new owned observation.
        return "AUTHORITY_UNAVAILABLE"
    return None


def _axis(axis, snapshot):
    if axis.axis == "INVENTORY_CAPITAL":
        if not any(rule.requirements.required for rule in snapshot.rules):
            return AxisReadiness(axis=axis.axis, state="NOT_APPLICABLE")
        if axis.state == "NOT_APPLICABLE":
            return AxisReadiness(axis=axis.axis, state="UNKNOWN", reason="DEPENDENCY_UNVERIFIED")
    if axis.state in {"PASS", "WAIT"}:
        requirements = tuple(rule.requirements for rule in snapshot.rules)
        capital_axis = axis.axis == "INVENTORY_CAPITAL"
        reason = _observation_reason(
            axis.observation, snapshot.context, snapshot.computed_at,
            inventory=capital_axis and any(item.inventory for item in requirements),
            book=capital_axis and any(item.simulation_book for item in requirements))
        if reason is not None:
            return AxisReadiness(axis=axis.axis, state="UNKNOWN", reason=reason,
                                 observation=axis.observation)
        context = snapshot.context
        if capital_axis and (
            any(item.inventory for item in requirements) and context.inventory_revision is None
            or any(item.simulation_book for item in requirements) and context.book_revision is None
        ):
            return AxisReadiness(axis=axis.axis, state="UNKNOWN", reason="DEPENDENCY_UNVERIFIED",
                                 observation=axis.observation)
        if (axis.axis == "SOURCE_COVERAGE" and (
                context.source_hash is None or context.coverage_hash is None)
                or axis.axis == "REVIEW_ACTIVATION" and context.review_receipt_hash is None):
            return AxisReadiness(axis=axis.axis, state="BLOCKED", reason="SOURCE_REVIEW_REQUIRED",
                                 observation=axis.observation)
        if (axis.axis == "RUNTIME_OWNERSHIP" and context.runtime_generation is None
                or axis.axis == "REVIEW_ACTIVATION" and context.activation_revision is None):
            return AxisReadiness(axis=axis.axis, state="UNKNOWN", reason="AUTHORITY_UNAVAILABLE",
                                 observation=axis.observation)
    return axis


def _rule(rule, snapshot, *, owner_current):
    def result(state, reason=None):
        return RuleReadiness(facts=rule, state=state, reason=reason)

    wait = rule.expected_confirmation
    observed = wait.observation if wait is not None else rule.observation
    if observed is not None:
        reason = _observation_reason(
            observed, snapshot.context, snapshot.computed_at,
            inventory=rule.requirements.inventory, book=rule.requirements.simulation_book)
        if reason is not None:
            return result("UNKNOWN", reason)
    # Preserve all leaves and the original ALL/ANY root, without re-evaluation.
    for state in ("BLOCKED", "MISSING_INPUT", "UNKNOWN"):
        incomplete = next((leaf for leaf in rule.leaves if leaf.state == state), None)
        if incomplete is not None:
            return result(state, incomplete.reason)
    if wait is not None:
        if not wait.prior_inputs_complete:
            return result("MISSING_INPUT", "MISSING_DATA")
        if wait.target != rule.expected_target:
            return result("UNKNOWN", "TARGET_MISMATCH")
        if (not owner_current or wait.expected_at <= snapshot.computed_at
                or wait.observation.calendar_reference != wait.calendar_reference):
            return result("UNKNOWN", "AUTHORITY_UNAVAILABLE")
        return result("WAITING_OFFICIAL_CONFIRMATION", "EXPECTED_CONFIRMATION")
    if rule.evaluated_at is None:
        return result("AWAITING_FIRST_EVALUATION", "AWAITING_FIRST_EVALUATION")
    if (rule.observation is None or rule.evaluated_at > snapshot.computed_at
            or rule.evaluated_at > rule.observation.observed_at):
        return result("UNKNOWN", "AUTHORITY_UNAVAILABLE")
    if rule.expected_target is None or rule.evaluated_target != rule.expected_target:
        return result("UNKNOWN", "TARGET_MISMATCH")
    if not rule.leaves or rule.root_outcome is None:
        return result("UNKNOWN", "DEPENDENCY_UNVERIFIED")
    if rule.root_outcome == "MISSING_INPUT":
        return result("MISSING_INPUT", "MISSING_DATA")
    return result("CONDITION_TRUE" if rule.root_outcome == "SATISFIED" else "CONDITION_FALSE")


def summarize_readiness(snapshot: ReadinessSnapshot) -> ReadinessAssessment:
    """Apply MRD precedence; consume observations, never grant or refresh authority."""
    axes = tuple(_axis(axis, snapshot) for axis in snapshot.axes)
    owner_current = next(axis for axis in axes if axis.axis == "RUNTIME_OWNERSHIP").state == "PASS"
    rules = tuple(_rule(rule, snapshot, owner_current=owner_current) for rule in snapshot.rules)
    states = {rule.state for rule in rules}
    blocked = any(axis.state == "BLOCKED" and axis.reason != "SOURCE_REVIEW_REQUIRED"
                  for axis in axes) or any(
        rule.state in {"BLOCKED", "MISSING_INPUT"} and rule.reason != "SOURCE_REVIEW_REQUIRED"
        for rule in rules)
    review = any(axis.reason == "SOURCE_REVIEW_REQUIRED" for axis in axes) or any(
        rule.reason == "SOURCE_REVIEW_REQUIRED" for rule in rules)
    unknown = any(axis.state == "UNKNOWN" for axis in axes) or bool(
        states & {"UNKNOWN", "AWAITING_FIRST_EVALUATION"})
    service_wait = any(axis.state == "WAIT" and axis.reason == "SERVICE_PENDING" for axis in axes)
    confirmation_wait = "WAITING_OFFICIAL_CONFIRMATION" in states
    if any(axis.state == "WAIT" and axis.reason == "EXPECTED_CONFIRMATION" for axis in axes):
        unknown = unknown or not confirmation_wait
    summary = (
        "BLOCKED" if blocked else "NEEDS_REVIEW" if review else "UNKNOWN" if unknown
        else "WAITING_REQUIRED_SERVICE" if service_wait
        else "WAITING_EXPECTED_CONFIRMATION" if confirmation_wait else "READY_FOR_MONITORING"
    )
    observations = tuple(
        axis.observation for axis in axes if axis.state != "NOT_APPLICABLE") + tuple(
        rule.expected_confirmation.observation if rule.expected_confirmation is not None
        else rule.observation for rule in snapshot.rules)
    fresh_until = None
    if observations and all(
        item is not None and item.expires_at is not None
        and _observation_reason(item, snapshot.context, snapshot.computed_at) is None
        for item in observations
    ):
        fresh_until = min(item.expires_at for item in observations)
    return ReadinessAssessment(snapshot=snapshot, axes=axes, rules=rules,
                               summary=summary, fresh_until=fresh_until)
