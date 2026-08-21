"""Stable content hashing for validated executable trade plans."""

from hashlib import sha256

from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.domain.plan_models import TradePlan


def plan_sha256(plan: TradePlan) -> str:
    """Hash the exact canonical UTF-8 JSON representation of a plan."""

    return sha256(dump_plan_json(plan).encode("utf-8")).hexdigest()


__all__ = ["plan_sha256"]
