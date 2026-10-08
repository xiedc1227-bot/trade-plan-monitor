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
        ).fetchone() == ("backtest-preparation-v1", 1)


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
            "version": "UPDATE backtest_preparation_metadata SET schema_version = 2",
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
