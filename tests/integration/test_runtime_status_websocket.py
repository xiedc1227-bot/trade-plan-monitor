"""V2 control frames retain durable replay and never certify progress themselves."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def test_v2_heartbeat_reads_authority_and_keeps_the_delivered_cursor(tmp_path):
    asyncio.run(_heartbeat_scenario(tmp_path, storm=False))


def test_continuous_publication_wakes_cannot_starve_v2_heartbeat(tmp_path):
    asyncio.run(_heartbeat_scenario(tmp_path, storm=True))


def test_authority_failure_and_already_disconnected_socket_close_cleanly():
    from types import SimpleNamespace

    from starlette.datastructures import QueryParams
    from starlette.websockets import WebSocketDisconnect

    from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
    from trade_plan_monitor.web.websocket import monitor_websocket

    class FailedAuthority:
        monitor_contract_version = 2

        async def serve(self, socket, *, after):
            raise ApiError(ApiErrorCode.SERVICE_UNAVAILABLE)

    class DisconnectedSocket:
        app = SimpleNamespace(state=SimpleNamespace(
            monitor_contract_version=2, monitor_websocket_service=FailedAuthority(),
        ))
        query_params = QueryParams("after=0&monitorContractVersion=2")
        closes = []

        async def close(self, *, code):
            self.closes.append(code)
            raise WebSocketDisconnect(code=1006)

    socket = DisconnectedSocket()
    asyncio.run(monitor_websocket(socket))
    assert socket.closes == [1011]


async def _heartbeat_scenario(tmp_path, *, storm):
    from trade_plan_monitor.web.runtime_status_websocket import RuntimeStatusEventStream

    now = datetime(2026, 9, 27, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    upgrade_database(engine)
    sessions = create_session_factory(engine)

    class Reader:
        calls = 0

        async def get_health(self):
            self.calls += 1
            return {
                "monitorContractVersion": 2,
                "runtimeGeneration": None,
                "observedAt": now,
                "runtimeStatus": {
                    "lifecycle": "STOPPED",
                    "mode": "BLOCKED",
                    "reasonCode": "RUNTIME_STOPPED",
                    "nextWakeAt": None,
                    "nextRetryAt": None,
                    "lastProgressAt": None,
                    "coordinator": {"state": "STOPPED", "progressDueAt": None},
                    "scopes": [],
                },
            }

    class Socket:
        frames = asyncio.Queue()

        async def accept(self):
            pass

        async def receive(self):
            await asyncio.Future()

        async def send_json(self, frame):
            await self.frames.put(frame)

    reader, socket = Reader(), Socket()
    class StormStream(RuntimeStatusEventStream):
        async def _wait_for_publication(self, revision, **kwargs):
            await asyncio.sleep(0.001)
            return revision + 1, True

    stream_type = StormStream if storm else RuntimeStatusEventStream
    stream = stream_type(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: now),
        read_service=reader,
        heartbeat_interval_seconds=0.01,
    )
    task = asyncio.create_task(stream.serve(socket, after=0))
    try:
        first = await asyncio.wait_for(socket.frames.get(), 1)
        second = await asyncio.wait_for(socket.frames.get(), 1)
        assert first == second
        assert first["sequence"] == 0
        assert first["monitorContractVersion"] == 2
        assert first["runtimeStatus"]["lastProgressAt"] is None
        assert "runtimeLive" not in first
        assert reader.calls >= 2
        assert stream._snapshot_required_frame(9) == {
            "type": "snapshot.required",
            "monitorContractVersion": 2,
            "sequence": 9,
            "reason": "REPLAY_UNAVAILABLE",
        }
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        engine.dispose()
