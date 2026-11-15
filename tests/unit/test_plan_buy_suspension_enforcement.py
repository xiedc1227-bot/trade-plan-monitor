"""A suspension gates both tranches without consuming or reversing an occurrence."""

from datetime import datetime, time

import pytest
from tests.unit.test_source_tranches import confirm, tranche_plan

from trade_plan_monitor.decision.unified_lifecycle import check_execution, confirm_signal
from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan


def guarded_plan():
    raw = tranche_plan().model_dump(mode="python")
    start = datetime.fromisoformat("2026-06-01T09:30:00+08:00")
    raw.update(schema_version=10, execution_version="condition-plan-v6",
        buy_suspension={"condition": {"type": "MINUTE_CLOSE_BELOW",
            "timeframe_minutes": 5, "price_fen": 2420}, "effective_from": start})
    return BuySuspensionTradePlan.model_validate(raw)


def checked(plan, signal, **authority):
    when = datetime.combine(datetime.fromisoformat(signal["execution_date"]).date(),
        time(10), plan.buy_suspension.effective_from.tzinfo)
    return check_execution(plan, signal, inventory={"known": True, "total_qty": 100,
        "tactical_qty": 100, "sellable_tactical": 100}, quote_fen=3900,
        evaluated_at=when, tradable=True, risk_blocked=False, risk_known=True, **authority)


@pytest.mark.parametrize("index", [0, 1])
def test_guard_without_authority_cannot_create_either_buy(index):
    plan = guarded_plan()
    first = {**confirm(tranche_plan(), 0), "state": "SIMULATED", "simulated_qty": 100}
    assert confirm(plan, index, day=2, previous=(first,) if index else ()) is None


@pytest.mark.parametrize("state", ["CONFIRMED", "READY"])
@pytest.mark.parametrize("latched", [False, True])
def test_pending_buy_is_blocked_and_only_breach_invalidates(state, latched):
    plan = guarded_plan()
    signal = {**confirm(tranche_plan(), 0), "state": state}
    result = checked(plan, signal, buy_suspension_allowed=False,
        buy_suspension_latched=latched)
    assert result["executable_qty"] == 0
    assert result["state"] == ("INVALIDATED" if latched else "CONFIRMED")
    assert result["simulated_qty"] == 0
    assert ("BUY_SUSPENSION_LATCHED" if latched else "BUY_SUSPENSION_UNVERIFIED") in result[
        "blockers"]


def test_guard_missing_commit_authority_blocks_old_ready_by_default():
    result = checked(guarded_plan(), {**confirm(tranche_plan(), 0), "state": "READY"})
    assert result["executable_qty"] == 0


def test_current_authority_allows_buy_but_cannot_reverse_a_completed_fill():
    plan = guarded_plan()
    signal = confirm(tranche_plan(), 0)
    assert checked(plan, signal, buy_suspension_allowed=True)["executable_qty"] == 100
    completed = {**signal, "state": "SIMULATED", "simulated_qty": 100}
    result = checked(plan, completed, buy_suspension_allowed=False, buy_suspension_latched=True)
    assert result["state"] == "SIMULATED" and result["simulated_qty"] == 100


def test_sell_does_not_borrow_buy_guard_or_lose_its_original_conditions():
    plan = guarded_plan()
    signal = {**confirm(tranche_plan(), 0), "side": "SELL"}
    result = checked(plan, signal, buy_suspension_allowed=False, buy_suspension_latched=True)
    assert result["executable_qty"] == 100 and result["state"] == "READY"


def test_explicit_denial_also_blocks_an_owned_guard_not_visible_in_plan_fields():
    # T08 owns inherited/retired definitions; this helper must not bypass its admission.
    plan = tranche_plan()
    signal = confirm(plan, 0)
    result = check_execution(plan, signal, inventory={"known": True, "total_qty": 100},
        quote_fen=3900, evaluated_at=datetime.fromisoformat("2026-06-02T10:00:00+08:00"),
        tradable=True, risk_blocked=False, risk_known=True, buy_suspension_allowed=False)
    assert result["executable_qty"] == 0


def test_current_authority_can_confirm_without_rearming_consumed_tranches():
    from tests.unit.test_daily_conditions import synthetic_series

    plan = guarded_plan()
    series, _ = synthetic_series(count=1)
    sessions, _ = synthetic_series(count=6)
    args = dict(series=series, facts=(), session_dates=sessions.session_dates,
        plan_version_id="version-1", review_id="review-1", buy_suspension_allowed=True)
    signal = confirm_signal(plan, plan.ordinary_rules[0], previous=(), **args)
    assert signal is not None
    completed = {**signal, "state": "SIMULATED", "simulated_qty": 100}
    assert confirm_signal(plan, plan.ordinary_rules[0], previous=(completed,), **args) is None
