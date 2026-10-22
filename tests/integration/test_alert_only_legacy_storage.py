"""Legacy storage fences simulation while independently reviewed price alerts still work."""

import json
from uuid import UUID

import pytest
from sqlalchemy import select
from tests.integration.test_daily_plan_chain import FRIDAY, SYMBOL, Chain
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertEvent,
    PositionInventoryState,
    PositionLot,
)


def _price_alert_plan():
    raw = unified_payload()
    raw.update(
        ordinary_rules=[],
        risk_branches=[],
        alert_rules=[
            {
                "kind": "RISK_ALERT",
                "rule_id": "legacy-storage-price-reminder",
                "condition": {
                    "type": "DAILY_PRICE_COMPARE",
                    "field": "close",
                    "offset": 0,
                    "comparator": "LT",
                    "reference": {
                        "mode": "FIXED",
                        "value": "4000",
                        "unit": "FEN",
                        "as_of": str(FRIDAY),
                        "source": "Synthetic fixed daily close threshold",
                    },
                },
                "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
            }
        ],
    )
    return UnifiedTradePlan.model_validate(raw)


def _legacy_layout(chain):
    """Recreate the original stricter constraint in an isolated test database only."""
    with chain.plans._engine.begin() as connection:
        original = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='daily_plan_record'"
        ).scalar_one()
        assert original.count("'SIMULATION',") == 1
        connection.exec_driver_sql("ALTER TABLE daily_plan_record RENAME TO current_daily_record")
        connection.exec_driver_sql(original.replace("'SIMULATION',", ""))
        connection.exec_driver_sql(
            "INSERT INTO daily_plan_record SELECT * FROM current_daily_record"
        )
        connection.exec_driver_sql("DROP TABLE current_daily_record")
        for index in DailyRecord.__table__.indexes:
            index.create(connection)


def _inventory_records(chain):
    with chain.plans._unit_of_work() as work:
        return {
            "simulation_positions": list(
                work.daily.session.execute(
                    select(DailyRecord.__table__).where(
                        DailyRecord.kind.in_(("POSITION", "SIMULATION"))
                    )
                )
            ),
            "actual_positions": list(work.daily.session.execute(select(PositionLot.__table__))),
            "actual_inventory": list(
                work.daily.session.execute(select(PositionInventoryState.__table__))
            ),
        }


def test_pending_reminder_draft_on_old_layout_is_not_reviewed_activated_or_evaluated(tmp_path):
    chain = Chain(tmp_path)
    chain.plan = _price_alert_plan()
    with chain.client:
        _legacy_layout(chain)
        saved = chain.activate(review=False)
        before = _inventory_records(chain)
        version = chain.client.get("/api/v1/plan-versions/" + saved["id"]).json()
        assert version["status"] == "DRAFT" and not version["canActivate"]
        assert version["reviewId"] is None
        assert len(chain.plan.alert_rules) == 1
        assert not chain.plan.ordinary_rules and not chain.plan.risk_branches
        assert chain.client.get("/api/v1/plan-runtime/" + SYMBOL).json()["status"] == "UNSUPPORTED"
        with chain.plans._unit_of_work() as work:
            assert work.daily.session.scalars(select(ActivePlan)).all() == []
            assert work.daily.session.scalars(select(AlertEvent)).all() == []
            assert work.daily.list(symbol=SYMBOL, kind="EVALUATION") == ()
        assert _inventory_records(chain) == before


@pytest.mark.parametrize("preserved_report", [False, True])
def test_reviewed_price_reminder_works_on_old_layout_and_preserves_simulation_fences(
    tmp_path, preserved_report
):
    chain = Chain(tmp_path)
    chain.plan = _price_alert_plan()
    with chain.client:
        _legacy_layout(chain)
        if preserved_report:
            with chain.plans._unit_of_work() as work:
                work.daily.session.add(
                    DailyRecord(
                        id="preserved-report",
                        kind="REPORT",
                        symbol=SYMBOL,
                        lineage="old-policy",
                        revision=7,
                        payload_json='{"old_report":true}',
                        created_at=chain.now.isoformat(),
                        updated_at=chain.now.isoformat(),
                    )
                )
                work.commit()
        # This approval belongs only to an isolated synthetic test policy.
        chain.activate()
        before = _inventory_records(chain)
        result = chain.evaluate(series=chain.series(), official=FRIDAY)
        assert len(result.snapshot["alerts"]) == len(result.event_ids) == 1
        assert result.snapshot["alerts"][0]["outcome"] == "SATISFIED"
        assert result.snapshot["signals"] == result.snapshot["risks"] == []
        assert not result.snapshot["inventory"]["known"]
        assert result.snapshot["inventory"]["total_qty"] is None
        response = chain.client.get("/api/v1/plan-runtime/" + SYMBOL)
        assert response.status_code == 200
        assert response.json()["status"] == "CURRENT"
        assert len(response.json()["snapshot"]["alerts"]) == 1
        inventory = chain.client.get(
            "/api/v1/simulation-position-inventory",
            params={"symbol": SYMBOL, "asOfTradeDate": str(FRIDAY)},
        )
        assert inventory.status_code == 200
        assert inventory.json()["status"] == "UNSUPPORTED"
        assert inventory.json()["snapshot"] is None
        rejected = chain.post(
            "simulation-position-confirmations",
            {
                "symbol": SYMBOL,
                "coreQty": 0,
                "tacticalQty": 0,
                "expectedRevision": 0,
            },
            status=409,
        )
        assert rejected["error"]["details"][0]["code"] == (
            "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"
        )
        assert chain.evaluate(series=chain.series(), official=FRIDAY).event_ids == ()
        assert _inventory_records(chain) == before
        with chain.plans._unit_of_work() as work:
            events = work.daily.session.scalars(select(AlertEvent)).all()
            assert len(events) == 1
            assert json.loads(events[0].payload_json)["signal_type"] == "REMINDER"
            event = work.alerts.get(UUID(result.event_ids[0]))
            assert daily_delivery_allowed(work.daily.session, event, chain.now)
            if preserved_report:
                report = work.daily.session.get(DailyRecord, "preserved-report")
                assert (report.revision, report.payload_json) == (7, '{"old_report":true}')
        chain.post(
            "simulated-trades",
            {
                "planVersionId": chain.version["id"],
                "causeId": event.cause_id,
                "expectedCauseRevision": 1,
                "expectedInventoryRevision": 0,
                "quantity": 100,
            },
            status=409,
        )
        assert _inventory_records(chain) == before
