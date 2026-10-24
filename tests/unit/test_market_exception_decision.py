"""Schema 7 decisions expose eligibility, never infer human approval."""

import pytest
from tests.unit.test_market_exception_contract import exception_payload

from trade_plan_monitor.decision.market_exception_decision import ExceptionCalculation
from trade_plan_monitor.domain.daily_hash import daily_hash


def calculation(**changes):
    raw = dict(
        formula_version="market-linkage-calculation-v2", base_quantity=100,
        factor=None, ceiling=100, minimum=100, increment=100, candidate_quantity=100,
        capacity=500, authorized_quantity=0, blockers=["EXCEPTION_APPROVAL_REQUIRED"],
        route="WEAK_MINIMUM", approval=None)
    raw.update(changes)
    raw["calculation_hash"] = daily_hash(raw["formula_version"], raw)
    return ExceptionCalculation.model_validate(raw)


def test_eligible_quantity_never_authorizes_without_event():
    assert calculation().authorized_quantity == 0
    with pytest.raises(ValueError):
        calculation(authorized_quantity=100, blockers=[])


def test_broken_candidate_does_not_default_quantity():
    assert calculation(route="BROKEN_STRONG", candidate_quantity=None).candidate_quantity is None
    with pytest.raises(ValueError):
        calculation(route="BROKEN_STRONG", candidate_quantity=100)


def test_ordinary_schema7_retains_floor_calculation():
    assert calculation(route=None, factor="1", approval=None, authorized_quantity=100,
                       blockers=[]).authorized_quantity == 100
    with pytest.raises(ValueError):
        calculation(route=None, factor="0.5", authorized_quantity=100, blockers=[])


def test_fixture_remains_opt_in():
    assert exception_payload()["schema_version"] == 7
