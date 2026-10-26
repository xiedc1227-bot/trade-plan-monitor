"""Final transaction fences protect a shared book even with overlapping issued offers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from hashlib import sha256
from threading import Barrier
from uuid import UUID

import pytest
from tests.integration import test_p2_concurrency as historical
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_p3_chain import p3_chain as p3_chain

from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.state.simulation import (
    SimulationAuthorityError,
    SimulationCommand,
    simulate_inventory,
)


@pytest.mark.parametrize("p3_chain", [("OPEN_COST_CAP", False, "ORDINARY", 60000)], indirect=True)
def test_two_connections_and_independent_offers_cannot_spend_the_same_budget(p3_chain):
    chain = p3_chain
    chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain)).snapshot[
        "signals"][0]
    assert first["executable_qty"] == 200
    # Seed a second independently identified, already-issued strict offer to stress
    # the final fence. Current scheduling is not asked to create overlapping buys.
    other_id = sha256(b"independent-issued-p3-offer").hexdigest()
    with chain.plans._unit_of_work() as work:
        row = work.daily.get(first["signal_id"])
        second = work.daily.save(other_id, kind="SIGNAL", symbol=chain.plan.symbol,
            lineage=row["lineage"], expected_revision=0,
            payload=row["payload"] | dict(signal_id=other_id,
                evidence_fingerprint=sha256(b"independent-condition-occurrence").hexdigest()))
        work.commit()
    commands = [SimulationCommand(plan_version_id=UUID(chain.version["id"]),
        cause_id=identity, expected_cause_revision=revision, expected_inventory_revision=1,
        quantity=200) for identity, revision in
        ((first["signal_id"], first["revision"]), (other_id, second["revision"]))]
    barrier = Barrier(2)

    def execute(command):
        barrier.wait(timeout=5)
        try:
            with chain.plans._unit_of_work() as work:
                receipt = simulate_inventory(work, command, chain.now)
                work.commit()
                return receipt.quantity
        except (RevisionConflictError, SimulationAuthorityError):
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(execute, commands))
    assert outcomes.count(200) == outcomes.count("CONFLICT") == 1
    with chain.plans._unit_of_work() as work:
        book = CapitalRepository(work.daily.session).get(chain.plan.symbol)
        assert book.retained_basis_fen == 52700 <= 60000
        assert DailyAccounting(work.daily).snapshot(chain.plan.symbol, chain.now.date())[
            "total_qty"] == 300
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")) == 1
    # Reopen a separate connection: the book is durable and a second whole debit exceeds C.
    with chain.plans._unit_of_work() as work:
        assert CapitalRepository(work.daily.session).get(chain.plan.symbol) == book
        assert book.retained_basis_fen + 32700 > 60000


@pytest.mark.parametrize("p3_chain", [("MARKET_VALUE_CAP", True, "WEAK_MINIMUM"),
    ("OPEN_COST_CAP", True, "BROKEN_STRONG")], indirect=True)
@pytest.mark.parametrize("case", ["retry", "race", "rollback"])
def test_capital_exception_retries_races_and_atomic_failure(p3_chain, monkeypatch, case):
    if case == "retry":
        historical.test_same_command_replays_and_another_command_cannot_fill_twice(p3_chain)
    elif case == "race":
        historical.test_revocation_and_execution_race_has_one_winner(p3_chain)
    else:
        historical.test_failure_after_inventory_write_rolls_back_every_effect(p3_chain, monkeypatch)
