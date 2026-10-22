"""UTC persistence clocks must not break strict Shanghai read projections."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import (
    ActivePlan,
    PlanActivationState,
    PositionInventoryState,
    PositionLot,
)
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.daily_service import read_daily
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
from trade_plan_monitor.web.routers.daily_plans import DailyInventoryResource

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 21, 16, 5, tzinfo=UTC)
LOCAL_NOW = NOW.astimezone(SHANGHAI)
SYMBOL = "605296.SH"
INVENTORY_URL = (
    f"/api/v1/simulation-position-inventory?symbol={SYMBOL}&asOfTradeDate=2026-10-22"
)


@pytest.fixture
def store(tmp_path):
    lifecycle = PersistentPlanWebLifecycle(
        database_path=tmp_path / "read-timezone.sqlite3", clock=lambda: NOW
    )
    lifecycle._start_sync()
    try:
        yield lifecycle
    finally:
        lifecycle._stop_sync()


def _state(store):
    with store._unit_of_work() as work:
        return {
            model.__tablename__: sorted(
                tuple(row) for row in work.daily.session.execute(select(model.__table__))
            )
            for model in (
                DailyRecord, ActivePlan, PlanActivationState, PositionInventoryState, PositionLot
            )
        }


def _legacy_report(store):
    with store._unit_of_work() as work:
        work.daily.session.add(DailyRecord(
            id="preserved-report", kind="REPORT", symbol=SYMBOL, lineage="old-policy",
            revision=1, payload_json='{"old_report":true}',
            created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
        ))
        work.commit()


def _evaluation_head(store):
    payload = {
        "symbol": SYMBOL, "plan_version_id": "historical-version",
        "plan_hash": "a" * 64, "content_hash": "b" * 64,
        "review_id": "historical-review", "activation_revision": 1,
        "evaluated_at": LOCAL_NOW.isoformat(), "official_trade_date": None,
        "inventory": {
            "symbol": SYMBOL, "revision": 0, "known": False,
            "total_qty": None, "core_qty": None, "tactical_qty": None,
            "sellable_core": None, "sellable_tactical": None,
        },
        "fact_revisions": [], "signals": [], "risks": [], "alerts": [],
        "risk_action": {
            "status": "WAITING", "core_qty": None, "tactical_qty": None,
            "unavailable_core_qty": None, "unavailable_tactical_qty": None,
            "blockers": ["SIMULATION_POSITION_UNKNOWN"],
        },
        "data_blockers": ["DAILY_DATA_MISSING"], "daily_evidence": None, "quote": None,
        "next_action": "WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION",
    }
    with store._unit_of_work() as work:
        work.daily.save(
            "evaluation-head-" + SYMBOL, kind="EVALUATION", symbol=SYMBOL,
            lineage="historical-policy", payload=payload, expected_revision=0,
        )
        work.commit()


@pytest.mark.parametrize("legacy", [False, True])
def test_inventory_read_converts_utc_without_initializing_or_converting_positions(store, legacy):
    if legacy:
        _legacy_report(store)
    before = _state(store)
    view = read_daily(store, symbol=SYMBOL, trade_date=LOCAL_NOW.date())
    assert view.evaluated_at == NOW
    assert view.evaluated_at.tzinfo == SHANGHAI
    assert view.evaluated_at.date() == LOCAL_NOW.date()
    if legacy:
        assert view.status == "UNSUPPORTED"
        assert view.reason == "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"
        assert view.snapshot is None
    else:
        assert view.status == "CURRENT"
        assert not view.snapshot.known
        assert (
            view.snapshot.total_qty is view.snapshot.core_qty is view.snapshot.tactical_qty is None
        )
    assert _state(store) == before


def test_runtime_read_converts_utc_head_timestamp_without_changing_historical_evidence(store):
    _evaluation_head(store)
    before = _state(store)
    view = read_daily(store, symbol=SYMBOL, trade_date=None)
    assert view.status == "INACTIVE"
    assert view.evaluated_at == NOW
    assert view.evaluated_at.tzinfo == SHANGHAI
    assert view.snapshot.evaluated_at == LOCAL_NOW
    assert not view.snapshot.signals and not view.snapshot.risks
    assert _state(store) == before


@pytest.mark.parametrize("legacy", [False, True])
def test_naive_service_clock_is_not_silently_assigned_a_timezone(store, legacy):
    if legacy:
        _legacy_report(store)
    before = _state(store)
    store._clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises((RuntimeError, ValidationError)):
        read_daily(store, symbol=SYMBOL, trade_date=LOCAL_NOW.date())
    assert _state(store) == before


@pytest.mark.parametrize("invalid_time", [NOW, NOW.replace(tzinfo=None)])
def test_response_model_still_rejects_unconverted_utc_and_naive_values(invalid_time):
    with pytest.raises(ValidationError):
        DailyInventoryResource(
            symbol=SYMBOL, evaluated_at=invalid_time, status="UNSUPPORTED", snapshot=None
        )


@pytest.mark.parametrize("legacy", [False, True])
def test_inventory_http_read_returns_typed_state_with_shanghai_time(store, legacy):
    if legacy:
        _legacy_report(store)
    before = _state(store)
    app = create_app(plan_service=store)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    try:
        response = client.get(INVENTORY_URL)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["evaluatedAt"] == LOCAL_NOW.isoformat()
        assert data["status"] == ("UNSUPPORTED" if legacy else "CURRENT")
        if legacy:
            assert data["reason"] == "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"
            assert data["snapshot"] is None
        else:
            assert data["snapshot"]["known"] is False
            assert data["snapshot"]["totalQty"] is None
        assert _state(store) == before
    finally:
        client.close()


def test_inventory_http_read_uses_the_unchanged_production_default_clock(store):
    store._clock = PersistentPlanWebLifecycle()._clock
    before = _state(store)
    client = TestClient(create_app(plan_service=store), base_url="http://127.0.0.1:8765")
    try:
        response = client.get(INVENTORY_URL)
        assert response.status_code == 200, response.text
        observed = datetime.fromisoformat(response.json()["evaluatedAt"])
        assert observed.utcoffset() == LOCAL_NOW.utcoffset()
        assert response.json()["snapshot"]["known"] is False
        assert _state(store) == before
    finally:
        client.close()


def test_runtime_http_read_preserves_utc_head_instant_and_inactive_status(store):
    _evaluation_head(store)
    before = _state(store)
    client = TestClient(create_app(plan_service=store), base_url="http://127.0.0.1:8765")
    try:
        response = client.get("/api/v1/plan-runtime/" + SYMBOL)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "INACTIVE"
        assert response.json()["evaluatedAt"] == LOCAL_NOW.isoformat()
        assert _state(store) == before
    finally:
        client.close()
