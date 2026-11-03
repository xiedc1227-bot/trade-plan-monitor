"""Private read-only projection of existing native records and owner proofs.

Ordinary-rule evaluations are not persisted completely by the current producer.
Missing roots/leaves stay UNKNOWN. This module never runs a trading evaluator or
rescans historical cutover membership to manufacture a positive observation.
"""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime.status_authority import (
    ConditionInputStamp,
    RuntimeReadAuthority,
    condition_completion_matches,
    condition_status_target,
)
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.daily_state_models import DailyEvaluationState
from trade_plan_monitor.state.events import MonitorEventLog
from trade_plan_monitor.state.p3_accounting import capital_storage_ready
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.repositories import PlanRepository
from trade_plan_monitor.state.source_action_authority import _condition_evidence_matches
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.web.plan_readiness_models import (
    AxisReadiness,
    ConditionReadiness,
    ReadinessContext,
    ReadinessObservation,
    ReadinessSnapshot,
    RuleReadinessFacts,
)
from trade_plan_monitor.web.plan_readiness_summary import (
    inventory_requirements,
    summarize_readiness,
)
from trade_plan_monitor.web.source_coverage_read import read_source_coverage

MAX_READINESS_BYTES = 1024 * 1024


def _no_write_identity():
    raise RuntimeError("Readiness cannot allocate business identities")


def authority_identity(authority):
    """The existing runtime read fence, without renewing owner progress."""
    if type(authority) is not RuntimeReadAuthority:
        return None
    return (authority.token, authority.generation, authority.configuration_revision,
            authority.lifecycle, authority.block_reason, authority.standby_reason,
            authority.owner_absent, authority.plans, authority.dependencies,
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
    book = (CapitalRepository(session).get(plan.symbol)
            if any(req.simulation_book for req in requirements) and capital_storage_ready(session)
            else None)
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
    target = condition_status_target(session, plan=plan, now=now, proof=proof)
    bound_head = bool(bound_active and payload and payload["plan_version_id"] == version_id
        and payload["plan_hash"] == details.plan_hash
        and payload["content_hash"] == details.content_hash
        and payload["review_id"] == details.review_id
        and payload["activation_revision"] == active.revision)
    # Validate the native shape without accepting a client-supplied evaluation.
    native = (None if not bound_head
              else DailyEvaluationState.model_validate_json(canonical(payload)))
    # Read only the existing exact risk IDs. These references are retained as
    # unverified historical evidence; matching an active branch is not provenance.
    risks = {identity: reads.daily(daily_hash("daily-risk-obligation-v1", {
        "symbol": plan.symbol, "kind": identity}))
        for kind, identity, _, _ in owners if kind == "RISK_BRANCH"}
    current = bool(native and owner_current and proof is not None
        and proof.symbol == plan.symbol and proof.plan_family == "CONDITION_PLAN"
        and proof.plan_version_id == version_id and proof.plan_hash == details.plan_hash
        and proof.activation_revision == active.revision
        and proof.runtime_generation == authority.generation
        and native.runtime_generation == str(authority.generation)
        and proof.configuration_revision == authority.configuration_revision
        and target is not None and proof.target == evidence.target == target
        and condition_completion_matches(session, proof=proof, snapshot=payload, now=now)
        and DailyAccounting(work.daily).evaluation_current(payload,
            plan_version_id=version_id, content_hash=details.content_hash,
            inventory=inventory or {"symbol": plan.symbol, "revision": 0}, now=now,
            require_daily_data=inventory is not None))
    if current and native.minute_target is not None:
        current = native.minute_target <= now < native.minute_target + timedelta(seconds=90)
    # These are existing values for the second read, not a new proof/hash domain.
    binding = (source.summary.model_dump_json(), details.payload_json, details.revision,
        details.status, details.review_id, details.review_revision, details.review_confirmed_at,
        active, activation, canonical(inventory), None if book is None else book.model_dump_json(),
        None if head is None else (head["id"], head["revision"], canonical(payload)),
        current, target,
        tuple((identity, None if row is None else (row["revision"], canonical(row["payload"])))
              for identity, row in risks.items()))
    return SimpleNamespace(source=source, details=details, plan=plan, owners=owners,
        requirements=requirements, active=bound_active, inventory=inventory, book=book,
        native=native, proof=proof, target=target, current=current, binding=binding,
        owner_current=owner_current,
        activation_revision=active.revision if bound_active else None, risks=risks)


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
            book_revision=None if value.book is None else value.book.revision)

        def observation(*refs, availability="CURRENT", expires=None, as_of=None):
            return ReadinessObservation(context=context, availability=availability,
                observed_at=now, as_of=as_of, expires_at=expires,
                evidence_refs=tuple(refs))

        source_observation = observation("plan:" + version_id,
            "coverage:" + (summary.coverage_bundle_hash or "unavailable"))
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
        expiry = (value.native.minute_target + timedelta(seconds=90)
                  if value.current and value.native.minute_target else None)
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
        inventory_ok = (not applicable or bool(value.inventory and value.inventory["known"]
            and all(not req.sellability or all(value.inventory[name] is not None
                for name in ("sellable_core", "sellable_tactical")) for req in value.requirements)
            and not any(req.quote or req.economics or req.fees or req.cost_basis
                        or req.simulation_book for req in value.requirements)))
        axes.append(AxisReadiness(axis="INVENTORY_CAPITAL",
            state="NOT_APPLICABLE" if not applicable else "PASS" if inventory_ok else "UNKNOWN",
            reason=None if inventory_ok else "DEPENDENCY_UNVERIFIED",
            observation=observation("inventory:" + str(context.inventory_revision))))
        # Existing global IN_APP counts certify neither a rule's selected channel
        # nor its exact successful receipt/configuration. No test send is attempted.
        axes.append(AxisReadiness(axis="NOTIFICATION_DELIVERY", state="UNKNOWN",
                                  reason="DELIVERY_UNVERIFIED"))
        rules = []
        for (kind, identity, side, rule), requirements in zip(
                value.owners, value.requirements, strict=True):
            evidence, root = None, None
            matching = None
            rule_target = value.target
            confirmation = getattr(rule, "confirmation", None)
            if (confirmation is not None and rule_target is not None
                    and (confirmation.kind == "OFFICIAL_DAILY_CLOSE")
                    != (rule_target.kind == "OFFICIAL_CLOSE")):
                rule_target = None
            if kind == "ALERT_RULE" and value.current and review_ok:
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
            condition = getattr(rule, "condition", None)
            if condition is None or value.native is None:
                leaves = ()
            else:
                leaves = _leaves(condition, "condition",
                    evidence, reference=evaluation_ref)
            rule_observation = None if value.native is None else data_observation
            if kind == "RISK_BRANCH" and value.risks.get(identity) is not None:
                row = value.risks[identity]
                rule_observation = observation("risk:" + row["id"], availability="CACHED")
            rules.append(RuleReadinessFacts(owner_kind=kind, owner_id=identity, side=side,
                requirements=requirements, expected_target=rule_target,
                evaluated_target=None if root is None else value.proof.target,
                evaluated_at=None if root is None else evaluated_at,
                observation=rule_observation,
                root_outcome=root, leaves=leaves))
        if value.current and any(rule.root_outcome is None for rule in rules):
            axes = [AxisReadiness(axis="DATA_EVALUATION", state="UNKNOWN",
                    reason="DEPENDENCY_UNVERIFIED", observation=data_observation)
                    if axis.axis == "DATA_EVALUATION" else axis for axis in axes]
        alert = any(kind == "ALERT_RULE" for kind, *_ in value.owners)
        trade = any(kind != "ALERT_RULE" for kind, *_ in value.owners)
        result = summarize_readiness(ReadinessSnapshot(computed_at=now, context=context,
            scope="MIXED" if alert and trade else "ALERT_ONLY" if alert else "TRADE_RULES",
            axes=tuple(axes), rules=tuple(rules)))
        if len(result.model_dump_json(by_alias=True).encode("utf-8")) > MAX_READINESS_BYTES:
            raise ValueError("Readiness exceeds the complete 1MiB view bound")
        return result, value.binding


def changed_readiness(result):
    """Retain all owners/axes after exhausted context retries, with no current claim."""
    axes = tuple(AxisReadiness(axis=axis.axis, state="UNKNOWN", reason="CONTEXT_CHANGED")
                 for axis in result.snapshot.axes)
    rules = tuple(rule.model_copy(update={"observation": None, "root_outcome": None,
        "leaves": tuple(leaf.model_copy(update={"state": "UNKNOWN", "reason": "CONTEXT_CHANGED",
                                              "evidence_refs": ()}) for leaf in rule.leaves)})
        for rule in result.snapshot.rules)
    changed = summarize_readiness(result.snapshot.model_copy(update={"axes": axes, "rules": rules}))
    if len(changed.model_dump_json(by_alias=True).encode("utf-8")) > MAX_READINESS_BYTES:
        raise ValueError("Readiness exceeds the complete 1MiB view bound")
    return changed
