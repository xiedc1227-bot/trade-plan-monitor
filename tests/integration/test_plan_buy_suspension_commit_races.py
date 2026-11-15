"""Two real SQLite writers order correction and BUY without blind sleeps."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event

import pytest
from tests.integration.test_plan_buy_suspension_recovery import advance, guard_row
from tests.integration.test_plan_buy_suspension_simulation import chain as chain
from tests.integration.test_plan_buy_suspension_simulation import command, ready

from trade_plan_monitor.state.market_exception_service import ExceptionAuthorityError
from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.state.simulation import SimulationAuthorityError, simulate_inventory


@pytest.mark.parametrize("first", ["BUY", "CORRECTION"])
def test_actual_correction_and_buy_obey_the_existing_writer_order(chain, first):
    owner, signal = ready(chain)
    cmd = command(chain, signal)
    target = guard_row(chain)["state"].target
    chain.now += timedelta(seconds=1)
    held, release, attempting = Event(), Event(), Event()

    def action(kind, lead):
        if not lead:
            attempting.set()
        try:
            with chain.plans._unit_of_work() as work:
                if kind == "BUY":
                    simulate_inventory(work, cmd, chain.now,
                        buy_suspension_current=owner.buy_suspension_current)
                else:
                    work.daily.lock_symbol(chain.plan.symbol)
                    old = work.history.list_minutes(chain.plan.symbol,
                        start=target, end=target)[0]
                    work.history.upsert_minutes((old.model_copy(update={"close_fen": 2419,
                        "received_at": chain.now}),))
                if lead:
                    held.set()
                    assert release.wait(5)
                work.commit()
            return kind
        except (SimulationAuthorityError, RevisionConflictError, ExceptionAuthorityError):
            return "REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        leading = pool.submit(action, first, True)
        try:
            assert held.wait(5)
            trailing = pool.submit(action, "CORRECTION" if first == "BUY" else "BUY", False)
            assert attempting.wait(5)
        finally:
            release.set()
        assert leading.result(timeout=10) == first
        assert trailing.result(timeout=10) == ("CORRECTION" if first == "BUY" else "REJECTED")
    chain.sdk.breach = target
    assert advance(chain)["state"].outcome == "LATCHED"
    with chain.plans._unit_of_work() as work:
        fills = work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")
        assert len(fills) == int(first == "BUY")
        assert work.daily.get("simulation-position-" + chain.plan.symbol)["payload"][
            "batches"][-1]["quantity"] == 100
        if first == "BUY":
            assert work.daily.get(signal["signal_id"])["payload"]["simulated_qty"] == 100


def test_two_actual_buy_commands_cannot_consume_one_occurrence_twice(chain):
    owner, signal = ready(chain)
    cmd = command(chain, signal)
    start = Barrier(2)

    def submit():
        start.wait(timeout=5)
        try:
            with chain.plans._unit_of_work() as work:
                simulate_inventory(work, cmd, chain.now,
                    buy_suspension_current=owner.buy_suspension_current)
                work.commit()
                return "FILLED"
        except (SimulationAuthorityError, RevisionConflictError, ExceptionAuthorityError):
            return "REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(submit), pool.submit(submit)
        assert sorted((one.result(timeout=10), two.result(timeout=10))) == ["FILLED", "REJECTED"]
    with chain.plans._unit_of_work() as work:
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")) == 1
