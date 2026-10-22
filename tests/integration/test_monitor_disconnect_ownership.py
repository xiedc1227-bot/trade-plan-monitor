"""Real proof/session ownership survives the transport observer's departure."""

import asyncio
from threading import Event

import pytest
from sqlalchemy import event
from test_monitor_disconnect import Socket, empty_replay
from test_monitor_evidence_sharing import seed, until
from test_persistent_monitor_read_service import _NOW, _setup

from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state import projections
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.monitor_composition import create_monitor_composition
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService
from trade_plan_monitor.web.runtime_status_websocket import RuntimeStatusEventStream


@pytest.mark.parametrize("departing", ["leader", "follower", "all"])
@pytest.mark.parametrize("invalid", [False, True])
def test_disconnect_preserves_shared_proof_and_surviving_authority(
    tmp_path, monkeypatch, departing, invalid,
):
    engine, _, _, health = _setup(tmp_path)
    sessions = create_session_factory(engine)
    seed(sessions, _NOW)
    authority = RuntimeReadAuthority(
        token="owner", lifecycle="STOPPED", progress=None, health=health, owner_absent=True,
    )
    authority_calls = []

    def current():
        authority_calls.append(1)
        return authority

    reader = RuntimeStatusReadService(sessions, current, clock=lambda: _NOW)
    entered, release = Event(), Event()
    original = projections._latest_index_records
    validations = []

    def held(*args, **kwargs):
        validations.append(1)
        if len(validations) == 1:
            entered.set()
            assert release.wait(5)
            if invalid:
                raise ValueError("invalid shared proof")
        return original(*args, **kwargs)

    monkeypatch.setattr(projections, "_latest_index_records", held)

    async def scenario():
        sockets = [Socket(), Socket()]
        streams = [RuntimeStatusEventStream(
            read_service=reader, unit_of_work_factory=empty_replay,
            heartbeat_interval_seconds=0.001,
        ) for _ in sockets]
        tasks = [asyncio.create_task(streams[0].serve(sockets[0].websocket, after=0))]
        try:
            await until(entered.is_set)
            streams[0]._heartbeat_interval_seconds = 3600
            tasks.append(asyncio.create_task(streams[1].serve(sockets[1].websocket, after=0)))
            await until(lambda: reader._index_verifier.snapshot()["joins"] >= 1)
            streams[1]._heartbeat_interval_seconds = 3600
            indices = [0, 1] if departing == "all" else [0 if departing == "leader" else 1]
            for i in indices:
                sockets[i].disconnect()
            await asyncio.sleep(0.03)
            assert all(tasks[i].done() for i in indices)
            for i in indices:
                await tasks[i]
            assert reader.outstanding_work >= 1
            assert reader._index_verifier.snapshot()["retained_bytes"] > 0
            with pytest.raises(TimeoutError):
                await reader._read_owner.drain(timeout=0.001)
            release.set()
            for i in set(range(2)) - set(indices):
                if invalid:
                    with pytest.raises(ApiError):
                        await asyncio.wait_for(asyncio.shield(tasks[i]), 1)
                    assert not sockets[i].frames
                else:
                    await until(lambda i=i: bool(sockets[i].frames))
                    assert len(authority_calls) >= 3
                    sockets[i].disconnect()
                    await asyncio.wait_for(asyncio.shield(tasks[i]), 1)
            await reader._read_owner.drain(timeout=1)
            assert reader._index_verifier.snapshot()["retained_bytes"] == 0
            assert reader.outstanding_work == 0
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await reader.stop()
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        engine.dispose()


def test_disconnected_snapshot_keeps_storage_pause_until_real_cleanup(tmp_path):
    config = tmp_path / "app.yaml"
    config.write_text("tushare: {}\n", encoding="utf8")
    composition = create_monitor_composition(
        config_path=config, database_path=tmp_path / "monitor.sqlite3", monitor_contract_version=2,
    )
    reader, runtime = composition.read_service, composition._runtime
    entered, release = Event(), Event()
    original_assemble, original_suspend = reader._assemble, reader.suspend_for_storage
    disposed = []
    event.listen(reader._sessions.kw["bind"], "engine_disposed",
                 lambda _engine: disposed.append(reader.outstanding_work))

    def held(*args):
        entered.set()
        assert release.wait(5)
        return original_assemble(*args)

    async def short_suspend(owner):
        await original_suspend(owner, timeout=0.001)

    async def scenario():
        await composition.start()
        disposed.clear()
        reader._assemble, reader.suspend_for_storage = held, short_suspend
        composition.websocket_service._heartbeat_interval_seconds = 0.001
        socket = Socket()
        task = asyncio.create_task(composition.websocket_service.serve(socket.websocket, after=0))
        try:
            await until(entered.is_set)
            socket.disconnect()
            await asyncio.sleep(0.03)
            assert task.done()
            await task
            with pytest.raises(TimeoutError):
                await runtime._checkpoint_wal()
            assert reader.outstanding_work == 1 and not disposed
            assert runtime.runtime_generation in reader._read_owner._storage_pauses
            with pytest.raises(ApiError):
                await reader.get_health()
            release.set()
            await reader._read_owner.drain(timeout=1)
            reader.suspend_for_storage = original_suspend
            await runtime._checkpoint_wal()
            assert runtime.runtime_generation in reader._read_owner._storage_pauses
            await runtime._close_database()
            assert disposed and set(disposed) == {0}
            assert not reader._read_owner._storage_pauses
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            reader.suspend_for_storage = original_suspend
            await composition.stop()
    asyncio.run(scenario())


def test_stopped_health_temporary_reader_is_still_joined_on_disconnect(tmp_path, monkeypatch):
    engine, _, _, health = _setup(tmp_path)
    sessions = create_session_factory(engine)
    authority = RuntimeReadAuthority(
        token="owner", lifecycle="STOPPED", progress=None, health=health, owner_absent=True,
    )
    reader = RuntimeStatusReadService(sessions, lambda: authority, clock=lambda: _NOW)
    reader.allow_stopped_health()
    entered, release = Event(), Event()
    stopping = []
    original_assemble = RuntimeStatusReadService._assemble
    original_stop = RuntimeStatusReadService.stop

    def held(self, *args):
        entered.set()
        assert release.wait(5)
        return original_assemble(self, *args)

    async def stop(self, **kwargs):
        stopping.append(self)
        await original_stop(self, **kwargs)

    monkeypatch.setattr(RuntimeStatusReadService, "_assemble", held)
    monkeypatch.setattr(RuntimeStatusReadService, "stop", stop)

    async def scenario():
        socket = Socket()
        stream = RuntimeStatusEventStream(read_service=reader, unit_of_work_factory=empty_replay,
                                          heartbeat_interval_seconds=0.001)
        task = asyncio.create_task(stream.serve(socket.websocket, after=0))
        try:
            await until(entered.is_set)
            socket.disconnect()
            await until(lambda: bool(stopping))
            temporary = stopping[0]
            assert temporary is not reader and temporary.outstanding_work == 1
            assert not task.done()
            task.cancel()  # A second cancellation cannot discard the temporary reader's drain.
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert temporary.outstanding_work == 0 and not socket.frames
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await reader.stop()
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        engine.dispose()
