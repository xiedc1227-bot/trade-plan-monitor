"""Sequenced WebSocket replay backed by the committed monitor-event ledger."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from trade_plan_monitor.diagnostics.read_tracing import trace_point
from trade_plan_monitor.runtime.health import live_runtime_identity
from trade_plan_monitor.state.events import MonitorEvent, MonitorEventError
from trade_plan_monitor.state.unit_of_work import UnitOfWork
from trade_plan_monitor.web.monitor_connection import MonitorConnection

DEFAULT_HEARTBEAT_SECONDS = 20
_CLOSE_NORMAL = 1000
_CLOSE_POLICY_VIOLATION = 1008
_CLOSE_INTERNAL_ERROR = 1011
_CLOSE_TRY_AGAIN_LATER = 1013
_MAX_SEQUENCE = 2**53 - 1
_SNAPSHOT_REASON = "REPLAY_UNAVAILABLE"

UnitOfWorkFactory = Callable[[], UnitOfWork]
RuntimeLivenessProvider = Callable[[], object]
Clock = Callable[[], datetime]
router = APIRouter(tags=["monitor"])


class UncommittedEventError(RuntimeError):
    """An event publisher was given a value absent from committed storage."""

    code = "UNCOMMITTED_EVENT"


class MonitorWebSocketService(Protocol):
    """Injected application service used by the WebSocket transport adapter."""

    async def serve(self, websocket: WebSocket, *, after: int) -> None: ...


class CommittedMonitorEventStream:
    """Replay durable monitor events and use publication only as a wake-up signal."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        heartbeat_interval_seconds: int | float = DEFAULT_HEARTBEAT_SECONDS,
        runtime_liveness_provider: RuntimeLivenessProvider | None = None,
        clock: Clock | None = None,
        fixed_heartbeat_cadence: bool = False,
    ) -> None:
        if not callable(unit_of_work_factory):
            raise TypeError("unit_of_work_factory must be callable")
        if (
            isinstance(heartbeat_interval_seconds, bool)
            or not isinstance(heartbeat_interval_seconds, (int, float))
            or not math.isfinite(heartbeat_interval_seconds)
            or heartbeat_interval_seconds <= 0
        ):
            raise ValueError("heartbeat_interval_seconds must be positive and finite")
        self._unit_of_work_factory = unit_of_work_factory
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._runtime_liveness_provider = runtime_liveness_provider
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock
        self._fixed_heartbeat_cadence = fixed_heartbeat_cadence
        self._condition = asyncio.Condition()
        self._publication_revision = 0

    @property
    def heartbeat_interval_seconds(self) -> int | float:
        return self._heartbeat_interval_seconds

    async def publish_committed(self, event: MonitorEvent) -> None:
        """Wake connected clients only after exact durable-event verification."""

        if type(event) is not MonitorEvent:
            raise TypeError("event must be a MonitorEvent")
        try:
            with self._unit_of_work_factory() as unit_of_work:
                stored = unit_of_work.events.get(event.event_id)
        except MonitorEventError:
            raise UncommittedEventError("Event is not available in committed storage") from None
        if stored != event:
            raise UncommittedEventError("Event does not match committed storage")
        async with self._condition:
            self._publication_revision += 1
            self._condition.notify_all()

    async def serve(self, websocket: WebSocket, *, after: int) -> None:
        """Send contiguous replay pages, then durable polling heartbeats."""

        if type(after) is not int or after < 0:
            raise ValueError("after must be a non-negative integer")
        await websocket.accept()
        connection = MonitorConnection(websocket)
        await connection.run(lambda connection: self._send_loop(websocket, after, connection))

    async def _send_loop(
        self, websocket: WebSocket, after: int, connection: MonitorConnection,
    ) -> None:
        cursor = after
        publication_revision = self._publication_revision
        loop = asyncio.get_running_loop()
        heartbeat_due = loop.time() + self._heartbeat_interval_seconds
        while True:
            connection.check_open()
            if self._fixed_heartbeat_cadence and loop.time() >= heartbeat_due:
                await self._send_heartbeat(websocket, cursor, connection)
                heartbeat_due = loop.time() + self._heartbeat_interval_seconds
            connection.check_open()
            page = self._replay_page(cursor)
            if page.requires_snapshot:
                connection.check_open()
                await websocket.send_json(
                    self._snapshot_required_frame(page.high_water_sequence)
                )
                await websocket.close(code=_CLOSE_NORMAL)
                return
            if page.events:
                for event in page.events:
                    connection.check_open()
                    await websocket.send_json(_event_frame(event))
                    cursor = event.sequence
                # An uncongested transport can send a whole page without suspending.
                await asyncio.sleep(0)
                continue

            if self._fixed_heartbeat_cadence:
                publication_revision, changed = await self._wait_for_publication(
                    publication_revision, timeout_seconds=max(0, heartbeat_due - loop.time()),
                )
            else:
                publication_revision, changed = await self._wait_for_publication(
                    publication_revision,
                )
            if not changed and not self._fixed_heartbeat_cadence:
                await self._send_heartbeat(websocket, cursor, connection)

    async def _send_heartbeat(
        self, websocket: WebSocket, cursor: int, connection: MonitorConnection,
    ) -> None:
        connection.check_open()
        trace_point("socket.heartbeat_admission")
        try:
            frame = await self._current_heartbeat_frame(cursor)
        except asyncio.CancelledError:
            trace_point("socket.observer_cancelled")
            raise
        connection.check_open()
        await websocket.send_json(frame)

    def _snapshot_required_frame(self, sequence: int) -> dict[str, object]:
        return {"type": "snapshot.required", "sequence": sequence, "reason": _SNAPSHOT_REASON}

    async def _current_heartbeat_frame(self, sequence: int) -> dict[str, object]:
        return self._heartbeat_frame(sequence)

    def _replay_page(self, after: int):
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.events.replay_page_after(after)

    async def _wait_for_publication(
        self, revision: int, *, timeout_seconds: float | None = None,
    ) -> tuple[int, bool]:
        async with self._condition:
            if self._publication_revision != revision:
                return self._publication_revision, True
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._publication_revision != revision),
                    timeout=(self._heartbeat_interval_seconds
                             if timeout_seconds is None else timeout_seconds),
                )
            except TimeoutError:
                return self._publication_revision, False
            return self._publication_revision, True

    def _heartbeat_frame(self, sequence: int) -> dict[str, object]:
        provider = self._runtime_liveness_provider
        if provider is None:
            return {
                "type": "heartbeat",
                "sequence": sequence,
                "runtimeLive": False,
                "runtimeGeneration": None,
                "runtimeStartedAt": None,
            }
        try:
            value = provider()
            observed_at = (
                self._clock()
                if self._clock is not None
                else getattr(value, "observed_at", None)
            )
            runtime_identity = live_runtime_identity(value, observed_at=observed_at)
        except Exception:
            runtime_identity = None
        runtime_live = runtime_identity is not None
        return {
            "type": "heartbeat",
            "sequence": sequence,
            "runtimeLive": runtime_live,
            "runtimeGeneration": (
                str(runtime_identity[1]) if runtime_identity is not None else None
            ),
            "runtimeStartedAt": (
                runtime_identity[0].isoformat() if runtime_identity is not None else None
            ),
        }


def _event_frame(event: MonitorEvent) -> dict[str, object]:
    return event.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )


def _after_cursor(websocket: WebSocket) -> int | None:
    values = websocket.query_params.getlist("after")
    if len(values) != 1:
        return None
    raw = values[0]
    if raw == "0":
        return 0
    if (
        not raw
        or len(raw) > 19
        or raw[0] == "0"
        or any(character not in "0123456789" for character in raw)
    ):
        return None
    value = int(raw)
    return value if value <= _MAX_SEQUENCE else None


@router.websocket("/ws/v1/monitor")
async def monitor_websocket(websocket: WebSocket) -> None:
    if getattr(websocket.app.state, "monitor_contract_version", 1) == 2 and (
        websocket.query_params.getlist("monitorContractVersion") != ["2"]
    ):
        await websocket.accept()
        await websocket.close(
            code=_CLOSE_POLICY_VIOLATION, reason="MONITOR_CONTRACT_MISMATCH",
        )
        return
    after = _after_cursor(websocket)
    if after is None:
        await websocket.accept()
        await websocket.close(code=_CLOSE_POLICY_VIOLATION)
        return
    service = getattr(websocket.app.state, "monitor_websocket_service", None)
    if getattr(websocket.app.state, "monitor_contract_version", 1) == 2 and (
        getattr(service, "monitor_contract_version", None) != 2
    ):
        await websocket.accept()
        await websocket.close(code=_CLOSE_TRY_AGAIN_LATER)
        return
    serve = getattr(service, "serve", None)
    if not callable(serve):
        await websocket.accept()
        await websocket.close(code=_CLOSE_TRY_AGAIN_LATER)
        return
    try:
        await cast(MonitorWebSocketService, service).serve(websocket, after=after)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=_CLOSE_INTERNAL_ERROR)
        except (RuntimeError, WebSocketDisconnect):
            pass


__all__ = [
    "CommittedMonitorEventStream",
    "DEFAULT_HEARTBEAT_SECONDS",
    "MonitorWebSocketService",
    "UncommittedEventError",
    "router",
]
