"""A whole simulated trade consumes its approval in the same durable transaction."""

from datetime import datetime, time

import pytest
from tests.integration import test_p2_chain as p2_fixture
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_market_exception_runtime import approve_current, exception_inputs

from trade_plan_monitor.state.market_exception_repository import ExceptionRepository
from trade_plan_monitor.state.market_exception_service import (
    ExceptionRevocationCommand,
    revoke_exception,
)

exception_chain = p2_fixture.p2_chain
pytestmark = pytest.mark.parametrize(
    "exception_chain", [(r, "REQUIRED") for r in ("WEAK_MINIMUM", "BROKEN_STRONG")],
    indirect=True)


def ready(chain):
    approved = approve_current(chain)
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    return approved, result.snapshot["signals"][0]


def test_full_simulation_consumes_approval_once(exception_chain):
    chain = exception_chain
    approved, signal = ready(chain)
    receipt = chain.simulate(signal)
    assert receipt["quantity"] == approved.candidate.frozen_quantity
    with chain.plans._unit_of_work() as work:
        row = ExceptionRepository(work.daily).get(approved.candidate.candidate_id)
        assert row["payload"]["state"] == "CONSUMED"
        assert row["payload"]["frozen_quantity"] == receipt["quantity"]
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")) == 1
        with pytest.raises(ValueError):
            revoke_exception(work.daily, ExceptionRevocationCommand(
                command_id="late-revoke", approval_id=approved.event.event_id,
                expected_revision=row["revision"], reason="Cannot undo fill"), now=chain.now)


def test_revocation_blocks_execution_before_runtime_refresh(exception_chain):
    chain = exception_chain
    approved, signal = ready(chain)
    with chain.plans._unit_of_work() as work:
        revoke_exception(work.daily, ExceptionRevocationCommand(
            command_id="revoke", approval_id=approved.event.event_id, expected_revision=2,
            reason="Withdraw"), now=chain.now)
        work.commit()
    with chain.plans._unit_of_work() as work:
        from uuid import UUID

        from trade_plan_monitor.state.simulation import SimulationCommand, simulate_inventory
        inventory = work.daily.get("simulation-position-" + chain.plan.symbol)
        with pytest.raises(ValueError):
            simulate_inventory(work, SimulationCommand(plan_version_id=UUID(chain.version["id"]),
                cause_id=signal["signal_id"], expected_cause_revision=signal["revision"],
                expected_inventory_revision=inventory["revision"], quantity=signal["planned_qty"]),
                chain.now)
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()


def test_capacity_recovers_without_resizing_or_new_approval(exception_chain):
    from trade_plan_monitor.state.daily_accounting import DailyAccounting

    chain = exception_chain
    approved = approve_current(chain)
    with chain.plans._unit_of_work() as work:
        account = DailyAccounting(work.daily)
        account.simulate(symbol=chain.plan.symbol, identity="other-buy", side="BUY",
            quantities={"TACTICAL": 1900}, expected_revision=1, now=chain.now)
        work.commit()
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    blocked = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    signal = blocked.snapshot["signals"][0]
    assert signal["planned_qty"] == approved.candidate.frozen_quantity
    assert signal["executable_qty"] == 0
    assert "MAX_QUANTITY_CAPACITY" in signal["blockers"]
    with chain.plans._unit_of_work() as work:
        account = DailyAccounting(work.daily)
        account.simulate(symbol=chain.plan.symbol, identity="other-sell", side="SELL",
            quantities={"TACTICAL": 1900}, expected_revision=2, now=chain.now)
        work.commit()
    restored = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert restored.snapshot["signals"][0]["executable_qty"] == approved.candidate.frozen_quantity
    assert restored.snapshot["signals"][0]["signal_id"] == signal["signal_id"]


def test_failure_after_inventory_write_rolls_back_every_effect(exception_chain, monkeypatch):
    from uuid import UUID

    from trade_plan_monitor.state.simulation import SimulationCommand, simulate_inventory

    chain = exception_chain
    approved, signal = ready(chain)
    original = ExceptionRepository.transition

    def fail_consumption(self, candidate, event, *, expected_revision):
        if event.to_state == "CONSUMED":
            raise RuntimeError("injected after inventory write")
        return original(self, candidate, event, expected_revision=expected_revision)

    monkeypatch.setattr(ExceptionRepository, "transition", fail_consumption)
    with pytest.raises(RuntimeError, match="injected"), chain.plans._unit_of_work() as work:
        simulate_inventory(work, SimulationCommand(plan_version_id=UUID(chain.version["id"]),
            cause_id=signal["signal_id"], expected_cause_revision=signal["revision"],
            expected_inventory_revision=1, quantity=signal["planned_qty"]), chain.now)
        work.commit()
    with chain.plans._unit_of_work() as work:
        assert work.daily.get("simulation-position-" + chain.plan.symbol)["revision"] == 1
        assert ExceptionRepository(work.daily).get(
            approved.candidate.candidate_id)["payload"]["state"] == "APPROVED"
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION") == ()
    monkeypatch.setattr(ExceptionRepository, "transition", original)
    assert chain.simulate(signal)["quantity"] == approved.candidate.frozen_quantity


def test_same_command_replays_and_another_command_cannot_fill_twice(exception_chain):
    chain = exception_chain
    approved, signal = ready(chain)
    body = dict(planVersionId=chain.version["id"], causeId=signal["signal_id"],
        expectedCauseRevision=signal["revision"], expectedInventoryRevision=1,
        quantity=signal["planned_qty"])
    first = chain.post("simulated-trades", body, key="one-trade")
    assert chain.post("simulated-trades", body, key="one-trade") == first
    chain.post("simulated-trades", body, key="another-trade", status=409)
    with chain.plans._unit_of_work() as work:
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")) == 1
        assert ExceptionRepository(work.daily).get(
            approved.candidate.candidate_id)["payload"]["state"] == "CONSUMED"


def test_revocation_and_execution_race_has_one_winner(exception_chain):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import UUID

    from trade_plan_monitor.state.market_exception_service import ExceptionAuthorityError
    from trade_plan_monitor.state.repositories import RevisionConflictError
    from trade_plan_monitor.state.simulation import (
        SimulationAuthorityError,
        SimulationCommand,
        simulate_inventory,
    )

    chain = exception_chain
    approved, signal = ready(chain)
    barrier = Barrier(2)

    def race(action):
        barrier.wait(timeout=5)
        try:
            with chain.plans._unit_of_work() as work:
                if action == "CONSUMED":
                    simulate_inventory(work, SimulationCommand(
                        plan_version_id=UUID(chain.version["id"]), cause_id=signal["signal_id"],
                        expected_cause_revision=signal["revision"], expected_inventory_revision=1,
                        quantity=signal["planned_qty"]), chain.now)
                else:
                    revoke_exception(work.daily, ExceptionRevocationCommand(
                        command_id="race-revoke", approval_id=approved.event.event_id,
                        expected_revision=2, reason="Competing withdrawal"), now=chain.now)
                work.commit()
                return action
        except (ExceptionAuthorityError, SimulationAuthorityError, RevisionConflictError):
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(race, ["CONSUMED", "REVOKED"]))
    assert outcomes.count("CONFLICT") == 1
    with chain.plans._unit_of_work() as work:
        row = ExceptionRepository(work.daily).get(approved.candidate.candidate_id)
        state = row["payload"]["state"]
        assert state in {"CONSUMED", "REVOKED"}
        fills = work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")
        assert len(fills) == int(state == "CONSUMED")
