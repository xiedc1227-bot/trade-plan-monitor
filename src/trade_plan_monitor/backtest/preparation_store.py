"""Tagged SQLite preparation storage; no providers, live state or worker startup."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import MAX_EXTRACTION_ATTEMPTS
from trade_plan_monitor.backtest.models import StableIdentifier
from trade_plan_monitor.backtest.preparation_models import (
    PREPARATION_DOMAIN,
    PREPARATION_SCHEMA_VERSION,
    CollectionPreparationAttempt,
    CollectionPreparationCandidate,
    CollectionPreparationRecord,
    CollectionPreparationReview,
    CollectionPreparationWorkClaim,
    PlanCollectionPreparationInput,
    PreparationAttempt,
    PreparationCandidate,
    PreparationCandidateInput,
    PreparationItem,
    PreparationRecord,
    PreparationReview,
    PreparationSource,
    PreparationWorkClaim,
    SinglePlanPreparationInput,
    decode_preparation_record_json,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    CollectionPreparationReviewCommand,
    PreparationReviewCommand,
    PreparationSemanticError,
    correct_collection_candidate,
    prepare_frozen_collection,
    prepare_frozen_plan,
)
from trade_plan_monitor.backtest.storage_guard import reject_incompatible_database
from trade_plan_monitor.backtest.time import SHANGHAI

_IDENTIFIER = TypeAdapter(StableIdentifier)
_TABLES = {
    "backtest_preparation_metadata",
    "backtest_preparation",
    "backtest_preparation_idempotency",
}
_SCHEMA = (
    "CREATE TABLE backtest_preparation_metadata "
    "(singleton INTEGER PRIMARY KEY CHECK (singleton = 1), domain TEXT NOT NULL, "
    "schema_version INTEGER NOT NULL)",
    "CREATE TABLE backtest_preparation "
    "(preparation_id TEXT PRIMARY KEY, document_json TEXT NOT NULL)",
    "CREATE TABLE backtest_preparation_idempotency "
    "(idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, response_json TEXT NOT NULL)",
)


class PreparationConflictError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _request_hash(name, preparation_id, payload):
    return sha256(canonical_json({
        "domain": PREPARATION_DOMAIN, "operation": name,
        "preparation_id": preparation_id, "payload": payload,
    }).encode()).hexdigest()


class PreparationStore:
    """Persist private preparation documents using revision-checked transactions."""

    def __init__(
        self, database_path: str | Path, *, clock: Callable[[], datetime] | None = None,
        busy_timeout_ms: int = 5000,
    ) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be a string or Path")
        if isinstance(database_path, str) and not database_path.strip():
            raise ValueError("database_path must not be empty")
        if type(busy_timeout_ms) is not int or not 1 <= busy_timeout_ms <= 60000:
            raise ValueError("busy_timeout_ms must be between 1 and 60000")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._path = Path(database_path).expanduser().resolve()
        if self._path.exists() and not self._path.is_file():
            raise ValueError("database_path must point to a file")
        self._timeout = busy_timeout_ms / 1000
        self._clock = clock or (lambda: datetime.now(SHANGHAI))
        reject_incompatible_database(
            self._path, store_name="backtest preparation",
            forbidden_prefixes=("market_", "backtest_run", "backtest_job", "backtest_fill",
                                "backtest_detail", "backtest_plan_snapshot"),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )}
            if not tables:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO backtest_preparation_metadata VALUES (1, ?, ?)",
                    (PREPARATION_DOMAIN, PREPARATION_SCHEMA_VERSION),
                )
            elif tables != _TABLES or connection.execute(
                "SELECT singleton, domain, schema_version FROM backtest_preparation_metadata"
            ).fetchall() != [(1, PREPARATION_DOMAIN, PREPARATION_SCHEMA_VERSION)]:
                raise ValueError("database_path is not a supported tagged preparation store")
            connection.commit()

    @property
    def database_path(self) -> Path:
        return self._path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._path, timeout=self._timeout)) as connection:
            with connection:
                yield connection

    def get(self, preparation_id: str) -> PreparationRecord | CollectionPreparationRecord | None:
        preparation_id = _IDENTIFIER.validate_python(preparation_id)
        with self._connect() as connection:
            return self._read(connection, preparation_id)

    @staticmethod
    def _read(
        connection: sqlite3.Connection, preparation_id: str,
    ) -> PreparationRecord | CollectionPreparationRecord | None:
        row = connection.execute(
            "SELECT document_json FROM backtest_preparation WHERE preparation_id = ?",
            (preparation_id,),
        ).fetchone()
        if row is None:
            return None
        record = decode_preparation_record_json(row[0])
        if record.preparation_id != preparation_id:
            raise ValueError("stored preparation identity does not match its key")
        return record

    def _operation(self, name, preparation_id, payload, idempotency_key, change):
        preparation_id = _IDENTIFIER.validate_python(preparation_id)
        idempotency_key = _IDENTIFIER.validate_python(idempotency_key)
        request_hash = _request_hash(name, preparation_id, payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT request_hash, response_json FROM backtest_preparation_idempotency "
                "WHERE idempotency_key = ?", (idempotency_key,),
            ).fetchone()
            if previous is not None:
                if previous[0] != request_hash:
                    raise PreparationConflictError("IDEMPOTENCY_CONFLICT")
                return decode_preparation_record_json(previous[1])
            if connection.execute(
                "SELECT 1 FROM backtest_preparation WHERE preparation_id != ? "
                "AND json_extract(document_json, '$.status') IN "
                "('EXTRACTING', 'CANCEL_REQUESTED') LIMIT 1",
                (preparation_id,),
            ).fetchone() is not None:
                raise PreparationConflictError("PREPARATION_BUSY")
            existing = self._read(connection, preparation_id)
            if (isinstance(existing, CollectionPreparationRecord) and existing.workflow != "LEGACY"
                    and existing.status == "REVIEWED"):
                raise PreparationConflictError("REVIEWED_PLAN_IMMUTABLE")
            record = change(existing, self._clock())
            encoded = record.model_dump_json()
            connection.execute(
                "INSERT INTO backtest_preparation VALUES (?, ?) "
                "ON CONFLICT(preparation_id) DO UPDATE SET document_json = excluded.document_json",
                (preparation_id, encoded),
            )
            connection.execute(
                "INSERT INTO backtest_preparation_idempotency VALUES (?, ?, ?)",
                (idempotency_key, request_hash, encoded),
            )
            connection.commit()
            return record

    def create(
        self, command: SinglePlanPreparationInput | PlanCollectionPreparationInput,
        *, idempotency_key: str,
    ) -> PreparationRecord | CollectionPreparationRecord:
        if not isinstance(command, (SinglePlanPreparationInput, PlanCollectionPreparationInput)):
            raise TypeError("command must be a versioned preparation input")
        command = type(command).model_validate(command.model_dump(mode="python"))

        def change(previous, now):
            if previous is not None:
                raise PreparationConflictError("PREPARATION_EXISTS")
            sources = tuple(source.with_inferred_date() for source in command.sources)
            if isinstance(command, PlanCollectionPreparationInput):
                if (all(source.effective_trade_date is not None for source in sources)
                        and any(source.effective_trade_date is None for source in command.sources)):
                    sources = tuple(sorted(sources, key=lambda source: source.effective_trade_date))
                self.validate_collection_chronology(sources)
                return CollectionPreparationRecord(
                    preparation_id=command.preparation_id, revision=1,
                    items=tuple(PreparationItem(
                        source=source, status="DRAFT" if index == 0 else "WAITING",
                    ) for index, source in enumerate(sources)),
                    created_at=now, updated_at=now,
                )
            return PreparationRecord(
                preparation_id=command.preparation_id, revision=1,
                source=sources[0], source_revision=1, created_at=now, updated_at=now,
            )

        return self._operation(
            "CREATE", command.preparation_id, command, idempotency_key, change,
        )

    def edit_collection(
        self, preparation_id, *, expected_revision, idempotency_key,
        source: PreparationSource | None = None, source_order: tuple[str, ...] | None = None,
    ) -> CollectionPreparationRecord:
        """Invalidate only the affected suffix; frozen mutation receipts remain unchanged."""
        if source is None and source_order is None:
            raise ValueError("collection edit requires source or source_order")
        if source is not None:
            if not isinstance(source, PreparationSource):
                raise TypeError("source must be PreparationSource")
            source = PreparationSource.model_validate(source.model_dump(mode="python"))
        if source_order is not None:
            if type(source_order) is not tuple:
                raise ValueError("source_order must be an explicit tuple of existing IDs")
            source_order = tuple(_IDENTIFIER.validate_python(value) for value in source_order)

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if not isinstance(record, CollectionPreparationRecord):
                raise PreparationConflictError("PREPARATION_SCHEMA_CONFLICT")
            if record.workflow != "LEGACY" and (record.status == "REVIEWED"
                or source_order is not None or source is None
                or source.source_id != record.items[-1].source.source_id):
                raise PreparationConflictError("REVIEWED_PLAN_IMMUTABLE")
            if record.status in {"EXTRACTING", "CANCEL_REQUESTED"} or record.work_claim is not None:
                raise PreparationConflictError("PREPARATION_BUSY")
            if record.status == "CANCELLED":
                raise PreparationConflictError("PREPARATION_CANCELLED")
            original = tuple(item.source.source_id for item in record.items)
            order = original if source_order is None else source_order
            if len(order) != len(original) or set(order) != set(original):
                raise PreparationConflictError("SOURCE_ORDER_CONFLICT")
            if source is not None and source.source_id not in original:
                raise PreparationConflictError("SOURCE_ID_CONFLICT")
            by_id = {item.source.source_id: item for item in record.items}
            resolved = source.with_inferred_date() if source is not None else None
            changed = [index for index, identity in enumerate(order) if identity != original[index]]
            if resolved is not None and resolved != by_id[resolved.source_id].source:
                changed.append(order.index(source.source_id))
            if not changed:
                return record
            first, items = min(changed), []
            for index, identity in enumerate(order):
                item = by_id[identity]
                if index >= first:
                    replacement = (
                        resolved if resolved is not None and resolved.source_id == identity
                        else item.source
                    )
                    ready = index == 0 or (index == first and items[-1].candidate is not None
                                           and items[-1].candidate.policy_ready)
                    item = item.model_copy(update={
                        "source": replacement,
                        "source_revision": item.source_revision + int(replacement != item.source),
                        "candidate_revision": item.candidate_revision + 1,
                        "candidate": None, "base_hash": None, "attempts": (),
                        "status": "DRAFT" if ready else "WAITING",
                    })
                items.append(item)
            self.validate_collection_chronology(tuple(item.source for item in items))
            return self._updated(
                record, now, items=tuple(items), status="DRAFT", review=None,
                review_revision=record.review_revision + 1,
            )

        return self._operation("EDIT_COLLECTION", preparation_id, {
            "expected_revision": expected_revision, "source": source, "source_order": source_order,
        }, idempotency_key, change)

    @staticmethod
    def _require_revision(record, expected_revision):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        if record is None:
            raise PreparationConflictError("PREPARATION_NOT_FOUND")
        if record.revision != expected_revision:
            raise PreparationConflictError("REVISION_CONFLICT")
        return record

    def replay_create(self, command, *, idempotency_key, operation="CREATE"):
        """Read the original create receipt without changing the current source."""
        key = _IDENTIFIER.validate_python(idempotency_key)
        expected = _request_hash(operation, command.preparation_id, command)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_hash, response_json FROM backtest_preparation_idempotency "
                "WHERE idempotency_key = ?", (key,),
            ).fetchone()
        if row is None:
            return None
        if row[0] != expected:
            raise PreparationConflictError("IDEMPOTENCY_CONFLICT")
        return decode_preparation_record_json(row[1])

    @staticmethod
    def _updated(record, now, **changes):
        return record.model_copy(update={
            "revision": record.revision + 1, "updated_at": now, **changes,
        })

    def edit_source(
        self, preparation_id: str, *, source: PreparationSource,
        expected_revision: int, idempotency_key: str,
    ) -> PreparationRecord:
        if not isinstance(source, PreparationSource):
            raise TypeError("source must be PreparationSource")
        source = PreparationSource.model_validate(source.model_dump(mode="python"))

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if source.source_id != record.source.source_id:
                raise PreparationConflictError("SOURCE_ID_CONFLICT")
            resolved = source.with_inferred_date()
            if resolved == record.source:
                return record
            pending = record.status in {"EXTRACTING", "CANCEL_REQUESTED"}
            attempts = () if not pending else (record.attempts[-1].model_copy(update={
                "status": "CANCEL_REQUESTED",
            }),)
            return self._updated(
                record, now, source=resolved, source_revision=record.source_revision + 1,
                status="CANCEL_REQUESTED" if pending else "DRAFT",
                attempts=attempts, candidate=None, review=None, source_edit_pending=pending,
                candidate_revision=record.candidate_revision + 1,
                review_revision=record.review_revision + 1,
            )

        return self._operation("EDIT", preparation_id, {
            "source": source, "expected_revision": expected_revision,
        }, idempotency_key, change)

    def replay_mutation(
        self, operation, preparation_id, *, expected_revision, idempotency_key, source=None,
        source_order=None,
    ):
        """Return an original edit/cancel receipt before consulting new-work admission."""
        if operation not in {"EDIT", "CANCEL", "EDIT_COLLECTION"}:
            raise ValueError("mutation must be EDIT, EDIT_COLLECTION or CANCEL")
        identity = _IDENTIFIER.validate_python(preparation_id)
        key = _IDENTIFIER.validate_python(idempotency_key)
        payload = {"expected_revision": expected_revision}
        if operation == "EDIT":
            if not isinstance(source, PreparationSource):
                raise TypeError("source must be PreparationSource")
            payload["source"] = PreparationSource.model_validate(source.model_dump(mode="python"))
        elif operation == "EDIT_COLLECTION":
            if source is None and source_order is None:
                raise ValueError("collection edit requires source or source_order")
            if source is not None:
                source = PreparationSource.model_validate(source.model_dump(mode="python"))
            if source_order is not None:
                if type(source_order) is not tuple:
                    raise ValueError("source_order must be an explicit tuple")
                source_order = tuple(_IDENTIFIER.validate_python(item) for item in source_order)
            payload.update(source=source, source_order=source_order)
        expected = _request_hash(operation, identity, payload)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_hash, response_json FROM backtest_preparation_idempotency "
                "WHERE idempotency_key = ?", (key,),
            ).fetchone()
        if row is None:
            return None
        if row[0] != expected:
            raise PreparationConflictError("IDEMPOTENCY_CONFLICT")
        return decode_preparation_record_json(row[1])

    def start_attempt(
        self, preparation_id: str, *, expected_revision: int, idempotency_key: str,
        work_claim: PreparationWorkClaim | CollectionPreparationWorkClaim | None = None,
    ) -> PreparationRecord:
        """Record explicit intent only; this method never invokes or resumes AI."""
        if work_claim is not None:
            claim_type = (CollectionPreparationWorkClaim
                          if isinstance(work_claim, CollectionPreparationWorkClaim)
                          else PreparationWorkClaim)
            work_claim = claim_type.model_validate(work_claim.model_dump(mode="python"))

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if isinstance(record, CollectionPreparationRecord):
                return self._start_collection_attempt(record, work_claim, now)
            if isinstance(work_claim, CollectionPreparationWorkClaim):
                raise PreparationConflictError("PREPARATION_SCHEMA_CONFLICT")
            if record.work_claim is not None and (
                work_claim is None or record.work_claim.phase != "ENDED"
                or (record.work_claim.admission_key, record.work_claim.intent_hash,
                    record.work_claim.claimed_at, record.work_claim.owner_id) != (
                    work_claim.admission_key, work_claim.intent_hash,
                    work_claim.claimed_at, work_claim.owner_id)
            ):
                raise PreparationConflictError("WORKER_CLAIM_PENDING")
            if work_claim is not None and (
                work_claim.phase != "READY" or work_claim.source_revision != record.source_revision
                or work_claim.source_hash != record.source.binding_hash
            ):
                raise PreparationConflictError("STALE_WORKER")
            if record.status in {"EXTRACTING", "CANCEL_REQUESTED"}:
                raise PreparationConflictError("PREPARATION_BUSY")
            if record.status == "CANCELLED":
                raise PreparationConflictError("PREPARATION_CANCELLED")
            if record.status == "FAILED" and not record.attempts[-1].retryable:
                raise PreparationConflictError("RETRY_NOT_ALLOWED")
            if len(record.attempts) >= MAX_EXTRACTION_ATTEMPTS:
                raise PreparationConflictError("ATTEMPTS_EXHAUSTED")
            attempt = PreparationAttempt(
                attempt_id=work_claim.generation if work_claim else str(uuid4()),
                source_revision=record.source_revision,
                source_hash=record.source.binding_hash, status="RUNNING", started_at=now,
            )
            return self._updated(
                record, now, status="EXTRACTING", attempts=(*record.attempts, attempt),
                candidate=None, review=None, candidate_revision=record.candidate_revision + 1,
                review_revision=record.review_revision + 1,
                work_claim=work_claim,
            )

        return self._operation("START_ATTEMPT", preparation_id, {
            "expected_revision": expected_revision,
        }, idempotency_key, change)

    @staticmethod
    def validate_collection_chronology(sources):
        for field in ("authored_at", "available_at", "effective_trade_date"):
            known = [getattr(source, field) for source in sources
                     if getattr(source, field) is not None]
            if any(left > right for left, right in zip(known, known[1:], strict=False)):
                raise PreparationConflictError("SOURCE_CHRONOLOGY_CONFLICT")

    @staticmethod
    def next_collection_item(record):
        """Earliest unresolved item only; no caller can skip a failed predecessor."""
        for index, item in enumerate(record.items):
            if item.candidate is None or not item.candidate.policy_ready:
                return index, item
        raise PreparationConflictError("PREPARATION_COMPLETE")

    def _start_collection_attempt(self, record, claim, now):
        self.validate_collection_chronology(tuple(item.source for item in record.items))
        if not isinstance(claim, CollectionPreparationWorkClaim):
            raise PreparationConflictError("WORKER_CLAIM_REQUIRED")
        if record.work_claim is not None and (
            record.work_claim.phase != "ENDED"
            or (record.work_claim.admission_key, record.work_claim.intent_hash,
                record.work_claim.claimed_at, record.work_claim.owner_id) != (
                claim.admission_key, claim.intent_hash, claim.claimed_at, claim.owner_id)
        ):
            raise PreparationConflictError("WORKER_CLAIM_PENDING")
        if record.status in {"EXTRACTING", "CANCEL_REQUESTED"}:
            raise PreparationConflictError("PREPARATION_BUSY")
        if record.status == "CANCELLED":
            raise PreparationConflictError("PREPARATION_CANCELLED")
        index, item = self.next_collection_item(record)
        base = None if index == 0 or item.independent else record.items[index - 1].candidate
        expected_base = base.candidate_hash if base else None
        if index and not item.independent and (base is None or not base.policy_ready):
            raise PreparationConflictError("PREDECESSOR_UNRESOLVED")
        if claim.phase != "READY" or (
            claim.source_id, claim.source_revision, claim.source_hash, claim.base_hash
        ) != (item.source.source_id, item.source_revision, item.source.binding_hash, expected_base):
            raise PreparationConflictError("STALE_WORKER")
        if item.status == "FAILED" and not item.attempts[-1].retryable:
            raise PreparationConflictError("RETRY_NOT_ALLOWED")
        if len(item.attempts) >= MAX_EXTRACTION_ATTEMPTS:
            raise PreparationConflictError("ATTEMPTS_EXHAUSTED")
        attempt = CollectionPreparationAttempt(
            attempt_id=claim.generation, source_revision=item.source_revision,
            source_hash=item.source.binding_hash, base_hash=expected_base,
            status="RUNNING", started_at=now,
        )
        items = list(record.items)
        items[index] = item.model_copy(update={
            "base_hash": expected_base, "status": "EXTRACTING", "candidate": None,
            "attempts": (*item.attempts, attempt),
            "candidate_revision": item.candidate_revision + 1,
        })
        return self._updated(
            record, now, items=tuple(items), status="EXTRACTING", work_claim=claim,
            review=None, review_revision=record.review_revision + 1,
        )

    @staticmethod
    def _collection_active_item(record, attempt_id):
        claim = record.work_claim
        if claim is None or claim.generation != attempt_id:
            raise PreparationConflictError("STALE_WORKER")
        for index, item in enumerate(record.items):
            if item.source.source_id == claim.source_id:
                if not item.attempts or item.attempts[-1].attempt_id != attempt_id:
                    break
                return index, item
        raise PreparationConflictError("STALE_ATTEMPT")

    def _finish_collection_attempt(self, record, now, attempt_id, candidate, error_code, retryable,
                                   repair_feedback=(), repair_context_json=None):
        index, item = self._collection_active_item(record, attempt_id)
        if record.status != "EXTRACTING" or item.status != "EXTRACTING":
            raise PreparationConflictError("STALE_ATTEMPT")
        attempt = item.attempts[-1].model_copy(update={
            "status": "SUCCEEDED" if candidate is not None else "FAILED", "finished_at": now,
            "error_code": error_code, "retryable": retryable, "repair_feedback": repair_feedback,
            "repair_context_json": repair_context_json,
        })
        bound = None if candidate is None else CollectionPreparationCandidate(
            **candidate.model_dump(), source_revision=item.source_revision,
            source_hash=item.source.binding_hash, base_hash=item.base_hash,
        )
        items = list(record.items)
        items[index] = item.model_copy(update={
            "status": "CANDIDATE" if bound is not None else "FAILED",
            "candidate": bound, "attempts": (*item.attempts[:-1], attempt),
            "candidate_revision": item.candidate_revision + int(bound is not None),
        })
        if bound is not None and bound.validation == "VALID" and index + 1 < len(items):
            items[index + 1] = items[index + 1].model_copy(update={"status": "DRAFT"})
        complete = all(item.candidate is not None for item in items)
        return self._updated(
            record, now, items=tuple(items),
            status="FAILED" if bound is None else "CANDIDATE" if complete else "DRAFT",
            work_claim=record.work_claim.model_copy(update={"phase": "ENDED"}),
        )

    def replay_start_attempt(self, preparation_id, *, expected_revision, idempotency_key):
        """Read a matching original receipt; never restart the recorded attempt."""
        preparation_id = _IDENTIFIER.validate_python(preparation_id)
        idempotency_key = _IDENTIFIER.validate_python(idempotency_key)
        expected = _request_hash("START_ATTEMPT", preparation_id, {
            "expected_revision": expected_revision,
        })
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_hash, response_json FROM backtest_preparation_idempotency "
                "WHERE idempotency_key = ?", (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        if row[0] != expected:
            raise PreparationConflictError("IDEMPOTENCY_CONFLICT")
        return decode_preparation_record_json(row[1])

    @staticmethod
    def _owned_claim(record, generation, owner_id):
        claim = record.work_claim
        if claim is None or (claim.generation, claim.owner_id) != (generation, owner_id):
            raise PreparationConflictError("STALE_WORKER")
        return claim

    def _work_phase(self, preparation_id, generation, owner_id, expected_revision, phase):
        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            claim = self._owned_claim(record, generation, owner_id)
            if claim.phase == "ENDED" or record.status not in {"EXTRACTING", "CANCEL_REQUESTED"}:
                raise PreparationConflictError("STALE_WORKER")
            if phase == "CALLING" and (record.status != "EXTRACTING" or claim.phase != "READY"):
                raise PreparationConflictError("STALE_WORKER")
            return self._updated(record, now, work_claim=claim.model_copy(update={"phase": phase}))

        return self._operation("WORK_PHASE", preparation_id, {
            "generation": generation, "owner_id": owner_id,
            "expected_revision": expected_revision, "phase": phase,
        }, str(uuid4()), change)  # A progress transition must never replay old call authority.

    def begin_call(self, preparation_id, *, generation, owner_id, expected_revision):
        return self._work_phase(preparation_id, generation, owner_id, expected_revision, "CALLING")

    def mark_unknown(self, preparation_id, *, generation, owner_id, expected_revision):
        return self._work_phase(preparation_id, generation, owner_id, expected_revision, "UNKNOWN")

    def clear_work_claim(self, preparation_id, *, generation, expected_revision):
        """Clear only a durably ended claim after its global reservation was released."""
        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if record.work_claim is None or record.work_claim.generation != generation:
                raise PreparationConflictError("STALE_WORKER")
            if record.work_claim.phase != "ENDED":
                raise PreparationConflictError("WORKER_CLAIM_PENDING")
            return self._updated(record, now, work_claim=None)

        return self._operation("CLEAR_WORK", preparation_id, {
            "generation": generation, "expected_revision": expected_revision,
        }, f"{generation}.clear", change)

    def recover_unknown(
        self, preparation_id, *, generation, expected_revision, confirmed_ended, idempotency_key,
    ):
        """Explicit recovery only; the caller must prove/confirm prior physical work ended."""
        if type(confirmed_ended) is not bool or not confirmed_ended:
            raise PreparationConflictError("RECOVERY_CONFIRMATION_REQUIRED")

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            claim = record.work_claim
            if claim is None or claim.generation != generation or claim.phase == "ENDED":
                raise PreparationConflictError("STALE_WORKER")
            if record.status == "CANCEL_REQUESTED":
                return self._ended_cancellation(record, now)
            if record.status != "EXTRACTING":
                raise PreparationConflictError("STALE_WORKER")
            if isinstance(record, CollectionPreparationRecord):
                return self._finish_collection_attempt(
                    record, now, claim.generation, None, "UNKNOWN_PROVIDER_OUTCOME", True,
                )
            ended = record.attempts[-1].model_copy(update={
                "status": "FAILED", "finished_at": now,
                "error_code": "UNKNOWN_PROVIDER_OUTCOME", "retryable": True,
            })
            return self._updated(record, now, status="FAILED",
                                 attempts=(*record.attempts[:-1], ended),
                                 work_claim=claim.model_copy(update={"phase": "ENDED"}))

        return self._operation("RECOVER_WORK", preparation_id, {
            "generation": generation, "expected_revision": expected_revision,
            "confirmed_ended": confirmed_ended,
        }, idempotency_key, change)

    def finish_attempt(
        self, preparation_id: str, *, attempt_id: str, expected_revision: int, idempotency_key: str,
        candidate: PreparationCandidateInput | None = None, error_code: str | None = None,
        retryable: bool = False,
        worker_owner_id: str | None = None,
        repair_feedback: tuple[str, ...] = (),
        repair_context_json: str | None = None,
    ) -> PreparationRecord:
        if candidate is not None and not isinstance(candidate, PreparationCandidateInput):
            raise TypeError("candidate must be PreparationCandidateInput")
        if (candidate is None) == (error_code is None) or type(retryable) is not bool:
            raise ValueError("finish requires exactly one candidate or classified error")
        if candidate is not None and retryable:
            raise ValueError("successful candidate cannot be retryable")
        attempt_id = _IDENTIFIER.validate_python(attempt_id)

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if record.work_claim is not None:
                claim = self._owned_claim(record, attempt_id, worker_owner_id)
                if claim.phase != "CALLING":
                    raise PreparationConflictError("STALE_WORKER")
            if isinstance(record, CollectionPreparationRecord):
                return self._finish_collection_attempt(
                    record, now, attempt_id, candidate, error_code, retryable, repair_feedback,
                    repair_context_json,
                )
            if record.status != "EXTRACTING" or record.attempts[-1].attempt_id != attempt_id:
                raise PreparationConflictError("STALE_ATTEMPT")
            attempt = record.attempts[-1].model_copy(update={
                "status": "SUCCEEDED" if candidate is not None else "FAILED",
                "finished_at": now, "error_code": error_code, "retryable": retryable,
                "repair_feedback": repair_feedback,
                "repair_context_json": repair_context_json,
            })
            bound = None if candidate is None else PreparationCandidate(
                **candidate.model_dump(), source_revision=record.source_revision,
                source_hash=record.source.binding_hash,
            )
            return self._updated(
                record, now, status="CANDIDATE" if bound is not None else "FAILED",
                attempts=(*record.attempts[:-1], attempt), candidate=bound,
                candidate_revision=record.candidate_revision + int(bound is not None),
                work_claim=(record.work_claim.model_copy(update={"phase": "ENDED"})
                            if record.work_claim else None),
            )

        payload = {
            "attempt_id": attempt_id, "expected_revision": expected_revision,
            "candidate": candidate, "error_code": error_code, "retryable": retryable,
        }
        if worker_owner_id is not None:
            payload["worker_owner_id"] = worker_owner_id
        if repair_feedback:
            payload["repair_feedback"] = repair_feedback
        if repair_context_json is not None:
            payload["repair_context_json"] = repair_context_json
        return self._operation("FINISH_ATTEMPT", preparation_id, payload, idempotency_key, change)

    def cancel(
        self, preparation_id: str, *, expected_revision: int, idempotency_key: str,
    ) -> PreparationRecord:
        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if isinstance(record, CollectionPreparationRecord):
                if record.status in {"CANCEL_REQUESTED", "CANCELLED"}:
                    return record
                items = []
                for item in record.items:
                    if item.status == "EXTRACTING":
                        pending = item.attempts[-1].model_copy(update={
                            "status": "CANCEL_REQUESTED",
                        })
                        item = item.model_copy(update={
                            "status": "CANCEL_REQUESTED",
                            "attempts": (*item.attempts[:-1], pending),
                        })
                    elif not item.attempts:
                        item = item.model_copy(update={"status": "CANCELLED"})
                    items.append(item)
                return self._updated(
                    record, now, items=tuple(items), review=None,
                    review_revision=record.review_revision + 1,
                    status="CANCEL_REQUESTED" if record.status == "EXTRACTING" else "CANCELLED",
                )
            if record.status == "CANCEL_REQUESTED":
                return (
                    self._updated(record, now, source_edit_pending=False)
                    if record.source_edit_pending else record
                )
            attempts = record.attempts
            if record.status == "EXTRACTING":
                attempts = (*attempts[:-1], attempts[-1].model_copy(update={
                    "status": "CANCEL_REQUESTED",
                }))
            return self._updated(
                record, now,
                status="CANCEL_REQUESTED" if record.status == "EXTRACTING" else "CANCELLED",
                attempts=attempts, candidate=None, review=None,
                candidate_revision=record.candidate_revision + 1,
                review_revision=record.review_revision + 1,
            )

        return self._operation("CANCEL", preparation_id, {
            "expected_revision": expected_revision,
        }, idempotency_key, change)

    def acknowledge_cancellation(
        self, preparation_id: str, *, attempt_id: str, expected_revision: int, idempotency_key: str,
        worker_owner_id: str | None = None,
    ) -> PreparationRecord:
        """Record caller-confirmed end; ML-T10 must first drain its actual worker."""
        attempt_id = _IDENTIFIER.validate_python(attempt_id)

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if record.work_claim is not None:
                self._owned_claim(record, attempt_id, worker_owner_id)
            if isinstance(record, CollectionPreparationRecord):
                _, item = self._collection_active_item(record, attempt_id)
                attempts = item.attempts
            else:
                attempts = record.attempts
            if record.status != "CANCEL_REQUESTED" or attempts[-1].attempt_id != attempt_id:
                raise PreparationConflictError("STALE_ATTEMPT")
            return self._ended_cancellation(record, now)

        payload = {
            "attempt_id": attempt_id, "expected_revision": expected_revision,
        }
        if worker_owner_id is not None:
            payload["worker_owner_id"] = worker_owner_id
        return self._operation("ACK_CANCEL", preparation_id, payload, idempotency_key, change)

    def _ended_cancellation(self, record, now):
        if isinstance(record, CollectionPreparationRecord):
            index, item = self._collection_active_item(record, record.work_claim.generation)
            ended = item.attempts[-1].model_copy(update={
                "status": "CANCELLED", "finished_at": now,
            })
            item = item.model_copy(update={
                "status": "CANCELLED", "attempts": (*item.attempts[:-1], ended),
            })
            return self._updated(
                record, now, status="CANCELLED",
                items=(*record.items[:index], item, *record.items[index + 1:]),
                work_claim=record.work_claim.model_copy(update={"phase": "ENDED"}),
            )
        superseded = record.attempts[-1].source_revision != record.source_revision
        ended = record.attempts[-1].model_copy(update={"status": "CANCELLED", "finished_at": now})
        return self._updated(
            record, now, status="DRAFT" if record.source_edit_pending else "CANCELLED",
            attempts=() if superseded else (*record.attempts[:-1], ended),
            source_edit_pending=False,
            work_claim=(record.work_claim.model_copy(update={"phase": "ENDED"})
                        if record.work_claim else None),
        )

    def record_review(
        self, preparation_id: str, *, expected_revision: int, expected_source_revision: int,
        expected_candidate_revision: int, candidate_hash: str, evidence_hash: str,
        confirmed: bool, idempotency_key: str,
    ) -> PreparationRecord:
        """Persist an explicit declaration; semantic review/freeze belongs to ML-T11."""

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            declaration = PreparationReview(
                source_revision=expected_source_revision,
                candidate_revision=expected_candidate_revision,
                candidate_hash=candidate_hash, evidence_hash=evidence_hash,
                confirmed=confirmed, reviewed_at=now,
            )
            if record.candidate is None or record.candidate.validation != "VALID":
                raise PreparationConflictError("CANDIDATE_NOT_VALID")
            if (
                declaration.source_revision != record.source_revision
                or declaration.candidate_revision != record.candidate_revision
                or declaration.candidate_hash != record.candidate.candidate_hash
                or declaration.evidence_hash != record.candidate.evidence_hash
            ):
                raise PreparationConflictError("REVIEW_BINDING_CONFLICT")
            return self._updated(
                record, now, status="REVIEWED", review=declaration,
                review_revision=record.review_revision + 1,
            )

        return self._operation("REVIEW", preparation_id, {
            "expected_revision": expected_revision, "source_revision": expected_source_revision,
            "candidate_revision": expected_candidate_revision, "candidate_hash": candidate_hash,
            "evidence_hash": evidence_hash, "confirmed": confirmed,
        }, idempotency_key, change)

    def review_and_freeze(
        self, preparation_id: str, *, command: PreparationReviewCommand, idempotency_key: str,
    ) -> PreparationRecord:
        """One atomic human mutation; legacy review declarations do not freeze semantic input."""
        if isinstance(command, CollectionPreparationReviewCommand):
            return self._review_collection(preparation_id, command, idempotency_key)
        if not isinstance(command, PreparationReviewCommand):
            raise TypeError("command must be PreparationReviewCommand")
        command = PreparationReviewCommand.model_validate(command.model_dump(mode="python"))

        def change(previous, now):
            record = self._require_revision(previous, command.expected_revision)
            try:
                manifest = prepare_frozen_plan(record, command, now)
            except PreparationSemanticError as error:
                raise PreparationConflictError(error.code) from None
            except ValueError:
                raise PreparationConflictError("REVIEW_SEMANTIC_CONFLICT") from None
            candidate = PreparationCandidate(
                payload_json=canonical_json(manifest), validation="VALID", issues=(),
                evidence_hash=manifest.version.evidence_hash,
                source_revision=record.source_revision, source_hash=record.source.binding_hash,
            )
            declaration = PreparationReview(
                source_revision=record.source_revision,
                candidate_revision=record.candidate_revision + 1,
                candidate_hash=candidate.candidate_hash, evidence_hash=candidate.evidence_hash,
                confirmed=command.confirmed, reviewed_at=now,
            )
            return self._updated(
                record, now, status="REVIEWED", candidate=candidate, review=declaration,
                candidate_revision=record.candidate_revision + 1,
                review_revision=record.review_revision + 1,
            )

        return self._operation(
            "REVIEW_AND_FREEZE", preparation_id, command, idempotency_key, change,
        )

    def correct_collection_item(self, preparation_id, *, command, idempotency_key):
        if not isinstance(command, CollectionItemCorrectionCommand):
            raise TypeError("command must be CollectionItemCorrectionCommand")
        command = CollectionItemCorrectionCommand.model_validate_json(command.model_dump_json())

        def change(previous, now):
            record = self._require_revision(previous, command.expected_revision)
            if not isinstance(record, CollectionPreparationRecord):
                raise PreparationConflictError("REVIEW_SEMANTIC_CONFLICT")
            if (record.workflow == "SINGLE"
                    and command.binding.source_id != record.items[-1].source.source_id):
                raise PreparationConflictError("REVIEWED_PLAN_IMMUTABLE")
            try:
                index, reviewed = correct_collection_candidate(record, command)
            except PreparationSemanticError as error:
                raise PreparationConflictError(error.code) from None
            except ValueError:
                raise PreparationConflictError("REVIEW_SEMANTIC_CONFLICT") from None
            item = record.items[index]
            candidate = CollectionPreparationCandidate(
                **reviewed.to_preparation_candidate().model_dump(),
                source_revision=item.source_revision, source_hash=item.source.binding_hash,
                base_hash=item.base_hash,
            )
            items = list(record.items[:index])
            items.append(item.model_copy(update={
                "candidate": candidate, "candidate_revision": item.candidate_revision + 1,
                "status": "CANDIDATE",
            }))
            for offset, later in enumerate(record.items[index + 1:], start=index + 1):
                items.append(PreparationItem(
                    source=later.source, source_revision=later.source_revision,
                    candidate_revision=later.candidate_revision + 1,
                    status="DRAFT" if offset == index + 1 else "WAITING",
                ))
            return self._updated(
                record, now, items=tuple(items), review=None,
                review_revision=record.review_revision + 1,
                status="CANDIDATE" if index == len(record.items) - 1 else "DRAFT",
            )

        return self._operation("CORRECT_ITEM", preparation_id, command, idempotency_key, change)

    def _review_collection(self, preparation_id, command, idempotency_key):
        command = CollectionPreparationReviewCommand.model_validate_json(command.model_dump_json())

        def change(previous, now):
            record = self._require_revision(previous, command.expected_revision)
            if not isinstance(record, CollectionPreparationRecord):
                raise PreparationConflictError("REVIEW_SEMANTIC_CONFLICT")
            effective_command = command
            parent = None
            if record.reviewed_base is not None:
                from trade_plan_monitor.backtest.plan_library import reviewed_entry
                parent_record, parent = reviewed_entry(self, record.reviewed_base)
                if (record.items[:-1] != parent_record.items
                        or record.base_account != parent.account):
                    raise PreparationConflictError("REVIEWED_BASE_CHANGED")
                if command.account is not None and command.account != parent.account:
                    raise PreparationConflictError("INITIAL_ACCOUNT_IMMUTABLE")
                effective_command = command.model_copy(update={"account": parent.account})
            try:
                manifest = prepare_frozen_collection(
                    record, effective_command, now, reviewed_parent=parent,
                )
            except PreparationSemanticError as error:
                raise PreparationConflictError(error.code) from None
            except ValueError:
                raise PreparationConflictError("REVIEW_SEMANTIC_CONFLICT") from None
            return self._updated(
                record, now, status="REVIEWED", review_revision=record.review_revision + 1,
                review=CollectionPreparationReview(
                    items=command.items, confirmed=command.confirmed, reviewed_at=now,
                    manifest_json=canonical_json(manifest),
                ),
            )

        return self._operation(
            "REVIEW_AND_FREEZE", preparation_id, command, idempotency_key, change,
        )

    def replay_review(self, preparation_id, *, command, idempotency_key):
        """Read the immutable original review receipt after later edits or restarts."""
        preparation_id = _IDENTIFIER.validate_python(preparation_id)
        idempotency_key = _IDENTIFIER.validate_python(idempotency_key)
        operation = ("CORRECT_ITEM" if isinstance(command, CollectionItemCorrectionCommand)
                     else "REVIEW_AND_FREEZE")
        expected = _request_hash(operation, preparation_id, command)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_hash, response_json FROM backtest_preparation_idempotency "
                "WHERE idempotency_key = ?", (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        if row[0] != expected:
            raise PreparationConflictError("IDEMPOTENCY_CONFLICT")
        return decode_preparation_record_json(row[1])
