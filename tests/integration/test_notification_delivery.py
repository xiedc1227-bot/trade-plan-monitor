"""Transactional notification-outbox persistence contract tests."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Lock
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy import event as sqlalchemy_event

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
from trade_plan_monitor.notifications.channels import (
    ChannelDeliveryResult,
    ChannelErrorCode,
    ConsoleChannel,
    DeliveryChannel,
    WebhookChannel,
    WebhookConfig,
)
from trade_plan_monitor.notifications.dispatcher import (
    DEFAULT_RETRY_BACKOFF,
    DeliveryAttemptStatus,
    DeliveryStorageError,
    NotificationDispatcher,
)
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import AlertPayload, AlertSeverity
from trade_plan_monitor.notifications.outbox import (
    AlertIdentityConflictError,
    OutboxStorageError,
)
from trade_plan_monitor.notifications.render import render_alert
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import AlertEvent as AlertEventRow
from trade_plan_monitor.state.models import (
    AuditLog,
    DeliveryAttempt,
    PositionLot,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 8, 21, 10, 30, tzinfo=SHANGHAI)
PLAN_HASH = "a" * 64
SYMBOL = "003043.SZ"


@pytest.fixture
def database_engine(tmp_path: Path) -> Engine:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    upgrade_database(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _unit_of_work(engine: Engine, *, now: datetime = NOW) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(
        create_session_factory(engine),
        clock=lambda: now,
    )


def _payload(
    identity: int,
    *,
    evaluated_at: datetime | None = None,
    event_id: UUID | None = None,
    name: str = "华亚智能",
) -> AlertPayload:
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
        event_id=event_id or UUID(int=identity),
        dedup_key=alert_dedup_key(signal),
        plan_id="huaya-smart",
        plan_version=1,
        plan_hash=PLAN_HASH,
        symbol=SYMBOL,
        name=name,
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


def _row_counts(engine: Engine) -> tuple[int, int, int]:
    with create_session_factory(engine)() as session:
        return (
            session.scalar(select(func.count()).select_from(AlertEventRow)) or 0,
            session.scalar(select(func.count()).select_from(PositionLot)) or 0,
            session.scalar(select(func.count()).select_from(AuditLog)) or 0,
        )


def _with_decimal_fact(payload: AlertPayload, value: Decimal) -> AlertPayload:
    evidence = payload.matched_conditions[0].model_copy(
        update={
            "facts": (
                EvidenceFact(
                    key="observed_ratio",
                    value=value,
                    unit=EvidenceUnit.RATIO,
                ),
            ),
        }
    )
    return payload.model_copy(
        update={
            "matched_conditions": (evidence,),
            "satisfied_conditions": (evidence,),
        }
    )


def test_state_audit_and_outbox_commit_or_rollback_in_one_transaction(
    database_engine: Engine,
) -> None:
    committed_payload = _payload(1)
    with _unit_of_work(database_engine) as work:
        event = work.alerts.enqueue(committed_payload)
        work.positions.record_buy(
            symbol=SYMBOL,
            bucket="CORE",
            quantity=100,
            acquired_trade_date=date(2026, 8, 20),
            cost_fen=6400,
            board_lot=100,
            max_position_qty=1_000,
            related_alert_id=str(event.event_id),
        )
        work.commit()

    assert _row_counts(database_engine) == (1, 1, 1)

    with _unit_of_work(database_engine) as work:
        event = work.alerts.enqueue(_payload(2))
        work.positions.record_buy(
            symbol=SYMBOL,
            bucket="TACTICAL",
            quantity=100,
            acquired_trade_date=date(2026, 8, 20),
            cost_fen=6500,
            board_lot=100,
            max_position_qty=1_000,
            related_alert_id=str(event.event_id),
        )
        # Leaving the unit of work without commit simulates an interrupted transaction.

    assert _row_counts(database_engine) == (1, 1, 1)


def test_concurrent_dedup_enqueue_has_one_unique_claim(database_engine: Engine) -> None:
    payload = _payload(10)
    start = Barrier(2)

    def enqueue_once() -> tuple[UUID, int]:
        with _unit_of_work(database_engine) as work:
            start.wait(timeout=5)
            event = work.alerts.enqueue(payload)
            work.commit()
            return event.event_id, event.sequence

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: enqueue_once(), range(2)))

    assert results == [(payload.event_id, 1), (payload.event_id, 1)]
    assert _row_counts(database_engine)[0] == 1


def test_restart_dedup_preserves_original_event_identity(database_engine: Engine) -> None:
    original = _payload(20)
    with _unit_of_work(database_engine) as work:
        first = work.alerts.enqueue(original)
        work.commit()

    retried = original.model_copy(update={"event_id": UUID(int=21)})
    with _unit_of_work(database_engine, now=NOW + timedelta(minutes=5)) as work:
        replayed = work.alerts.enqueue(retried)
        work.commit()

    assert replayed == first
    assert replayed.event_id == original.event_id
    assert replayed.sequence == 1
    assert _row_counts(database_engine)[0] == 1


def test_restart_dedup_normalizes_decimal_scale_and_signed_zero(
    database_engine: Engine,
) -> None:
    scaled = _with_decimal_fact(_payload(22), Decimal("1.50"))
    with _unit_of_work(database_engine) as work:
        scaled_event = work.alerts.enqueue(scaled)
        work.commit()

    equivalent_scale = _with_decimal_fact(
        scaled.model_copy(update={"event_id": UUID(int=23)}),
        Decimal("1.5"),
    )
    with _unit_of_work(database_engine) as work:
        assert work.alerts.enqueue(equivalent_scale) == scaled_event
        work.commit()

    zero = _with_decimal_fact(_payload(24), Decimal("0.00"))
    with _unit_of_work(database_engine) as work:
        zero_event = work.alerts.enqueue(zero)
        work.commit()

    signed_zero = _with_decimal_fact(
        zero.model_copy(update={"event_id": UUID(int=25)}),
        Decimal("-0.0"),
    )
    with _unit_of_work(database_engine) as work:
        assert work.alerts.enqueue(signed_zero) == zero_event
        work.commit()


def test_restart_dedup_preserves_integer_and_decimal_type_identity(
    database_engine: Engine,
) -> None:
    original = _payload(26)
    integer_evidence = original.matched_conditions[0].model_copy(
        update={
            "facts": (
                EvidenceFact(
                    key="quantity",
                    value=1,
                    unit=EvidenceUnit.SHARES,
                ),
            ),
        }
    )
    integer_payload = original.model_copy(
        update={
            "matched_conditions": (integer_evidence,),
            "satisfied_conditions": (integer_evidence,),
        }
    )
    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(integer_payload)
        work.commit()

    decimal_evidence = integer_evidence.model_copy(
        update={
            "facts": (
                EvidenceFact(
                    key="quantity",
                    value=Decimal("1"),
                    unit=EvidenceUnit.SHARES,
                ),
            ),
        }
    )
    conflicting = integer_payload.model_copy(
        update={
            "event_id": UUID(int=27),
            "matched_conditions": (decimal_evidence,),
            "satisfied_conditions": (decimal_evidence,),
        }
    )
    with _unit_of_work(database_engine) as work:
        with pytest.raises(AlertIdentityConflictError, match="conflicting semantics"):
            work.alerts.enqueue(conflicting)


def test_dedup_identity_rejects_conflicting_semantic_payload(database_engine: Engine) -> None:
    original = _payload(30)
    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(original)
        work.commit()

    conflicting = original.model_copy(
        update={"event_id": UUID(int=31), "name": "冲突名称"},
    )
    with _unit_of_work(database_engine) as work:
        with pytest.raises(AlertIdentityConflictError, match="identity"):
            work.alerts.enqueue(conflicting)

    assert _row_counts(database_engine)[0] == 1


def test_outbox_assigns_ordered_sequences_and_replays_after_cursor(
    database_engine: Engine,
) -> None:
    with _unit_of_work(database_engine) as work:
        created = tuple(work.alerts.enqueue(_payload(identity)) for identity in (40, 41, 42))
        work.commit()

    assert tuple(event.sequence for event in created) == (1, 2, 3)

    with _unit_of_work(database_engine) as work:
        replayed = work.alerts.replay_after(1)

    assert tuple(event.event_id for event in replayed) == (
        UUID(int=41),
        UUID(int=42),
    )
    assert tuple(event.sequence for event in replayed) == (2, 3)


def test_replay_sequence_does_not_reset_after_retained_events_are_deleted(
    database_engine: Engine,
) -> None:
    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(_payload(43))
        work.alerts.enqueue(_payload(44))
        work.commit()

    with create_session_factory(database_engine).begin() as session:
        session.execute(delete(AlertEventRow))

    with _unit_of_work(database_engine) as work:
        newest = work.alerts.enqueue(_payload(45))
        work.commit()

    assert newest.sequence == 3
    with _unit_of_work(database_engine) as work:
        assert work.alerts.replay_after(2) == (newest,)


def test_replay_includes_exact_seven_day_boundary(database_engine: Engine) -> None:
    event_times = (
        NOW - timedelta(days=7, seconds=1),
        NOW - timedelta(days=7),
        NOW - timedelta(minutes=1),
    )
    for identity, created_at in zip((50, 51, 52), event_times, strict=True):
        payload = _payload(identity, evaluated_at=created_at - timedelta(minutes=1))
        with _unit_of_work(database_engine, now=created_at) as work:
            work.alerts.enqueue(payload)
            work.commit()

    with _unit_of_work(database_engine, now=NOW) as work:
        replayed = work.alerts.replay_after(0)

    assert tuple(event.event_id for event in replayed) == (UUID(int=51), UUID(int=52))
    assert tuple(event.sequence for event in replayed) == (2, 3)


def test_replay_retention_must_be_valid_before_unit_of_work_opens(
    database_engine: Engine,
) -> None:
    with pytest.raises(ValueError, match="replay_retention"):
        SqlAlchemyUnitOfWork(
            create_session_factory(database_engine),
            replay_retention=timedelta(0),
        )


def test_replay_rejects_stored_event_identity_mismatch(database_engine: Engine) -> None:
    payload = _payload(55)
    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(payload)
        work.commit()

    with create_session_factory(database_engine).begin() as session:
        row = session.get(AlertEventRow, str(payload.event_id))
        assert row is not None
        mismatched_payload = payload.model_copy(
            update={"event_id": UUID(int=56)},
        )
        row.payload_json = mismatched_payload.model_dump_json()
        row.message_text = render_alert(mismatched_payload)

    with _unit_of_work(database_engine) as work:
        with pytest.raises(OutboxStorageError, match="Stored alert event"):
            work.alerts.get(payload.event_id)


def test_replay_storage_error_has_no_raw_payload_context(database_engine: Engine) -> None:
    payload = _payload(57)
    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(payload)
        work.commit()

    raw_marker = "raw-payload-must-not-escape"
    with create_session_factory(database_engine).begin() as session:
        row = session.get(AlertEventRow, str(payload.event_id))
        assert row is not None
        row.payload_json = '{"name":"' + raw_marker + '"'

    with _unit_of_work(database_engine) as work:
        with pytest.raises(OutboxStorageError) as error_info:
            work.alerts.get(payload.event_id)

    public_error = error_info.value
    assert raw_marker not in str(public_error)
    assert raw_marker not in repr(public_error)
    assert public_error.__context__ is None
    assert public_error.__cause__ is None


def test_acknowledge_is_idempotent_audited_and_does_not_change_position(
    database_engine: Engine,
) -> None:
    payload = _payload(60)
    with _unit_of_work(database_engine) as work:
        event = work.alerts.enqueue(payload)
        position_before = work.positions.record_buy(
            symbol=SYMBOL,
            bucket="CORE",
            quantity=100,
            acquired_trade_date=date(2026, 8, 20),
            cost_fen=6400,
            board_lot=100,
            max_position_qty=1_000,
            related_alert_id=str(event.event_id),
        )
        work.commit()

    acknowledged_at = NOW + timedelta(minutes=1)
    with _unit_of_work(database_engine, now=acknowledged_at) as work:
        acknowledged = work.alerts.acknowledge(event.event_id)
        position_after = work.positions.get_lot(position_before.id)
        work.commit()

    with _unit_of_work(database_engine, now=NOW + timedelta(minutes=2)) as work:
        repeated = work.alerts.acknowledge(event.event_id)
        work.commit()

    assert acknowledged.acknowledged_at == acknowledged_at
    assert repeated == acknowledged
    assert position_after == position_before

    with create_session_factory(database_engine)() as session:
        acknowledgement_audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "ALERT_ACKNOWLEDGED")
        ).all()
        assert len(acknowledgement_audits) == 1
        assert acknowledgement_audits[0].entity_type == "ALERT_EVENT"
        assert acknowledgement_audits[0].entity_id == str(event.event_id)
        assert acknowledgement_audits[0].before_hash is not None
        assert acknowledgement_audits[0].after_hash is not None
        assert acknowledgement_audits[0].before_hash != acknowledgement_audits[0].after_hash
        assert session.scalar(select(func.count()).select_from(DeliveryAttempt)) == 0


def test_acknowledge_integrity_failure_is_sanitized_and_atomic(
    database_engine: Engine,
) -> None:
    payload = _payload(70)
    with _unit_of_work(database_engine) as work:
        event = work.alerts.enqueue(payload)
        work.commit()

    collision_id = "audit-collision"
    with create_session_factory(database_engine).begin() as session:
        session.add(
            AuditLog(
                id=collision_id,
                action="TEST_SENTINEL",
                entity_type="TEST",
                entity_id="sentinel",
                before_hash=None,
                after_hash=None,
                details_json="{}",
                created_at=NOW.isoformat(),
            )
        )

    work = SqlAlchemyUnitOfWork(
        create_session_factory(database_engine),
        clock=lambda: NOW + timedelta(minutes=1),
        id_factory=lambda: collision_id,
    )
    with work:
        with pytest.raises(OutboxStorageError) as error_info:
            work.alerts.acknowledge(event.event_id)

    public_error = error_info.value
    assert "INSERT INTO" not in str(public_error)
    assert "audit_log" not in repr(public_error)
    assert public_error.__context__ is None
    assert public_error.__cause__ is None
    with create_session_factory(database_engine)() as session:
        row = session.get(AlertEventRow, str(event.event_id))
        assert row is not None
        assert row.acknowledged_at is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "ALERT_ACKNOWLEDGED")
            )
            == 0
        )


def _attempt_ids() -> object:
    for identity in range(1, 100):
        yield f"delivery-{identity:03d}"


def test_dispatcher_recovers_a_committed_event_after_restart_and_skips_disabled_webhook(
    database_engine: Engine,
) -> None:
    with _unit_of_work(database_engine) as work:
        committed = work.alerts.enqueue(_payload(80))
        work.commit()

    console_lines: list[str] = []
    identities = _attempt_ids()
    dispatcher = NotificationDispatcher(
        create_session_factory(database_engine),
        channels=(
            ConsoleChannel(write_line=console_lines.append),
            WebhookChannel(client=httpx.AsyncClient(), config=WebhookConfig()),
        ),
        clock=lambda: NOW,
        id_factory=lambda: next(identities),
    )
    try:
        attempts = asyncio.run(dispatcher.dispatch_pending())
    finally:
        asyncio.run(dispatcher.aclose())

    assert tuple(attempt.channel for attempt in attempts) == (
        DeliveryChannel.IN_APP,
        DeliveryChannel.CONSOLE,
    )
    assert all(attempt.status is DeliveryAttemptStatus.DELIVERED for attempt in attempts)
    assert str(committed.event_id) in console_lines[0]
    with _unit_of_work(database_engine) as work:
        assert work.alerts.get(committed.event_id) == committed
    with create_session_factory(database_engine)() as session:
        assert session.scalars(select(DeliveryAttempt)).all()
        assert (
            session.scalar(
                select(func.count())
                .select_from(DeliveryAttempt)
                .where(DeliveryAttempt.channel == DeliveryChannel.WEBHOOK.value)
            )
            == 0
        )


def test_console_and_webhook_failures_remain_isolated_from_mandatory_in_app_delivery(
    database_engine: Engine,
) -> None:
    raw_marker = "raw-channel-failure-must-not-escape"

    def fail_console(_line: str) -> None:
        raise RuntimeError(raw_marker)

    def fail_webhook(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=raw_marker, request=request)

    with _unit_of_work(database_engine) as work:
        committed = work.alerts.enqueue(_payload(81))
        work.commit()

    async def dispatch() -> tuple[object, ...]:
        identities = _attempt_ids()
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail_webhook)) as client:
            dispatcher = NotificationDispatcher(
                create_session_factory(database_engine),
                channels=(
                    ConsoleChannel(write_line=fail_console),
                    WebhookChannel(
                        client=client,
                        config=WebhookConfig(
                            enabled=True,
                            endpoint="https://hooks.example.test/alerts",
                            allowlisted_hosts=("hooks.example.test",),
                        ),
                    ),
                ),
                clock=lambda: NOW,
                id_factory=lambda: next(identities),
            )
            return await dispatcher.dispatch_pending()

    attempts = asyncio.run(dispatch())
    by_channel = {attempt.channel: attempt for attempt in attempts}

    assert by_channel[DeliveryChannel.IN_APP].status is DeliveryAttemptStatus.DELIVERED
    assert by_channel[DeliveryChannel.CONSOLE].status is DeliveryAttemptStatus.RETRY_PENDING
    assert by_channel[DeliveryChannel.WEBHOOK].status is DeliveryAttemptStatus.RETRY_PENDING
    assert by_channel[DeliveryChannel.CONSOLE].error_code is ChannelErrorCode.CONSOLE_WRITE_FAILED
    assert by_channel[DeliveryChannel.WEBHOOK].error_code is ChannelErrorCode.WEBHOOK_TRANSIENT
    assert raw_marker not in repr(attempts)
    with _unit_of_work(database_engine) as work:
        assert work.alerts.get(committed.event_id) == committed


def test_webhook_retry_schedule_is_persistent_bounded_and_uses_the_same_event_id(
    database_engine: Engine,
) -> None:
    requested_event_ids: list[str] = []

    def fail_webhook(request: httpx.Request) -> httpx.Response:
        requested_event_ids.append(json.loads(request.content)["eventId"])
        return httpx.Response(503, request=request)

    with _unit_of_work(database_engine) as work:
        committed = work.alerts.enqueue(_payload(82))
        work.commit()

    current_time = [NOW]
    identities = _attempt_ids()

    async def run_attempt() -> tuple[object, ...]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail_webhook)) as client:
            dispatcher = NotificationDispatcher(
                create_session_factory(database_engine),
                channels=(
                    WebhookChannel(
                        client=client,
                        config=WebhookConfig(
                            enabled=True,
                            endpoint="https://hooks.example.test/alerts",
                            allowlisted_hosts=("hooks.example.test",),
                        ),
                    ),
                ),
                clock=lambda: current_time[0],
                id_factory=lambda: next(identities),
            )
            return await dispatcher.dispatch_pending()

    first = asyncio.run(run_attempt())
    assert tuple(attempt.channel for attempt in first) == (
        DeliveryChannel.IN_APP,
        DeliveryChannel.WEBHOOK,
    )
    assert asyncio.run(run_attempt()) == ()

    for delay in DEFAULT_RETRY_BACKOFF:
        current_time[0] += delay
        asyncio.run(run_attempt())

    current_time[0] += timedelta(days=1)
    assert asyncio.run(run_attempt()) == ()
    assert requested_event_ids == [str(committed.event_id)] * 4

    with create_session_factory(database_engine)() as session:
        rows = session.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.channel == DeliveryChannel.WEBHOOK.value)
            .order_by(DeliveryAttempt.attempt)
        ).all()
    assert [row.attempt for row in rows] == [1, 2, 3, 4]
    assert [row.status for row in rows] == [
        DeliveryAttemptStatus.RETRY_PENDING.value,
        DeliveryAttemptStatus.RETRY_PENDING.value,
        DeliveryAttemptStatus.RETRY_PENDING.value,
        DeliveryAttemptStatus.FAILED.value,
    ]
    assert [row.next_retry_at for row in rows] == [
        (NOW + timedelta(seconds=30)).isoformat(),
        (NOW + timedelta(seconds=90)).isoformat(),
        (NOW + timedelta(seconds=390)).isoformat(),
        None,
    ]


def test_non_retryable_webhook_failure_is_not_attempted_again(
    database_engine: Engine,
) -> None:
    request_count = 0

    def reject_webhook(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(422, text="private response", request=request)

    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(_payload(83))
        work.commit()

    async def dispatch_twice() -> tuple[tuple[object, ...], tuple[object, ...]]:
        identities = _attempt_ids()
        async with httpx.AsyncClient(transport=httpx.MockTransport(reject_webhook)) as client:
            dispatcher = NotificationDispatcher(
                create_session_factory(database_engine),
                channels=(
                    WebhookChannel(
                        client=client,
                        config=WebhookConfig(
                            enabled=True,
                            endpoint="https://hooks.example.test/alerts",
                            allowlisted_hosts=("hooks.example.test",),
                        ),
                    ),
                ),
                clock=lambda: NOW,
                id_factory=lambda: next(identities),
            )
            return await dispatcher.dispatch_pending(), await dispatcher.dispatch_pending()

    first, second = asyncio.run(dispatch_twice())

    assert first[-1].status is DeliveryAttemptStatus.FAILED
    assert first[-1].response_code == 422
    assert second == ()
    assert request_count == 1


def test_dispatch_limit_bounds_channel_work_and_uncommitted_events_are_invisible(
    database_engine: Engine,
) -> None:
    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(_payload(84))
    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(_payload(85))
        work.alerts.enqueue(_payload(86))
        work.commit()

    identities = _attempt_ids()
    dispatcher = NotificationDispatcher(
        create_session_factory(database_engine),
        channels=(),
        clock=lambda: NOW,
        id_factory=lambda: next(identities),
    )

    first = asyncio.run(dispatcher.dispatch_pending(limit=1))
    second = asyncio.run(dispatcher.dispatch_pending(limit=1))

    assert len(first) == 1
    assert len(second) == 1
    assert {first[0].event_id, second[0].event_id} == {UUID(int=85), UUID(int=86)}


def test_webhook_network_call_occurs_with_no_database_transaction_open(
    database_engine: Engine,
) -> None:
    active_transactions = 0

    @sqlalchemy_event.listens_for(database_engine, "begin")
    def track_begin(_connection: object) -> None:
        nonlocal active_transactions
        active_transactions += 1

    @sqlalchemy_event.listens_for(database_engine, "commit")
    @sqlalchemy_event.listens_for(database_engine, "rollback")
    def track_end(_connection: object) -> None:
        nonlocal active_transactions
        active_transactions -= 1

    def webhook(request: httpx.Request) -> httpx.Response:
        assert active_transactions == 0
        return httpx.Response(204, request=request)

    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(_payload(87))
        work.commit()

    async def dispatch() -> tuple[object, ...]:
        identities = _attempt_ids()
        async with httpx.AsyncClient(transport=httpx.MockTransport(webhook)) as client:
            dispatcher = NotificationDispatcher(
                create_session_factory(database_engine),
                channels=(
                    WebhookChannel(
                        client=client,
                        config=WebhookConfig(
                            enabled=True,
                            endpoint="https://hooks.example.test/alerts",
                            allowlisted_hosts=("hooks.example.test",),
                        ),
                    ),
                ),
                clock=lambda: NOW,
                id_factory=lambda: next(identities),
            )
            return await dispatcher.dispatch_pending()

    attempts = asyncio.run(dispatch())

    assert attempts[-1].status is DeliveryAttemptStatus.DELIVERED
    assert active_transactions == 0


def test_delivery_storage_failure_drops_sql_parameters_context_and_cause(
    database_engine: Engine,
) -> None:
    raw_marker = "secret-delivery-collision"
    with _unit_of_work(database_engine) as work:
        work.alerts.enqueue(_payload(88))
        work.alerts.enqueue(_payload(89))
        work.commit()

    dispatcher = NotificationDispatcher(
        create_session_factory(database_engine),
        channels=(),
        clock=lambda: NOW,
        id_factory=lambda: raw_marker,
    )

    with pytest.raises(DeliveryStorageError) as error_info:
        asyncio.run(dispatcher.dispatch_pending())

    public_error = error_info.value
    assert raw_marker not in str(public_error)
    assert raw_marker not in repr(public_error)
    assert public_error.__context__ is None
    assert public_error.__cause__ is None


@pytest.mark.parametrize("entrypoint", ("dispatch_pending", "dispatch_event"))
def test_concurrent_dispatchers_atomically_claim_one_external_delivery(
    database_engine: Engine,
    entrypoint: str,
) -> None:
    with _unit_of_work(database_engine) as work:
        committed = work.alerts.enqueue(_payload(90))
        work.commit()

    in_app = NotificationDispatcher(
        create_session_factory(database_engine),
        channels=(),
        clock=lambda: NOW,
        id_factory=lambda: "delivery-in-app",
    )
    assert asyncio.run(in_app.dispatch_pending())[0].channel is DeliveryChannel.IN_APP

    external_deliveries: list[UUID] = []
    delivery_lock = Lock()

    class RecordingChannel:
        channel = DeliveryChannel.CONSOLE
        enabled = True

        async def deliver(self, event: object) -> ChannelDeliveryResult:
            with delivery_lock:
                external_deliveries.append(event.event_id)
            return ChannelDeliveryResult(
                channel=self.channel,
                delivered=True,
                retryable=False,
            )

    claim_barrier = Barrier(2)
    identity_lock = Lock()
    next_identity = 0

    def synchronized_id() -> str:
        nonlocal next_identity
        claim_barrier.wait(timeout=5)
        with identity_lock:
            next_identity += 1
            return f"concurrent-delivery-{next_identity}"

    dispatchers = tuple(
        NotificationDispatcher(
            create_session_factory(database_engine),
            channels=(RecordingChannel(),),
            clock=lambda: NOW,
            id_factory=synchronized_id,
        )
        for _index in range(2)
    )
    with ThreadPoolExecutor(max_workers=2) as executor:

        def dispatch(dispatcher: NotificationDispatcher) -> tuple[object, ...]:
            operation = (
                dispatcher.dispatch_pending()
                if entrypoint == "dispatch_pending"
                else dispatcher.dispatch_event(committed.event_id)
            )
            return asyncio.run(operation)

        futures = tuple(executor.submit(dispatch, dispatcher) for dispatcher in dispatchers)
        results = tuple(future.result(timeout=10) for future in futures)

    assert external_deliveries == [committed.event_id]
    assert sum(len(result) for result in results) == 1
    with create_session_factory(database_engine)() as session:
        rows = session.scalars(
            select(DeliveryAttempt).where(
                DeliveryAttempt.event_id == str(committed.event_id),
                DeliveryAttempt.channel == DeliveryChannel.CONSOLE.value,
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].attempt == 1
    assert rows[0].status == DeliveryAttemptStatus.DELIVERED.value


def test_restart_reclaims_an_expired_attempt_without_allocating_a_new_attempt(
    database_engine: Engine,
) -> None:
    with _unit_of_work(database_engine) as work:
        committed = work.alerts.enqueue(_payload(91))
        work.commit()

    in_app = NotificationDispatcher(
        create_session_factory(database_engine),
        channels=(),
        clock=lambda: NOW,
        id_factory=lambda: "recovery-in-app",
    )
    asyncio.run(in_app.dispatch_pending())
    current_time = [NOW]
    delivered_ids: list[UUID] = []

    async def exercise_crash_and_recovery() -> tuple[object, ...]:
        started = asyncio.Event()
        never_finish = asyncio.Event()

        class BlockingChannel:
            channel = DeliveryChannel.CONSOLE
            enabled = True

            async def deliver(self, _event: object) -> ChannelDeliveryResult:
                started.set()
                await never_finish.wait()
                raise AssertionError("unreachable")

        crashing = NotificationDispatcher(
            create_session_factory(database_engine),
            channels=(BlockingChannel(),),
            clock=lambda: current_time[0],
            id_factory=lambda: "recoverable-claim",
        )
        task = asyncio.create_task(crashing.dispatch_pending())
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        class RecordingChannel:
            channel = DeliveryChannel.CONSOLE
            enabled = True

            async def deliver(self, event: object) -> ChannelDeliveryResult:
                delivered_ids.append(event.event_id)
                return ChannelDeliveryResult(
                    channel=self.channel,
                    delivered=True,
                    retryable=False,
                )

        restarted = NotificationDispatcher(
            create_session_factory(database_engine),
            channels=(RecordingChannel(),),
            clock=lambda: current_time[0],
            id_factory=lambda: (_ for _ in ()).throw(AssertionError("must reuse claim")),
        )
        assert await restarted.dispatch_pending() == ()
        current_time[0] += timedelta(seconds=60)
        return await restarted.dispatch_pending()

    recovered = asyncio.run(exercise_crash_and_recovery())

    assert delivered_ids == [committed.event_id]
    assert len(recovered) == 1
    assert recovered[0].attempt == 1
    assert recovered[0].status is DeliveryAttemptStatus.DELIVERED
    with create_session_factory(database_engine)() as session:
        rows = session.scalars(
            select(DeliveryAttempt).where(
                DeliveryAttempt.event_id == str(committed.event_id),
                DeliveryAttempt.channel == DeliveryChannel.CONSOLE.value,
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].attempt == 1
    assert rows[0].status == DeliveryAttemptStatus.DELIVERED.value


def test_dispatcher_rejects_a_channel_iterable_after_the_fourth_item() -> None:
    yielded = 0

    def overlong_channels() -> object:
        nonlocal yielded
        for _index in range(4):
            yielded += 1
            yield ConsoleChannel(write_line=lambda _line: None)
        raise AssertionError("dispatcher consumed beyond the closed channel vocabulary")

    with pytest.raises(ValueError, match="at most three"):
        NotificationDispatcher(lambda: None, channels=overlong_channels())

    assert yielded == 4
