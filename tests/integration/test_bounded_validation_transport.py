"""Isolated spawned proof: integrity and owned cleanup, never a service hook."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Event
from zoneinfo import ZoneInfo

import pytest
from scripts.experiments.bounded_transport import ChunkWorker

from trade_plan_monitor.market_index.canonical import verified_market_index_snapshot_json
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot
from trade_plan_monitor.runtime.market_indexes import DASHBOARD_INDEX_CODES
from trade_plan_monitor.state.index_evidence import RawIndexCandidate
from trade_plan_monitor.state.index_evidence_flights import IndexEvidenceFlights
from trade_plan_monitor.state.projections import (
    ProjectionError,
    _latest_index_records,
    _market_index_values,
)


def inputs(count=4):
    now = datetime(2026, 10, 22, 10, tzinfo=ZoneInfo('Asia/Shanghai'))
    rows = []
    for i in range(count):
        at = now + timedelta(minutes=i)
        value = build_market_index_snapshot(
            index_code=DASHBOARD_INDEX_CODES[0], decision_cutoff=at, requests=(),
            five_minute_bars=(), official_daily_bars=(), content_revision=i+1,
            observed_at=at, observed_no_later_than=at,
        )
        from types import SimpleNamespace
        payload = SimpleNamespace(**_market_index_values(
            value, i+1, verified_market_index_snapshot_json(value),
        ))
        head = SimpleNamespace(
            mapping_version=value.mapping_version, index_code=value.index_code.value,
            decision_cutoff=value.decision_cutoff.isoformat(),
            request_set_hash=value.request_set_hash, provider_content_revision=i+1,
            snapshot_hash=value.snapshot_hash, updated_at=at.isoformat(),
        )
        rows.append(RawIndexCandidate.capture(head, payload))
    return tuple(rows)


def test_complete_empty_and_repeated_proofs():
    with ChunkWorker() as worker:
        for rows in ((), inputs(), inputs(1), inputs()):
            result = worker.validate(rows, DASHBOARD_INDEX_CODES)
            assert result == _latest_index_records(iter(rows), DASHBOARD_INDEX_CODES)
            assert worker.retained_bytes == 0 and worker.last['drained']
        process = worker.process
    assert not process.is_alive()


@pytest.mark.parametrize('damage', ['json', 'missing', 'head', 'canonical'])
def test_old_unselected_tamper_is_rejected(damage):
    rows = list(inputs())
    old = rows[0]
    if damage == 'missing':
        rows[0] = replace(old, payload=None)
    elif damage == 'head':
        h = list(old.head)
        h[4] += 1
        rows[0] = replace(old, head=tuple(h))
    else:
        p = list(old.payload)
        p[9] = b'{}' if damage == 'json' else p[9] + b' '
        rows[0] = replace(old, payload=tuple(p))
    with ChunkWorker() as worker:
        with pytest.raises(ProjectionError):
            worker.validate(tuple(rows), DASHBOARD_INDEX_CODES)
        assert worker.retained_bytes == 0


@pytest.mark.parametrize('fault', ['count', 'digest', 'sequence', 'generation', 'truncated'])
def test_incomplete_or_crossed_stream_never_returns_success(fault):
    with ChunkWorker() as worker:
        with pytest.raises(RuntimeError):
            worker.validate(inputs(), DASHBOARD_INDEX_CODES, fault=fault)
        assert worker.retained_bytes == 0


def test_cancelled_follower_does_not_release_physical_lease():
    with ChunkWorker() as worker, ThreadPoolExecutor(3) as pool:
        flights, cancelled = IndexEvidenceFlights(), Event()
        rows, entered, release = inputs(), Event(), Event()

        def verify(values):
            return worker.validate(tuple(values), DASHBOARD_INDEX_CODES,
                                   admitted=entered, parent_gate=release)

        first = pool.submit(flights.run, ('same',), lambda: iter(rows), verify)
        assert entered.wait(5)
        second = pool.submit(flights.run, ('same',), lambda: iter(rows), verify,
                             cancelled=cancelled)
        third = pool.submit(flights.run, ('same',), lambda: iter(rows), verify)
        try:
            with flights._condition:
                assert flights._condition.wait_for(
                    lambda: flights.snapshot()['joins'] == 2, timeout=5,
                )
            cancelled.set()
            with pytest.raises(RuntimeError):
                second.result(timeout=5)
            assert worker.retained_bytes > 0 and not first.done()
            with pytest.raises(TimeoutError):
                flights.drain(timeout=0.01)
        finally:
            release.set()
        assert first.result() == third.result()
        flights.drain(timeout=5)
        assert worker.retained_bytes == flights.snapshot()['retained_bytes'] == 0


@pytest.mark.parametrize('fault', ['crash', 'hang'])
def test_child_fault_quarantines_worker_and_joins_before_release(fault):
    with ChunkWorker(timeout=0.5) as worker:
        with pytest.raises(RuntimeError):
            worker.validate(inputs(), DASHBOARD_INDEX_CODES, fault=fault)
        assert not worker.process.is_alive()
        assert worker.retained_bytes == 0 and worker.broken


def test_cleanup_failure_keeps_reservation(monkeypatch):
    with ChunkWorker() as worker:
        def fail():
            raise OSError('injected cleanup failure')
        monkeypatch.setattr(worker, '_release', fail)
        with pytest.raises(OSError):
            worker.validate(inputs(), DASHBOARD_INDEX_CODES)
        assert worker.retained_bytes > 0


def test_repeated_observer_cancel_keeps_owned_bridge_and_storage_pause():
    from trade_plan_monitor.web.monitor_read_ownership import MonitorReadOwner

    async def scenario(worker):
        owner = MonitorReadOwner()
        entered, release = Event(), Event()

        async def operation():
            return await asyncio.to_thread(worker.validate, inputs(), DASHBOARD_INDEX_CODES,
                                           admitted=entered, parent_gate=release)

        observer = asyncio.create_task(owner.run(operation))
        assert await asyncio.to_thread(entered.wait, 5)
        try:
            observer.cancel('original')
            with pytest.raises(asyncio.CancelledError):
                await observer
            observer.cancel('again')
            owner.pause_storage('retention')
            with pytest.raises(TimeoutError):
                await owner.drain(timeout=0.01)
            assert owner.outstanding_work == 1 and worker.retained_bytes > 0
            assert owner._storage_pauses == {'retention'}
        finally:
            release.set()
        await owner.drain(timeout=5)
        owner.resume_storage('retention')
        assert owner.outstanding_work == worker.retained_bytes == 0
        assert not owner._storage_pauses

    with ChunkWorker() as worker:
        asyncio.run(scenario(worker))


def test_real_pipe_oversize_receive_fails_and_sender_is_joined():
    import multiprocessing

    from scripts.experiments.bounded_codec import FRAME

    parent, child = multiprocessing.get_context('spawn').Pipe()
    with ThreadPoolExecutor(1) as pool:
        sending = pool.submit(parent.send_bytes, b'x' * (FRAME+1))
        try:
            with pytest.raises(OSError):
                child.recv_bytes(FRAME)
        finally:
            child.close()
        try:
            sending.result(timeout=5)
        except (OSError, BrokenPipeError):
            pass
        finally:
            parent.close()


def test_encoding_failure_after_start_never_requests_thread_fallback(monkeypatch):
    from scripts.experiments import bounded_transport
    from scripts.experiments.bounded_codec import AdmissionError

    def failed_encoder(_):
        raise AdmissionError('injected encode failure after submission')

    with ChunkWorker() as worker:
        monkeypatch.setattr(bounded_transport, 'encode', failed_encoder)
        with pytest.raises(RuntimeError):
            worker.validate(inputs(), DASHBOARD_INDEX_CODES)
        assert worker.broken and not worker.process.is_alive()
        assert worker.retained_bytes == 0
