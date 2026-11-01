"""Recheck fact attribution in recorded evidence without rewriting its history."""

from datetime import date

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.reviewed_fact_targets import (
    assess_unbound_fact,
    matches_reviewed_fact_condition,
)
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.daily_state_models import DailyFactState
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader


def _native_roots(plan, owner_kind, owner_id):
    """Select roots by native owner identity and schema, never by leaf content."""
    if not isinstance(plan, DailyTradePlan):
        return ()
    if owner_kind == "ORDINARY_RULE":
        matches = [rule for rule in plan.ordinary_rules
                   if rule.status == "ENABLED" and rule.rule_id == owner_id]
    elif isinstance(plan, UnifiedTradePlan) and owner_kind == "ALERT_RULE":
        matches = [rule for rule in plan.alert_rules if rule.rule_id == owner_id]
    elif isinstance(plan, UnifiedTradePlan) and owner_kind == "RISK_BRANCH":
        matches = [branch for branch in plan.risk_branches
                   if branch.kind == "SEVERE_TECHNICAL" and branch.condition is not None
                   and risk_identity(branch) == owner_id]
    else:
        return ()
    if len(matches) != 1:
        return ()
    owner, = matches
    if isinstance(plan, UnifiedTradePlan):
        return (("condition", owner.condition),)
    return tuple((name, getattr(owner, name)) for name in (
        "price_structure", "volume_or_candle", "technical")) + tuple(
            (f"prerequisites[{i}]", node) for i, node in enumerate(owner.prerequisites))


def _target_leaf(plan, roots, root_index, positions, owner_kind, owner_id):
    native = _native_roots(plan, owner_kind, owner_id)
    # Only a complete ordered native root set has an unambiguous position.
    # Concatenated/derived confirmation trees cannot borrow a matching leaf.
    if len(native) != len(roots) or any(
            root.get("condition") != node.model_dump(mode="json")
            for root, (_, node) in zip(roots, native, strict=True)):
        return None
    path, node = native[root_index]
    for index in positions:
        if node.type not in {"ALL", "ANY"} or index >= len(node.conditions):
            return None
        node = node.conditions[index]
        path += f".conditions[{index}]"
    return node, path


def fact_evidence_satisfied(work, plan, roots, *, confirmed_trade_date, owner_kind,
                            owner_id, signal_id=None, plan_version_id=None):
    """Project ambiguous FACT leaves to MISSING, preserving native ALL/ANY logic.

    Other evidence retains its recorded outcome and existing market-data guards.
    Each FACT resolves its original SQL owner; an active sibling is no substitute.
    Targeted leaves additionally require its complete ordered native root set.
    Call within the consumer's existing transaction/no-autoflush boundary.
    """
    reads = ActionOwnerReader(work)
    owners = {}
    now = work.daily.clock()
    day = date.fromisoformat(str(confirmed_trade_date))
    roots = tuple(roots)

    def attributed(root, root_index, positions):
        condition = root["condition"]
        for identity in root.get("fact_ids", ()):
            row = reads.daily(identity)
            if row is None or row["kind"] != "FACT" or row["symbol"] != plan.symbol:
                return False
            fact = DailyFactState.model_validate(row["payload"])
            if fact.plan_version_id not in owners:
                details = reads.details(fact.plan_version_id)
                owners[fact.plan_version_id] = (details, load_plan_json(details.payload_json))
            details, original = owners[fact.plan_version_id]
            if (details.id != fact.plan_version_id or details.symbol != plan.symbol
                    or details.content_hash != fact.content_hash
                    or plan_version_id is not None and fact.plan_version_id != plan_version_id
                    or fact.kind != condition["fact_kind"]
                    or fact.satisfied != (root["outcome"] == "SATISFIED")
                    or fact.available_at > now or fact.verified_at > now
                    or condition["validity_scope"] == "TRADE_DATE" and fact.trade_date != day
                    or condition["validity_scope"] == "SIGNAL" and (
                        signal_id is None or fact.signal_id != signal_id)):
                return False
            if fact.reviewed_fact_target is not None:
                selected = _target_leaf(
                    original, roots, root_index, positions, owner_kind, owner_id)
                if selected is None or not matches_reviewed_fact_condition(
                        original, fact, selected[0], plan_version_id=details.id,
                        owner_kind=owner_kind, owner_id=owner_id, condition_path=selected[1]):
                    return False
            else:
                # Preserve the old complete-definition diagnostic, including
                # legitimate derived confirmation roots and folded equal refs.
                decision = assess_unbound_fact(original, fact)
                if (not decision.usable or decision.definition_json != canonical(condition)
                        or not any(ref.owner_kind == owner_kind and ref.owner_id == owner_id
                                   for ref in decision.definitions)):
                    return False
        return bool(root.get("fact_ids"))

    def outcome(root, root_index, positions=()):
        tag = root["condition"]["type"]
        if tag in {"ALL", "ANY"}:
            children = root.get("children", ())
            conditions = root["condition"]["conditions"]
            if not conditions or len(children) != len(conditions):
                return "MISSING_INPUT"
            statuses = {outcome(child, root_index, (*positions, index))
                        if child["condition"] == condition else "MISSING_INPUT"
                        for index, (child, condition) in enumerate(
                            zip(children, conditions, strict=True))}
            decisive, otherwise = (("UNSATISFIED", "SATISFIED") if tag == "ALL"
                                   else ("SATISFIED", "UNSATISFIED"))
            return (decisive if decisive in statuses else
                    "MISSING_INPUT" if "MISSING_INPUT" in statuses else otherwise)
        if (tag == "REVIEWED_FACT" and root["outcome"] != "MISSING_INPUT"
                and not attributed(root, root_index, positions)):
            return "MISSING_INPUT"
        return root["outcome"]

    return all(outcome(root, index) == "SATISFIED" for index, root in enumerate(roots))


def signal_fact_evidence_satisfied(work, plan, signal):
    return fact_evidence_satisfied(work, plan, signal["evidence"],
        confirmed_trade_date=signal["confirmed_trade_date"], owner_kind="ORDINARY_RULE",
        owner_id=signal["rule_id"], signal_id=signal["signal_id"],
        plan_version_id=signal["plan_version_id"])
