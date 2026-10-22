"""Real SQLite snapshots under experimental, shared byte admission."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Condition, Event
from time import monotonic

import pytest
from scripts.experiments.bounded_benchmark import frozen_engine
from scripts.experiments.global_evidence_budget import MIB, Budget, BudgetUnavailable
from scripts.experiments.global_evidence_flights import Flights
from scripts.experiments.global_evidence_scan import Scan
from test_bounded_validation_transport import inputs

from trade_plan_monitor.runtime.market_indexes import DASHBOARD_INDEX_CODES
from trade_plan_monitor.state.index_evidence import HEAD_FIELDS, PAYLOAD_FIELDS
from trade_plan_monitor.state.projections import ProjectionError, _latest_index_records


def database(tmp_path, rows):
    import sqlite3
    path = tmp_path/'monitor.sqlite3'
    connection = sqlite3.connect(path)
    connection.execute('pragma journal_mode=WAL')
    for name, fields in [('market_index_snapshot_head', HEAD_FIELDS),
                         ('market_index_snapshot', PAYLOAD_FIELDS)]:
        connection.execute('create table '+name+' ('+','.join(fields)+')')
    for row in rows:
        connection.execute('insert into market_index_snapshot_head values ('
                           + ','.join('?' for _ in row.head)+')', row.head)
        if row.payload is not None:
            payload = list(row.payload)
            if row.json_is_text:
                payload[9] = payload[9].decode('utf8')
            connection.execute('insert into market_index_snapshot values ('
                               + ','.join('?' for _ in payload)+')', payload)
    connection.commit()
    connection.close()
    return frozen_engine(path)


def scan(connection, budget, **kw):
    return Scan(connection, budget, inputs(1)[0].head[0], DASHBOARD_INDEX_CODES, **kw)


def test_real_scan_is_literal_and_query_requires_live_lease(tmp_path):
    rows = inputs()
    engine, budget = database(tmp_path, rows), Budget()
    with engine.connect() as connection, connection.begin():
        reader = scan(connection, budget)
        with reader.metadata():
            raw, size, count = reader.measure()
            assert raw >= sum(r.retained_size() for r in rows) and count == len(rows)
            with reader.acquire(size, 'scan') as work:
                seen = []
                reader.before_payload = lambda: seen.append(budget.snapshot()['categories']['scan'])
                actual = tuple(reader.rows(work))
                assert all(a.exact(b) for a, b in zip(rows, actual, strict=True))
                assert seen and min(seen) == size
            with pytest.raises(BudgetUnavailable):
                tuple(reader.rows(work))
    engine.dispose()
    budget.drain()


@pytest.mark.parametrize('text', [True, False])
def test_embedded_nul_unicode_and_blob_are_preserved_before_validation(tmp_path, text):
    row = inputs(1)[0]
    values = list(row.payload)
    values[9] = '中\x00文'.encode() if text else b'\xff\x00literal'
    row = replace(row, payload=tuple(values), json_is_text=text)
    engine, budget = database(tmp_path, (row,)), Budget()
    with engine.connect() as connection, connection.begin():
        reader = scan(connection, budget)
        with reader.metadata():
            _, size, _ = reader.measure()
            with reader.acquire(size, 'scan') as work:
                actual = tuple(reader.rows(work))
                assert len(actual) == 1 and row.exact(actual[0])
    budget.drain()
    engine.dispose()


@pytest.mark.parametrize('damage', ['missing', 'canonical', 'head', 'json'])
def test_old_tamper_preserves_original_rejection_and_releases(tmp_path, damage):
    rows = list(inputs())
    if damage == 'missing':
        rows[0] = replace(rows[0], payload=None)
    elif damage == 'head':
        h = list(rows[0].head)
        h[4] += 1
        rows[0] = replace(rows[0], head=tuple(h))
    else:
        p = list(rows[0].payload)
        p[9] = p[9]+b' ' if damage == 'canonical' else b'{}'
        rows[0] = replace(rows[0], payload=tuple(p))
    engine, budget = database(tmp_path, rows), Budget()
    flights = Flights(budget)
    with engine.connect() as connection, connection.begin(), pytest.raises(ProjectionError):
        flights.run(('s',), scan(connection, budget),
                    lambda values: _latest_index_records(values, DASHBOARD_INDEX_CODES),
                    DASHBOARD_INDEX_CODES)
    flights.drain()
    engine.dispose()


def test_eight_equal_readers_share_without_leader_waiting_for_unadmitted_work(tmp_path):
    engine, budget = database(tmp_path, inputs()), Budget()
    flights, entered, release = Flights(budget), Event(), Event()
    def verify(values):
        result = _latest_index_records(values, DASHBOARD_INDEX_CODES)
        entered.set()
        assert release.wait(5)
        return result
    def run():
        with engine.connect() as connection, connection.begin():
            return flights.run(('s',), scan(connection, budget), verify, DASHBOARD_INDEX_CODES)
    with ThreadPoolExecutor(8) as pool:
        leader = pool.submit(run)
        assert entered.wait(5)
        others = [pool.submit(run) for _ in range(7)]
        try:
            with flights.condition:
                assert flights.condition.wait_for(lambda: flights.stats['joins'] == 7, timeout=5)
            assert budget.snapshot()['used'] > 0
        finally:
            release.set()
        assert all(f.result(timeout=5) == leader.result() for f in others)
    assert flights.stats['proofs'] == 1
    flights.drain()
    engine.dispose()


def test_budget_fallback_still_validates_complete_stream(tmp_path):
    rows = inputs(50)
    engine, budget = database(tmp_path, rows), Budget(3*MIB)
    flights = Flights(budget)
    with engine.connect() as connection, connection.begin():
        value = flights.run(('s',), scan(connection, budget),
                            lambda values: _latest_index_records(values, DASHBOARD_INDEX_CODES),
                            DASHBOARD_INDEX_CODES)
    assert value == _latest_index_records(iter(rows), DASHBOARD_INDEX_CODES)
    assert flights.stats['fallbacks'] == 1
    flights.drain()
    engine.dispose()


def test_oversized_text_is_rejected_before_payload_query(tmp_path):
    row = inputs(1)[0]
    p = list(row.payload)
    p[9] = b'x'*(16*MIB)
    engine, budget = database(tmp_path, [replace(row, payload=tuple(p))]), Budget()
    with engine.connect() as connection, connection.begin():
        reader = scan(connection, budget)
        with pytest.raises(BudgetUnavailable):
            Flights(budget).run(('s',), reader, tuple, DASHBOARD_INDEX_CODES)
        assert reader.stats['payloadQueries'] == 0
    budget.drain()
    engine.dispose()


def test_expired_or_cancelled_reader_does_not_execute_payload(tmp_path):
    engine, budget = database(tmp_path, inputs()), Budget()
    for expired in (False, True):
        cancelled = Event()
        if not expired:
            cancelled.set()
        with engine.connect() as connection, connection.begin():
            reader = scan(connection, budget, cancelled=cancelled,
                          deadline=monotonic()-1 if expired else monotonic()+15)
            with pytest.raises(BudgetUnavailable):
                Flights(budget).run(('s',), reader, tuple, DASHBOARD_INDEX_CODES)
            assert reader.stats['payloadQueries'] == 0
    engine.dispose()
    budget.drain()


def test_observer_cancellation_keeps_physical_lease_and_storage_fence(tmp_path):
    from trade_plan_monitor.web.monitor_read_ownership import MonitorReadOwner
    engine, budget = database(tmp_path, inputs()), Budget()
    flights, entered, release = Flights(budget), Event(), Event()
    def run():
        def verify(values):
            result = _latest_index_records(values, DASHBOARD_INDEX_CODES)
            entered.set()
            assert release.wait(5)
            return result
        with engine.connect() as connection, connection.begin():
            return flights.run(('s',), scan(connection, budget), verify, DASHBOARD_INDEX_CODES)
    async def scenario():
        owner = MonitorReadOwner()
        observer = asyncio.create_task(owner.run(lambda: asyncio.to_thread(run)))
        assert await asyncio.to_thread(entered.wait, 5)
        try:
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            observer.cancel()
            owner.pause_storage('test')
            with pytest.raises(TimeoutError):
                await owner.drain(timeout=0.01)
            assert budget.snapshot()['used'] > 0 and owner.outstanding_work == 1
        finally:
            release.set()
        await owner.drain(timeout=5)
        owner.resume_storage('test')
    asyncio.run(scenario())
    flights.drain()
    engine.dispose()


def test_actual_valid_large_row_exposes_availability_gate(tmp_path):
    from scripts.experiments.global_evidence_large import large_candidate
    row = large_candidate()
    assert len(row.payload[9]) < 16*MIB
    assert _latest_index_records(iter((row,)), DASHBOARD_INDEX_CODES)
    engine, budget = database(tmp_path, (row,)), Budget()
    with engine.connect() as connection, connection.begin():
        reader = scan(connection, budget)
        with pytest.raises(BudgetUnavailable):
            Flights(budget).run(('s',), reader,
                               lambda v: _latest_index_records(v, DASHBOARD_INDEX_CODES),
                               DASHBOARD_INDEX_CODES)
        assert reader.stats['payloadQueries'] == 0
    engine.dispose()
    budget.drain()


def test_valid_medium_row_falls_back_before_process_submission(tmp_path):
    from scripts.experiments.bounded_transport import ChunkWorker
    from scripts.experiments.global_evidence_large import large_candidate
    row = large_candidate(10)
    engine, budget = database(tmp_path, (row,)), Budget()
    with ChunkWorker() as worker, engine.connect() as connection, connection.begin():
        flights = Flights(budget, worker)
        value = flights.run(('s',), scan(connection, budget),
                            lambda v: _latest_index_records(v, DASHBOARD_INDEX_CODES),
                            DASHBOARD_INDEX_CODES)
        assert value == _latest_index_records(iter((row,)), DASHBOARD_INDEX_CODES)
        assert flights.stats['fallbacks'] == 1 and not worker.last
        flights.drain()
    engine.dispose()


def test_changed_snapshot_releases_comparison_and_revalidates(tmp_path):
    import sqlite3
    engine, budget = database(tmp_path, inputs()), Budget()
    flights, entered, release = Flights(budget), Event(), Event()
    def verify(values):
        result = _latest_index_records(values, DASHBOARD_INDEX_CODES)
        entered.set()
        assert release.wait(5)
        return result
    def read():
        with engine.connect() as connection, connection.begin():
            return flights.run(('s',), scan(connection, budget), verify, DASHBOARD_INDEX_CODES)
    with ThreadPoolExecutor(2) as pool:
        leader = pool.submit(read)
        assert entered.wait(5)
        with sqlite3.connect(tmp_path/'monitor.sqlite3') as writer:
            writer.execute("update market_index_snapshot set snapshot_json=snapshot_json || ' '")
        follower = pool.submit(read)
        try:
            with flights.condition:
                assert flights.condition.wait_for(lambda: flights.stats['mismatches'] == 1, 5)
        finally:
            release.set()
        assert leader.result(timeout=5)
        with pytest.raises(ProjectionError):
            follower.result(timeout=5)
    assert flights.stats['proofs'] == 2 and flights.stats['joins'] == 0
    flights.drain()
    engine.dispose()


def test_cursor_cleanup_failure_retains_lease(tmp_path, monkeypatch):
    engine, budget = database(tmp_path, inputs()), Budget()
    with engine.connect() as connection, connection.begin():
        reader = scan(connection, budget)
        with reader.metadata():
            _, size, _ = reader.measure()
            with reader.acquire(size, 'scan') as work:
                original = connection.exec_driver_sql
                def execute(sql, parameters=()):
                    result = original(sql, parameters)
                    if ' and h.rowid in (' in sql:
                        close = result.close
                        def failed_close():
                            close()
                            raise OSError('injected cursor cleanup failure')
                        monkeypatch.setattr(result, 'close', failed_close)
                    return result
                monkeypatch.setattr(connection, 'exec_driver_sql', execute)
                with pytest.raises(OSError):
                    tuple(reader.rows(work))
            assert work.failed and budget.snapshot()['used'] >= size
    with pytest.raises(TimeoutError):
        budget.drain(0.01)
    engine.dispose()


def test_large_comparison_workspaces_do_not_block_collecting_leader(tmp_path):
    engine, budget = database(tmp_path, inputs()), Budget()
    flights = Flights(budget)
    collecting, collect_release, validating, proof_release = (Event() for _ in range(4))
    counted, measured = Condition(), 0
    def run(leader=False):
        nonlocal measured
        with engine.connect() as connection, connection.begin():
            reader = scan(connection, budget)
            original = reader.measure
            def measure():
                nonlocal measured
                raw, _, count = original()
                with counted:
                    measured += 1
                    counted.notify_all()
                return raw, 16*MIB, count
            reader.measure = measure
            if leader:
                def gate():
                    collecting.set()
                    assert collect_release.wait(5)
                reader.before_payload = gate
            def verify(values):
                result = _latest_index_records(values, DASHBOARD_INDEX_CODES)
                validating.set()
                assert proof_release.wait(5)
                return result
            return flights.run(('s',), reader, verify, DASHBOARD_INDEX_CODES)
    with ThreadPoolExecutor(8) as pool:
        first = pool.submit(run, True)
        assert collecting.wait(5)
        others = [pool.submit(run) for _ in range(7)]
        try:
            with counted:
                assert counted.wait_for(lambda: measured == 8, 5)
            # Waiting collectors own metadata only, not expensive comparison workspaces.
            assert budget.snapshot()['categories']['scan'] == 16*MIB
            collect_release.set()
            assert validating.wait(5)
            with flights.condition:
                assert flights.condition.wait_for(lambda: flights.stats['joins'] == 7, 5)
        finally:
            collect_release.set()
            proof_release.set()
        assert all(f.result(timeout=5) == first.result() for f in others)
    flights.drain()
    engine.dispose()


def test_child_cleanup_debt_is_not_refunded_by_global_ledger(tmp_path):
    class FailedWorker:
        retained_bytes = 1
        def validate(self, *_):
            raise OSError('child cleanup failed')
    engine, budget = database(tmp_path, inputs()), Budget()
    flights = Flights(budget, FailedWorker())
    with engine.connect() as connection, connection.begin(), pytest.raises(OSError):
        flights.run(('s',), scan(connection, budget), tuple, DASHBOARD_INDEX_CODES)
    assert budget.snapshot()['used'] > 0 and budget.closing
    with pytest.raises(TimeoutError):
        flights.drain(0.01)
    engine.dispose()
