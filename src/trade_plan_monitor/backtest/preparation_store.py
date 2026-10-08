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
    PreparationAttempt,
    PreparationCandidate,
    PreparationCandidateInput,
    PreparationRecord,
    PreparationReview,
    PreparationSource,
    SinglePlanPreparationInput,
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

    def get(self, preparation_id: str) -> PreparationRecord | None:
        preparation_id = _IDENTIFIER.validate_python(preparation_id)
        with self._connect() as connection:
            return self._read(connection, preparation_id)

    @staticmethod
    def _read(connection: sqlite3.Connection, preparation_id: str) -> PreparationRecord | None:
        row = connection.execute(
            "SELECT document_json FROM backtest_preparation WHERE preparation_id = ?",
            (preparation_id,),
        ).fetchone()
        if row is None:
            return None
        record = PreparationRecord.model_validate_json(row[0])
        if record.preparation_id != preparation_id:
            raise ValueError("stored preparation identity does not match its key")
        return record

    def _operation(self, name, preparation_id, payload, idempotency_key, change):
        preparation_id = _IDENTIFIER.validate_python(preparation_id)
        idempotency_key = _IDENTIFIER.validate_python(idempotency_key)
        request_hash = sha256(canonical_json({
            "domain": PREPARATION_DOMAIN, "operation": name,
            "preparation_id": preparation_id, "payload": payload,
        }).encode()).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT request_hash, response_json FROM backtest_preparation_idempotency "
                "WHERE idempotency_key = ?", (idempotency_key,),
            ).fetchone()
            if previous is not None:
                if previous[0] != request_hash:
                    raise PreparationConflictError("IDEMPOTENCY_CONFLICT")
                return PreparationRecord.model_validate_json(previous[1])
            if connection.execute(
                "SELECT 1 FROM backtest_preparation WHERE preparation_id != ? "
                "AND json_extract(document_json, '$.status') IN "
                "('EXTRACTING', 'CANCEL_REQUESTED') LIMIT 1",
                (preparation_id,),
            ).fetchone() is not None:
                raise PreparationConflictError("PREPARATION_BUSY")
            record = change(self._read(connection, preparation_id), self._clock())
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
        self, command: SinglePlanPreparationInput, *, idempotency_key: str,
    ) -> PreparationRecord:
        if not isinstance(command, SinglePlanPreparationInput):
            raise TypeError("command must be SinglePlanPreparationInput")
        command = SinglePlanPreparationInput.model_validate(command.model_dump(mode="python"))

        def change(previous, now):
            if previous is not None:
                raise PreparationConflictError("PREPARATION_EXISTS")
            return PreparationRecord(
                preparation_id=command.preparation_id, revision=1,
                source=command.sources[0], source_revision=1, created_at=now, updated_at=now,
            )

        return self._operation(
            "CREATE", command.preparation_id, command, idempotency_key, change,
        )

    @staticmethod
    def _require_revision(record, expected_revision):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        if record is None:
            raise PreparationConflictError("PREPARATION_NOT_FOUND")
        if record.revision != expected_revision:
            raise PreparationConflictError("REVISION_CONFLICT")
        return record

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
            if source == record.source:
                return record
            pending = record.status in {"EXTRACTING", "CANCEL_REQUESTED"}
            attempts = () if not pending else (record.attempts[-1].model_copy(update={
                "status": "CANCEL_REQUESTED",
            }),)
            return self._updated(
                record, now, source=source, source_revision=record.source_revision + 1,
                status="CANCEL_REQUESTED" if pending else "DRAFT",
                attempts=attempts, candidate=None, review=None, source_edit_pending=pending,
                candidate_revision=record.candidate_revision + 1,
                review_revision=record.review_revision + 1,
            )

        return self._operation("EDIT", preparation_id, {
            "source": source, "expected_revision": expected_revision,
        }, idempotency_key, change)

    def start_attempt(
        self, preparation_id: str, *, expected_revision: int, idempotency_key: str,
    ) -> PreparationRecord:
        """Record explicit intent only; this method never invokes or resumes AI."""

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if record.status in {"EXTRACTING", "CANCEL_REQUESTED"}:
                raise PreparationConflictError("PREPARATION_BUSY")
            if record.status == "CANCELLED":
                raise PreparationConflictError("PREPARATION_CANCELLED")
            if record.status == "FAILED" and not record.attempts[-1].retryable:
                raise PreparationConflictError("RETRY_NOT_ALLOWED")
            if len(record.attempts) >= MAX_EXTRACTION_ATTEMPTS:
                raise PreparationConflictError("ATTEMPTS_EXHAUSTED")
            attempt = PreparationAttempt(
                attempt_id=str(uuid4()), source_revision=record.source_revision,
                source_hash=record.source.binding_hash, status="RUNNING", started_at=now,
            )
            return self._updated(
                record, now, status="EXTRACTING", attempts=(*record.attempts, attempt),
                candidate=None, review=None, candidate_revision=record.candidate_revision + 1,
                review_revision=record.review_revision + 1,
            )

        return self._operation("START_ATTEMPT", preparation_id, {
            "expected_revision": expected_revision,
        }, idempotency_key, change)

    def finish_attempt(
        self, preparation_id: str, *, attempt_id: str, expected_revision: int, idempotency_key: str,
        candidate: PreparationCandidateInput | None = None, error_code: str | None = None,
        retryable: bool = False,
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
            if record.status != "EXTRACTING" or record.attempts[-1].attempt_id != attempt_id:
                raise PreparationConflictError("STALE_ATTEMPT")
            attempt = record.attempts[-1].model_copy(update={
                "status": "SUCCEEDED" if candidate is not None else "FAILED",
                "finished_at": now, "error_code": error_code, "retryable": retryable,
            })
            bound = None if candidate is None else PreparationCandidate(
                **candidate.model_dump(), source_revision=record.source_revision,
                source_hash=record.source.binding_hash,
            )
            return self._updated(
                record, now, status="CANDIDATE" if bound is not None else "FAILED",
                attempts=(*record.attempts[:-1], attempt), candidate=bound,
                candidate_revision=record.candidate_revision + int(bound is not None),
            )

        return self._operation("FINISH_ATTEMPT", preparation_id, {
            "attempt_id": attempt_id, "expected_revision": expected_revision,
            "candidate": candidate, "error_code": error_code, "retryable": retryable,
        }, idempotency_key, change)

    def cancel(
        self, preparation_id: str, *, expected_revision: int, idempotency_key: str,
    ) -> PreparationRecord:
        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
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
    ) -> PreparationRecord:
        """Record caller-confirmed end; ML-T10 must first drain its actual worker."""
        attempt_id = _IDENTIFIER.validate_python(attempt_id)

        def change(previous, now):
            record = self._require_revision(previous, expected_revision)
            if record.status != "CANCEL_REQUESTED" or record.attempts[-1].attempt_id != attempt_id:
                raise PreparationConflictError("STALE_ATTEMPT")
            superseded = record.attempts[-1].source_revision != record.source_revision
            ended = record.attempts[-1].model_copy(update={
                "status": "CANCELLED", "finished_at": now,
            })
            return self._updated(
                record, now, status="DRAFT" if record.source_edit_pending else "CANCELLED",
                attempts=() if superseded else (*record.attempts[:-1], ended),
                source_edit_pending=False,
            )

        return self._operation("ACK_CANCEL", preparation_id, {
            "attempt_id": attempt_id, "expected_revision": expected_revision,
        }, idempotency_key, change)

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
