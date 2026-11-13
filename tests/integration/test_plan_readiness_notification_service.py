"""Current local service is actual owner/dispatcher work, never a synthetic send."""

import asyncio
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from tests.integration.current_pipeline_fixture import current_three_rule_plan
from tests.integration.test_current_condition_plan_authority import OwnedProgress
from tests.integration.test_runtime_status_projection import _current_status

from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.notifications.channels import InAppChannel
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime import production
from trade_plan_monitor.runtime.production import (
    ProductionSemanticBindings,
    SemanticContractBinding,
)
from trade_plan_monitor.runtime.provider_contract import import_stock_semantic_contract
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.web.monitor_composition import _ProductionRuntimeState
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


class ProgressOwner(OwnedProgress):
    def progress_snapshot(self):
        return self.tracker.snapshot()


@pytest.fixture
def service_case(tmp_path, monkeypatch, request):
    native = production.ProductionMonitorPipeline
    owners = []

    def build(**kwargs):
        owner = ProgressOwner(kwargs["runtime_generation"], kwargs["clock"])
        owners.append(owner)
        directory = kwargs["certification_directory"]
        sidecar = directory / "stock-semantic.json"
        semantic = import_stock_semantic_contract(
            directory / "tushare-stock-live.json",
            sidecar,
            now=kwargs["clock"].now(),
            endpoint_url=str(kwargs["configuration"].api_url),
            installed_sdk_version=lambda: "1.4.29",
        )
        assert semantic is not None
        kwargs["semantic_bindings"] = ProductionSemanticBindings(
            stock=SemanticContractBinding(sidecar, semantic.semantic_revision),
            index=None,
            installed_sdk_version=lambda: "1.4.29",
        )
        return native(**kwargs, progress_owner=owner)

    monkeypatch.setattr(production, "ProductionMonitorPipeline", build)
    options = getattr(request, "param", {})
    raw = current_three_rule_plan(overlapping_risk=options.get("true", False)).model_dump(
        mode="json"
    )
    if not options.get("mixed"):
        raw["ordinary_rules"] = []
    if options.get("conflict"):
        raw["ordinary_rules"][1]["condition"] = raw["ordinary_rules"][0]["condition"]
    if options.get("all_false"):
        raw["ordinary_rules"][0]["condition"] = raw["ordinary_rules"][1]["condition"]
    if options.get("two_alerts"):
        raw["alert_rules"].append({**raw["alert_rules"][0], "rule_id": "second-reminder"})
    case = _current_status(tmp_path, monkeypatch, plan=UnifiedTradePlan.model_validate(raw))
    case.channel = InAppChannel()
    case.dispatcher = NotificationDispatcher(
        case.sessions, channels=(case.channel,), clock=case.pipeline._clock.now
    )
    state = _ProductionRuntimeState(
        config_path=tmp_path / "unused.yaml",
        database_path=Path(case.engine.url.database),
        engine=case.engine,
        session_factory=case.sessions,
        clock=case.pipeline._clock,
        request_controller=case.controller,
        dispatcher=case.dispatcher,
        runtime_generation=lambda: case.pipeline._runtime_generation,
        progress_owner=lambda: owners[0],
        monitor_contract_version=2,
    )
    state._pipeline = case.pipeline
    case.state, case.progress = state, owners[0].tracker
    case.owner_adapter = owners[0]

    def authority():
        token, revision, plans = case.pipeline.runtime_status_snapshot()
        value = replace(
            case.current[0],
            token=token,
            configuration_revision=revision,
            plans=plans,
            progress=case.progress.snapshot(),
            notification_configuration=case.state.notification_configuration_snapshot(),
        )
        if hasattr(RuntimeReadAuthority, "notification_service"):
            value = replace(
                value,
                notification_service=case.state.notification_service_snapshot(
                    runtime_generation=value.generation,
                    configuration_revision=revision,
                    plans=plans,
                ),
            )
        return value

    case.owner = authority
    case.reader = RuntimeStatusReadService(case.sessions, authority, clock=case.pipeline._clock.now)
    try:
        yield case
    finally:
        case.close()


def read(case):
    return asyncio.run(
        case.reader.get_plan_readiness(version_id=case.result.snapshot["plan_version_id"])
    )


def notification_axis(result):
    return next(axis for axis in result.axes if axis.axis == "NOTIFICATION_DELIVERY")


def check(case):
    return asyncio.run(case.state.run_deadline(case.deadline))


def test_actual_complete_false_alert_only_check_can_finish_service_readiness(service_case):
    case = service_case
    assert notification_axis(read(case)).state == "UNKNOWN"
    check(case)
    result = read(case)
    assert all(rule.state == "CONDITION_FALSE" for rule in result.rules)
    assert notification_axis(result).state == "PASS"
    assert result.summary == "READY_FOR_MONITORING"
    assert all(
        channel.eligible is None
        for rule in result.rules
        for channel in rule.facts.notification.channels
    )


def test_native_getter_requires_real_storage_work(service_case):
    case = service_case
    assert case.dispatcher.in_app_service_check() is None
    check(case)
    actual = case.dispatcher.in_app_service_check()
    assert actual is not None and actual.started_at <= actual.completed_at


def test_getters_and_gets_do_not_refresh_work_or_access_storage(service_case, monkeypatch):
    from sqlalchemy import event

    from trade_plan_monitor.runtime import daily_service, market_exceptions
    from trade_plan_monitor.state.daily_repository import DailyRepository
    from trade_plan_monitor.web.plan_readiness_service import authority_identity

    case = service_case
    check(case)
    owner = case.owner()
    retained = owner.notification_service
    assert retained is not None

    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only service observation attempted I/O, send, acquisition or evaluation")

    with monkeypatch.context() as getters:
        getters.setattr(case.dispatcher, "_clock", forbidden)
        getters.setattr(case.dispatcher, "_session_factory", forbidden)
        getters.setattr(case.pipeline._clock, "now", forbidden)
        assert case.dispatcher.in_app_service_check() is retained.storage
        assert (
            case.state.notification_service_snapshot(
                runtime_generation=owner.generation,
                configuration_revision=owner.configuration_revision,
                plans=owner.plans,
            )
            is retained
        )

    def no_dml(_connection, _cursor, sql, _parameters, _context, _many):
        assert sql.lstrip().split()[0].upper() not in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "ALTER",
            "DROP",
        }

    monkeypatch.setattr(case.dispatcher, "dispatch_pending", forbidden)
    monkeypatch.setattr(case.dispatcher, "dispatch_event", forbidden)
    monkeypatch.setattr(InAppChannel, "deliver", forbidden)
    monkeypatch.setattr(case.pipeline, "run_deadline", forbidden)
    monkeypatch.setattr(daily_service, "daily_delivery_allowed", forbidden)
    monkeypatch.setattr(daily_service, "evaluate_unified_condition", forbidden)
    monkeypatch.setattr(market_exceptions, "current_exception_authority", forbidden)
    monkeypatch.setattr(DailyRepository, "list", forbidden)
    monkeypatch.setattr(case.sdk, "rt_min", forbidden)
    event.listen(case.engine, "before_cursor_execute", no_dml)
    try:
        for _ in range(3):
            assert notification_axis(read(case)).state == "PASS"
            assert case.owner().notification_service == retained
            assert authority_identity(case.owner()) == authority_identity(owner)
    finally:
        event.remove(case.engine, "before_cursor_execute", no_dml)
    with pytest.raises(FrozenInstanceError):
        retained.valid_until = retained.valid_until + timedelta(days=1)


def test_unrelated_progress_and_repeated_gets_cannot_extend_original_expiry(service_case):
    case = service_case
    check(case)
    retained = case.owner().notification_service
    case.pipeline._clock.current = retained.valid_until + timedelta(seconds=1)
    token = case.progress.begin_step(timeout_seconds=30)
    case.progress.complete_step(
        token, next_wake_at=case.pipeline._clock.now() + timedelta(seconds=30)
    )
    for _ in range(2):
        result = read(case)
        assert notification_axis(result).state == "UNKNOWN"
        assert case.owner().notification_service.valid_until == retained.valid_until
    assert case.dispatcher.in_app_service_check().completed_at == retained.storage.completed_at


@pytest.mark.parametrize(
    "change",
    [
        "closed",
        "disabled",
        "dispatcher",
        "same-enum",
        "pipeline",
        "owner",
        "generation",
        "configuration",
        "completion",
    ],
)
def test_actual_instance_and_context_changes_revoke_current_service(
    service_case, monkeypatch, change
):
    from trade_plan_monitor.notifications.channels import DeliveryChannel

    case = service_case
    check(case)
    original = case.owner()
    assert original.notification_service is not None
    if change == "closed":
        case.dispatcher.begin_shutdown()
    elif change == "disabled":
        case.channel.enabled = False
    elif change in {"dispatcher", "same-enum"}:

        class CustomInApp(InAppChannel):
            channel = DeliveryChannel.IN_APP

        adapter = CustomInApp() if change == "same-enum" else InAppChannel()
        case.state._dispatcher = NotificationDispatcher(
            case.sessions, channels=(adapter,), clock=case.pipeline._clock.now
        )
        if change == "same-enum":
            asyncio.run(case.state._dispatcher.dispatch_pending())
    elif change == "pipeline":
        case.state._pipeline = object()
    elif change == "owner":
        case.state._progress_owner = lambda: object()
    else:
        plans = original.plans
        generation, revision = original.generation, original.configuration_revision
        if change == "generation":
            generation = uuid4()
        elif change == "configuration":
            revision += "-changed"
        else:
            proof = replace(plans[0].completion, result_hash="f" * 64)
            plans = (replace(plans[0], completion=proof),)
        assert (
            case.state.notification_service_snapshot(
                runtime_generation=generation, configuration_revision=revision, plans=plans
            )
            is None
        )
    assert (
        case.state.notification_service_snapshot(
            runtime_generation=original.generation,
            configuration_revision=original.configuration_revision,
            plans=original.plans,
        )
        is None
    )
    if change == "disabled":
        case.channel.enabled = True
        assert case.dispatcher.in_app_service_check() is None


def test_new_check_revokes_old_before_storage_and_getter_failure_cannot_keep_pass(
    service_case,
    monkeypatch,
):
    case = service_case
    check(case)
    before = case.dispatcher.in_app_service_check()
    native = case.dispatcher._pending_events

    def real_storage(*args):
        assert case.dispatcher.in_app_service_check() is None
        return native(*args)

    monkeypatch.setattr(case.dispatcher, "_pending_events", real_storage)
    check(case)
    assert case.dispatcher.in_app_service_check().check is not before.check
    monkeypatch.setattr(case.dispatcher, "_pending_events", lambda *_args: ())
    check(case)
    assert case.dispatcher.in_app_service_check() is None
    assert notification_axis(read(case)).state == "UNKNOWN"


def test_real_storage_failure_revokes_previous_pass(service_case):
    from sqlalchemy import text

    from trade_plan_monitor.notifications.dispatcher import DeliveryStorageError

    case = service_case
    check(case)
    assert notification_axis(read(case)).state == "PASS"
    with case.sessions.begin() as session:
        session.execute(text("DROP TABLE alert_event"))
    with pytest.raises(DeliveryStorageError):
        check(case)
    assert case.dispatcher.in_app_service_check() is None
    assert case.owner().notification_service is None
    assert notification_axis(read(case)).state == "UNKNOWN"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
def test_actual_delivered_alert_fulfills_duty_without_current_eligibility(
    service_case,
):
    case = service_case
    check(case)
    assert case.owner().notification_service is not None
    result = read(case)
    assert notification_axis(result).state == "PASS"
    assert any(
        channel.latest_attempt is not None and channel.latest_attempt.status == "DELIVERED"
        for rule in result.rules
        for channel in rule.facts.notification.channels
    )
    assert all(
        channel.eligible is None
        for rule in result.rules
        for channel in rule.facts.notification.channels
    )


@pytest.mark.parametrize("service_case", [{"mixed": True}], indirect=True)
def test_mixed_false_and_ordinary_obligations_remain_unknown(service_case):
    case = service_case
    check(case)
    assert case.owner().notification_service is not None
    assert case.result.snapshot["signals"]
    assert notification_axis(read(case)).state == "UNKNOWN"


@pytest.mark.parametrize("service_case", [{"mixed": True, "conflict": True}], indirect=True)
def test_real_bidirectional_conflict_zero_snapshot_keeps_ready_original_signal(service_case):
    case = service_case
    assert len(case.result.snapshot["signals"]) == 2
    assert all(row["executable_qty"] == 0 for row in case.result.snapshot["signals"])
    with case.work() as work:
        originals = [work.daily.get(row["signal_id"]) for row in case.result.snapshot["signals"]]
    assert all(row["payload"]["state"] == "READY" for row in originals)
    assert all(row["payload"]["executable_qty"] > 0 for row in originals)
    check(case)
    assert case.owner().notification_service is not None
    assert notification_axis(read(case)).state == "UNKNOWN"


def test_missing_owner_context_and_startup_checks_never_certify_evaluation(service_case):
    case = service_case
    check(case)
    assert notification_axis(read(case)).state == "PASS"
    asyncio.run(case.state.recover_startup(case.pipeline._clock.now().date()))
    assert case.dispatcher.in_app_service_check() is not None
    assert case.owner().notification_service is None
    assert notification_axis(read(case)).state == "UNKNOWN"
    case.state._progress_owner = None
    check(case)
    assert case.dispatcher.in_app_service_check() is not None
    assert case.owner().notification_service is None
    case.reader = RuntimeStatusReadService(
        case.sessions, lambda: None, clock=case.pipeline._clock.now
    )
    assert notification_axis(read(case)).state == "UNKNOWN"


def test_cancelled_new_deadline_revokes_previous_pass(service_case, monkeypatch):
    case = service_case
    check(case)
    assert notification_axis(read(case)).state == "PASS"
    native = case.pipeline.run_deadline

    async def scenario():
        entered = asyncio.Event()

        async def pending(deadline):
            entered.set()
            await asyncio.Event().wait()
            return await native(deadline)

        monkeypatch.setattr(case.pipeline, "run_deadline", pending)
        task = asyncio.create_task(case.state.run_deadline(case.deadline))
        await entered.wait()
        assert case.owner().notification_service is None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert case.owner().notification_service is None

    asyncio.run(scenario())
    assert notification_axis(read(case)).state == "UNKNOWN"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
def test_cancelled_real_native_delivery_does_not_complete_storage_check(service_case, monkeypatch):
    case = service_case
    native = InAppChannel.deliver

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(adapter, event):
            entered.set()
            await release.wait()
            return await native(adapter, event)

        monkeypatch.setattr(InAppChannel, "deliver", delayed)
        task = asyncio.create_task(case.state.run_deadline(case.deadline))
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert case.dispatcher.in_app_service_check() is None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert case.dispatcher.in_app_service_check() is None
        assert case.owner().notification_service is None
        # The old shielded receipt is still physically outstanding. A new bounded
        # scan can skip its non-due CLAIMED row, but cannot certify completion.
        await case.dispatcher.dispatch_pending()
        assert case.dispatcher.in_app_service_check() is None
        release.set()
        await case.dispatcher.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("service_case", [{"true": True, "two_alerts": True}], indirect=True)
def test_native_scan_limit_and_cursor_do_not_certify_queue_coverage(service_case):
    from uuid import UUID

    from trade_plan_monitor.notifications.channels import DeliveryChannel

    case = service_case
    assert len(case.result.event_ids) == 2
    asyncio.run(case.dispatcher.dispatch_pending(limit=1))
    limited = case.dispatcher.in_app_service_check()
    assert limited.limit == limited.selected_count == limited.considered_count == 1
    with case.work() as work:
        events = [work.alerts.get(UUID(identity)) for identity in case.result.event_ids]
    case.dispatcher = NotificationDispatcher(
        case.sessions,
        channels=(InAppChannel(),),
        clock=case.pipeline._clock.now,
        admission=lambda _event, _now: False,
    )
    case.state._dispatcher = case.dispatcher
    cursor = max(event.sequence for event in events)
    case.dispatcher._scan_after[DeliveryChannel.IN_APP] = cursor
    check(case)
    checked = case.dispatcher.in_app_service_check()
    assert checked.cursor_start == cursor and checked.cursor_end == 0
    assert checked.selected_count == checked.considered_count == 0
    assert case.owner().notification_service is not None
    assert notification_axis(read(case)).state == "UNKNOWN"
    with case.work() as work:
        assert all(work.alerts.get(event.event_id) is not None for event in events)


def test_pending_getter_error_revokes_bound_proof(service_case, monkeypatch):
    case = service_case
    check(case)

    def broken():
        raise RuntimeError("private-test-marker")

    monkeypatch.setattr(case.dispatcher, "in_app_service_check", broken)
    assert case.owner().notification_service is None
    assert notification_axis(read(case)).state == "UNKNOWN"


@pytest.mark.parametrize("service_case", [{"mixed": True, "all_false": True}], indirect=True)
def test_actual_schema5_mixed_all_false_establishes_no_duty(service_case):
    case = service_case
    check(case)
    result = read(case)
    assert case.owner().notification_service is not None
    assert not case.result.snapshot["signals"]
    assert all(rule.state == "CONDITION_FALSE" for rule in result.rules)
    assert all(
        axis.state in {"PASS", "NOT_APPLICABLE"}
        for axis in result.axes
        if axis.axis != "NOTIFICATION_DELIVERY"
    )
    assert notification_axis(result).state == "PASS"


@pytest.mark.parametrize("seconds,state", [(-1, "PASS"), (0, "UNKNOWN")])
def test_original_service_deadline_is_exclusive(service_case, seconds, state):
    case = service_case
    check(case)
    original = case.owner().notification_service
    case.pipeline._clock.current = original.valid_until + timedelta(seconds=seconds)
    result = read(case)
    assert notification_axis(result).state == state
    assert case.owner().notification_service == original


@pytest.mark.parametrize("continuous", [False, True], ids=["stabilizes", "exhausts"])
def test_actual_new_service_check_participates_in_existing_double_read(
    service_case,
    monkeypatch,
    continuous,
):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = service_case
    check(case)
    previous = case.owner()
    check(case)
    current = case.owner()
    assert projection.authority_identity(replace(previous, notification_service=None)) == (
        projection.authority_identity(replace(current, notification_service=None))
    )
    assert projection.authority_identity(previous) != projection.authority_identity(current)
    native, calls = projection.read_readiness_binding, []

    def changed(*args):
        if not calls or continuous:
            check(case)
        calls.append(True)
        return native(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    result = read(case)
    assert len(calls) == 2
    if continuous:
        assert notification_axis(result).state == "UNKNOWN"
        assert all(
            axis.state == "UNKNOWN" and axis.reason == "CONTEXT_CHANGED"
            for axis in result.axes
            if axis.axis != "INVENTORY_CAPITAL"
        )
        assert next(axis for axis in result.axes if axis.axis == "INVENTORY_CAPITAL").state == (
            "NOT_APPLICABLE"
        )
        assert all(rule.facts.notification is None for rule in result.rules)
    else:
        assert notification_axis(result).state == "PASS"


@pytest.mark.parametrize("service_case", [{"true": True}], indirect=True)
def test_mid_check_dispatcher_replacement_cannot_bind_another_instances_work(
    service_case, monkeypatch
):
    case = service_case
    native = InAppChannel.deliver
    original = case.dispatcher

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(adapter, event):
            entered.set()
            await release.wait()
            return await native(adapter, event)

        monkeypatch.setattr(InAppChannel, "deliver", delayed)
        running = asyncio.create_task(case.state.run_deadline(case.deadline))
        await asyncio.wait_for(entered.wait(), timeout=5)
        replacement = NotificationDispatcher(
            case.sessions, channels=(InAppChannel(),), clock=case.pipeline._clock.now
        )
        case.state._dispatcher = replacement
        try:
            # The second instance performs a real direct scan while the first owns
            # the non-due CLAIMED row. That scan has no production-deadline binding.
            await replacement.dispatch_pending()
            assert replacement.in_app_service_check() is not None
        finally:
            release.set()
            await running
        assert case.owner().notification_service is None
        await original.aclose()
        await replacement.aclose()

    asyncio.run(scenario())
