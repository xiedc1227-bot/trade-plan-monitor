"""Fulfillment reuses actual guarded native delivery, without a send permission."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from tests.integration import test_plan_readiness_notification_service as service_fixture
from tests.integration.test_plan_readiness_notification_service import (
    check,
    notification_axis,
    read,
)
from tests.integration.test_plan_readiness_notification_service import service_case as service_case

from trade_plan_monitor.notifications.channels import DeliveryChannel
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime import daily_service


@pytest.fixture
def alert_profile(monkeypatch, request):
    mode = getattr(request, "param", None)
    if mode not in {"true-false", "no-alerts"}:
        return
    original = service_fixture.current_three_rule_plan

    def plan(**kwargs):
        from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

        raw = original(**kwargs).model_dump(mode="json")
        if mode == "no-alerts":
            raw["alert_rules"] = []
        else:
            raw["alert_rules"].append(
                {
                    **raw["alert_rules"][0],
                    "rule_id": "false-reminder",
                    "condition": {
                        "type": "MINUTE_CLOSE_BELOW",
                        "timeframe_minutes": 5,
                        "price_fen": 950,
                    },
                }
            )
        return UnifiedTradePlan.model_validate(raw)

    monkeypatch.setattr(service_fixture, "current_three_rule_plan", plan)


@pytest.fixture
def fulfillment_case(alert_profile, service_case, monkeypatch, tmp_path):
    case = service_case
    guard = daily_service.daily_delivery_allowed
    case.send_guards = []
    case.tmp_path = tmp_path

    def actual_guard(session, event, now):
        allowed = guard(session, event, now)
        case.send_guards.append((event.event_id, allowed))
        return allowed

    monkeypatch.setattr(daily_service, "daily_delivery_allowed", actual_guard)
    case.dispatcher = NotificationDispatcher(
        case.sessions,
        channels=(case.channel,),
        clock=case.pipeline._clock.now,
        enforce_current_plan=True,
    )
    case.state._dispatcher = case.dispatcher
    return case


def in_app(rule):
    return next(
        item for item in rule.facts.notification.channels if item.channel is DeliveryChannel.IN_APP
    )


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
def test_actual_guarded_alert_delivery_fulfills_current_obligation(fulfillment_case):
    case = fulfillment_case
    check(case)
    result = read(case)
    assert case.send_guards and all(allowed is True for _event, allowed in case.send_guards)
    assert result.rules[0].state == "CONDITION_TRUE"
    assert in_app(result.rules[0]).latest_attempt.status == "DELIVERED"
    assert result.rules[0].facts.notification.observation.availability == "PERSISTED_ONLY"
    assert in_app(result.rules[0]).eligible is None
    assert notification_axis(result).state == "PASS"
    assert result.summary == "READY_FOR_MONITORING"


@pytest.mark.parametrize("service_case", [{"mixed": True, "all_false": True}], indirect=True)
def test_schema5_empty_signal_current_false_establishes_no_duty(fulfillment_case):
    case = fulfillment_case
    check(case)
    result = read(case)
    assert case.plan.schema_version == 5 and case.plan.ordinary_rules
    assert not case.plan.risk_branches
    assert all(rule.state == "CONDITION_FALSE" for rule in result.rules)
    assert not case.result.snapshot["signals"] and not case.result.snapshot["risks"]
    assert not case.result.snapshot.get("exception_candidates")
    assert notification_axis(result).state == "PASS"


@pytest.mark.parametrize("service_case", [{"true": True, "two_alerts": True}], indirect=True)
def test_two_true_alerts_require_each_exact_receipt(fulfillment_case, monkeypatch):
    case = fulfillment_case
    native = case.dispatcher.dispatch_pending

    async def one():
        return await native(limit=1)

    monkeypatch.setattr(case.dispatcher, "dispatch_pending", one)
    check(case)
    partial = read(case)
    assert all(rule.state == "CONDITION_TRUE" for rule in partial.rules)
    assert sum(in_app(rule).latest_attempt is not None for rule in partial.rules) == 1
    assert notification_axis(partial).state == "UNKNOWN"
    check(case)
    complete = read(case)
    assert all(in_app(rule).latest_attempt.status == "DELIVERED" for rule in complete.rules)
    assert all(in_app(rule).eligible is None for rule in complete.rules)
    assert notification_axis(complete).state == "PASS"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
@pytest.mark.parametrize("alert_profile", ["true-false"], indirect=True)
def test_current_true_and_false_alerts_have_distinct_obligations(fulfillment_case):
    case = fulfillment_case
    check(case)
    result = read(case)
    assert {rule.state for rule in result.rules} == {"CONDITION_TRUE", "CONDITION_FALSE"}
    true = next(rule for rule in result.rules if rule.state == "CONDITION_TRUE")
    false = next(rule for rule in result.rules if rule.state == "CONDITION_FALSE")
    assert in_app(true).latest_attempt.status == "DELIVERED"
    assert false.facts.notification.event_id is None and in_app(false).latest_attempt is None
    assert notification_axis(result).state == "PASS"


@pytest.mark.parametrize("service_case", [{"mixed": True, "all_false": True}], indirect=True)
@pytest.mark.parametrize("alert_profile", ["no-alerts"], indirect=True)
def test_schema5_false_ordinary_rules_do_not_require_optional_alerts(fulfillment_case):
    case = fulfillment_case
    check(case)
    result = read(case)
    assert case.plan.ordinary_rules and not case.plan.alert_rules
    assert all(rule.state == "CONDITION_FALSE" for rule in result.rules)
    assert notification_axis(result).state == "PASS"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
def test_new_owned_same_key_eval_retains_actual_event_and_receipt_times(fulfillment_case):
    from tests.integration.test_plan_readiness_notification_reads import new_same_target_commit

    case = fulfillment_case
    check(case)
    original = read(case).rules[0].facts.notification
    attempt = next(
        item.latest_attempt for item in original.channels if item.channel is DeliveryChannel.IN_APP
    )
    previous_eval = case.result.snapshot["evaluated_at"]
    produced = new_same_target_commit(case)
    assert not produced.duplicate and not produced.event_ids
    assert produced.snapshot["evaluated_at"] > previous_eval
    check(case)
    result = read(case)
    retained = result.rules[0].facts.notification
    assert retained.event_id == original.event_id and retained.created_at == original.created_at
    assert in_app(result.rules[0]).latest_attempt == attempt
    assert retained.observation.as_of == original.created_at
    assert retained.observation.availability == "PERSISTED_ONLY"
    assert in_app(result.rules[0]).eligible is None
    assert notification_axis(result).state == "PASS"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
def test_wrong_exact_read_target_does_not_fulfill_current_rule(fulfillment_case, monkeypatch):
    from trade_plan_monitor.decision.models import IntradayEvaluationTarget
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = fulfillment_case
    check(case)
    native = projection.read_owned_notifications

    def wrong_target(*args, **kwargs):
        facts, binding = native(*args, **kwargs)
        changed = {
            key: replace(
                value,
                target=IntradayEvaluationTarget(
                    bucket_end=value.target.bucket_end - timedelta(minutes=5)
                ),
            )
            if value.event is not None
            else value
            for key, value in facts.items()
        }
        return changed, binding

    monkeypatch.setattr(projection, "read_owned_notifications", wrong_target)
    result = read(case)
    assert in_app(result.rules[0]).latest_attempt.status == "DELIVERED"
    assert notification_axis(result).state == "UNKNOWN"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
@pytest.mark.parametrize(
    "field,value",
    [
        ("rule_id", "another-rule"),
        ("review_id", "another-review"),
        ("plan_version_id", "another-version"),
    ],
)
def test_native_valid_wrong_causal_owner_or_production_binding_is_unknown(
    fulfillment_case,
    field,
    value,
):
    from trade_plan_monitor.notifications.daily_models import DailyAlertPayload, render_daily_alert
    from trade_plan_monitor.notifications.outbox import _event_from_row
    from trade_plan_monitor.state.models import AlertEvent

    case = fulfillment_case
    check(case)
    before = read(case).rules[0].facts.notification
    with case.sessions.begin() as session:
        row = session.get(AlertEvent, str(before.event_id))
        raw = json.loads(row.payload_json)
        raw[field] = value
        payload = DailyAlertPayload.model_validate_json(json.dumps(raw))
        row.payload_json, row.message_text = payload.model_dump_json(), render_daily_alert(payload)
        assert _event_from_row(row).event_id == before.event_id
    result = read(case)
    assert result.rules[0].state == "CONDITION_TRUE"
    assert result.rules[0].facts.notification.event_id is None
    assert notification_axis(result).state == "UNKNOWN"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
def test_another_channel_receipt_cannot_fulfill_in_app(fulfillment_case):
    from sqlalchemy import select

    from trade_plan_monitor.state.models import DeliveryAttempt

    case = fulfillment_case
    check(case)
    with case.sessions.begin() as session:
        row = session.scalar(select(DeliveryAttempt))
        row.channel = "CONSOLE"
    result = read(case)
    assert in_app(result.rules[0]).latest_attempt is None
    assert (
        next(
            item.latest_attempt
            for item in result.rules[0].facts.notification.channels
            if item.channel is DeliveryChannel.CONSOLE
        ).status
        == "DELIVERED"
    )
    assert notification_axis(result).state == "UNKNOWN"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
@pytest.mark.parametrize("continuous", [False, True], ids=["missing-receipt", "exhausts"])
def test_exact_receipt_changes_use_existing_double_read(fulfillment_case, monkeypatch, continuous):
    from sqlalchemy import select

    from trade_plan_monitor.state.models import DeliveryAttempt
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = fulfillment_case
    check(case)
    with case.sessions() as session:
        row = session.scalar(select(DeliveryAttempt))
        saved = {column.key: getattr(row, column.key) for column in row.__table__.columns}
    native, calls = projection.read_readiness_binding, []

    def changed(*args):
        if not calls or continuous:
            with case.sessions.begin() as session:
                if not calls:
                    session.delete(session.get(DeliveryAttempt, saved["id"]))
                else:
                    session.add(DeliveryAttempt(**saved))
        calls.append(True)
        return native(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    result = read(case)
    assert len(calls) == 2 and notification_axis(result).state == "UNKNOWN"
    if continuous:
        assert notification_axis(result).reason == "CONTEXT_CHANGED"
        assert result.rules[0].facts.notification is None
    else:
        assert result.rules[0].state == "CONDITION_TRUE"
        assert in_app(result.rules[0]).latest_attempt is None


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
def test_fulfilled_get_performs_no_work_and_preserves_historical_observation(
    fulfillment_case,
    monkeypatch,
):
    from sqlalchemy import event

    from trade_plan_monitor.state.daily_repository import DailyRepository

    case = fulfillment_case
    check(case)
    original = read(case)
    guard_calls = tuple(case.send_guards)
    service = case.owner().notification_service

    def forbidden(*_args, **_kwargs):
        pytest.fail("fulfillment GET attempted work, sending policy, evaluator or history scan")

    def no_dml(_connection, _cursor, sql, _parameters, _context, _many):
        assert sql.lstrip().split()[0].upper() not in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "ALTER",
            "DROP",
        }

    monkeypatch.setattr(daily_service, "daily_delivery_allowed", forbidden)
    monkeypatch.setattr(daily_service, "evaluate_unified_condition", forbidden)
    monkeypatch.setattr(case.dispatcher, "dispatch_pending", forbidden)
    monkeypatch.setattr(case.dispatcher, "dispatch_event", forbidden)
    monkeypatch.setattr(DailyRepository, "list", forbidden)
    monkeypatch.setattr(case.sdk, "rt_min", forbidden)
    event.listen(case.engine, "before_cursor_execute", no_dml)
    try:
        for _ in range(2):
            observed = read(case)
            assert notification_axis(observed).state == "PASS"
            assert observed.rules[0].facts.notification == original.rules[0].facts.notification
            assert case.owner().notification_service == service
    finally:
        event.remove(case.engine, "before_cursor_execute", no_dml)
    assert tuple(case.send_guards) == guard_calls


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
@pytest.mark.parametrize("change", ["unbound-check", "closed", "expired"])
def test_historical_delivery_requires_current_service_gate(fulfillment_case, change):
    case = fulfillment_case
    check(case)
    original = read(case).rules[0].facts.notification
    if change == "unbound-check":
        asyncio.run(case.dispatcher.dispatch_pending())
    elif change == "closed":
        case.dispatcher.begin_shutdown()
    else:
        service = case.owner().notification_service
        case.pipeline._clock.current = service.valid_until + timedelta(seconds=1)
        token = case.progress.begin_step(timeout_seconds=30)
        case.progress.complete_step(
            token, next_wake_at=case.pipeline._clock.now() + timedelta(seconds=30)
        )
    result = read(case)
    assert in_app(result.rules[0]).latest_attempt.status == "DELIVERED"
    assert result.rules[0].facts.notification.created_at == original.created_at
    assert in_app(result.rules[0]).eligible is None
    assert notification_axis(result).state == "UNKNOWN"
