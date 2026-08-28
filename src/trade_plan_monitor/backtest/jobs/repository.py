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
from uuid import uuid4

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.jobs.models import (
    JOB_IDEMPOTENCY_DAYS,
    MAX_JOB_REQUEST_BYTES,
    MAX_QUEUED_JOBS,
    BacktestDatasetVerificationJobResult,
    BacktestDataSyncJobResult,
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
from trade_plan_monitor.backtest.results import BacktestResultStore
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
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
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
    ) -> None:
        if not isinstance(database_path, (str, Path)):
            raise TypeError("database_path must be a string or Path")
        if isinstance(database_path, str) and not database_path.strip():
            raise ValueError("database_path must not be empty")
        if type(busy_timeout_ms) is not int or not 1 <= busy_timeout_ms <= 60_000:
            raise ValueError("busy_timeout_ms must be between 1 and 60000")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._path = Path(database_path).expanduser().resolve()
        if self._path.exists() and not self._path.is_file():
            raise ValueError("database_path must point to a file")
        self._busy_timeout_ms = busy_timeout_ms
        self._clock = clock
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
        if self._migration_inventory.database_state is DatabaseState.FRESH:
            BacktestResultStore(self._path, busy_timeout_ms=busy_timeout_ms)
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                create_backtest_job_schema(connection)
                connection.commit()
        current = inspect_result_database(self._path)
        if current.database_state is not DatabaseState.CURRENT or (
            "MISSING_BACKTEST_JOB_SCHEMA" in current.migration_reasons
        ):
            raise MigrationPreflightError("BACKTEST_JOB_SCHEMA_INITIALIZATION_FAILED")

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


def _validate_idempotency_key(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("idempotency_key must contain 1..128 allowlisted characters")
    return value


def _validate_request_id(value: str | None) -> str:
    if type(value) is not str or _REQUEST_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("request_id must be 32 lowercase hexadecimal characters")
    return value


def _validate_job_id(value: str) -> str:
    if type(value) is not str or _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ValueError("job_id must contain 1..128 allowlisted characters")
    return value


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
