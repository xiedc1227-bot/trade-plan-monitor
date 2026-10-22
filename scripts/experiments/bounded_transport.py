"""Isolated P0 worker; no production registration, authority, sessions or credentials."""

import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from threading import Lock, Timer
from time import perf_counter, process_time, sleep
from uuid import uuid4

from scripts.experiments.bounded_codec import (
    FRAME,
    OUTPUT,
    AdmissionError,
    ProtocolError,
    decode,
    encode,
    plan,
)

CONTROL = 4096


def fingerprint():
    from trade_plan_monitor.state import projections
    return hashlib.sha256(Path(projections.__file__).read_bytes()).hexdigest()


def send(connection, kind, generation, job, sequence, **values):
    blob = json.dumps(dict(v=1, kind=kind, generation=generation, job=job,
                           sequence=sequence, **values), separators=(',', ':')).encode()
    if len(blob) > CONTROL:
        raise ProtocolError('control too large')
    connection.send_bytes(blob)


def receive(connection, generation, job=None, sequence=None):
    try:
        value = json.loads(connection.recv_bytes(CONTROL))
    except (ValueError, OSError, EOFError) as error:
        raise ProtocolError('invalid control') from error
    if (type(value) is not dict or value.get('v') != 1
            or value.get('generation') != generation
            or (job is not None and value.get('job') != job)
            or (sequence is not None and value.get('sequence') != sequence)):
        raise ProtocolError('crossed control')
    return value


def _job(connection, generation, start):
    from trade_plan_monitor.market_index.identity import MarketIndexCode
    from trade_plan_monitor.state.projections import (
        ProjectionError,
        ProjectionMissingDependencyError,
        _latest_index_records,
    )
    job = start['job']
    sequence, count, total = 0, 0, 0
    digest = hashlib.sha256()
    ended = False
    started, cpu = perf_counter(), process_time()
    decode_seconds = wait_seconds = 0
    if start.get('fault') == 'crash':
        os._exit(71)
    if start.get('fault') == 'hang':
        sleep(60)

    def stream():
        nonlocal sequence, count, total, ended, decode_seconds, wait_seconds
        while True:
            before = perf_counter()
            send(connection, 'NEED', generation, job, sequence)
            message = receive(connection, generation, job, sequence)
            if message['kind'] == 'END':
                if (message.get('count') != count or count != start['count']
                        or message.get('bytes') != total
                        or message.get('digest') != digest.hexdigest()):
                    raise ProtocolError('incomplete stream')
                ended = True
                return
            if message['kind'] != 'CHUNK' or message.get('first') != count:
                raise ProtocolError('out of order input')
            blob = connection.recv_bytes(FRAME)
            wait_seconds += perf_counter() - before
            if len(blob) != message.get('bytes'):
                raise ProtocolError('input length mismatch')
            digest.update(blob)
            total += len(blob)
            before = perf_counter()
            rows = decode(blob)
            decode_seconds += perf_counter() - before
            if len(rows) != message.get('count'):
                raise ProtocolError('input count mismatch')
            count += len(rows)
            if count > start['count']:
                raise ProtocolError('extra input')
            for row in rows:
                yield row
            # The consumer can retain its last row; the admission envelope charges overlap.
            del row, rows, blob
            sequence += 1

    try:
        if start.get('core') != fingerprint():
            raise ProtocolError('core version mismatch')
        values = _latest_index_records(stream(), tuple(MarketIndexCode(c) for c in start['codes']))
        if not ended:
            raise ProtocolError('unconsumed stream')
        output = ('[' + ','.join(v.model_dump_json() for v in values) + ']').encode()
        if len(output) > OUTPUT:
            raise ProtocolError('output envelope exceeded')
        send(connection, 'RESULT', generation, job, sequence, bytes=len(output),
             count=count, digest=digest.hexdigest())
        connection.send_bytes(output)
        return dict(count=count, chunks=sequence, inputBytes=total, outputBytes=len(output),
                    childSeconds=perf_counter()-started, childCpuSeconds=process_time()-cpu,
                    decodeSeconds=decode_seconds, inputWaitSeconds=wait_seconds)
    except ProjectionMissingDependencyError:
        send(connection, 'ERROR', generation, job, sequence, code='missing')
    except ProjectionError:
        send(connection, 'ERROR', generation, job, sequence, code='evidence')
    except Exception:
        send(connection, 'ERROR', generation, job, sequence, code='transport')
    return dict(count=count, chunks=sequence, failed=True)


def _worker(connection, generation):
    # Import cost is deliberately part of the separately measured cold start.
    core = fingerprint()
    send(connection, 'READY', generation, '', 0, core=core)
    try:
        while True:
            start = receive(connection, generation)
            if start['kind'] == 'STOP':
                return
            if start['kind'] != 'START' or start['sequence'] != 0:
                raise ProtocolError('invalid start')
            metrics = _job(connection, generation, start)
            # _job has returned: its generator, candidate, raw text and output are gone.
            send(connection, 'DRAINED', generation, start['job'], metrics['chunks'], **metrics)
            del start, metrics
    finally:
        connection.close()


class ChunkWorker:
    """Single physical owner. Test observers may detach; this bridge must finish."""

    def __init__(self, *, timeout=30):
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe(duplex=True)
        self.generation, self.timeout = uuid4().hex, timeout
        self.process = context.Process(target=_worker, args=(child, self.generation))
        self.retained_bytes, self.last, self.broken = 0, {}, False
        self._lock = Lock()
        started = perf_counter()
        self.process.start()
        child.close()
        if not self.connection.poll(30):
            self._retire()
            raise RuntimeError('worker startup failed')
        ready = receive(self.connection, self.generation, '', 0)
        if ready['kind'] != 'READY' or ready['core'] != fingerprint():
            self._retire()
            raise RuntimeError('worker core mismatch')
        self.cold_seconds = perf_counter()-started

    def _retire(self):
        self.broken = True
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(5)
        if self.process.is_alive():
            raise RuntimeError('child has not physically exited')

    def _release(self):
        self.retained_bytes = 0

    def validate(self, rows, codes, *, external_bytes=0, fault=None,
                 admitted=None, parent_gate=None):
        from trade_plan_monitor.state.projections import (
            MarketIndexSnapshotRecord,
            ProjectionError,
            ProjectionMissingDependencyError,
        )
        admission = plan(rows, external_bytes=external_bytes)
        if not self._lock.acquire(blocking=False):
            raise RuntimeError('physical owner already active')
        if self.broken or self.retained_bytes:
            self._lock.release()
            raise RuntimeError('worker is fenced')
        self.retained_bytes = admission.reserved
        job, sequence, total = uuid4().hex, 0, 0
        digest = hashlib.sha256()
        encode_seconds = 0
        drained = False
        timer = Timer(self.timeout, self._retire)
        timer.daemon = True
        timer.start()
        try:
            send(self.connection, 'START', self.generation, job, 0, count=len(rows),
                 codes=[c.value for c in codes], core=fingerprint(), fault=fault)
            if admitted is not None:
                admitted.set()
            if parent_gate is not None and not parent_gate.wait(self.timeout):
                raise RuntimeError('test gate timed out')
            output, failure, failure_sequence = None, None, None
            while True:
                message = receive(self.connection, self.generation, job)
                kind = message['kind']
                expected = failure_sequence if kind == 'DRAINED' and failure else sequence
                if kind == 'ERROR':
                    if message['sequence'] not in (sequence, max(0, sequence-1)):
                        raise ProtocolError('crossed error')
                elif message['sequence'] != expected:
                    raise ProtocolError('crossed response')
                if kind == 'NEED':
                    if sequence < len(admission.chunks):
                        first, end = admission.chunks[sequence]
                        started = perf_counter()
                        blob = encode(rows[first:end])
                        encode_seconds += perf_counter()-started
                        digest.update(blob)
                        total += len(blob)
                        send(self.connection, 'CHUNK',
                             'wrong' if fault == 'generation' else self.generation, job,
                             sequence+1 if fault == 'sequence' else sequence,
                             first=first, count=end-first, bytes=len(blob))
                        self.connection.send_bytes(blob[:-1] if fault == 'truncated' else blob)
                        del blob
                        sequence += 1
                    else:
                        send(self.connection, 'END', self.generation, job, sequence,
                             count=len(rows)+(fault == 'count'), bytes=total,
                             digest='wrong' if fault == 'digest' else digest.hexdigest())
                elif kind == 'RESULT':
                    if (sequence != len(admission.chunks) or message.get('count') != len(rows)
                            or message.get('digest') != digest.hexdigest()):
                        raise ProtocolError('premature result')
                    output = self.connection.recv_bytes(OUTPUT)
                    if len(output) != message['bytes']:
                        raise ProtocolError('output length mismatch')
                elif kind == 'ERROR':
                    failure = message['code']
                    failure_sequence = message['sequence']
                elif kind == 'DRAINED':
                    if output is None and failure is None:
                        raise ProtocolError('missing outcome')
                    drained = True
                    self.last = dict(message, reservedBytes=admission.reserved,
                                     externalBytes=external_bytes, rawBytes=admission.raw_bytes,
                                     encodeSeconds=encode_seconds, drained=True)
                    break
                else:
                    raise ProtocolError('unexpected response')
            if failure == 'missing':
                raise ProjectionMissingDependencyError('Stored index dependency is missing')
            if failure == 'evidence':
                raise ProjectionError('Stored index evidence is invalid')
            if failure is not None:
                raise ProtocolError('worker rejected transport')
            return tuple(MarketIndexSnapshotRecord.model_validate_json(json.dumps(v))
                         for v in json.loads(output))
        except (AdmissionError, ProtocolError, OSError, EOFError) as error:
            self._retire()
            raise RuntimeError('physical transport failed') from error
        finally:
            timer.cancel()
            timer.join()
            try:
                if not drained and self.process.is_alive():
                    self._retire()
                if drained or not self.process.is_alive():
                    self._release()
            finally:
                self._lock.release()

    def close(self):
        with self._lock:
            if self.process.is_alive() and not self.broken:
                send(self.connection, 'STOP', self.generation, '', 0)
                self.process.join(5)
            if self.process.is_alive():
                self._retire()
            self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
