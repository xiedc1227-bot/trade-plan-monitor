"""Recheck fact attribution in recorded evidence without rewriting its history."""

from datetime import date

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.reviewed_fact_targets import assess_unbound_fact
from trade_plan_monitor.state.daily_state_models import DailyFactState
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader


def fact_evidence_satisfied(work, plan, roots, *, confirmed_trade_date, owner_kind,
                            owner_id, signal_id=None, plan_version_id=None):
    """Project ambiguous FACT leaves to MISSING, preserving native ALL/ANY logic.

    Other evidence retains its recorded outcome and existing market-data guards.
    Each FACT resolves its original SQL owner; an active sibling is no substitute.
    Call within the consumer's existing transaction/no-autoflush boundary.
    """
    reads = ActionOwnerReader(work)
    owners = {}
    now = work.daily.clock()
    day = date.fromisoformat(str(confirmed_trade_date))

    def attributed(root):
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
            decision = assess_unbound_fact(original, fact)
            if (details.symbol != plan.symbol or details.content_hash != fact.content_hash
                    or plan_version_id is not None and fact.plan_version_id != plan_version_id
                    or not decision.usable
                    or decision.definition_json != canonical(condition)
                    or not any(ref.owner_kind == owner_kind and ref.owner_id == owner_id
                               for ref in decision.definitions)
                    or fact.kind != condition["fact_kind"]
                    or fact.satisfied != (root["outcome"] == "SATISFIED")
                    or fact.available_at > now or fact.verified_at > now
                    or condition["validity_scope"] == "TRADE_DATE" and fact.trade_date != day
                    or condition["validity_scope"] == "SIGNAL" and (
                        signal_id is None or fact.signal_id != signal_id)):
                return False
        return bool(root.get("fact_ids"))

    def outcome(root):
        tag = root["condition"]["type"]
        if tag in {"ALL", "ANY"}:
            statuses = {outcome(child) for child in root["children"]}
            decisive, otherwise = (("UNSATISFIED", "SATISFIED") if tag == "ALL"
                                   else ("SATISFIED", "UNSATISFIED"))
            return (decisive if decisive in statuses else
                    "MISSING_INPUT" if "MISSING_INPUT" in statuses else otherwise)
        if tag == "REVIEWED_FACT" and root["outcome"] != "MISSING_INPUT" and not attributed(root):
            return "MISSING_INPUT"
        return root["outcome"]

    return all(outcome(root) == "SATISFIED" for root in roots)


def signal_fact_evidence_satisfied(work, plan, signal):
    return fact_evidence_satisfied(work, plan, signal["evidence"],
        confirmed_trade_date=signal["confirmed_trade_date"], owner_kind="ORDINARY_RULE",
        owner_id=signal["rule_id"], signal_id=signal["signal_id"],
        plan_version_id=signal["plan_version_id"])
