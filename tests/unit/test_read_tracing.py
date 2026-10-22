"""Diagnostic failures and capacity must never become business admission."""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from trade_plan_monitor.diagnostics.read_tracing import (
    ReadTraceWindow,
    configured_trace_window,
    current_trace,
    read_span,
    read_trace,
    trace_point,
)
from trade_plan_monitor.web.read_tracing import ReadTracingMiddleware


def test_bounds_secrecy_and_exception_transparency(tmp_path):
    window = ReadTraceWindow(directory=tmp_path, max_traces=2, max_spans=3)
    with pytest.raises(ValueError, match="business failure"):
        with read_trace("http.result", window=window):
            with read_span("result.audit", cpu=True):
                trace_point("result.join", count=2961)
                trace_point("source text and credentials must not be accepted")
                for _ in range(10):
                    trace_point("result.endpoint_return")
                raise ValueError("business failure: secret-source-body")
    record = window.records[-1]
    assert record["status"] == "error"
    assert len(record["spans"]) <= 3
    assert record["droppedSpans"] > 0
    text = json.dumps(record)
    assert "secret-source-body" not in text
    assert "source text" not in text
    assert current_trace() is None
    for _ in range(4):
        with read_trace("http.result", window=window):
            pass
    assert len(window.records) == 2
    assert window.active == 0


def test_invalid_sink_initialization_is_disabled(tmp_path, monkeypatch):
    blocker = tmp_path / 'not-a-directory'
    blocker.write_text('unchanged')
    monkeypatch.setenv('TPM_READ_TRACE_DIR', str(blocker))
    assert configured_trace_window() is None
    assert blocker.read_text() == 'unchanged'


def test_rotation_and_completed_memory_are_bounded(tmp_path):
    window = ReadTraceWindow(directory=tmp_path)
    for _ in range(1024):
        with read_trace('http.result', window=window):
            for _ in range(64):
                trace_point('result.join', physicalId='a'*32, joined=True, count=2961)
    window.close()
    assert len(window.records) == 128
    files = list(tmp_path.glob('read-traces.jsonl*'))
    assert 1 < len(files) <= 3
    assert all(f.stat().st_size <= 1024**2 for f in files)
    assert all(len(line.encode('utf8')) <= 16384
               for f in files for line in f.read_text(encoding='utf8').splitlines())
    assert sum(p.stat().st_size for p in tmp_path.glob('*.jsonl*')) <= 3 * 1024**2


def test_disabled_and_failed_sink_preserve_result(monkeypatch):
    assert current_trace() is None
    with read_span("result.audit", cpu=True):
        assert current_trace() is None
    window = ReadTraceWindow()

    def failed(_record):
        raise OSError("private-path must not escape")

    monkeypatch.setattr(window, "_write", failed)
    with read_trace("http.result", window=window):
        with read_span("result.audit", cpu=True):
            result = 42
    assert result == 42
    assert window.active == 0


def test_capacity_expiry_and_async_wait_has_no_cpu(monkeypatch):
    window = ReadTraceWindow(max_active=1)
    with read_trace("http.result", window=window):
        with read_trace("metadata.physical", window=window):
            pass
        with read_span("metadata.admission"):
            pass
    assert len(window.records) == 1
    assert all("threadCpuNs" not in span for span in window.records[0]["spans"])
    monkeypatch.setattr(window, "_deadline_ns", 0)
    with read_trace("http.result", window=window):
        pass
    assert len(window.records) == 1


def test_http_correlation_error_body_and_disabled():
    async def scenario():
        for enabled in (False, True):
            window = ReadTraceWindow() if enabled else None
            app = FastAPI()
            app.add_middleware(ReadTracingMiddleware, window=window)

            @app.get('/api/v1/backtest-runs/{run_id}')
            async def endpoint(run_id: str):
                if run_id == 'handled-error':
                    raise HTTPException(503, detail='unchanged public failure')
                trace_point("result.endpoint_return")
                return {"unchanged": True}

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test",
            ) as client:
                response = await client.get('/api/v1/backtest-runs/private-run-id')
                failed = await client.get('/api/v1/backtest-runs/handled-error')
            assert response.json() == {"unchanged": True}
            assert failed.status_code == 503
            assert failed.json() == {'detail': 'unchanged public failure'}
            assert ("X-Read-Trace-ID" in response.headers) == enabled
            if enabled:
                assert window.records[-2]["traceId"] == response.headers["X-Read-Trace-ID"]
                assert "private-run-id" not in json.dumps(list(window.records))
                stages = {s["stage"] for s in window.records[-2]["spans"]}
                assert {"http.headers", "http.body", "result.endpoint_return"} <= stages
                assert any(s.get('statusCode') == 503 for s in window.records[-1]['spans'])

    asyncio.run(scenario())


def test_socket_connection_correlates_heartbeat_without_changing_frames():
    async def scenario():
        window, sent = ReadTraceWindow(), []

        async def app(scope, receive, send):
            await send({'type': 'websocket.accept'})
            with read_trace('monitor.heartbeat'):
                with read_span('monitor.authority_before', cpu=True):
                    pass
            await send({'type': 'websocket.send', 'text': 'original frame'})
            assert (await receive())['type'] == 'websocket.disconnect'

        async def receive():
            return {'type': 'websocket.disconnect', 'code': 1000}

        async def send(message):
            sent.append(message)

        middleware = ReadTracingMiddleware(app, window=window)
        await middleware({'type': 'websocket', 'path': '/ws/v1/monitor'}, receive, send)
        socket = next(r for r in window.records if r['entry'] == 'monitor.socket')
        heartbeat = next(r for r in window.records if r['entry'] == 'monitor.heartbeat')
        assert heartbeat['parentId'] == socket['traceId']
        assert sent[0]['headers'] == [(b'x-read-trace-id', socket['traceId'].encode('ascii'))]
        assert sent[1] == {'type': 'websocket.send', 'text': 'original frame'}
        assert {s['stage'] for s in socket['spans']} == {'socket.accept', 'socket.disconnect'}

    asyncio.run(scenario())
