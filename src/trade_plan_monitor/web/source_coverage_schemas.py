"""Public read-only source evidence; proposals never confer trading authority."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from trade_plan_monitor.ai.source_coverage_models import (
    CoverageIssue,
    NormalizationChange,
    SourceObligation,
)
from trade_plan_monitor.web.schemas import ApiValue

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
SafeInt = Annotated[int, Field(ge=0, le=9_007_199_254_740_991)]
PositiveSafeInt = Annotated[int, Field(gt=0, le=9_007_199_254_740_991)]
Path = Annotated[str, Field(min_length=1, max_length=512)]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
State = Literal["MAPPED", "MAPPED_WITH_REGISTERED_SUPPLEMENT", "CONTEXT_VERIFIED",
                "SCOPE_EXCLUDED", "UNRESOLVED", "UNSUPPORTED", "CONFLICT"]


class SourceCoverageSummaryView(ApiValue):
    status: Literal["COMPLETE", "BLOCKED", "LEGACY_UNASSESSED", "UNKNOWN"]
    authority_granted: Literal[False] = False
    coverage_complete: bool
    current_review_bound: bool
    can_confirm_review: bool
    review_state: Literal["UNCONFIRMED", "CURRENT", "NEEDS_REVIEW", "UNKNOWN"]
    reason: Literal["SOURCE_COVERAGE_REQUIRED", "SOURCE_COVERAGE_STALE",
                    "SOURCE_COVERAGE_UPGRADE_REQUIRED", "SOURCE_COVERAGE_LIMIT_EXCEEDED"] | None
    source_hash: Hash
    candidate_plan_hash: Hash
    content_hash: Hash | None
    mapping_hash: Hash | None
    rules_version: Literal["source-coverage-rules-v1"] | None
    coverage_evidence_hash: Hash | None
    coverage_revision: PositiveSafeInt | None
    coverage_bundle_hash: Hash | None
    normalization_hash: Hash | None
    original_review_evidence_hash: Hash | None
    review_id: UUID | None
    review_revision: SafeInt
    coverage_review_receipt_hash: Hash | None
    origin: Literal["AI_NEW", "AI_HISTORICAL", "HUMAN"] | None
    automatic_fidelity_verified: bool
    obligation_count: Annotated[int, Field(ge=0, le=4096)]
    issue_count: Annotated[int, Field(ge=0, le=8192)]
    normalization_change_count: Annotated[int, Field(ge=0, le=2000)]
    total_rows: Annotated[int, Field(ge=0, le=14288)]

    @model_validator(mode="after")
    def coherent(self):
        if self.coverage_complete != (self.status == "COMPLETE"):
            raise ValueError("coverage status and completeness differ")
        if self.current_review_bound and (not self.coverage_complete or self.review_id is None):
            raise ValueError("current review requires complete evidence and review identity")
        if (self.review_state == "CURRENT") != self.current_review_bound:
            raise ValueError("current review state differs from its receipt binding")
        proof = (self.content_hash, self.mapping_hash, self.rules_version,
                 self.coverage_evidence_hash, self.original_review_evidence_hash)
        if self.current_review_bound and (self.review_revision == 0
                or self.coverage_review_receipt_hash is None or self.coverage_revision is None
                or self.coverage_bundle_hash is None or self.reason is not None or None in proof):
            raise ValueError("current review is missing its complete receipt tuple")
        if self.can_confirm_review and (not self.coverage_complete or self.review_id is not None
                or self.review_revision != 0 or self.current_review_bound
                or self.review_state != "UNCONFIRMED" or None in proof
                or self.coverage_revision is None or self.coverage_bundle_hash is None
                or self.reason is not None):
            raise ValueError("confirmation observation requires an unconfirmed complete draft")
        if self.automatic_fidelity_verified and (self.origin != "AI_NEW"
                or not self.coverage_complete or self.normalization_hash is None):
            raise ValueError("automatic fidelity requires its current original AI normalization")
        if self.coverage_complete and (self.issue_count or not self.obligation_count):
            raise ValueError("complete coverage requires obligations and no source issues")
        if self.total_rows != (self.obligation_count + self.issue_count
                               + self.normalization_change_count):
            raise ValueError("coverage row counts differ")
        return self


class SourceMappingProposalView(ApiValue):
    """The saved mapping proposal, separately from the server's treatment."""

    proposed_disposition: Literal["POLICY", "INVENTORY_ASSERTION", "BACKGROUND", "CONTEXT",
                                  "UNRESOLVED", "UNSUPPORTED"]
    semantic_role: Literal["DIRECTIVE", "HISTORICAL", "ACCOUNT", "COMMENTARY", "AMBIGUOUS"] | None
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    proposed_paths: tuple[str, ...] = Field(max_length=512)


class SourceHumanSupplementLinkView(ApiValue):
    supplement_id: Identifier
    path: Path
    candidate_content_hash: Hash


class SourceObligationView(ApiValue):
    version: Literal["source-obligation-v1"]
    rules_version: Literal["source-coverage-rules-v1"]
    source_hash: Hash
    clause_id: Identifier
    start: Annotated[int, Field(ge=0, le=150_000)]
    end: Annotated[int, Field(gt=0, le=150_000)]
    excerpt: Annotated[str, Field(min_length=1, max_length=512)]
    kind: Literal["DECLARATION", "PREDICATE", "RELATION", "CONTEXT", "SCOPE_EXCLUSION", "UNKNOWN"]
    scope: Literal["PLAN", "BUY", "SELL", "RISK", "ALERT", "UNKNOWN"]
    server_state: State
    semantics_json: Annotated[str, Field(max_length=8192)] | None
    group_id: Hash | None
    relation_ids: tuple[Hash, ...] = Field(max_length=64)
    paths: tuple[Path, ...] = Field(max_length=512)
    obligation_id: Hash
    mapping_proposal: SourceMappingProposalView | None
    human_supplements: tuple[SourceHumanSupplementLinkView, ...] = Field(max_length=2000)

    @model_validator(mode="after")
    def exact_obligation(self):
        value = self.model_dump(exclude={"server_state", "mapping_proposal", "human_supplements"})
        SourceObligation.model_validate(value | dict(state=self.server_state))
        return self


class SourceCoverageIssueView(ApiValue):
    code: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")]
    path: Path
    start: Annotated[int, Field(ge=0, le=150_000)] | None
    end: Annotated[int, Field(gt=0, le=150_000)] | None
    message: Annotated[str, Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def exact_issue(self):
        CoverageIssue.model_validate(self.model_dump())
        return self


class SourceNormalizationChangeView(ApiValue):
    path: Path
    before_json: Annotated[str, Field(max_length=8192)]
    after_json: Annotated[str, Field(max_length=8192)]
    reason: Identifier
    trace_role: Literal["CURRENT_ASSESSMENT", "HISTORICAL_INPUT"]
    source_hash: Hash
    before_hash: Hash
    after_hash: Hash
    evidence_hash: Hash

    @model_validator(mode="after")
    def exact_change(self):
        NormalizationChange.model_validate(self.model_dump(include={
            "path", "before_json", "after_json", "reason"}))
        return self


class SourceObligationRow(ApiValue):
    kind: Literal["OBLIGATION"] = "OBLIGATION"
    row_index: SafeInt
    obligation: SourceObligationView


class SourceIssueRow(ApiValue):
    kind: Literal["ISSUE"] = "ISSUE"
    row_index: SafeInt
    issue: SourceCoverageIssueView


class SourceNormalizationRow(ApiValue):
    kind: Literal["NORMALIZATION_CHANGE"] = "NORMALIZATION_CHANGE"
    row_index: SafeInt
    change: SourceNormalizationChangeView


SourceCoverageRow = Annotated[
    SourceObligationRow | SourceIssueRow | SourceNormalizationRow, Field(discriminator="kind")]


class SourceCoveragePage(ApiValue):
    authority_granted: Literal[False] = False
    plan_version_id: UUID
    summary: SourceCoverageSummaryView
    items: tuple[SourceCoverageRow, ...] = Field(max_length=100)
    limit: Annotated[int, Field(ge=1, le=100)]
    returned_count: Annotated[int, Field(ge=0, le=100)]
    total_rows: Annotated[int, Field(ge=0, le=14288)]
    next_cursor: Annotated[str, Field(min_length=1, max_length=512)] | None

    @model_validator(mode="after")
    def counts(self):
        if self.returned_count != len(self.items) or self.returned_count > self.limit:
            raise ValueError("coverage page count differs")
        if self.total_rows != self.summary.total_rows:
            raise ValueError("coverage page total differs")
        if self.items:
            start = self.items[0].row_index
            if [row.row_index for row in self.items] != list(range(start, start + len(self.items))):
                raise ValueError("coverage page rows are not consecutive")
            if start + len(self.items) > self.total_rows:
                raise ValueError("coverage page rows exceed the total")
            if (self.next_cursor is not None) != (start + len(self.items) < self.total_rows):
                raise ValueError("coverage continuation differs from its row range")
        elif self.total_rows or self.next_cursor is not None:
            raise ValueError("nonempty evidence cannot return an empty page")
        for row in self.items:
            expected = ("OBLIGATION" if row.row_index < self.summary.obligation_count else
                "ISSUE" if row.row_index < self.summary.obligation_count + self.summary.issue_count
                else "NORMALIZATION_CHANGE")
            if row.kind != expected:
                raise ValueError("coverage row kind differs from its stream position")
        return self
