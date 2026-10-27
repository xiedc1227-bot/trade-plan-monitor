"""Original leaf identities retained by a private consumer-placement alias."""

from trade_plan_monitor.ai.source_assurance_binding import CandidateBinding
from trade_plan_monitor.ai.source_coverage_models import Hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue


class AssuranceReuseRef(DailyValue):
    original_owner_binding: CandidateBinding
    original_assurance_hash: Hash
    original_current_review_hash: Hash
    original_manifest_hash: Hash
    lineage_hash: Hash
