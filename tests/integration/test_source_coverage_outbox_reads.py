"""Daily outbox admission reads current owners without flushing caller changes."""

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import event as sql_event
from sqlalchemy import insert, select, update
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_delivery import (
    _corrupt_source,
    _event,
    _message_with_metadata,
    _risk_event,
)
from tests.integration.test_source_coverage_delivery_dispatch import LocalRecordingChannel
from tests.integration.test_source_coverage_simulation_actions import current as current

from trade_plan_monitor.notifications.daily_models import DailyAlertPayload
from trade_plan_monitor.notifications.dispatcher import DeliveryStorageError, NotificationDispatcher
from trade_plan_monitor.notifications.outbox import OutboxStorageError
from trade_plan_monitor.state.models import AlertDeliveryEligibility, PlanSource, PlanVersion
from trade_plan_monitor.state.source_coverage_store import SourceCoverageIntegrityError


@contextmanager
def _read_only(session):
    statements, commits = [], []

    def statement(connection, cursor, sql, parameters, context, many):
        statements.append(sql.lstrip().upper())

    def commit(current):
        commits.append(current)

    engine = session.get_bind()
    sql_event.listen(engine, "before_cursor_execute", statement)
    sql_event.listen(session, "after_commit", commit)
    try:
        yield
    finally:
        sql_event.remove(engine, "before_cursor_execute", statement)
        sql_event.remove(session, "after_commit", commit)
    assert not commits
    # A deferred read transaction is permitted; writer BEGIN IMMEDIATE is not.
    assert all(sql == "BEGIN" or sql.startswith(("SELECT", "PRAGMA")) for sql in statements), [
        sql for sql in statements if sql != "BEGIN" and not sql.startswith(("SELECT", "PRAGMA"))]


def _metadata(event, now, *, status="HOLD"):
    # Adversarial recovery metadata is a veto input, never source authority.
    # Every event here already owns a real current source review and activation.
    return dict(event_id=str(event.event_id), schema_version=1, revision=0,
        delivery_class="STATE_RISK", source_cutoff=None, expires_at=None, status=status,
        reason="RECOVERY_REQUIRED", barrier_json=None, result_hash=None,
        updated_at=now.isoformat())


def _other_queued_event(work, event):
    other = _message_with_metadata(event, event_id=UUID(int=710921),
                                   cause_id="other-metadata-owner")
    payload = DailyAlertPayload.model_validate(other.model_dump(mode="python",
        exclude={"sequence", "message_text", "created_at", "acknowledged_at"}))
    return work.alerts.enqueue_daily(payload)


@pytest.mark.parametrize("method", ["is_delivery_allowed", "is_current_actionable"])
@pytest.mark.parametrize("owner", ["version", "source"])
@pytest.mark.parametrize("change", ["dirty", "new", "deleted"])
def test_outbox_delivery_keeps_relevant_pending_plan_change_unflushed(
    current, method, owner, change,
):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        version = session.get(PlanVersion, event.plan_version_id)
        model, identity, field = ((PlanVersion, version.id, "payload_json") if owner == "version"
                                 else (PlanSource, version.source_id, "source_text"))
        held = session.get(model, identity)
        before = {column.name: getattr(held, column.name) for column in model.__table__.columns}
        if change == "dirty":
            setattr(held, field, before[field] + " ")
        elif change == "new":
            held = model(**before)
            session.add(held)
        else:
            session.delete(held)
        expected = (OutboxStorageError if method == "is_delivery_allowed"
                    else SourceCoverageIntegrityError)
        with _read_only(session), pytest.raises(expected):
            getattr(work.alerts, method)(event, market_date=chain.now.date())
        assert held in getattr(session, change)
        if change == "dirty":
            assert getattr(held, field) == before[field] + " "
        with session.no_autoflush:
            primary_key, = model.__table__.primary_key.columns
            stored = session.execute(select(model.__table__).where(primary_key == identity)
                                     ).mappings().one()
        assert stored == before


@pytest.mark.parametrize("change", ["new", "dirty", "deleted", "key-out", "key-in"])
def test_pending_delivery_metadata_cannot_flush_or_grant_new_permission(current, change):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        values = _metadata(event, chain.now)
        if change == "new":
            held = AlertDeliveryEligibility(**values)
            session.add(held)
        else:
            if change == "key-in":
                # A real second canonical row owns the metadata's foreign key;
                # this synthetic queued row grants no permission for its cause.
                queued = _other_queued_event(work, event)
                values["event_id"] = str(queued.event_id)
            session.execute(insert(AlertDeliveryEligibility), values)
            held = session.get(AlertDeliveryEligibility, values["event_id"])
            if change == "dirty":
                held.reason = "Pending classification edit"
            elif change == "deleted":
                session.delete(held)
            else:
                held.event_id = (str(UUID(int=710922)) if change == "key-out"
                                 else str(event.event_id))
        with _read_only(session):
            assert not work.alerts.is_delivery_allowed(event, market_date=chain.now.date())
        assert held in (session.new if change == "new" else session.deleted if change == "deleted"
                        else session.dirty)
        with session.no_autoflush:
            stored = session.execute(select(AlertDeliveryEligibility.__table__).where(
                AlertDeliveryEligibility.event_id == values["event_id"])).mappings().one_or_none()
        assert stored == (None if change == "new" else values)


@pytest.mark.parametrize("status", ["HOLD", "SUPPRESS"])
def test_actual_metadata_veto_does_not_become_delivery_authority(current, status):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        session.execute(insert(AlertDeliveryEligibility),
                        _metadata(event, chain.now, status=status))
        with _read_only(session):
            assert not work.alerts.is_delivery_allowed(event, market_date=chain.now.date())
        # The old UI-current flag remains a distinct native actionability check.
        with _read_only(session):
            assert work.alerts.is_current_actionable(event, market_date=chain.now.date())


def test_cached_metadata_cannot_hide_a_committed_sql_veto(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        session.execute(insert(AlertDeliveryEligibility), _metadata(event, chain.now))
        held = session.get(AlertDeliveryEligibility, str(event.event_id))
        session.execute(update(AlertDeliveryEligibility).where(
            AlertDeliveryEligibility.event_id == held.event_id).values(status="SUPPRESS"),
            execution_options={"synchronize_session": False})
        # A clean stale cache must be refreshed, without erasing pending changes.
        assert held.status == "HOLD"
        with _read_only(session):
            assert not work.alerts.is_delivery_allowed(event, market_date=chain.now.date())
        assert held.status == "SUPPRESS"


def test_cached_eligible_status_cannot_bypass_actual_sql_hold(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        # Fault injection of the formerly cached status. It is never sufficient
        # authorization: the actual source/review/native guards remain mandatory.
        values = _metadata(event, chain.now, status="ELIGIBLE") | dict(
            barrier_json="{}", result_hash="a" * 64)
        session.execute(insert(AlertDeliveryEligibility), values)
        held = session.get(AlertDeliveryEligibility, str(event.event_id))
        session.execute(update(AlertDeliveryEligibility).where(
            AlertDeliveryEligibility.event_id == held.event_id).values(
                status="HOLD", barrier_json=None, result_hash=None),
            execution_options={"synchronize_session": False})
        assert held.status == "ELIGIBLE"
        with _read_only(session):
            assert not work.alerts.is_delivery_allowed(event, market_date=chain.now.date())
        assert held.status == "HOLD"


def test_unrelated_pending_metadata_neither_flushes_nor_vetoes_the_actual_event(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        other = _other_queued_event(work, event)
        pending = AlertDeliveryEligibility(**_metadata(other, chain.now))
        session.add(pending)
        with _read_only(session):
            assert work.alerts.is_delivery_allowed(event, market_date=chain.now.date())
        assert pending in session.new
        with session.no_autoflush:
            assert session.scalar(select(AlertDeliveryEligibility.event_id).where(
                AlertDeliveryEligibility.event_id == str(other.event_id))) is None


@pytest.mark.parametrize("method", ["is_delivery_allowed", "is_current_actionable"])
def test_unrelated_pending_source_is_not_flushed_by_outbox_reads(current, method):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        session = work.daily.session
        other = PlanSource(id=str(UUID(int=710923)), source_text="Unrelated source",
            source_hash=sha256(b"Unrelated source").hexdigest(), created_at=chain.now.isoformat())
        session.add(other)
        session.flush()
        other.source_text = "Pending unrelated edit"
        with _read_only(session):
            assert getattr(work.alerts, method)(event, market_date=chain.now.date())
        assert other in session.dirty and other.source_text == "Pending unrelated edit"
        with session.no_autoflush:
            assert session.scalar(select(PlanSource.source_text).where(
                PlanSource.id == other.id)) == "Unrelated source"


def test_outbox_keeps_exact_message_identity_and_native_window(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    with chain.plans._unit_of_work() as work:
        with _read_only(work.daily.session):
            assert work.alerts.is_delivery_allowed(event, market_date=chain.now.date())
        changed = _message_with_metadata(event, plan_id="other-plan")
        with _read_only(work.daily.session):
            assert not work.alerts.is_delivery_allowed(changed, market_date=chain.now.date())
    chain.now += timedelta(minutes=5)
    with chain.plans._unit_of_work() as work, _read_only(work.daily.session):
        assert not work.alerts.is_delivery_allowed(event, market_date=chain.now.date())


@pytest.mark.parametrize("options", [{}, {"expired": True}])
def test_outbox_keeps_independent_retained_risk_window(legacy, options):
    case = legacy(**options)
    event = _risk_event(case)
    with case.work() as work, _read_only(work.daily.session):
        assert work.alerts.is_delivery_allowed(event, market_date=event.trading_date)
        assert work.alerts.is_current_actionable(event, market_date=event.trading_date)


def test_default_dispatcher_keeps_the_sanitized_storage_error_for_invalid_source(current):
    chain, signal = current
    event = _event(chain, signal["signal_id"])
    _corrupt_source(chain)
    channel = LocalRecordingChannel()
    dispatcher = NotificationDispatcher(chain.plans._session_factory,
        channels=(channel,), clock=lambda: chain.now, enforce_current_plan=True)
    with pytest.raises(DeliveryStorageError):
        asyncio.run(dispatcher.dispatch_event(event.event_id))
    assert channel.sent == []
