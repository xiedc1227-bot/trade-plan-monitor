"""Separate human provenance for complete supported source changes."""

from typing import Literal

from pydantic import Field, model_validator

from trade_plan_monitor.ai.source_change_models import SourceChangeAssessment
from trade_plan_monitor.ai.source_coverage_models import COMPLETE_STATES, Hash


class HumanSourceChangeAssessment(SourceChangeAssessment):
    version: Literal["source-human-change-coverage-v1"] = "source-human-change-coverage-v1"
    origin: Literal["HUMAN"] = "HUMAN"
    derivation_hash: None = None
    raw_delta_verified: bool = Field(default=False, strict=True)
    provider_full_draft_supplied: bool = Field(default=False, strict=True)
    full_draft_fidelity_verified: bool = Field(default=False, strict=True)
    human_operation_hash: Hash

    def _complete(self):
        return (bool(self.obligations) and not self.issues and self.parent_verified
                and bool(self.human_operation_hash)
                and all(row.state in COMPLETE_STATES and row.scope != "UNKNOWN"
                        for row in self.obligations))

    @model_validator(mode="after")
    def no_provider_claim(self):
        if (self.raw_delta_verified or self.provider_full_draft_supplied
                or self.full_draft_fidelity_verified):
            raise ValueError("human reassessment cannot manufacture original provider fidelity")
        return self
