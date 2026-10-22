"""Own transport observers without taking ownership of physical monitor reads."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from starlette.websockets import WebSocket, WebSocketDisconnect

from trade_plan_monitor.diagnostics.read_tracing import trace_point


class MonitorConnection:
    def __init__(self, websocket: WebSocket):
        self._websocket = websocket
        self._closed = False

    def check_open(self) -> None:
        if self._closed:
            raise WebSocketDisconnect()

    def _terminate(self) -> None:
        if not self._closed:
            self._closed = True
            trace_point("socket.terminal")

    async def _receive(self) -> None:
        try:
            while True:
                message = await self._websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                # Unsolicited data has no application meaning; ready receives must be fair.
                await asyncio.sleep(0)
        except WebSocketDisconnect:
            return
        finally:
            self._terminate()

    async def _send(self, sender: Callable[[MonitorConnection], Awaitable[None]]) -> None:
        try:
            await sender(self)
        except WebSocketDisconnect:
            return
        finally:
            self._terminate()

    async def run(self, sender: Callable[[MonitorConnection], Awaitable[None]]) -> None:
        children = (
            asyncio.create_task(self._receive(), name="monitor.socket.receive"),
            asyncio.create_task(self._send(sender), name="monitor.socket.send"),
        )
        cancellation = None
        try:
            await asyncio.wait(children, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError as error:
            cancellation = error
        finally:
            for child in children:
                if not child.done():
                    child.cancel()
            cleanup = asyncio.gather(*children, return_exceptions=True)
            # A second outer cancellation cannot interrupt a child's existing finally/drain.
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError as error:
                    if cancellation is None:
                        cancellation = error
            outcomes = cleanup.result()
            trace_point("socket.children_drained", count=0)
        # In particular, a cancelled health observer's finally may fail storage cleanup.
        for outcome in outcomes:
            if isinstance(outcome, BaseException) and not isinstance(
                outcome, asyncio.CancelledError,
            ):
                raise outcome
        if cancellation is not None:
            # Preserve cancellation identity/arguments for enclosing AnyIO cancel scopes.
            raise cancellation
