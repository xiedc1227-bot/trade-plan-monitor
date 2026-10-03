"""Public simulation commands succeed atomically and never touch actual holdings."""

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from tests.integration.test_daily_plan_chain import (
    SH,
    SYMBOL,
    TUESDAY,
    ready_chain,
)
from tests.integration.test_daily_plan_chain import chain as chain

from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import (
    PositionInventoryConfirmation,
    PositionInventoryState,
    PositionLot,
    PositionOpeningBalance,
)


def inventory(chain):
    return chain.client.get("/api/v1/simulation-position-inventory", params={
        "symbol": SYMBOL, "asOfTradeDate": str(chain.now.date())}).json()["snapshot"]


def command(chain, signal, quantity=100):
    return {"planVersionId": chain.version["id"], "causeId": signal["signal_id"],
            "expectedCauseRevision": signal["revision"],
            "expectedInventoryRevision": inventory(chain)["revision"], "quantity": quantity}


def test_full_simulation_retry_restart_tplusone_and_no_actual_tables(chain):
    series, ready = ready_chain(chain)
    signal = ready.snapshot["signals"][0]
    assert inventory(chain)["totalQty"] == 100  # reminder has no effect
    payload = command(chain, signal)
    receipt = chain.post("simulated-trades", payload, key="once")
    assert receipt["quantity"] == 100
    assert receipt["inventory"]["totalQty"] == 200
    assert receipt["inventory"]["sellableTactical"] == 0
    assert chain.post("simulated-trades", payload, key="once") == receipt
    chain.post("simulated-trades", payload, status=409)
    with chain.plans._unit_of_work() as work:
        for model in (
            PositionLot,
            PositionOpeningBalance,
            PositionInventoryConfirmation,
            PositionInventoryState,
        ):
            assert work.daily.session.scalar(select(func.count()).select_from(model)) == 0
        assert len(work.daily.list(symbol=SYMBOL, kind="SIMULATION")) == 1
    from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService

    chain.runtime = DailyRuntimeEvaluationService(
        chain.plans._unit_of_work, clock=lambda: chain.now
    )
    after = chain.evaluate(series=series, price=3970)
    assert after.snapshot["signals"][0]["state"] == "SIMULATED"
    assert after.snapshot["signals"][0]["simulated_qty"] == 100
    assert after.event_ids == ()
    chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
    assert inventory(chain)["sellableTactical"] == 100


@pytest.mark.parametrize("quantity", [40, 60, 150, 200])
def test_invalid_or_partial_quantity_is_zero_mutation(chain, quantity):
    _, ready = ready_chain(chain)
    before = inventory(chain)
    chain.post(
        "simulated-trades", command(chain, ready.snapshot["signals"][0], quantity), status=422
    )
    assert inventory(chain) == before
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=SYMBOL, kind="SIMULATION") == ()
        assert (
            work.daily.get(ready.snapshot["signals"][0]["signal_id"])["payload"]["simulated_qty"]
            == 0
        )


def test_missing_current_calendar_blocks_setup_and_sellability(chain):
    from sqlalchemy import delete

    from trade_plan_monitor.state.models import TradingCalendar
    with chain.plans._unit_of_work() as work:
        work.daily.session.execute(delete(TradingCalendar))
        work.commit()
    chain.post("simulation-position-confirmations", {"symbol": SYMBOL, "coreQty": 100,
        "tacticalQty": 0, "expectedRevision": 0}, status=422)
    assert inventory(chain)["known"] is False


def test_aggregate_setup_rejects_whole_quantity_above_transport_safe_integer(chain):
    before = inventory(chain)
    chain.post("simulation-position-confirmations", {"symbol": SYMBOL,
        "coreQty": 9_007_199_254_741_000, "tacticalQty": 0,
        "expectedRevision": 0}, status=422)
    assert inventory(chain) == before
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=SYMBOL, kind="POSITION") == ()
    chain.post("simulation-position-confirmations", {"symbol": SYMBOL,
        "coreQty": 9_007_199_254_740_900, "tacticalQty": 9_007_199_254_740_900,
        "expectedRevision": 0}, status=422)
    assert inventory(chain) == before
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=SYMBOL, kind="POSITION") == ()


def test_preserved_broker_evidence_is_unsupported_not_a_simulation(chain):
    import json
    with chain.plans._unit_of_work() as work:
        work.daily.session.add(
            DailyRecord(
                id=uuid4().hex,
                kind="REPORT",
                symbol=SYMBOL,
                lineage=SYMBOL,
                revision=1,
                payload_json=json.dumps({"status": "FILLED", "quantity": 100}),
                created_at=chain.now.isoformat(),
                updated_at=chain.now.isoformat(),
            )
        )
        work.commit()
    view = chain.client.get("/api/v1/plan-runtime/" + SYMBOL)
    assert view.status_code == 200
    assert view.json()["status"] == "UNSUPPORTED"
    assert view.json()["snapshot"] is None
    response = chain.post("simulation-position-confirmations", {"symbol": SYMBOL,
        "coreQty": 100, "tacticalQty": 0, "expectedRevision": 0}, status=409)
    assert response["error"]["details"][0]["code"] == "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"
    assert (
        chain.evaluate(series=chain.series(), official=TUESDAY).snapshot["status"] == "UNSUPPORTED"
    )


def test_removed_order_endpoint_and_editor_fields(chain):
    assert chain.client.post("/api/v1/daily-execution-reports", json={}).status_code == 404
    operations = chain.client.get("/api/v1/plan-editor-schema").json()["operationSchemas"]
    assert set(operations) == {"FACT", "POSITION", "SIMULATION", "REASSESSMENT"}
    assert set(operations["POSITION"]["properties"]) == {
        "symbol",
        "coreQty",
        "tacticalQty",
        "expectedRevision",
    }


def test_new_fact_cannot_reuse_a_stale_ready_head(chain):
    _, ready = ready_chain(chain)
    signal = ready.snapshot["signals"][0]
    chain.app.state.runtime_lifecycle = None  # commit succeeds before any runtime refresh
    chain.post("plan-facts", {"planVersionId": chain.version["id"],
        "contentHash": chain.version["contentHash"], "factId": "new-invalidation",
        "kind": "SIGNAL_INVALIDATION", "signalId": signal["signal_id"],
        "tradeDate": str(TUESDAY), "expectedRevision": 0,
        "evidence": "Synthetic current technical signal invalidation explicitly verified"})
    response = chain.post("simulated-trades", command(chain, signal), status=409)
    assert response["error"]["details"][0]["code"] == "DAILY_SIMULATION_CURRENT_FACTS_REQUIRED"
    assert inventory(chain)["totalQty"] == 100


def test_atomic_rollback_includes_inventory_consumption_and_receipt(chain, monkeypatch):
    _, ready = ready_chain(chain)
    from trade_plan_monitor.state.daily_repository import DailyRepository
    original = DailyRepository.save

    def fail_receipt(self, identity, **kwargs):
        if kwargs["kind"] == "SIMULATION":
            raise ValueError("synthetic persistence failure after inventory/signal writes")
        return original(self, identity, **kwargs)

    monkeypatch.setattr(DailyRepository, "save", fail_receipt)
    chain.post("simulated-trades", command(chain, ready.snapshot["signals"][0]), status=422)
    assert inventory(chain)["totalQty"] == 100
    with chain.plans._unit_of_work() as work:
        assert (
            work.daily.get(ready.snapshot["signals"][0]["signal_id"])["payload"]["state"] == "READY"
        )
        assert work.daily.list(symbol=SYMBOL, kind="SIMULATION") == ()


def test_two_distinct_confirmation_keys_cannot_consume_one_signal(chain):
    from concurrent.futures import ThreadPoolExecutor
    _, ready = ready_chain(chain)
    payload = command(chain, ready.snapshot["signals"][0])
    # Both requests start with the same current revisions; one atomic winner is allowed.
    def execute(key):
        return chain.client.post("/api/v1/simulated-trades", json=payload,
            headers={"Idempotency-Key": key}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(execute, ["concurrent-a", "concurrent-b"]))
    assert sorted(outcomes) == [200, 409]
    assert inventory(chain)["totalQty"] == 200
    with chain.plans._unit_of_work() as work:
        assert len(work.daily.list(symbol=SYMBOL, kind="SIMULATION")) == 1


def test_risk_simulation_keeps_tplusone_obligation_then_fulfills_without_reviving_buy(chain):
    series, ready = ready_chain(chain)
    chain.simulate(ready.snapshot["signals"][0])
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        chain.post("plan-facts", {"planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"], "factId": kind,
            "kind": kind, "tradeDate": "2026-09-18", "expectedRevision": 0,
            "evidence": "Synthetic complete severe technical evidence explicitly verified"})
    current = chain.evaluate(series=series, price=3970)
    action = current.snapshot["risk_action"]
    assert (action["core_qty"], action["tactical_qty"], action["unavailable_tactical_qty"]) == (
        100,
        0,
        100,
    )
    chain.simulate(action, 100)
    with chain.plans._unit_of_work() as work:
        assert work.daily.get(action["cause_id"])["payload"]["status"] == "CONFIRMED"
    chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
    action = chain.evaluate(series=series, price=3970).snapshot["risk_action"]
    assert (action["core_qty"], action["tactical_qty"]) == (0, 100)
    chain.simulate(action, 100)
    with chain.plans._unit_of_work() as work:
        assert work.daily.get(action["cause_id"])["payload"]["status"] == "FULFILLED"
    final = chain.evaluate(series=series, price=3970)
    assert final.snapshot["inventory"]["total_qty"] == 0
    assert final.snapshot["signals"][0]["state"] == "SIMULATED"
    assert final.snapshot["signals"][0]["executable_qty"] == 0


def reviewed_ready(chain, *, planned=100, core=100, tactical=0):
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    raw = chain.plan.model_dump(mode="json")
    raw["ordinary_rules"][0]["quantity"] = planned
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1, supplement_revision=1 if planned == 100 else 0)
    series = chain.series()
    chain.evaluate(series=series)
    chain.facts()
    chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
    chain.position(core, tactical)
    return series, chain.evaluate(series=series, price=3970)


def test_planned200_partial100_is_rejected_with_zero_mutation(chain):
    _, ready = reviewed_ready(chain, planned=200)
    signal = ready.snapshot["signals"][0]
    assert signal["executable_qty"] == 200
    before = inventory(chain)
    chain.post("simulated-trades", command(chain, signal, 100), status=422)
    assert inventory(chain) == before
    with chain.plans._unit_of_work() as work:
        assert work.daily.get(signal["signal_id"])["payload"]["simulated_qty"] == 0
        assert work.daily.list(symbol=SYMBOL, kind="SIMULATION") == ()


def test_current200_plus_buy100_reaches_max300_and_blocks_independent_new_buy(chain):
    from tests.integration.test_daily_history_regression import fact
    series, ready = reviewed_ready(chain, core=100, tactical=100)
    old = ready.snapshot["signals"][0]
    chain.simulate(old)
    assert inventory(chain)["totalQty"] == 300
    chain.now = datetime(2026, 9, 22, 16, tzinfo=SH)
    later = chain.series(TUESDAY)
    chain.evaluate(series=later)
    for kind in ("PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL"):
        fact(chain, kind, TUESDAY, suffix="next")
    fact(chain, "INDEPENDENT_EVENT", TUESDAY, suffix="independent", signal=old["signal_id"])
    chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
    new = chain.evaluate(series=later, price=3970).snapshot["signals"][-1]
    assert new["signal_id"] != old["signal_id"]
    assert new["executable_qty"] == 0
    assert "MAX_QUANTITY_CAPACITY" in new["blockers"]
    chain.simulate(new, 100, status=409)
    assert inventory(chain)["totalQty"] == 300


def test_initialization_retry_cannot_overwrite_trades_or_reset_consumption(chain):
    _, ready = ready_chain(chain)
    chain.simulate(ready.snapshot["signals"][0])
    before = inventory(chain)
    original = {"symbol": SYMBOL, "coreQty": 100, "tacticalQty": 0, "expectedRevision": 0}
    chain.post("simulation-position-confirmations", original)
    assert inventory(chain) == before
    chain.post("simulation-position-confirmations", {**original, "coreQty": 0,
        "tacticalQty": 200, "expectedRevision": before["revision"]}, status=409)
    assert inventory(chain) == before
    with chain.plans._unit_of_work() as work:
        assert (
            work.daily.get(ready.snapshot["signals"][0]["signal_id"])["payload"]["state"]
            == "SIMULATED"
        )


def test_same_key_changed_body_is_conflict_and_preserves_original_receipt(chain):
    _, ready = ready_chain(chain)
    payload = command(chain, ready.snapshot["signals"][0])
    original = chain.post("simulated-trades", payload, key="fixed-body")
    chain.post("simulated-trades", {**payload, "quantity": 200}, key="fixed-body", status=409)
    assert chain.post("simulated-trades", payload, key="fixed-body") == original
    assert inventory(chain)["totalQty"] == 200


def test_old_risk_nonwhole_target_has_typed_history_without_execution_authority(chain):
    import json
    value = {"risk_id": "old-risk", "kind": "ORDINARY_TECHNICAL", "status": "CONFIRMED",
             "target_core_qty": 40, "target_tactical_qty": 60,
             "scope_evidence": "Preserved old technical scope with unsupported quantity",
             "confirmed_trade_date": "2026-09-18"}
    with chain.plans._unit_of_work() as work:
        work.daily.session.add(DailyRecord(id="old-risk", kind="RISK", symbol=SYMBOL,
            lineage=SYMBOL, revision=1, payload_json=json.dumps(value),
            created_at=chain.now.isoformat(), updated_at=chain.now.isoformat()))
        work.commit()
    response = chain.client.get("/api/v1/plan-runtime/" + SYMBOL)
    assert response.status_code == 200
    view = response.json()
    assert view["status"] == "UNSUPPORTED"
    assert view["risks"][0]["scopeEvidence"] == value["scope_evidence"]
    assert view["risks"][0]["confirmedTradeDate"] == "2026-09-18"
    assert "targetCoreQty" not in view["risks"][0]
    chain.post("simulation-position-confirmations", {"symbol": SYMBOL, "coreQty": 100,
        "tacticalQty": 0, "expectedRevision": 0}, status=409)


def test_existing_unpublished_layout_rejects_simulation_before_mutation(chain):
    from sqlalchemy import text
    with chain.plans._unit_of_work() as work:
        sql = work.daily.session.scalar(
            text("SELECT sql FROM sqlite_master WHERE name='daily_plan_record'")
        )
        old_sql = sql.replace("daily_plan_record", "old_daily_layout", 1).replace(
            "'SIMULATION',", ""
        )
        work.daily.session.execute(text(old_sql))
        work.daily.session.execute(
            text("INSERT INTO old_daily_layout SELECT * FROM daily_plan_record")
        )
        work.daily.session.execute(text("DROP TABLE daily_plan_record"))
        work.daily.session.execute(text("ALTER TABLE old_daily_layout RENAME TO daily_plan_record"))
        work.commit()
    response = chain.post("simulation-position-confirmations", {"symbol": SYMBOL, "coreQty": 100,
        "tacticalQty": 0, "expectedRevision": 0}, status=409)
    assert response["error"]["details"][0]["code"] == "DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED"
    with chain.plans._unit_of_work() as work:
        assert work.daily.session.scalar(select(func.count()).select_from(DailyRecord).where(
            DailyRecord.kind.in_(("POSITION", "SIMULATION")))) == 0
