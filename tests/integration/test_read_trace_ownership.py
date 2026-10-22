"""Logical callers and physically owned reads must not be conflated."""

import asyncio
from contextvars import ContextVar
from threading import Event

import pytest

from trade_plan_monitor.backtest.thread_lifecycle import (
    BacktestMetadataThread,
    BacktestResultReadThread,
)
from trade_plan_monitor.diagnostics.read_tracing import (
    ReadTraceWindow,
    current_trace,
    read_span,
    read_trace,
)


def test_shared_physical_trace_survives_all_observers_and_drains():
    entered, release = Event(), Event()
    physical_ids, metadata_calls = [], []

    def physical():
        trace = current_trace()
        physical_ids.append(None if trace is None else trace.trace_id)
        with read_span("result.audit", cpu=True):
            entered.set()
            assert release.wait(5)
        return "verified"

    async def scenario():
        window = ReadTraceWindow()
        metadata, results = BacktestMetadataThread(), BacktestResultReadThread()

        async def observer():
            with read_trace("http.result", window=window):
                def metadata_read():
                    trace = current_trace()
                    metadata_calls.append(None if trace is None else trace.trace_id)
                await metadata.read(metadata_read)
                return await results.read_shared(("run", "same-key"), physical)

        a, b = asyncio.create_task(observer()), asyncio.create_task(observer())
        try:
            async with asyncio.timeout(5):
                while not entered.is_set() or len(metadata_calls) < 2 or results._readers < 2:
                    await asyncio.sleep(0)
            a.cancel()
            b.cancel()
            await asyncio.gather(a, b, return_exceptions=True)
            cleanup = asyncio.create_task(results.stop())
            await asyncio.sleep(0)
            assert not cleanup.done()
            assert results.outstanding_work == 1
            assert not any(r['entry'] == 'result.physical' for r in window.records)
            release.set()
            await cleanup
        finally:
            release.set()
            await results.stop()
            await metadata.stop()
        roots = [r for r in window.records if r['entry'] == 'http.result']
        workers = [r for r in window.records if r['entry'] == 'result.physical']
        assert len(roots) == 2 and len(workers) == 1
        assert len(metadata_calls) == len(set(metadata_calls)) == 2
        assert physical_ids == [workers[0]['traceId']]
        assert all(r['status'] == 'cancelled' for r in roots)
        joins = [s for r in roots for s in r['spans'] if s['stage'] == 'result.join']
        assert {s['physicalId'] for s in joins} == set(physical_ids)
        assert sorted(s['joined'] for s in joins) == [False, True]
        assert workers[0]['status'] == 'ok'
        assert any(s['stage'] == 'worker.execute' for s in workers[0]['spans'])
        assert window.active == 0

    asyncio.run(scenario())


def test_queued_physical_read_and_exception_keep_distinct_spans():
    entered, release = Event(), Event()

    async def scenario():
        window, results = ReadTraceWindow(), BacktestResultReadThread()

        def first():
            entered.set()
            assert release.wait(5)

        def broken():
            raise ValueError("private-evidence-details")

        async def read(key, operation):
            with read_trace('http.result', window=window):
                return await results.read_shared((key,), operation)

        a = asyncio.create_task(read('first', first))
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            b = asyncio.create_task(read('second', broken))
            await asyncio.sleep(0.01)
            release.set()
            await a
            with pytest.raises(ValueError, match='private-evidence-details'):
                await b
        finally:
            release.set()
            await results.stop()
        workers = [r for r in window.records if r['entry'] == 'result.physical']
        assert len(workers) == 2
        assert {r['status'] for r in workers} == {'ok', 'error'}
        assert any(s['endNs'] - s['startNs'] >= 1_000_000
                   for r in workers for s in r['spans'] if s['stage'] == 'result.admission')
        assert 'private-evidence-details' not in str(list(window.records))

    asyncio.run(scenario())


def test_worker_does_not_inherit_unrelated_caller_authority_context():
    caller_authority = ContextVar('unrelated_caller_authority', default=None)

    async def scenario():
        metadata, results = BacktestMetadataThread(), BacktestResultReadThread()
        caller_authority.set('must-stay-on-caller')
        try:
            with read_trace('http.result', window=ReadTraceWindow()):
                def query():
                    assert current_trace() is not None
                    return caller_authority.get()
                assert await metadata.read(query) is None
                assert await results.read_shared(('run',), query) is None
            assert caller_authority.get() == 'must-stay-on-caller'
        finally:
            await metadata.stop()
            await results.stop()
    asyncio.run(scenario())
