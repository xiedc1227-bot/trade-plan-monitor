"""Transport departure must reach existing read ownership without releasing it."""

import asyncio
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from starlette.websockets import WebSocket

from trade_plan_monitor.diagnostics.read_tracing import ReadTraceWindow, read_trace
from trade_plan_monitor.web.monitor_read_ownership import MonitorReadOwner, current_read_lease
from trade_plan_monitor.web.runtime_status_websocket import RuntimeStatusEventStream
from trade_plan_monitor.web.websocket import CommittedMonitorEventStream


def health():
    return dict(
        monitorContractVersion=2, runtimeGeneration=None,
        observedAt=datetime(2026, 10, 22, tzinfo=ZoneInfo("Asia/Shanghai")),
        runtimeStatus=dict(
            lifecycle="STOPPED", mode="BLOCKED", reasonCode="RUNTIME_STOPPED",
            nextWakeAt=None, nextRetryAt=None, lastProgressAt=None,
            coordinator=dict(state="STOPPED", progressDueAt=None), scopes=[],
        ),
    )


@contextmanager
def empty_replay():
    yield SimpleNamespace(events=SimpleNamespace(replay_page_after=lambda _: SimpleNamespace(
        requires_snapshot=False, events=(),
    )))


class Socket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.messages.put_nowait(dict(type="websocket.connect"))
        self.accepted = asyncio.Event()
        self.listening = asyncio.Event()
        self.closed_observed = asyncio.Event()
        self.frames = []
        self.send_attempts = self.receivers = self.peak_receivers = 0
        self.peer_closed = False
        self.cleanup_release = None
        self.cleanup_entered = asyncio.Event()
        self.websocket = WebSocket(dict(type="websocket", path="/ws/v1/monitor"),
                                   self.receive, self.send)

    async def receive(self):
        self.receivers += 1
        self.peak_receivers = max(self.peak_receivers, self.receivers)
        self.listening.set()
        try:
            value = await self.messages.get()
            if isinstance(value, Exception):
                raise value
            if value["type"] == "websocket.disconnect":
                self.closed_observed.set()
            return value
        except asyncio.CancelledError:
            if self.cleanup_release is not None:
                self.cleanup_entered.set()
                await self.cleanup_release.wait()
            raise
        finally:
            self.receivers -= 1

    async def send(self, message):
        if message["type"] == "websocket.accept":
            self.listening.clear()
            self.accepted.set()
        elif message["type"] == "websocket.send":
            self.send_attempts += 1
            if self.peer_closed:
                raise OSError("closed test peer")
            self.frames.append(message)

    def disconnect(self):
        self.peer_closed = True
        self.messages.put_nowait(dict(type="websocket.disconnect", code=1000))


class Reader:
    def __init__(self, *, held=False):
        self.owner = MonitorReadOwner()
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.calls, self.leases = 0, []
        self.held = held

    async def get_health(self):
        self.calls += 1

        async def operation():
            self.leases.append(current_read_lease.get())
            self.entered.set()
            if self.held:
                await self.release.wait()
            return health()

        return await self.owner.run(operation)


async def settle(task, reader=None):
    if reader is not None:
        reader.release.set()
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if reader is not None:
        await reader.owner.stop(timeout=1)


@pytest.mark.parametrize("version", [1, 2])
def test_close_before_first_heartbeat_never_reads_health(version):
    async def scenario():
        socket, reader = Socket(), Reader()
        def liveness():
            reader.calls += 1
            return None
        stream = (
            RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                     heartbeat_interval_seconds=0.02)
            if version == 2 else CommittedMonitorEventStream(
                unit_of_work_factory=empty_replay, heartbeat_interval_seconds=0.02,
                runtime_liveness_provider=liveness,
            )
        )
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(socket.accepted.wait(), 1)
            socket.disconnect()
            await asyncio.wait_for(asyncio.shield(task), 0.2)
            assert reader.calls == 0
            assert socket.closed_observed.is_set()
            assert socket.receivers == 0 and socket.peak_receivers == 1
        finally:
            await settle(task, reader)
    asyncio.run(scenario())


def test_disconnect_cancels_only_observer_and_retains_physical_drain():
    async def scenario():
        socket, reader, window = Socket(), Reader(held=True), ReadTraceWindow()
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=0.001)
        async def serve():
            with read_trace("monitor.socket", window=window):
                await stream.serve(socket.websocket, after=0)
        task = asyncio.create_task(serve())
        try:
            await asyncio.wait_for(reader.entered.wait(), 1)
            socket.disconnect()
            await asyncio.sleep(0.03)
            assert task.done(), "known closed socket is still waiting for health"
            await task
            assert reader.leases[0].cancelled.is_set()
            assert reader.owner.outstanding_work == 1
            with pytest.raises(TimeoutError):
                await reader.owner.drain(timeout=0.001)
            assert reader.owner.outstanding_work == 1
            assert socket.send_attempts == 0 and socket.receivers == 0
            root = next(r for r in window.records if r["entry"] == "monitor.socket")
            assert {s["stage"] for s in root["spans"]} >= {
                "socket.terminal", "socket.heartbeat_admission",
                "socket.observer_cancelled", "socket.children_drained",
            }
        finally:
            await settle(task, reader)
        assert reader.owner.outstanding_work == 0
    asyncio.run(scenario())


def test_disconnect_wins_when_deadline_and_publication_are_ready_together():
    async def scenario():
        socket, reader = Socket(), Reader()
        waiting, wake = asyncio.Event(), asyncio.Event()
        class Stream(RuntimeStatusEventStream):
            async def _wait_for_publication(self, revision, **kwargs):
                waiting.set()
                await wake.wait()
                return revision + 1, True
        stream = Stream(read_service=reader, unit_of_work_factory=empty_replay,
                        heartbeat_interval_seconds=0.001)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(waiting.wait(), 1)
            await asyncio.sleep(0.005)
            socket.disconnect()
            wake.set()
            await asyncio.wait_for(asyncio.shield(task), 0.2)
            assert reader.calls == 0
        finally:
            await settle(task, reader)
    asyncio.run(scenario())


def test_receiver_failure_stops_sender_and_remains_a_failure():
    async def scenario():
        socket, reader = Socket(), Reader()
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=10)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(socket.accepted.wait(), 1)
            socket.messages.put_nowait(RuntimeError("receiver failure"))
            with pytest.raises(RuntimeError, match="receiver failure"):
                await asyncio.wait_for(asyncio.shield(task), 0.2)
            assert reader.calls == 0 and socket.receivers == 0
        finally:
            await settle(task, reader)
    asyncio.run(scenario())


def test_completed_health_and_disconnect_do_not_attempt_another_send():
    async def scenario():
        socket, reader = Socket(), Reader(held=True)
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=0.001)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(reader.entered.wait(), 1)
            socket.disconnect()
            reader.release.set()
            await asyncio.wait_for(asyncio.shield(task), 0.2)
            assert socket.send_attempts == 0
        finally:
            await settle(task, reader)
    asyncio.run(scenario())


def test_incoming_data_has_no_health_or_command_semantics():
    async def scenario():
        socket, reader = Socket(), Reader()
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=10)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(socket.accepted.wait(), 1)
            for _ in range(50):
                socket.messages.put_nowait(dict(type="websocket.receive", text="not a command"))
            socket.disconnect()
            await asyncio.wait_for(asyncio.shield(task), 0.2)
            assert reader.calls == 0 and socket.peak_receivers == 1
        finally:
            await settle(task, reader)
    asyncio.run(scenario())


def test_send_disconnect_without_receive_event_also_joins_receiver():
    async def scenario():
        socket, reader = Socket(), Reader()
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=0.001)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(socket.accepted.wait(), 1)
            socket.peer_closed = True
            await asyncio.wait_for(asyncio.shield(task), 0.2)
            assert reader.calls == 1 and socket.send_attempts == 1
            assert socket.receivers == 0
        finally:
            await settle(task, reader)
    asyncio.run(scenario())


def test_receive_disconnect_interrupts_blocked_send():
    async def scenario():
        socket, reader = Socket(), Reader()
        sending, release = asyncio.Event(), asyncio.Event()
        original_send = socket.send

        async def blocked_send(message):
            if message["type"] == "websocket.send":
                sending.set()
                await release.wait()
            await original_send(message)

        socket.websocket._send = blocked_send
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=0.001)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(sending.wait(), 1)
            socket.disconnect()
            await asyncio.sleep(0.03)
            assert task.done(), "blocked send outlives observed disconnect"
            await task
            assert socket.receivers == 0
        finally:
            release.set()
            await settle(task, reader)
    asyncio.run(scenario())


def test_repeated_outer_cancellation_still_joins_receiver_cleanup():
    async def scenario():
        socket, reader = Socket(), Reader()
        socket.cleanup_release = asyncio.Event()
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=10)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(socket.accepted.wait(), 1)
            await asyncio.wait_for(socket.listening.wait(), 0.2)
            task.cancel("first cancellation")
            await asyncio.wait_for(socket.cleanup_entered.wait(), 0.2)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            assert socket.receivers == 1
            socket.cleanup_release.set()
            with pytest.raises(asyncio.CancelledError, match="first cancellation"):
                await task
            assert socket.receivers == 0 and reader.calls == 0
        finally:
            socket.cleanup_release.set()
            await settle(task, reader)
    asyncio.run(scenario())


def test_cancelled_health_cleanup_failure_is_not_hidden_by_peer_close():
    async def scenario():
        class FailedCleanup(Reader):
            async def get_health(self):
                try:
                    return await super().get_health()
                finally:
                    raise OSError("health cleanup failed")

        socket, reader = Socket(), FailedCleanup(held=True)
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=0.001)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(reader.entered.wait(), 1)
            socket.disconnect()
            with pytest.raises(OSError, match="health cleanup failed"):
                await asyncio.wait_for(asyncio.shield(task), 0.2)
            assert reader.leases[0].cancelled.is_set()
            assert reader.owner.outstanding_work == 1
            assert socket.receivers == 0
        finally:
            await settle(task, reader)
    asyncio.run(scenario())


def test_fast_replay_pages_yield_to_queued_disconnect():
    async def scenario():
        socket = Socket()
        original_send = socket.websocket._send

        async def send(message):
            await original_send(message)
            if message["type"] == "websocket.send" and socket.send_attempts == 1:
                # The ASGI close event can be ready before send itself starts failing.
                socket.messages.put_nowait(dict(type="websocket.disconnect", code=1000))

        class Replay(CommittedMonitorEventStream):
            def _replay_page(self, after):
                event = SimpleNamespace(
                    sequence=after + 1,
                    model_dump=lambda **kwargs: dict(type="test", sequence=after + 1),
                )
                return SimpleNamespace(requires_snapshot=False,
                                       events=(event,) if after < 100 else ())

        socket.websocket._send = send
        stream = Replay(unit_of_work_factory=empty_replay, heartbeat_interval_seconds=10)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await asyncio.wait_for(asyncio.shield(task), 0.2)
            assert socket.closed_observed.is_set()
            assert socket.send_attempts == 1
            assert socket.receivers == 0
        finally:
            await settle(task)
    asyncio.run(scenario())
