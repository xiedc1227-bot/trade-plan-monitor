"""The current quote rejects or admits the original whole frozen quantity."""

from datetime import datetime, time

import pytest
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_p3_runtime import signal_fixture
from tests.integration.test_p3_storage import database

from trade_plan_monitor.decision.unified_lifecycle import check_execution
from trade_plan_monitor.state.daily_state_models import DailySignalState


@pytest.mark.parametrize(("price", "quantity"), [(2752, 200), (2753, 0), (2000, 200)])
def test_current_quote_never_clips_frozen_quantity(price, quantity):
    plan, _, signal = signal_fixture()
    # Preserve source zone validity while testing only the cap boundary.
    raw = plan.model_dump(mode="json")
    raw["levels"]["low_buy"].update(low_fen=100, high_fen=3000)
    from tests.unit.test_p3_composition import inputs_for

    from trade_plan_monitor.decision.p3_composition import evaluate_p3_market
    from trade_plan_monitor.decision.unified_lifecycle import confirm_signal
    from trade_plan_monitor.domain.p3_policy_models import P3TradePlan
    plan = P3TradePlan.model_validate(raw)
    _, inputs = inputs_for()
    result = evaluate_p3_market(plan, plan.ordinary_rules[0], **inputs)
    signal = confirm_signal(plan, plan.ordinary_rules[0], series=inputs["series"], facts=(),
        previous=(), session_dates=inputs["session_dates"], plan_version_id="p3-plan",
        review_id="p3-review", linkage=result.decision)
    checked = check_execution(plan, signal, inventory={"known": True, "total_qty": 0,
        "revision": 1}, quote_fen=price, evaluated_at=datetime.combine(TUESDAY, time(10), SH),
        tradable=True, risk_blocked=False, risk_known=True,
        capital_inputs={"retained_basis_fen": None, "book_revision": None})
    assert checked["planned_qty"] == 200
    assert checked["executable_qty"] == quantity
    assert checked["capital_execution"]["after_fen"] == 200*price
    DailySignalState.model_validate(checked)


def test_replaced_capital_policy_cannot_reuse_frozen_signal():
    plan, _, signal = signal_fixture()
    raw = plan.model_dump(mode="json")
    raw["position"]["limit"]["capital_policy"]["cap_fen"] += 1
    plan = type(plan).model_validate(raw)
    checked = check_execution(plan, signal, inventory={"known": True, "total_qty": 0},
        quote_fen=161, evaluated_at=datetime.combine(TUESDAY, time(10), SH),
        tradable=True, risk_blocked=False, risk_known=True)
    assert checked["state"] == "INVALIDATED" and checked["executable_qty"] == 0
    assert "P3_FROZEN_POLICY_CHANGED" in checked["blockers"]



__all__ = ["database"]


def test_private_runtime_executes_atomic_cost_debit_and_rejects_reuse(database, monkeypatch):
    from tests.integration.p3_private_chain import PrivateChain

    from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
    from trade_plan_monitor.state.repositories import RevisionConflictError
    from trade_plan_monitor.state.simulation import simulate_inventory
    engine, _ = database
    chain = PrivateChain(engine, monkeypatch, mode="OPEN_COST_CAP")
    chain.evaluate()
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    current = chain.evaluate()
    assert current.snapshot["signals"], current.snapshot["market_linkage"]
    signal = current.snapshot["signals"][0]
    assert signal["executable_qty"] == 200
    command = chain.command(signal)
    with chain.work() as work:
        receipt = simulate_inventory(work, command, chain.now, identity_factory=lambda: "buy-once")
        book = CapitalRepository(work.daily.session).get(chain.plan.symbol)
        assert receipt.quantity == 200 and receipt.inventory.total_qty == 200
        assert book.retained_basis_fen == 32700
        work.commit()
    with chain.work() as work:
        with pytest.raises(RevisionConflictError):
            simulate_inventory(work, command, chain.now)
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")) == 1



def test_reconciliation_after_ready_rejects_stale_execution_without_mutation(database, monkeypatch):
    from tests.integration.p3_private_chain import PrivateChain

    from trade_plan_monitor.state.daily_accounting import DailyAccounting
    from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
    from trade_plan_monitor.state.simulation import SimulationAuthorityError, simulate_inventory
    engine, _ = database
    chain = PrivateChain(engine, monkeypatch, mode="OPEN_COST_CAP", quantity=400)
    chain.open_basis(450000)
    chain.evaluate()
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    ready = chain.evaluate()
    signal = ready.snapshot["signals"][0]
    assert signal["executable_qty"] == 200
    command = chain.command(signal)
    chain.open_basis(530000, "corrected-opening")
    with chain.work() as work:
        with pytest.raises(SimulationAuthorityError, match="SIGNAL_NOT_EXECUTABLE"):
            simulate_inventory(work, command, chain.now)
        inventory = DailyAccounting(work.daily).snapshot(chain.plan.symbol, chain.now.date())
        assert inventory["total_qty"] == 400
        book = CapitalRepository(work.daily.session).get(chain.plan.symbol)
        assert book.retained_basis_fen == 530000
        assert not work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")
    corrected = chain.evaluate()
    assert corrected.snapshot["signals"][0]["planned_qty"] == 200
    assert corrected.snapshot["signals"][0]["executable_qty"] == 0
    assert not corrected.duplicate


def test_actual_technical_risk_sell_needs_no_opening_cost(database, monkeypatch):
    from tests.integration.p3_private_chain import PrivateChain
    from tests.unit.test_p2_policy_contract import p2_payload
    from tests.unit.test_p3_composition import inputs_for

    from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
    from trade_plan_monitor.state.simulation import simulate_inventory
    engine, _ = database
    plan, _ = inputs_for(mode="OPEN_COST_CAP")
    raw = plan.model_dump(mode="json")
    severe = next(b for b in p2_payload()["risk_branches"] if b["kind"] == "SEVERE_TECHNICAL")
    severe["condition"] = raw["ordinary_rules"][0]["condition"]
    raw["risk_branches"] = [severe]
    plan = type(plan).model_validate(raw)
    chain = PrivateChain(engine, monkeypatch, mode="OPEN_COST_CAP", quantity=400, plan=plan)
    chain.evaluate()
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    result = chain.evaluate()
    risk = result.snapshot["risk_action"]
    assert risk["status"] == "RISK_EXIT" and risk["tactical_qty"] == 400
    command = chain.command(risk, quantity=400)
    with chain.work() as work:
        assert CapitalRepository(work.daily.session).get(plan.symbol) is None
        receipt = simulate_inventory(work, command, chain.now, identity_factory=lambda: "risk-sell")
        assert receipt.side == "SELL" and receipt.inventory.total_qty == 0
        assert CapitalRepository(work.daily.session).get(plan.symbol) is None
        work.commit()



def test_late_failure_rolls_back_actual_capital_inventory_signal_and_receipt(database, monkeypatch):
    from tests.integration.p3_private_chain import PrivateChain
    from tests.integration.test_unified_simulation_transactions import ledger_dump

    from trade_plan_monitor.state.daily_repository import DailyRepository
    from trade_plan_monitor.state.simulation import simulate_inventory
    engine, path = database
    chain = PrivateChain(engine, monkeypatch, mode="OPEN_COST_CAP")
    chain.evaluate()
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    signal = chain.evaluate().snapshot["signals"][0]
    command = chain.command(signal)
    before = ledger_dump(path)
    original = DailyRepository.save
    def fail_receipt(self, identity, **kwargs):
        if kwargs["kind"] == "SIMULATION":
            raise RuntimeError("injected P3 late failure")
        return original(self, identity, **kwargs)
    monkeypatch.setattr(DailyRepository, "save", fail_receipt)
    with pytest.raises(RuntimeError, match="injected P3 late failure"):
        with chain.work() as work:
            simulate_inventory(work, command, chain.now, identity_factory=lambda: "rollback-buy")
            work.commit()
    assert ledger_dump(path) == before
