"""Single-source preparation persists independently from live/market/job state."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_store import (
    PreparationConflictError,
    PreparationStore,
)

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def source(text="Explicit 100 CORE shares at 40.105/share; cash unknown."):
    return PreparationSource(source_id="source-1", text=text)


def create(store, *, key="create-1"):
    return store.create(
        SinglePlanPreparationInput(preparation_id="preparation-1", sources=(source(),)),
        idempotency_key=key,
    )


def test_source_and_creation_receipt_survive_restart(tmp_path):
    path = tmp_path / "preparations.sqlite"
    store = PreparationStore(path, clock=lambda: NOW)
    record = create(store)
    assert record.revision == record.source_revision == 1
    assert record.source.text == source().text
    assert record.source.source_hash == sha256(source().text.encode()).hexdigest()
    assert record.source.authored_at is record.source.available_at is None
    assert record.candidate is record.review is None
    assert record.attempts == ()
    reopened = PreparationStore(path, clock=lambda: NOW)
    assert reopened.get(record.preparation_id) == record
    assert create(reopened) == record
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT domain, schema_version FROM backtest_preparation_metadata"
        ).fetchone() == ("backtest-preparation-v1", 2)


@pytest.mark.parametrize("count", [0, 2])
def test_preparation_rejects_any_other_source_count(count):
    with pytest.raises(ValidationError):
        SinglePlanPreparationInput(
            preparation_id="preparation-1", sources=tuple(source() for _ in range(count))
        )


@pytest.mark.parametrize("table", ["active_plan", "market_head", "backtest_job", "unknown"])
def test_cross_domain_path_is_rejected_without_file_mutation(tmp_path, table):
    path = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"CREATE TABLE {table} (id TEXT)")
        connection.commit()
    original = path.read_bytes()
    with pytest.raises(ValueError):
        PreparationStore(path)
    assert path.read_bytes() == original


def test_concurrent_creation_retry_has_one_durable_receipt(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: create(store), range(6)))
    assert all(record == results[0] for record in results)
    with pytest.raises(PreparationConflictError, match="PREPARATION_EXISTS"):
        create(store, key="different-intent")


def candidate(validation="VALID"):
    from trade_plan_monitor.backtest.preparation_models import PreparationCandidateInput

    return PreparationCandidateInput(
        payload_json='{"schema_version":"fixture-v1","opening_cost_fen":401050}',
        validation=validation,
        evidence_hash="e" * 64,
        issues=() if validation == "VALID" else ("Missing source fact",),
    )


def start(store, record, key="attempt-1"):
    return store.start_attempt(
        record.preparation_id, expected_revision=record.revision, idempotency_key=key,
    )


def finish(store, record, *, value=None, key="finish-1", **failure):
    return store.finish_attempt(
        record.preparation_id, attempt_id=record.attempts[-1].attempt_id,
        expected_revision=record.revision, candidate=value, idempotency_key=key, **failure,
    )


def review(store, record, **changes):
    values = dict(
        expected_revision=record.revision,
        expected_source_revision=record.source_revision,
        expected_candidate_revision=record.candidate_revision,
        candidate_hash=record.candidate.candidate_hash,
        evidence_hash=record.candidate.evidence_hash,
        confirmed=True,
        idempotency_key="review-1",
    )
    return store.record_review(record.preparation_id, **(values | changes))


def test_running_attempt_restart_requires_explicit_outcome(tmp_path):
    path = tmp_path / "preparations.sqlite"
    store = PreparationStore(path, clock=lambda: NOW)
    original = create(store)
    running = start(store, original)
    reopened = PreparationStore(path, clock=lambda: NOW)
    assert reopened.get(original.preparation_id) == running
    assert start(reopened, original) == running
    with pytest.raises(PreparationConflictError, match="PREPARATION_BUSY"):
        start(reopened, running, "blind-retry")
    assert reopened.get(original.preparation_id) == running


def test_validation_is_not_review_and_explicit_review_is_durable(tmp_path):
    path = tmp_path / "preparations.sqlite"
    store = PreparationStore(path, clock=lambda: NOW)
    ready = finish(store, start(store, create(store)), value=candidate())
    assert ready.status == "CANDIDATE"
    assert ready.candidate.validation == "VALID"
    assert ready.review is None
    assert ready.attempts[-1].status == "SUCCEEDED"
    reopened = PreparationStore(path, clock=lambda: NOW)
    assert reopened.get(ready.preparation_id) == ready
    approved = review(reopened, ready)
    assert approved.status == "REVIEWED"
    assert approved.review.confirmed is True
    assert approved.review.candidate_revision == ready.candidate_revision
    assert approved.review.source_revision == ready.source_revision
    assert approved.review.evidence_hash == "e" * 64
    assert approved.review_revision > ready.review_revision
    assert PreparationStore(path).get(ready.preparation_id) == approved


@pytest.mark.parametrize("validation", ["INVALID", "UNRESOLVED"])
def test_unresolved_candidate_cannot_be_reviewed(tmp_path, validation):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    ready = finish(store, start(store, create(store)), value=candidate(validation))
    with pytest.raises(PreparationConflictError, match="CANDIDATE_NOT_VALID"):
        review(store, ready)
    assert store.get(ready.preparation_id) == ready


@pytest.mark.parametrize("changes", [
    {"confirmed": False}, {"confirmed": 1}, {"candidate_hash": "a" * 64},
    {"evidence_hash": "a" * 64}, {"expected_candidate_revision": 999},
    {"expected_source_revision": 999},
])
def test_review_rejects_implicit_approval_and_changed_binding(tmp_path, changes):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    ready = finish(store, start(store, create(store)), value=candidate())
    with pytest.raises((ValueError, PreparationConflictError)):
        review(store, ready, **changes)
    assert store.get(ready.preparation_id) == ready


def test_source_edit_invalidates_candidate_review_and_old_receipts_stay_frozen(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = create(store)
    ready = finish(store, start(store, original), value=candidate())
    approved = review(store, ready)
    edited = store.edit_source(
        approved.preparation_id, source=source("Corrected opening cost unknown."),
        expected_revision=approved.revision, idempotency_key="edit-1",
    )
    assert edited.source_revision == original.source_revision + 1
    assert edited.candidate_revision > approved.candidate_revision
    assert edited.review_revision > approved.review_revision
    assert edited.candidate is edited.review is None
    assert edited.attempts == ()
    assert edited.status == "DRAFT"
    assert create(store) == original
    assert review(store, ready) == approved
    assert store.get(original.preparation_id) == edited


@pytest.mark.parametrize("action", ["edit", "cancel"])
def test_edit_and_cancel_fence_late_completion(tmp_path, action):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    running = start(store, create(store))
    if action == "edit":
        current = store.edit_source(
            running.preparation_id, source=source("Corrected source"),
            expected_revision=running.revision, idempotency_key="edit-1",
        )
    else:
        current = store.cancel(
            running.preparation_id, expected_revision=running.revision, idempotency_key="cancel-1",
        )
        assert current.attempts[-1].status == "CANCEL_REQUESTED"
    with pytest.raises(PreparationConflictError):
        finish(store, running, value=candidate())
    with pytest.raises(PreparationConflictError, match="STALE_ATTEMPT"):
        store.finish_attempt(
            current.preparation_id, attempt_id=running.attempts[-1].attempt_id,
            expected_revision=current.revision, candidate=candidate(), idempotency_key="late-2",
        )
    assert store.get(running.preparation_id) == current


def test_three_retryable_attempts_are_a_durable_bound(tmp_path):
    path = tmp_path / "preparations.sqlite"
    store = PreparationStore(path, clock=lambda: NOW)
    record = create(store)
    for number in range(3):
        record = start(store, record, f"attempt-{number}")
        record = finish(
            store, record, error_code="PROVIDER_TIMEOUT", retryable=True, key=f"fail-{number}",
        )
        store = PreparationStore(path, clock=lambda: NOW)
    assert len(record.attempts) == 3
    assert all(attempt.status == "FAILED" for attempt in record.attempts)
    with pytest.raises(PreparationConflictError, match="ATTEMPTS_EXHAUSTED"):
        start(store, record, "attempt-4")
    assert store.get(record.preparation_id) == record


def test_non_retryable_failure_and_cancel_do_not_requeue(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    failed = finish(store, start(store, create(store)), error_code="UNSUPPORTED_SOURCE")
    with pytest.raises(PreparationConflictError, match="RETRY_NOT_ALLOWED"):
        start(store, failed, "retry")
    cancelled = store.cancel(
        failed.preparation_id, expected_revision=failed.revision, idempotency_key="cancel",
    )
    with pytest.raises(PreparationConflictError, match="PREPARATION_CANCELLED"):
        start(store, cancelled, "retry-cancelled")


def test_concurrent_source_edits_enforce_revision(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = create(store)

    def edit(number):
        try:
            return store.edit_source(
                original.preparation_id, source=source(f"Correction {number}"),
                expected_revision=original.revision, idempotency_key=f"edit-{number}",
            )
        except PreparationConflictError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, range(2)))
    assert results.count("REVISION_CONFLICT") == 1
    assert store.get(original.preparation_id).source_revision == 2


def test_identical_source_edit_does_not_reset_attempt_budget(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    running = start(store, create(store))
    unchanged = store.edit_source(
        running.preparation_id, source=running.source,
        expected_revision=running.revision, idempotency_key="same-source",
    )
    assert unchanged == running


def test_other_preparation_cannot_start_or_be_created_while_attempt_unresolved(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    first = create(store)
    second = store.create(
        SinglePlanPreparationInput(preparation_id="preparation-2", sources=(source(),)),
        idempotency_key="create-2",
    )
    running = start(store, first)
    with pytest.raises(PreparationConflictError, match="PREPARATION_BUSY"):
        start(store, second, "attempt-2")
    with pytest.raises(PreparationConflictError, match="PREPARATION_BUSY"):
        store.create(
            SinglePlanPreparationInput(preparation_id="preparation-3", sources=(source(),)),
            idempotency_key="create-3",
        )
    assert store.get("preparation-3") is None
    reopened = PreparationStore(store.database_path, clock=lambda: NOW)
    assert reopened.get(first.preparation_id) == running
    assert reopened.get(second.preparation_id) == second


def test_state_write_rolls_back_if_idempotency_receipt_fails(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = create(store)
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute(
            "CREATE TRIGGER fixture_receipt_failure BEFORE INSERT "
            "ON backtest_preparation_idempotency WHEN NEW.idempotency_key = 'edit-fault' "
            "BEGIN SELECT RAISE(ABORT, 'fixture receipt failure'); END"
        )
        connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="fixture receipt failure"):
        store.edit_source(
            original.preparation_id, source=source("Corrected source"),
            expected_revision=original.revision, idempotency_key="edit-fault",
        )
    assert store.get(original.preparation_id) == original
    with closing(sqlite3.connect(store.database_path)) as connection:
        assert connection.execute(
            "SELECT 1 FROM backtest_preparation_idempotency WHERE idempotency_key = 'edit-fault'"
        ).fetchone() is None
        connection.execute("DROP TRIGGER fixture_receipt_failure")
        connection.commit()
    retried = store.edit_source(
        original.preparation_id, source=source("Corrected source"),
        expected_revision=original.revision, idempotency_key="edit-fault",
    )
    assert retried.revision == 2


def test_idempotency_key_cannot_bind_changed_source_or_operation(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = create(store)
    with pytest.raises(PreparationConflictError, match="IDEMPOTENCY_CONFLICT"):
        store.create(
            SinglePlanPreparationInput(preparation_id=original.preparation_id,
                                       sources=(source("Changed source"),)),
            idempotency_key="create-1",
        )
    with pytest.raises(PreparationConflictError, match="IDEMPOTENCY_CONFLICT"):
        start(store, original, "create-1")
    assert store.get(original.preparation_id) == original


def test_reextraction_requires_fresh_review_and_preserves_old_reply(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    first = finish(store, start(store, create(store)), value=candidate())
    approved = review(store, first)
    running = start(store, approved, "reextract")
    assert running.candidate is running.review is None
    new = finish(store, running, value=candidate(), key="finish-2")
    assert new.candidate_revision > approved.candidate_revision
    assert new.review is None
    assert review(store, first) == approved
    assert store.get(new.preparation_id) == new
    with pytest.raises(PreparationConflictError, match="REVIEW_BINDING_CONFLICT"):
        review(store, new, expected_candidate_revision=first.candidate_revision,
               idempotency_key="stale-review")


@pytest.mark.parametrize("payload", [
    "{", "[]", '{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}',
    '{"nested":' * 65 + "{}" + "}" * 65,
    '{"items":[' + ",".join("0" for _ in range(10001)) + "]}",
    '{"text":"' + "汉" * 350000 + '"}',
], ids=["malformed", "array", "duplicates", "nan", "infinite", "depth", "nodes", "utf8-bytes"])
def test_candidate_payload_has_existing_extraction_bounds(payload):
    from trade_plan_monitor.backtest.preparation_models import PreparationCandidateInput

    with pytest.raises(ValidationError):
        PreparationCandidateInput(payload_json=payload, validation="VALID", evidence_hash="e" * 64)


def test_metadata_only_edit_fences_result_and_preserves_supplied_dates(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    running = start(store, create(store))
    corrected = running.source.model_copy(update={
        "authored_at": NOW, "available_at": NOW, "effective_trade_date": NOW.date(),
    })
    edited = store.edit_source(
        running.preparation_id, source=corrected, expected_revision=running.revision,
        idempotency_key="source-dates",
    )
    assert edited.source.source_hash == running.source.source_hash
    assert edited.source.binding_hash != running.source.binding_hash
    assert PreparationStore(store.database_path).get(edited.preparation_id).source == corrected
    with pytest.raises(PreparationConflictError, match="STALE_ATTEMPT"):
        store.finish_attempt(
            edited.preparation_id, expected_revision=edited.revision,
            attempt_id=running.attempts[-1].attempt_id, candidate=candidate(),
            idempotency_key="late-after-dates",
        )


@pytest.mark.parametrize("other_store", ["market", "results"])
def test_preparation_file_cannot_be_opened_as_other_backtest_domain(tmp_path, other_store):
    from trade_plan_monitor.backtest.market_store import BacktestMarketStore
    from trade_plan_monitor.backtest.migration import MigrationPreflightError
    from trade_plan_monitor.backtest.results import BacktestResultStore

    path = tmp_path / "preparations.sqlite"
    create(PreparationStore(path, clock=lambda: NOW))
    original = path.read_bytes()
    constructor = BacktestMarketStore if other_store == "market" else BacktestResultStore
    with pytest.raises((ValueError, MigrationPreflightError)):
        constructor(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("mutation", ["domain", "version", "missing-tag", "mixed-domain"])
def test_unsupported_or_mixed_preparation_tag_is_not_adopted(tmp_path, mutation):
    path = tmp_path / "preparations.sqlite"
    create(PreparationStore(path, clock=lambda: NOW))
    with closing(sqlite3.connect(path)) as connection:
        statements = {
            "domain": "UPDATE backtest_preparation_metadata SET domain = 'different-domain'",
            "version": "UPDATE backtest_preparation_metadata SET schema_version = 999",
            "missing-tag": "DROP TABLE backtest_preparation_metadata",
            "mixed-domain": "CREATE TABLE active_plan (id TEXT)",
        }
        connection.execute(statements[mutation])
        connection.commit()
    original = path.read_bytes()
    with pytest.raises(ValueError):
        PreparationStore(path)
    assert path.read_bytes() == original


def test_durable_identity_mismatch_is_rejected(tmp_path):
    import json

    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = create(store)
    document = json.loads(original.model_dump_json()) | {"preparation_id": "different"}
    with closing(sqlite3.connect(store.database_path)) as connection:
        connection.execute(
            "UPDATE backtest_preparation SET document_json = ? WHERE preparation_id = ?",
            (json.dumps(document), original.preparation_id),
        )
        connection.commit()
    with pytest.raises(ValueError, match="identity"):
        store.get(original.preparation_id)


def test_concurrent_different_preparation_attempts_have_one_winner(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    records = [store.create(
        SinglePlanPreparationInput(preparation_id=f"preparation-{number}", sources=(source(),)),
        idempotency_key=f"create-{number}",
    ) for number in range(2)]

    def attempt(record):
        try:
            return start(store, record, "start-" + record.preparation_id)
        except PreparationConflictError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, records))
    assert results.count("PREPARATION_BUSY") == 1
    assert sum(store.get(record.preparation_id).status == "EXTRACTING" for record in records) == 1


def test_lost_completion_reply_returns_original_candidate_after_later_edit(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    running = start(store, create(store))
    completed = finish(store, running, value=candidate())
    edited = store.edit_source(
        completed.preparation_id, source=source("Changed after completion"),
        expected_revision=completed.revision, idempotency_key="edit-after-completion",
    )
    assert finish(store, running, value=candidate()) == completed
    assert store.get(edited.preparation_id) == edited


@pytest.mark.parametrize("action", ["cancel", "edit"])
def test_cancel_or_edit_keeps_unresolved_attempt_until_explicit_acknowledgment(tmp_path, action):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = create(store)
    second = store.create(
        SinglePlanPreparationInput(preparation_id="preparation-2", sources=(source(),)),
        idempotency_key="create-2",
    )
    running = start(store, original)
    if action == "cancel":
        pending = store.cancel(
            running.preparation_id, expected_revision=running.revision, idempotency_key="cancel",
        )
    else:
        pending = store.edit_source(
            running.preparation_id, source=source("Corrected source"),
            expected_revision=running.revision, idempotency_key="edit",
        )
    reopened = PreparationStore(store.database_path, clock=lambda: NOW)
    assert reopened.get(pending.preparation_id).status == "CANCEL_REQUESTED"
    with pytest.raises(PreparationConflictError, match="PREPARATION_BUSY"):
        start(reopened, second, "start-other")
    with pytest.raises(PreparationConflictError, match="PREPARATION_BUSY"):
        start(reopened, pending, "start-replacement")
    with pytest.raises(PreparationConflictError, match="STALE_ATTEMPT"):
        reopened.acknowledge_cancellation(
            pending.preparation_id, attempt_id="different-attempt",
            expected_revision=pending.revision, idempotency_key="bad-ack",
        )
    ended = reopened.acknowledge_cancellation(
        pending.preparation_id, attempt_id=running.attempts[-1].attempt_id,
        expected_revision=pending.revision, idempotency_key="ack",
    )
    assert ended.status == ("CANCELLED" if action == "cancel" else "DRAFT")
    assert reopened.get(ended.preparation_id) == ended
    assert start(reopened, second, "start-other").status == "EXTRACTING"


def test_cancel_after_source_edit_ends_without_reopening_draft(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    running = start(store, create(store))
    edited = store.edit_source(
        running.preparation_id, source=source("Corrected source"),
        expected_revision=running.revision, idempotency_key="edit",
    )
    pending = store.cancel(
        edited.preparation_id, expected_revision=edited.revision, idempotency_key="cancel-edit",
    )
    ended = store.acknowledge_cancellation(
        pending.preparation_id, expected_revision=pending.revision,
        attempt_id=running.attempts[-1].attempt_id, idempotency_key="ack",
    )
    assert ended.status == "CANCELLED"
    assert ended.source == edited.source


def test_constructed_values_cannot_bypass_source_cardinality(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    forged = SinglePlanPreparationInput.model_construct(
        preparation_id="preparation-1", sources=(source(), source("second source")),
    )
    with pytest.raises(ValueError):
        store.create(forged, idempotency_key="forged")
    assert store.get("preparation-1") is None


def test_constructed_values_cannot_persist_blank_source(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = create(store)
    forged = PreparationSource.model_construct(source_id="source-1", text=" ")
    with pytest.raises(ValueError):
        store.edit_source(
            original.preparation_id, source=forged, expected_revision=original.revision,
            idempotency_key="forged-source",
        )
    assert store.get(original.preparation_id) == original


def test_constructed_values_cannot_persist_unbounded_candidate(tmp_path):
    from trade_plan_monitor.backtest.preparation_models import PreparationCandidateInput

    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    running = start(store, create(store))
    forged = PreparationCandidateInput.model_construct(
        payload_json="[]", validation="VALID", evidence_hash="e" * 64, issues=(),
    )
    with pytest.raises(ValueError):
        finish(store, running, value=forged)
    assert store.get(running.preparation_id) == running


def collection_input():
    from trade_plan_monitor.backtest.preparation_models import PlanCollectionPreparationInput

    return PlanCollectionPreparationInput(
        preparation_id="collection-1", sources=tuple(
            PreparationSource(source_id=f"source-{number}",
                              text=f"Synthetic complete source {number}")
            for number in (3, 1, 2)
        ),
    )


def test_collection_creation_preserves_order_and_frozen_receipt_across_restart(tmp_path):
    path, value = tmp_path / "preparations.sqlite", collection_input()
    store = PreparationStore(path, clock=lambda: NOW)
    created = store.create(value, idempotency_key="collection-create")
    assert created.schema_version == "backtest-preparation-v2"
    assert tuple(item.source for item in created.items) == value.sources
    assert [item.status for item in created.items] == ["DRAFT", "WAITING", "WAITING"]
    assert all(item.source_revision == 1 and item.candidate_revision == 0
               and item.candidate is item.base_hash is None and item.attempts == ()
               for item in created.items)
    reopened = PreparationStore(path, clock=lambda: NOW)
    assert reopened.get(created.preparation_id) == created
    assert reopened.create(value, idempotency_key="collection-create") == created


def edit_collection(store, record, *, source=None, order=None, key="collection-edit"):
    return store.edit_collection(
        record.preparation_id, source=source, source_order=order,
        expected_revision=record.revision, idempotency_key=key,
    )


def test_collection_edit_invalidates_only_changed_suffix_and_freezes_old_receipts(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    value = collection_input()
    original = store.create(value, idempotency_key="collection-create")
    corrected = original.items[1].source.model_copy(update={"text": "Synthetic correction"})
    edited = edit_collection(store, original, source=corrected)
    assert edited.revision == original.revision + 1
    assert edited.items[0].model_dump_json() == original.items[0].model_dump_json()
    assert [item.source_revision for item in edited.items] == [1, 2, 1]
    assert [item.candidate_revision for item in edited.items] == [0, 1, 1]
    assert all(item.candidate is item.base_hash is None for item in edited.items[1:])
    assert edited.review is None
    assert edit_collection(store, original, source=corrected) == edited
    assert store.create(value, idempotency_key="collection-create") == original
    assert store.replay_create(value, idempotency_key="collection-create") == original
    assert PreparationStore(store.database_path).get(original.preparation_id) == edited


def test_collection_reorder_preserves_ids_and_invalidates_from_first_changed_position(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = store.create(collection_input(), idempotency_key="collection-create")
    reordered = edit_collection(store, original, order=("source-3", "source-2", "source-1"))
    assert [item.source.source_id for item in reordered.items] == [
        "source-3", "source-2", "source-1",
    ]
    assert reordered.items[0].model_dump_json() == original.items[0].model_dump_json()
    assert [item.source_revision for item in reordered.items] == [1, 1, 1]
    assert [item.candidate_revision for item in reordered.items] == [0, 1, 1]
    assert {item.source.source_id: item.source for item in reordered.items} == {
        item.source.source_id: item.source for item in original.items
    }
    for number, order in enumerate(((), ("source-3", "source-1"),
                                    ("source-3", "source-1", "source-1"),
                                    ("source-3", "source-1", "new-id"))):
        with pytest.raises(ValueError):
            edit_collection(store, reordered, order=order, key=f"bad-order-{number}")
    with pytest.raises(ValueError):
        edit_collection(store, reordered, source=PreparationSource(source_id="new-id", text="New"),
                        key="changed-id")
    assert store.get(original.preparation_id) == reordered


def test_collection_noop_and_metadata_edit_keep_precise_revision_semantics(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = store.create(collection_input(), idempotency_key="collection-create")
    unchanged = edit_collection(store, original, source=original.items[0].source,
                                order=tuple(item.source.source_id for item in original.items))
    assert unchanged.model_dump_json() == original.model_dump_json()
    corrected = original.items[1].source.model_copy(update={
        "authored_at": NOW, "available_at": NOW, "effective_trade_date": NOW.date(),
    })
    edited = edit_collection(store, original, source=corrected, key="metadata-edit")
    assert corrected.source_hash == original.items[1].source.source_hash
    assert corrected.binding_hash != original.items[1].source.binding_hash
    assert edited.items[0] == original.items[0]
    assert [item.source_revision for item in edited.items] == [1, 2, 1]
    assert [item.candidate_revision for item in edited.items] == [0, 1, 1]
    with pytest.raises(PreparationConflictError, match="REVISION_CONFLICT"):
        edit_collection(store, original, source=corrected, key="stale-edit")


def test_collection_concurrent_edits_have_one_revision_winner(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = store.create(collection_input(), idempotency_key="collection-create")

    def change(number):
        try:
            corrected = original.items[1].source.model_copy(update={"text": f"Correction {number}"})
            return edit_collection(store, original, source=corrected, key=f"edit-{number}")
        except PreparationConflictError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, range(2)))
    assert results.count("REVISION_CONFLICT") == 1
    current = store.get(original.preparation_id)
    assert current.revision == 2 and current.items[1].source_revision == 2
    assert current.items[0] == original.items[0]


def test_collection_count_identity_and_exact_utf8_aggregate_bounds():
    from trade_plan_monitor.backtest.preparation_models import PlanCollectionPreparationInput

    sources = tuple(PreparationSource(source_id=f"s{number}", text="Synthetic")
                    for number in range(257))
    def make(items):
        return PlanCollectionPreparationInput(preparation_id="bounded", sources=items)

    assert len(make(sources[:256]).sources) == 256
    for invalid in ((), sources, (sources[0], sources[0])):
        with pytest.raises(ValidationError):
            make(invalid)
    full = tuple(PreparationSource(source_id=f"full-{number}", text="x" * 150_000)
                 for number in range(55))
    assert len(make((*full, PreparationSource(source_id="tail", text="x" * 138_608))).sources) == 56
    for tail in ("x" * 138_609, "文" * 138_608):
        with pytest.raises(ValidationError):
            make((*full, PreparationSource(source_id="tail", text=tail)))


def materialized_collection(record):
    from trade_plan_monitor.backtest.preparation_models import (
        CollectionPreparationAttempt,
        CollectionPreparationCandidate,
    )

    items, base_hash = [], None
    for item in record.items:
        value = CollectionPreparationCandidate(
            **candidate().model_dump(), source_revision=item.source_revision,
            source_hash=item.source.binding_hash, base_hash=base_hash,
        )
        attempt = CollectionPreparationAttempt(
            attempt_id="fixture-" + item.source.source_id, source_revision=item.source_revision,
            source_hash=item.source.binding_hash, base_hash=base_hash,
            status="SUCCEEDED", started_at=NOW, finished_at=NOW,
        )
        items.append(item.model_copy(update={
            "candidate": value, "candidate_revision": 1, "base_hash": base_hash,
            "attempts": (attempt,), "status": "CANDIDATE",
        }))
        base_hash = value.candidate_hash
    return record.model_copy(update={"items": tuple(items), "status": "CANDIDATE"})


def test_collection_candidate_chain_rejects_stale_source_and_predecessor_bindings(tmp_path):
    from trade_plan_monitor.backtest.preparation_models import CollectionPreparationRecord

    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    ready = materialized_collection(store.create(collection_input(), idempotency_key="create"))
    assert CollectionPreparationRecord.model_validate_json(ready.model_dump_json()) == ready
    for field, stale in (("source_revision", 2), ("source_hash", "f" * 64),
                         ("base_hash", "e" * 64)):
        raw = ready.model_dump(mode="python")
        raw["items"][1]["candidate"][field] = stale
        with pytest.raises(ValidationError):
            CollectionPreparationRecord.model_validate(raw)
    raw = ready.model_dump(mode="python")
    # Even matching local candidate/attempt bases cannot replace the actual predecessor binding.
    raw["items"][1]["base_hash"] = "e" * 64
    raw["items"][1]["candidate"]["base_hash"] = "e" * 64
    raw["items"][1]["attempts"][0]["base_hash"] = "e" * 64
    with pytest.raises(ValidationError):
        CollectionPreparationRecord.model_validate(raw)


def test_collection_edit_clears_materialized_descendants_and_preserves_prefix_bytes(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = store.create(collection_input(), idempotency_key="create")
    ready = materialized_collection(original)
    # Persist an explicitly synthetic completed chain; worker orchestration belongs to RP-T07.
    store._operation("FIXTURE_CANDIDATES", original.preparation_id, {}, "fixture-candidates",
                     lambda record, now: ready)
    edited = edit_collection(store, ready, source=ready.items[1].source.model_copy(update={
        "text": "Synthetic revised middle source",
    }))
    assert edited.items[0].model_dump_json() == ready.items[0].model_dump_json()
    assert [item.source_revision for item in edited.items] == [1, 2, 1]
    assert [item.candidate_revision for item in edited.items] == [1, 2, 2]
    assert [item.status for item in edited.items] == ["CANDIDATE", "DRAFT", "WAITING"]
    assert all(item.candidate is item.base_hash is None and item.attempts == ()
               for item in edited.items[1:])
    assert store.get(edited.preparation_id) == edited


def test_collection_whole_chain_review_binds_every_item_and_requires_explicit_true(tmp_path):
    from trade_plan_monitor.backtest.preparation_models import (
        CollectionPreparationRecord,
        CollectionPreparationReview,
        PreparationItemReview,
    )

    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    ready = materialized_collection(store.create(collection_input(), idempotency_key="create"))
    approval = CollectionPreparationReview(items=tuple(PreparationItemReview(
        source_id=item.source.source_id, source_revision=item.source_revision,
        candidate_revision=item.candidate_revision, candidate_hash=item.candidate.candidate_hash,
        evidence_hash=item.candidate.evidence_hash, base_hash=item.base_hash,
    ) for item in ready.items), confirmed=True, reviewed_at=NOW)
    approved = ready.model_copy(update={
        "status": "REVIEWED", "review_revision": 1, "review": approval,
    })
    for implicit in (1, False, "true"):
        with pytest.raises(ValidationError):
            approval.model_copy(update={"confirmed": implicit})
    for field, wrong in (("source_id", "other"), ("source_revision", 2),
                         ("candidate_revision", 2), ("candidate_hash", "f" * 64),
                         ("evidence_hash", "f" * 64), ("base_hash", "f" * 64)):
        raw = approved.model_dump(mode="python")
        raw["review"]["items"][1][field] = wrong
        with pytest.raises(ValidationError):
            CollectionPreparationRecord.model_validate(raw)
    for items in (approval.items[:-1], tuple(reversed(approval.items))):
        with pytest.raises(ValidationError):
            approved.model_copy(update={"review": approval.model_copy(update={"items": items})})
    store._operation("FIXTURE_REVIEW", ready.preparation_id, {}, "fixture-review",
                     lambda record, now: approved)
    reopened = PreparationStore(store.database_path, clock=lambda: NOW)
    assert reopened.get(ready.preparation_id) == approved
    edited = edit_collection(reopened, approved, source=approved.items[-1].source.model_copy(
        update={"text": "Synthetic corrected last source"},
    ))
    assert edited.review is None and edited.review_revision == approved.review_revision + 1
    assert edited.items[:-1] == approved.items[:-1]


@pytest.mark.parametrize("status", ["EXTRACTING", "CANCEL_REQUESTED"])
def test_collection_unknown_claim_keeps_creation_and_edits_exclusive(tmp_path, status):
    from trade_plan_monitor.backtest.preparation_models import (
        CollectionPreparationAttempt,
        CollectionPreparationWorkClaim,
    )

    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    legacy = create(store)
    original = store.create(collection_input(), idempotency_key="collection-create")
    item = original.items[0]
    attempt = CollectionPreparationAttempt(
        attempt_id="synthetic-generation", source_revision=1, source_hash=item.source.binding_hash,
        base_hash=None, status="RUNNING" if status == "EXTRACTING" else "CANCEL_REQUESTED",
        started_at=NOW,
    )
    claim = CollectionPreparationWorkClaim(
        generation=attempt.attempt_id, owner_id="synthetic-owner", source_id=item.source.source_id,
        source_revision=1, source_hash=item.source.binding_hash, base_hash=None,
        admission_key="synthetic-admission", intent_hash="a" * 64, claimed_at=NOW,
        intent_json="{}", phase="UNKNOWN",
    )
    pending = original.model_copy(update={
        "items": (item.model_copy(update={"attempts": (attempt,), "status": status}),
                  *original.items[1:]), "status": status, "work_claim": claim,
    })
    store._operation("FIXTURE_PENDING", original.preparation_id, {}, "fixture-pending",
                     lambda record, now: pending)
    reopened = PreparationStore(store.database_path, clock=lambda: NOW)
    assert reopened.get(original.preparation_id) == pending
    with pytest.raises(PreparationConflictError, match="PREPARATION_BUSY"):
        edit_collection(reopened, pending, source=item.source.model_copy(
            update={"text": "Changed"},
        ))
    with pytest.raises(PreparationConflictError, match="PREPARATION_BUSY"):
        reopened.create(collection_input().model_copy(update={"preparation_id": "other"}),
                        idempotency_key="other-create")
    with pytest.raises(PreparationConflictError, match="PREPARATION_BUSY"):
        reopened.edit_source(legacy.preparation_id, source=source("Changed"),
                             expected_revision=legacy.revision, idempotency_key="legacy-edit")
    assert reopened.replay_create(
        collection_input(), idempotency_key="collection-create",
    ) == original
    assert create(reopened).model_dump_json() == legacy.model_dump_json()
    assert reopened.get(original.preparation_id) == pending


def test_collection_edit_revalidates_constructed_source_before_persisting(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    original = store.create(collection_input(), idempotency_key="create")
    forged = PreparationSource.model_construct(source_id="source-1", text=" ")
    with pytest.raises(ValueError):
        edit_collection(store, original, source=forged)
    assert store.get(original.preparation_id) == original
