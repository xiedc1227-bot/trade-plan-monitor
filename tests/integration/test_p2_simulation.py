"""Per-occurrence quantity validation cannot bypass required economics."""

from datetime import date

import pytest
from tests.integration.test_market_exception_storage import NOW, binding
from tests.integration.test_p2_chain import p2_chain as p2_chain
from tests.unit.test_p2_economics import economics

from trade_plan_monitor.domain.p2_policy_models import RequiredEconomics
from trade_plan_monitor.state.market_exception_models import new_candidate
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityContext,
    ExceptionAuthorityError,
    _quantity,
)
from trade_plan_monitor.state.p2_authority import P2EconomicsContext


def context(entry):
    return ExceptionAuthorityContext(binding_hash="a"*64, inventory_revision=1,
        evaluation_revision=1, authority_hash="b"*64, capacity=500, blockers=(),
        pretrade=P2EconomicsContext(policy=RequiredEconomics.model_validate(economics()),
            entry_fen=entry, symbol="600000.SH", session=date(2026, 10, 26)))


@pytest.mark.parametrize(("entry", "passes"), [(1000, True), (1001, False), (None, False)])
def test_weak_minimum_exact_quantity_gate(entry, passes):
    candidate = new_candidate(binding(), NOW)
    if passes:
        assert _quantity(candidate, context(entry), None) == 100
    else:
        with pytest.raises(ExceptionAuthorityError):
            _quantity(candidate, context(entry), None)


def test_broken_strong_never_fills_quantity_to_make_gate_pass():
    candidate = new_candidate(binding(route="BROKEN_STRONG", base_quantity=500), NOW)
    with pytest.raises(ExceptionAuthorityError):
        _quantity(candidate, context(1000), None)
    assert _quantity(candidate, context(1000), 100) == 100
    assert _quantity(candidate, context(1000), 200) == 200


@pytest.mark.parametrize("p2_chain", [(r, "REQUIRED") for r in
    ("ORDINARY", "WEAK_MINIMUM", "BROKEN_STRONG")], indirect=True)
def test_required_gate_rechecks_current_quote_before_whole_simulation(p2_chain):
    from datetime import datetime, time

    from tests.integration.test_daily_plan_chain import SH, TUESDAY
    from tests.integration.test_market_exception_runtime import approve_current, exception_inputs

    chain = p2_chain
    if chain.p2_route == "ORDINARY":
        chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    else:
        approve_current(chain)
    chain.now = datetime.combine(TUESDAY, time(9, 35), SH)
    inputs = exception_inputs(chain)
    bad = inputs.model_copy(update={"quote": inputs.quote.model_copy(update={"price_fen": 175})})
    failed = chain.runtime.run_inputs(plan=chain.plan, inputs=bad).snapshot["signals"][0]
    assert failed["pretrade_execution"]["outcome"] == "FAIL"
    assert failed["executable_qty"] == 0
    chain.simulate(failed, quantity=failed["planned_qty"], status=409)
    chain.now = chain.now.replace(minute=36)
    good = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    signal = good.snapshot["signals"][0]
    assert signal["planned_qty"] == failed["planned_qty"]
    assert signal["pretrade_execution"]["outcome"] == "PASS"
    assert chain.simulate(signal)["quantity"] == signal["planned_qty"]
