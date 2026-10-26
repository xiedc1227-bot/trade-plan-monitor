"""Both private P3 exception routes require exact approval and fresh whole capital."""

from datetime import datetime, time

import pytest
from tests.integration.p3_private_chain import PrivateChain
from tests.integration.test_daily_plan_chain import SH, TUESDAY
from tests.integration.test_p3_storage import database
from tests.unit.test_p3_composition import inputs_for

from trade_plan_monitor.runtime.market_exceptions import (
    apply_exception_decision,
    current_exception_authority,
)
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityError,
    ExceptionDecisionCommand,
    ExceptionPreviewCommand,
    preview_exception,
)
from trade_plan_monitor.state.simulation import simulate_inventory

__all__ = ["database"]


@pytest.mark.parametrize(("route", "base", "proposed", "expected"), [
    ("WEAK_MINIMUM", 200, None, 100), ("BROKEN_STRONG", 1000, 300, 300)])
def test_both_routes_approve_then_separately_execute_full_quantity(
    database, monkeypatch, route, base, proposed, expected,
):
    engine, _ = database
    plan, _ = inputs_for(base, route)
    chain = PrivateChain(engine, monkeypatch, plan=plan, route=route)
    first = chain.evaluate()
    assert first.snapshot["signals"] == []
    resource = first.snapshot["exception_candidates"][0]
    candidate = ExceptionCandidate.model_validate(resource["candidate"])
    with chain.work() as work:
        def current(c):
            return current_exception_authority(work, c, chain.now)
        if route == "BROKEN_STRONG":
            with pytest.raises(ExceptionAuthorityError, match="QUANTITY_REQUIRED"):
                preview_exception(work.daily, ExceptionPreviewCommand(
                    candidate_id=candidate.candidate_id, expected_revision=1),
                    current=current, now=chain.now)
        shown = preview_exception(work.daily, ExceptionPreviewCommand(
            candidate_id=candidate.candidate_id, expected_revision=1,
            proposed_quantity=proposed), current=current, now=chain.now)
        assert shown.quantity == expected and shown.capital.outcome == "PASS"
        assert shown.current.share_capacity.mode == "UNBOUNDED"
        receipt = apply_exception_decision(work, ExceptionDecisionCommand(
            command_id="explicit-approve", candidate_id=candidate.candidate_id,
            expected_revision=1, decision="APPROVE", reason="Reviewed this exact occurrence",
            preview_id=shown.preview_id, preview_hash=shown.preview_hash), now=chain.now)
        assert receipt.candidate.frozen_quantity == expected
        assert not work.daily.list(symbol=plan.symbol, kind="SIMULATION")
        work.commit()

    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    signal = chain.evaluate().snapshot["signals"][0]
    assert signal["executable_qty"] == expected
    command = chain.command(signal)
    with chain.work() as work:
        receipt = simulate_inventory(work, command, chain.now)
        assert receipt.quantity == expected
        work.commit()


@pytest.mark.parametrize(("route", "base", "cap", "proposed"), [
    ("WEAK_MINIMUM", 200, 80000, None), ("BROKEN_STRONG", 1000, 100000, 300)])
def test_money_failure_keeps_exact_exception_intent_without_resizing(
    database, monkeypatch, route, base, cap, proposed,
):
    engine, _ = database
    plan, _ = inputs_for(base, route)
    raw = plan.model_dump(mode="json")
    raw["position"]["limit"]["capital_policy"]["cap_fen"] = cap
    plan = type(plan).model_validate(raw)
    chain = PrivateChain(engine, monkeypatch, plan=plan, route=route, quantity=400)
    resource = chain.evaluate().snapshot["exception_candidates"][0]
    candidate = resource["candidate"]
    with chain.work() as work:
        command = ExceptionPreviewCommand(candidate_id=candidate["candidate_id"],
            expected_revision=1, proposed_quantity=proposed)
        with pytest.raises(ExceptionAuthorityError, match="CAPITAL_LIMIT_EXCEEDED"):
            preview_exception(work.daily, command,
                current=lambda c: current_exception_authority(work, c, chain.now), now=chain.now)
        assert not work.daily.list(symbol=plan.symbol, kind="SIGNAL")
        assert not work.daily.list(symbol=plan.symbol, kind="SIMULATION")
        assert not work.daily.list(symbol=plan.symbol, kind="EXCEPTION_PREVIEW")
