"""Durable backtest-job schema and atomic admission coverage."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from threading import Barrier, Lock
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.dataset import DatasetManifest, DatasetScope
from trade_plan_monitor.backtest.jobs import (
    MAX_JOB_ERROR_CHARACTERS,
    MAX_JOB_REQUEST_BYTES,
    BacktestDatasetScopeRequest,
    BacktestJobKind,
    BacktestJobRepository,
    BacktestJobStatus,
    BacktestRunJobRequest,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
    JobAdmissionError,
)
from trade_plan_monitor.backtest.jobs.repository import (
    BacktestJobQueryResult,
    BacktestJobSubmissionBinding,
    BacktestRunSubmissionReservation,
)
from trade_plan_monitor.backtest.migration import (
    DatabaseState,
    MigrationPreflightError,
    VerifiedBackupFacts,
    authorize_migration,
    inspect_result_database,
    migrate_result_database,
)
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.results import (
    BacktestResultStore,
    BacktestRunStatus,
    BacktestRunSummary,
    backtest_detail_set_hash,
    backtest_fill_set_hash,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile

_PLAN_PATH = Path(__file__).parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class _Clock:
    def __init__(self, value: datetime) -> None:
        self._value = value
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._value

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self._value += delta


def _hash(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _scope(*, day: int = 20) -> BacktestDatasetScopeRequest:
    trade_date = date(2026, 4, 1) + timedelta(days=day)
    return BacktestDatasetScopeRequest(
        symbols=("003043.SZ",),
        start=trade_date,
        end=trade_date,
        warmup_start=trade_date,
        historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        adjustment_policy="NONE",
    )


def _run_input(label: str) -> BacktestRunInput:
    plan = load_plan_yaml(_PLAN_PATH.read_text(encoding="utf-8"))
    start = date(2026, 8, 20)
    manifest = DatasetManifest(
        dataset_hash=_hash(f"dataset:{label}"),
        scope=DatasetScope(
            symbols=(plan.symbol,),
            start=start,
            end=date(2026, 8, 24),
            warmup_start=date(2025, 8, 20),
            historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        ),
        items=(),
    )
    return BacktestRunInput.create(
        plan=plan,
        manifest=manifest,
        initial_cash_fen=10_000_000,
        initial_lots=(),
        execution_config=ExecutionConfig(
            commission_rate=Decimal("0.0003"),
            minimum_commission_fen=500,
            stamp_duty_rate=Decimal("0.0005"),
            transfer_fee_rate=Decimal("0.00001"),
            buy_slippage_bps=Decimal("2"),
            sell_slippage_bps=Decimal("2"),
        ),
        manual_event_risk=False,
    )


def _materialize_run(store: BacktestResultStore, run_input: BacktestRunInput) -> str:
    report_hash = _hash(f"report:{run_input.run_id}")
    summary = BacktestRunSummary(
        run_id=run_input.run_id,
        plan_sha256=run_input.plan_sha256,
        dataset_hash=run_input.dataset_hash,
        status=BacktestRunStatus.COMPLETED,
        completed_at=datetime(2026, 8, 24, 15, 30, tzinfo=_SHANGHAI),
        event_start=run_input.start,
        event_end=run_input.end,
        symbols=(run_input.plan_snapshot.symbol,),
        coverage={"detailCount": 0, "fillCount": 0},
        assumptions={
            "executionConfigHash": run_input.execution_config.config_hash,
            "manualEventRisk": run_input.manual_event_risk,
            "reportHash": report_hash,
        },
        formula_versions={
            "execution": run_input.execution_config.formula_version,
            "indicator": run_input.indicator_formula_version,
            "runner": run_input.run_formula_version,
        },
        final_metrics={"totalReturn": "0"},
    )
    assert store.record_verified_run(summary, run_input=run_input)
    proof = store.verify_staged_publication(
        run_id=summary.run_id,
        expected_fill_count=0,
        expected_detail_count=0,
        expected_report_hash=report_hash,
        expected_fill_set_hash=backtest_fill_set_hash((), version="v2"),
        expected_detail_set_hash=backtest_detail_set_hash((), version="v2"),
    )
    assert store.publish_verified_publication(proof)
    return report_hash


def _row_count(path: Path, table: str) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def test_twenty_concurrent_same_key_submissions_create_one_durable_job(
    tmp_path: Path,
) -> None:
    path = tmp_path / "jobs.sqlite3"
    clock = _Clock(datetime(2026, 8, 28, 9, 30, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(path, clock=clock)
    request = DataSyncJobRequest(scope=_scope(), refresh=False, allow_network=True)
    barrier = Barrier(20)

    def submit(index: int):
        barrier.wait()
        return repository.submit(
            request,
            "same-key",
            request_id=f"{index:032x}",
        )

    with ThreadPoolExecutor(max_workers=20) as executor:
        receipts = tuple(executor.map(submit, range(20)))

    assert len({receipt.job_id for receipt in receipts}) == 1
    assert len(set(receipts)) == 1
    assert receipts[0].status is BacktestJobStatus.QUEUED
    assert receipts[0].attempt == 0
    assert receipts[0].revision == 0
    assert _row_count(path, "backtest_job") == 1
    assert _row_count(path, "backtest_job_idempotency") == 1
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            "SELECT request_json, network_authorized_at, request_id, claim_token FROM backtest_job"
        ).fetchone()
    assert row is not None
    payload = json.loads(str(row[0]))
    assert payload["allowNetwork"] is True
    assert set(payload) == {"allowNetwork", "kind", "refresh", "scope"}
    assert set(payload["scope"]) == {
        "adjustmentPolicy",
        "end",
        "historicalProfile",
        "start",
        "symbols",
        "warmupStart",
    }
    assert str(row[1]) == "2026-08-28T09:30:00.000000+08:00"
    assert str(row[2]) in {f"{index:032x}" for index in range(20)}
    assert row[3] is None
    persisted = str(row[0]).lower()
    assert not any(
        forbidden in persisted
        for forbidden in ("credential", "token", "password", "database_path", "claim_token")
    )


def test_same_key_conflict_adds_nothing_and_active_operation_reuses_one_job(
    tmp_path: Path,
) -> None:
    repository = BacktestJobRepository(tmp_path / "admission.sqlite3")
    original = DatasetVerifyJobRequest(scope=_scope(day=21))
    changed = DatasetVerifyJobRequest(scope=_scope(day=22))

    first = repository.submit(original, "stable-key")
    with pytest.raises(JobAdmissionError) as conflict:
        repository.submit(changed, "stable-key")
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    assert len(repository.list_jobs()) == 1

    deduplicated = repository.submit(original, "different-key")
    assert deduplicated == first
    assert len(repository.list_jobs()) == 1


def test_materialized_run_is_reused_immediately_and_same_key_expires_after_14_days(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reuse.sqlite3"
    clock = _Clock(datetime(2026, 8, 28, 10, 0, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(path, clock=clock)
    result_store = BacktestResultStore(path)
    run_input = _run_input("reuse")
    report_hash = _materialize_run(result_store, run_input)
    request = BacktestRunJobRequest(run_input=run_input)

    first = repository.submit(request, "run-key")
    assert first.status is BacktestJobStatus.COMPLETED
    assert first.run_id == run_input.run_id
    assert first.dataset_hash == run_input.dataset_hash
    assert first.reused is True
    assert first.attempt == 0
    assert first.revision == 0
    view = repository.get(first.job_id)
    assert view is not None
    assert view.result is not None
    assert view.result.report_hash == report_hash

    audited_request = BacktestRunJobRequest(
        run_input=run_input.model_copy(
            update={"plan_version_id": UUID("12345678-1234-4123-8123-123456789abc")}
        )
    )
    audited = repository.submit(audited_request, "audited-run-key")
    assert audited.job_id != first.job_id
    assert audited.run_id == first.run_id
    assert audited.reused is True

    clock.advance(timedelta(days=14))
    assert repository.submit(request, "run-key") == first
    clock.advance(timedelta(microseconds=1))
    after_expiry = repository.submit(request, "run-key")
    assert after_expiry.job_id != first.job_id
    assert after_expiry.status is BacktestJobStatus.COMPLETED
    assert after_expiry.reused is True
    assert _row_count(path, "backtest_job") == 3
    assert _row_count(path, "backtest_job_idempotency") == 2


def test_single_unfinished_task_and_history_list_bounds(tmp_path: Path) -> None:
    repository = BacktestJobRepository(tmp_path / "capacity.sqlite3")
    first = repository.submit(DatasetVerifyJobRequest(scope=_scope()), "first")
    with pytest.raises(JobAdmissionError) as busy:
        repository.submit(DatasetVerifyJobRequest(scope=_scope(day=21)), "second")
    assert busy.value.code == "BACKTEST_BUSY"
    assert tuple(item.job_id for item in repository.list_jobs(limit=100)) == (first.job_id,)
    with pytest.raises(ValueError, match="limit"):
        repository.list_jobs(limit=101)


def test_strict_requests_bounds_and_each_sync_job_owns_its_authorization(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authorization.sqlite3"
    clock = _Clock(datetime(2026, 8, 28, 11, 0, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(path, clock=clock)

    with pytest.raises(ValidationError):
        DataSyncJobRequest.model_validate(
            {
                "scope": _scope().model_dump(mode="python"),
                "refresh": False,
                "allow_network": False,
            }
        )
    for forbidden in ("credential", "database_path", "claim_token"):
        payload = {
            "scope": _scope().model_dump(mode="python"),
            "refresh": False,
            "allow_network": True,
            forbidden: "must-not-persist",
        }
        with pytest.raises(ValidationError):
            DataSyncJobRequest.model_validate(payload)
    with pytest.raises(ValueError, match="request_id"):
        repository.submit(
            DataSyncJobRequest(scope=_scope(day=3), refresh=False, allow_network=True),
            "missing-request-id",
        )

    first = repository.submit(
        DataSyncJobRequest(scope=_scope(day=4), refresh=False, allow_network=True),
        "sync-one",
        request_id="1" * 32,
    )
    repository.request_cancel(first.job_id, "finish-first")
    clock.advance(timedelta(seconds=1))
    second = repository.submit(
        DataSyncJobRequest(scope=_scope(day=5), refresh=False, allow_network=True),
        "sync-two",
        request_id="2" * 32,
    )
    assert first.job_id != second.job_id
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT request_json, network_authorized_at, request_id "
            "FROM backtest_job WHERE kind = 'DATA_SYNC' ORDER BY created_at"
        ).fetchall()
    assert tuple(row[1:] for row in rows) == (
        ("2026-08-28T11:00:00.000000+08:00", "1" * 32),
        ("2026-08-28T11:00:01.000000+08:00", "2" * 32),
    )
    assert all(len(str(row[0]).encode("utf-8")) <= MAX_JOB_REQUEST_BYTES for row in rows)
    assert MAX_JOB_REQUEST_BYTES == 256 * 1024
    assert MAX_JOB_ERROR_CHARACTERS == 512
    with closing(sqlite3.connect(path)) as connection:
        job_id = str(connection.execute("SELECT job_id FROM backtest_job LIMIT 1").fetchone()[0])
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE backtest_job SET request_json = ? WHERE job_id = ?",
                ("x" * (MAX_JOB_REQUEST_BYTES + 1), job_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE backtest_job
                SET status = 'FAILED', phase = 'TERMINAL', finished_at = ?,
                    error_code = 'FAILED', error_message = ?
                WHERE job_id = ?
                """,
                (
                    "2026-08-28T11:00:02.000000+08:00",
                    "x" * (MAX_JOB_ERROR_CHARACTERS + 1),
                    job_id,
                ),
            )


def test_job_times_reject_utc_and_persist_canonical_shanghai_text(tmp_path: Path) -> None:
    repository = BacktestJobRepository(
        tmp_path / "utc.sqlite3",
        clock=lambda: datetime(2026, 8, 28, 3, 0, tzinfo=ZoneInfo("UTC")),
    )
    with pytest.raises(ValueError, match="Shanghai"):
        repository.submit(DatasetVerifyJobRequest(scope=_scope()), "utc-clock")


def test_additive_job_schema_requires_verified_migration_for_existing_results(
    tmp_path: Path,
) -> None:
    path = tmp_path / "existing-results.sqlite3"
    BacktestResultStore(path)
    inventory = inspect_result_database(path)
    assert inventory.database_state is DatabaseState.CURRENT
    assert inventory.migration_reasons == ("MISSING_BACKTEST_JOB_SCHEMA",)
    with pytest.raises(
        MigrationPreflightError,
        match="LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION",
    ):
        BacktestJobRepository(path)

    decision = authorize_migration(
        inventory,
        VerifiedBackupFacts(
            source_fingerprint=inventory.source_fingerprint.digest,
            backup_sha256="a" * 64,
            backup_size_bytes=path.stat().st_size,
            verified_at=datetime(2026, 8, 28, 12, 0, tzinfo=_SHANGHAI),
            coordinator_stopped=True,
        ),
    )
    migrated = migrate_result_database(inventory, decision)
    assert migrated.database_state is DatabaseState.CURRENT
    assert migrated.migration_reasons == ()
    repository = BacktestJobRepository(path)
    assert (
        repository.submit(
            DatasetVerifyJobRequest(scope=_scope()),
            "after-migration",
        ).kind
        is BacktestJobKind.DATASET_VERIFY
    )


def test_cancelled_run_resubmission_uses_a_new_job_and_the_same_run_identity(
    tmp_path: Path,
) -> None:
    repository = BacktestJobRepository(tmp_path / "cancelled-run.sqlite3")
    run_input = _run_input("cancelled-rerun")
    request = BacktestRunJobRequest(run_input=run_input)
    first = repository.submit(request, "first-run")

    cancelled = repository.request_cancel(first.job_id, "cancel-first-run")
    assert cancelled.status is BacktestJobStatus.CANCELLED
    second = repository.submit(request, "second-run")

    assert second.job_id != first.job_id
    assert second.run_id == first.run_id == run_input.run_id
    assert second.status is BacktestJobStatus.QUEUED
    assert len(repository.list_jobs()) == 2


def test_submission_binding_replays_persisted_request_and_canonical_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "submission-binding.sqlite3"
    repository = BacktestJobRepository(path)
    request = BacktestRunJobRequest(run_input=_run_input("durable-binding"))

    receipt = repository.submit(request, "durable-submit-key")
    binding = repository.get_submission_binding("durable-submit-key")

    assert isinstance(binding, BacktestJobSubmissionBinding)
    assert binding is not None
    assert binding.receipt == receipt
    with closing(sqlite3.connect(path)) as connection:
        persisted_request = str(
            connection.execute(
                "SELECT request_json FROM backtest_job WHERE job_id = ?",
                (receipt.job_id,),
            ).fetchone()[0]
        )
    assert binding.canonical_request_json == persisted_request
    persisted_payload = json.loads(binding.canonical_request_json)
    assert persisted_payload["kind"] == "BACKTEST_RUN"
    assert (
        persisted_payload["runInput"]["plan_snapshot"]["plan_id"]
        == request.run_input.plan_snapshot.plan_id
    )
    with pytest.raises(FrozenInstanceError):
        binding.canonical_request_json = "{}"  # type: ignore[misc]


def test_submission_binding_conflicts_with_cancel_and_deletes_expiry_atomically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "submission-binding-expiry.sqlite3"
    clock = _Clock(datetime(2026, 8, 28, 13, 0, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(path, clock=clock)
    receipt = repository.submit(
        DatasetVerifyJobRequest(scope=_scope(day=32)),
        "expiring-submit-key",
    )
    repository.request_cancel(receipt.job_id, "expiring-cancel-key")

    clock.advance(timedelta(days=14))
    assert repository.get_submission_binding("expiring-submit-key") is not None
    with pytest.raises(JobAdmissionError) as conflict:
        repository.get_submission_binding("expiring-cancel-key")
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"

    clock.advance(timedelta(microseconds=1))
    assert repository.get_submission_binding("expiring-submit-key") is None
    assert repository.get_submission_binding("expiring-cancel-key") is None
    with closing(sqlite3.connect(path)) as connection:
        remaining = int(
            connection.execute(
                "SELECT COUNT(*) FROM backtest_job_idempotency WHERE idempotency_key IN (?, ?)",
                ("expiring-submit-key", "expiring-cancel-key"),
            ).fetchone()[0]
        )
    assert remaining == 0


def test_run_submission_reservation_expires_with_generation_fencing(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 8, 28, 13, 30, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(tmp_path / "run-reservation.sqlite3", clock=clock)
    intent_json = canonical_json({"datasetHash": "a" * 64, "planVersionId": str(UUID(int=1))})

    first = repository.claim_run_submission(intent_json, "reserved-run-intent")
    pending = repository.claim_run_submission(intent_json, "reserved-run-intent")

    assert isinstance(first, BacktestRunSubmissionReservation)
    assert pending is None

    clock.advance(timedelta(seconds=30))
    still_pending = repository.claim_run_submission(intent_json, "reserved-run-intent")

    assert still_pending is None
    pruned = repository.prune_job_rows(as_of=clock(), remaining_budget=1)
    assert pruned.deleted_count == 1
    replacement = repository.claim_run_submission(intent_json, "reserved-run-intent")

    assert isinstance(replacement, BacktestRunSubmissionReservation)
    assert replacement.claimed_at > first.claimed_at
    assert repository.release_run_submission(first) is False
    assert repository.release_run_submission(replacement) is True


def test_run_submission_reservation_heartbeat_prevents_live_takeover(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 8, 28, 13, 45, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(tmp_path / "renewed-reservation.sqlite3", clock=clock)
    intent_json = canonical_json({"datasetHash": "b" * 64, "planVersionId": str(UUID(int=2))})
    reservation = repository.claim_run_submission(intent_json, "renewed-run-intent")
    assert isinstance(reservation, BacktestRunSubmissionReservation)

    clock.advance(timedelta(seconds=20))
    assert repository.renew_run_submission(reservation)
    clock.advance(timedelta(seconds=15))

    assert repository.claim_run_submission(intent_json, "renewed-run-intent") is None
    assert repository.release_run_submission(reservation)


def test_job_keyset_query_filters_and_freezes_created_membership(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 8, 28, 14, 0, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(tmp_path / "job-keyset.sqlite3", clock=clock)
    oldest = repository.submit(
        DatasetVerifyJobRequest(scope=_scope(day=33)),
        "query-oldest",
    )
    repository.request_cancel(oldest.job_id, "finish-oldest")
    clock.advance(timedelta(seconds=1))
    middle = repository.submit(
        DataSyncJobRequest(scope=_scope(day=34), refresh=False, allow_network=True),
        "query-middle",
        request_id="a" * 32,
    )
    repository.request_cancel(middle.job_id, "finish-middle")
    clock.advance(timedelta(seconds=1))
    run_input = _run_input("query-newest")
    newest = repository.submit(BacktestRunJobRequest(run_input=run_input), "query-newest")

    first_page = repository.query_jobs(
        kinds=(),
        statuses=(BacktestJobStatus.QUEUED, BacktestJobStatus.CANCELLED),
        created_from=datetime(2026, 8, 28, 14, 0, tzinfo=_SHANGHAI),
        created_to=datetime(2026, 8, 28, 14, 0, 2, tzinfo=_SHANGHAI),
        limit=2,
    )
    assert isinstance(first_page, BacktestJobQueryResult)
    assert tuple(item.job_id for item in first_page.items) == (newest.job_id, middle.job_id)
    assert first_page.membership_revision == 5
    assert repository.current_membership_revision() == first_page.membership_revision

    high_water = (first_page.items[0].created_at, first_page.items[0].job_id)
    after = (first_page.items[-1].created_at, first_page.items[-1].job_id)
    repository.request_cancel(newest.job_id, "finish-newest")
    clock.advance(timedelta(seconds=1))
    later = repository.submit(
        DatasetVerifyJobRequest(scope=_scope(day=35)),
        "query-after-high-water",
    )
    second_page = repository.query_jobs(
        statuses=(BacktestJobStatus.QUEUED, BacktestJobStatus.CANCELLED),
        high_water=high_water,
        after=after,
        limit=101,
    )
    assert tuple(item.job_id for item in second_page.items) == (oldest.job_id,)
    assert later.job_id not in {item.job_id for item in second_page.items}
    assert second_page.membership_revision == 7

    by_identity = repository.query_jobs(
        kinds=(BacktestJobKind.DATASET_VERIFY, BacktestJobKind.BACKTEST_RUN),
        statuses=(),
        run_id=run_input.run_id,
        dataset_hash=run_input.dataset_hash,
        limit=101,
    )
    assert tuple(item.job_id for item in by_identity.items) == (newest.job_id,)

    repository.request_cancel(later.job_id, "query-cancel-later")
    mixed_statuses = repository.query_jobs(
        kinds=(BacktestJobKind.DATASET_VERIFY,),
        statuses=(BacktestJobStatus.QUEUED, BacktestJobStatus.CANCELLED),
    )
    assert {item.job_id for item in mixed_statuses.items} == {later.job_id, oldest.job_id}


def _submit_cancelled(repository, request, key):
    receipt = repository.submit(request, key)
    repository.request_cancel(receipt.job_id, "finish-" + key)
    return receipt


def test_job_keyset_query_breaks_equal_created_times_by_descending_job_id(
    tmp_path: Path,
) -> None:
    clock = _Clock(datetime(2026, 8, 28, 14, 30, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(tmp_path / "job-keyset-tie.sqlite3", clock=clock)
    receipts = tuple(
        _submit_cancelled(repository,
            DatasetVerifyJobRequest(scope=_scope(day=36 + index)),
            f"query-tie-{index}",
        )
        for index in range(2)
    )
    ordered_ids = tuple(sorted((receipt.job_id for receipt in receipts), reverse=True))

    first = repository.query_jobs(limit=1)
    assert tuple(item.job_id for item in first.items) == ordered_ids[:1]
    second = repository.query_jobs(
        high_water=(first.items[0].created_at, first.items[0].job_id),
        after=(first.items[0].created_at, first.items[0].job_id),
    )
    assert tuple(item.job_id for item in second.items) == ordered_ids[1:]


def test_job_keyset_insertion_fence_blocks_same_timestamp_late_insert(
    tmp_path: Path,
) -> None:
    clock = _Clock(datetime(2026, 8, 28, 14, 45, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(tmp_path / "job-keyset-insertion.sqlite3", clock=clock)
    oldest = _submit_cancelled(repository,
        DatasetVerifyJobRequest(scope=_scope(day=38)),
        "same-time-oldest",
    )
    newest = _submit_cancelled(repository,
        DatasetVerifyJobRequest(scope=_scope(day=39)),
        "same-time-newest",
    )

    first = repository.query_jobs(limit=1)
    assert tuple(item.job_id for item in first.items) == (newest.job_id,)
    late = _submit_cancelled(repository,
        DatasetVerifyJobRequest(scope=_scope(day=40)),
        "same-time-late",
    )
    second = repository.query_jobs(
        high_water=(first.items[0].created_at, first.items[0].job_id),
        after=(first.items[0].created_at, first.items[0].job_id),
    )

    assert tuple(item.job_id for item in second.items) == (oldest.job_id,)
    assert late.job_id not in {item.job_id for item in second.items}


def test_job_keyset_query_rejects_non_shanghai_boundaries_and_invalid_bounds(
    tmp_path: Path,
) -> None:
    repository = BacktestJobRepository(tmp_path / "job-keyset-validation.sqlite3")
    shanghai = datetime(2026, 8, 28, 15, 0, tzinfo=_SHANGHAI)
    utc = datetime(2026, 8, 28, 7, 0, tzinfo=ZoneInfo("UTC"))

    with pytest.raises(ValueError, match="Shanghai"):
        repository.query_jobs(created_from=utc)
    with pytest.raises(ValueError, match="Shanghai"):
        repository.query_jobs(high_water=(utc, "a" * 32))
    with pytest.raises(ValueError, match="created_from"):
        repository.query_jobs(
            created_from=shanghai + timedelta(seconds=1),
            created_to=shanghai,
        )
    with pytest.raises(ValueError, match="limit"):
        repository.query_jobs(limit=102)
    with pytest.raises(TypeError, match="kinds"):
        repository.query_jobs(kinds=[BacktestJobKind.DATA_SYNC])  # type: ignore[arg-type]
