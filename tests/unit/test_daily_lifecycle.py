"""Synthetic official calendar proves next-session-only ordinary authority."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from test_daily_plan import synthetic_plan_payload

from trade_plan_monitor.decision.daily_lifecycle import check_daily_execution, next_session
from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan


def test_holiday_calendar_and_included_endpoints_do_not_allow_chasing():
    dates = (date(2026, 9, 18), date(2026, 9, 22), date(2026, 9, 23))
    assert next_session(dates[0], dates) == dates[1]
    plan = DailyTradePlan.model_validate(synthetic_plan_payload())
    signal = {
        "side": "BUY",
        "state": "CONFIRMED",
        "execution_date": str(dates[1]),
        "planned_qty": 100,
        "simulated_qty": 0,
        "signal_id": "synthetic",
    }
    inventory = {
        "known": True,
        "total_qty": 100,
    }
    for price, expected in [(3944, 0), (3945, 100), (3990, 100), (3991, 0)]:
        result = check_daily_execution(
            plan,
            signal,
            inventory=inventory,
            quote_fen=price,
            evaluated_at=datetime(2026, 9, 22, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
            tradable=True,
            risk_blocked=False,
            risk_known=True,
        )
        assert result["executable_qty"] == expected
    result = check_daily_execution(
        plan,
        signal,
        inventory=inventory,
        quote_fen=3970,
        evaluated_at=datetime(2026, 9, 22, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
        tradable=True,
        risk_blocked=False,
        risk_known=True,
    )
    assert result["state"] == "EXPIRED"
    assert result["executable_qty"] == 0
