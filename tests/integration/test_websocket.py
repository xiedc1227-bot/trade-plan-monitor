"""Sequenced WebSocket replay over the committed notification outbox."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from starlette.websockets import WebSocketDisconnect

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DecisionZone,
    EvidenceFact,
    EvidenceUnit,
    NextStep,
    NextStepCode,
    SignalIntent,
)
from trade_plan_monitor.domain.plan_models import OfficialCloseBelowLevelCondition
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import AlertPayload, AlertSeverity
from trade_plan_monitor.runtime.health import LEGACY_RUNTIME_GENERATION, RuntimeServiceStatus
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import (
    MonitorEventDraft,
    MonitorEventPayload,
    MonitorEventType,
)
from trade_plan_monitor.state.models import MonitorEvent as MonitorEventRow
from trade_plan_monitor.state.models import MonitorSequence
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.app import create_app
from trade_plan_monitor.web.routers.dashboard import (
    ConnectionStatus,
    DashboardCounts,
    DashboardResponse,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 24, 10, 30, tzinfo=SHANGHAI)
PLAN_HASH = "a" * 64
SYMBOL = "003043.SZ"


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _DashboardService:
    def __init__(self, sequence: int) -> None:
        self.sequence = sequence

    async def get_dashboard(self) -> DashboardResponse:
        return DashboardResponse(
            sequence=self.sequence,
            observed_at=NOW,
            runtime_generation=LEGACY_RUNTIME_GENERATION,
            connection_status=ConnectionStatus.CONNECTED,
            counts=DashboardCounts(
                actionable=0,
                low_zone_watch=0,
                blocked=0,
                risk=0,
                stale=0,
                normal=0,
            ),
            symbols=(),
            market_indexes=(),
        )


class _CapturingWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.frames: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, frame: dict[str, object]) -> None:
        await self.frames.put(frame)

    async def close(self, *, code: int) -> None:
        del code


@pytest.fixture
def database_engine(tmp_path: Path) -> Engine:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    upgrade_database(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


def _websocket_module() -> ModuleType:
    return import_module("trade_plan_monitor.web.websocket")


def _unit_of_work_factory(
    engine: Engine,
    clock: _Clock,
    *,
    replay_retention: timedelta = timedelta(days=7),
):
    session_factory = create_session_factory(engine)

    def create() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            session_factory,
            clock=clock,
            replay_retention=replay_retention,
        )

    return create


def _payload(identity: int, *, evaluated_at: datetime | None = None) -> AlertPayload:
    evaluation_time = evaluated_at or NOW - timedelta(minutes=1)
    evidence = ConditionEvidence(
        condition=OfficialCloseBelowLevelCondition(level="RISK_LINE"),
        outcome=ConditionOutcome.SATISFIED,
        facts=(
            EvidenceFact(
                key="current_price_fen",
                value=6070,
                unit=EvidenceUnit.FEN,
            ),
        ),
    )
    signal = SignalIntent(
        signal_type=ActionableSignalType.RISK_BREACH,
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        trading_date=evaluation_time.date(),
        cause_id=f"risk-{identity:04d}",
        quantity=None,
        bucket=None,
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY),
    )
    return AlertPayload(
        event_id=UUID(int=identity),
        dedup_key=alert_dedup_key(signal),
        plan_id="huaya-smart",
        plan_version=1,
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        name="华亚智能",
        signal_type=signal.signal_type,
        severity=AlertSeverity.RISK,
        trading_date=signal.trading_date,
        cause_id=signal.cause_id,
        evaluated_at=evaluation_time,
        market_data_at=evaluation_time,
        data_age_seconds=0,
        price_fen=6070,
        quantity=None,
        bucket=None,
        target_lot_id=None,
        matched_conditions=(evidence,),
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        zone=DecisionZone.BELOW_RISK,
        relevant_zone=None,
        risk_line_fen=6080,
        next_step=signal.next_step,
    )


def _commit_events(
    factory,
    *identities: int,
    evaluated_at: datetime | None = None,
):
    with factory() as work:
        alerts = tuple(
            work.alerts.enqueue(_payload(identity, evaluated_at=evaluated_at))
            for identity in identities
        )
        events = tuple(work.events.get(alert.event_id) for alert in alerts)
        work.commit()
    return events


def _stream(factory, *, heartbeat_interval_seconds: float = 0.01):
    module = _websocket_module()
    return module.CommittedMonitorEventStream(
        unit_of_work_factory=factory,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )


def test_non_alert_event_replays_with_the_versioned_generic_envelope(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    with factory() as work:
        event = work.events.append(
            MonitorEventDraft(
                event_id=UUID(int=99),
                event_type=MonitorEventType.SYMBOL_HEALTH_UPDATED,
                aggregate_id=SYMBOL,
                payload=MonitorEventPayload(
                    entity_id=SYMBOL,
                    symbol=SYMBOL,
                    revision=4,
                    status="STALE",
                ),
                occurred_at=NOW,
            )
        )
        work.commit()

    with TestClient(create_app(websocket_service=_stream(factory))).websocket_connect(
        "/ws/v1/monitor?after=0"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame == {
        "type": "symbol.health.updated",
        "sequence": 1,
        "eventId": str(event.event_id),
        "aggregateId": SYMBOL,
        "payload": {
            "entityId": SYMBOL,
            "symbol": SYMBOL,
            "revision": 4,
            "status": "STALE",
        },
        "occurredAt": NOW.isoformat(),
        "schemaVersion": 1,
    }


def test_alert_creation_and_acknowledgement_share_the_global_event_transaction(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    with factory() as work:
        alert = work.alerts.enqueue(_payload(1))
        acknowledged = work.alerts.acknowledge(alert.event_id)
        assert work.alerts.acknowledge(alert.event_id) == acknowledged
        work.commit()

    with factory() as work:
        monitor_events = work.events.replay_page_after(0).events

    assert alert.sequence == 1
    assert tuple(event.sequence for event in monitor_events) == (1, 2)
    assert tuple(event.event_type for event in monitor_events) == (
        MonitorEventType.ALERT_CREATED,
        MonitorEventType.ALERT_ACKNOWLEDGED,
    )
    assert monitor_events[0].event_id == alert.event_id
    assert monitor_events[0].payload.model_dump(exclude_none=True) == {
        "entity_id": str(alert.event_id),
        "symbol": alert.symbol,
        "revision": 0,
    }
    assert monitor_events[1].aggregate_id == str(alert.event_id)
    assert monitor_events[1].payload.revision == 1


def test_rest_snapshot_sequence_is_applied_before_ordered_replay(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    first, second, third = _commit_events(factory, 1, 2, 3)
    stream = _stream(factory)
    client = TestClient(
        create_app(
            read_service=_DashboardService(sequence=first.sequence),
            websocket_service=stream,
        )
    )

    snapshot = client.get("/api/v1/dashboard")
    assert snapshot.status_code == 200
    assert snapshot.json()["sequence"] == first.sequence

    with client.websocket_connect(
        f"/ws/v1/monitor?after={snapshot.json()['sequence']}"
    ) as websocket:
        frames = (websocket.receive_json(), websocket.receive_json())

    assert tuple(frame["type"] for frame in frames) == (
        "alert.created",
        "alert.created",
    )
    assert tuple(frame["sequence"] for frame in frames) == (
        second.sequence,
        third.sequence,
    )
    assert tuple(frame["eventId"] for frame in frames) == (
        str(second.event_id),
        str(third.event_id),
    )
    assert all(frame["sequence"] > snapshot.json()["sequence"] for frame in frames)


def test_reconnect_and_process_restart_replay_every_committed_event(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    first, second = _commit_events(factory, 10, 11)

    first_process = TestClient(create_app(websocket_service=_stream(factory)))
    with first_process.websocket_connect("/ws/v1/monitor?after=0") as websocket:
        assert websocket.receive_json()["sequence"] == first.sequence
        assert websocket.receive_json()["sequence"] == second.sequence

    third = _commit_events(factory, 12)[0]
    restarted_process = TestClient(create_app(websocket_service=_stream(factory)))
    with restarted_process.websocket_connect(
        f"/ws/v1/monitor?after={second.sequence}"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "alert.created"
    assert frame["sequence"] == third.sequence
    assert frame["eventId"] == str(third.event_id)


def test_duplicate_publication_never_duplicates_a_sequence(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    event = _commit_events(factory, 20)[0]
    stream = _stream(factory)

    asyncio.run(stream.publish_committed(event))
    asyncio.run(stream.publish_committed(event))

    with TestClient(create_app(websocket_service=stream)).websocket_connect(
        "/ws/v1/monitor?after=0"
    ) as websocket:
        created = websocket.receive_json()
        heartbeat = websocket.receive_json()

    assert created["type"] == "alert.created"
    assert created["sequence"] == event.sequence
    assert heartbeat == {
        "type": "heartbeat",
        "sequence": event.sequence,
        "runtimeLive": False,
        "runtimeGeneration": None,
        "runtimeStartedAt": None,
    }


def test_committed_publication_wakes_a_connected_client_without_waiting_for_heartbeat(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    stream = _stream(factory, heartbeat_interval_seconds=30)

    async def exercise() -> tuple[dict[str, object], bool]:
        websocket = _CapturingWebSocket()
        connection = asyncio.create_task(stream.serve(websocket, after=0))
        await asyncio.sleep(0)
        event = _commit_events(factory, 25)[0]
        await stream.publish_committed(event)
        try:
            frame = await asyncio.wait_for(websocket.frames.get(), timeout=1)
        finally:
            connection.cancel()
            with pytest.raises(asyncio.CancelledError):
                await connection
        return frame, websocket.accepted

    frame, accepted = asyncio.run(exercise())

    assert accepted is True
    assert frame["type"] == "alert.created"
    assert frame["sequence"] == 1


def test_uncommitted_event_cannot_be_published(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    stream = _stream(factory)
    with factory() as work:
        alert = work.alerts.enqueue(_payload(30))
        event = work.events.get(alert.event_id)
        # Deliberately leave the transaction without commit.

    with pytest.raises(_websocket_module().UncommittedEventError):
        asyncio.run(stream.publish_committed(event))


def test_committed_creation_can_publish_after_a_concurrent_acknowledgement(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    event = _commit_events(factory, 35)[0]
    clock.now = NOW + timedelta(minutes=1)
    with factory() as work:
        acknowledged = work.alerts.acknowledge(event.event_id)
        work.commit()
    assert acknowledged.acknowledged_at == clock.now

    stream = _stream(factory)
    asyncio.run(stream.publish_committed(event))


def test_gap_forces_snapshot_before_any_incremental_event(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    _commit_events(factory, 40, 41, 42)
    with create_session_factory(database_engine).begin() as session:
        session.execute(delete(MonitorEventRow).where(MonitorEventRow.sequence == 2))

    with TestClient(create_app(websocket_service=_stream(factory))).websocket_connect(
        "/ws/v1/monitor?after=0"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame == {
        "type": "snapshot.required",
        "sequence": 3,
        "reason": "REPLAY_UNAVAILABLE",
    }


def test_gap_beyond_the_first_page_is_detected_before_returning_events(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    _commit_events(factory, 43, 44, 45)
    with create_session_factory(database_engine).begin() as session:
        session.execute(delete(MonitorEventRow).where(MonitorEventRow.sequence == 3))

    with factory() as work:
        page = work.events.replay_page_after(0, limit=2)

    assert page.requires_snapshot is True
    assert page.high_water_sequence == 3
    assert page.events == ()


def test_sequence_high_water_behind_committed_storage_fails_closed(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    clock.now = NOW - timedelta(days=8)
    _commit_events(factory, 45, evaluated_at=clock.now - timedelta(minutes=1))
    clock.now = NOW
    with create_session_factory(database_engine).begin() as session:
        state = session.get(MonitorSequence, 1)
        assert state is not None
        state.last_sequence = 0

    client = TestClient(create_app(websocket_service=_stream(factory)))
    with client.websocket_connect("/ws/v1/monitor?after=0") as websocket:
        with pytest.raises(WebSocketDisconnect) as captured:
            websocket.receive_json()

    assert captured.value.code == 1011


def test_expired_seven_day_replay_forces_snapshot_recovery(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    clock.now = NOW - timedelta(days=7, seconds=1)
    _commit_events(factory, 50, evaluated_at=clock.now - timedelta(minutes=1))
    clock.now = NOW
    _commit_events(factory, 51)

    with TestClient(create_app(websocket_service=_stream(factory))).websocket_connect(
        "/ws/v1/monitor?after=0"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "snapshot.required"
    assert frame["sequence"] == 2
    assert frame["reason"] == "REPLAY_UNAVAILABLE"


def test_empty_stream_uses_exact_twenty_second_default_heartbeat_contract(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    module = _websocket_module()
    default_stream = module.CommittedMonitorEventStream(unit_of_work_factory=factory)
    assert module.DEFAULT_HEARTBEAT_SECONDS == 20
    assert default_stream.heartbeat_interval_seconds == 20

    fast_stream = _stream(factory)
    with TestClient(create_app(websocket_service=fast_stream)).websocket_connect(
        "/ws/v1/monitor?after=0"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame == {
        "type": "heartbeat",
        "sequence": 0,
        "runtimeLive": False,
        "runtimeGeneration": None,
        "runtimeStartedAt": None,
    }


def test_heartbeat_fails_closed_after_runtime_progress_deadline(
    database_engine: Engine,
    clock: _Clock,
) -> None:
    factory = _unit_of_work_factory(database_engine, clock)
    runtime = SimpleNamespace(
        status=RuntimeServiceStatus.RUNNING,
        read_only=False,
        observed_at=NOW,
        started_at=NOW - timedelta(minutes=1),
        next_poll_at=NOW + timedelta(seconds=30),
        runtime_generation=LEGACY_RUNTIME_GENERATION,
    )
    module = _websocket_module()
    stream = module.CommittedMonitorEventStream(
        unit_of_work_factory=factory,
        runtime_liveness_provider=lambda: runtime,
        clock=clock,
    )

    assert stream._heartbeat_frame(4) == {
        "type": "heartbeat",
        "sequence": 4,
        "runtimeLive": True,
        "runtimeGeneration": str(LEGACY_RUNTIME_GENERATION),
        "runtimeStartedAt": runtime.started_at.isoformat(),
    }

    clock.now = NOW + timedelta(minutes=1)
    assert stream._heartbeat_frame(4) == {
        "type": "heartbeat",
        "sequence": 4,
        "runtimeLive": False,
        "runtimeGeneration": None,
        "runtimeStartedAt": None,
    }


@pytest.mark.parametrize(
    "after",
    [
        "",
        "-1",
        "+1",
        "01",
        "not-a-sequence",
        str(2**63),
        str(2**53),
        "9" * 20,
        pytest.param("9" * 5_000, id="too-many-digits"),
        "0&after=1",
    ],
)
def test_invalid_replay_cursor_is_closed_without_detail(after: str) -> None:
    client = TestClient(create_app(websocket_service=object()))

    with client.websocket_connect(f"/ws/v1/monitor?after={after}") as websocket:
        with pytest.raises(WebSocketDisconnect) as captured:
            websocket.receive_json()

    assert captured.value.code == 1008
