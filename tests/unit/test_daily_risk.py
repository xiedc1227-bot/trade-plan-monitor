"""Daily timing oracles using explicitly synthetic reviewed plan supplements."""

from datetime import date

import pytest
from test_daily_plan import synthetic_plan_payload

from trade_plan_monitor.decision.daily_risk import advance_daily_risks
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan


@pytest.mark.parametrize("protect_core", [True, False])
def test_clear_risk_uses_new_reviewed_scope_but_pending_risk_keeps_old_scope(protect_core):
    days = tuple(date(2026, 9, d) for d in (21, 22, 23))
    raw = synthetic_plan_payload()
    for branch in raw["risk_branches"]:
        branch.update(involves_core=protect_core, target_core_qty=0 if protect_core else 100)
    old_plan = DailyTradePlan.model_validate(raw)
    arguments = dict(session_dates=days, suspended_dates=(), facts=(), basis_id="synthetic")
    clear = advance_daily_risks(
        old_plan, previous=(), close_date=days[0], close_fen=4000, **arguments
    )
    pending = advance_daily_risks(
        old_plan, previous=(), close_date=days[0], close_fen=3800, **arguments
    )
    for branch in raw["risk_branches"]:
        branch.update(
            involves_core=not protect_core,
            target_core_qty=100 if protect_core else 0,
            scope_evidence="Synthetic new reviewed technical scope",
        )
    new_plan = DailyTradePlan.model_validate(raw)
    first = advance_daily_risks(
        new_plan, previous=clear, close_date=days[0], close_fen=3800, **arguments
    )
    confirmed = advance_daily_risks(
        new_plan, previous=first, close_date=days[1], close_fen=3810, **arguments
    )
    ordinary = next(r for r in confirmed if r["kind"] == "ORDINARY_TECHNICAL")
    assert ordinary["status"] == "CONFIRMED"
    assert ordinary["involves_core"] is (not protect_core)
    assert ordinary["target_core_qty"] == (100 if protect_core else 0)
    latched = advance_daily_risks(
        new_plan, previous=pending, close_date=days[1], close_fen=3810, **arguments
    )
    ordinary = next(r for r in latched if r["kind"] == "ORDINARY_TECHNICAL")
    assert ordinary["involves_core"] is protect_core
    assert ordinary["target_core_qty"] == (0 if protect_core else 100)


def test_rebounding_second_close_still_confirms_then_third_session_exit():
    plan = DailyTradePlan.model_validate(synthetic_plan_payload())
    days = (date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23))
    first = advance_daily_risks(
        plan,
        previous=(),
        close_date=days[0],
        close_fen=3800,
        basis_id="synthetic",
        session_dates=days,
        suspended_dates=(),
        facts=(),
    )
    ordinary = next(r for r in first if r["kind"] == "ORDINARY_TECHNICAL")
    assert ordinary["status"] == "PENDING"
    second = advance_daily_risks(
        plan,
        previous=first,
        close_date=days[1],
        close_fen=3810,
        basis_id="synthetic",
        session_dates=days,
        suspended_dates=(),
        facts=(),
    )
    ordinary = next(r for r in second if r["kind"] == "ORDINARY_TECHNICAL")
    assert ordinary["status"] == "CONFIRMED"
    assert ordinary["earliest_execution_date"] == str(days[2])
    rebound = advance_daily_risks(
        plan,
        previous=second,
        close_date=days[2],
        close_fen=4100,
        basis_id="synthetic",
        session_dates=days,
        suspended_dates=(),
        facts=(),
    )
    assert next(r for r in rebound if r["kind"] == "ORDINARY_TECHNICAL")["status"] == "CONFIRMED"


def test_both_reviewed_suspension_choices_have_distinct_resumption_behavior():
    days = tuple(date(2026, 9, d) for d in (21, 22, 23, 24))
    for policy, expected in [
        ("RESUME_FIRST_CLOSE", "CONFIRMED"),
        ("RESTART_ADJACENT_PAIR", "PENDING"),
    ]:
        raw = synthetic_plan_payload()
        raw["risk_branches"][0]["suspension_confirmation_policy"] = policy
        plan = DailyTradePlan.model_validate(raw)
        first = advance_daily_risks(
            plan,
            previous=(),
            close_date=days[0],
            close_fen=3800,
            basis_id="synthetic",
            session_dates=days,
            suspended_dates=(days[1],),
            facts=(),
        )
        resumed = advance_daily_risks(
            plan,
            previous=first,
            close_date=days[2],
            close_fen=3810,
            basis_id="synthetic",
            session_dates=days,
            suspended_dates=(days[1],),
            facts=(),
        )
        assert next(r for r in resumed if r["kind"] == "ORDINARY_TECHNICAL")["status"] == expected


def test_excluded_fundamental_fact_does_not_confirm_any_technical_risk():
    plan = DailyTradePlan.model_validate(synthetic_plan_payload())
    risks = advance_daily_risks(
        plan,
        previous=(),
        close_date=None,
        close_fen=None,
        basis_id=None,
        session_dates=(),
        suspended_dates=(),
        facts=(
            {
                "id": "synthetic-official",
                "kind": "FUNDAMENTAL_INVALIDATION",
                "verified": True,
                "verified_at": "2026-09-22T10:00:00+08:00",
                "trade_date": "2026-09-22",
            },
        ),
    )
    assert {r["kind"] for r in risks} == {"ORDINARY_TECHNICAL", "SEVERE_TECHNICAL"}
    assert all(r["status"] == "CLEAR" for r in risks)
