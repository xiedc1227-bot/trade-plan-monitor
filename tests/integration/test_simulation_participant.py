"""Shared execution participates in caller-owned transactions without Web imports."""

from uuid import UUID

import pytest
from tests.integration.test_unified_runtime import current_chain, minute_inputs
from tests.integration.test_unified_simulation_transactions import ledger_dump

from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.state.simulation import (
    SimulationAuthorityError,
    SimulationCommand,
    simulate_inventory,
)

__all__ = ["current_chain"]
IDENTITY = "8398a937-3b0b-4a4c-8ce8-0759f729b39c"


def prepared(chain):
    evaluated = chain.runtime.run_inputs(
        plan=chain.plan, inputs=minute_inputs(chain, series=chain.series())
    )
    signal = evaluated.snapshot["signals"][0]
    with chain.plans._unit_of_work() as work:
        inventory = work.daily.get("simulation-position-601021.SH")
    return SimulationCommand(
        plan_version_id=UUID(chain.version["id"]),
        cause_id=signal["signal_id"],
        expected_cause_revision=signal["revision"],
        expected_inventory_revision=inventory["revision"],
        quantity=100,
    )


@pytest.mark.parametrize("late_failure", [False, True])
def test_participant_never_commits_the_callers_transaction(current_chain, tmp_path, late_failure):
    chain = current_chain
    command = prepared(chain)
    before = ledger_dump(tmp_path / "daily.sqlite")
    try:
        with chain.plans._unit_of_work() as work:
            receipt = simulate_inventory(
                work, command, chain.now, identity_factory=lambda: IDENTITY
            )
            assert receipt.simulation_id == IDENTITY
            assert receipt.side == "BUY"
            assert receipt.quantity == 100
            assert receipt.price_fen == 3970
            assert receipt.inventory.total_qty == 200
            assert receipt.inventory.sellable_tactical == 0
            assert work.daily.get(command.cause_id)["payload"]["state"] == "SIMULATED"
            assert work.daily.get(IDENTITY)["payload"]["quantity"] == 100
            if late_failure:
                raise RuntimeError("caller write failed after all participant writes")
    except RuntimeError as error:
        assert late_failure
        assert "caller write failed" in str(error)
    assert ledger_dump(tmp_path / "daily.sqlite") == before


def test_commit_is_explicit_and_consumed_occurrence_cannot_trade_twice(current_chain, tmp_path):
    chain = current_chain
    command = prepared(chain)
    with chain.plans._unit_of_work() as work:
        result = simulate_inventory(work, command, chain.now, identity_factory=lambda: IDENTITY)
        work.commit()
    assert result.inventory.total_qty == 200
    before = ledger_dump(tmp_path / "daily.sqlite")
    command = command.model_copy(
        update={
            "expected_cause_revision": command.expected_cause_revision + 1,
            "expected_inventory_revision": result.inventory_revision,
        }
    )
    with chain.plans._unit_of_work() as work:
        with pytest.raises(SimulationAuthorityError) as error:
            simulate_inventory(work, command, chain.now)
    assert error.value.reason == "DAILY_SIMULATION_CURRENT_FACTS_REQUIRED"
    assert ledger_dump(tmp_path / "daily.sqlite") == before


@pytest.mark.parametrize("field", ["expected_cause_revision", "expected_inventory_revision"])
def test_stale_revisions_reject_without_partial_writes(current_chain, tmp_path, field):
    chain = current_chain
    command = prepared(chain)
    command = command.model_copy(update={field: 0})
    before = ledger_dump(tmp_path / "daily.sqlite")
    with chain.plans._unit_of_work() as work:
        with pytest.raises(RevisionConflictError):
            simulate_inventory(work, command, chain.now)
    assert ledger_dump(tmp_path / "daily.sqlite") == before


def test_full_quantity_and_authority_rejections_are_transport_independent(current_chain, tmp_path):
    chain = current_chain
    command = prepared(chain)
    before = ledger_dump(tmp_path / "daily.sqlite")
    with chain.plans._unit_of_work() as work:
        with pytest.raises(ValueError, match="complete offered quantity"):
            simulate_inventory(work, command.model_copy(update={"quantity": 200}), chain.now)
    assert ledger_dump(tmp_path / "daily.sqlite") == before
    chain.now = chain.now.replace(hour=16)
    with chain.plans._unit_of_work() as work:
        with pytest.raises(SimulationAuthorityError) as error:
            simulate_inventory(work, command, chain.now)
    # The existing quote freshness guard runs before the session/authority check.
    assert error.value.reason == "DAILY_SIMULATION_CURRENT_QUOTE_REQUIRED"
    assert ledger_dump(tmp_path / "daily.sqlite") == before


def test_participant_execution_imports_no_web_adapter(current_chain, monkeypatch):
    import builtins

    chain = current_chain
    command = prepared(chain)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("trade_plan_monitor.web"):
            raise AssertionError("shared simulation attempted to import a Web adapter")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with chain.plans._unit_of_work() as work:
        receipt = simulate_inventory(work, command, chain.now, identity_factory=lambda: IDENTITY)
        assert receipt.inventory.total_qty == 200
