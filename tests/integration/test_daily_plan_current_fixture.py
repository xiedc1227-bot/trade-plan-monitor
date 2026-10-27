"""The shared current workflow fixture obtains real complete source authority."""

from tests.integration.test_daily_plan_chain import Chain

from trade_plan_monitor.ai.source_coverage_models import COMPLETE_STATES
from trade_plan_monitor.state.source_coverage_authority import require_current_coverage
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore


def test_default_current_chain_uses_complete_source_and_actual_current_review(tmp_path):
    chain = Chain(tmp_path)
    with chain.client:
        chain.activate()
        with chain.plans._unit_of_work() as work:
            details = work.plans.get_version_details(chain.version["id"])
            stored = require_current_coverage(work, details, require_review=True)
            receipt = SourceCoverageStore(work.daily.session).receipt(details.review_id)
            assert stored.assessment.coverage_complete
            assert stored.assessment.origin == "HUMAN"
            assert stored.assessment.automatic_fidelity_verified is False
            assert stored.assessment.source_hash == details.source_hash
            assert all(row.state in COMPLETE_STATES for row in stored.assessment.obligations)
            assert receipt.coverage_bundle_hash == stored.evidence_hash
            assert work.plans.get_active(details.symbol).plan_version_id == details.id
            assert not details.daily_mapping.supplements
