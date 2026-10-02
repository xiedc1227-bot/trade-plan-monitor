"""Safety oracles using explicitly synthetic human-reviewed plans and inventory."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from test_daily_plan import synthetic_plan_payload

from trade_plan_monitor.decision.daily_lifecycle import check_daily_execution
from trade_plan_monitor.decision.daily_risk import advance_daily_risks, risk_execution
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote, DailySeries
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SH = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 22, 10, tzinfo=SH)
SYMBOL = "601021.SH"
SESSIONS = (date(2026, 9, 18), date(2026, 9, 21), NOW.date())


@pytest.fixture
def reviewed_plan():
    """Enable SELL by an explicit synthetic supplement, not historical inference."""
    payload = synthetic_plan_payload()
    sell = deepcopy(payload["ordinary_rules"][0])
    sell.update(side="SELL", rule_id="synthetic-pressure-sell", zone="PRESSURE")
    payload["ordinary_rules"][1] = sell
    return DailyTradePlan.model_validate(payload)


@pytest.fixture
def inventory_work(tmp_path):
    engine = create_sqlite_engine(tmp_path / "synthetic-daily-safety.sqlite")
    try:
        upgrade_database(engine)
        with engine.begin() as connection:
            connection.execute(
                TradingCalendar.__table__.insert(),
                {
                    "exchange": "SSE",
                    "cal_date": NOW.date(),
                    "is_open": True,
                    "previous_trade_date": SESSIONS[1],
                },
            )
        sessions = create_session_factory(engine)
        with SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW) as work:
            yield work
    finally:
        engine.dispose()


def _confirm(accounting, *, core, tactical, sellable_core, sellable_tactical):
    accounting.initialize(symbol=SYMBOL, core_qty=sellable_core,
        tactical_qty=sellable_tactical, expected_revision=0, now=NOW)
    if core > sellable_core or tactical > sellable_tactical:
        row = accounting.snapshot(SYMBOL, NOW.date())
        accounting.simulate(symbol=SYMBOL, identity="synthetic-today-batch", side="BUY",
            quantities={"CORE": core - sellable_core, "TACTICAL": tactical - sellable_tactical},
            expected_revision=row["revision"], now=NOW)
    return accounting.snapshot(SYMBOL, NOW.date())



def _ordinary(plan, inventory, *, side, risk_blocked=False):
    return check_daily_execution(
        plan,
        {
            "signal_id": "synthetic-new-" + side.lower(),
            "side": side,
            "bucket": "TACTICAL",
            "state": "CONFIRMED",
            "execution_date": str(NOW.date()),
            "planned_qty": 100,
            "simulated_qty": 0,
        },
        inventory=inventory,
        quote_fen=3970 if side == "BUY" else 4200,
        evaluated_at=NOW,
        tradable=True,
        risk_blocked=risk_blocked,
        risk_known=True,
    )




def test_ordinary_sell_cannot_use_sellable_core_when_tactical_is_zero(
    reviewed_plan, inventory_work
):
    accounting = DailyAccounting(inventory_work.daily)
    _confirm(accounting, core=100, tactical=0, sellable_core=100, sellable_tactical=0)
    before = accounting.snapshot(SYMBOL, NOW.date())
    assert before["known"] and before["sellable_core"] == 100
    assert before["tactical_qty"] == 0

    result = _ordinary(reviewed_plan, before, side="SELL")

    assert result["executable_qty"] == 0
    assert result["blockers"] == ["TACTICAL_SELLABLE_INSUFFICIENT"]
    assert accounting.snapshot(SYMBOL, NOW.date()) == before


def test_ordinary_sell_cannot_sell_tactical_shares_bought_today(reviewed_plan, inventory_work):
    accounting = DailyAccounting(inventory_work.daily)
    initial = _confirm(accounting, core=0, tactical=0, sellable_core=0, sellable_tactical=0)
    accounting.simulate(symbol=SYMBOL, identity="synthetic-today-buy", side="BUY",
        quantities={"TACTICAL": 100}, expected_revision=initial["revision"], now=NOW)
    before = accounting.snapshot(SYMBOL, NOW.date())
    assert before["known"] and before["tactical_qty"] == 100
    assert before["sellable_tactical"] == 0

    result = _ordinary(reviewed_plan, before, side="SELL")

    assert result["executable_qty"] == 0
    assert result["blockers"] == ["TACTICAL_SELLABLE_INSUFFICIENT"]
    assert accounting.snapshot(SYMBOL, NOW.date()) == before




def _daily_series_payload():
    day = SESSIONS[1]
    close_available = datetime(2026, 9, 21, 16, tzinfo=SH)
    return {
        "symbol": SYMBOL,
        "bars": (
            {
                "bar_id": "synthetic-official-close",
                "symbol": SYMBOL,
                "trade_date": day,
                "open": "3950",
                "high": "4000",
                "low": "3900",
                "close": "3970",
                "volume_shares": 1000,
                "official": True,
                "provider": "synthetic-reviewed-provider",
                "basis_id": "synthetic-reviewed-qfq",
                "adjustment_as_of": day,
                "available_at": close_available,
                "received_at": close_available,
            },
        ),
        "basis_id": "synthetic-reviewed-qfq",
        "adjustment_as_of": day,
        "provider": "synthetic-reviewed-provider",
        "quote_comparable": True,
        "session_dates": (day,),
        "suspended_dates": (),
        "cutoff": close_available,
    }


def test_future_adjustment_basis_cannot_enter_an_earlier_daily_evaluation():
    payload = _daily_series_payload()
    assert DailySeries.model_validate(payload).adjustment_as_of == SESSIONS[1]
    payload["adjustment_as_of"] = NOW.date()
    payload["bars"][0]["adjustment_as_of"] = NOW.date()

    with pytest.raises(ValidationError, match="future adjustment basis"):
        DailySeries.model_validate(payload)


def test_daily_close_received_after_cutoff_cannot_be_used_as_available_evidence():
    payload = _daily_series_payload()
    assert DailySeries.model_validate(payload).bars[0].trade_date == SESSIONS[1]
    payload["bars"][0]["received_at"] = payload["cutoff"] + timedelta(seconds=1)

    with pytest.raises(ValidationError, match="unavailable at evaluation cutoff"):
        DailySeries.model_validate(payload)


@pytest.mark.parametrize(
    "quote_offset, available_offset",
    [
        pytest.param(timedelta(seconds=1), timedelta(seconds=1), id="future-quote"),
        pytest.param(timedelta(0), timedelta(seconds=1), id="future-availability"),
        pytest.param(-timedelta(minutes=5, seconds=1), timedelta(0), id="stale-quote"),
    ],
)
def test_future_or_stale_execution_quote_cannot_grant_authority(quote_offset, available_offset):
    payload = {
        "symbol": SYMBOL,
        "price_fen": 3970,
        "quote_at": NOW,
        "available_at": NOW,
        "evaluated_at": NOW,
        "tradable": True,
        "special_state_verified": True,
        "liquidity_available": True,
    }
    assert DailyExecutionQuote.model_validate(payload).price_fen == 3970
    payload.update(quote_at=NOW + quote_offset, available_at=NOW + available_offset)

    with pytest.raises(ValidationError, match="execution quote is not fresh"):
        DailyExecutionQuote.model_validate(payload)


def _confirmed_risks(plan, *, severe):
    first = advance_daily_risks(
        plan,
        previous=(),
        close_date=SESSIONS[0],
        close_fen=3800,
        basis_id="synthetic-reviewed-qfq",
        session_dates=SESSIONS,
        suspended_dates=(),
        facts=(),
    )
    facts = []
    if severe:
        facts.extend(
            {
                "id": "synthetic-" + kind,
                "kind": kind,
                "verified": True,
                "trade_date": str(SESSIONS[1]),
            }
            for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION")
        )
    return advance_daily_risks(
        plan,
        previous=first,
        close_date=SESSIONS[1],
        close_fen=3800,
        basis_id="synthetic-reviewed-qfq",
        session_dates=SESSIONS,
        suspended_dates=(),
        facts=tuple(facts),
    )


@pytest.mark.parametrize(
    "severe, expected_branch",
    [
        (False, "ORDINARY_TECHNICAL"),
        (True, "SEVERE_TECHNICAL"),
    ],
)
def test_confirmed_risk_priority_blocks_an_otherwise_executable_ordinary_buy(
    reviewed_plan, inventory_work, severe, expected_branch
):
    accounting = DailyAccounting(inventory_work.daily)
    inventory = _confirm(
        accounting, core=100, tactical=100, sellable_core=100, sellable_tactical=100
    )
    assert _ordinary(reviewed_plan, inventory, side="BUY")["executable_qty"] == 100
    risks = _confirmed_risks(reviewed_plan, severe=severe)
    action = risk_execution(
        risks, plan=reviewed_plan, inventory=inventory, evaluated_at=NOW, tradable=True
    )
    assert action["status"] == "RISK_EXIT"
    assert action["branch"] == expected_branch

    result = _ordinary(reviewed_plan, inventory, side="BUY", risk_blocked=True)

    assert result["executable_qty"] == 0
    assert result["blockers"] == ["HIGHER_PRIORITY_RISK"]
    assert accounting.snapshot(SYMBOL, NOW.date()) == inventory


@pytest.mark.parametrize("retained_tactical, sellable_tactical", [(0, 100), (100, 200)])
def test_risk_respects_protected_core_reviewed_target_and_actual_sellable_ceiling(
    reviewed_plan, inventory_work, retained_tactical, sellable_tactical
):
    payload = reviewed_plan.model_dump(mode="python")
    for branch in payload["risk_branches"]:
        branch.update(
            involves_core=False, target_core_qty=100, target_tactical_qty=retained_tactical
        )
    plan = DailyTradePlan.model_validate(payload)
    accounting = DailyAccounting(inventory_work.daily)
    inventory = _confirm(
        accounting, core=100, tactical=200, sellable_core=100, sellable_tactical=sellable_tactical
    )
    risks = _confirmed_risks(plan, severe=True)

    result = risk_execution(risks, plan=plan, inventory=inventory, evaluated_at=NOW, tradable=True)

    assert result["core_qty"] == 0
    assert result["tactical_qty"] == 100
    assert inventory["tactical_qty"] - result["tactical_qty"] >= retained_tactical
    assert result["tactical_qty"] <= inventory["sellable_tactical"]
    assert result["unavailable_tactical_qty"] == 200 - retained_tactical - 100
    assert accounting.snapshot(SYMBOL, NOW.date()) == inventory


def test_highest_priority_branch_cannot_weaken_other_confirmed_bucket_targets(
    reviewed_plan, inventory_work
):
    payload = reviewed_plan.model_dump(mode="python")
    for branch in payload["risk_branches"]:
        if branch["kind"] == "SEVERE_TECHNICAL":
            branch.update(involves_core=False, target_core_qty=100, target_tactical_qty=100)
        else:
            branch.update(involves_core=False, target_core_qty=100, target_tactical_qty=0)
    plan = DailyTradePlan.model_validate(payload)
    accounting = DailyAccounting(inventory_work.daily)
    inventory = _confirm(
        accounting, core=100, tactical=200, sellable_core=100, sellable_tactical=200
    )
    risks = _confirmed_risks(plan, severe=True)
    severe = tuple(r for r in risks if r["kind"] == "SEVERE_TECHNICAL")
    highest_only = risk_execution(
        severe, plan=plan, inventory=inventory, evaluated_at=NOW, tradable=True
    )
    assert (highest_only["core_qty"], highest_only["tactical_qty"]) == (0, 100)

    combined = risk_execution(
        risks, plan=plan, inventory=inventory, evaluated_at=NOW, tradable=True
    )

    assert combined["branch"] == "SEVERE_TECHNICAL"
    assert (combined["core_qty"], combined["tactical_qty"]) == (0, 200)
    assert accounting.snapshot(SYMBOL, NOW.date()) == inventory


def test_confirmed_technical_risk_survives_unknown_quantity_and_missing_auxiliary_close(
    reviewed_plan,
):
    confirmed = _confirmed_risks(reviewed_plan, severe=True)
    retained = advance_daily_risks(
        reviewed_plan,
        previous=confirmed,
        close_date=None,
        close_fen=None,
        basis_id=None,
        session_dates=(),
        suspended_dates=(),
        facts=(),
    )
    assert retained == confirmed
    result = risk_execution(
        retained,
        plan=reviewed_plan,
        inventory={
            "known": False,
            "core_qty": None,
            "tactical_qty": None,
            "sellable_core": None,
            "sellable_tactical": None,
        },
        evaluated_at=NOW,
        tradable=False,
    )
    assert result["status"] == "RISK_EXIT"
    assert result["branch"] == "SEVERE_TECHNICAL"
    assert result["core_qty"] is result["tactical_qty"] is None
    assert set(result["blockers"]) == {
        "POSITION_UNKNOWN_RISK_REMAINS_CONFIRMED",
        "WAIT_FOR_CERTIFIED_TRADABILITY",
        "SELLABLE_QUANTITY_UNKNOWN",
    }




def test_only_core_affected_branch_may_set_core_retained_target(reviewed_plan, inventory_work):
    raw = reviewed_plan.model_dump(mode="python")
    for b in raw["risk_branches"]:
        b.update(
            involves_core=b["kind"] == "SEVERE_TECHNICAL",
            target_core_qty=200 if b["kind"] == "SEVERE_TECHNICAL" else 100,
        )
    raw["position"]["max_qty"] = 500
    plan = DailyTradePlan.model_validate(raw)
    inventory = _confirm(
        DailyAccounting(inventory_work.daily),
        core=300,
        tactical=0,
        sellable_core=300,
        sellable_tactical=0,
    )
    result = risk_execution(
        _confirmed_risks(plan, severe=True),
        plan=plan,
        inventory=inventory,
        evaluated_at=NOW,
        tradable=True,
    )
    assert result["target_core_qty"] == 200
    assert result["core_qty"] == 100


def test_risk_aggregate_offer_preserves_core_and_tplusone_unavailable():
    plan = DailyTradePlan.model_validate(synthetic_plan_payload())
    risk = {
        "kind": "ORDINARY_TECHNICAL",
        "status": "CONFIRMED",
        "priority": 3,
        "earliest_execution_date": "2026-09-22",
        "target_core_qty": 100,
        "target_tactical_qty": 0,
        "involves_core": False,
    }
    inventory = {
        "known": True,
        "core_qty": 100,
        "tactical_qty": 300,
        "sellable_core": 100,
        "sellable_tactical": 200,
    }
    result = risk_execution(
        (risk,),
        plan=plan,
        inventory=inventory,
        evaluated_at=datetime(2026, 9, 22, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        tradable=True,
    )
    assert result["core_qty"] == 0
    assert result["target_core_qty"] == 100
    assert result["tactical_qty"] == 200
    assert result["unavailable_tactical_qty"] == 100
    assert "allocations" not in result
