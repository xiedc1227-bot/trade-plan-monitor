"""Real ledger/runtime boundary regressions with explicit synthetic human policy."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest
from tests.integration.test_daily_plan_chain import (
    FRIDAY,
    SH,
    SYMBOL,
    TUESDAY,
    WEDNESDAY,
    ready_chain,
)
from tests.integration.test_daily_plan_chain import (
    chain as chain,
)
from tests.unit.test_daily_state_models import signal_payload

from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs, daily_delivery_allowed


def enable_sell(chain):
    raw = chain.plan.model_dump(mode="json")
    sell = {
        **raw["ordinary_rules"][0],
        "side": "SELL",
        "zone": "PRESSURE",
        "rule_id": "pressure-sell",
    }
    raw["ordinary_rules"] = [sell]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    chain.evaluate(series=chain.series(close=4200), official=FRIDAY)
    chain.facts()
    return chain.evaluate(series=chain.series(close=4200), official=FRIDAY)


def test_real_sell_pressure_never_sells_core_and_complete_tactical_simulation(chain):
    enable_sell(chain)
    chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
    chain.position(100, 100)
    ready = chain.evaluate(series=chain.series(close=4200), price=4200)
    assert ready.snapshot["signals"][0]["executable_qty"] == 100
    chain.simulate(ready.snapshot["signals"][0])
    assert (
        chain.client.get(
            f"/api/v1/simulation-position-inventory?symbol={SYMBOL}&asOfTradeDate={TUESDAY}"
        ).json()["snapshot"]["coreQty"]
        == 100
    )


def test_unconsumed_expiry_restart_later_close_requires_new_independent_evidence(chain):
    series, ready = ready_chain(chain)
    chain.now = chain.now.replace(hour=15)
    expired = chain.evaluate(series=series, price=3970)
    old = expired.snapshot["signals"][0]
    assert (old["state"], old["simulated_qty"], old["executable_qty"]) == (
        "EXPIRED",
        0,
        0,
    )
    chain.now = chain.now.replace(hour=16)
    later = chain.series(TUESDAY)
    chain.evaluate(series=later, official=TUESDAY)
    for kind in ("PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL"):
        chain.post(
            "plan-facts",
            {
                "planVersionId": chain.version["id"],
                "contentHash": chain.version["contentHash"],
                "factId": "later-" + kind,
                "kind": kind,
                "tradeDate": str(TUESDAY),
                "expectedRevision": 0,
                "evidence": "Synthetic later close separately verified for a new structure",
            },
        )
    repeated = chain.evaluate(series=later, official=TUESDAY)
    assert len(repeated.snapshot["signals"]) == 1
    assert repeated.snapshot["signals"][0]["simulated_qty"] == 0
    assert repeated.event_ids == ()
    chain.post(
        "plan-facts",
        {
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": "new-independent-structure",
            "kind": "INDEPENDENT_EVENT",
            "tradeDate": str(TUESDAY),
            "signalId": old["signal_id"],
            "expectedRevision": 0,
            "evidence": "Synthetic verified new completed-day structure linked to prior occurrence",
        },
    )
    new = chain.evaluate(series=later, official=TUESDAY)
    with chain.plans._unit_of_work() as work:
        records = work.daily.list(symbol=SYMBOL, kind="SIGNAL")
        assert len(records) == 2
        original = work.daily.get(old["signal_id"])["payload"]
        assert (original["simulated_qty"], original["state"]) == (
            0,
            "EXPIRED",
        )
    assert new.snapshot["signals"][-1]["execution_date"] == str(WEDNESDAY)
    assert new.snapshot["signals"][-1]["signal_id"] != old["signal_id"]
    assert new.event_ids == ()


def test_long_signal_history_pages_without_stopping_current_runtime(chain):
    with chain.plans._unit_of_work() as work:
        for index in range(505):
            payload = {
                **signal_payload(),
                "signal_id": f"history-{index:04d}",
                "state": "SIMULATED",
                "simulated_qty": 100,
                "executable_qty": 0,
            }
            work.daily.save(
                payload["signal_id"],
                kind="SIGNAL",
                symbol=SYMBOL,
                lineage=payload["lineage"],
                payload=payload,
                expected_revision=0,
            )
        work.commit()
    result = chain.evaluate(series=chain.series(), official=FRIDAY)
    assert len(result.snapshot["signals"]) == 1
    assert result.snapshot["signals"][0]["signal_id"] == "history-0504"
    with chain.plans._unit_of_work() as work:
        assert len(work.daily.list(symbol=SYMBOL, kind="SIGNAL", limit=100)) == 505


def test_send_time_quote_age_rechecked_even_when_notice_itself_is_recent(chain):
    series, _ = ready_chain(chain)
    # Filled amount unchanged; this quote was already four minutes old on evaluation.
    chain.now += timedelta(seconds=1)
    quote = DailyExecutionQuote(
        symbol=SYMBOL,
        price_fen=3970,
        quote_at=chain.now - timedelta(minutes=4),
        available_at=chain.now - timedelta(minutes=4),
        evaluated_at=chain.now,
        tradable=True,
        special_state_verified=True,
        liquidity_available=True,
    )
    evaluated = chain.runtime.run_inputs(
        plan=chain.plan,
        inputs=DailyRuntimeInputs(
            evaluated_at=chain.now,
            official_trade_date=None,
            series=series,
            session_dates=(FRIDAY, TUESDAY, WEDNESDAY),
            suspended_dates=(),
            quote=quote,
            data_blockers=(),
        ),
    )
    # The original deduplicated event must be checked against the latest quote.
    with chain.plans._unit_of_work() as work:
        from sqlalchemy import select

        from trade_plan_monitor.state.models import AlertEvent

        row = work.daily.session.scalars(select(AlertEvent)).first()
        event = work.alerts.get(UUID(row.id))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
        assert not daily_delivery_allowed(
            work.daily.session, event, chain.now + timedelta(minutes=2)
        )
    assert evaluated.snapshot["signals"][0]["executable_qty"] == 100


@pytest.mark.parametrize("kind", ["ORDINARY_TECHNICAL", "SEVERE_TECHNICAL"])
def test_each_risk_blocks_both_ordinary_sides_and_retains_exact_scope(chain, kind):
    raw = chain.plan.model_dump(mode="json")
    raw["ordinary_rules"].append({
        **raw["ordinary_rules"][0],
        "side": "SELL",
        "zone": "PRESSURE",
        "rule_id": "pressure-sell",
    })
    for branch in raw["risk_branches"]:
        branch["target_core_qty"] = 100
        branch["involves_core"] = False
        branch["target_tactical_qty"] = 0
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    chain.evaluate(series=chain.series(), official=FRIDAY)
    chain.facts()
    chain.evaluate(series=chain.series(), official=FRIDAY)
    chain.evaluate(series=chain.series(close=4200), official=FRIDAY)
    if kind == "ORDINARY_TECHNICAL":
        chain.evaluate(series=chain.series(close=3800), official=FRIDAY)
        chain.now = datetime(2026, 9, 22, 16, tzinfo=SH)
        chain.evaluate(series=chain.series(TUESDAY, 3810), official=TUESDAY)
    elif kind == "SEVERE_TECHNICAL":
        chain.now += timedelta(microseconds=1)
        chain.now += timedelta(microseconds=1)
        chain.post(
            "plan-facts",
            {
                "planVersionId": chain.version["id"],
                "contentHash": chain.version["contentHash"],
                "factId": "severe-structure",
                "kind": "SEVERE_STRUCTURE",
                "tradeDate": str(FRIDAY),
                "expectedRevision": 0,
                "evidence": "Synthetic official structure failure independently verified",
            },
        )
        assert (
            next(
                r
                for r in chain.evaluate(series=chain.series(), official=FRIDAY).snapshot["risks"]
                if r["kind"] == kind
            )["status"]
            == "CLEAR"
        )
        chain.post(
            "plan-facts",
            {
                "planVersionId": chain.version["id"],
                "contentHash": chain.version["contentHash"],
                "factId": "severe-deterioration",
                "kind": "SEVERE_DETERIORATION",
                "tradeDate": str(FRIDAY),
                "expectedRevision": 0,
                "evidence": "Synthetic official deterioration independently verified",
            },
        )
        confirmed = chain.evaluate(series=chain.series(), official=FRIDAY)
        assert next(r for r in confirmed.snapshot["risks"] if r["kind"] == kind)[
            "earliest_execution_date"
        ] == str(TUESDAY)
    chain.now = datetime(2026, 9, 23 if kind == "ORDINARY_TECHNICAL" else 22, 10, tzinfo=SH)
    chain.position(100, 100)
    result = chain.evaluate(
        series=chain.series(TUESDAY, 3810) if kind == "ORDINARY_TECHNICAL" else chain.series(),
        price=3970,
    )
    assert result.snapshot["risk_action"]["branch"] == kind
    assert result.snapshot["risk_action"]["target_core_qty"] == 100
    assert result.snapshot["risk_action"]["target_tactical_qty"] == 0
    assert result.snapshot["risk_action"]["core_qty"] == 0
    assert {s["side"] for s in result.snapshot["signals"]} == {"BUY", "SELL"}
    assert all(
        s["executable_qty"] == 0 and "HIGHER_PRIORITY_RISK" in s["blockers"]
        for s in result.snapshot["signals"]
    )
