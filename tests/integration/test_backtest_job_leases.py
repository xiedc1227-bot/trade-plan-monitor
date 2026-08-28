"""Lease, fencing, cancellation, and recovery coverage for durable jobs."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Barrier, Lock
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest.jobs import (
    BacktestDatasetScopeRequest,
    BacktestDataSyncJobResult,
    BacktestJobPhase,
    BacktestJobRepository,
    BacktestJobStatus,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
    JobAdmissionError,
)
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile

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


class _MonotonicClock:
    def __init__(self) -> None:
        self._value = 0.0

    def __call__(self) -> float:
        return self._value

    def advance(self, seconds: float) -> None:
        self._value += seconds


def _scope(day: int = 20) -> BacktestDatasetScopeRequest:
    trade_date = date(2026, 4, 1) + timedelta(days=day)
    return BacktestDatasetScopeRequest(
        symbols=("003043.SZ",),
        start=trade_date,
        end=trade_date,
        warmup_start=trade_date,
        historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        adjustment_policy="NONE",
    )


def _sync_request(day: int = 20) -> DataSyncJobRequest:
    return DataSyncJobRequest(scope=_scope(day), refresh=False, allow_network=True)


def _token(claim: object) -> str:
    return claim.claim_token.get_secret_value()  # type: ignore[attr-defined]


def _sync_result() -> BacktestDataSyncJobResult:
    return BacktestDataSyncJobResult(
        calendar_rows=1,
        minute_days=1,
        daily_limit_rows=1,
        daily_bar_rows=1,
        network_calls=1,
    )


def test_two_repositories_atomically_claim_one_slot_with_a_thirty_second_lease(
    tmp_path: Path,
) -> None:
    path = tmp_path / "claims.sqlite3"
    clock = _Clock(datetime(2026, 8, 28, 9, 30, tzinfo=_SHANGHAI))
    first = BacktestJobRepository(path, clock=clock)
    second = BacktestJobRepository(path, clock=clock)
    receipt = first.submit(
        _sync_request(),
        "claim-once",
        request_id="1" * 32,
    )
    barrier = Barrier(2)

    def claim(repository: BacktestJobRepository):
        barrier.wait()
        return repository.claim_next()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(executor.map(claim, (first, second)))

    active = tuple(item for item in claims if item is not None)
    assert len(active) == 1
    claimed = active[0]
    assert claimed.job_id == receipt.job_id
    assert claimed.attempt == 1
    assert claimed.lease_expires_at == datetime(2026, 8, 28, 9, 30, 30, tzinfo=_SHANGHAI)
    assert first.claim_next() is None
    view = second.get(receipt.job_id)
    assert view is not None
    assert view.status is BacktestJobStatus.RUNNING
    assert view.attempt == 1
    assert _token(claimed) not in view.model_dump_json()
    assert _token(claimed) not in repr(view)
    assert "allowNetwork" not in claimed.model_dump_json()
    assert "allowNetwork" not in repr(claimed)
    clock.advance(timedelta(seconds=10))
    assert first.heartbeat(receipt.job_id, _token(claimed))
    clock.advance(timedelta(seconds=29))
    assert second.heartbeat(receipt.job_id, _token(claimed))


def test_recovery_has_exactly_three_claim_generations_and_fences_stale_tokens(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recovery.sqlite3"
    clock = _Clock(datetime(2026, 8, 28, 10, 0, tzinfo=_SHANGHAI))
    first = BacktestJobRepository(path, clock=clock)
    second = BacktestJobRepository(path, clock=clock)
    receipt = first.submit(
        _sync_request(day=21),
        "recover-sync",
        request_id="2" * 32,
    )

    claim_one = first.claim_next()
    assert claim_one is not None
    clock.advance(timedelta(seconds=30))
    assert first.heartbeat(receipt.job_id, _token(claim_one)) is False

    claim_two = second.recover_expired()
    assert claim_two is not None
    assert claim_two.job_id == receipt.job_id
    assert claim_two.attempt == 2
    assert _token(claim_two) != _token(claim_one)
    assert (
        first.update_progress(
            receipt.job_id,
            _token(claim_one),
            phase=BacktestJobPhase.SYNCING_DATA,
            completed_units=1,
            total_units=2,
        )
        is False
    )
    assert first.complete(receipt.job_id, _token(claim_one), _sync_result()) is False
    assert first.fail(receipt.job_id, _token(claim_one), "STALE", "stale") is False
    assert first.acknowledge_cancel(receipt.job_id, _token(claim_one)) is False

    clock.advance(timedelta(seconds=30))
    claim_three = first.recover_expired()
    assert claim_three is not None
    assert claim_three.attempt == 3
    assert len({_token(claim_one), _token(claim_two), _token(claim_three)}) == 3

    clock.advance(timedelta(seconds=30))
    assert second.recover_expired() is None
    exhausted = first.get(receipt.job_id)
    assert exhausted is not None
    assert exhausted.status is BacktestJobStatus.FAILED
    assert exhausted.attempt == 3
    assert exhausted.error_code == "WORKER_RECOVERY_EXHAUSTED"
    assert exhausted.finished_at == datetime(2026, 8, 28, 10, 1, 30, tzinfo=_SHANGHAI)


def test_sync_recovery_fails_closed_if_persisted_network_authorization_is_lost(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authorization-recovery.sqlite3"
    clock = _Clock(datetime(2026, 8, 28, 10, 30, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(path, clock=clock)
    receipt = repository.submit(
        _sync_request(day=27),
        "authorization-recovery",
        request_id="9" * 32,
    )
    claim = repository.claim_next()
    assert claim is not None
    with closing(sqlite3.connect(path)) as connection:
        request_payload = json.loads(
            str(
                connection.execute(
                    "SELECT request_json FROM backtest_job WHERE job_id = ?",
                    (receipt.job_id,),
                ).fetchone()[0]
            )
        )
        request_payload["allowNetwork"] = False
        connection.execute(
            "UPDATE backtest_job SET request_json = ? WHERE job_id = ?",
            (
                json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")),
                receipt.job_id,
            ),
        )
        connection.commit()
    clock.advance(timedelta(seconds=30))

    assert repository.recover_expired() is None
    failed = repository.get(receipt.job_id)
    assert failed is not None
    assert failed.status is BacktestJobStatus.FAILED
    assert failed.error_code == "NETWORK_AUTHORIZATION_MISSING"
    assert failed.attempt == 1


def test_progress_is_monotonic_and_throttled_by_an_injected_monotonic_clock(
    tmp_path: Path,
) -> None:
    wall_clock = _Clock(datetime(2026, 8, 28, 11, 0, tzinfo=_SHANGHAI))
    monotonic_clock = _MonotonicClock()
    repository = BacktestJobRepository(
        tmp_path / "progress.sqlite3",
        clock=wall_clock,
        monotonic_clock=monotonic_clock,
    )
    receipt = repository.submit(
        _sync_request(day=22),
        "progress-sync",
        request_id="3" * 32,
    )
    claim = repository.claim_next()
    assert claim is not None
    token = _token(claim)

    assert repository.update_progress(
        receipt.job_id,
        token,
        phase=BacktestJobPhase.SYNCING_DATA,
        completed_units=1,
        total_units=10,
    )
    assert not repository.update_progress(
        receipt.job_id,
        token,
        phase=BacktestJobPhase.SYNCING_DATA,
        completed_units=2,
        total_units=10,
    )
    monotonic_clock.advance(0.999)
    assert not repository.update_progress(
        receipt.job_id,
        token,
        phase=BacktestJobPhase.SYNCING_DATA,
        completed_units=3,
        total_units=10,
    )
    monotonic_clock.advance(0.001)
    wall_clock.advance(timedelta(seconds=1))
    assert repository.update_progress(
        receipt.job_id,
        token,
        phase=BacktestJobPhase.SYNCING_DATA,
        completed_units=3,
        total_units=10,
    )
    with pytest.raises(ValueError, match="monotonic"):
        repository.update_progress(
            receipt.job_id,
            token,
            phase=BacktestJobPhase.SYNCING_DATA,
            completed_units=2,
            total_units=10,
        )
    assert repository.update_progress(
        receipt.job_id,
        token,
        phase=BacktestJobPhase.FINALIZING,
        completed_units=4,
        total_units=10,
    )
    view = repository.get(receipt.job_id)
    assert view is not None
    assert view.progress.phase is BacktestJobPhase.FINALIZING
    assert view.progress.completed_units == 4
    assert view.progress.updated_at == datetime(2026, 8, 28, 11, 0, 1, tzinfo=_SHANGHAI)


def test_cancel_replays_original_response_and_current_claim_owns_acknowledgement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cancel.sqlite3"
    clock = _Clock(datetime(2026, 8, 28, 12, 0, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(path, clock=clock)
    receipt = repository.submit(
        _sync_request(day=23),
        "running-sync",
        request_id="4" * 32,
    )
    claim = repository.claim_next()
    assert claim is not None

    clock.advance(timedelta(seconds=30))
    recovered = repository.recover_expired()
    assert recovered is not None

    cancellation = repository.request_cancel(receipt.job_id, "cancel-running")
    assert cancellation.status is BacktestJobStatus.CANCEL_REQUESTED
    assert repository.claim_next() is None
    assert repository.request_cancel(receipt.job_id, "cancel-running") == cancellation
    assert repository.acknowledge_cancel(receipt.job_id, _token(claim)) is False
    assert repository.acknowledge_cancel(receipt.job_id, _token(recovered)) is True
    cancelled = repository.get(receipt.job_id)
    assert cancelled is not None
    assert cancelled.status is BacktestJobStatus.CANCELLED
    assert repository.request_cancel(receipt.job_id, "cancel-running") == cancellation

    queued = repository.submit(
        DatasetVerifyJobRequest(scope=_scope(day=24)),
        "queued-verify",
    )
    queued_cancel = repository.request_cancel(queued.job_id, "cancel-queued")
    assert queued_cancel.status is BacktestJobStatus.CANCELLED
    assert queued_cancel.attempt == 0
    with pytest.raises(JobAdmissionError) as conflict:
        repository.request_cancel(receipt.job_id, "queued-verify")
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"
    clock.advance(timedelta(days=14))
    assert repository.request_cancel(queued.job_id, "cancel-queued") == queued_cancel
    clock.advance(timedelta(microseconds=1))
    renewed = repository.request_cancel(queued.job_id, "cancel-queued")
    assert renewed.status is BacktestJobStatus.CANCELLED
    assert renewed.responded_at != queued_cancel.responded_at


def test_expired_cancel_request_recovers_to_cancelled_without_publication(
    tmp_path: Path,
) -> None:
    clock = _Clock(datetime(2026, 8, 28, 13, 0, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(tmp_path / "cancel-recovery.sqlite3", clock=clock)
    receipt = repository.submit(
        _sync_request(day=25),
        "cancel-recovery",
        request_id="5" * 32,
    )
    claim = repository.claim_next()
    assert claim is not None
    original = repository.request_cancel(receipt.job_id, "cancel-recovery-key")
    clock.advance(timedelta(seconds=30))

    assert repository.recover_expired() is None
    view = repository.get(receipt.job_id)
    assert view is not None
    assert view.status is BacktestJobStatus.CANCELLED
    assert view.result is None
    assert repository.acknowledge_cancel(receipt.job_id, _token(claim)) is False
    assert repository.request_cancel(receipt.job_id, "cancel-recovery-key") == original


def test_current_claim_completes_and_submission_replay_expires_from_finished_at(
    tmp_path: Path,
) -> None:
    clock = _Clock(datetime(2026, 8, 28, 14, 0, tzinfo=_SHANGHAI))
    repository = BacktestJobRepository(tmp_path / "complete.sqlite3", clock=clock)
    request = _sync_request(day=26)
    receipt = repository.submit(
        request,
        "complete-sync",
        request_id="6" * 32,
    )
    claim = repository.claim_next()
    assert claim is not None

    assert repository.complete(receipt.job_id, _token(claim), _sync_result())
    view = repository.get(receipt.job_id)
    assert view is not None
    assert view.status is BacktestJobStatus.COMPLETED
    assert view.result == _sync_result()
    assert view.finished_at == datetime(2026, 8, 28, 14, 0, tzinfo=_SHANGHAI)
    assert not repository.heartbeat(receipt.job_id, _token(claim))

    clock.advance(timedelta(days=14))
    assert repository.submit(request, "complete-sync", request_id="7" * 32) == receipt
    clock.advance(timedelta(microseconds=1))
    renewed = repository.submit(request, "complete-sync", request_id="8" * 32)
    assert renewed.job_id != receipt.job_id
    assert renewed.status is BacktestJobStatus.QUEUED
