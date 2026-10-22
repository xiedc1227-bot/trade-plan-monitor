"""Diagnostic observers must stop even when physical drain reports failure."""

import asyncio
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from scripts.experiments import global_evidence_benchmark as benchmark


@pytest.mark.parametrize('failure', ['reader_stop', 'flight_drain'])
def test_cleanup_failure_still_joins_memory_sampler(tmp_path, monkeypatch, failure):
    threads, stops = [], []
    worker = SimpleNamespace(process=SimpleNamespace(is_alive=lambda: False),
                             close=lambda: None)
    engine = SimpleNamespace(dispose=lambda: None)

    class Reader:
        async def _read(self):
            return (SimpleNamespace(model_dump=lambda **_: {}),)

        async def stop(self):
            if failure == 'reader_stop':
                raise RuntimeError(failure)

    def drain():
        raise RuntimeError('flight_drain')

    def thread_factory(*args, **kwargs):
        thread = Thread(*args, **kwargs)
        threads.append(thread)
        return thread

    def event_factory():
        event = Event()
        stops.append(event)
        return event

    monkeypatch.setattr(benchmark, 'Thread', thread_factory)
    monkeypatch.setattr(benchmark, 'Event', event_factory)
    monkeypatch.setattr(benchmark, 'process_metrics', lambda _: {'cpuSeconds': 0})
    monkeypatch.setattr(benchmark, 'ChunkWorker', lambda: worker)
    monkeypatch.setattr(benchmark, 'frozen_engine', lambda _: engine)
    monkeypatch.setattr(benchmark, 'sessionmaker', lambda **_: None)
    monkeypatch.setattr(benchmark, 'FrozenStore', lambda _: SimpleNamespace(
        get_result_run=lambda _: None))
    monkeypatch.setattr(benchmark, 'RuntimeStatusReadService', lambda *_, **kw: Reader())
    monkeypatch.setattr(benchmark, 'Flights', lambda *_: SimpleNamespace(drain=drain))
    source = tmp_path/'source'
    source.write_bytes(b'fixture')
    args = SimpleNamespace(monitor=source, results=source, run='fixture', memory='original',
                           output=tmp_path/'report.json')
    try:
        with pytest.raises(RuntimeError, match=failure):
            asyncio.run(benchmark.run(args))
        assert threads and all(not thread.is_alive() for thread in threads)
        assert all(stop.is_set() for stop in stops)
    finally:
        # A failing regression must not leave the test runner's observer alive.
        for stop in stops:
            stop.set()
        for thread in threads:
            thread.join(timeout=3)
