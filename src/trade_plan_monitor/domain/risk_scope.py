"""Stable risk identities and acquisition windows shared by review and execution."""

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.domain.daily_plan_models import DailyValue


class RiskHoldingScope(DailyValue):
    mode: Literal["BEFORE_TRADE_DATE", "FROM_TRADE_DATE"]
    trade_date: date
    end_trade_date: date | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def window(self):
        if self.end_trade_date is not None and (
            self.mode != "FROM_TRADE_DATE" or self.end_trade_date <= self.trade_date
        ):
            raise ValueError("risk cohort end must follow its inclusive start")
        return self


def risk_identity(branch):
    if isinstance(branch, dict):
        return branch.get("rule_id") or branch["kind"]
    return getattr(branch, "rule_id", None) or branch.kind


def restrict_scope(previous, mode, trade_date):
    """Intersect a new subset restriction with the original cohort window."""
    if previous is not None and not isinstance(previous, dict):
        previous = previous.model_dump(mode="json")
    day = date.fromisoformat(str(trade_date))
    low, high = (None, day) if mode == "BEFORE_TRADE_DATE" else (day, None)
    if previous:
        old_day = date.fromisoformat(str(previous["trade_date"]))
        if previous["mode"] == "BEFORE_TRADE_DATE":
            high = min(high, old_day) if high is not None else old_day
        else:
            low = max(low, old_day) if low is not None else old_day
            if previous.get("end_trade_date"):
                end = date.fromisoformat(str(previous["end_trade_date"]))
                high = min(high, end) if high is not None else end
    if low is not None and high is not None and low >= high:
        raise ValueError("empty cohort restriction requires a distinct new risk rule")
    return RiskHoldingScope(mode="BEFORE_TRADE_DATE" if low is None else "FROM_TRADE_DATE",
                            trade_date=high if low is None else low,
                            end_trade_date=high if low is not None else None)


def scope_contains(scope, lot):
    """Opening inventory is observed before simulated entries, never re-dated."""
    if scope is None:
        return True
    if not isinstance(scope, dict):
        scope = scope.model_dump(mode="json")
    acquired = lot.get("acquired_trade_date")
    if acquired is None:
        # An unknown acquisition precedes the recorded opening observation. A
        # later cutoff can classify it without inventing an acquisition date.
        observed = lot.get("observed_trade_date")
        if observed is None or str(observed) > str(scope["trade_date"]):
            return None
        before = True
    else:
        before = str(acquired) < str(scope["trade_date"])
    if scope["mode"] == "BEFORE_TRADE_DATE":
        return before
    if before:
        return False
    end = scope.get("end_trade_date")
    return end is None or str(acquired) < str(end)


def scoped_inventory(risk, inventory, lots):
    """Unknown lot classification stays unknown; excluded holdings never count."""
    scope = risk.get("holding_scope")
    if scope is None:
        return inventory
    result = dict(inventory)
    for bucket in ("core", "tactical"):
        own = [lot for lot in lots if lot["bucket"] == bucket.upper()]
        matches = [scope_contains(scope, lot) for lot in own]
        result[bucket + "_qty"] = (
            None if not inventory["known"] or None in matches else
            sum(lot["quantity"] for lot, match in zip(own, matches, strict=True) if match)
        )
        selected = [lot for lot, match in zip(own, matches, strict=True) if match]
        available = [lot.get("sellable_quantity") for lot in selected]
        result["sellable_" + bucket] = (
            None if result[bucket + "_qty"] is None or None in available else sum(available)
        )
    return result


def risk_fulfilled(risk, inventory, lots):
    own = scoped_inventory(risk, inventory, lots)
    return own["known"] and all(
        own[bucket + "_qty"] is not None
        and own[bucket + "_qty"] <= risk["target_" + bucket + "_qty"]
        for bucket in ("tactical", "core") if bucket != "core" or risk["involves_core"]
    )


def blocks_new_entry(risk, trade_date):
    return risk["status"] in {"PENDING", "OBSERVATION", "CONFIRMED"} and scope_contains(
        risk.get("holding_scope"), {"acquired_trade_date": str(trade_date)}) is not False
