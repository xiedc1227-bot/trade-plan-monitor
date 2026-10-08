"""Explicit human preparation review, exact provenance and one frozen research plan."""

import re
from datetime import datetime, time
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from trade_plan_monitor.ai.daily_review import DailyMapping, build_daily_review
from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    LoopPlanExtractionResult,
    OpeningAccountFacts,
    validate_opening_evidence,
)
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import (
    KnownLoopCash,
    LoopAccountInput,
    LoopInitialLot,
    UnknownLoopCash,
)
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import (
    LoopPlanReview,
    LoopPlanVersion,
    LoopSchedule,
    LoopScheduleEntry,
    LoopTimestamp,
)
from trade_plan_monitor.backtest.preparation_models import (
    PreparationCandidateInput,
    PreparationRecord,
    PreparationSource,
)
from trade_plan_monitor.backtest.research_input import ResearchValue, _confirmed
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.domain.daily_plan_models import Text
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

_UNSUPPORTED = re.compile(
    r"部分成交|挂单|基本面.*(?:退出|卖出)|partial fill|pending.order|fundamental.*exit",
    re.I,
)


class PreparationSemanticError(ValueError):
    """A sanitized semantic/review conflict without untrusted source or provider text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PreparationReviewCommand(ResearchValue):
    """Only this explicit human mutation can register corrections and scoped supplements."""

    expected_revision: int = Field(ge=1)
    expected_source_revision: int = Field(ge=1)
    expected_candidate_revision: int = Field(ge=1)
    candidate_hash: Sha256Hex
    evidence_hash: Sha256Hex
    confirmed: Annotated[Literal[True], BeforeValidator(_confirmed)]
    evidence: Text
    draft: UnifiedPlanDraft | None = None
    mapping: DailyMapping | None = None
    account: LoopAccountInput | None = None

    @model_validator(mode="after")
    def bounded(self):
        # Reuse the existing byte/node/depth guard, without creating durable state or approval.
        PreparationCandidateInput(
            payload_json=canonical_json(self),
            validation="VALID",
            evidence_hash="0" * 64,
        )
        return self


class FrozenPreparedPlan(ResearchValue):
    schema_version: Literal["prepared-loop-plan-v1"] = "prepared-loop-plan-v1"
    preparation_id: StableIdentifier
    source_revision: int = Field(ge=1)
    extraction_candidate_revision: int = Field(ge=1)
    extraction_candidate_hash: Sha256Hex
    extraction_evidence_hash: Sha256Hex
    source: PreparationSource
    opening_evidence: OpeningAccountFacts
    mapping: DailyMapping
    account: LoopAccountInput
    account_origin: Literal["SOURCE", "HUMAN_REVIEW"]
    version: LoopPlanVersion

    @property
    def schedule(self) -> LoopSchedule:
        return LoopSchedule(
            entries=(
                LoopScheduleEntry(
                    effective_trade_date=self.source.effective_trade_date,
                    version=self.version,
                ),
            )
        )

    @property
    def manifest_hash(self) -> str:
        return sha256(("prepared-loop-plan-v1\0" + canonical_json(self)).encode()).hexdigest()

    @model_validator(mode="after")
    def bound(self):
        if any(
            value is None
            for value in (
                self.source.authored_at,
                self.source.available_at,
                self.source.effective_trade_date,
            )
        ):
            raise ValueError("frozen source chronology is incomplete")
        validate_opening_evidence(self.opening_evidence, self.source.text)
        review = build_daily_review(
            UnifiedPlanDraft.from_executable(self.version.snapshot),
            self.mapping,
            self.source.text,
        )
        if (
            review.issues
            or review.mapping != self.mapping
            or any(_UNSUPPORTED.search(c.excerpt) for c in self.mapping.clauses)
        ):
            raise ValueError("frozen mapping has unresolved or noncanonical evidence")
        digest = _evidence_digest(
            source_hash=self.source.binding_hash,
            extraction_candidate_hash=self.extraction_candidate_hash,
            extraction_evidence_hash=self.extraction_evidence_hash,
            opening_evidence=self.opening_evidence,
            mapping=self.mapping,
            account=self.account,
            account_origin=self.account_origin,
            plan_hash=self.version.plan_hash,
            evidence=self.version.review.evidence,
        )
        if (
            self.version.evidence_hash != digest
            or self.version.version_id != "prepared-" + digest
            or self.version.source_hashes != (self.source.binding_hash,)
            or self.version.authored_at != self.source.authored_at
            or self.version.available_at != self.source.available_at
            or self.version.information_cutoff != self.source.available_at
        ):
            raise ValueError("frozen plan does not bind the exact source/account/review")
        if self.account_origin == "SOURCE" and self.account != _source_account(
            self.opening_evidence,
            self.source,
        ):
            raise ValueError("source account differs from its exact original facts")
        start = max(
            self.source.available_at,
            datetime.combine(self.source.effective_trade_date, time.min, SHANGHAI),
        )
        if self.schedule.select(start) is None or self.account.snapshot_at > start:
            raise ValueError("frozen account/plan chronology does not cover the historical start")
        if sum(lot.quantity for lot in self.account.lots) > self.version.snapshot.position.max_qty:
            raise ValueError("reviewed inventory exceeds the plan maximum")
        return self


def _evidence_digest(**values):
    return sha256(
        canonical_json(
            {
                "domain": "prepared-loop-review-evidence-v1",
                **values,
            }
        ).encode()
    ).hexdigest()


def _original_extraction(record: PreparationRecord) -> LoopPlanExtractionResult:
    candidate = record.candidate
    if candidate is None or not record.attempts:
        raise PreparationSemanticError("REVIEW_REQUIRED")
    try:
        result = LoopPlanExtractionResult.model_validate_json(candidate.payload_json)
        # This AI boundary rejects human supplements/scope selections even if a flag is forged.
        output = LoopPlanExtractionOutput(
            schema_version=result.schema_version,
            draft=result.draft,
            clauses=result.daily_mapping.clauses,
            bindings=result.daily_mapping.bindings,
            assumptions=result.assumptions,
            warnings=result.warnings,
            opening_account=result.opening_account,
        )
        if result.daily_mapping.supplements:
            raise ValueError("AI cannot register supplements")
        reviewed = output.review(record.source.text)
        validate_opening_evidence(result.opening_account, record.source.text)
        digest = sha256(
            canonical_json(
                {
                    "domain": "monitor-loop-extraction-evidence-v1",
                    "source_binding_hash": record.source.binding_hash,
                    "plan_mapping": reviewed.mapping,
                    "opening_account": result.opening_account,
                }
            ).encode()
        ).hexdigest()
        if (
            result.status is not PlanExtractionStatus.SUCCEEDED
            or result.source_id != record.source.source_id
            or result.source_text_sha256 != record.source.source_hash
            or result.source_binding_hash != record.source.binding_hash
            or result.authored_at != record.source.authored_at
            or result.available_at != record.source.available_at
            or result.effective_trade_date != record.source.effective_trade_date
            or str(result.request_id) != record.attempts[-1].attempt_id
            or result.evidence_hash != digest
            or candidate.evidence_hash != digest
        ):
            raise ValueError("original extraction binding changed")
        if any(_UNSUPPORTED.search(c.excerpt) for c in result.daily_mapping.clauses):
            raise PreparationSemanticError("UNSUPPORTED_SOURCE")
        return result
    except PreparationSemanticError:
        raise
    except ValueError:
        raise PreparationSemanticError("EXTRACTION_BINDING_CONFLICT") from None


def _source_account(facts: OpeningAccountFacts, source: PreparationSource) -> LoopAccountInput:
    if facts.snapshot_at is None or (facts.inventory_quantity is None and facts.lots):
        raise PreparationSemanticError("ACCOUNT_REVIEW_REQUIRED")
    if any(lot.bucket is None for lot in facts.lots):
        raise PreparationSemanticError("ACCOUNT_REVIEW_REQUIRED")
    return LoopAccountInput(
        snapshot_at=facts.snapshot_at.value,
        inventory_known=facts.inventory_quantity is not None,
        cash=(
            KnownLoopCash(balance_fen=facts.cash_fen.value) if facts.cash_fen else UnknownLoopCash()
        ),
        lots=tuple(
            LoopInitialLot(
                lot_key=lot.lot_key,
                bucket=lot.bucket.value,
                quantity=lot.quantity.value,
                cost_basis_fen=lot.cost_basis_fen,
                acquired_trade_date=lot.acquired_trade_date.value
                if lot.acquired_trade_date
                else None,
                sellable_quantity=lot.sellable_quantity.value if lot.sellable_quantity else None,
                evidence=canonical_json(lot),
            )
            for lot in facts.lots
        ),
        opening_mark=None,
        evidence=f"Source-bound opening account: {source.binding_hash}",
    )


def prepare_frozen_plan(
    record: PreparationRecord,
    command: PreparationReviewCommand,
    reviewed_at: LoopTimestamp,
) -> FrozenPreparedPlan:
    """Verify a human mutation without granting authority through validation alone."""
    if record.work_claim is not None:
        raise PreparationSemanticError("WORKER_CLAIM_PENDING")
    if record.status != "CANDIDATE" or record.candidate is None:
        raise PreparationSemanticError("REVIEW_REQUIRED")
    if (
        command.expected_revision != record.revision
        or command.expected_source_revision != record.source_revision
        or command.expected_candidate_revision != record.candidate_revision
        or command.candidate_hash != record.candidate.candidate_hash
        or command.evidence_hash != record.candidate.evidence_hash
    ):
        raise PreparationSemanticError("REVIEW_BINDING_CONFLICT")
    original = _original_extraction(record)
    if any(
        value is None
        for value in (
            record.source.authored_at,
            record.source.available_at,
            record.source.effective_trade_date,
        )
    ):
        raise PreparationSemanticError("SOURCE_TIME_REQUIRED")
    draft = command.draft or original.draft
    if (draft.symbol, draft.market) != (original.draft.symbol, original.draft.market):
        raise PreparationSemanticError("SOURCE_ASSET_CONFLICT")
    snapshot = draft.to_executable()
    if snapshot is None:
        raise PreparationSemanticError("REVIEW_UNRESOLVED")
    reviewed = build_daily_review(
        draft, command.mapping or original.daily_mapping, record.source.text
    )
    if reviewed.issues:
        raise PreparationSemanticError("REVIEW_UNRESOLVED")
    account = command.account or _source_account(original.opening_account, record.source)
    origin = "HUMAN_REVIEW" if command.account is not None else "SOURCE"
    digest = _evidence_digest(
        source_hash=record.source.binding_hash,
        extraction_candidate_hash=command.candidate_hash,
        extraction_evidence_hash=command.evidence_hash,
        opening_evidence=original.opening_account,
        mapping=reviewed.mapping,
        account=account,
        account_origin=origin,
        plan_hash=plan_sha256(snapshot),
        evidence=command.evidence,
    )
    version = LoopPlanVersion(
        version_id="prepared-" + digest,
        plan_hash=plan_sha256(snapshot),
        snapshot=snapshot,
        source_hashes=(record.source.binding_hash,),
        evidence_hash=digest,
        authored_at=record.source.authored_at,
        available_at=record.source.available_at,
        information_cutoff=record.source.available_at,
        review=LoopPlanReview(
            content_hash=reviewed.content_hash,
            reviewed_at=reviewed_at,
            confirmed=command.confirmed,
            evidence=command.evidence,
            source_hashes=(record.source.binding_hash,),
            evidence_hash=digest,
        ),
    )
    return FrozenPreparedPlan(
        preparation_id=record.preparation_id,
        source_revision=record.source_revision,
        extraction_candidate_revision=record.candidate_revision,
        extraction_candidate_hash=command.candidate_hash,
        extraction_evidence_hash=command.evidence_hash,
        source=record.source,
        opening_evidence=original.opening_account,
        mapping=reviewed.mapping,
        account=account,
        account_origin=origin,
        version=version,
    )


def frozen_preparation(record: PreparationRecord) -> FrozenPreparedPlan:
    """Read durable authority; validation, legacy declarations and candidates cannot grant it."""
    if record.status != "REVIEWED" or record.review is None or record.candidate is None:
        raise PreparationSemanticError("REVIEW_REQUIRED")
    record = PreparationRecord.model_validate_json(record.model_dump_json())
    if record.work_claim is not None:
        raise PreparationSemanticError("WORKER_CLAIM_PENDING")
    try:
        manifest = FrozenPreparedPlan.model_validate_json(record.candidate.payload_json)
        if (
            manifest.preparation_id != record.preparation_id
            or manifest.source != record.source
            or manifest.source_revision != record.source_revision
            or manifest.extraction_candidate_revision + 1 != record.candidate_revision
            or manifest.version.evidence_hash != record.candidate.evidence_hash
            or manifest.version.review.reviewed_at != record.review.reviewed_at
        ):
            raise ValueError("frozen preparation declaration differs from its manifest")
        return manifest
    except ValueError:
        raise PreparationSemanticError("FROZEN_BINDING_CONFLICT") from None
