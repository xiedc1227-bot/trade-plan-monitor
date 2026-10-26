"""Stable identities for canonical executable plans and v3 review content."""

import json
from hashlib import sha256

from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.domain.plan_models import ExecutableTradePlan, ExplicitTradePlan


def daily_plan_content_sha256(plan: DailyTradePlan) -> str:
    """Bind every Schema 4 semantic field under its own review domain."""
    if not isinstance(plan, DailyTradePlan):
        raise TypeError("plan must be a DailyTradePlan")
    content = plan.model_dump(mode="json", exclude={"plan_id", "version", "name", "metadata"})
    canonical = json.dumps(
        content, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    domain = {
        4: b"daily-plan-review-content-v1\x00", 5: b"plan-review-content-v2\x00",
        6: b"plan-review-content-v3\x00", 7: b"plan-review-content-v4\x00",
        8: b"plan-review-content-v5\x00",
    }[plan.schema_version]
    return sha256(domain + canonical.encode("utf-8")).hexdigest()


def unified_plan_content_sha256(plan) -> str:
    if plan.schema_version not in {5, 6, 7}:
        raise TypeError("plan must use the current condition contract")
    return daily_plan_content_sha256(plan)


def plan_sha256(plan: ExecutableTradePlan) -> str:
    """Hash the exact canonical UTF-8 JSON representation of a plan."""

    return sha256(dump_plan_json(plan).encode("utf-8")).hexdigest()


def explicit_plan_content_sha256(plan: ExplicitTradePlan) -> str:
    """Hash Schema v3 trading meaning under the review-content domain."""

    if not isinstance(plan, ExplicitTradePlan):
        raise TypeError("plan must be an ExplicitTradePlan")
    content = plan.model_dump(mode="json")
    for field in ("version", "name", "metadata", "plan_id"):
        content.pop(field)
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(b"plan-review-content-v1\x00" + canonical).hexdigest()


__all__ = ["explicit_plan_content_sha256", "plan_sha256"]
