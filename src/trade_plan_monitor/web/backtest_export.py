"""Bounded disconnect-aware streaming primitives for backtest exports."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from threading import Event
from typing import Literal, Protocol

from anyio import CancelScope, to_thread

MAX_EXPORT_CHUNK_BYTES = 64 * 1_024

BacktestExportKind = Literal["SUMMARY_JSON", "FILLS_CSV"]


@dataclass(frozen=True, slots=True)
class PreparedBacktestExport:
    """Pre-header validated active-v2 identity and its incremental byte iterator."""

    run_id: str
    export_kind: BacktestExportKind
    schema_version: str
    chunks: Iterator[bytes]


class CancellationToken:
    """Thread-safe cancellation observed by application export iterators."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def cancelled(self) -> bool:
        return self._event.is_set()


class DisconnectProbe(Protocol):
    async def is_disconnected(self) -> bool: ...


async def disconnect_aware_chunks(
    chunks: Iterator[bytes],
    probe: DisconnectProbe,
    cancellation: CancellationToken,
    *,
    first_chunk: bytes | None = None,
) -> AsyncIterator[bytes]:
    """Pull one bounded chunk at a time and stop before the next pull on disconnect."""

    if not isinstance(chunks, Iterator) or iter(chunks) is not chunks:
        raise TypeError("chunks must be an incremental byte iterator")
    if not callable(getattr(probe, "is_disconnected", None)):
        raise TypeError("probe must expose is_disconnected")
    if not isinstance(cancellation, CancellationToken):
        raise TypeError("cancellation must be a CancellationToken")
    if first_chunk is not None:
        _validate_chunk(first_chunk)
    try:
        while True:
            if cancellation.cancelled() or await probe.is_disconnected():
                cancellation.cancel()
                return
            if first_chunk is not None:
                chunk = first_chunk
                first_chunk = None
            else:
                chunk = await to_thread.run_sync(_next_chunk, chunks)
            if chunk is _END:
                return
            _validate_chunk(chunk)
            yield chunk
    finally:
        cancellation.cancel()
        close = getattr(chunks, "close", None)
        if callable(close):
            with CancelScope(shield=True):
                await to_thread.run_sync(close)


async def prime_export_chunks(
    chunks: Iterator[bytes],
    cancellation: CancellationToken,
) -> bytes:
    """Validate one required chunk before an HTTP response commits its headers."""

    if not isinstance(chunks, Iterator) or iter(chunks) is not chunks:
        raise TypeError("chunks must be an incremental byte iterator")
    if not isinstance(cancellation, CancellationToken):
        raise TypeError("cancellation must be a CancellationToken")
    try:
        if cancellation.cancelled():
            raise RuntimeError("export was cancelled before streaming")
        chunk = await to_thread.run_sync(_next_chunk, chunks)
        if chunk is _END:
            raise RuntimeError("export stream must contain a first chunk")
        _validate_chunk(chunk)
        return chunk
    except BaseException:
        cancellation.cancel()
        close = getattr(chunks, "close", None)
        if callable(close):
            with CancelScope(shield=True):
                await to_thread.run_sync(close)
        raise


_END = object()


def _next_chunk(chunks: Iterator[bytes]) -> bytes | object:
    try:
        return next(chunks)
    except StopIteration:
        return _END


def _validate_chunk(chunk: object) -> None:
    if type(chunk) is not bytes or not 0 < len(chunk) <= MAX_EXPORT_CHUNK_BYTES:
        raise RuntimeError("export chunk must contain between 1 byte and 64 KiB")


__all__ = [
    "MAX_EXPORT_CHUNK_BYTES",
    "BacktestExportKind",
    "CancellationToken",
    "PreparedBacktestExport",
    "disconnect_aware_chunks",
    "prime_export_chunks",
]
