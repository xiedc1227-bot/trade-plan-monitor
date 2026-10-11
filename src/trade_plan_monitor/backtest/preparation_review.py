"""Explicit human preparation review, exact provenance and one frozen research plan."""

from datetime import datetime, time
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from trade_plan_monitor.ai.daily_review import DailyMapping, build_daily_review
from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    LoopPlanExtractionResult,
    OpeningAccountFacts,
    unsupported_loop_source_spans,
    validate_opening_evidence,
)
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.plan_update_extraction import (
    PlanUpdateExtractionOutput,
    PlanUpdateExtractionResult,
)
from trade_plan_monitor.ai.update_review import (
    MaterializedUpdateCandidate,
    PlanCandidateReview,
    build_initial_review,
    build_update_review,
    context_from_review,
    materialize_extraction,
)
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import (
    KnownLoopCash,
    LoopAccountInput,
    LoopInitialLot,
    UnknownLoopCash,
)
from trade_plan_monitor.backtest.models import Sha256Hex, StableIdentifier
from trade_plan_monitor.backtest.plan_schedule import (
    MAX_SCHEDULED_ENTRIES,
    LoopAccountContext,
    LoopPlanReview,
    LoopPlanVersion,
    LoopSchedule,
    LoopScheduleEntry,
    LoopTimestamp,
    ScheduledLoopSchedule,
    ScheduledPlanVersion,
    ScheduledScheduleEntry,
)
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationRecord,
    PreparationCandidateInput,
    PreparationItemReview,
    PreparationRecord,
    PreparationSource,
)
from trade_plan_monitor.backtest.research_input import ResearchValue, _confirmed
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.domain.daily_plan_models import Text
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft


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
            or unsupported_loop_source_spans(self.source.text)
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
        if self.account.opening_mark is not None and self.account.opening_mark.available_at > start:
            raise ValueError("frozen opening mark was unavailable at the historical start")
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
        if unsupported_loop_source_spans(record.source.text):
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
    if isinstance(record, CollectionPreparationRecord):
        return frozen_collection(record)
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


class CollectionItemCorrectionCommand(ResearchValue):
    expected_revision: int = Field(ge=1)
    binding: PreparationItemReview
    confirmed: Annotated[Literal[True], BeforeValidator(_confirmed)]
    evidence: Text
    draft: UnifiedPlanDraft | None = None
    mapping: DailyMapping | None = None
    update: PlanUpdateExtractionOutput | None = None


class CollectionPreparationReviewCommand(ResearchValue):
    expected_revision: int = Field(ge=1)
    items: tuple[PreparationItemReview, ...] = Field(min_length=1, max_length=MAX_SCHEDULED_ENTRIES)
    confirmed: Annotated[Literal[True], BeforeValidator(_confirmed)]
    evidence: Text
    account: LoopAccountInput | None = None


def collection_item_binding(item):
    if item.candidate is None:
        raise PreparationSemanticError("REVIEW_REQUIRED")
    return PreparationItemReview(
        source_id=item.source.source_id, source_revision=item.source_revision,
        candidate_revision=item.candidate_revision, candidate_hash=item.candidate.candidate_hash,
        evidence_hash=item.candidate.evidence_hash, base_hash=item.base_hash,
    )


def _update_original(record, index, base):
    item = record.items[index]
    payload = item.candidate.payload_json
    try:
        import json
        schema = json.loads(payload).get("schema_version")
        if schema == "monitor-loop-materialized-update-v1":
            materialized = MaterializedUpdateCandidate.model_validate_json(payload)
            original = materialized.extraction
            if (materialize_extraction(base, item.base_hash, item.source, original) != materialized
                or item.candidate.evidence_hash != materialized.review.evidence_hash):
                raise ValueError("materialized candidate evidence changed")
        else:
            original = PlanUpdateExtractionResult.model_validate_json(payload)
            if item.candidate.evidence_hash != original.evidence_hash:
                raise ValueError("original candidate evidence changed")
        context = context_from_review(base, item.base_hash)
        digest = sha256(canonical_json({
            "domain": "monitor-loop-update-evidence-v1",
            "source_binding_hash": item.source.binding_hash,
            "context": context, "output": original.output,
        }).encode()).hexdigest()
        if (original.evidence_hash != digest
            or original.base_hash != item.base_hash
            or original.source_id != item.source.source_id
            or original.source_binding_hash != item.source.binding_hash
            or original.source_text_sha256 != item.source.source_hash
            or original.available_at != item.source.available_at
            or original.authored_at != item.source.authored_at
            or original.effective_trade_date != item.source.effective_trade_date
            or str(original.request_id) != item.attempts[-1].attempt_id):
            raise ValueError("update extraction binding changed")
        return original
    except ValueError:
        raise PreparationSemanticError("EXTRACTION_BINDING_CONFLICT") from None


def correct_collection_candidate(record, command):
    """Explicit corrections grant validated context, never whole-chain replay authority."""
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    record = CollectionPreparationRecord.model_validate_json(record.model_dump_json())
    if record.work_claim is not None:
        raise PreparationSemanticError("WORKER_CLAIM_PENDING")
    if record.status in {"CANCELLED", "CANCEL_REQUESTED"}:
        raise PreparationSemanticError("REVIEW_REQUIRED")
    index = next((i for i, item in enumerate(record.items)
                  if item.source.source_id == command.binding.source_id), None)
    if (index is None or command.expected_revision != record.revision
        or collection_item_binding(record.items[index]) != command.binding):
        raise PreparationSemanticError("REVIEW_BINDING_CONFLICT")
    item = record.items[index]
    if not index:
        if command.update is not None:
            raise PreparationSemanticError("REVIEW_SEMANTIC_CONFLICT")
        try:
            previous = PlanCandidateReview.model_validate_json(item.candidate.payload_json)
        except ValueError:
            original = _original_extraction(item)
            draft = command.draft or original.draft
            mapping = command.mapping or original.daily_mapping
            original_asset = original.draft.symbol, original.draft.market
        else:
            previous = preparation_candidate_review(record, index)
            draft = command.draft or previous.draft
            if command.mapping is None:
                raise PreparationSemanticError("REVIEW_MAPPING_REQUIRED")
            mapping = command.mapping
            original_asset = previous.draft.symbol, previous.draft.market
        if (draft.symbol, draft.market) != original_asset:
            raise PreparationSemanticError("SOURCE_ASSET_CONFLICT")
        reviewed = build_initial_review(draft, mapping, item.source)
    else:
        base = preparation_candidate_review(record, index - 1)
        if command.draft is not None:
            raise PreparationSemanticError("REVIEW_UPDATE_REQUIRED")
        try:
            previous = PlanCandidateReview.model_validate_json(item.candidate.payload_json)
        except ValueError:
            original = _update_original(record, index, base)
            output = command.update or original.output
        else:
            previous = preparation_candidate_review(record, index)
            if command.update is None:
                raise PreparationSemanticError("REVIEW_UPDATE_REQUIRED")
            output = command.update
        reviewed = build_update_review(base, item.source, output, mapping=command.mapping)
    if reviewed.issues:
        raise PreparationSemanticError("REVIEW_UNRESOLVED")
    return index, reviewed


class FrozenCollectionItem(ResearchValue):
    source: PreparationSource
    source_revision: int = Field(ge=1)
    extraction_candidate_revision: int = Field(ge=1)
    extraction_candidate_hash: Sha256Hex
    extraction_evidence_hash: Sha256Hex
    base_hash: Sha256Hex | None
    mapping: PlanCandidateReview
    version: ScheduledPlanVersion

    @model_validator(mode="after")
    def bound(self):
        if self.mapping.issues or (
            self.mapping.source_id, self.mapping.source_hash, self.mapping.available_at
        ) != (self.source.source_id, self.source.binding_hash, self.source.available_at):
            raise ValueError("frozen item mapping is unresolved or bound to another source")
        expected = _collection_version(self.source, self.mapping, self.version.review.reviewed_at,
                                       self.version.review.evidence)
        if expected != self.version:
            raise ValueError("frozen version differs from reviewed evidence")
        return self


def _collection_version(source, mapping, reviewed_at, evidence):
    snapshot = mapping.draft.to_executable()
    if snapshot is None or any(value is None for value in (
        source.authored_at, source.available_at, source.effective_trade_date,
    )):
        raise PreparationSemanticError("SOURCE_TIME_REQUIRED")
    hashes = tuple(dict.fromkeys((source.binding_hash, *(b.source_hash for b in mapping.bindings))))
    context = mapping.account_context
    account_context = None if context is None else LoopAccountContext(
        core_qty=context.core_qty.value if context.core_qty else None,
        tactical_qty=context.tactical_qty.value if context.tactical_qty else None,
        dependent_rule_ids=context.dependent_rule_ids, evidence=canonical_json(context),
    )
    return ScheduledPlanVersion(
        version_id="prepared-" + mapping.evidence_hash, plan_hash=plan_sha256(snapshot),
        snapshot=snapshot, source_hashes=hashes, evidence_hash=mapping.evidence_hash,
        authored_at=source.authored_at, available_at=source.available_at,
        information_cutoff=source.available_at, account_context=account_context,
        review=LoopPlanReview(
            content_hash=daily_plan_content_sha256(snapshot), reviewed_at=reviewed_at,
            confirmed=True, evidence=evidence, source_hashes=hashes,
            evidence_hash=mapping.evidence_hash,
        ),
    )


class FrozenPreparedCollection(ResearchValue):
    schema_version: Literal["prepared-loop-plan-v2"] = "prepared-loop-plan-v2"
    preparation_id: StableIdentifier
    revision: int = Field(ge=1)
    items: tuple[FrozenCollectionItem, ...] = Field(min_length=1, max_length=MAX_SCHEDULED_ENTRIES)
    schedule: ScheduledLoopSchedule
    account: LoopAccountInput
    account_origin: Literal["SOURCE", "HUMAN_REVIEW"]
    opening_evidence: OpeningAccountFacts | None
    reviewed_at: LoopTimestamp
    review_hash: Sha256Hex

    @property
    def manifest_hash(self):
        return sha256(("prepared-loop-plan-v2\0" + canonical_json(self)).encode()).hexdigest()

    @model_validator(mode="after")
    def bound(self):
        if self.review_hash != _collection_review_hash(
            self.model_dump(mode="python", exclude={"review_hash"}),
        ):
            raise ValueError("frozen chain differs from explicit account/source review")
        sources, previous = {}, None
        for item in self.items:
            source = item.source
            if source.source_id in sources:
                raise ValueError("duplicate frozen source")
            if previous is not None and (item.base_hash != previous.extraction_candidate_hash
                or source.available_at < previous.source.available_at
                or source.authored_at < previous.source.authored_at
                or source.effective_trade_date <= previous.source.effective_trade_date):
                raise ValueError("frozen chain source/base chronology changed")
            if previous is None and item.base_hash is not None:
                raise ValueError("initial item cannot have a predecessor")
            sources[source.source_id] = source
            for bound in item.mapping.bindings:
                original = sources.get(bound.source_id)
                if original is None or original.binding_hash != bound.source_hash or any(
                    original.text[c.start:c.end] != c.excerpt for c in bound.clauses
                ):
                    raise ValueError("frozen inherited evidence differs from past source")
            if item.version.review.reviewed_at != self.reviewed_at:
                raise ValueError("frozen item differs from chain review time")
            previous = item
        expected = ScheduledLoopSchedule(entries=tuple(ScheduledScheduleEntry(
            effective_trade_date=item.source.effective_trade_date, version=item.version,
        ) for item in self.items))
        if expected != self.schedule:
            raise ValueError("frozen schedule differs from reviewed items")
        first = self.items[0]
        if self.opening_evidence is not None:
            validate_opening_evidence(self.opening_evidence, first.source.text)
        if self.account_origin == "SOURCE" and (self.opening_evidence is None or
            self.account != _source_account(self.opening_evidence, first.source)):
            raise ValueError("initial account differs from original first-source evidence")
        start = max(first.source.available_at, self.account.snapshot_at, datetime.combine(
            first.source.effective_trade_date, time.min, SHANGHAI,
        ))
        if (
            start.date() != first.source.effective_trade_date
            or self.schedule.select(start) is None
            or (self.account.opening_mark is not None
                and self.account.opening_mark.available_at > start)
        ):
            raise ValueError("opening account or plan is unavailable at start")
        if sum(lot.quantity for lot in self.account.lots) > first.version.snapshot.position.max_qty:
            raise ValueError("initial inventory exceeds first plan maximum")
        return self


def _collection_review_hash(value):
    return sha256(("prepared-loop-chain-review-v2\0" + canonical_json(value)).encode()).hexdigest()


def prepare_frozen_collection(record, command, reviewed_at):
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    record = CollectionPreparationRecord.model_validate_json(record.model_dump_json())
    if record.work_claim is not None:
        raise PreparationSemanticError("WORKER_CLAIM_PENDING")
    if record.status != "CANDIDATE":
        raise PreparationSemanticError("REVIEW_REQUIRED")
    if command.expected_revision != record.revision or command.items != tuple(
        collection_item_binding(item) for item in record.items
    ):
        raise PreparationSemanticError("REVIEW_BINDING_CONFLICT")
    frozen = []
    for index, item in enumerate(record.items):
        mapping = preparation_candidate_review(record, index)
        frozen.append(FrozenCollectionItem(
            source=item.source, source_revision=item.source_revision,
            extraction_candidate_revision=item.candidate_revision,
            extraction_candidate_hash=item.candidate.candidate_hash,
            extraction_evidence_hash=item.candidate.evidence_hash, base_hash=item.base_hash,
            mapping=mapping, version=_collection_version(
                item.source, mapping, reviewed_at, command.evidence,
            ),
        ))
    first = record.items[0]
    try:
        PlanCandidateReview.model_validate_json(first.candidate.payload_json)
    except ValueError:
        opening = _original_extraction(first).opening_account
    else:
        opening = None
    if command.account is None and opening is None:
        raise PreparationSemanticError("ACCOUNT_REVIEW_REQUIRED")
    account = command.account or _source_account(opening, first.source)
    values = dict(
        schema_version="prepared-loop-plan-v2",
        preparation_id=record.preparation_id, revision=record.revision + 1,
        items=tuple(frozen), schedule=ScheduledLoopSchedule(entries=tuple(ScheduledScheduleEntry(
            effective_trade_date=item.source.effective_trade_date, version=item.version,
        ) for item in frozen)), account=account,
        account_origin="HUMAN_REVIEW" if command.account is not None else "SOURCE",
        opening_evidence=opening, reviewed_at=reviewed_at,
    )
    return FrozenPreparedCollection(**values, review_hash=_collection_review_hash(values))


def frozen_collection(record):
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    record = CollectionPreparationRecord.model_validate_json(record.model_dump_json())
    if record.status != "REVIEWED" or record.review is None or not record.review.manifest_json:
        raise PreparationSemanticError("REVIEW_REQUIRED")
    if record.work_claim is not None:
        raise PreparationSemanticError("WORKER_CLAIM_PENDING")
    try:
        manifest = FrozenPreparedCollection.model_validate_json(record.review.manifest_json)
        if (manifest.preparation_id != record.preparation_id or manifest.revision != record.revision
            or manifest.reviewed_at != record.review.reviewed_at
            or len(manifest.items) != len(record.items)):
            raise ValueError("frozen collection identity changed")
        for index, (frozen, item) in enumerate(zip(manifest.items, record.items, strict=True)):
            if (frozen.source != item.source or frozen.source_revision != item.source_revision
                or frozen.extraction_candidate_revision != item.candidate_revision
                or frozen.extraction_candidate_hash != item.candidate.candidate_hash
                or frozen.extraction_evidence_hash != item.candidate.evidence_hash
                or frozen.base_hash != item.base_hash
                or frozen.mapping != preparation_candidate_review(record, index)):
                raise ValueError("frozen item differs from exact collection binding")
        return manifest
    except ValueError:
        raise PreparationSemanticError("FROZEN_BINDING_CONFLICT") from None
