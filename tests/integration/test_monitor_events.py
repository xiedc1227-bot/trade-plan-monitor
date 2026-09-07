"""Unified durable monitor-event ledger contract tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path
from threading import Barrier
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine

from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 24, 11, 0, tzinfo=SHANGHAI)
SYMBOL = "003043.SZ"


@pytest.fixture
def database_engine(tmp_path: Path) -> Engine:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    upgrade_database(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _module():
    return import_module("trade_plan_monitor.state.events")


def _factory(engine: Engine):
    session_factory = create_session_factory(engine)
    return lambda: SqlAlchemyUnitOfWork(session_factory, clock=lambda: NOW)


def _drafts():
    events = _module()
    event_types = events.MonitorEventType
    payload = events.MonitorEventPayload
    draft = events.MonitorEventDraft
    values = (
        (
            event_types.SYMBOL_SNAPSHOT_UPDATED,
            SYMBOL,
            payload(entity_id=SYMBOL, symbol=SYMBOL, result_hash="a" * 64),
        ),
        (
            event_types.SYMBOL_HEALTH_UPDATED,
            SYMBOL,
            payload(entity_id=SYMBOL, symbol=SYMBOL, revision=2, status="LIVE"),
        ),
        (
            event_types.ALERT_CREATED,
            str(UUID(int=3)),
            payload(entity_id=str(UUID(int=3)), symbol=SYMBOL, revision=0),
        ),
        (
            event_types.ALERT_ACKNOWLEDGED,
            str(UUID(int=3)),
            payload(entity_id=str(UUID(int=3)), symbol=SYMBOL, revision=1),
        ),
        (
            event_types.PLAN_EXTRACTION_UPDATED,
            "extract-5",
            payload(entity_id="extract-5", revision=3, status="SUCCEEDED"),
        ),
        (
            event_types.PLAN_ACTIVATED,
            SYMBOL,
            payload(entity_id="plan-version-6", symbol=SYMBOL, revision=4),
        ),
        (
            event_types.PLAN_DEACTIVATED,
            SYMBOL,
            payload(entity_id=SYMBOL, symbol=SYMBOL, revision=5),
        ),
        (
            event_types.POSITION_UPDATED,
            "lot-8",
            payload(entity_id="lot-8", symbol=SYMBOL, status="OPEN"),
        ),
        (
            event_types.AI_PROVIDER_UPDATED,
            "provider-9",
            payload(entity_id="provider-9", revision=7),
        ),
        (
            event_types.SYSTEM_HEALTH_UPDATED,
            "TUSHARE_RT_MIN",
            payload(entity_id="TUSHARE_RT_MIN", status="READY"),
        ),
        (
            event_types.MARKET_INDEX_UPDATED,
            "000688.SH",
            payload(entity_id="000688.SH", revision=1, status="LIVE"),
        ),
    )
    return tuple(
        draft(
            event_id=(
                UUID(int=3) if event_type is event_types.ALERT_CREATED else UUID(int=100 + index)
            ),
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=event_payload,
            occurred_at=NOW + timedelta(seconds=index),
        )
        for index, (event_type, aggregate_id, event_payload) in enumerate(values, start=1)
    )


def test_global_event_log_sequences_every_closed_event_type_and_restarts(
    database_engine: Engine,
) -> None:
    factory = _factory(database_engine)
    drafts = _drafts()
    with factory() as work:
        created = tuple(work.events.append(draft) for draft in drafts)
        work.commit()

    assert tuple(event.sequence for event in created) == tuple(range(1, 12))
    assert tuple(event.event_type for event in drafts) == tuple(_module().MonitorEventType)
    assert tuple(event.event_type for event in created) == tuple(
        event.event_type for event in drafts
    )

    with factory() as restarted:
        page = restarted.events.replay_page_after(0)
        assert restarted.events.current_sequence() == 11

    assert page.requires_snapshot is False
    assert page.high_water_sequence == 11
    assert page.events == created


def test_market_index_event_commits_and_replays_after_the_previous_cursor(
    database_engine: Engine,
) -> None:
    events = _module()
    factory = _factory(database_engine)
    baseline = _drafts()[-2]
    market_index = events.MonitorEventDraft(
        event_id=UUID(int=201),
        event_type=events.MonitorEventType.MARKET_INDEX_UPDATED,
        aggregate_id="000688.SH",
        payload=events.MonitorEventPayload(
            entity_id="000688.SH",
            revision=1,
            status="LIVE",
        ),
        occurred_at=NOW + timedelta(seconds=20),
    )

    with factory() as work:
        first = work.events.append(baseline)
        committed = work.events.append(market_index)
        work.commit()

    with factory() as restarted:
        page = restarted.events.replay_page_after(first.sequence)

    assert page.requires_snapshot is False
    assert page.high_water_sequence == committed.sequence
    assert page.events == (committed,)


@pytest.mark.parametrize(
    ("draft_index", "draft_update", "payload_update"),
    (
        (0, {"aggregate_id": "000001.SZ"}, {}),
        (0, {}, {"entity_id": "000001.SZ"}),
        (0, {}, {"revision": 1}),
        (1, {}, {"symbol": "000001.SZ"}),
        (1, {}, {"entity_id": "000001.SZ"}),
        (1, {}, {"result_hash": "b" * 64}),
        (2, {"event_id": UUID(int=999)}, {}),
        (2, {}, {"revision": 1}),
        (3, {}, {"revision": 0}),
        (4, {"aggregate_id": "extract-other"}, {}),
        (4, {}, {"symbol": SYMBOL}),
        (5, {}, {"symbol": "000001.SZ"}),
        (5, {}, {"status": "ACTIVE"}),
        (6, {}, {"entity_id": "plan-version-other"}),
        (6, {}, {"result_hash": "b" * 64}),
        (7, {}, {"status": None}),
        (7, {"aggregate_id": "lot-other"}, {}),
        (7, {}, {"status": "STALE"}),
        (7, {}, {"revision": 2}),
        (8, {"aggregate_id": "provider-other"}, {}),
        (8, {}, {"status": "READY"}),
        (9, {"aggregate_id": "OTHER_CAPABILITY"}, {}),
        (9, {}, {"revision": 1}),
    ),
)
def test_event_payload_contract_rejects_wrong_identity_and_non_applicable_hints(
    draft_index: int,
    draft_update: dict[str, object],
    payload_update: dict[str, object],
) -> None:
    events = _module()
    document = _drafts()[draft_index].model_dump(mode="python", round_trip=True)
    document.update(draft_update)
    document["payload"] = {
        **document["payload"],
        **payload_update,
    }

    with pytest.raises(ValidationError):
        events.MonitorEventDraft.model_validate(document)


def test_global_event_identity_is_idempotent_and_conflicts_fail_closed(
    database_engine: Engine,
) -> None:
    factory = _factory(database_engine)
    original = _drafts()[1]
    with factory() as work:
        first = work.events.append(original)
        assert work.events.append(original) == first
        work.commit()

    conflicting = original.model_copy(
        update={
            "payload": original.payload.model_copy(update={"status": "STALE"}),
        }
    )
    with factory() as work:
        with pytest.raises(_module().MonitorEventIdentityConflictError):
            work.events.append(conflicting)

    with factory() as work:
        assert work.events.current_sequence() == 1


def test_global_event_and_sequence_roll_back_together(database_engine: Engine) -> None:
    factory = _factory(database_engine)
    with factory() as work:
        work.events.append(_drafts()[0])
        # Leaving without commit rolls back the event and its high-water update.

    with factory() as work:
        assert work.events.current_sequence() == 0
        assert work.events.replay_page_after(0).events == ()


def test_concurrent_global_event_writers_allocate_distinct_sequences(
    database_engine: Engine,
) -> None:
    factory = _factory(database_engine)
    barrier = Barrier(2)

    def append(index: int) -> int:
        draft = _drafts()[index]
        barrier.wait()
        with factory() as work:
            event = work.events.append(draft)
            work.commit()
            return event.sequence

    with ThreadPoolExecutor(max_workers=2) as executor:
        sequences = tuple(executor.map(append, (0, 1)))

    assert set(sequences) == {1, 2}
    with factory() as work:
        assert tuple(event.sequence for event in work.events.replay_page_after(0).events) == (1, 2)


def test_global_event_numeric_fields_are_bounded_to_sqlite_int64(
    database_engine: Engine,
) -> None:
    events = _module()
    with pytest.raises(ValidationError):
        events.MonitorEventPayload(entity_id="provider-1", revision=2**63)

    with _factory(database_engine)() as work:
        with pytest.raises(ValueError, match="SQLite integer range"):
            work.events.replay_page_after(2**63)


def test_global_event_sequence_refuses_to_cross_the_public_safe_integer_boundary(
    database_engine: Engine,
) -> None:
    events = _module()
    session_factory = create_session_factory(database_engine)
    with session_factory.begin() as session:
        state = session.get(events.MonitorSequence, 1)
        assert state is not None
        state.last_sequence = events.MAX_PUBLIC_SEQUENCE

    with _factory(database_engine)() as work:
        assert work.events.current_sequence() == events.MAX_PUBLIC_SEQUENCE
        with pytest.raises(events.MonitorEventStorageError, match="sequence state is invalid"):
            work.events.append(_drafts()[0])

    with _factory(database_engine)() as work:
        assert work.events.current_sequence() == events.MAX_PUBLIC_SEQUENCE


@pytest.mark.parametrize(
    "operation",
    ("append", "lock", "get", "current_sequence", "replay"),
)
def test_global_event_storage_failures_are_sanitized_at_every_public_db_boundary(
    tmp_path: Path,
    operation: str,
) -> None:
    engine = create_sqlite_engine(tmp_path / f"missing-monitor-{operation}.db")
    try:
        with _factory(engine)() as work:
            with pytest.raises(_module().MonitorEventStorageError) as error_info:
                if operation == "append":
                    work.events.append(_drafts()[0])
                elif operation == "lock":
                    work.events.lock_for_append()
                elif operation == "get":
                    work.events.get(UUID(int=1))
                elif operation == "current_sequence":
                    work.events.current_sequence()
                else:
                    work.events.replay_page_after(0)

        public_error = error_info.value
        assert "monitor_sequence" not in str(public_error)
        assert "SELECT" not in repr(public_error)
        assert public_error.__context__ is None
        assert public_error.__cause__ is None
    finally:
        engine.dispose()
