"""Exact native notification history grants no present send authority."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.integration.current_pipeline_fixture import current_three_rule_plan
from tests.integration.test_current_condition_plan_authority import OwnedProgress
from tests.integration.test_market_exception_runtime import exception_chain as exception_chain
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_plan_readiness_risk_reads import (
    activate_successor,
    branch,
    cycle,
    recover_and_cycle,
)
from tests.integration.test_plan_readiness_risk_reads import (
    read as read_risk,
)
from tests.integration.test_plan_readiness_risk_reads import risk_case as risk_case
from tests.integration.test_plan_readiness_risk_reads import risk_read_case as risk_read_case
from tests.integration.test_plan_readiness_risk_reads import (
    risk_read_configuration as risk_read_configuration,
)
from tests.integration.test_runtime_status_projection import _current_status

from trade_plan_monitor.notifications.channels import DeliveryChannel, InAppChannel
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime import production
from trade_plan_monitor.state.models import AlertDeliveryEligibility, AlertEvent, DeliveryAttempt
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


@pytest.fixture
def notification_case(tmp_path, monkeypatch, request):
    native_pipeline = production.ProductionMonitorPipeline
    trackers = []

    def owned(**kwargs):
        progress = OwnedProgress(kwargs["runtime_generation"], kwargs["clock"])
        trackers.append(progress.tracker)
        return native_pipeline(**kwargs, progress_owner=progress)

    monkeypatch.setattr(production, "ProductionMonitorPipeline", owned)
    options = getattr(request, "param", {})
    plan = current_three_rule_plan(overlapping_risk=options.get("alert", False))
    case = _current_status(tmp_path, monkeypatch, plan=plan)
    case.tmp_path = tmp_path
    case.dispatcher = NotificationDispatcher(
        case.sessions, channels=(InAppChannel(),), clock=case.pipeline._clock.now
    )

    def owner():
        token, revision, plans = case.pipeline.runtime_status_snapshot()
        return replace(
            case.current[0],
            token=token,
            configuration_revision=revision,
            plans=plans,
            progress=trackers[0].snapshot(),
            notification_configuration=case.dispatcher.configuration_snapshot(),
        )

    case.owner = owner
    case.tracker = trackers[0]
    case.reader = RuntimeStatusReadService(
        case.sessions, case.owner, clock=case.pipeline._clock.now
    )
    try:
        yield case
    finally:
        case.close()


def read(case):
    return asyncio.run(
        case.reader.get_plan_readiness(version_id=case.result.snapshot["plan_version_id"])
    )


def notification(result, side="BUY"):
    return next(
        rule.facts.notification
        for rule in result.rules
        if rule.facts.owner_kind == "ORDINARY_RULE" and rule.facts.side == side
    )


def test_native_production_event_and_actual_in_app_receipt_remain_channel_specific(
    notification_case,
):
    case = notification_case
    before = notification(read(case))
    assert before is not None and before.event_id is not None
    assert before.cause_id == case.result.snapshot["signals"][0]["signal_id"]
    assert all(
        channel.latest_attempt is None and channel.eligible is None for channel in before.channels
    )
    attempts = asyncio.run(case.dispatcher.dispatch_event(before.event_id))
    assert len(attempts) == 1 and attempts[0].status == "DELIVERED"
    assessed = read(case)
    after = notification(assessed)
    channel = next(item for item in after.channels if item.channel is DeliveryChannel.IN_APP)
    assert channel.latest_attempt.id == attempts[0].id
    assert channel.latest_attempt.delivered_at == attempts[0].delivered_at
    assert channel.configured is True and channel.enabled is True and channel.eligible is None
    assert all(
        item.latest_attempt is None
        for item in after.channels
        if item.channel is not DeliveryChannel.IN_APP
    )
    assert (
        next(axis for axis in assessed.axes if axis.axis == "NOTIFICATION_DELIVERY").state
        == "UNKNOWN"
    )


def test_complete_false_exposes_configuration_without_inventing_an_event(notification_case):
    case = notification_case
    assessed = read(case)
    selected = next(
        rule
        for rule in assessed.rules
        if rule.facts.owner_kind == "ORDINARY_RULE" and rule.facts.side == "SELL"
    )
    assert selected.state == "CONDITION_FALSE"
    assert selected.facts.root_outcome == "UNSATISFIED"
    assert selected.facts.leaves and all(
        leaf.state in {"CONDITION_TRUE", "CONDITION_FALSE"} and leaf.evidence_refs
        for leaf in selected.facts.leaves
    )
    facts = selected.facts.notification
    assert facts is not None and facts.event_id is None
    actual = next(item for item in facts.channels if item.channel is DeliveryChannel.IN_APP)
    assert actual.configured is True and actual.enabled is True and actual.eligible is None
    assert all(
        item.latest_attempt is None and item.historical_status is None for item in facts.channels
    )


@pytest.mark.parametrize("notification_case", [{"alert": True}], indirect=True)
def test_actual_alert_event_has_its_saved_cause_and_confirmation_target(notification_case):
    case = notification_case
    assessed = read(case)
    facts = next(
        rule.facts.notification for rule in assessed.rules if rule.facts.owner_kind == "ALERT_RULE"
    )
    saved = case.result.snapshot["alerts"][0]
    assert saved["outcome"] == "SATISFIED"
    assert facts.event_id is not None and facts.cause_id == saved["cause_id"]
    assert facts.target.bucket_end.isoformat() == saved["confirmed_at"]
    with case.work() as work:
        original = work.alerts.get(facts.event_id)
    assert facts.created_at == original.created_at
    assert facts.observation.availability == "PERSISTED_ONLY"


@pytest.mark.parametrize(
    "field,value",
    [
        ("review_id", "another-review"),
        ("activation_revision", 2),
        ("quantity", 200),
        ("evidence", []),
        ("rule_id", "another-rule"),
        ("plan_version_id", "another-version"),
        ("execution_date", "2026-09-15"),
        ("next_step", "REVIEW_RISK_EXIT"),
        ("pretrade_mode", "NONE"),
        ("capital_mode", "MARKET_VALUE_CAP"),
        ("trading_date", "2026-09-15"),
    ],
)
def test_native_valid_same_key_event_with_wrong_complete_binding_is_unknown(
    notification_case,
    field,
    value,
):
    from trade_plan_monitor.notifications.daily_models import DailyAlertPayload, render_daily_alert
    from trade_plan_monitor.notifications.outbox import _event_from_row

    case = notification_case
    original = notification(read(case))
    with case.sessions.begin() as session:
        row = session.get(AlertEvent, str(original.event_id))
        raw = json.loads(row.payload_json)
        raw[field] = value
        payload = DailyAlertPayload.model_validate_json(json.dumps(raw))
        row.payload_json = payload.model_dump_json()
        row.message_text = render_daily_alert(payload)
        assert _event_from_row(row).event_id == original.event_id
    after = notification(read(case))
    assert after.event_id is None
    assert all(item.latest_attempt is None for item in after.channels)


def test_event_after_bound_production_eval_is_unknown_even_before_get_time(notification_case):
    from trade_plan_monitor.notifications.daily_models import DailyAlertPayload
    from trade_plan_monitor.notifications.outbox import _event_from_row

    case = notification_case
    before = notification(read(case))
    produced = case.pipeline._clock.now()
    later = produced + timedelta(seconds=1)
    case.pipeline._clock.current = later + timedelta(seconds=1)
    with case.sessions.begin() as session:
        row = session.get(AlertEvent, str(before.event_id))
        raw = json.loads(row.payload_json)
        raw["evaluated_at"] = later.isoformat()
        row.payload_json = DailyAlertPayload.model_validate_json(json.dumps(raw)).model_dump_json()
        row.created_at = later.isoformat()
        event = _event_from_row(row)
        assert produced < event.evaluated_at < case.pipeline._clock.now()
    assert notification(read(case)).event_id is None


def test_raw_same_key_event_keeps_original_created_at_and_no_current_eligibility(notification_case):
    case = notification_case
    before = notification(read(case))
    case.pipeline._clock.current += timedelta(seconds=1)
    case.dispatcher.begin_shutdown()
    after = notification(read(case))
    assert after.event_id == before.event_id and after.created_at == before.created_at
    assert all(item.eligible is None for item in after.channels)
    assert next(item for item in after.channels if item.channel is DeliveryChannel.IN_APP).enabled


@pytest.mark.parametrize("status", ["CLAIMED", "DELIVERED", "RETRY_PENDING", "FAILED"])
def test_only_exact_latest_attempt_is_projected_with_closed_safe_fields(notification_case, status):
    case = notification_case
    before = notification(read(case))
    first = asyncio.run(case.dispatcher.dispatch_event(before.event_id))[0]
    with case.sessions.begin() as session:
        session.add(
            DeliveryAttempt(
                id=str(uuid4()),
                event_id=str(before.event_id),
                channel="IN_APP",
                attempt=2,
                status=status,
                response_code=200
                if status == "DELIVERED"
                else 503
                if status in {"RETRY_PENDING", "FAILED"}
                else None,
                next_retry_at=(case.now + timedelta(seconds=30)).isoformat()
                if status == "RETRY_PENDING"
                else None,
                delivered_at=case.now.isoformat() if status == "DELIVERED" else None,
                error_code="CHANNEL_FAILURE" if status in {"RETRY_PENDING", "FAILED"} else None,
            )
        )
    after = notification(read(case))
    actual = next(
        item.latest_attempt for item in after.channels if item.channel is DeliveryChannel.IN_APP
    )
    assert actual.attempt == 2 and actual.status == status and actual.id != first.id
    assert set(actual.model_dump()) == {
        "id",
        "event_id",
        "channel",
        "attempt",
        "status",
        "response_code",
        "next_retry_at",
        "delivered_at",
        "error_code",
    }
    assert all(item.eligible is None for item in after.channels)


@pytest.mark.parametrize(
    "change",
    [
        "bad-payload",
        "missing-event",
        "missing-event-table",
        "missing-classification-table",
        "missing-attempt-table",
        "oversized-event",
        "bad-attempt-error",
    ],
)
def test_missing_or_invalid_storage_does_not_invent_delivery(notification_case, change):
    from sqlalchemy import text

    case = notification_case
    before = notification(read(case))
    if change == "bad-attempt-error":
        asyncio.run(case.dispatcher.dispatch_event(before.event_id))
    with case.sessions.begin() as session:
        if change == "missing-event":
            session.delete(session.get(AlertEvent, str(before.event_id)))
        elif change.endswith("table"):
            table = {
                "missing-event-table": "alert_event",
                "missing-classification-table": "alert_delivery_eligibility",
                "missing-attempt-table": "delivery_attempt",
            }[change]
            session.execute(text("DROP TABLE " + table))
        elif change == "bad-attempt-error":
            from sqlalchemy import select

            row = session.scalar(
                select(DeliveryAttempt).where(DeliveryAttempt.event_id == str(before.event_id))
            )
            row.error_code = "SECRET_TOKEN=private"
        else:
            row = session.get(AlertEvent, str(before.event_id))
            row.payload_json = "{" if change == "bad-payload" else "x" * (1024 * 1024 + 1)
    after = notification(read(case))
    assert all(item.latest_attempt is None for item in after.channels)
    if change in {"bad-payload", "missing-event", "missing-event-table", "oversized-event"}:
        assert after.event_id is None
    assert "SECRET_TOKEN" not in after.model_dump_json()


@pytest.fixture
def risk_notification_case(risk_read_case):
    case = risk_read_case
    case.dispatcher = NotificationDispatcher(
        case.sessions, channels=(InAppChannel(),), clock=case.pipeline._clock.now
    )
    actual_owner = case.owner
    case.owner = lambda: replace(
        actual_owner(), notification_configuration=case.dispatcher.configuration_snapshot()
    )
    case.reader = RuntimeStatusReadService(
        case.sessions, case.owner, clock=case.pipeline._clock.now
    )
    return case


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_risk_exit_belongs_only_to_selected_cause_and_uses_production_successor(
    risk_notification_case,
):
    case = risk_notification_case
    before = branch(read_risk(case), "severe-risk").facts.notification
    assert before.event_id is not None
    original = case.latest.snapshot["risk_action"]
    assert before.cause_id == original["cause_id"]
    assert branch(read_risk(case), "ordinary-risk").facts.notification.event_id is None
    activate_successor(case)
    assert case.latest.snapshot["risk_action"]["tactical_qty"] == 0
    assert branch(read_risk(case), "severe-risk").facts.notification.event_id is None
    next_risk_session(case)
    after = branch(read_risk(case), "severe-risk").facts.notification
    assert after.event_id is not None and after.event_id != before.event_id
    with case.work() as work:
        produced = work.alerts.get(after.event_id)
        cause = next(
            item
            for item in case.latest.snapshot["risks"]
            if item["risk_id"] == case.latest.snapshot["risk_action"]["cause_id"]
        )
        birth = work.daily.get(cause["origin_evaluation_id"])
    assert produced.plan_version_id == case.latest.snapshot["plan_version_id"]
    assert produced.plan_version_id != birth["payload"]["plan_version_id"]
    assert after.cause_id == case.latest.snapshot["risk_action"]["cause_id"]
    assert after.target is None  # A daily basis date alone is no condition-target proof.
    assert all(item.eligible is None for item in after.channels)


@pytest.mark.parametrize(
    "field,value", [("attempt", 1.5), ("response_code", 200.5), ("attempt", "not-a-number")]
)
def test_malformed_sqlite_numeric_receipt_is_local_unknown(notification_case, field, value):
    from sqlalchemy import text

    case = notification_case
    before = notification(read(case))
    asyncio.run(case.dispatcher.dispatch_event(before.event_id))
    with case.sessions.begin() as session:
        session.execute(
            text("UPDATE delivery_attempt SET " + field + "=:value WHERE event_id=:event"),
            {"value": value, "event": str(before.event_id)},
        )
    actual = notification(read(case))
    assert actual.event_id == before.event_id
    assert all(item.latest_attempt is None for item in actual.channels)


def test_stopped_configuration_has_explicit_historical_observation_and_no_eligibility(
    notification_case,
):
    case = notification_case
    original_owner = case.owner
    asyncio.run(case.dispatcher.aclose())
    case.tracker.stop()
    case.reader = RuntimeStatusReadService(
        case.sessions,
        lambda: replace(original_owner(), lifecycle="STOPPED"),
        clock=case.pipeline._clock.now,
    )
    facts = notification(read(case), "SELL")
    assert facts.event_id is None
    assert facts.observation.availability == "PERSISTED_ONLY"
    assert facts.observation.context.runtime_generation == original_owner().generation
    assert facts.observation.as_of is None and facts.observation.expires_at is None
    assert next(item for item in facts.channels if item.channel is DeliveryChannel.IN_APP).enabled
    assert all(item.eligible is None for item in facts.channels)
    case.reader = RuntimeStatusReadService(
        case.sessions, lambda: None, clock=case.pipeline._clock.now
    )
    assert notification(read(case), "SELL") is None


@pytest.mark.parametrize(
    "risk_case", [{"early_activation": True, "line": 6500, "ordinary_only": True}], indirect=True
)
def test_risk_born_pending_can_be_confirmed_and_notified_by_successor(risk_notification_case):
    case = risk_notification_case
    original = next(
        item for item in case.latest.snapshot["risks"] if item["rule_id"] == "ordinary-risk"
    )
    assert original["status"] == "PENDING"
    activate_successor(case)
    next_risk_session(case)
    facts = branch(read_risk(case), "ordinary-risk").facts.notification
    assert facts.event_id is not None
    with case.work() as work:
        event = work.alerts.get(facts.event_id)
        birth = work.daily.get(original["origin_evaluation_id"])
    assert event.plan_version_id != birth["payload"]["plan_version_id"]
    assert event.confirmed_trade_date != birth["payload"]["official_trade_date"]
    assert facts.target.trade_date == event.confirmed_trade_date


def next_risk_session(case):
    from tests.integration.test_daily_plan_chain import Chain, official_proof
    from tests.integration.test_plan_readiness_risk_reads import PausedReevaluation

    morning = case.pipeline._clock.now().replace(hour=10, minute=5, second=15) + timedelta(days=1)
    chain = Chain(case.tmp_path)
    chain.plan, chain.now, chain.runtime = case.plan, morning, PausedReevaluation()
    with chain.client:
        chain.post(
            "plan-facts",
            {
                "planVersionId": case.latest.snapshot["plan_version_id"],
                "contentHash": case.latest.snapshot["content_hash"],
                "factId": "next-session-notification-tradability",
                "kind": "TRADABILITY",
                "tradeDate": str(morning.date()),
                "expectedRevision": 0,
                "evidence": "Synthetic verified next-session tradability and liquidity fixture.",
                "officialEvidence": official_proof(chain),
            },
        )
    recover_and_cycle(case, morning)


def new_same_target_commit(case):
    from tests.integration.test_daily_plan_chain import Chain, official_proof
    from tests.integration.test_plan_readiness_risk_reads import PausedReevaluation

    previous = case.latest if hasattr(case, "latest") else case.result
    now = case.pipeline._clock.now() + timedelta(seconds=1)
    chain = Chain(case.tmp_path)
    chain.plan, chain.now, chain.runtime = case.plan, now, PausedReevaluation()
    with chain.client:
        chain.post(
            "plan-facts",
            {
                "planVersionId": previous.snapshot["plan_version_id"],
                "contentHash": previous.snapshot["content_hash"],
                "kind": "TRADABILITY",
                "factId": "notification-dedup-independent-witness",
                "tradeDate": str(now.date()),
                "expectedRevision": 0,
                "evidence": "Synthetic independent source revision witness.",
                "officialEvidence": official_proof(chain),
            },
        )
    if hasattr(case, "latest"):
        cycle(case, now)
        return case.latest
    case.pipeline._clock.current = now
    case.result = asyncio.run(case.pipeline.run_deadline(case.deadline))[0]
    return case.result


@pytest.mark.parametrize("notification_case", [{"alert": True}], indirect=True)
def test_new_owned_eval_reusing_ordinary_and_alert_keys_keeps_original_event_times(
    notification_case,
):
    case = notification_case
    before = read(case)
    events = {
        rule.facts.owner_id: rule.facts.notification
        for rule in before.rules
        if rule.facts.notification.event_id is not None
    }
    previous_time = case.result.snapshot["evaluated_at"]
    result = new_same_target_commit(case)
    assert not result.duplicate and result.snapshot["evaluated_at"] > previous_time
    assert not result.event_ids
    after = read(case)
    for rule in after.rules:
        old = events.get(rule.facts.owner_id)
        if old is not None:
            assert rule.facts.notification.event_id == old.event_id
            assert rule.facts.notification.created_at == old.created_at
            assert rule.facts.notification.observation.as_of == old.created_at


def test_native_exception_event_is_readable_but_missing_owned_completion_stays_unknown(
    exception_chain,
):
    from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget
    from trade_plan_monitor.state.daily_state_models import DailyEvaluationState
    from trade_plan_monitor.state.readiness_notification_reads import (
        NotificationReader,
        _common,
        _exception,
        read_owned_notifications,
    )

    chain = exception_chain
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    resource = result.snapshot["exception_candidates"][0]
    with chain.plans._unit_of_work() as work:
        details = work.plans.get_version_details(result.snapshot["plan_version_id"])
        value = SimpleNamespace(
            plan=chain.plan,
            details=details,
            proof=None,
            active=True,
            native=DailyEvaluationState.model_validate_json(json.dumps(result.snapshot)),
        )
        reader = NotificationReader(work, now=chain.now)
        expected, target = _exception(
            reader, value, resource["candidate"]["binding"]["rule_id"], result.snapshot
        )
        native = reader.event(
            {**_common(chain.plan, details, result.snapshot), **expected},
            target=target,
            produced_at=chain.now,
        )
        assert native.event is not None
        assert str(native.event.event_id) in result.event_ids
        assert native.event.cause_id == resource["candidate"]["candidate_id"]
        assert isinstance(native.target, OfficialCloseEvaluationTarget)
        assert read_owned_notifications(work, value=value, authority=None, now=chain.now) == (
            {},
            (),
        )


def test_two_ordinary_occurrences_cannot_choose_first_or_latest(notification_case):
    from copy import deepcopy

    from trade_plan_monitor.state.readiness_notification_reads import _ordinary
    from trade_plan_monitor.web.plan_readiness_service import _load

    case = notification_case
    with case.sessions() as session, session.begin():
        value = _load(session, case.owner(), case.result.snapshot["plan_version_id"], case.now)
        snapshot = deepcopy(case.result.snapshot)
        source = snapshot["signals"][0]
        other = {**source, "signal_id": "another-native-occurrence"}
        snapshot["signals"].append(other)
        assert _ordinary(value, source["rule_id"], source["side"], snapshot) is None


@pytest.mark.parametrize("code,status", [(503, "RETRY_PENDING"), (400, "FAILED")])
def test_mock_webhook_failure_never_borrows_in_app_success(notification_case, code, status):
    import httpx

    from trade_plan_monitor.notifications.channels import WebhookChannel, WebhookConfig

    case = notification_case
    initial = notification(read(case))

    async def dispatch():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(code, text="private-test-marker", request=request)
            )
        ) as client:
            case.dispatcher = NotificationDispatcher(
                case.sessions,
                clock=case.pipeline._clock.now,
                channels=(
                    InAppChannel(),
                    WebhookChannel(
                        client=client,
                        config=WebhookConfig(
                            enabled=True,
                            endpoint="https://hooks.example.test/private",
                            allowlisted_hosts=("hooks.example.test",),
                        ),
                    ),
                ),
            )
            await case.dispatcher.dispatch_event(initial.event_id)

    asyncio.run(dispatch())
    after = notification(read(case))
    channels = {item.channel: item for item in after.channels}
    assert channels[DeliveryChannel.IN_APP].latest_attempt.status == "DELIVERED"
    assert channels[DeliveryChannel.WEBHOOK].latest_attempt.status == status
    assert channels[DeliveryChannel.CONSOLE].latest_attempt is None
    assert all(item.eligible is None for item in channels.values())
    assert "private-test-marker" not in after.model_dump_json()
    assert "hooks.example.test" not in after.model_dump_json()


def test_actual_inflight_claim_is_not_reported_as_success(notification_case):
    import httpx

    from trade_plan_monitor.notifications.channels import WebhookChannel, WebhookConfig

    case = notification_case
    initial = notification(read(case))

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def respond(request):
            entered.set()
            await release.wait()
            return httpx.Response(201, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            case.dispatcher = NotificationDispatcher(
                case.sessions,
                clock=case.pipeline._clock.now,
                channels=(
                    InAppChannel(),
                    WebhookChannel(
                        client=client,
                        config=WebhookConfig(
                            enabled=True,
                            endpoint="https://hooks.example.test/private",
                            allowlisted_hosts=("hooks.example.test",),
                        ),
                    ),
                ),
            )
            task = asyncio.create_task(case.dispatcher.dispatch_event(initial.event_id))
            await asyncio.wait_for(entered.wait(), timeout=5)
            try:
                assessed = await case.reader.get_plan_readiness(
                    version_id=case.result.snapshot["plan_version_id"]
                )
                actual = next(
                    item
                    for item in notification(assessed).channels
                    if item.channel is DeliveryChannel.WEBHOOK
                )
                assert actual.latest_attempt.status == "CLAIMED"
                assert actual.latest_attempt.delivered_at is None and actual.eligible is None
            finally:
                release.set()
                await task

    asyncio.run(scenario())


def persist_classification(case, event_id, status="HOLD"):
    from trade_plan_monitor.notifications.delivery_eligibility import DeliveryEligibilityRecord

    barrier = None
    if status == "ELIGIBLE":
        target = case.pipeline._clock.now().replace(second=0)
        barrier = dict(
            symbol=case.plan.symbol,
            plan_hash=case.owner().plans[0].plan_hash,
            activation_revision=case.owner().plans[0].activation_revision,
            runtime_generation=str(case.owner().generation),
            target_bucket_end=target.isoformat(),
            reconciled_through=target.isoformat(),
            pending_obligations=0,
            observed_at=case.pipeline._clock.now().isoformat(),
        )
    record = DeliveryEligibilityRecord.model_validate_json(
        json.dumps(
            dict(
                event_id=str(event_id),
                schema_version=1,
                revision=0,
                delivery_class="STATE_RISK",
                source_cutoff=None,
                expires_at=None,
                status=status,
                reason={
                    "HOLD": "RECOVERY_REQUIRED",
                    "SUPPRESS": "RISK_RESOLVED",
                    "ELIGIBLE": "CURRENT_INSTRUCTION",
                }[status],
                updated_at=case.pipeline._clock.now().isoformat(),
                barrier=barrier,
                result_hash="a" * 64 if barrier is not None else None,
            )
        )
    )
    fields = record.model_dump(mode="json", exclude={"barrier"})
    fields["barrier_json"] = None if barrier is None else record.barrier.model_dump_json()
    with case.sessions.begin() as session:
        session.add(AlertDeliveryEligibility(**fields))


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
@pytest.mark.parametrize("status", ["HOLD", "SUPPRESS", "ELIGIBLE"])
def test_captured_native_classification_is_separate_from_current_channel_eligibility(
    risk_notification_case,
    status,
):
    case = risk_notification_case
    before = branch(read_risk(case), "severe-risk").facts.notification
    persist_classification(case, before.event_id, status)
    after = branch(read_risk(case), "severe-risk").facts.notification
    assert all(item.historical_status == status for item in after.channels)
    assert all(item.historical_updated_at == case.pipeline._clock.now() for item in after.channels)
    assert all(item.eligible is None and item.latest_attempt is None for item in after.channels)


@pytest.mark.parametrize("notification_case", [{"alert": True}], indirect=True)
@pytest.mark.parametrize("resource", ["payload", "barrier"])
def test_real_deep_json_failure_is_local_to_notification_and_keeps_other_owner(
    notification_case,
    resource,
):
    case = notification_case
    before = read(case)
    ordinary = notification(before)
    alert = next(
        rule.facts.notification for rule in before.rules if rule.facts.owner_kind == "ALERT_RULE"
    )
    persist_classification(case, ordinary.event_id)
    deep = "[" * 2000 + "0" + "]" * 2000
    assert len(deep.encode()) < 1024 * 1024
    with case.sessions.begin() as session:
        if resource == "payload":
            session.get(AlertEvent, str(ordinary.event_id)).payload_json = deep
        else:
            session.get(AlertDeliveryEligibility, str(ordinary.event_id)).barrier_json = deep
    after = read(case)
    retained = next(
        rule.facts.notification for rule in after.rules if rule.facts.owner_kind == "ALERT_RULE"
    )
    assert retained.event_id == alert.event_id
    actual = notification(after)
    assert (
        actual.event_id is None if resource == "payload" else actual.event_id == ordinary.event_id
    )
    assert all(item.historical_status is None for item in actual.channels)
    assert next(item for item in actual.channels if item.channel is DeliveryChannel.IN_APP).enabled


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_real_unknown_inventory_produces_known_null_risk_quantity_without_guessing(
    risk_notification_case,
):
    from trade_plan_monitor.state.daily_models import DailyRecord

    case = risk_notification_case
    with case.sessions.begin() as session:
        session.delete(session.get(DailyRecord, "simulation-position-" + case.plan.symbol))
    cycle(case, case.pipeline._clock.now() + timedelta(seconds=1))
    action = case.latest.snapshot["risk_action"]
    assert action["status"] == "RISK_EXIT"
    assert action["core_qty"] is None and action["tactical_qty"] is None
    facts = branch(read_risk(case), "severe-risk").facts.notification
    assert facts.event_id is not None and str(facts.event_id) in case.latest.event_ids
    with case.work() as work:
        event = work.alerts.get(facts.event_id)
    assert event.quantity is None and event.risk_scope == action
    assert all(item.eligible is None for item in facts.channels)
    repeated = new_same_target_commit(case)
    assert not repeated.duplicate and not repeated.event_ids
    retained = branch(read_risk(case), "severe-risk").facts.notification
    assert retained.event_id == facts.event_id and retained.created_at == facts.created_at


@pytest.mark.parametrize("notification_case", [{"alert": True}], indirect=True)
def test_other_actual_event_receipt_never_satisfies_ordinary_event(notification_case):
    case = notification_case
    before = read(case)
    alert = next(
        rule.facts.notification for rule in before.rules if rule.facts.owner_kind == "ALERT_RULE"
    )
    asyncio.run(case.dispatcher.dispatch_event(alert.event_id))
    after = read(case)
    assert all(item.latest_attempt is None for item in notification(after).channels)
    assert any(
        item.latest_attempt is not None
        for rule in after.rules
        if rule.facts.owner_kind == "ALERT_RULE"
        for item in rule.facts.notification.channels
    )


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
@pytest.mark.parametrize("change", ["cause-revision", "raw-scope"])
def test_risk_cause_revision_and_original_scope_cannot_be_substituted(
    risk_notification_case,
    change,
):
    from trade_plan_monitor.notifications.daily_models import (
        DailyAlertPayload,
        daily_alert_key,
        render_daily_alert,
    )
    from trade_plan_monitor.state.daily_models import DailyRecord

    case = risk_notification_case
    before = branch(read_risk(case), "severe-risk").facts.notification
    with case.sessions.begin() as session:
        if change == "cause-revision":
            session.get(DailyRecord, before.cause_id).revision += 1
        else:
            row = session.get(AlertEvent, str(before.event_id))
            payload = json.loads(row.payload_json)
            payload["risk_scope"]["blockers"].append("ANOTHER_ORIGINAL_SCOPE")
            payload["dedup_key"] = daily_alert_key(
                payload["cause_id"],
                payload["plan_hash"],
                payload["signal_type"],
                payload["simulated_qty"],
                payload["quantity"],
                payload["risk_scope"],
                payload["confirmed_trade_date"],
            )
            native = DailyAlertPayload.model_validate_json(json.dumps(payload))
            row.dedup_key, row.payload_json = native.dedup_key, native.model_dump_json()
            row.message_text = render_daily_alert(native)
    after = branch(read_risk(case), "severe-risk").facts.notification
    assert after.event_id is None
    assert all(item.latest_attempt is None and item.eligible is None for item in after.channels)


@pytest.fixture
def minute_severe_plan(risk_read_configuration, monkeypatch):
    from tests.integration import test_plan_risk_evaluation_output as fixture

    from trade_plan_monitor.domain.plan_codec import load_plan_json

    original = fixture.risk_plan

    def plan(options):
        raw = original(options).model_dump(mode="json")
        next(item for item in raw["risk_branches"] if item["kind"] == "SEVERE_TECHNICAL")[
            "condition"
        ] = {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 1000}
        return load_plan_json(json.dumps(raw))

    monkeypatch.setattr(fixture, "risk_plan", plan)


@pytest.mark.parametrize(
    "risk_case",
    [{"early_activation": True, "severe": "true", "minute_neighbors": True}],
    indirect=True,
)
def test_actual_minute_severe_risk_does_not_turn_daily_basis_into_official_target(
    minute_severe_plan,
    risk_notification_case,
):
    from tests.integration.test_plan_risk_evaluation_output import MONDAY_CLOSE

    case = risk_notification_case
    recover_and_cycle(case, MONDAY_CLOSE)
    actual = next(
        item
        for item in case.latest.snapshot["risk_evaluations"]
        if item["risk_identity"] == "severe-risk"
    )
    assert actual["target"]["kind"] == "INTRADAY"
    assert actual["evidence"]["outcome"] == "SATISFIED"
    next_risk_session(case)
    facts = branch(read_risk(case), "severe-risk").facts.notification
    assert facts.event_id is not None
    assert facts.target is None
    with case.work() as work:
        event = work.alerts.get(facts.event_id)
    assert event.confirmed_trade_date.isoformat() == actual["target"]["bucket_end"][:10]


@pytest.mark.parametrize("change", ["symbol", "family", "target"])
def test_notification_completion_must_keep_its_production_owner_and_target(
    notification_case,
    change,
):
    from trade_plan_monitor.decision.models import IntradayEvaluationTarget

    case = notification_case
    assert notification(read(case)).event_id is not None
    original_owner = case.owner

    def wrong_proof():
        owner = original_owner()
        selected = owner.plans[0]
        proof = selected.completion
        values = (
            {"symbol": "600001.SH"}
            if change == "symbol"
            else (
                {"plan_family": "EXPLICIT_RULE"}
                if change == "family"
                else {
                    "target": IntradayEvaluationTarget(
                        bucket_end=proof.target.bucket_end + timedelta(minutes=5)
                    )
                }
            )
        )
        return replace(owner, plans=(replace(selected, completion=replace(proof, **values)),))

    case.reader = RuntimeStatusReadService(
        case.sessions, wrong_proof, clock=case.pipeline._clock.now
    )
    facts = notification(read(case))
    assert facts.event_id is None
    assert all(item.latest_attempt is None for item in facts.channels)


@pytest.mark.parametrize(
    "payload",
    ["x" * (1024 * 1024 + 1), "[" * 2000 + "0" + "]" * 2000],
    ids=["oversized", "deep-json"],
)
def test_additional_daily_point_read_caps_payload_before_native_decode(notification_case, payload):
    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.state.readiness_notification_reads import NotificationReader

    case = notification_case
    identity = case.owner().plans[0].completion.input_stamp.immutable_record_id
    with case.sessions.begin() as session:
        session.get(DailyRecord, identity).payload_json = payload
    with case.work() as work:
        reader = NotificationReader(work, now=case.pipeline._clock.now())
        assert reader.daily(identity) is None
        assert len(reader.binding) == 1
        if len(payload) > 1024 * 1024:
            assert payload not in reader.binding[0][-1]
