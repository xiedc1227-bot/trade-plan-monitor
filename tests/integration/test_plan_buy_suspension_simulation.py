"""Final BUY admission uses real current guard proof in the existing transaction."""

from datetime import timedelta
from uuid import UUID

import pytest
from tests.integration.test_plan_buy_suspension_recovery import advance, guard_row
from tests.integration.test_plan_buy_suspension_runtime import chain as chain
from tests.integration.test_plan_buy_suspension_runtime import inputs, prepare
from tests.integration.test_unified_simulation_transactions import ledger_dump

from trade_plan_monitor.state.simulation import (
    SimulationAuthorityError,
    SimulationCommand,
    simulate_inventory,
)


def ready(chain, *, side="BUY", plan=None):
    owner = prepare(chain, side=side, plan=plan)
    row = advance(chain)
    result = owner.daily_evaluations.run_inputs(plan=chain.plan,
        inputs=inputs(chain, revision=row["revision"]))
    return owner, result.snapshot["signals"][0]


def command(chain, signal):
    with chain.plans._unit_of_work() as work:
        inventory = work.daily.get("simulation-position-" + chain.plan.symbol)
    return SimulationCommand(plan_version_id=UUID(chain.version["id"]),
        cause_id=signal["signal_id"], expected_cause_revision=signal["revision"],
        expected_inventory_revision=inventory["revision"], quantity=signal["executable_qty"])


def breach(chain):
    target = guard_row(chain)["state"].target
    chain.now += timedelta(seconds=1)
    with chain.plans._unit_of_work() as work:
        minute = work.history.list_minutes(chain.plan.symbol, start=target, end=target)[0]
        work.history.upsert_minutes((minute.model_copy(update={"close_fen": 2419,
            "received_at": chain.now}),))
        work.commit()
    chain.sdk.breach = target
    assert advance(chain)["state"].outcome == "LATCHED"


def test_actual_api_clear_buy_replays_once_and_later_breach_does_not_reverse_fill(chain):
    _, signal = ready(chain)
    payload = command(chain, signal).model_dump(mode="json", by_alias=True)
    receipt = chain.post("simulated-trades", payload, key="t07-one-buy")
    assert receipt["quantity"] == 100 and receipt["inventory"]["totalQty"] == 200
    breach(chain)
    assert chain.post("simulated-trades", payload, key="t07-one-buy") == receipt
    chain.post("simulated-trades", payload, key="t07-another-buy", status=409)
    with chain.plans._unit_of_work() as work:
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")) == 1
        consumed = work.daily.get(signal["signal_id"])["payload"]
        assert consumed["state"] == "SIMULATED" and consumed["simulated_qty"] == 100


@pytest.mark.parametrize("change", ["latch", "target", "generation", "revision", "callback"])
def test_old_ready_direct_participant_cannot_use_cached_proof(chain, change):
    owner, signal = ready(chain)
    cmd = command(chain, signal)
    current = owner.buy_suspension_current
    if change == "latch":
        breach(chain)
    elif change == "target":
        chain.now += timedelta(minutes=5)
    elif change == "generation":
        owner._recovery_configuration_revision += "-changed"
    elif change == "revision":
        owner.provider.daily_adjustment_factors(chain.plan.symbol, chain.now.date(),
            chain.now.date())  # An unchanged receipt keeps proof; next change invalidates it.
        chain.sdk.factor = "2.76"
        owner.provider.daily_adjustment_factors(chain.plan.symbol, chain.now.date(),
            chain.now.date())
        advance(chain)
    before = ledger_dump(chain.database)
    with chain.plans._unit_of_work() as work:
        with pytest.raises(SimulationAuthorityError, match="BUY_SUSPENSION_"):
            simulate_inventory(work, cmd, chain.now,
                buy_suspension_current=None if change == "callback" else current)
    assert ledger_dump(chain.database) == before


def test_second_previously_issued_tranche_is_blocked_after_first_fill_without_reset(chain):
    from copy import deepcopy
    from hashlib import sha256

    from tests.integration.test_unified_runtime import current_plan

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = current_plan(mixed=False).model_dump(mode="python")
    first = raw["ordinary_rules"][0]
    first["independent_signal"] = {"mode": "ONCE_PER_RULE"}
    second = deepcopy(first)
    second.update(rule_id="second-tranche", independent_signal={
        "mode": "AFTER_RULE_COMPLETED", "prior_rule_id": first["rule_id"]})
    raw["ordinary_rules"] = [first, second]
    owner, signal = ready(chain, plan=UnifiedTradePlan.model_validate(raw))
    with chain.plans._unit_of_work() as work:
        simulate_inventory(work, command(chain, signal), chain.now,
            buy_suspension_current=owner.buy_suspension_current)
        work.commit()
    # Stress the final fence with an already-issued second-tranche request,
    # rather than ask confirmation to backdate a completion on the same bar.
    identity = sha256(b"t07-issued-second-tranche").hexdigest()
    with chain.plans._unit_of_work() as work:
        row = work.daily.save(identity, kind="SIGNAL", symbol=chain.plan.symbol,
            lineage=chain.plan.plan_id, expected_revision=0,
            payload={**signal, "signal_id": identity, "rule_id": "second-tranche",
                     "occurrence_mode": "AFTER_RULE_COMPLETED"})
        work.commit()
    offered = {**row["payload"], "revision": row["revision"]}
    breach(chain)
    with chain.plans._unit_of_work() as work:
        with pytest.raises(SimulationAuthorityError, match="BUY_SUSPENSION_LATCHED"):
            simulate_inventory(work, command(chain, offered), chain.now,
                buy_suspension_current=owner.buy_suspension_current)
        assert work.daily.get(signal["signal_id"])["payload"]["simulated_qty"] == 100
        assert work.daily.get(identity)["payload"]["simulated_qty"] == 0
        assert len(work.daily.list(symbol=chain.plan.symbol, kind="SIMULATION")) == 1


def test_direct_api_latched_guard_rejects_old_ready_without_runtime_refresh(chain):
    _, signal = ready(chain)
    payload = command(chain, signal).model_dump(mode="json", by_alias=True)
    breach(chain)
    before = ledger_dump(chain.database)
    rejected = chain.post("simulated-trades", payload, status=409)
    assert "BUY_SUSPENSION_LATCHED" in {d["code"] for d in rejected["error"]["details"]}
    assert ledger_dump(chain.database) == before


def test_sell_commit_does_not_require_buy_guard_authority(chain):
    _, signal = ready(chain, side="SELL")
    breach(chain)
    with chain.plans._unit_of_work() as work:
        receipt = simulate_inventory(work, command(chain, signal), chain.now)
        work.commit()
    assert receipt.side == "SELL" and receipt.quantity == 100


def test_late_caller_failure_rolls_back_all_buy_effects(chain):
    owner, signal = ready(chain)
    cmd = command(chain, signal)
    before = ledger_dump(chain.database)
    with pytest.raises(RuntimeError, match="late caller"), chain.plans._unit_of_work() as work:
        simulate_inventory(work, cmd, chain.now,
            buy_suspension_current=owner.buy_suspension_current)
        raise RuntimeError("late caller")
    assert ledger_dump(chain.database) == before
