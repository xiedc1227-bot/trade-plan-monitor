"""Independent public participants and literal expectations verify the native cycle."""

import json
from pathlib import Path

import pytest
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_monitor_loop_cycle import cycle_input, frames
from tests.integration.test_monitor_loop_valuation import report_case
from tests.unit.test_monitor_loop_schedule import at, calendar

from trade_plan_monitor.backtest.loop_input import LoopResponsePolicy
from trade_plan_monitor.backtest.loop_report import verify_loop_events
from trade_plan_monitor.state.daily_state_models import DailySignalState
from trade_plan_monitor.state.models import TradingCalendar

EXPECTED = json.loads(
    (Path(__file__).parents[1] / "fixtures/monitor-loop/scenarios.json").read_text()
)


def known_opening():
    value = cycle_input()
    core = value.initial_account.lots[0].model_copy(
        update={
            "acquired_trade_date": at(19).date(),
            "sellable_quantity": 100,
        }
    )
    return value.model_copy(
        update={
            "initial_account": value.initial_account.model_copy(
                update={"lots": (core, value.initial_account.lots[1])}
            )
        }
    )


def signals(values):
    excluded = {"signal_id", "plan_version_id", "review_id", "lineage", "revision"}
    return [
        DailySignalState.model_validate(value).model_dump(mode="json", exclude=excluded)
        for value in values
    ]


def test_every_evaluation_and_fill_matches_independent_public_workflow(tmp_path):
    value = known_opening()
    expected = EXPECTED["buy_sell"]
    assert "operations" not in value.model_dump()  # Expectations are never fed into replay.
    report, events = report_case(tmp_path / "loop", value)
    executions = [event.payload.attempt for event in events if event.payload.kind == "EXECUTED"]
    assert len(executions) == len(expected["fills"]) == 2
    for attempt, wanted in zip(executions, expected["fills"], strict=True):
        receipt = attempt.receipt
        assert attempt.status == "FILLED" and attempt.at.isoformat() == wanted["at"]
        assert receipt.authority_receipt.side == wanted["side"]
        assert receipt.authority_receipt.price_fen == wanted["quote_fen"]
        assert receipt.authority_receipt.quantity == wanted["quantity"]
        assert receipt.settlement.fill_price_fen == wanted["fill_price_fen"]
        assert receipt.settlement.total_fees_fen == wanted["fees_fen"]
        assert receipt.account.cash.balance_fen == wanted["cash_fen"]
        assert receipt.authority_receipt.inventory.total_qty == wanted["inventory_qty"]
    assert report.final_account.cash.balance_fen == expected["final_cash_fen"]
    assert report.final_account.paid_fees_fen == expected["paid_fees_fen"]
    assert report.final_account.realized_pnl_fen == expected["realized_pnl_fen"]
    assert report.final_account.accounting_cost_fen == expected["accounting_cost_fen"]
    for field in ("core_qty", "tactical_qty", "sellable_core", "sellable_tactical"):
        assert getattr(report.final_inventory, field) == expected[field]

    chain = Chain(tmp_path / "online")
    chain.plan = value.schedule.entries[0].version.snapshot
    chain.now = value.boundary.started_at
    online = []
    with chain.client:
        chain.activate()
        with chain.plans._unit_of_work() as work:
            work.daily.session.add_all(TradingCalendar(**day.model_dump()) for day in calendar())
            work.commit()
        chain.post(
            "simulation-position-confirmations",
            {
                "symbol": chain.plan.symbol,
                "coreQty": 100,
                "tacticalQty": 100,
                "expectedRevision": 0,
            },
        )
        for frame in frames():
            chain.now = frame.runtime.evaluated_at
            with chain.plans._unit_of_work() as work:
                work.history.upsert_minutes(frame.runtime.minute_prefix)
                for bar in frame.runtime.five_minute_bars:
                    work.history.upsert_five_minute(**bar.model_dump())
                work.commit()
            actual = chain.runtime.run_inputs(plan=chain.plan, inputs=frame.runtime)
            online.append(actual.snapshot)
            wanted = next(
                (fill for fill in expected["fills"] if fill["at"] == chain.now.isoformat()), None
            )
            if wanted is not None:
                signal = next(
                    s
                    for s in actual.snapshot["signals"]
                    if s["side"] == wanted["side"] and s["state"] == "READY"
                )
                receipt = chain.post(
                    "simulated-trades",
                    {
                        "planVersionId": chain.version["id"],
                        "causeId": signal["signal_id"],
                        "expectedCauseRevision": signal["revision"],
                        "expectedInventoryRevision": actual.snapshot["inventory"]["revision"],
                        "quantity": 100,
                    },
                )
                assert (
                    receipt["side"] == wanted["side"] and receipt["priceFen"] == wanted["quote_fen"]
                )
                assert receipt["inventory"]["totalQty"] == wanted["inventory_qty"]
                online.append(
                    chain.runtime.run_inputs(plan=chain.plan, inputs=frame.runtime).snapshot
                )
    evaluated = [event.payload for event in events if event.payload.kind == "EVALUATED"]
    assert len(online) == len(evaluated) == 15
    for actual, native in zip(online, evaluated, strict=True):
        assert signals(actual["signals"]) == signals(native.signals)
        assert actual["inventory"] == native.inventory.model_dump(mode="json")
        assert actual["risk_action"] == native.risk_action.model_dump(
            mode="json", exclude_none=True
        )


@pytest.mark.parametrize(
    "mode,delay,end,key",
    [("OBSERVE_ONLY", 0, 43, "observe"), ("FOLLOW_REMINDERS", 120, 37, "delayed")],
)
def test_independent_no_fill_and_pending_expectations(tmp_path, mode, delay, end, key):
    value = known_opening().model_copy(
        update={"response": LoopResponsePolicy(mode=mode, response_delay_seconds=delay)}
    )
    report, _ = report_case(tmp_path, value, frames(end=end))
    expected = EXPECTED[key]
    assert report.cycle.fills == expected["fills"] and report.cycle.intents == expected["intents"]
    assert report.final_account.cash.balance_fen == expected["cash_fen"]
    if key == "delayed":
        assert report.cycle.unfilled_intents == expected["unfilled_intents"]
    else:
        assert report.final_inventory.total_qty == expected["inventory_qty"]


def test_future_dataset_change_cannot_rename_causal_past(tmp_path):
    value = known_opening()
    past = list(frames())
    future = list(frames(day=21))
    first, original = report_case(tmp_path / "original", value, [*past, *future])
    changed = value.model_copy(update={"dataset_hash": "4" * 64})
    second, revised = report_case(tmp_path / "revised", changed, past)
    assert first.run_id != second.run_id
    before = [event for event in original if event.at <= at(20, 9, 43, 12)]
    # Same causal prefix remains independent of future dataset membership and tail.
    assert [(e.event_id, e.cause_event_id, e.at, e.payload) for e in before] == [
        (e.event_id, e.cause_event_id, e.at, e.payload) for e in revised
    ]
    verify_loop_events(first, original)
    verify_loop_events(second, revised)
    with pytest.raises(ValueError, match="LOOP_AUDIT_ORDER_BINDING_MISMATCH"):
        verify_loop_events(second, [e.model_copy(update={"run_id": first.run_id}) for e in revised])
