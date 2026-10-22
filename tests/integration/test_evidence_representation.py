"""Differential checks for isolated representation and scan stages."""
import pytest
import test_global_evidence_admission as reference
from scripts.experiments.evidence_representation import ByteScan, OrderedScan


@pytest.mark.parametrize('scan_type', [ByteScan, OrderedScan])
@pytest.mark.parametrize('case', [
    'test_real_scan_is_literal_and_query_requires_live_lease',
    'test_budget_fallback_still_validates_complete_stream',
    'test_oversized_text_is_rejected_before_payload_query',
    'test_expired_or_cancelled_reader_does_not_execute_payload',
    'test_actual_valid_large_row_exposes_availability_gate',
    'test_changed_snapshot_releases_comparison_and_revalidates',
    'test_observer_cancellation_keeps_physical_lease_and_storage_fence',
    'test_child_cleanup_debt_is_not_refunded_by_global_ledger',
])
def test_existing_contract(tmp_path, monkeypatch, scan_type, case):
    monkeypatch.setattr(reference, 'Scan', scan_type)
    getattr(reference, case)(tmp_path)

@pytest.mark.parametrize('scan_type', [ByteScan, OrderedScan])
@pytest.mark.parametrize('damage', ['missing', 'canonical', 'head', 'json'])
def test_tamper(tmp_path, monkeypatch, scan_type, damage):
    monkeypatch.setattr(reference, 'Scan', scan_type)
    reference.test_old_tamper_preserves_original_rejection_and_releases(tmp_path, damage)

@pytest.mark.parametrize('scan_type', [ByteScan, OrderedScan])
@pytest.mark.parametrize('text', [False, True])
def test_literal_types(tmp_path, monkeypatch, scan_type, text):
    monkeypatch.setattr(reference, 'Scan', scan_type)
    reference.test_embedded_nul_unicode_and_blob_are_preserved_before_validation(tmp_path, text)


def test_funded_collection_cohort_precedes_fast_proof(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from scripts.experiments.evidence_cohort import Flights
    from scripts.experiments.global_evidence_budget import Budget

    from trade_plan_monitor.runtime.market_indexes import DASHBOARD_INDEX_CODES as codes
    from trade_plan_monitor.state.projections import _latest_index_records
    engine, budget = reference.database(tmp_path, reference.inputs()), Budget()
    flights = Flights(budget)
    collecting, release = Event(), Event()
    def read(leader=False):
        with engine.connect() as connection, connection.begin():
            scan = OrderedScan(connection, budget, reference.inputs(1)[0].head[0], codes)
            if leader:
                def gate():
                    collecting.set()
                    assert release.wait(5)
                scan.before_payload = gate
            return flights.run(('scope',), scan,
                               lambda rows: _latest_index_records(rows, codes), codes)
    with ThreadPoolExecutor(8) as pool:
        first = pool.submit(read, True)
        assert collecting.wait(5)
        others = [pool.submit(read) for _ in range(7)]
        try:
            with flights.condition:
                assert flights.condition.wait_for(lambda: len(flights.waiting) == 7, 5)
        finally:
            release.set()
        assert all(f.result(timeout=10) == first.result() for f in others)
    assert flights.stats['proofs'] == 1 and flights.stats['joins'] == 7
    physical = next(e['at'] for e in flights.events if e['name'] == 'physical.start')
    assert all(e['at'] <= physical for e in flights.events if e['name'] == 'compare.end')
    assert not flights.pending and not flights.prepaid
    flights.drain()
    engine.dispose()

@pytest.mark.parametrize('case', [
    'test_changed_snapshot_releases_comparison_and_revalidates',
    'test_expired_or_cancelled_reader_does_not_execute_payload',
    'test_large_comparison_workspaces_do_not_block_collecting_leader',
    'test_observer_cancellation_keeps_physical_lease_and_storage_fence',
    'test_child_cleanup_debt_is_not_refunded_by_global_ledger',
])
def test_cohort_lifecycle(tmp_path, monkeypatch, case):
    from scripts.experiments.evidence_cohort import Flights
    monkeypatch.setattr(reference, 'Flights', Flights)
    monkeypatch.setattr(reference, 'Scan', OrderedScan)
    getattr(reference, case)(tmp_path)

@pytest.mark.parametrize('scan_type', [ByteScan, OrderedScan])
def test_failed_cursor_cleanup_keeps_budget(tmp_path, monkeypatch, scan_type):
    from scripts.experiments.global_evidence_budget import Budget
    engine, budget = reference.database(tmp_path, reference.inputs()), Budget()
    with engine.connect() as connection, connection.begin():
        scan = scan_type(connection, budget, reference.inputs(1)[0].head[0],
                         reference.DASHBOARD_INDEX_CODES)
        with scan.metadata():
            _, size, _ = scan.measure()
            execute = connection.exec_driver_sql
            def faulty(sql, params=()):
                result = execute(sql, params)
                if 'cast(p.snapshot_json as blob)' in sql:
                    close = result.close
                    def fail():
                        close()
                        raise OSError('cleanup failure')
                    monkeypatch.setattr(result, 'close', fail)
                return result
            monkeypatch.setattr(connection, 'exec_driver_sql', faulty)
            with scan.acquire(size, 'scan') as work:
                with pytest.raises(OSError):
                    tuple(scan.rows(work))
            assert work.failed and budget.snapshot()['used'] >= size
    with pytest.raises(TimeoutError):
        budget.drain(0.01)
    engine.dispose()


def test_invalid_utf8_text_remains_invalid(tmp_path):
    import sqlite3

    from scripts.experiments.global_evidence_budget import Budget

    from trade_plan_monitor.state.projections import _latest_index_records
    engine = reference.database(tmp_path, reference.inputs())
    with sqlite3.connect(tmp_path/'monitor.sqlite3') as writer:
        writer.execute("update market_index_snapshot set snapshot_json=cast(x'ff00' as text)")
    budget = Budget()
    with engine.connect() as connection, connection.begin():
        reader = OrderedScan(connection, budget, reference.inputs(1)[0].head[0],
                             reference.DASHBOARD_INDEX_CODES)
        with reader.metadata():
            _, size, _ = reader.measure()
            with reader.acquire(size, 'scan') as work:
                with pytest.raises(UnicodeError):
                    _latest_index_records(reader.rows(work), reference.DASHBOARD_INDEX_CODES)
    budget.drain()
    engine.dispose()


@pytest.mark.parametrize('reason', ['cancel', 'deadline'])
def test_prepaid_follower_loses_admission_without_leaking_credit(tmp_path, reason):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from scripts.experiments.evidence_cohort import Flights
    from scripts.experiments.global_evidence_budget import Budget, BudgetUnavailable

    engine, budget = reference.database(tmp_path, reference.inputs()), Budget()
    flights, collecting, release = Flights(budget), Event(), Event()
    funded = flights.fund
    affected = []

    def expire_after_funding(scope):
        funded(scope)
        assert len(flights.prepaid) == 1
        for _, reader, _ in flights.waiting.values():
            affected.append(reader)
            if reason == 'cancel':
                reader.cancelled.set()
            else:
                reader.deadline = 0
    flights.fund = expire_after_funding

    def read(leader=False):
        with engine.connect() as connection, connection.begin():
            reader = OrderedScan(connection, budget, reference.inputs(1)[0].head[0],
                                 reference.DASHBOARD_INDEX_CODES, cancelled=Event())
            if leader:
                def gate():
                    collecting.set()
                    assert release.wait(5)
                reader.before_payload = gate
            return flights.run(('scope',), reader, tuple, reference.DASHBOARD_INDEX_CODES)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(read, True)
        assert collecting.wait(5)
        other = pool.submit(read)
        try:
            with flights.condition:
                assert flights.condition.wait_for(lambda: len(flights.waiting) == 1, 5)
        finally:
            release.set()
        assert first.result(timeout=5)
        with pytest.raises(BudgetUnavailable):
            other.result(timeout=5)
    assert affected[0].stats['payloadQueries'] == 0
    assert not flights.prepaid and not flights.pending
    assert flights.stats['proofs'] == 1 and flights.stats['joins'] == 0
    flights.drain()
    engine.dispose()
