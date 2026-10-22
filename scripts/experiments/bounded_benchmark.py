"""Fixed P0 comparison on explicitly supplied frozen read-only databases.

Run as python -m scripts.experiments.bounded_benchmark --help.
No production app or provider is started; synthetic authority is explicit.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from threading import Event, Thread, get_ident
from time import perf_counter, process_time
from zoneinfo import ZoneInfo

from scripts.experiments.bounded_codec import AdmissionError
from scripts.experiments.bounded_transport import ChunkWorker
from scripts.experiments.process_metrics import process_metrics
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from trade_plan_monitor.backtest.composition import _ProductionBacktestService
from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state import projections
from trade_plan_monitor.web.routers.health import RuntimeHealthResponse
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


class FrozenStore(BacktestResultStore):
    def __init__(self, path):
        self._path = path.resolve()
        self._busy_timeout_ms = 5000

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self._path.as_uri()+'?mode=ro', uri=True, isolation_level=None)
        connection.execute('PRAGMA query_only=ON')
        try:
            yield connection
        finally:
            connection.close()


def frozen_engine(path):
    def connect():
        connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True,
                                     isolation_level=None, check_same_thread=False)
        connection.execute('PRAGMA query_only=ON')
        return connection
    engine = create_engine('sqlite+pysqlite://', creator=connect, poolclass=QueuePool,
                           pool_size=8, max_overflow=0)

    @event.listens_for(engine, 'begin')
    def begin(connection):
        connection.exec_driver_sql('BEGIN')
    return engine


def frozen_authority(now):
    health = RuntimeHealthResponse.model_validate_json(json.dumps(dict(
        status='RUNNING', readOnly=False, observedAt=now, startedAt=now-timedelta(minutes=1),
        stoppedAt=None, lastCompletedMinute=None, lastCompletedMinuteAgeSeconds=None,
        latestEvaluationAt=None, latestEvaluationAgeSeconds=None, gaps=[], nextRetryAt=None,
        cooldownUntil=None, providers=[],
        executor=dict(activeCount=0, maxWorkers=1, waitingCount=0),
        database=dict(status='READY', walStatus='READY', lastCheckpointAt=None,
                      lastBackupAt=None, errorCode=None),
        delivery=dict(status='READY', pendingCount=0, failedCount=0, lastDeliveredAt=None,
                      nextRetryAt=None, errorCode=None),
        nextPollAt=now+timedelta(minutes=1),
    ), default=lambda value: value.isoformat()))
    return RuntimeReadAuthority(token='frozen-absent-owner', lifecycle='STOPPED', progress=None,
                                health=health, owner_absent=True)


def output_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     default=str).encode()).hexdigest()


async def run(args):
    now = datetime(2026, 10, 22, 12, tzinfo=ZoneInfo('Asia/Shanghai'))
    authority_value, owner_thread = frozen_authority(now), get_ident()
    authority_calls = 0

    def authority():
        nonlocal authority_calls
        assert get_ident() == owner_thread
        authority_calls += 1
        return authority_value

    engine = frozen_engine(args.monitor)
    store = FrozenStore(args.results)
    service = object.__new__(_ProductionBacktestService)
    service._result_store = store
    result_run = store.get_result_run(args.run)
    worker = None if args.memory == 'thread' else ChunkWorker()
    original = projections._latest_index_records
    report = dict(scope='Frozen RO full reads; synthetic absent owner; no production acceptance.',
                  baseline='f430c96', frameBytes=1048576, reservedCopyBytes=16777216,
                  coldSeconds=None if worker is None else worker.cold_seconds,
                  inputs={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (args.monitor, args.results)}, rows=[], memorySamples=[])
    expected = {}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf8')
    save()

    async def sample(variant, case, block, control=False):
        nonlocal authority_calls
        authority_calls = 0
        reader = RuntimeStatusReadService(sessionmaker(bind=engine, expire_on_commit=False),
                                          authority, clock=lambda: now)
        entered, proofs, finished = Event(), [], {}

        def dispatch(values, codes):
            values = tuple(values)
            if variant == 'process':
                try:
                    result = worker.validate(values, codes, admitted=entered)
                    proofs.append(dict(worker.last, fallback=False))
                    return result
                except AdmissionError as error:
                    proofs.append(dict(fallback=True, reason=str(error)))
            entered.set()
            result = original(iter(values), codes)
            if variant == 'thread':
                proofs.append(dict(rawBytes=sum(v.retained_size() for v in values), fallback=False))
            return result

        projections._latest_index_records = dispatch
        child_before = process_metrics(worker.process.pid)['cpuSeconds'] if worker else 0
        start, cpu = perf_counter(), process_time()

        async def monitor():
            value = await reader._read()
            finished['monitorSeconds'] = perf_counter()-start
            return value[0].model_dump(mode='json')

        async def result():
            before = perf_counter()
            value = await asyncio.to_thread(service._project_run, result_run)
            finished['resultSeconds'] = perf_counter()-before
            return value.model_dump(mode='json')

        row = dict(variant=variant, case=case, block=block, control=control)
        try:
            if case == 'mixed':
                task = asyncio.create_task(monitor())
                assert await asyncio.to_thread(entered.wait, 30)
                mon, res = await asyncio.gather(task, result())
            elif case == 'monitor':
                mon, res = await monitor(), None
            else:
                mon, res = None, await result()
            wall, parent_cpu = perf_counter()-start, process_time()-cpu
            child_cpu = (process_metrics(worker.process.pid)['cpuSeconds']-child_before
                         if worker else 0)
            hashes = {}
            for name, value in (('monitor', mon), ('result', res)):
                if value is not None:
                    digest = output_hash(value)
                    expected.setdefault(name, digest)
                    assert digest == expected[name]
                    hashes[name] = digest
            assert authority_calls == (0 if case == 'result' else 2)
            assert reader.outstanding_work == 0
            assert reader._index_verifier.snapshot()['retained_bytes'] == 0
            assert worker is None or worker.retained_bytes == 0
            row.update(ok=True, wallSeconds=wall, parentCpuSeconds=parent_cpu,
                       childCpuSeconds=child_cpu, totalCpuSeconds=parent_cpu+child_cpu,
                       authorityCalls=authority_calls, hashes=hashes, proofs=proofs, **finished)
        except BaseException as error:
            row.update(ok=False, error=type(error).__name__)
            raise
        finally:
            await reader.stop()
            report['rows'].append(row)
            save()
            summary = {k: v for k, v in row.items() if k not in ('hashes', 'proofs')}
            print(json.dumps(summary), flush=True)

    stop = Event()

    def observe_memory():
        while not stop.is_set():
            parent = process_metrics(os.getpid())
            child = process_metrics(worker.process.pid) if worker else None
            report['memorySamples'].append(dict(parent=parent, child=child))
            stop.wait(0.02)

    sampler = None
    try:
        if args.memory:
            sampler = Thread(target=observe_memory)
            sampler.start()
            await sample(args.memory, 'mixed', 1)
        elif args.smoke:
            for variant in ('thread', 'process'):
                await sample(variant, 'mixed', 0)
        else:
            for case in ('monitor', 'result', 'mixed'):
                for pair in range(10):
                    for _ in range(2):
                        await sample('thread', case, pair+1, True)
                for block in range(20):
                    for letter in ('ABBA' if block % 2 == 0 else 'BAAB'):
                        await sample('thread' if letter == 'A' else 'process', case, block+1)
            report['medians'] = {
                case: {variant: {field: median(row[field] for row in report['rows']
                                              if row['case'] == case and row['variant'] == variant
                                              and not row['control'])
                                 for field in ('wallSeconds', 'totalCpuSeconds')
                                 + (() if case == 'result' else ('monitorSeconds',))
                                 + (() if case == 'monitor' else ('resultSeconds',))}
                       for variant in ('thread', 'process')}
                for case in ('monitor', 'result', 'mixed')}
    finally:
        stop.set()
        if sampler:
            sampler.join()
        projections._latest_index_records = original
        if worker:
            worker.close()
            report['childExited'] = not worker.process.is_alive()
        engine.dispose()
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monitor', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--memory', choices=['thread', 'process'])
    asyncio.run(run(parser.parse_args()))
