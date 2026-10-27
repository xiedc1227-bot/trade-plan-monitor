"""Supported current workflow sources; historical natural-language unit fixtures stay unchanged."""

import json
from hashlib import sha256
from uuid import UUID, uuid4

from tests.integration.test_plan_preparation_worker import (
    collection_claim,
    collection_update_result,
)
from tests.unit.test_daily_review import reviewed_mapping as legacy_mapping
from tests.unit.test_monitor_loop_schedule import at
from tests.unit.test_plan_update_bindings import current_update
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.ai.daily_review import (
    DailyClause,
    DailyFieldBinding,
    DailyMapping,
    DailySupplement,
    semantic_values,
)
from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    LoopPlanExtractionResult,
)
from trade_plan_monitor.ai.models import PlanExtractionStatus
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.ai.source_derivation import DerivationStage, SourceDerivationEvidence
from trade_plan_monitor.ai.source_derivation_replay import expand_update_with_evidence
from trade_plan_monitor.ai.source_normalization import capture_normalization
from trade_plan_monitor.ai.source_obligations import declarations
from trade_plan_monitor.ai.update_review import context_from_review, materialize_extraction
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_models import (
    PlanCollectionPreparationInput,
    PreparationSource,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    collection_item_binding,
)
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_content_sha256
from trade_plan_monitor.domain.plan_validation import ValidationIssue
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.source_coverage_authority import extraction_inputs
from trade_plan_monitor.state.source_coverage_values import CoverageInputs

SINGLE_MISSING_PATH = "ordinary_rules[0].independent_signal.evidence_requirement"
ACCOUNT_FACTS = (
    "实际持仓100股。", "CORE持仓100股。", "TACTICAL持仓0股。", "每股成本40.105元/股。",
)


def single_draft():
    return UnifiedPlanDraft.from_executable(research_plan().model_copy(update={
        "symbol": "002240.SZ", "market": "SZSE"}))


def field_source(draft, *, missing=(), tail=()):
    values = semantic_values(draft)
    lines = [f"{path} = {json.dumps(None if path in missing else value, ensure_ascii=False)}"
             for path, value in values.items()]
    return "\n".join((*lines, *tail))


def reviewed_mapping(draft, source="Synthetic human-reviewed supplements for this fixture."):
    if not source.startswith("schema_version = "):
        return legacy_mapping(draft, source)
    parsed = declarations(source)
    clauses = server_source_clauses(source)
    values = semantic_values(draft)
    digest = daily_draft_content_sha256(draft)
    by_path = {path: tuple(clause for declaration in parsed if declaration.path == path
        for clause in clauses if declaration.start <= clause.start < clause.end <= declaration.end)
        for path in values}
    supplements, bindings = [], []
    for path, value in values.items():
        declaration = next(row for row in parsed if row.path == path)
        if declaration.value is None and value is not None:
            identifier = "explicit-missing-" + str(len(supplements))
            supplements.append(DailySupplement(supplement_id=identifier,
                candidate_content_hash=digest, path=path, value=value,
                reason="The source explicitly leaves this parameter missing; human supplies it."))
            bindings.append(DailyFieldBinding(path=path, value=value, origin="HUMAN_SUPPLEMENT",
                unit="JSON", clause_ids=(), supplement_id=identifier))
        else:
            if type(declaration.value) is not type(value) or declaration.value != value:
                raise ValueError("Workflow fixture cannot override an explicit source value")
            bindings.append(DailyFieldBinding(path=path, value=value,
                origin="SOURCE_SEMANTIC" if value is None or type(value) is bool else "SOURCE",
                unit="JSON", clause_ids=tuple(row.clause_id for row in by_path[path]),
                supplement_id=None))
    mapped_clauses = []
    for clause in clauses:
        paths = tuple(path for path, group in by_path.items() if clause in group)
        mapped_clauses.append(DailyClause.model_validate(clause.model_dump() | dict(
            disposition="POLICY" if paths else "CONTEXT", paths=paths,
            reason="Exact supported field declaration or original opening-account fact.",
            semantic_role=None if paths else "ACCOUNT")))
    return DailyMapping(mapping_version="daily-mapping-v1", candidate_content_hash=digest,
        clauses=tuple(mapped_clauses), bindings=tuple(bindings), supplements=tuple(supplements))


def loop_candidate(source, output, identity):
    """Exact synthetic provider bytes and identity normalization, with no network call."""
    reviewed = output.review(source.text)
    result = LoopPlanExtractionResult(request_id=identity, provider_id=UUID(int=2),
        model="synthetic-workflow-no-provider-call", prompt_version="monitor-loop-extract-v1",
        source_text_sha256=source.source_hash, source_id=source.source_id,
        source_binding_hash=source.binding_hash, authored_at=source.authored_at,
        available_at=source.available_at, effective_trade_date=source.effective_trade_date,
        draft=output.draft, daily_mapping=reviewed.mapping, opening_account=output.opening_account,
        assumptions=(), warnings=(), usage=None, status=PlanExtractionStatus.SUCCEEDED,
        validation_issues=tuple(ValidationIssue(code=row.code, path=row.path, severity="ERROR",
            message=row.reason, activationBlocking=True) for row in reviewed.issues),
        evidence_hash=sha256(canonical_json(dict(domain="monitor-loop-extraction-evidence-v1",
            source_binding_hash=source.binding_hash, plan_mapping=reviewed.mapping,
            opening_account=output.opening_account)).encode()).hexdigest())
    image = output.draft.model_dump(mode="json")
    trace = capture_normalization(image, image, source.text)
    raw = "\n" + json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n\t"
    derivation = SourceDerivationEvidence.build(kind="FULL_DRAFT", source_hash=source.source_hash,
        raw_json=raw, context_json=None, base_hash=None, stages=(DerivationStage.build(
            phase="SOURCE_NORMALIZED", output_json=canonical(output.model_dump(mode="json"))),))
    inputs = CoverageInputs.build(source_hash=source.source_hash,
        source_binding_hash=source.binding_hash, normalization=trace, derivation=derivation)
    return result, inputs


def current_collection(tmp_path, *, now, later_text=None, first_available=None,
                       without_source_times=False):
    from trade_plan_monitor.ai.loop_plan_extraction import OpeningAccountFacts, OpeningFact

    final = UnifiedPlanDraft.from_executable(research_plan())
    text = field_source(final, missing=("position.max_qty",), tail=("账户记录：当前持仓0股。",))
    first = PreparationSource(source_id="first", text=text,
        authored_at=None if without_source_times else first_available or at(19),
        available_at=None if without_source_times else first_available or at(19),
        effective_trade_date=at(19).date())
    source, output = current_update(later_text or "position.max_qty = 300\n其余规则保留。")
    if without_source_times:
        source = source.model_copy(update={"authored_at": None, "available_at": None})
    store = PreparationStore(tmp_path / "collection-review.sqlite", clock=lambda: now)
    record = store.create(PlanCollectionPreparationInput(preparation_id="collection-review",
        sources=(first, source)), idempotency_key="create")
    claim = collection_claim(record, 0, generation=str(uuid4())).model_copy(
        update={"claimed_at": now})
    record = store.start_attempt(record.preparation_id, expected_revision=record.revision,
        idempotency_key="start-0", work_claim=claim)
    record = store.begin_call(record.preparation_id, generation=claim.generation,
        owner_id=claim.owner_id, expected_revision=record.revision)
    incomplete = final.model_copy(update={"position": final.position.model_copy(
        update={"max_qty": None})})
    start = text.index("账户记录：当前持仓0股。")
    opening = OpeningAccountFacts(inventory_quantity=OpeningFact(value=0, start=start,
        end=len(text), excerpt=text[start:]), lots=(), cash_fen=None, snapshot_at=None)
    initial_output = LoopPlanExtractionOutput(schema_version="monitor-loop-extraction-v1",
        draft=incomplete, clauses=tuple(DailyClause.model_validate(clause.model_dump() | dict(
            disposition="UNRESOLVED", paths=(),
            reason="Original extraction awaits exact source-bound correction."))
            for clause in server_source_clauses(text)), bindings=(), opening_account=opening)
    result, inputs = loop_candidate(first, initial_output, UUID(claim.generation))
    record = store.finish_attempt(record.preparation_id, attempt_id=claim.generation,
        expected_revision=record.revision, idempotency_key="finish-0",
        worker_owner_id=claim.owner_id,
        candidate=result.to_preparation_candidate(), inputs=inputs)
    record = store.clear_work_claim(record.preparation_id, generation=claim.generation,
                                   expected_revision=record.revision)
    command = CollectionItemCorrectionCommand(expected_revision=record.revision,
        binding=collection_item_binding(record.items[0]), confirmed=True, draft=final,
        mapping=reviewed_mapping(final, text),
        evidence="The first workflow source explicitly leaves the cap missing; supply 1000 shares.")
    record = store.correct_collection_item(record.preparation_id, command=command,
                                           idempotency_key="initial-null-cap-1000")
    base = preparation_candidate_review(record, 0)
    context = context_from_review(base, record.items[0].candidate.candidate_hash)
    # Direct legacy-shaped update JSON deliberately preserves old workflow tests'
    # raw extraction/output access, while recording real private derivation evidence.
    raw = json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2)
    output, derivation = expand_update_with_evidence(raw, source, context)
    claim = collection_claim(record, 1, generation=str(uuid4())).model_copy(
        update={"claimed_at": now})
    record = store.start_attempt(record.preparation_id, expected_revision=record.revision,
        idempotency_key="start-1", work_claim=claim)
    record = store.begin_call(record.preparation_id, generation=claim.generation,
        owner_id=claim.owner_id, expected_revision=record.revision)
    result = collection_update_result(base, source, output, UUID(claim.generation), context)
    result = result.model_copy(update={"source_derivation": derivation})
    result = materialize_extraction(base, context.base_hash, source, result)
    record = store.finish_attempt(record.preparation_id, attempt_id=claim.generation,
        expected_revision=record.revision, idempotency_key="finish-1",
        worker_owner_id=claim.owner_id,
        candidate=result.to_preparation_candidate(), inputs=extraction_inputs(result.extraction))
    record = store.clear_work_claim(record.preparation_id, generation=claim.generation,
                                   expected_revision=record.revision)
    return store, record
