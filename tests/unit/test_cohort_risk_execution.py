"""Risk exits must debit the holding cohort authorized by the reviewed plan."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from test_daily_plan import synthetic_plan_payload
from tests.unit.test_unified_preparation_updates import buy_and_sell_plan

from trade_plan_monitor.decision.daily_risk import risk_execution
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

NOW = datetime(2026, 10, 12, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
OLD_HOLDINGS = {"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-10-09"}


def _confirmed_risk(*, target_core=0, target_tactical=0):
    return {
        "kind": "ORDINARY_TECHNICAL",
        "status": "CONFIRMED",
        "priority": 3,
        "earliest_execution_date": "2026-10-09",
        "target_core_qty": target_core,
        "target_tactical_qty": target_tactical,
        "involves_core": True,
        "holding_scope": dict(OLD_HOLDINGS),
    }


def _lot(identity, *, bucket="TACTICAL", quantity=100, acquired="2026-09-30", sellable=100):
    return {
        "id": identity,
        "bucket": bucket,
        "quantity": quantity,
        "acquired_trade_date": acquired,
        "sellable_quantity": sellable,
        "baseline": False,
    }


def _execute(lots, *, risk=None, tradable=True):
    inventory = {"known": True}
    for bucket in ("CORE", "TACTICAL"):
        own = [lot for lot in lots if lot["bucket"] == bucket]
        inventory[bucket.lower() + "_qty"] = sum(lot["quantity"] for lot in own)
        inventory["sellable_" + bucket.lower()] = sum(
            lot["sellable_quantity"] for lot in own
        )
    return risk_execution(
        (risk or _confirmed_risk(),),
        plan=DailyTradePlan.model_validate(synthetic_plan_payload()),
        inventory=inventory,
        lots=lots,
        evaluated_at=NOW,
        tradable=tradable,
    )


def test_reviewed_risk_branch_can_exclude_holdings_acquired_from_new_plan_date():
    payload = buy_and_sell_plan().model_dump(mode="json")
    payload["risk_branches"] = [{
        **synthetic_plan_payload()["risk_branches"][0],
        "condition": None,
        "holding_scope": dict(OLD_HOLDINGS),
        "risk_line_fen": 3818,
        "risk_comparison": "LT",
    }]

    plan = UnifiedTradePlan.model_validate(payload)

    assert plan.risk_branches[0].model_dump(mode="json")["holding_scope"] == OLD_HOLDINGS


def test_old_risk_exit_allocates_only_old_core_and_tactical_lots():
    lots = [
        _lot("old-core", bucket="CORE"),
        _lot("old-tactical"),
        _lot("new-core", bucket="CORE", acquired="2026-10-09"),
        _lot("new-tactical", acquired="2026-10-09"),
    ]

    result = _execute(lots)

    assert (result["core_qty"], result["tactical_qty"]) == (100, 100)
    assert sorted(result["lot_allocations"], key=lambda item: item["id"]) == [
        {"id": "old-core", "bucket": "CORE", "quantity": 100},
        {"id": "old-tactical", "bucket": "TACTICAL", "quantity": 100},
    ]


def test_opening_holding_observed_before_cutover_is_old_without_acquisition_date():
    opening = {
        **_lot("opening-old", acquired=None),
        "origin": "monitor-loop-opening-v1",
        "observed_trade_date": "2026-09-24",
        "baseline": True,
    }
    later = _lot("new-position", acquired="2026-10-09")

    result = _execute([opening, later])

    assert result["tactical_qty"] == 100
    assert result["lot_allocations"] == [
        {"id": "opening-old", "bucket": "TACTICAL", "quantity": 100}
    ]


def test_no_old_holdings_means_no_remaining_old_exit_quantity_despite_new_holdings():
    result = _execute([_lot("new-only", acquired="2026-10-09")])

    assert (result["core_qty"], result["tactical_qty"]) == (0, 0)
    assert (result["unavailable_core_qty"], result["unavailable_tactical_qty"]) == (0, 0)
    assert result["lot_allocations"] == []


def test_unsellable_old_lot_cannot_be_replaced_with_sellable_new_lot():
    result = _execute([
        _lot("old-unavailable", sellable=0),
        _lot("new-sellable", acquired="2026-10-09"),
    ])

    assert result["tactical_qty"] == 0
    assert result["unavailable_tactical_qty"] == 100
    assert result["lot_allocations"] == []


def test_uncertified_tradability_keeps_only_old_cohort_exit_outstanding():
    result = _execute([
        _lot("old-sellable"),
        _lot("new-sellable", acquired="2026-10-09"),
    ], tradable=False)

    assert result["tactical_qty"] == 0
    assert result["unavailable_tactical_qty"] == 100
    assert result["lot_allocations"] == []
    assert "WAIT_FOR_CERTIFIED_TRADABILITY" in result["blockers"]


def test_retained_target_is_applied_inside_old_cohort_not_against_all_new_holdings():
    result = _execute([
        _lot("old-two-lots", quantity=200, sellable=200),
        _lot("new-position", acquired="2026-10-09"),
    ], risk=_confirmed_risk(target_tactical=100))

    assert result["tactical_qty"] == 100
    assert result["unavailable_tactical_qty"] == 0
    assert result["lot_allocations"] == [
        {"id": "old-two-lots", "bucket": "TACTICAL", "quantity": 100}
    ]


@pytest.mark.parametrize("acquired", ["2026-10-09", "2026-10-12"])
def test_cutover_day_or_later_buy_is_never_substituted_for_old_holding(acquired):
    result = _execute([
        _lot("old-position"),
        _lot("new-position", acquired=acquired, sellable=0 if acquired == "2026-10-12" else 100),
    ])

    assert result["tactical_qty"] == 100
    assert result["unavailable_tactical_qty"] == 0
    assert result["lot_allocations"] == [
        {"id": "old-position", "bucket": "TACTICAL", "quantity": 100}
    ]
