"""SQLite-backed atomic admission for durable backtest jobs."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.control import MonotonicProgressThrottle
from trade_plan_monitor.backtest.jobs.models import (
    JOB_IDEMPOTENCY_DAYS,
    JOB_LEASE_SECONDS,
    JOB_MAX_CLAIM_GENERATIONS,
    JOB_PROGRESS_INTERVAL_SECONDS,
    MAX_JOB_REQUEST_BYTES,
    MAX_QUEUED_JOBS,
    BacktestDatasetVerificationJobResult,
    BacktestDataSyncJobResult,
    BacktestJobCancellationReceipt,
    BacktestJobClaim,
    BacktestJobKind,
    BacktestJobPhase,
    BacktestJobProgress,
    BacktestJobReceipt,
    BacktestJobRequest,
    BacktestJobStatus,
    BacktestJobView,
    BacktestProgressUnit,
    BacktestRunJobRequest,
    BacktestRunJobResult,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
)
from trade_plan_monitor.backtest.migration import (
    DatabaseState,
    MigrationInventory,
    MigrationPreflightError,
    create_backtest_job_schema,
    inspect_result_database,
    require_safe_store_initialization,
)
from trade_plan_monitor.backtest.results import (
    BacktestResultStore,
    RetentionPruneResult,
    VerifiedBacktestPublication,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.backtest.storage_guard import reject_incompatible_database
from trade_plan_monitor.backtest.time import (
    format_shanghai_datetime,
    parse_shanghai_datetime,
    shanghai_now_text,
)

_REQUEST_HASH_DOMAIN = b"backtest-job-request-v1\0"
_OPERATION_HASH_DOMAIN = b"backtest-job-operation-v1\0"
_RUN_INPUT_HASH_DOMAIN = b"backtest-run-input-record-v1\0"
_CANCEL_HASH_DOMAIN = b"backtest-job-cancel-v1\0"
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_CLAIM_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_ACTIVE_STATUSES = (
    BacktestJobStatus.QUEUED.value,
    BacktestJobStatus.RUNNING.value,
    BacktestJobStatus.CANCEL_REQUESTED.value,
)
_JOB_COLUMNS = """
    job_id, kind, status, request_hash, run_id, dataset_hash,
    phase, progress_unit, completed_units, total_units,
    attempt, revision, created_at, started_at, updated_at,
    finished_at, cancel_requested_at, reused, result_json,
    error_code, error_message
"""
_CLAIM_COLUMNS = """
    job_id, kind, request_json, run_id, dataset_hash,
    attempt, revision, claim_token, heartbeat_at, lease_expires_at
"""


class JobAdmissionError(RuntimeError):
    """A stable, sanitized admission failure with no request content."""

    _MESSAGES = {
        "IDEMPOTENCY_CONFLICT": "Idempotency key is already bound to another request.",
        "QUEUE_FULL": "The durable backtest queue is full.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(self._MESSAGES[code])


class BacktestJobRepository:
    """Own job admission in the shared backtest-results SQLite database."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = 5_000,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be a string or Path")
        if isinstance(database_path, str) and not database_path.strip():
            raise ValueError("database_path must not be empty")
        if type(busy_timeout_ms) is not int or not 1 <= busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms must be between 1 and 60000")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        if monotonic_clock is not None and not callable(monotonic_clock):
            raise TypeError("monotonic_clock must be callable")
        self._path = Path(database_path).expanduser().resolve()
        if self._path.exists() and not self._path.is_file():
            raise ValueError("database_path must point to a file")
        self._busy_timeout_ms = busy_timeout_ms
        self._clock = clock
        self._progress_throttle = (
            MonotonicProgressThrottle(interval_seconds=JOB_PROGRESS_INTERVAL_SECONDS)
            if monotonic_clock is None
            else MonotonicProgressThrottle(
                interval_seconds=JOB_PROGRESS_INTERVAL_SECONDS,
                clock=monotonic_clock,
            )
        )
        self._migration_inventory = inspect_result_database(self._path)
        reject_incompatible_database(
            self._path,
            store_name="backtest job",
            forbidden_prefixes=("market_",),
            observed_table_names=self._migration_inventory.table_names,
        )
        if "MISSING_BACKTEST_JOB_SCHEMA" in self._migration_inventory.migration_reasons:
            raise MigrationPreflightError("LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION")
        require_safe_store_initialization(self._migration_inventory)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        result_store: BacktestResultStore | None = None
        if self._migration_inventory.database_state is DatabaseState.FRESH:
            result_store = BacktestResultStore(self._path, busy_timeout_ms=busy_timeout_ms)
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                create_backtest_job_schema(connection)
                connection.commit()
        current = inspect_result_database(self._path)
        if current.database_state is not DatabaseState.CURRENT or (
            "MISSING_BACKTEST_JOB_SCHEMA" in current.migration_reasons
        ):
            raise MigrationPreflightError("BACKTEST_JOB_SCHEMA_INITIALIZATION_FAILED")
        self._result_store = result_store or BacktestResultStore(
            self._path,
            busy_timeout_ms=busy_timeout_ms,
        )

    @property
    def database_path(self) -> Path:
        return self._path

    @property
    def migration_inventory(self) -> MigrationInventory:
        return self._migration_inventory

    def submit(
        self,
        request: BacktestJobRequest,
        idempotency_key: str,
        *,
        request_id: str | None = None,
    ) -> BacktestJobReceipt:
        """Atomically replay, deduplicate, reuse, or admit one durable operation."""

        if not isinstance(
            request,
            (DataSyncJobRequest, DatasetVerifyJobRequest, BacktestRunJobRequest),
        ):
            raise TypeError("request must be a strict backtest job request")
        normalized_key = _validate_idempotency_key(idempotency_key)
        if isinstance(request, DataSyncJobRequest):
            normalized_request_id = _validate_request_id(request_id)
        else:
            normalized_request_id = None
        now = self._now()
        now_text = format_shanghai_datetime(now)
        request_json = _canonical_request_json(request)
        if len(request_json.encode("utf-8")) > MAX_JOB_REQUEST_BYTES:
            raise ValueError("canonical job request exceeds 256 KiB")
        request_hash = sha256(_REQUEST_HASH_DOMAIN + request_json.encode("utf-8")).hexdigest()
        operation_hash = sha256(_OPERATION_HASH_DOMAIN + request_json.encode("utf-8")).hexdigest()
        run_id, dataset_hash = _request_identities(request)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._claim_or_replay_idempotency(
                connection,
                idempotency_key=normalized_key,
                request_hash=request_hash,
                now=now,
                created_at=now_text,
            )
            if replay is not None:
                connection.commit()
                return replay

            active = connection.execute(
                f"""
                SELECT {_JOB_COLUMNS}
                FROM backtest_job
                WHERE operation_hash = ? AND status IN (?, ?, ?)
                ORDER BY created_at, job_id
                LIMIT 2
                """,
                (operation_hash, *_ACTIVE_STATUSES),
            ).fetchall()
            if len(active) > 1:
                raise RuntimeError("durable job store contains duplicate active operations")
            if active:
                receipt = _receipt_from_row(active[0])
                self._bind_idempotency_response(
                    connection,
                    idempotency_key=normalized_key,
                    request_hash=request_hash,
                    receipt=receipt,
                    created_at=now_text,
                    expires_at=None,
                )
                connection.commit()
                return receipt

            reused_result = (
                _verified_materialized_run(connection, request.run_input)
                if isinstance(request, BacktestRunJobRequest)
                else None
            )
            if reused_result is None:
                queued = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM backtest_job WHERE status = 'QUEUED'"
                    ).fetchone()[0]
                )
                if queued >= MAX_QUEUED_JOBS:
                    raise JobAdmissionError("QUEUE_FULL")

            job_id = uuid4().hex
            reused = reused_result is not None
            status = BacktestJobStatus.COMPLETED if reused else BacktestJobStatus.QUEUED
            phase = BacktestJobPhase.TERMINAL if reused else BacktestJobPhase.QUEUED
            result_json = (
                canonical_json(
                    BacktestRunJobResult(
                        run_id=run_id,
                        report_hash=reused_result,
                        reused=True,
                    )
                )
                if reused and run_id is not None
                else None
            )
            finished_at = now_text if reused else None
            membership_revision = _next_membership_revision(connection)
            connection.execute(
                """
                INSERT INTO backtest_job (
                    job_id, kind, status, request_hash, operation_hash, request_json,
                    run_id, dataset_hash, phase, progress_unit,
                    completed_units, total_units, attempt, revision, membership_revision,
                    created_at, started_at, updated_at, finished_at,
                    cancel_requested_at, reused, result_json, error_code, error_message,
                    network_authorized_at, request_id, claim_token, lease_expires_at,
                    heartbeat_at, progress_updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    0, NULL, 0, 0, ?, ?, NULL, ?, ?,
                    NULL, ?, ?, NULL, NULL, ?, ?, NULL, NULL, NULL, NULL
                )
                """,
                (
                    job_id,
                    request.kind.value,
                    status.value,
                    request_hash,
                    operation_hash,
                    request_json,
                    run_id,
                    dataset_hash,
                    phase.value,
                    _progress_unit(request.kind).value,
                    membership_revision,
                    now_text,
                    now_text,
                    finished_at,
                    int(reused),
                    result_json,
                    now_text if isinstance(request, DataSyncJobRequest) else None,
                    normalized_request_id,
                ),
            )
            receipt = BacktestJobReceipt(
                job_id=job_id,
                kind=request.kind,
                status=status,
                run_id=run_id,
                dataset_hash=dataset_hash,
                attempt=0,
                revision=0,
                reused=reused,
                submitted_at=now,
            )
            expires_at = (
                format_shanghai_datetime(now + timedelta(days=JOB_IDEMPOTENCY_DAYS))
                if reused
                else None
            )
            self._bind_idempotency_response(
                connection,
                idempotency_key=normalized_key,
                request_hash=request_hash,
                receipt=receipt,
                created_at=now_text,
                expires_at=expires_at,
            )
            connection.commit()
            return receipt

    def get(self, job_id: str) -> BacktestJobView | None:
        normalized_job_id = _validate_job_id(job_id)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_JOB_COLUMNS} FROM backtest_job WHERE job_id = ?",
                (normalized_job_id,),
            ).fetchone()
        return None if row is None else _view_from_row(row)

    def list_jobs(
        self,
        *,
        kind: BacktestJobKind | None = None,
        status: BacktestJobStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[BacktestJobView, ...]:
        if kind is not None and not isinstance(kind, BacktestJobKind):
            raise TypeError("kind must be a BacktestJobKind or None")
        if status is not None and not isinstance(status, BacktestJobStatus):
            raise TypeError("status must be a BacktestJobStatus or None")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        clauses: list[str] = []
        parameters: list[object] = []
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(kind.value)
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status.value)
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {_JOB_COLUMNS} FROM backtest_job{where}
                ORDER BY created_at DESC, job_id DESC LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()
        return tuple(_view_from_row(row) for row in rows)

    def claim_next(self) -> BacktestJobClaim | None:
        """Atomically claim the oldest queued job when the single slot is free."""

        now = self._now()
        now_text = format_shanghai_datetime(now)
        lease_text = format_shanghai_datetime(now + timedelta(seconds=JOB_LEASE_SECONDS))
        claim_token = token_hex(32)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT job_id FROM backtest_job "
                "WHERE status IN ('RUNNING', 'CANCEL_REQUESTED') LIMIT 2"
            ).fetchall()
            if len(active) > 1:
                raise RuntimeError("durable job store contains more than one active job")
            if active:
                connection.commit()
                return None
            row = connection.execute(
                """
                SELECT job_id FROM backtest_job
                WHERE status = 'QUEUED' AND attempt = 0
                ORDER BY created_at, job_id LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            job_id = str(row[0])
            membership_revision = _next_membership_revision(connection)
            updated = connection.execute(
                """
                UPDATE backtest_job
                SET status = 'RUNNING', phase = 'VALIDATING_INPUT', attempt = 1,
                    revision = revision + 1, membership_revision = ?,
                    started_at = ?, updated_at = ?, claim_token = ?,
                    lease_expires_at = ?, heartbeat_at = ?, progress_updated_at = NULL
                WHERE job_id = ? AND status = 'QUEUED' AND attempt = 0
                """,
                (
                    membership_revision,
                    now_text,
                    now_text,
                    claim_token,
                    lease_text,
                    now_text,
                    job_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("queued job claim lost inside its write transaction")
            claim = self._load_claim(connection, job_id)
            connection.commit()
        return claim

    def heartbeat(self, job_id: str, claim_token: str) -> bool:
        """Extend a current active claim without changing its public revision."""

        normalized_job_id = _validate_job_id(job_id)
        normalized_token = _validate_claim_token(claim_token)
        now = self._now()
        now_text = format_shanghai_datetime(now)
        lease_text = format_shanghai_datetime(now + timedelta(seconds=JOB_LEASE_SECONDS))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE backtest_job
                SET heartbeat_at = ?, lease_expires_at = ?
                WHERE job_id = ? AND claim_token = ?
                  AND status IN ('RUNNING', 'CANCEL_REQUESTED')
                  AND lease_expires_at > ?
                """,
                (
                    now_text,
                    lease_text,
                    normalized_job_id,
                    normalized_token,
                    now_text,
                ),
            )
            connection.commit()
        return updated.rowcount == 1

    def update_progress(
        self,
        job_id: str,
        claim_token: str,
        *,
        phase: BacktestJobPhase,
        completed_units: int,
        total_units: int | None = None,
    ) -> bool:
        """Persist monotonic worker progress, throttled outside phase transitions."""

        normalized_job_id = _validate_job_id(job_id)
        normalized_token = _validate_claim_token(claim_token)
        if not isinstance(phase, BacktestJobPhase):
            raise TypeError("phase must be a BacktestJobPhase")
        if phase in {BacktestJobPhase.QUEUED, BacktestJobPhase.TERMINAL}:
            raise ValueError("worker progress phase must be nonterminal")
        if type(completed_units) is not int or completed_units < 0:
            raise ValueError("completed_units must be a non-negative integer")
        if total_units is not None and (type(total_units) is not int or total_units < 0):
            raise ValueError("total_units must be a non-negative integer or None")
        if total_units is not None and completed_units > total_units:
            raise ValueError("completed_units cannot exceed total_units")
        now = self._now()
        now_text = format_shanghai_datetime(now)
        throttle_key = f"{normalized_job_id}:{normalized_token}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT phase, completed_units, total_units
                FROM backtest_job
                WHERE job_id = ? AND claim_token = ? AND status = 'RUNNING'
                  AND lease_expires_at > ?
                """,
                (normalized_job_id, normalized_token, now_text),
            ).fetchone()
            if row is None:
                connection.commit()
                return False
            previous_completed = int(row[1])
            previous_total = None if row[2] is None else int(row[2])
            if completed_units < previous_completed:
                raise ValueError("completed_units must be monotonic within an attempt")
            normalized_total = previous_total if total_units is None else total_units
            if (
                previous_total is not None
                and normalized_total is not None
                and normalized_total < previous_total
            ):
                raise ValueError("total_units must be monotonic within an attempt")
            if normalized_total is not None and completed_units > normalized_total:
                raise ValueError("completed_units cannot exceed total_units")
            phase_changed = str(row[0]) != phase.value
            if not self._progress_throttle.admit(throttle_key, force=phase_changed):
                connection.commit()
                return False
            updated = connection.execute(
                """
                UPDATE backtest_job
                SET phase = ?, completed_units = ?, total_units = ?,
                    progress_updated_at = ?, updated_at = ?, revision = revision + 1
                WHERE job_id = ? AND claim_token = ? AND status = 'RUNNING'
                  AND lease_expires_at > ?
                """,
                (
                    phase.value,
                    completed_units,
                    normalized_total,
                    now_text,
                    now_text,
                    normalized_job_id,
                    normalized_token,
                    now_text,
                ),
            )
            if updated.rowcount != 1:
                self._progress_throttle.forget(throttle_key)
                connection.commit()
                return False
            connection.commit()
        return True

    def complete(
        self,
        job_id: str,
        claim_token: str,
        result: BacktestDataSyncJobResult
        | BacktestDatasetVerificationJobResult
        | BacktestRunJobResult,
    ) -> bool:
        """Commit one token-fenced completed job representation."""

        normalized_job_id = _validate_job_id(job_id)
        normalized_token = _validate_claim_token(claim_token)
        if not isinstance(
            result,
            (
                BacktestDataSyncJobResult,
                BacktestDatasetVerificationJobResult,
                BacktestRunJobResult,
            ),
        ):
            raise TypeError("result must be a closed backtest job result")
        publication: VerifiedBacktestPublication | None = None
        if isinstance(result, BacktestRunJobResult):
            publication = self._result_store.verify_job_publication(
                result.run_id,
                expected_report_hash=result.report_hash,
            )
        now = self._now()
        now_text = format_shanghai_datetime(now)
        expires_at = format_shanghai_datetime(now + timedelta(days=JOB_IDEMPOTENCY_DAYS))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT kind, run_id, dataset_hash FROM backtest_job
                WHERE job_id = ? AND claim_token = ? AND status = 'RUNNING'
                  AND lease_expires_at > ?
                """,
                (normalized_job_id, normalized_token, now_text),
            ).fetchone()
            if row is None:
                connection.commit()
                return False
            kind = BacktestJobKind(str(row[0]))
            if result.kind is not kind:
                raise ValueError("job result kind does not match the claimed job")
            if isinstance(result, BacktestRunJobResult) and result.run_id != str(row[1]):
                raise ValueError("run result identity does not match the claimed job")
            if publication is not None:
                self._result_store.materialize_verified_publication(connection, publication)
            dataset_hash = (
                result.dataset_hash
                if isinstance(result, BacktestDatasetVerificationJobResult)
                else (None if row[2] is None else str(row[2]))
            )
            membership_revision = _next_membership_revision(connection)
            updated = connection.execute(
                """
                UPDATE backtest_job
                SET status = 'COMPLETED', phase = 'TERMINAL', dataset_hash = ?,
                    result_json = ?, finished_at = ?, updated_at = ?,
                    revision = revision + 1, membership_revision = ?,
                    claim_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = NULL, error_message = NULL
                WHERE job_id = ? AND claim_token = ? AND status = 'RUNNING'
                  AND lease_expires_at > ?
                """,
                (
                    dataset_hash,
                    canonical_json(result.model_dump(mode="json", round_trip=True)),
                    now_text,
                    now_text,
                    membership_revision,
                    normalized_job_id,
                    normalized_token,
                    now_text,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return False
            _expire_job_idempotency(connection, normalized_job_id, expires_at)
            connection.commit()
        self._progress_throttle.forget(f"{normalized_job_id}:{normalized_token}")
        return True

    def prune_job_rows(
        self,
        *,
        as_of: datetime,
        remaining_budget: int,
    ) -> RetentionPruneResult:
        """Delete expired terminal jobs within the caller-owned total row budget."""

        with self.maintenance_unit_of_work() as connection:
            return self.prune_job_rows_participant(
                connection,
                as_of=as_of,
                remaining_budget=remaining_budget,
            )

    @contextmanager
    def maintenance_unit_of_work(self) -> Iterator[sqlite3.Connection]:
        """Own the one job/result maintenance transaction for this database."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()

    def prune_job_rows_participant(
        self,
        connection: sqlite3.Connection,
        *,
        as_of: datetime,
        remaining_budget: int,
    ) -> RetentionPruneResult:
        """Delete expired terminal jobs inside the owner maintenance transaction."""

        _require_repository_connection(connection, self._path)
        normalized_as_of = parse_shanghai_datetime(format_shanghai_datetime(as_of))
        if type(remaining_budget) is not int or not 0 <= remaining_budget <= 1_000:
            raise ValueError("remaining_budget must be between 0 and 1000")
        cutoff = format_shanghai_datetime(normalized_as_of - timedelta(days=JOB_IDEMPOTENCY_DAYS))
        if remaining_budget == 0:
            has_more = (
                connection.execute(
                    """
                    SELECT 1 FROM backtest_job
                    WHERE status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                      AND finished_at < ? LIMIT 1
                    """,
                    (cutoff,),
                ).fetchone()
                is not None
            )
            return RetentionPruneResult(deleted_count=0, has_more=has_more)
        job_ids = tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT job_id FROM backtest_job
                WHERE status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                  AND finished_at < ?
                ORDER BY finished_at, job_id LIMIT ?
                """,
                (cutoff, remaining_budget),
            ).fetchall()
        )
        deleted_count = 0
        for job_id in job_ids:
            connection.execute(
                "DELETE FROM backtest_job_idempotency WHERE job_id = ?",
                (job_id,),
            )
            deleted_count += connection.execute(
                """
                DELETE FROM backtest_job
                WHERE job_id = ?
                  AND status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                  AND finished_at < ?
                """,
                (job_id, cutoff),
            ).rowcount
        has_more = (
            connection.execute(
                """
                SELECT 1 FROM backtest_job
                WHERE status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                  AND finished_at < ? LIMIT 1
                """,
                (cutoff,),
            ).fetchone()
            is not None
        )
        return RetentionPruneResult(deleted_count=deleted_count, has_more=has_more)

    def fail(
        self,
        job_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
    ) -> bool:
        """Commit one sanitized failure only for the current unexpired claim."""

        normalized_job_id = _validate_job_id(job_id)
        normalized_token = _validate_claim_token(claim_token)
        normalized_code, normalized_message = _validate_sanitized_error(error_code, error_message)
        now = self._now()
        now_text = format_shanghai_datetime(now)
        expires_at = format_shanghai_datetime(now + timedelta(days=JOB_IDEMPOTENCY_DAYS))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            membership_revision = _next_membership_revision(connection)
            updated = connection.execute(
                """
                UPDATE backtest_job
                SET status = 'FAILED', phase = 'TERMINAL', result_json = NULL,
                    error_code = ?, error_message = ?, finished_at = ?, updated_at = ?,
                    revision = revision + 1, membership_revision = ?,
                    claim_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL
                WHERE job_id = ? AND claim_token = ? AND status = 'RUNNING'
                  AND lease_expires_at > ?
                """,
                (
                    normalized_code,
                    normalized_message,
                    now_text,
                    now_text,
                    membership_revision,
                    normalized_job_id,
                    normalized_token,
                    now_text,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return False
            _expire_job_idempotency(connection, normalized_job_id, expires_at)
            connection.commit()
        self._progress_throttle.forget(f"{normalized_job_id}:{normalized_token}")
        return True

    def request_cancel(
        self,
        job_id: str,
        idempotency_key: str,
    ) -> BacktestJobCancellationReceipt:
        """Atomically request cancellation and retain its canonical response."""

        normalized_job_id = _validate_job_id(job_id)
        normalized_key = _validate_idempotency_key(idempotency_key)
        request_json = canonical_json({"jobId": normalized_job_id, "operation": "CANCEL"})
        request_hash = sha256(_CANCEL_HASH_DOMAIN + request_json.encode("utf-8")).hexdigest()
        now = self._now()
        now_text = format_shanghai_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._claim_or_replay_cancellation(
                connection,
                idempotency_key=normalized_key,
                request_hash=request_hash,
                now=now,
                created_at=now_text,
            )
            if replay is not None:
                connection.commit()
                return replay
            row = connection.execute(
                """
                SELECT status, attempt, revision, finished_at
                FROM backtest_job WHERE job_id = ?
                """,
                (normalized_job_id,),
            ).fetchone()
            if row is None:
                raise KeyError("backtest job not found")
            status = BacktestJobStatus(str(row[0]))
            attempt = int(row[1])
            revision = int(row[2])
            finished_at = None if row[3] is None else parse_shanghai_datetime(str(row[3]))
            if status is BacktestJobStatus.QUEUED:
                membership_revision = _next_membership_revision(connection)
                updated = connection.execute(
                    """
                    UPDATE backtest_job
                    SET status = 'CANCELLED', phase = 'TERMINAL',
                        cancel_requested_at = ?, finished_at = ?, updated_at = ?,
                        revision = revision + 1, membership_revision = ?
                    WHERE job_id = ? AND status = 'QUEUED' AND attempt = 0
                    """,
                    (
                        now_text,
                        now_text,
                        now_text,
                        membership_revision,
                        normalized_job_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("queued cancellation lost inside its write transaction")
                status = BacktestJobStatus.CANCELLED
                revision += 1
                finished_at = now
            elif status is BacktestJobStatus.RUNNING:
                membership_revision = _next_membership_revision(connection)
                updated = connection.execute(
                    """
                    UPDATE backtest_job
                    SET status = 'CANCEL_REQUESTED', cancel_requested_at = ?,
                        updated_at = ?, revision = revision + 1,
                        membership_revision = ?
                    WHERE job_id = ? AND status = 'RUNNING'
                    """,
                    (
                        now_text,
                        now_text,
                        membership_revision,
                        normalized_job_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("running cancellation lost inside its write transaction")
                status = BacktestJobStatus.CANCEL_REQUESTED
                revision += 1
            receipt = BacktestJobCancellationReceipt(
                job_id=normalized_job_id,
                status=status,
                attempt=attempt,
                revision=revision,
                responded_at=now,
            )
            expires_at = (
                None
                if finished_at is None
                else format_shanghai_datetime(finished_at + timedelta(days=JOB_IDEMPOTENCY_DAYS))
            )
            self._bind_cancellation_response(
                connection,
                idempotency_key=normalized_key,
                request_hash=request_hash,
                job_id=normalized_job_id,
                receipt=receipt,
                created_at=now_text,
                expires_at=expires_at,
            )
            if expires_at is not None:
                _expire_job_idempotency(connection, normalized_job_id, expires_at)
            connection.commit()
            return receipt

    def acknowledge_cancel(self, job_id: str, claim_token: str) -> bool:
        """Let only the current unexpired worker acknowledge cancellation."""

        normalized_job_id = _validate_job_id(job_id)
        normalized_token = _validate_claim_token(claim_token)
        now = self._now()
        now_text = format_shanghai_datetime(now)
        expires_at = format_shanghai_datetime(now + timedelta(days=JOB_IDEMPOTENCY_DAYS))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            membership_revision = _next_membership_revision(connection)
            updated = connection.execute(
                """
                UPDATE backtest_job
                SET status = 'CANCELLED', phase = 'TERMINAL', result_json = NULL,
                    finished_at = ?, updated_at = ?, revision = revision + 1,
                    membership_revision = ?, claim_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = NULL, error_message = NULL
                WHERE job_id = ? AND claim_token = ?
                  AND status = 'CANCEL_REQUESTED' AND lease_expires_at > ?
                """,
                (
                    now_text,
                    now_text,
                    membership_revision,
                    normalized_job_id,
                    normalized_token,
                    now_text,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                return False
            _expire_job_idempotency(connection, normalized_job_id, expires_at)
            connection.commit()
        self._progress_throttle.forget(f"{normalized_job_id}:{normalized_token}")
        return True

    def recover_expired(self) -> BacktestJobClaim | None:
        """Recover or terminate the one expired active claim deterministically."""

        now = self._now()
        now_text = format_shanghai_datetime(now)
        terminal_expiry = format_shanghai_datetime(now + timedelta(days=JOB_IDEMPOTENCY_DAYS))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT job_id, kind, status, request_json, run_id, dataset_hash,
                       attempt, revision, claim_token, lease_expires_at,
                       network_authorized_at
                FROM backtest_job
                WHERE status IN ('RUNNING', 'CANCEL_REQUESTED')
                ORDER BY created_at, job_id LIMIT 2
                """
            ).fetchall()
            if len(rows) > 1:
                raise RuntimeError("durable job store contains more than one active job")
            if not rows:
                connection.commit()
                return None
            row = rows[0]
            if row[9] is None or str(row[9]) > now_text:
                connection.commit()
                return None
            job_id = str(row[0])
            kind = BacktestJobKind(str(row[1]))
            status = BacktestJobStatus(str(row[2]))
            attempt = int(row[6])
            previous_token = None if row[8] is None else str(row[8])
            if previous_token is None:
                raise RuntimeError("active job is missing its claim token")
            if status is BacktestJobStatus.CANCEL_REQUESTED:
                membership_revision = _next_membership_revision(connection)
                connection.execute(
                    """
                    UPDATE backtest_job
                    SET status = 'CANCELLED', phase = 'TERMINAL', result_json = NULL,
                        finished_at = ?, updated_at = ?, revision = revision + 1,
                        membership_revision = ?, claim_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL,
                        error_code = NULL, error_message = NULL
                    WHERE job_id = ? AND status = 'CANCEL_REQUESTED'
                      AND claim_token = ? AND lease_expires_at <= ?
                    """,
                    (
                        now_text,
                        now_text,
                        membership_revision,
                        job_id,
                        previous_token,
                        now_text,
                    ),
                )
                _expire_job_idempotency(connection, job_id, terminal_expiry)
                connection.commit()
                self._progress_throttle.forget(f"{job_id}:{previous_token}")
                return None
            recovery_error: tuple[str, str] | None = None
            if attempt >= JOB_MAX_CLAIM_GENERATIONS:
                recovery_error = (
                    "WORKER_RECOVERY_EXHAUSTED",
                    "Worker lease expired after three claim generations.",
                )
            elif kind is BacktestJobKind.DATA_SYNC and not _has_sync_authorization(
                request_json=str(row[3]),
                network_authorized_at=row[10],
            ):
                recovery_error = (
                    "NETWORK_AUTHORIZATION_MISSING",
                    "Persisted job-scoped network authorization is missing.",
                )
            if recovery_error is not None:
                membership_revision = _next_membership_revision(connection)
                connection.execute(
                    """
                    UPDATE backtest_job
                    SET status = 'FAILED', phase = 'TERMINAL', result_json = NULL,
                        error_code = ?, error_message = ?, finished_at = ?, updated_at = ?,
                        revision = revision + 1, membership_revision = ?,
                        claim_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE job_id = ? AND status = 'RUNNING'
                      AND claim_token = ? AND lease_expires_at <= ?
                    """,
                    (
                        *recovery_error,
                        now_text,
                        now_text,
                        membership_revision,
                        job_id,
                        previous_token,
                        now_text,
                    ),
                )
                _expire_job_idempotency(connection, job_id, terminal_expiry)
                connection.commit()
                self._progress_throttle.forget(f"{job_id}:{previous_token}")
                return None
            new_token = token_hex(32)
            lease_text = format_shanghai_datetime(now + timedelta(seconds=JOB_LEASE_SECONDS))
            updated = connection.execute(
                """
                UPDATE backtest_job
                SET attempt = attempt + 1, revision = revision + 1,
                    phase = 'VALIDATING_INPUT', completed_units = 0,
                    total_units = NULL, updated_at = ?, claim_token = ?,
                    lease_expires_at = ?, heartbeat_at = ?, progress_updated_at = NULL
                WHERE job_id = ? AND status = 'RUNNING' AND attempt < ?
                  AND claim_token = ? AND lease_expires_at <= ?
                """,
                (
                    now_text,
                    new_token,
                    lease_text,
                    now_text,
                    job_id,
                    JOB_MAX_CLAIM_GENERATIONS,
                    previous_token,
                    now_text,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("expired claim recovery lost inside its write transaction")
            claim = self._load_claim(connection, job_id)
            connection.commit()
        self._progress_throttle.forget(f"{job_id}:{previous_token}")
        return claim

    @staticmethod
    def _load_claim(connection: sqlite3.Connection, job_id: str) -> BacktestJobClaim:
        row = connection.execute(
            f"SELECT {_CLAIM_COLUMNS} FROM backtest_job WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("claimed job disappeared inside its write transaction")
        return _claim_from_row(row)

    def _claim_or_replay_cancellation(
        self,
        connection: sqlite3.Connection,
        *,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
        created_at: str,
    ) -> BacktestJobCancellationReceipt | None:
        claimed = connection.execute(
            """
            INSERT INTO backtest_job_idempotency (
                idempotency_key, operation, request_hash, job_id,
                response_json, created_at, expires_at
            ) VALUES (?, 'CANCEL', ?, NULL, NULL, ?, NULL)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (idempotency_key, request_hash, created_at),
        )
        if claimed.rowcount == 1:
            return None
        row = connection.execute(
            """
            SELECT operation, request_hash, response_json, expires_at
            FROM backtest_job_idempotency WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        expires_at = None if row[3] is None else parse_shanghai_datetime(str(row[3]))
        if expires_at is not None and now > expires_at:
            connection.execute(
                "DELETE FROM backtest_job_idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            return self._claim_or_replay_cancellation(
                connection,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=now,
                created_at=created_at,
            )
        if str(row[0]) != "CANCEL" or str(row[1]) != request_hash:
            raise JobAdmissionError("IDEMPOTENCY_CONFLICT")
        if row[2] is None:
            raise RuntimeError("committed cancellation claim is missing its canonical response")
        return BacktestJobCancellationReceipt.model_validate_json(str(row[2]))

    @staticmethod
    def _bind_cancellation_response(
        connection: sqlite3.Connection,
        *,
        idempotency_key: str,
        request_hash: str,
        job_id: str,
        receipt: BacktestJobCancellationReceipt,
        created_at: str,
        expires_at: str | None,
    ) -> None:
        response_json = canonical_json(receipt.model_dump(mode="json", round_trip=True))
        updated = connection.execute(
            """
            UPDATE backtest_job_idempotency
            SET job_id = ?, response_json = ?, created_at = ?, expires_at = ?
            WHERE idempotency_key = ? AND operation = 'CANCEL'
              AND request_hash = ? AND job_id IS NULL AND response_json IS NULL
            """,
            (
                job_id,
                response_json,
                created_at,
                expires_at,
                idempotency_key,
                request_hash,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("cancellation claim could not bind its canonical response")

    def _claim_or_replay_idempotency(
        self,
        connection: sqlite3.Connection,
        *,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
        created_at: str,
    ) -> BacktestJobReceipt | None:
        claimed = connection.execute(
            """
            INSERT INTO backtest_job_idempotency (
                idempotency_key, operation, request_hash, job_id,
                response_json, created_at, expires_at
            ) VALUES (?, 'SUBMIT', ?, NULL, NULL, ?, NULL)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (idempotency_key, request_hash, created_at),
        )
        if claimed.rowcount == 1:
            return None
        row = connection.execute(
            """
            SELECT operation, request_hash, response_json, expires_at
            FROM backtest_job_idempotency WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        expires_at = None if row[3] is None else parse_shanghai_datetime(str(row[3]))
        if expires_at is not None and now > expires_at:
            connection.execute(
                "DELETE FROM backtest_job_idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            return self._claim_or_replay_idempotency(
                connection,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=now,
                created_at=created_at,
            )
        if str(row[0]) != "SUBMIT" or str(row[1]) != request_hash:
            raise JobAdmissionError("IDEMPOTENCY_CONFLICT")
        if row[2] is None:
            raise RuntimeError("committed idempotency claim is missing its canonical response")
        return BacktestJobReceipt.model_validate_json(str(row[2]))

    @staticmethod
    def _bind_idempotency_response(
        connection: sqlite3.Connection,
        *,
        idempotency_key: str,
        request_hash: str,
        receipt: BacktestJobReceipt,
        created_at: str,
        expires_at: str | None,
    ) -> None:
        response_json = canonical_json(receipt.model_dump(mode="json", round_trip=True))
        updated = connection.execute(
            """
            UPDATE backtest_job_idempotency
            SET job_id = ?, response_json = ?, created_at = ?, expires_at = ?
            WHERE idempotency_key = ? AND operation = 'SUBMIT'
              AND request_hash = ? AND job_id IS NULL AND response_json IS NULL
            """,
            (
                receipt.job_id,
                response_json,
                created_at,
                expires_at,
                idempotency_key,
                request_hash,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError("idempotency claim could not bind its canonical response")

    def _now(self) -> datetime:
        if self._clock is None:
            return parse_shanghai_datetime(shanghai_now_text())
        value = self._clock()
        return parse_shanghai_datetime(format_shanghai_datetime(value))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._path,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _require_repository_connection(connection: sqlite3.Connection, path: Path) -> None:
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    rows = tuple(connection.execute("PRAGMA database_list"))
    main_rows = tuple(row for row in rows if len(row) >= 3 and str(row[1]) == "main")
    if len(main_rows) != 1 or not str(main_rows[0][2]):
        raise ValueError("maintenance connection must have one file-backed main database")
    if Path(str(main_rows[0][2])).resolve() != path:
        raise ValueError("maintenance connection targets another job database")


def _validate_idempotency_key(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("idempotency_key must contain 1..128 allowlisted characters")
    return value


def _validate_request_id(value: str | None) -> str:
    if type(value) is not str or _REQUEST_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("request_id must be 32 lowercase hexadecimal characters")
    return value


def _validate_claim_token(value: str) -> str:
    if type(value) is not str or _CLAIM_TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError("claim_token must be an opaque 256-bit value")
    return value


def _validate_job_id(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("job_id must contain 1..128 allowlisted characters")
    return value


def _validate_sanitized_error(error_code: str, error_message: str) -> tuple[str, str]:
    if type(error_code) is not str or _ERROR_CODE_PATTERN.fullmatch(error_code) is None:
        raise ValueError("error_code must contain 1..128 stable allowlisted characters")
    if (
        type(error_message) is not str
        or not 1 <= len(error_message) <= 512
        or not error_message.isprintable()
    ):
        raise ValueError("error_message must be 1..512 printable characters")
    return error_code, error_message


def _has_sync_authorization(
    *,
    request_json: str,
    network_authorized_at: object,
) -> bool:
    if network_authorized_at is None:
        return False
    try:
        authorized_at = parse_shanghai_datetime(str(network_authorized_at))
        payload = json.loads(request_json)
    except json.JSONDecodeError, TypeError, ValueError:
        return False
    return (
        authorized_at.utcoffset() is not None
        and type(payload) is dict
        and payload.get("kind") == BacktestJobKind.DATA_SYNC.value
        and payload.get("allowNetwork") is True
    )


def _expire_job_idempotency(
    connection: sqlite3.Connection,
    job_id: str,
    expires_at: str,
) -> None:
    connection.execute(
        "UPDATE backtest_job_idempotency SET expires_at = ? WHERE job_id = ?",
        (expires_at, job_id),
    )


def _request_identities(request: BacktestJobRequest) -> tuple[str | None, str | None]:
    if isinstance(request, BacktestRunJobRequest):
        return request.run_input.run_id, request.run_input.dataset_hash
    return None, None


def _canonical_request_json(request: BacktestJobRequest) -> str:
    if isinstance(request, (DataSyncJobRequest, DatasetVerifyJobRequest)):
        scope = request.scope
        payload: dict[str, object] = {
            "kind": request.kind,
            "scope": {
                "symbols": scope.symbols,
                "start": scope.start,
                "end": scope.end,
                "warmupStart": scope.warmup_start,
                "historicalProfile": scope.historical_profile,
                "adjustmentPolicy": scope.adjustment_policy,
            },
        }
        if isinstance(request, DataSyncJobRequest):
            payload.update(refresh=request.refresh, allowNetwork=request.allow_network)
        return canonical_json(payload)
    if isinstance(request, BacktestRunJobRequest):
        return canonical_json(
            {
                "kind": request.kind,
                "runInput": request.run_input.model_dump(mode="json", round_trip=True),
            }
        )
    raise AssertionError(f"unhandled job request: {type(request).__name__}")


def _progress_unit(kind: BacktestJobKind) -> BacktestProgressUnit:
    if kind in {BacktestJobKind.DATA_SYNC, BacktestJobKind.DATASET_VERIFY}:
        return BacktestProgressUnit.SYMBOL_DAYS
    if kind is BacktestJobKind.BACKTEST_RUN:
        return BacktestProgressUnit.EVENTS
    raise AssertionError(f"unhandled job kind: {kind!r}")


def _next_membership_revision(connection: sqlite3.Connection) -> int:
    connection.execute(
        "UPDATE backtest_job_state SET membership_revision = membership_revision + 1 "
        "WHERE state_key = 'GLOBAL'"
    )
    row = connection.execute(
        "SELECT membership_revision FROM backtest_job_state WHERE state_key = 'GLOBAL'"
    ).fetchone()
    if row is None:
        raise RuntimeError("backtest job state singleton is missing")
    return int(row[0])


def _verified_materialized_run(
    connection: sqlite3.Connection,
    run_input: BacktestRunInput,
) -> str | None:
    row = connection.execute(
        """
        SELECT run.summary_json, input.plan_sha256, input.input_hash,
               input.input_json, snapshot.snapshot_json
        FROM backtest_run AS run
        JOIN backtest_run_input AS input ON input.run_id = run.run_id
        JOIN backtest_plan_snapshot AS snapshot
          ON snapshot.plan_sha256 = input.plan_sha256
        WHERE run.run_id = ? AND run.dataset_hash = ?
          AND run.status = 'COMPLETED' AND run.materialized = 1
          AND run.summary_domain = 'backtest-run-summary-v2'
        """,
        (run_input.run_id, run_input.dataset_hash),
    ).fetchone()
    if row is None:
        return None
    stored_input_json = str(row[3])
    stored_input_hash = sha256(
        _RUN_INPUT_HASH_DOMAIN + stored_input_json.encode("utf-8")
    ).hexdigest()
    if str(row[1]) != run_input.plan_sha256 or str(row[2]) != stored_input_hash:
        return None
    try:
        stored_input_payload = json.loads(stored_input_json)
        stored_input_payload["plan_snapshot"] = json.loads(str(row[4]))
        stored_input = BacktestRunInput.model_validate_json(
            json.dumps(
                stored_input_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        summary = json.loads(str(row[0]))
        report_hash = summary["assumptions"]["reportHash"]
    except json.JSONDecodeError, KeyError, TypeError, ValueError:
        return None
    if stored_input.run_id != run_input.run_id:
        return None
    if type(report_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", report_hash) is None:
        return None
    return report_hash


def _receipt_from_row(row: sqlite3.Row | tuple[object, ...]) -> BacktestJobReceipt:
    return BacktestJobReceipt(
        job_id=str(row[0]),
        kind=BacktestJobKind(str(row[1])),
        status=BacktestJobStatus(str(row[2])),
        run_id=None if row[4] is None else str(row[4]),
        dataset_hash=None if row[5] is None else str(row[5]),
        attempt=int(row[10]),
        revision=int(row[11]),
        reused=bool(row[17]),
        submitted_at=parse_shanghai_datetime(str(row[12])),
    )


def _claim_from_row(row: sqlite3.Row | tuple[object, ...]) -> BacktestJobClaim:
    if row[7] is None or row[8] is None or row[9] is None:
        raise RuntimeError("active job claim fields are incomplete")
    return BacktestJobClaim(
        job_id=str(row[0]),
        kind=BacktestJobKind(str(row[1])),
        canonical_request_json=str(row[2]),
        run_id=None if row[3] is None else str(row[3]),
        dataset_hash=None if row[4] is None else str(row[4]),
        attempt=int(row[5]),
        revision=int(row[6]),
        claim_token=str(row[7]),
        claimed_at=parse_shanghai_datetime(str(row[8])),
        lease_expires_at=parse_shanghai_datetime(str(row[9])),
    )


def _view_from_row(row: sqlite3.Row | tuple[object, ...]) -> BacktestJobView:
    kind = BacktestJobKind(str(row[1]))
    result_model = {
        BacktestJobKind.DATA_SYNC: BacktestDataSyncJobResult,
        BacktestJobKind.DATASET_VERIFY: BacktestDatasetVerificationJobResult,
        BacktestJobKind.BACKTEST_RUN: BacktestRunJobResult,
    }[kind]
    result = None if row[18] is None else result_model.model_validate_json(str(row[18]))
    updated_at = parse_shanghai_datetime(str(row[14]))
    return BacktestJobView(
        job_id=str(row[0]),
        kind=kind,
        status=BacktestJobStatus(str(row[2])),
        request_hash=str(row[3]),
        run_id=None if row[4] is None else str(row[4]),
        dataset_hash=None if row[5] is None else str(row[5]),
        progress=BacktestJobProgress(
            phase=BacktestJobPhase(str(row[6])),
            completed_units=int(row[8]),
            total_units=None if row[9] is None else int(row[9]),
            unit=BacktestProgressUnit(str(row[7])),
            updated_at=updated_at,
        ),
        result=result,
        attempt=int(row[10]),
        revision=int(row[11]),
        created_at=parse_shanghai_datetime(str(row[12])),
        started_at=None if row[13] is None else parse_shanghai_datetime(str(row[13])),
        updated_at=updated_at,
        finished_at=None if row[15] is None else parse_shanghai_datetime(str(row[15])),
        cancel_requested_at=(None if row[16] is None else parse_shanghai_datetime(str(row[16]))),
        reused=bool(row[17]),
        error_code=None if row[19] is None else str(row[19]),
        error_message=None if row[20] is None else str(row[20]),
    )


__all__ = ["BacktestJobRepository", "JobAdmissionError"]
