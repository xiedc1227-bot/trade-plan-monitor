"""Structural predecessor defaults, independent of source language or phrasing."""

from copy import deepcopy

from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


def restore_unmentioned_fields(proposed, context, references):
    """Preserve omitted values, but never hide unsupported non-null modifications.

    An explicit binding to a null or empty field can clear it. Collections use
    stable identity; omitted rules are restored by the operation materializer.
    """
    prior = UnifiedPlanDraft.from_executable(context.snapshot).model_dump(mode="json")
    paths = {reference.path.removeprefix("draft.") for reference in references}

    def explicit(path):
        return any(path == p or path.startswith(p + ".") or path.startswith(p + "[") for p in paths)

    def merge(old, new, path):
        if new is None and not explicit(path):
            return deepcopy(old)
        if isinstance(old, dict) and isinstance(new, dict):
            return {key: merge(old.get(key), value, path + "." + key) for key, value in new.items()}
        return deepcopy(new)

    result = deepcopy(proposed)
    for key, value in result.items():
        if key in {"ordinary_rules", "alert_rules", "risk_branches"}:
            identity = risk_identity if key == "risk_branches" else lambda r: r["rule_id"]
            old = {identity(rule): rule for rule in prior[key]}
            result[key] = [
                merge(old.get(identity(rule)), rule, f"{key}[{index}]")
                for index, rule in enumerate(value)
            ]
        elif key not in {"plan_id", "version", "name"}:
            result[key] = merge(prior.get(key), value, key)
    return result
