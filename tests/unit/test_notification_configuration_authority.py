"""Actual dispatcher facts cross the owner fence without I/O or send authority."""

import asyncio
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.notifications.channels import DeliveryChannel, InAppChannel
from trade_plan_monitor.notifications.dispatcher import (
    NotificationChannelConfiguration,
    NotificationConfigurationSnapshot,
    NotificationDispatcher,
)
from trade_plan_monitor.runtime.progress import ProgressSnapshot
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.web.monitor_composition import (
    _ProductionRuntimeState,
    create_monitor_composition,
)
from trade_plan_monitor.web.plan_readiness_service import authority_identity


def forbidden(*_args, **_kwargs):
    pytest.fail("configuration observation must not open storage, sample time, admit or deliver")


def dispatcher(channels=None):
    return NotificationDispatcher(
        forbidden, channels=channels, clock=forbidden, id_factory=forbidden, admission=forbidden
    )


def test_getter_observes_actual_final_channels_without_inventing_production_defaults():
    default = dispatcher().configuration_snapshot()
    production = dispatcher((InAppChannel(),)).configuration_snapshot()
    assert tuple(item.channel for item in default.channels) == (
        DeliveryChannel.IN_APP,
        DeliveryChannel.CONSOLE,
    )
    assert tuple(item.channel for item in production.channels) == (DeliveryChannel.IN_APP,)
    assert all(item.enabled is True and item.closed is False for item in production.channels)
    assert production.admission_stopped is False


def test_snapshot_is_frozen_and_shutdown_does_not_rewrite_enablement():
    instance = dispatcher((InAppChannel(),))
    before = instance.configuration_snapshot()
    instance.begin_shutdown()
    after = instance.configuration_snapshot()
    assert after.admission_stopped is True
    assert after.channels == before.channels
    with pytest.raises(FrozenInstanceError):
        after.admission_stopped = False
    with pytest.raises(FrozenInstanceError):
        after.channels[0].enabled = False


class MutableChannel:
    """An adapter with secrets that must never enter the configuration view."""

    def __init__(self, channel=DeliveryChannel.WEBHOOK, *, enabled=False):
        self.channel = channel
        self.enabled = enabled
        self.endpoint = "https://example.invalid/private"
        self.token = "private-test-token"
        self.close_calls = 0
        self.fail_close = False

    async def deliver(self, *_args, **_kwargs):
        forbidden()

    async def aclose(self):
        self.close_calls += 1
        if self.fail_close:
            raise RuntimeError("private-test-token")


def test_final_channels_include_inserted_in_app_and_disabled_actual_adapters_only():
    webhook = MutableChannel()
    console = MutableChannel(DeliveryChannel.CONSOLE, enabled=True)
    instance = dispatcher((webhook, console))
    snapshot = instance.configuration_snapshot()
    assert asdict(snapshot) == {
        "channels": (
            {"channel": DeliveryChannel.IN_APP, "enabled": True, "closed": False},
            {"channel": DeliveryChannel.CONSOLE, "enabled": True, "closed": False},
            {"channel": DeliveryChannel.WEBHOOK, "enabled": False, "closed": False},
        ),
        "admission_stopped": False,
    }
    assert webhook.endpoint not in repr(snapshot)
    assert webhook.token not in repr(snapshot)
    assert webhook.close_calls == console.close_calls == 0
    webhook.enabled = True
    assert instance.configuration_snapshot().channels[-1].enabled is True
    assert snapshot.channels[-1].enabled is False


@pytest.mark.parametrize("value", [0, 1, "true", None])
@pytest.mark.parametrize("field", ["enabled", "closed", "admission_stopped"])
def test_snapshot_flags_require_strict_booleans(field, value):
    facts = NotificationChannelConfiguration(DeliveryChannel.IN_APP, True, False)
    with pytest.raises(TypeError, match="strict boolean"):
        if field == "admission_stopped":
            NotificationConfigurationSnapshot((facts,), value)
        else:
            replace(facts, **{field: value})


@pytest.mark.parametrize("channel", ["IN_APP", None, 0])
def test_snapshot_channels_require_native_enum(channel):
    with pytest.raises(TypeError, match="native channel enum"):
        NotificationChannelConfiguration(channel, True, False)


@pytest.mark.parametrize("channels", [[], [object()], (object(),)])
def test_snapshot_requires_native_frozen_tuple(channels):
    with pytest.raises(TypeError, match="frozen tuple"):
        NotificationConfigurationSnapshot(channels, False)


@pytest.mark.parametrize("count", [2, 4])
def test_snapshot_rejects_duplicate_or_overlong_channel_facts(count):
    facts = NotificationChannelConfiguration(DeliveryChannel.IN_APP, True, False)
    with pytest.raises(ValueError, match="unique and bounded"):
        NotificationConfigurationSnapshot((facts,) * count, False)


@pytest.mark.parametrize("value", [0, "true", None])
def test_getter_rejects_adapter_enablement_that_ceased_to_be_boolean(value):
    adapter = MutableChannel()
    instance = dispatcher((adapter,))
    adapter.enabled = value
    with pytest.raises(TypeError, match="strict boolean"):
        instance.configuration_snapshot()


def test_closed_records_completed_cleanup_and_failed_close_stays_unclosed():
    adapter = MutableChannel(enabled=True)
    instance = dispatcher((adapter,))
    adapter.fail_close = True

    async def scenario():
        with pytest.raises(RuntimeError):
            await instance.aclose()
        failed = instance.configuration_snapshot()
        assert failed.admission_stopped is True
        assert failed.channels[0].closed is True
        assert failed.channels[-1].closed is False
        assert all(item.enabled is True for item in failed.channels)
        assert adapter.close_calls == 1
        adapter.fail_close = False
        await instance.aclose()
        closed = instance.configuration_snapshot()
        assert closed.admission_stopped is True
        assert all(item.closed is True and item.enabled is True for item in closed.channels)
        assert adapter.close_calls == 2
        await instance.aclose()
        assert adapter.close_calls == 2
        assert instance.configuration_snapshot() == closed

    asyncio.run(scenario())


def production_state(tmp_path, instance):
    return _ProductionRuntimeState(
        config_path=tmp_path / "unused.yaml",
        database_path=tmp_path / "unused.sqlite3",
        engine=None,
        session_factory=forbidden,
        clock=SimpleNamespace(now=forbidden),
        request_controller=None,
        dispatcher=instance,
    )


def test_production_proxy_reads_same_dispatcher_without_cache_or_side_effects(tmp_path):
    adapter = MutableChannel()
    instance = dispatcher((adapter,))
    state = production_state(tmp_path, instance)
    before = state.notification_configuration_snapshot()
    assert before == instance.configuration_snapshot()
    adapter.enabled = True
    after = state.notification_configuration_snapshot()
    assert after == instance.configuration_snapshot()
    assert after != before
    instance.begin_shutdown()
    assert state.notification_configuration_snapshot().admission_stopped is True
    assert not (tmp_path / "unused.sqlite3").exists()
    assert adapter.close_calls == 0


def failing_getter():
    raise RuntimeError("private-test-token")


@pytest.mark.parametrize(
    "instance",
    [
        None,
        object(),
        SimpleNamespace(configuration_snapshot=failing_getter),
        SimpleNamespace(configuration_snapshot=lambda: object()),
    ],
    ids=["missing-dispatcher", "missing-getter", "getter-error", "invalid-result"],
)
def test_production_proxy_leaves_unavailable_configuration_unknown(tmp_path, instance):
    assert production_state(tmp_path, instance).notification_configuration_snapshot() is None


def read_authority():
    now = datetime(2026, 11, 13, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    progress = ProgressSnapshot(uuid4(), now, "STARTING", None, None, None)
    return RuntimeReadAuthority(object(), "STARTING", progress, object())


def test_authority_field_is_trailing_optional_and_rejects_non_native_configuration():
    authority = read_authority()
    assert authority.notification_configuration is None
    with pytest.raises(TypeError, match="native frozen"):
        replace(authority, notification_configuration={"channels": ()})
    absent = RuntimeReadAuthority(object(), "STOPPED", None, object(), owner_absent=True)
    with pytest.raises(ValueError, match="absent owner"):
        replace(absent, notification_configuration=dispatcher().configuration_snapshot())


@pytest.mark.parametrize("change", ["configured", "enabled", "shutdown", "closed", "unavailable"])
def test_each_configuration_change_invalidates_read_identity(change):
    instance = dispatcher((MutableChannel(enabled=True),))
    snapshot = instance.configuration_snapshot()
    authority = replace(read_authority(), notification_configuration=snapshot)
    if change == "configured":
        changed = replace(snapshot, channels=snapshot.channels[:1])
    elif change == "enabled":
        changed = replace(
            snapshot, channels=(snapshot.channels[0], replace(snapshot.channels[1], enabled=False))
        )
    elif change == "shutdown":
        changed = replace(snapshot, admission_stopped=True)
    elif change == "closed":
        changed = replace(
            snapshot, channels=(snapshot.channels[0], replace(snapshot.channels[1], closed=True))
        )
    else:
        changed = None
    assert authority_identity(authority) != authority_identity(
        replace(authority, notification_configuration=changed)
    )
    assert authority_identity(authority) == authority_identity(replace(authority))


def test_real_composition_binds_actual_generation_and_retains_stopped_configuration(
    tmp_path,
    monkeypatch,
):
    from tushare.pro.client import DataApi

    monkeypatch.setattr(DataApi, "query", forbidden)
    monkeypatch.setattr(InAppChannel, "deliver", forbidden)
    config = tmp_path / "app.yaml"
    config.write_text("tushare: {}\n", encoding="utf-8")
    composition = create_monitor_composition(
        config_path=config, database_path=tmp_path / "isolated.sqlite3", monitor_contract_version=2
    )
    provider = composition.read_service._authority
    with pytest.raises(RuntimeError, match="unavailable before startup"):
        provider()
    with monkeypatch.context() as absent:
        absent.setattr(composition, "_runtime", None)
        with pytest.raises(RuntimeError, match="progress authority is unavailable"):
            provider()

    async def scenario():
        await composition.start()
        try:
            owner = composition._runtime
            actual = owner._dispatcher
            with monkeypatch.context() as guarded:
                guarded.setattr(NotificationDispatcher, "__init__", forbidden)
                authority = provider()
                assert authority.generation == owner.runtime_generation
                assert authority.notification_configuration == actual.configuration_snapshot()
                assert tuple(
                    item.channel for item in authority.notification_configuration.channels
                ) == (DeliveryChannel.IN_APP,)
                snapshot = owner.progress_snapshot()
                with monkeypatch.context() as mismatched:
                    mismatched.setattr(
                        owner,
                        "progress_snapshot",
                        lambda: replace(snapshot, runtime_generation=uuid4()),
                    )
                    assert provider().notification_configuration is None
                with monkeypatch.context() as unavailable:
                    unavailable.setattr(actual, "configuration_snapshot", failing_getter)
                    assert provider().notification_configuration is None
                actual.begin_shutdown()
                stopping = provider().notification_configuration
                assert stopping.admission_stopped is True
                assert stopping.channels[0].enabled is True
                assert stopping.channels[0].closed is False
        finally:
            await composition.stop()
        stopped = provider()
        assert stopped.lifecycle == "STOPPED"
        assert stopped.generation == authority.generation
        assert stopped.notification_configuration == actual.configuration_snapshot()
        assert stopped.notification_configuration.admission_stopped is True
        assert stopped.notification_configuration.channels[0].enabled is True
        assert stopped.notification_configuration.channels[0].closed is True

    asyncio.run(scenario())
