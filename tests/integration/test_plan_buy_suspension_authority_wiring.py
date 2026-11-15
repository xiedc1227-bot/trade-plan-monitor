"""Actual lifespan passes current runtime authority, never a captured pipeline permit."""

from types import SimpleNamespace
from uuid import uuid4

from tests.integration.test_plan_buy_suspension_recovery import advance
from tests.integration.test_plan_buy_suspension_runtime import chain as chain
from tests.integration.test_plan_buy_suspension_runtime import prepare


def test_production_and_web_service_share_the_current_owned_guard_predicate(chain):
    owner = prepare(chain)
    row = advance(chain)
    assert owner.daily_evaluations._buy_suspension_current.__self__ is owner
    with chain.plans._unit_of_work() as work:
        work.daily.lock_symbol(chain.plan.symbol)
        assert chain.plans._buy_suspension_current(work, chain.plan,
            expected_revision=row["revision"])
        actual = chain.composition._runtime
        try:
            chain.composition._runtime = SimpleNamespace(runtime_generation=uuid4())
            assert not chain.plans._buy_suspension_current(work, chain.plan,
                expected_revision=row["revision"])
        finally:
            chain.composition._runtime = actual
        assert chain.plans._buy_suspension_current(work, chain.plan,
            expected_revision=row["revision"])


def test_web_binding_does_not_survive_composition_stop_admission(chain):
    prepare(chain)
    row = advance(chain)
    with chain.plans._unit_of_work() as work:
        work.daily.lock_symbol(chain.plan.symbol)
        assert chain.plans._buy_suspension_current(work, chain.plan,
            expected_revision=row["revision"])
        chain.composition._stopping = True
        try:
            assert not chain.plans._buy_suspension_current(work, chain.plan,
                expected_revision=row["revision"])
        finally:
            chain.composition._stopping = False
