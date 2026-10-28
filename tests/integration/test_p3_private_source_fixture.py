"""Synthetic P3 fixtures use real current human source review and SQL owners."""

import pytest
from tests.integration.p3_private_chain import PrivateChain
from tests.integration.test_p3_storage import database
from tests.unit.test_p3_composition import inputs_for

from trade_plan_monitor.ai.daily_review import semantic_values
from trade_plan_monitor.ai.source_obligations import declarations
from trade_plan_monitor.domain import plan_codec
from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanSource, PlanVersion
from trade_plan_monitor.state.source_action_authority import require_source_action_authority
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore

__all__ = ["database"]


@pytest.mark.parametrize(("route", "base", "cap", "quantity"), [
    ("WEAK_MINIMUM", 200, None, 0),
    ("BROKEN_STRONG", 1000, None, 0),
    ("WEAK_MINIMUM", 200, 80000, 400),
    ("BROKEN_STRONG", 1000, 100000, 400),
])
def test_private_p3_fixture_has_actual_source_review_and_activation(
    database, monkeypatch, route, base, cap, quantity,
):
    engine, _ = database
    original, _ = inputs_for(base, route)
    raw = original.model_dump(mode="json")
    if cap is not None:
        raw["position"]["limit"]["capital_policy"]["cap_fen"] = cap
    plan = type(original).model_validate(raw)
    # This pre-construction check proves the existing codec already admits P3;
    # no private codec replacement is needed to reach the actual current gate.
    assert load_plan_json(plan.model_dump_json()) == plan

    chain = PrivateChain(engine, monkeypatch, plan=plan, route=route, quantity=quantity)

    assert plan_codec.load_plan_json is load_plan_json
    with chain.work() as work:
        basis = require_source_action_authority(work, chain.version_id)
        assert basis.basis == "CURRENT" and basis.coverage_evidence_hash
        version = work.daily.session.get(PlanVersion, chain.version_id)
        source = work.daily.session.get(PlanSource, version.source_id)
        assert load_plan_json(version.payload_json) == plan == chain.plan
        details = work.plans.get_version_details(chain.version_id)
        assert {row.path: row.value for row in declarations(source.source_text)} == semantic_values(
            load_daily_draft_json(version.payload_json))
        assert details.extraction_id is None and details.review_origin == "MANUAL"
        stored = SourceCoverageStore(work.daily.session).latest(chain.version_id)
        assert stored.assessment.coverage_complete
        assert stored.assessment.origin == "HUMAN"
        assert not stored.assessment.automatic_fidelity_verified and stored.inputs is None
        receipt = SourceCoverageStore(work.daily.session).receipt(details.review_id)
        assert receipt.coverage_evidence_hash == stored.assessment.evidence_hash
        assert receipt.original_review_evidence_hash == details.review_evidence_hash
        assert details.review_id == "private-reviewed"
        assert details.review_confirmed_at == chain.now
        for model in (ActivePlan, PlanActivationState):
            actual = work.daily.session.get(model, plan.symbol)
            assert actual.plan_version_id == chain.version_id and actual.revision == 1
        assert work.daily.get("review-" + chain.version_id)["payload"]["confirmed"]
        assert not work.daily.list(symbol=plan.symbol, kind="SIMULATION")


def test_private_p3_fixture_cannot_reuse_its_review_after_a_new_coverage_assessment(
    database, monkeypatch,
):
    engine, _ = database
    chain = PrivateChain(engine, monkeypatch)
    with chain.work() as work:
        store = SourceCoverageStore(work.daily.session)
        current = store.latest(chain.version_id)
        assert require_source_action_authority(work, chain.version_id).basis == "CURRENT"
        store.append(chain.version_id, current.assessment, inputs=current.inputs,
            expected_revision=current.revision, command_id="fixture-reassessment", now=chain.now)
        work.commit()
    with chain.work() as work, pytest.raises(
        SourceCoverageAuthorityError, match="SOURCE_COVERAGE_STALE"
    ):
        require_source_action_authority(work, chain.version_id)
