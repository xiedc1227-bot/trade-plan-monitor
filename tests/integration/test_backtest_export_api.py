"""Focused transport and streaming contracts for active-v2 backtest exports."""

from __future__ import annotations

import ast
import asyncio
import inspect
from collections.abc import Callable, Iterator, Mapping
from threading import get_ident
from typing import cast

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.backtest_export import (
    MAX_EXPORT_CHUNK_BYTES,
    CancellationToken,
    PreparedBacktestExport,
    disconnect_aware_chunks,
)
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.origin_guard import SECURITY_HEADERS
from trade_plan_monitor.web.routers import backtest_exports
from trade_plan_monitor.web.schemas import ApiErrorCode

_RUN_ID = "b" * 64
_OTHER_RUN_ID = "c" * 64
_MISSING = object()
_SUMMARY = (
    b'{"completedAt":"2026-08-28T15:00:00.000000+08:00",'
    b'"schemaVersion":"backtest-report-summary-v2"}\n'
)
_FILLS = (
    b"schema_version,run_id,filled_at\n"
    b"backtest-simulated-fills-v2,"
    + _RUN_ID.encode("ascii")
    + b",2026-08-28T09:30:00.000000+08:00\n"
)


def _prepared(
    *,
    run_id: str = _RUN_ID,
    export_kind: str = "SUMMARY_JSON",
    schema_version: str | None = None,
    chunks: Iterator[bytes] | object | None = None,
) -> PreparedBacktestExport:
    default_schema = (
        "backtest-report-summary-v2"
        if export_kind == "SUMMARY_JSON"
        else "backtest-simulated-fills-v2"
    )
    default_body = _SUMMARY if export_kind == "SUMMARY_JSON" else _FILLS
    return PreparedBacktestExport(
        run_id=run_id,
        export_kind=cast(object, export_kind),
        schema_version=schema_version or default_schema,
        chunks=iter((default_body,)) if chunks is None else cast(Iterator[bytes], chunks),
    )


class _FakeExportService:
    def __init__(self, result: object = _MISSING) -> None:
        self.result = _prepared() if result is _MISSING else result
        self.calls: list[tuple[str, str, Callable[[], bool]]] = []

    async def prepare_export(
        self,
        *,
        run_id: str,
        export_kind: str,
        cancelled: Callable[[], bool],
    ) -> object | None:
        self.calls.append((run_id, export_kind, cancelled))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _client(*, service: object = _MISSING) -> TestClient:
    app = create_app()
    if service is not _MISSING:
        app.state.backtest_read_service = service
    return TestClient(app, raise_server_exceptions=False)


def _assert_error(response: object, *, status: int, code: str) -> None:
    typed_response = cast(object, response)
    assert typed_response.status_code == status  # type: ignore[attr-defined]
    payload = typed_response.json()  # type: ignore[attr-defined]
    assert payload["error"]["code"] == code
    assert payload["error"]["message"]
    assert (
        payload["error"]["requestId"]
        == typed_response.headers[  # type: ignore[attr-defined]
            "X-Request-ID"
        ]
    )


@pytest.mark.parametrize(
    ("export_kind", "body", "content_type", "suffix"),
    [
        ("SUMMARY_JSON", _SUMMARY, "application/json", "summary.json"),
        ("FILLS_CSV", _FILLS, "text/csv; charset=utf-8", "fills.csv"),
    ],
)
def test_export_route_streams_exact_active_v2_headers_and_body(
    export_kind: str,
    body: bytes,
    content_type: str,
    suffix: str,
) -> None:
    service = _FakeExportService(_prepared(export_kind=export_kind))
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/exports/{export_kind}"
    )

    assert response.status_code == 200
    assert response.content == body
    assert response.headers["Content-Type"] == content_type
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="backtest-{_RUN_ID}-{suffix}"'
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert len(response.headers["X-Request-ID"]) == 32
    assert not any(name.lower().startswith("access-control-") for name in response.headers)
    assert "Content-Length" not in response.headers
    run_id, kind, cancelled = service.calls.pop()
    assert (run_id, kind) == (_RUN_ID, export_kind)
    assert cancelled()


@pytest.mark.parametrize(
    ("run_id", "export_kind", "params"),
    [
        ("not-a-run", "SUMMARY_JSON", {}),
        ("B" * 64, "SUMMARY_JSON", {}),
        ("g" * 64, "SUMMARY_JSON", {}),
        (_RUN_ID, "summary_json", {}),
        (_RUN_ID, "DEBUG_TRACE", {}),
        (_RUN_ID, "SUMMARY_JSON", {"download": "true"}),
        (_RUN_ID, "FILLS_CSV", {"cursor": "anchor.signature"}),
    ],
)
def test_export_route_rejects_invalid_or_nonclosed_path_before_service(
    run_id: str,
    export_kind: str,
    params: Mapping[str, str],
) -> None:
    service = _FakeExportService()
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{run_id}/exports/{export_kind}", params=params
    )
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.calls == []


def test_export_route_rejects_repeated_query_before_service() -> None:
    service = _FakeExportService()
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON",
        params=[("download", "true"), ("download", "false")],
    )
    _assert_error(response, status=422, code="VALIDATION_ERROR")
    assert service.calls == []


def test_export_route_rejects_hostile_origin_before_service() -> None:
    service = _FakeExportService()
    response = _client(service=service).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON",
        headers={"Origin": "https://attacker.example"},
    )
    _assert_error(response, status=403, code="FORBIDDEN")
    assert service.calls == []
    assert not any(name.lower().startswith("access-control-") for name in response.headers)


def test_export_route_returns_not_found_before_committing_export_headers() -> None:
    service = _FakeExportService(None)
    response = _client(service=service).get(f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON")

    _assert_error(response, status=404, code="NOT_FOUND")
    assert "Content-Disposition" not in response.headers
    assert response.headers["Content-Type"] == "application/json"


def test_export_route_preserves_sanitized_preparation_error() -> None:
    service = _FakeExportService(ApiError(ApiErrorCode.CONFLICT))
    response = _client(service=service).get(f"/api/v1/backtest-runs/{_RUN_ID}/exports/FILLS_CSV")
    _assert_error(response, status=409, code="CONFLICT")
    assert "Content-Disposition" not in response.headers


@pytest.mark.parametrize(
    "prepared",
    [
        object(),
        _prepared(run_id=_OTHER_RUN_ID),
        _prepared(export_kind="FILLS_CSV"),
        _prepared(schema_version="backtest-report-summary-v1"),
        _prepared(chunks=(_SUMMARY,)),
        _prepared(chunks=_SUMMARY),
    ],
)
def test_export_route_rejects_mismatched_v1_or_buffered_service_output(
    prepared: object,
) -> None:
    service = _FakeExportService(prepared)
    response = _client(service=service).get(f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON")
    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "backtest-report-summary-v1" not in response.text


def test_missing_export_service_fails_closed() -> None:
    response = _client().get(f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON")
    _assert_error(response, status=503, code="SERVICE_UNAVAILABLE")


def test_export_route_openapi_declares_both_stream_media_types() -> None:
    app = create_app()
    operation = app.openapi()["paths"]["/api/v1/backtest-runs/{run_id}/exports/{export_kind}"][
        "get"
    ]

    assert set(operation["responses"]["200"]["content"]) == {
        "application/json",
        "text/csv",
    }
    assert {
        media: value["schema"] for media, value in operation["responses"]["200"]["content"].items()
    } == {
        "application/json": {"type": "string", "format": "binary"},
        "text/csv": {"type": "string", "format": "binary"},
    }


class _DisconnectProbe:
    def __init__(self, states: list[bool]) -> None:
        self._states = iter(states)
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return next(self._states, True)


class _CountingIterator:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = iter(chunks)
        self.next_calls = 0
        self.next_threads: list[int] = []
        self.closed = False
        self.close_calls = 0
        self.close_threads: list[int] = []

    def __iter__(self) -> _CountingIterator:
        return self

    def __next__(self) -> bytes:
        self.next_calls += 1
        self.next_threads.append(get_ident())
        return next(self._chunks)

    def close(self) -> None:
        self.close_calls += 1
        self.close_threads.append(get_ident())
        self.closed = True


class _RaisingIterator:
    def __init__(self) -> None:
        self.closed = False

    def __iter__(self) -> _RaisingIterator:
        return self

    def __next__(self) -> bytes:
        raise RuntimeError("private C:/results.sqlite3")

    def close(self) -> None:
        self.closed = True


def test_export_route_validates_lazy_first_chunk_before_committing_headers() -> None:
    chunks = _RaisingIterator()
    service = _FakeExportService(_prepared(chunks=chunks))

    response = _client(service=service).get(f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON")

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "Content-Disposition" not in response.headers
    assert "results.sqlite3" not in response.text
    assert chunks.closed


@pytest.mark.parametrize(
    "chunk",
    [b"", b"x" * (MAX_EXPORT_CHUNK_BYTES + 1), "not-bytes", bytearray(b"mutable")],
    ids=["empty", "oversized", "text", "mutable"],
)
def test_export_route_rejects_invalid_lazy_first_chunk_before_headers(
    chunk: object,
) -> None:
    chunks = _CountingIterator((cast(bytes, chunk),))
    response = _client(service=_FakeExportService(_prepared(chunks=chunks))).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON"
    )

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "Content-Disposition" not in response.headers
    assert response.headers.get("Cache-Control") != "no-store"
    assert chunks.close_calls == 1


def test_export_route_preserves_lazy_first_chunk_domain_error() -> None:
    def unavailable() -> Iterator[bytes]:
        raise ApiError(ApiErrorCode.NOT_FOUND)
        yield b"unreachable"

    response = _client(service=_FakeExportService(_prepared(chunks=unavailable()))).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON"
    )

    _assert_error(response, status=404, code="NOT_FOUND")
    assert "Content-Disposition" not in response.headers


def test_export_route_rejects_empty_lazy_iterator_before_headers() -> None:
    chunks = _CountingIterator(())
    response = _client(service=_FakeExportService(_prepared(chunks=chunks))).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON"
    )

    _assert_error(response, status=500, code="INTERNAL_ERROR")
    assert "Content-Disposition" not in response.headers
    assert chunks.next_calls == 1
    assert chunks.close_calls == 1


async def _collect_chunks(
    chunks: Iterator[bytes],
    probe: _DisconnectProbe,
    token: CancellationToken,
) -> tuple[bytes, ...]:
    return tuple([chunk async for chunk in disconnect_aware_chunks(chunks, probe, token)])


def test_disconnect_stops_before_pulling_the_next_chunk_and_closes_iterator() -> None:
    chunks = _CountingIterator((b"first", b"must-not-be-pulled"))
    probe = _DisconnectProbe([False, True])
    token = CancellationToken()

    streamed = asyncio.run(_collect_chunks(chunks, probe, token))

    assert streamed == (b"first",)
    assert chunks.next_calls == 1
    assert chunks.closed
    assert token.cancelled()


def test_actual_asgi_disconnect_stops_route_before_next_threaded_pull() -> None:
    main_thread = get_ident()
    chunks = _CountingIterator((b"first", b"must-not-be-pulled"))
    service = _FakeExportService(_prepared(chunks=chunks))
    app = create_app()
    app.state.backtest_read_service = service
    receive_calls = 0
    messages: list[Message] = []
    disconnect_ready = asyncio.Event()

    async def receive() -> Message:
        nonlocal receive_calls
        receive_calls += 1
        if receive_calls == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect_ready.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        messages.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            disconnect_ready.set()

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON",
        "raw_path": (f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON".encode()),
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8765")],
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", 8765),
    }

    asyncio.run(app(scope, receive, send))

    body_messages = [
        message
        for message in messages
        if message["type"] == "http.response.body" and message.get("body")
    ]
    assert [message["body"] for message in body_messages] == [b"first"]
    assert chunks.next_calls == 1
    assert chunks.close_calls == 1
    assert all(thread_id != main_thread for thread_id in chunks.next_threads)
    assert all(thread_id != main_thread for thread_id in chunks.close_threads)
    assert service.calls[0][2]()


def test_preexisting_cancellation_never_pulls_a_chunk() -> None:
    chunks = _CountingIterator((b"must-not-be-pulled",))
    probe = _DisconnectProbe([False])
    token = CancellationToken()
    token.cancel()

    streamed = asyncio.run(_collect_chunks(chunks, probe, token))

    assert streamed == ()
    assert chunks.next_calls == 0
    assert chunks.closed


@pytest.mark.parametrize(
    "chunk",
    [
        b"",
        b"x" * (MAX_EXPORT_CHUNK_BYTES + 1),
        "not-bytes",
        bytearray(b"mutable"),
    ],
    ids=["empty", "oversized", "text", "mutable"],
)
def test_stream_helper_rejects_empty_oversized_or_nonbyte_chunks(chunk: object) -> None:
    chunks = _CountingIterator((cast(bytes, chunk),))
    probe = _DisconnectProbe([False, False])
    token = CancellationToken()

    with pytest.raises(RuntimeError, match="export chunk"):
        asyncio.run(_collect_chunks(chunks, probe, token))
    assert chunks.closed
    assert token.cancelled()


def test_stream_helper_accepts_exact_64_kib_chunk_without_file_buffer() -> None:
    chunks = _CountingIterator((b"x" * MAX_EXPORT_CHUNK_BYTES,))
    probe = _DisconnectProbe([False, False])
    token = CancellationToken()

    streamed = asyncio.run(_collect_chunks(chunks, probe, token))

    assert tuple(map(len, streamed)) == (MAX_EXPORT_CHUNK_BYTES,)
    assert chunks.next_calls == 2
    assert chunks.close_calls == 1


def test_export_adapter_creates_no_file_and_imports_no_storage_or_replay(
    tmp_path: object,
) -> None:
    before = set(cast(object, tmp_path).iterdir())  # type: ignore[attr-defined]
    response = _client(service=_FakeExportService()).get(
        f"/api/v1/backtest-runs/{_RUN_ID}/exports/SUMMARY_JSON"
    )
    after = set(cast(object, tmp_path).iterdir())  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert before == after == set()

    imports: set[str] = set()
    for module in (backtest_exports, inspect.getmodule(disconnect_aware_chunks)):
        assert module is not None
        tree = ast.parse(inspect.getsource(module))
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imports.update(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
    assert not any(
        forbidden in imported
        for imported in imports
        for forbidden in (
            "pathlib",
            "tempfile",
            "tushare",
            "provider",
            "replay",
            "repository",
            "reporting",
            "backtest.results",
            "backtest.jobs",
        )
    )
