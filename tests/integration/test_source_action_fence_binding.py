"""Live consumers retain their original native binding after fresh source reads."""

import pytest
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_action_orm_freshness import (
    _AT,
    _actual_update,
    _hold,
    _ordinary_command,
)
from tests.integration.test_source_coverage_exception_actions import (
    _candidate,
    _ledger,
    _preview,
)
from tests.integration.test_source_coverage_exception_actions import (
    exception_chain as exception_chain,
)
from tests.integration.test_source_coverage_risk_simulation import _command, _ready
from tests.integration.test_source_coverage_simulation_actions import current as current

from trade_plan_monitor.runtime.daily_service import _action_source
from trade_plan_monitor.state import source_action_authority
from trade_plan_monitor.state.market_exception_service import ExceptionAuthorityError
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.simulation import (
    SimulationAuthorityError,
    simulate_inventory,
)


@pytest.mark.parametrize("mutation", ["policy", "activation", "review"])
def test_actual_ordinary_simulation_refreshes_preheld_owners_in_its_existing_writer(
    current, mutation,
):
    chain, signal = current
    payload = _ordinary_command(chain, signal)
    with chain.plans._unit_of_work() as work:
        held = _hold(work, chain.version["id"], chain.plan.symbol)
        _actual_update(work, held, mutation)
        with pytest.raises((SimulationAuthorityError, RepositoryError, ValueError)):
            simulate_inventory(work, payload, chain.now)
        assert not work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")


def test_runtime_source_join_cannot_adopt_a_different_live_activation(current):
    chain, _ = current
    with chain.plans._unit_of_work() as work:
        original = work.plans.get_active(chain.plan.symbol)
        held = _hold(work, chain.version["id"], chain.plan.symbol)
        _actual_update(work, held, "activation")
        basis, generation = _action_source(work, chain.version["id"],
            activation_revision=original.revision)
        assert basis is None
        assert generation == {"blocker": "SOURCE_COVERAGE_STALE"}


def test_exception_preview_cannot_adopt_an_activation_changed_after_native_inputs(
    exception_chain, monkeypatch,
):
    chain = exception_chain
    candidate = _candidate(chain)
    before = _ledger(chain)
    original = source_action_authority.require_source_action_authority
    observed = []

    def changed_after_native(work, version_id, **kwargs):
        held = _hold(work, version_id, chain.plan.symbol)
        _actual_update(work, held, "activation")
        observed.append(held)
        return original(work, version_id, **kwargs)

    monkeypatch.setattr(source_action_authority, "require_source_action_authority",
                        changed_after_native)
    with pytest.raises(ExceptionAuthorityError, match="SOURCE_COVERAGE_STALE"):
        _preview(chain, candidate)
    assert observed
    assert _ledger(chain) == before
    with chain.plans._unit_of_work() as work:
        assert work.plans.get_active(chain.plan.symbol).revision == 1


@pytest.mark.parametrize("mutation", ["policy", "activation", "review"])
def test_actual_cutover_simulation_refreshes_preheld_owners_in_its_existing_writer(
    legacy, mutation,
):
    case = legacy()
    _ready(case)
    payload = _command(case)
    with case.work() as work:
        held = _hold(work, case.id, case.draft.symbol)
        _actual_update(work, held, mutation)
        with pytest.raises((SimulationAuthorityError, RepositoryError, ValueError)):
            simulate_inventory(work, payload, _AT)
        assert not work.daily.list(symbol=case.draft.symbol, kind="SIMULATION")


@pytest.mark.parametrize("mutation", ["policy", "activation", "review"])
def test_helper_rechecks_same_writer_sql_changes_after_the_native_simulation_read(
    current, mutation, monkeypatch,
):
    chain, signal = current
    payload = _ordinary_command(chain, signal)
    original = source_action_authority.require_source_action_authority
    held_owners = []

    def actual_sql_changed_inside_writer(work, version_id, **kwargs):
        held = _hold(work, version_id, chain.plan.symbol)
        held_owners.append(held)
        _actual_update(work, held, mutation)
        return original(work, version_id, **kwargs)

    monkeypatch.setattr(source_action_authority, "require_source_action_authority",
                        actual_sql_changed_inside_writer)
    with chain.plans._unit_of_work() as work:
        with pytest.raises((SimulationAuthorityError, RepositoryError, ValueError)):
            receipt = simulate_inventory(work, payload, chain.now)
            assert receipt.quantity == 100
        assert held_owners
        assert not work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")
