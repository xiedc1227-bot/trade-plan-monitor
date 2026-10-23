"""Production UTC clocks must emit Shanghai-normalized activation events."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.integration.test_daily_plan_chain import Chain

from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle


@pytest.mark.parametrize("operation", ["activate", "deactivate"])
@pytest.mark.parametrize("clock_kind", ["default", "utc"])
def test_reviewed_alert_activation_events_accept_aware_utc_clocks(
    tmp_path, operation, clock_kind,
):
    chain = Chain(tmp_path)
    production = PersistentPlanWebLifecycle(
        database_path=tmp_path / "daily.sqlite",
        clock=None if clock_kind == "default" else (
            lambda: datetime(2026, 10, 23, 18, 0, tzinfo=UTC)
        ),
    )
    raw = chain.plan.model_dump(mode="json")
    raw.update(ordinary_rules=[], risk_branches=[], levels=None)
    raw["position"] = {"max_qty": 300}
    raw["alert_rules"] = [{
        "kind": "RISK_ALERT", "rule_id": "A1",
        "condition": {
            "type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
            "comparator": "LT",
            "reference": {"mode": "FIXED", "value": "2659", "unit": "FEN",
                          "as_of": "2026-10-15", "source": "Synthetic low"},
        },
        "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
    }]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    with chain.client:
        if operation == "activate":
            chain.plans._clock = production._clock
        active = chain.activate()
        if operation == "deactivate":
            chain.plans._clock = production._clock
            chain.post("plan-deactivations", {
                "symbol": chain.plan.symbol, "expectedRevision": 1,
            })
        with chain.plans._unit_of_work() as work:
            events = work.events.replay_page_after(work.events.current_sequence() - 1).events
            event = next(e for e in reversed(events)
                         if e.event_type.value == "plan." + operation + "d")
            state = work.plans.get_activation_state(chain.plan.symbol)
            expected_time = (work.plans.get_active(chain.plan.symbol).activated_at
                             if operation == "activate" else state.changed_at)
            assert event.occurred_at == expected_time
            assert event.occurred_at.utcoffset() == timedelta(hours=8)
            assert event.payload.revision == (1 if operation == "activate" else 2)
            assert event.payload.symbol == chain.plan.symbol
            if operation == "activate":
                assert state.plan_version_id == active["planVersionId"]
            else:
                assert state.plan_version_id is None
        with chain.plans._require_session_factory()() as session:
            from sqlalchemy import text
            for table in ("position_lot", "position_inventory_state",
                          "position_opening_balance", "position_inventory_confirmation"):
                assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
