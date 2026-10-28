"""Activation delegates its source check inside the existing transaction fence."""

import pytest
from tests.integration.test_source_coverage_authority import _confirm, _save
from tests.integration.test_source_coverage_authority_save import state as state

from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.state.repositories import PlanRepository, RepositoryError


def test_private_source_reader_can_reject_before_any_activation_write(state):
    identity, draft = _save(state)
    _confirm(state, identity)

    class RejectingPlans(PlanRepository):
        def _require_source_review(self, target_id):
            assert target_id == identity
            assert self.get_active(draft.symbol) is None
            raise RepositoryError("Frozen source selection is not authorized")

    with pytest.raises(RepositoryError, match="^Frozen source selection is not authorized$"):
        with state.work() as work:
            original = work.plans
            plans = RejectingPlans(
                original._session, clock=original._clock,
                id_factory=original._id_factory, events=original._events,
            )
            plans.activate(draft.to_executable(), expected_revision=0,
                           validation=PlanValidationResult(issues=()))
            work.commit()

    with state.work() as work:
        assert work.plans.get_active(draft.symbol) is None
        assert work.plans.get_version_details(identity).status == "DRAFT"
