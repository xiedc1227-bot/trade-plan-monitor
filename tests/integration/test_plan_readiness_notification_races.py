"""The existing two-snapshot fence includes every exact notification owner."""

import asyncio

import pytest
from tests.integration.test_plan_readiness_notification_reads import (
    notification,
    read,
)
from tests.integration.test_plan_readiness_notification_reads import (
    notification_case as notification_case,
)

from trade_plan_monitor.notifications.channels import InAppChannel
from trade_plan_monitor.notifications.delivery_eligibility import DeliveryEligibilityRecord
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import AlertDeliveryEligibility, AlertEvent, DeliveryAttempt


def hold(case, event_id):
    record = DeliveryEligibilityRecord.model_validate_json(
        '{"event_id":"' + str(event_id) + '","schema_version":1,"revision":0,'
        '"delivery_class":"INTRADAY_ACTIONABLE","source_cutoff":null,"expires_at":null,'
        '"status":"HOLD","reason":"SOURCE_CUTOFF_UNKNOWN","updated_at":"'
        + case.now.isoformat()
        + '","barrier":null,"result_hash":null}'
    )
    fields = record.model_dump(mode="json", exclude={"barrier"})
    fields["barrier_json"] = None
    with case.sessions.begin() as session:
        session.add(AlertDeliveryEligibility(**fields))


@pytest.mark.parametrize("change", ["event", "classification", "attempt", "configuration", "cause"])
@pytest.mark.parametrize("continuous", [False, True], ids=["stabilizes", "exhausts"])
def test_notification_changes_join_existing_bounded_retry_and_revoke_uncertain_context(
    notification_case,
    monkeypatch,
    change,
    continuous,
):
    from sqlalchemy import select

    from trade_plan_monitor.web import plan_readiness_service as projection

    case = notification_case
    initial = notification(read(case))
    asyncio.run(case.dispatcher.dispatch_event(initial.event_id))
    hold(case, initial.event_id)
    calls = []
    original = projection.read_readiness_binding

    def changing(*args):
        if not calls or continuous:
            if change == "configuration":
                if not calls:
                    case.dispatcher.begin_shutdown()
                else:
                    asyncio.run(case.dispatcher.aclose())
            else:
                with case.sessions.begin() as session:
                    if change == "event":
                        row = session.get(AlertEvent, str(initial.event_id))
                        row.acknowledged_at = case.now.isoformat() if not calls else None
                    elif change == "classification":
                        session.get(AlertDeliveryEligibility, str(initial.event_id)).revision += 1
                    elif change == "attempt":
                        row = session.scalar(
                            select(DeliveryAttempt).where(
                                DeliveryAttempt.event_id == str(initial.event_id)
                            )
                        )
                        row.response_code = 201 + len(calls)
                    else:
                        session.get(DailyRecord, initial.cause_id).revision += 1
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changing)
    assessed = read(case)
    assert len(calls) == 2
    if continuous:
        assert all(rule.facts.notification is None for rule in assessed.rules)
        assert all(
            axis.state == "UNKNOWN" and axis.reason == "CONTEXT_CHANGED" for axis in assessed.axes
        )
    else:
        facts = notification(assessed)
        assert facts.event_id == initial.event_id
        assert all(item.eligible is None for item in facts.channels)
        assert facts.observation.availability == "PERSISTED_ONLY"


def test_exact_indexed_point_reads_stay_constant_with_large_unrelated_history(
    notification_case,
    monkeypatch,
):
    from hashlib import sha256
    from uuid import uuid4

    from sqlalchemy import event, text

    from trade_plan_monitor.notifications.outbox import AlertOutbox
    from trade_plan_monitor.runtime import daily_service, market_exceptions
    from trade_plan_monitor.state.daily_repository import DailyRepository

    case = notification_case
    initial = notification(read(case))
    with case.sessions.begin() as session:
        # Deliberately malformed unrelated history must never be selected/decoded.
        session.add_all(
            AlertEvent(
                id=str(uuid4()),
                sequence=1000 + index,
                dedup_key=sha256(str(index).encode()).hexdigest(),
                payload_json="{",
                message_text="unrelated corrupt history",
                created_at=case.now.isoformat(),
                acknowledged_at=None,
            )
            for index in range(1000)
        )
    statements = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("notification observation attempted a send, policy, evaluator or history scan")

    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        assert sql.lstrip().split()[0].upper() not in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "ALTER",
            "DROP",
        }
        if any(
            "FROM " + table in sql
            for table in ("alert_event", "alert_delivery_eligibility", "delivery_attempt")
        ):
            statements.append(sql)

    monkeypatch.setattr(AlertOutbox, "list_events", forbidden)
    monkeypatch.setattr(AlertOutbox, "replay_after", forbidden)
    monkeypatch.setattr(DailyRepository, "list", forbidden)
    monkeypatch.setattr(daily_service, "daily_delivery_allowed", forbidden)
    monkeypatch.setattr(daily_service, "evaluate_unified_condition", forbidden)
    monkeypatch.setattr(market_exceptions, "current_exception_authority", forbidden)
    monkeypatch.setattr(InAppChannel, "deliver", forbidden)
    monkeypatch.setattr(case.pipeline, "run_deadline", forbidden)
    monkeypatch.setattr(case.sdk, "daily", forbidden, raising=False)
    monkeypatch.setattr(case.sdk, "adj_factor", forbidden, raising=False)
    event.listen(case.engine, "before_cursor_execute", capture)
    try:
        result = notification(read(case))
    finally:
        event.remove(case.engine, "before_cursor_execute", capture)
    assert result.event_id == initial.event_id
    assert len(statements) == 10  # 2 * (one event + one classification + three channels).
    assert all("WHERE" in sql and "LIMIT" in sql for sql in statements)
    assert all(
        "ORDER BY delivery_attempt.attempt DESC" in sql
        for sql in statements
        if "FROM delivery_attempt" in sql
    )
    with case.sessions() as session:
        for sql in (
            "SELECT id FROM alert_event WHERE dedup_key='x' LIMIT 1",
            "SELECT event_id FROM alert_delivery_eligibility WHERE event_id='x' LIMIT 1",
            "SELECT id FROM delivery_attempt WHERE event_id='x' AND channel='IN_APP' "
            "ORDER BY attempt DESC LIMIT 1",
        ):
            plan = session.execute(text("EXPLAIN QUERY PLAN " + sql)).all()
            assert all("SEARCH" in row[-1] and "INDEX" in row[-1] for row in plan)


@pytest.mark.parametrize("resource", ["event", "classification", "attempt"])
def test_missing_row_becoming_present_is_also_fenced(notification_case, monkeypatch, resource):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = notification_case
    initial = notification(read(case))
    saved = None
    if resource == "event":
        with case.sessions.begin() as session:
            row = session.get(AlertEvent, str(initial.event_id))
            saved = {column.key: getattr(row, column.key) for column in row.__table__.columns}
            session.delete(row)
    original, calls = projection.read_readiness_binding, []

    def becoming_present(*args):
        if not calls:
            if resource == "event":
                with case.sessions.begin() as session:
                    session.add(AlertEvent(**saved))
            elif resource == "classification":
                hold(case, initial.event_id)
            else:
                asyncio.run(case.dispatcher.dispatch_event(initial.event_id))
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", becoming_present)
    result = notification(read(case))
    assert len(calls) == 2 and result.event_id == initial.event_id
    assert all(item.eligible is None for item in result.channels)
