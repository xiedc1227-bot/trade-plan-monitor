"""Explicit human review freezes one research snapshot, never a live activation."""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from threading import Event
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from tests.unit.test_daily_review import reviewed_mapping
from tests.unit.test_monitor_loop_extraction import CASES, extract, fact, output_for
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.backtest.loop_input import KnownLoopCash, LoopAccountInput
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

NOW = datetime(2026, 10, 8, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
AVAILABLE = datetime(2026, 8, 20, 9, tzinfo=ZoneInfo("Asia/Shanghai"))


def ready_collection(tmp_path, *, later_text=None):
    from tests.integration.test_plan_preparation_worker import (
        collection_claim,
        collection_update_result,
    )
    from tests.unit.test_monitor_loop_schedule import at
    from tests.unit.test_plan_update_bindings import current_update, prior_review

    from trade_plan_monitor.ai.update_review import context_from_review, materialize_extraction
    from trade_plan_monitor.backtest.preparation_models import PlanCollectionPreparationInput

    base = prior_review()
    source, output = current_update() if later_text is None else current_update(later_text)
    first = PreparationSource(
        source_id="first", text="Synthetic human-reviewed supplements for this fixture.",
        authored_at=at(19), available_at=at(19), effective_trade_date=at(19).date(),
    )
    store = PreparationStore(tmp_path / "collection-review.sqlite", clock=lambda: NOW)
    record = store.create(
        PlanCollectionPreparationInput(preparation_id="collection-review", sources=(first, source)),
        idempotency_key="create",
    )
    for index in range(2):
        claim = collection_claim(record, index, generation=str(uuid4()))
        record = store.start_attempt(
            record.preparation_id, expected_revision=record.revision,
            idempotency_key=f"start-{index}", work_claim=claim,
        )
        record = store.begin_call(
            record.preparation_id, generation=claim.generation, owner_id=claim.owner_id,
            expected_revision=record.revision,
        )
        candidate = base.to_preparation_candidate()
        if index:
            context = context_from_review(base, record.items[0].candidate.candidate_hash)
            result = collection_update_result(base, source, output, UUID(claim.generation), context)
            candidate = materialize_extraction(base, context.base_hash, source, result)
            candidate = candidate.to_preparation_candidate()
        record = store.finish_attempt(
            record.preparation_id, attempt_id=claim.generation, expected_revision=record.revision,
            idempotency_key=f"finish-{index}", worker_owner_id=claim.owner_id, candidate=candidate,
        )
    record = store.clear_work_claim(
        record.preparation_id, generation=claim.generation, expected_revision=record.revision,
    )
    return store, record


def item_binding(item):
    from trade_plan_monitor.backtest.preparation_models import PreparationItemReview

    return PreparationItemReview(
        source_id=item.source.source_id, source_revision=item.source_revision,
        candidate_revision=item.candidate_revision, candidate_hash=item.candidate.candidate_hash,
        evidence_hash=item.candidate.evidence_hash, base_hash=item.base_hash,
    )


def collection_review_command(record, **changes):
    from trade_plan_monitor.backtest.preparation_review import CollectionPreparationReviewCommand

    values = dict(
        expected_revision=record.revision, items=tuple(item_binding(item) for item in record.items),
        confirmed=True, evidence="Explicit synthetic review of every source and opening account.",
        account=LoopAccountInput(
            snapshot_at=record.items[0].source.available_at, inventory_known=True,
            cash=KnownLoopCash(balance_fen=1_000_000), lots=(), opening_mark=None,
            evidence="Synthetic human opening cash 1000000 fen and zero shares.",
        ),
    )
    return CollectionPreparationReviewCommand(**(values | changes))


def test_collection_explicit_review_freezes_exact_complete_chain_and_account(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_collection(tmp_path)
    command = collection_review_command(ready)
    reviewed = store.review_and_freeze(
        ready.preparation_id, command=command, idempotency_key="freeze-collection",
    )
    frozen = frozen_preparation(reviewed)
    assert frozen.schema_version == "prepared-loop-plan-v2"
    assert frozen.preparation_id == ready.preparation_id
    assert frozen.revision == reviewed.revision == ready.revision + 1
    assert frozen.account == command.account and frozen.account_origin == "HUMAN_REVIEW"
    assert [item.source for item in frozen.items] == [item.source for item in ready.items]
    assert [item.version.snapshot.position.max_qty for item in frozen.items] == [1000, 300]
    assert all(item.version.review.confirmed is True for item in frozen.items)
    assert len(frozen.schedule.entries) == 2
    assert frozen.reviewed_at == NOW
    assert type(frozen).model_validate_json(reviewed.review.manifest_json) == frozen
    assert PreparationStore(store.database_path).get(ready.preparation_id) == reviewed
    assert store.review_and_freeze(
        ready.preparation_id, command=command, idempotency_key="freeze-collection",
    ) == reviewed


@pytest.mark.parametrize("confirmed", [False, 1, "true", None])
def test_collection_confirmation_is_literal_for_freeze_and_item_correction(tmp_path, confirmed):
    from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand

    _, ready = ready_collection(tmp_path)
    with pytest.raises(ValueError):
        collection_review_command(ready, confirmed=confirmed)
    with pytest.raises(ValueError):
        CollectionItemCorrectionCommand(
            expected_revision=ready.revision, binding=item_binding(ready.items[0]),
            confirmed=confirmed, evidence="Synthetic explicit correction.",
        )


def test_collection_validation_alone_or_missing_opening_account_cannot_freeze(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_collection(tmp_path)
    with pytest.raises(ValueError):
        frozen_preparation(ready)
    with pytest.raises(PreparationConflictError):
        store.review_and_freeze(
            ready.preparation_id, command=collection_review_command(ready, account=None),
            idempotency_key="missing-account",
        )
    assert store.get(ready.preparation_id) == ready


@pytest.mark.parametrize("field", ["source_revision", "candidate_revision", "candidate_hash",
                                  "evidence_hash", "base_hash"])
def test_collection_freeze_rejects_stale_item_binding_without_consuming_key(tmp_path, field):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_collection(tmp_path)
    bindings = tuple(item_binding(item) for item in ready.items)
    stale = bindings[1].model_copy(update={field: 99 if field.endswith("revision") else "f" * 64})
    with pytest.raises(PreparationConflictError):
        store.review_and_freeze(
            ready.preparation_id,
            command=collection_review_command(ready, items=(bindings[0], stale)),
            idempotency_key="freeze-exact",
        )
    assert store.get(ready.preparation_id) == ready
    assert store.review_and_freeze(
        ready.preparation_id, command=collection_review_command(ready),
        idempotency_key="freeze-exact",
    ).status == "REVIEWED"


@pytest.mark.parametrize("index", [0, 1], ids=["invalidate-successor", "keep-prefix"])
def test_collection_item_correction_preserves_prefix_and_invalidates_descendants(tmp_path, index):
    from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
    from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    store, ready = ready_collection(tmp_path)
    selected = ready.items[index]
    kwargs = {}
    if index == 0:
        raw = research_plan().model_dump(mode="json")
        raw["position"]["max_qty"] = 900
        draft = UnifiedPlanDraft.model_validate_json(json.dumps(raw))
        kwargs = {"draft": draft, "mapping": reviewed_mapping(draft, source=selected.source.text)}
    else:
        kwargs["update"] = PlanUpdateExtractionOutput.model_validate_json(json.dumps(
            json.loads(selected.candidate.payload_json)["extraction"]["output"]
        ))
    command = CollectionItemCorrectionCommand(
        expected_revision=ready.revision, binding=item_binding(selected), confirmed=True,
        evidence="Explicit synthetic item correction with all descendants reconsidered.", **kwargs,
    )
    corrected = store.correct_collection_item(
        ready.preparation_id, command=command, idempotency_key="correct-item",
    )
    assert corrected.items[:index] == ready.items[:index]
    item = corrected.items[index]
    assert item.source == selected.source and item.source_revision == selected.source_revision
    assert item.base_hash == selected.base_hash
    assert item.candidate_revision > selected.candidate_revision
    assert item.candidate.validation == "VALID"
    assert json.loads(item.candidate.payload_json)["schema_version"] == (
        "monitor-loop-candidate-evidence-v1"
    )
    assert corrected.review is None
    assert preparation_candidate_review(corrected, index).draft.position.max_qty == (
        900 if index == 0 else 300
    )
    for old, descendant in zip(ready.items[index + 1:], corrected.items[index + 1:], strict=True):
        assert descendant.source == old.source and descendant.source_revision == old.source_revision
        assert descendant.candidate is None and descendant.base_hash is None
        assert descendant.attempts == () and descendant.candidate_revision > old.candidate_revision
    assert store.correct_collection_item(
        ready.preparation_id, command=command, idempotency_key="correct-item",
    ) == corrected
    restored = PreparationStore(store.database_path).get(ready.preparation_id)
    assert restored == corrected
    assert preparation_candidate_review(restored, index).evidence_hash == (
        item.candidate.evidence_hash
    )


@pytest.mark.parametrize("field", ["account", "source", "candidate_hash", "version"])
def test_collection_frozen_manifest_rejects_bound_content_tampering(tmp_path, field):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_collection(tmp_path)
    frozen = frozen_preparation(store.review_and_freeze(
        ready.preparation_id, command=collection_review_command(ready), idempotency_key="freeze",
    ))
    raw = frozen.model_dump(mode="json")
    if field == "account":
        raw["account"]["cash"]["balance_fen"] += 1
    elif field == "source":
        raw["items"][1]["source"]["text"] += " Tampered."
    elif field == "version":
        raw["items"][1]["version"]["snapshot"]["position"]["max_qty"] = 900
    else:
        raw["items"][1]["extraction_candidate_hash"] = "f" * 64
    with pytest.raises(ValueError):
        type(frozen).model_validate_json(json.dumps(raw))


def test_collection_edit_invalidates_freeze_but_keeps_original_review_receipt(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_collection(tmp_path)
    command = collection_review_command(ready)
    reviewed = store.review_and_freeze(
        ready.preparation_id, command=command, idempotency_key="freeze",
    )
    frozen = frozen_preparation(reviewed)
    edited = store.edit_collection(
        ready.preparation_id, expected_revision=reviewed.revision, idempotency_key="edit-future",
        source=ready.items[1].source.model_copy(update={"text": "Synthetic revised later plan."}),
    )
    assert edited.items[0] == reviewed.items[0]
    assert edited.review is None and edited.items[1].candidate is None
    with pytest.raises(ValueError):
        frozen_preparation(edited)
    replayed = store.review_and_freeze(
        ready.preparation_id, command=command, idempotency_key="freeze",
    )
    assert replayed == reviewed
    assert frozen_preparation(replayed).manifest_hash == frozen.manifest_hash
    assert store.get(ready.preparation_id) == edited


def test_collection_review_time_does_not_change_earlier_causal_authority(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    store, ready = ready_collection(tmp_path / "first")
    reviewed = store.review_and_freeze(
        ready.preparation_id, command=collection_review_command(ready),
        idempotency_key="review-first",
    )
    first = frozen_preparation(reviewed)
    later_store, later_ready = ready_collection(
        tmp_path / "second", later_text="调整最大仓位为300股，其余规则保留。",
    )
    later_store._clock = lambda: NOW + timedelta(hours=1)
    rereviewed = later_store.review_and_freeze(
        later_ready.preparation_id, command=collection_review_command(later_ready),
        idempotency_key="review-later",
    )
    second = frozen_preparation(rereviewed)
    at = ready.items[0].source.available_at
    assert first.reviewed_at != second.reviewed_at
    assert first.schedule.select(at).authority_id == second.schedule.select(at).authority_id
    assert first.items[0].version.version_id == second.items[0].version.version_id
    assert first.items[1].source.binding_hash != second.items[1].source.binding_hash


@pytest.mark.parametrize("field", [
    "source_revision", "candidate_hash", "evidence_hash", "base_hash",
])
def test_collection_correction_rejects_stale_exact_binding(tmp_path, field):
    from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
    from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_collection(tmp_path)
    item = ready.items[1]
    update = PlanUpdateExtractionOutput.model_validate_json(json.dumps(
        json.loads(item.candidate.payload_json)["extraction"]["output"]
    ))
    command = CollectionItemCorrectionCommand(
        expected_revision=ready.revision, binding=item_binding(item), confirmed=True,
        evidence="Explicit synthetic corrected item.", update=update,
    )
    stale = command.model_copy(update={"binding": command.binding.model_copy(update={
        field: 99 if field.endswith("revision") else "f" * 64,
    })})
    with pytest.raises(PreparationConflictError):
        store.correct_collection_item(
            ready.preparation_id, command=stale, idempotency_key="correct",
        )
    assert store.get(ready.preparation_id) == ready
    assert store.correct_collection_item(
        ready.preparation_id, command=command, idempotency_key="correct",
    ).items[1].candidate.validation == "VALID"


@pytest.mark.parametrize("index", [0, 1], ids=["first", "successor"])
@pytest.mark.parametrize("field", ["source_id", "source_hash", "available_at"])
def test_collection_correction_rejects_wrong_source_inside_trusted_review(tmp_path, index, field):
    from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput
    from trade_plan_monitor.backtest.preparation_models import CollectionPreparationCandidate
    from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    store, ready = ready_collection(tmp_path)
    item = ready.items[index]
    review = preparation_candidate_review(ready, index)
    changes = {
        "source_id": "forged-other-source", "source_hash": "f" * 64,
        "available_at": review.available_at + timedelta(minutes=1),
    }
    wrong = review.model_copy(update={field: changes[field]})
    candidate = CollectionPreparationCandidate(
        **wrong.to_preparation_candidate().model_dump(), source_revision=item.source_revision,
        source_hash=item.source.binding_hash, base_hash=item.base_hash,
    )
    items = list(ready.items)
    items[index] = item.model_copy(update={"candidate": candidate})
    if index == 0:
        # Keep the outer record's chain internally consistent so rejection must inspect
        # the selected review's exact original source, rather than only its checksum.
        later = items[1]
        items[1] = later.model_copy(update={
            "base_hash": candidate.candidate_hash,
            "candidate": later.candidate.model_copy(update={"base_hash": candidate.candidate_hash}),
            "attempts": tuple(attempt.model_copy(update={"base_hash": candidate.candidate_hash})
                              for attempt in later.attempts),
        })
    forged = store._operation(
        "SYNTHETIC_BAD_REVIEW", ready.preparation_id, {}, "seed-bad-review",
        lambda record, now: record.model_copy(update={
            "items": tuple(items), "revision": record.revision + 1, "updated_at": now,
        }),
    )
    kwargs = {"draft": review.draft, "mapping": reviewed_mapping(
        review.draft, source=item.source.text,
    )} if index == 0 else {"update": PlanUpdateExtractionOutput.model_validate_json(json.dumps(
        json.loads(item.candidate.payload_json)["extraction"]["output"],
    ))}
    command = CollectionItemCorrectionCommand(
        expected_revision=forged.revision, binding=item_binding(forged.items[index]),
        confirmed=True, evidence="Explicit correction cannot repair original-source forgery.",
        **kwargs,
    )
    with pytest.raises(PreparationConflictError):
        store.correct_collection_item(
            forged.preparation_id, command=command, idempotency_key="must-reject",
        )
    assert store.get(forged.preparation_id) == forged


def test_collection_first_raw_extraction_requires_explicit_correction_before_continuing(tmp_path):
    from tests.integration.test_plan_preparation_worker import collection_claim

    from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult
    from trade_plan_monitor.backtest.preparation_models import PlanCollectionPreparationInput
    from trade_plan_monitor.backtest.preparation_review import CollectionItemCorrectionCommand
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    _, original = ready_preparation(tmp_path)
    proposal = review_command(original)
    next_source = original.source.model_copy(update={
        "source_id": "next", "text": "Synthetic future source requires separate extraction.",
        "authored_at": AVAILABLE + timedelta(days=1),
        "available_at": AVAILABLE + timedelta(days=1),
        "effective_trade_date": (AVAILABLE + timedelta(days=1)).date(),
    })
    store = PreparationStore(tmp_path / "first-correction.sqlite", clock=lambda: NOW)
    record = store.create(
        PlanCollectionPreparationInput(
            preparation_id="raw-first", sources=(original.source, next_source),
        ), idempotency_key="create",
    )
    claim = collection_claim(record, 0, generation=str(uuid4()))
    record = store.start_attempt(
        record.preparation_id, expected_revision=record.revision,
        idempotency_key="start", work_claim=claim,
    )
    record = store.begin_call(
        record.preparation_id, generation=claim.generation, owner_id=claim.owner_id,
        expected_revision=record.revision,
    )
    raw = LoopPlanExtractionResult.model_validate_json(original.candidate.payload_json)
    raw = raw.model_copy(update={"request_id": UUID(claim.generation)})
    ready = store.finish_attempt(
        record.preparation_id, attempt_id=claim.generation, expected_revision=record.revision,
        idempotency_key="finish", worker_owner_id=claim.owner_id,
        candidate=raw.to_preparation_candidate(),
    )
    ready = store.clear_work_claim(
        record.preparation_id, generation=claim.generation, expected_revision=ready.revision,
    )
    with pytest.raises(ValueError):
        preparation_candidate_review(ready, 0)
    command = CollectionItemCorrectionCommand(
        expected_revision=ready.revision, binding=item_binding(ready.items[0]), confirmed=True,
        evidence="Explicit synthetic source correction; no automatic activation.",
        draft=proposal.draft, mapping=proposal.mapping,
    )
    corrected = store.correct_collection_item(
        ready.preparation_id, command=command, idempotency_key="correct-first",
    )
    review = preparation_candidate_review(corrected, 0)
    assert review.draft == proposal.draft and review.issues == ()
    assert corrected.items[0].attempts == ready.items[0].attempts
    assert corrected.items[1].status == "DRAFT"
    assert corrected.items[1].candidate is None and not corrected.items[1].attempts
    assert corrected.review is None


def ready_preparation(tmp_path, *, source_text=None, opening_snapshot=False, metadata=None):
    text = source_text or CASES[0]["source"].split("参考行情", 1)[0]
    if opening_snapshot:
        text += "账户快照2026-08-20T09:00:00+08:00。"
    case = {**CASES[0], "source": text}
    source = PreparationSource(
        source_id="source-1",
        text=case["source"],
        **(
            dict(
                authored_at=AVAILABLE, available_at=AVAILABLE, effective_trade_date=AVAILABLE.date()
            )
            | (metadata or {})
        ),
    )
    output = output_for(case)
    if opening_snapshot:
        output["opening_account"]["snapshot_at"] = fact(
            text, "账户快照2026-08-20T09:00:00+08:00", AVAILABLE.isoformat()
        )
    result = extract(
        output,
        source.text,
        authored_at=source.authored_at,
        available_at=source.available_at,
        effective_trade_date=source.effective_trade_date,
    )
    store = PreparationStore(tmp_path / "preparation.sqlite3", clock=lambda: NOW)
    record = store.create(
        SinglePlanPreparationInput(preparation_id="one", sources=(source,)),
        idempotency_key="create",
    )
    running = store.start_attempt("one", expected_revision=record.revision, idempotency_key="start")
    result = result.model_copy(update={"request_id": UUID(running.attempts[-1].attempt_id)})
    ready = store.finish_attempt(
        "one",
        attempt_id=running.attempts[-1].attempt_id,
        expected_revision=running.revision,
        candidate=result.to_preparation_candidate(),
        idempotency_key="finish",
    )
    return store, ready


def review_command(record, **changes):
    from trade_plan_monitor.backtest.preparation_review import PreparationReviewCommand

    draft = UnifiedPlanDraft.from_executable(
        research_plan().model_copy(update={"symbol": "002240.SZ", "market": "SZSE"})
    )
    mapping = reviewed_mapping(draft, source=record.source.text)
    account = LoopAccountInput(
        snapshot_at=AVAILABLE,
        inventory_known=True,
        cash=KnownLoopCash(balance_fen=500000),
        lots=(),
        opening_mark=None,
        evidence="Synthetic human account override: no opening lots, cash 500000 fen.",
    )
    values = dict(
        expected_revision=record.revision,
        expected_source_revision=record.source_revision,
        expected_candidate_revision=record.candidate_revision,
        candidate_hash=record.candidate.candidate_hash,
        evidence_hash=record.candidate.evidence_hash,
        confirmed=True,
        evidence="Explicit synthetic human review of this source, plan and account.",
        draft=draft,
        mapping=mapping,
        account=account,
    )
    return PreparationReviewCommand(**(values | changes))


def test_explicit_review_freezes_complete_plan_account_and_original_evidence(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_preparation(tmp_path)
    assert ready.review is None
    command = review_command(ready)
    reviewed = store.review_and_freeze("one", command=command, idempotency_key="review")
    frozen = frozen_preparation(reviewed)
    assert frozen.source == ready.source
    assert frozen.extraction_candidate_hash == ready.candidate.candidate_hash
    assert frozen.extraction_evidence_hash == ready.candidate.evidence_hash
    assert frozen.opening_evidence.cost_basis_fen == 401050
    assert frozen.account == command.account
    assert frozen.version.snapshot == command.draft.to_executable()
    assert frozen.version.review.confirmed is True
    assert frozen.version.review.reviewed_at == NOW
    assert len(frozen.schedule.entries) == 1
    assert PreparationStore(store.database_path).get("one") == reviewed
    with pytest.raises(ValidationError):
        frozen.account.cash.balance_fen = 1


@pytest.mark.parametrize("confirmation", [False, 1, "true", None])
def test_review_requires_literal_human_confirmation(tmp_path, confirmation):
    store, ready = ready_preparation(tmp_path)
    with pytest.raises(ValidationError):
        review_command(ready, confirmed=confirmation)
    assert store.get("one") == ready


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_revision", 99),
        ("expected_source_revision", 99),
        ("expected_candidate_revision", 99),
        ("candidate_hash", "f" * 64),
        ("evidence_hash", "f" * 64),
    ],
)
def test_review_rejects_stale_revision_or_evidence_without_consuming_key(tmp_path, field, value):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    with pytest.raises(PreparationConflictError):
        store.review_and_freeze(
            "one", command=review_command(ready, **{field: value}), idempotency_key="review"
        )
    assert store.get("one") == ready
    assert (
        store.review_and_freeze(
            "one", command=review_command(ready), idempotency_key="review"
        ).status
        == "REVIEWED"
    )


@pytest.mark.parametrize("changes", [{"draft": None}, {"mapping": None}, {"account": None}])
def test_confirmation_cannot_acknowledge_unresolved_plan_evidence_or_account(tmp_path, changes):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    with pytest.raises(PreparationConflictError):
        store.review_and_freeze(
            "one", command=review_command(ready, **changes), idempotency_key="review"
        )
    assert store.get("one") == ready


@pytest.mark.parametrize("field", ["account", "source", "mapping", "extraction_candidate_hash"])
def test_frozen_manifest_detects_changed_bound_inputs(tmp_path, field):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_preparation(tmp_path)
    frozen = frozen_preparation(
        store.review_and_freeze("one", command=review_command(ready), idempotency_key="review")
    )
    payload = frozen.model_dump(mode="json")
    if field == "account":
        payload[field]["cash"]["balance_fen"] += 1
    elif field == "source":
        payload[field]["text"] += " 新补充。"
    elif field == "mapping":
        payload[field]["supplements"][0]["reason"] += " Changed evidence."
    else:
        payload[field] = "f" * 64
    with pytest.raises(ValidationError):
        type(frozen).model_validate(payload)


def review_service(store, jobs):
    from trade_plan_monitor.backtest.preparation_service import PreparationService
    from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor

    def forbidden_call(*args):
        pytest.fail("Review and reads must not call AI")

    return PreparationService(store, jobs, PreparationExtractor(forbidden_call))


@pytest.mark.parametrize("kind", ["RUN", "SYNC", "VERIFY"])
@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "EXPIRED"])
def test_unfinished_global_task_blocks_review_without_changing_candidate(tmp_path, kind, state):
    from tests.integration.test_backtest_jobs import _Clock
    from tests.integration.test_backtest_single_task import request

    from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError

    store, ready = ready_preparation(tmp_path)
    clock = _Clock(NOW)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=clock)
    first = jobs.submit(request(kind), "job", request_id="1" * 32)
    if state != "QUEUED":
        jobs.claim_next()
    if state == "CANCEL_REQUESTED":
        jobs.request_cancel(first.job_id, "cancel-job")
    if state == "EXPIRED":
        clock.advance(timedelta(seconds=31))

    async def scenario():
        service = review_service(store, jobs)
        try:
            with pytest.raises(JobAdmissionError) as blocked:
                await service.review_and_freeze(
                    "one", command=review_command(ready), idempotency_key="review"
                )
            assert blocked.value.code == "BACKTEST_BUSY"
            assert store.get("one") == ready
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_source_account_preserves_unknown_cash_dates_sellability_and_mark(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation

    store, ready = ready_preparation(tmp_path, opening_snapshot=True)
    reviewed = store.review_and_freeze(
        "one", command=review_command(ready, account=None), idempotency_key="review"
    )
    frozen = frozen_preparation(reviewed)
    assert frozen.account_origin == "SOURCE"
    assert frozen.account.snapshot_at == AVAILABLE
    assert frozen.account.cash.kind == "UNKNOWN"
    assert frozen.account.opening_mark is None
    (lot,) = frozen.account.lots
    assert lot.bucket == "CORE" and lot.quantity == 100 and lot.cost_basis_fen == 401050
    assert lot.acquired_trade_date is None and lot.sellable_quantity is None
    assert frozen.account.opening_equity_fen is None


@pytest.mark.parametrize("field", ["authored_at", "available_at", "effective_trade_date"])
def test_missing_source_chronology_needs_explicit_correction_before_freeze(tmp_path, field):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path, metadata={field: None})
    with pytest.raises(PreparationConflictError, match="SOURCE_TIME_REQUIRED"):
        store.review_and_freeze("one", command=review_command(ready), idempotency_key="review")
    assert store.get("one") == ready


def test_human_review_cannot_reclassify_unsupported_execution_as_background(tmp_path):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path, source_text=CASES[0]["source"])
    with pytest.raises(PreparationConflictError, match="UNSUPPORTED_SOURCE"):
        store.review_and_freeze("one", command=review_command(ready), idempotency_key="review")
    assert store.get("one") == ready


@pytest.mark.parametrize("expired", [False, True])
def test_unresolved_reservation_stays_occupied_before_review(tmp_path, expired):
    from tests.integration.test_backtest_jobs import _Clock

    from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError

    store, ready = ready_preparation(tmp_path)
    clock = _Clock(NOW)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=clock)
    reservation = jobs.claim_run_submission('{"domain":"unknown-work"}', "unknown")
    if expired:
        clock.advance(timedelta(seconds=31))

    async def scenario():
        service = review_service(store, jobs)
        try:
            with pytest.raises(JobAdmissionError) as blocked:
                await service.review_and_freeze(
                    "one", command=review_command(ready), idempotency_key="review"
                )
            assert blocked.value.code == "BACKTEST_BUSY"
            assert store.get("one") == ready
            assert (
                jobs.get_run_submission_reservation('{"domain":"unknown-work"}', "unknown")
                == reservation
            )
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_review_receipt_survives_source_edit_restart_and_another_active_job(tmp_path):
    from tests.integration.test_backtest_single_task import request
    from tests.unit.test_monitor_loop_input import costs

    from trade_plan_monitor.backtest.canonical import canonical_json
    from trade_plan_monitor.backtest.jobs import BacktestJobRepository
    from trade_plan_monitor.backtest.loop_input import LoopResponsePolicy, MonitorLoopInput
    from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3")
    command = review_command(ready)

    async def scenario():
        service = review_service(store, jobs)
        try:
            frozen = await service.review_and_freeze(
                "one", command=command, idempotency_key="review"
            )
            assert await service.get_frozen("one") == frozen
            original = canonical_json(frozen)
            run_input = MonitorLoopInput(
                schedule=frozen.schedule,
                initial_account=frozen.account,
                boundary=LoopEndBoundary.resolve(started_at=AVAILABLE, submitted_at=NOW),
                dataset_hash="3" * 64,
                response=LoopResponsePolicy(mode="FOLLOW_REMINDERS"),
                costs=costs(),
            )
            submitted = canonical_json(run_input)
            run_hash = run_input.input_hash
            reviewed = store.get("one")
            changed = await service.edit_source(
                "one",
                source=ready.source.model_copy(update={"text": ready.source.text + " 新补充。"}),
                expected_revision=reviewed.revision,
                idempotency_key="edit",
            )
            assert changed.candidate is None and changed.review is None
            with pytest.raises(PreparationConflictError, match="REVIEW_REQUIRED"):
                await service.get_frozen("one")
        finally:
            await service.stop()
        jobs.submit(request("VERIFY"), "other")
        restarted = review_service(PreparationStore(store.database_path), jobs)
        try:
            replay = await restarted.review_and_freeze(
                "one", command=command, idempotency_key="review"
            )
            assert canonical_json(replay) == original
            assert replay.manifest_hash == frozen.manifest_hash
            assert store.get("one") == changed
            assert canonical_json(run_input) == submitted and run_input.input_hash == run_hash
            with pytest.raises(PreparationConflictError, match="IDEMPOTENCY_CONFLICT"):
                await restarted.review_and_freeze(
                    "one",
                    command=command.model_copy(update={"evidence": "Changed human declaration"}),
                    idempotency_key="review",
                )
            assert len(jobs.list_jobs()) == 1
        finally:
            await restarted.stop()

    asyncio.run(scenario())


def test_receipt_write_failure_rolls_back_review_and_does_not_consume_key(tmp_path):
    store, ready = ready_preparation(tmp_path)
    command = review_command(ready)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("""CREATE TRIGGER review_receipt_fault
            BEFORE INSERT ON backtest_preparation_idempotency
            WHEN NEW.idempotency_key = 'review'
            BEGIN SELECT RAISE(ABORT, 'synthetic receipt fault'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic receipt fault"):
        store.review_and_freeze("one", command=command, idempotency_key="review")
    assert PreparationStore(store.database_path).get("one") == ready
    assert store.replay_review("one", command=command, idempotency_key="review") is None
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TRIGGER review_receipt_fault")
    assert (
        store.review_and_freeze("one", command=command, idempotency_key="review").status
        == "REVIEWED"
    )


@pytest.mark.parametrize("tamper", ["opaque", "request", "source", "evidence", "human"])
def test_valid_flag_cannot_authorize_forged_extraction_provenance(tmp_path, tamper):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    payload = json.loads(ready.candidate.payload_json)
    if tamper == "opaque":
        payload = {}
    elif tamper == "request":
        payload["request_id"] = "00000000-0000-0000-0000-000000000000"
    elif tamper == "source":
        payload["source_binding_hash"] = "f" * 64
    elif tamper == "evidence":
        payload["evidence_hash"] = "f" * 64
    else:
        payload["daily_mapping"] = review_command(ready).mapping.model_dump(mode="json")
    forged = ready.model_copy(
        update={
            "candidate": ready.candidate.model_copy(
                update={
                    "payload_json": json.dumps(payload),
                    "validation": "VALID",
                    "issues": (),
                }
            )
        }
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE backtest_preparation SET document_json = ? WHERE preparation_id = ?",
            (forged.model_dump_json(), "one"),
        )
    with pytest.raises(PreparationConflictError, match="EXTRACTION_BINDING_CONFLICT"):
        store.review_and_freeze("one", command=review_command(forged), idempotency_key="review")
    assert store.get("one") == forged


def test_legacy_review_declaration_is_not_a_frozen_manifest(tmp_path):
    from trade_plan_monitor.backtest.preparation_review import (
        PreparationSemanticError,
        frozen_preparation,
    )

    store, ready = ready_preparation(tmp_path)
    flagged = ready.model_copy(
        update={
            "candidate": ready.candidate.model_copy(update={"validation": "VALID", "issues": ()})
        }
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE backtest_preparation SET document_json = ? WHERE preparation_id = ?",
            (flagged.model_dump_json(), "one"),
        )
    declaration = store.record_review(
        "one",
        expected_revision=flagged.revision,
        expected_source_revision=flagged.source_revision,
        expected_candidate_revision=flagged.candidate_revision,
        candidate_hash=flagged.candidate.candidate_hash,
        evidence_hash=flagged.candidate.evidence_hash,
        confirmed=True,
        idempotency_key="legacy-review",
    )
    with pytest.raises(PreparationSemanticError, match="FROZEN_BINDING_CONFLICT"):
        frozen_preparation(declaration)


def test_cancelled_observer_keeps_review_admission_until_physical_end(tmp_path, monkeypatch):
    from tests.integration.test_backtest_single_task import request

    from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation
    from trade_plan_monitor.backtest.service_config import BacktestServiceConfig
    from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable

    store, ready = ready_preparation(tmp_path)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3")
    entered, release = Event(), Event()
    original = store.review_and_freeze

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "review_and_freeze", blocked)

    async def scenario():
        service = review_service(store, jobs)
        service._config = BacktestServiceConfig(shutdown_wait_seconds=0.02)
        observer = asyncio.create_task(
            service.review_and_freeze(
                "one", command=review_command(ready), idempotency_key="review"
            )
        )
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.005)
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            with pytest.raises(JobAdmissionError) as busy:
                jobs.submit(request("VERIFY"), "other")
            assert busy.value.code == "BACKTEST_BUSY"
            with pytest.raises(BacktestServiceUnavailable):
                await service.stop()
            with pytest.raises(JobAdmissionError):
                jobs.submit(request("VERIFY"), "other")
        finally:
            release.set()
            await service.wait_for_drain()
            await service.stop()
        assert frozen_preparation(store.get("one")).version.review.confirmed is True
        assert jobs.submit(request("VERIFY"), "other").status.value == "QUEUED"

    asyncio.run(scenario())


def test_restart_replays_durable_review_after_crash_before_admission_release(tmp_path, monkeypatch):
    from tests.integration.test_backtest_single_task import request

    from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError

    store, ready = ready_preparation(tmp_path)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3")
    command = review_command(ready)

    def fail_release(*args):
        raise OSError("synthetic release crash")

    async def scenario():
        service = review_service(store, jobs)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(jobs, "release_run_submission", fail_release)
                with pytest.raises(OSError, match="synthetic release crash"):
                    await service.review_and_freeze(
                        "one", command=command, idempotency_key="review"
                    )
            frozen = await service.get_frozen("one")
            with pytest.raises(JobAdmissionError):
                jobs.submit(request("VERIFY"), "other")
        finally:
            await service.stop()
        restarted = review_service(
            PreparationStore(store.database_path), BacktestJobRepository(jobs.database_path)
        )
        try:
            assert (
                await restarted.review_and_freeze("one", command=command, idempotency_key="review")
                == frozen
            )
            assert jobs.submit(request("VERIFY"), "other").status.value == "QUEUED"
        finally:
            await restarted.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("future", ["snapshot", "mark"])
def test_review_rejects_opening_account_information_after_historical_start(tmp_path, future):
    from trade_plan_monitor.backtest.loop_input import LoopOpeningMark
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    account = review_command(ready).account
    later = AVAILABLE + timedelta(days=1)
    if future == "snapshot":
        account = account.model_copy(update={"snapshot_at": later})
    else:
        account = account.model_copy(
            update={
                "opening_mark": LoopOpeningMark(
                    price_fen=4010,
                    price_at=later,
                    available_at=later,
                    evidence="Synthetic future observation cannot mark the opening account.",
                )
            }
        )
    with pytest.raises(PreparationConflictError):
        store.review_and_freeze(
            "one", command=review_command(ready, account=account), idempotency_key="review"
        )
    assert store.get("one") == ready


@pytest.mark.parametrize("expired", [False, True])
def test_same_review_key_without_receipt_cannot_reclaim_pending_admission(tmp_path, expired):
    from hashlib import sha256

    from tests.integration.test_backtest_jobs import _Clock

    from trade_plan_monitor.backtest.canonical import canonical_json
    from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError

    store, ready = ready_preparation(tmp_path)
    command = review_command(ready)
    clock = _Clock(NOW)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3", clock=clock)
    intent = canonical_json(
        {
            "domain": "single-source-review-v1",
            "preparation_id": "one",
            "command_hash": sha256(canonical_json(command).encode()).hexdigest(),
        }
    )
    key = (
        "prep-review-"
        + sha256(
            canonical_json(
                {
                    "preparation_id": "one",
                    "idempotency_key": "review",
                }
            ).encode()
        ).hexdigest()
    )
    pending = jobs.claim_run_submission(intent, key)
    if expired:
        clock.advance(timedelta(seconds=31))

    async def scenario():
        service = review_service(store, jobs)
        try:
            with pytest.raises(JobAdmissionError) as busy:
                await service.review_and_freeze("one", command=command, idempotency_key="review")
            assert busy.value.code == "BACKTEST_BUSY"
            assert store.get("one") == ready
            assert jobs.get_run_submission_reservation(intent, key) == pending
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_worker_completion_without_claim_cleanup_still_blocks_freezing(tmp_path):
    from uuid import uuid4

    from trade_plan_monitor.backtest.canonical import canonical_json
    from trade_plan_monitor.backtest.jobs import BacktestJobRepository
    from trade_plan_monitor.backtest.preparation_models import PreparationWorkClaim
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store, ready = ready_preparation(tmp_path)
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3")
    intent = canonical_json({"domain": "synthetic-ended-extraction"})
    reservation = jobs.claim_run_submission(intent, "ended-extraction")
    claim = PreparationWorkClaim(
        generation=ready.attempts[-1].attempt_id,
        owner_id=str(uuid4()),
        source_revision=ready.source_revision,
        source_hash=ready.source.binding_hash,
        admission_key=reservation.idempotency_key,
        intent_hash=reservation.intent_hash,
        claimed_at=reservation.claimed_at,
        intent_json=intent,
        phase="ENDED",
    )
    pending = ready.model_copy(update={"work_claim": claim})
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE backtest_preparation SET document_json = ? WHERE preparation_id = ?",
            (pending.model_dump_json(), "one"),
        )
    with pytest.raises(PreparationConflictError, match="WORKER_CLAIM_PENDING"):
        store.review_and_freeze("one", command=review_command(pending), idempotency_key="review")
    assert store.get("one") == pending
