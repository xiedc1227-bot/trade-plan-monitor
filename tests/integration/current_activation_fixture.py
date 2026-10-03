"""Reviewed current plan activation shared by offline production boundary tests."""

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.integration.test_daily_plan_chain import Chain
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle


def current_sample_plan():
    raw = unified_payload()
    raw.update(symbol="003043.SZ", market="SZSE", levels=None, monitoring=None, risk_branches=[])
    raw["position"] = {"max_qty": 1000}
    raw["ordinary_rules"][0].update(
        zone=None,
        condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000},
        confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        execution_window="CURRENT_SESSION",
    )
    return UnifiedTradePlan.model_validate(raw)


def current_mixed_plan():
    """One reviewed daily rule and one minute rule for both current data owners."""
    raw = unified_payload()
    raw.update(symbol="003043.SZ", market="SZSE", monitoring=None, risk_branches=[])
    raw["position"] = {"max_qty": 1000}
    minute_rule = deepcopy(raw["ordinary_rules"][0])
    minute_rule.update(
        rule_id="minute-sell",
        side="SELL",
        zone=None,
        condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000},
        confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        execution_window="CURRENT_SESSION",
    )
    raw["ordinary_rules"].append(minute_rule)
    return UnifiedTradePlan.model_validate(raw)


def seed_current(tmp_path, *, plan=None, activation_revision=0, clock=None):
    plan = plan or current_sample_plan()
    chain = Chain(tmp_path)
    chain.plan = plan
    chain.now = (
        clock.now()
        if clock is not None
        else datetime(2026, 9, 8, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    chain.plans = PersistentPlanWebLifecycle(
        database_path=tmp_path / "monitor.sqlite3", clock=lambda: chain.now
    )
    with chain.client:
        chain.activate(version=plan.version, activation_revision=activation_revision)
    return plan
