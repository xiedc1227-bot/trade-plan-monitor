"""Exact server-owned identity shared by initial, change and aggregate evidence."""

from typing import Literal

from pydantic import Field

from trade_plan_monitor.ai.source_coverage_models import Hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue, Identifier


class CandidateBinding(DailyValue):
    preparation_id: Identifier
    item_index: int = Field(strict=True, ge=0, le=511)
    source_id: Identifier
    source_revision: int = Field(strict=True, ge=1, le=9_007_199_254_740_991)
    source_binding_hash: Hash
    candidate_revision: int = Field(strict=True, ge=1, le=9_007_199_254_740_991)
    candidate_hash: Hash
    review_evidence_hash: Hash
    attempt_id: Identifier | None
    inputs_hash: Hash | None
    independent: bool = Field(strict=True)
    rules_version: Literal["source-coverage-rules-v1"] = "source-coverage-rules-v1"
