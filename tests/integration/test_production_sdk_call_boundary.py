"""Real owner/controller/certification boundaries with temporary SQLite and fake SDKs."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from threading import Event, current_thread, main_thread
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from test_permission_candidate_selection import ANCHOR, _block, _seed_open_day
from test_production_certification_gate import _composition
from test_production_index_daily_permission_maintenance import _one_official_index_day

from trade_plan_monitor.live_profiles import load_stock_certification
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.runtime.production import (
    PermissionMaintenanceResult,
    _CertifiedTushareClient,
)
from trade_plan_monitor.runtime.request_control import (
    RequestControlError,
    RequestControlErrorCode,
    RequestNotStartedError,
    TushareOperation,
)
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.runtime_recovery import ProviderRecoveryRepository

SCOPES = {
    TushareOperation.DAILY_BARS: ("daily", "_maybe_recheck_daily_bars_permission"),
    TushareOperation.DAILY_LIMITS: ("stk_limit", "_maybe_recheck_daily_limits_permission"),
    TushareOperation.INDEX_DAILY: ("index_daily", "_maybe_recheck_index_daily_permission"),
    TushareOperation.INDEX_REALTIME_MINUTES: (
        "rt_idx_min_daily", "_maybe_recheck_realtime_index_permission",
    ),
}


@asynccontextmanager
async def boundary_case(tmp_path, monkeypatch, scope):
    composition, sdk, _ = _composition(
        tmp_path, monkeypatch, active_plan=True, include_index=True, persisted_calendar=True,
    )
    try:
        await composition.start()
        runtime = composition._runtime
        pipeline = runtime._probe_capabilities.__self__._pipeline
        control = runtime._request_controller
        _seed_open_day(tmp_path / "monitor.sqlite3", ANCHOR)
        await _block(control, scope)
        runtime._clock.current += timedelta(seconds=301)
        pipeline._permission_market_window = lambda _now, _horizon: ()
        sdk._index_daily = lambda kwargs: _one_official_index_day(
            MarketIndexCode(str(kwargs["ts_code"])),
        )
        is_index = scope in {TushareOperation.INDEX_DAILY, TushareOperation.INDEX_REALTIME_MINUTES}
        provider = pipeline.index_provider if is_index else pipeline.provider
        yield SimpleNamespace(
            pipeline=pipeline, control=control, clock=runtime._clock, sdk=sdk, provider=provider,
            database=tmp_path / "monitor.sqlite3", captured=runtime._clock.now(),
            invoke=getattr(pipeline, SCOPES[scope][1]), original_client=provider._client,
        )
    finally:
        await composition.stop()


def persisted_rows(env):
    engine = create_sqlite_engine(env.database)
    try:
        repo = ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity=env.control._recovery_repository._provider_identity,
        )
        return repo.load()
    finally:
        engine.dispose()


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("change", ["legal", "expired", "epoch", "market", "stop", "configuration"])
def test_real_wrapper_final_gate_and_durable_reservation(tmp_path, monkeypatch, scope, change):
    async def scenario():
        async with boundary_case(tmp_path, monkeypatch, scope) as env:
            calls_before = len(env.sdk.calls)
            captured = env.captured
            reservations = []
            original_callback = env.pipeline._permission_probe_reservation_callback
            def callback(candidate):
                advance = original_callback(candidate)
                def reserved():
                    reservations.append(candidate)
                    advance()
                return reserved
            monkeypatch.setattr(env.pipeline, "_permission_probe_reservation_callback", callback)
            if change == "market":
                env.pipeline._permission_market_window = lambda _now, _horizon: (
                    (captured + timedelta(seconds=32), True),
                )
            def current():
                valid = env.original_client._current()
                env.clock.current += timedelta(seconds=16 if change == "expired" else 2)
                if change == "epoch":
                    with env.pipeline._calendar_epoch_lock:
                        env.pipeline._calendar_epoch += 1
                        env.pipeline._calendar_revoked.set()
                if change == "stop":
                    monkeypatch.setattr(env.pipeline, "_admission_revoked", lambda: True)
                if change == "configuration":
                    monkeypatch.setattr(env.pipeline, "_configuration_current", lambda: False)
                return valid
            env.provider._client = _CertifiedTushareClient(env.original_client._client, current)
            def sql_on_owner(conn, cursor, sql, parameters, context, many):
                assert current_thread() is main_thread(), "SDK workers must not query SQLite"
                assert sql.lstrip().upper().startswith(("SELECT", "BEGIN")) or (
                    "provider_recovery_checkpoint" in sql
                ), "permission recheck must not write business state"
            event.listen(Engine, "before_cursor_execute", sql_on_owner)
            try:
                result = await env.invoke()
            finally:
                event.remove(Engine, "before_cursor_execute", sql_on_owner)
            if change == "legal":
                assert result is PermissionMaintenanceResult.PROBED
                assert [name for name, _ in env.sdk.calls[calls_before:]] == [SCOPES[scope][0]]
                assert not env.control.is_permission_blocked(scope)
            else:
                assert result is PermissionMaintenanceResult.DEFERRED
                assert env.sdk.calls[calls_before:] == []
                assert env.control.is_permission_blocked(scope)
                row = next(row for row in persisted_rows(env)
                           if row.kind == "permission" and row.scope_key == scope.value)
                assert row.retry_at >= captured + timedelta(seconds=300)
                assert not any(row.kind in {"backoff", "cooldown"} for row in persisted_rows(env))
            if scope is not TushareOperation.INDEX_REALTIME_MINUTES:
                assert env.pipeline._permission_rotation_state.last_operation is scope
                assert len(reservations) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["certification", "guard", "sdk"])
def test_sentinel_identity_and_no_supplier_accounting(tmp_path, monkeypatch, stage):
    async def scenario():
        async with boundary_case(tmp_path, monkeypatch, TushareOperation.DAILY_BARS) as env:
            sentinel = RequestNotStartedError("trusted final-boundary sentinel")
            def current():
                if stage == "certification":
                    raise sentinel
                return True
            def endpoint(**kwargs):
                assert stage == "sdk"
                raise sentinel
            def guard():
                if stage == "guard":
                    raise sentinel
            env.provider._client = _CertifiedTushareClient(SimpleNamespace(daily=endpoint), current)
            reserved = []
            with pytest.raises(RequestNotStartedError) as caught:
                await env.control.recheck_permission(
                    TushareOperation.DAILY_BARS,
                    lambda: env.provider.probe_daily_bars_permission(
                        "003043.SZ", ANCHOR, _physical_start=guard,
                    ),
                    work_key="boundary:sentinel", on_reserved=lambda: reserved.append(True),
                )
            assert caught.value is sentinel
            assert reserved == [True]
            rows = persisted_rows(env)
            assert all(row.kind == "permission" for row in rows)
            assert next(row.retry_at for row in rows if row.scope_key == "daily_bars") >= (
                env.captured + timedelta(seconds=300)
            )
    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["cancel", "timeout"])
@pytest.mark.parametrize("stage", ["certification", "sdk"])
def test_wrapper_preparation_drains_with_no_extra_late_sentinel_accounting(
    tmp_path, monkeypatch, outcome, stage,
):
    async def scenario():
        async with boundary_case(tmp_path, monkeypatch, TushareOperation.DAILY_BARS) as env:
            entered, release = Event(), Event()
            def wait_for_release():
                entered.set()
                assert release.wait(3)
            def current():
                valid = env.original_client._current()
                if stage == "certification":
                    wait_for_release()
                return valid
            class DelayedSDK:
                def __getattr__(self, operation):
                    call = getattr(env.original_client._client, operation)
                    def endpoint(**kwargs):
                        if stage == "sdk":
                            wait_for_release()
                        return call(**kwargs)
                    return endpoint
            env.provider._client = _CertifiedTushareClient(DelayedSDK(), current)
            before = len(env.sdk.calls)
            if outcome == "timeout":
                monkeypatch.setattr(env.control, "_timeout_seconds", 0.05)
            attempt = asyncio.create_task(env.invoke())
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                inner = env.control._permission_rechecks[TushareOperation.DAILY_BARS]
                if outcome == "cancel":
                    attempt.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await attempt
                else:
                    assert await attempt is PermissionMaintenanceResult.FAILED
                assert not env.pipeline._permission_maintenance_lock.locked()
                rows_before_release = persisted_rows(env)
                backoffs = [row for row in rows_before_release if row.kind == "backoff"]
                assert len(backoffs) == int(outcome == "timeout")
                following = asyncio.create_task(env.control.execute(
                    TushareOperation.CURRENT_DAY_MINUTES,
                    lambda: None, work_key="boundary:after-drain",
                ))
                await asyncio.sleep(0)
                assert not following.done(), "physical slot stays occupied until work drains"
                release.set()
                if outcome == "cancel":
                    if stage == "certification":
                        with pytest.raises(RequestNotStartedError):
                            await inner
                    else:
                        with pytest.raises(RequestControlError) as caught:
                            await inner
                        assert caught.value.code is RequestControlErrorCode.INVALID_RESPONSE
                await following
                assert len(env.sdk.calls) - before == int(stage == "sdk")
                assert env.control.is_permission_blocked(TushareOperation.DAILY_BARS)
                assert persisted_rows(env) == rows_before_release
            finally:
                release.set()
    asyncio.run(scenario())


@pytest.mark.parametrize("offset", [0, 1])
def test_realtime_index_final_s_rechecks_expiry_after_authority_io(tmp_path, monkeypatch, offset):
    async def scenario():
        scope = TushareOperation.INDEX_REALTIME_MINUTES
        async with boundary_case(tmp_path, monkeypatch, scope) as env:
            semantics = env.pipeline._index_semantics
            expires = env.captured + timedelta(seconds=1)
            env.pipeline._index_semantics = semantics.model_copy(update={
                "provenance": semantics.provenance.model_copy(update={"valid_until": expires}),
            })
            phase = []
            original_current = env.pipeline._index_certification_current
            def slow_authority():
                valid = original_current()
                if phase:
                    env.clock.current = expires + timedelta(seconds=offset)
                return valid
            monkeypatch.setattr(env.pipeline, "_index_certification_current", slow_authority)
            def prepare():
                valid = original_current()
                phase.append("resolved")
                return valid
            env.provider._client = _CertifiedTushareClient(env.original_client._client, prepare)
            calls_before = len(env.sdk.calls)
            assert await env.invoke() is PermissionMaintenanceResult.DEFERRED
            assert env.sdk.calls[calls_before:] == []
            assert env.control.is_permission_blocked(TushareOperation.INDEX_REALTIME_MINUTES)
    asyncio.run(scenario())


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("fence", ["generation", "admission"])
def test_final_authority_io_rechecks_memory_fences_before_sdk(tmp_path, monkeypatch, scope, fence):
    async def scenario():
        async with boundary_case(tmp_path, monkeypatch, scope) as env:
            resolved, revoked, revocations = [], [], []
            is_index = scope in {
                TushareOperation.INDEX_DAILY, TushareOperation.INDEX_REALTIME_MINUTES,
            }
            method = "_index_certification_current" if is_index else "_stock_certification_current"
            original_current = getattr(env.pipeline, method)
            if fence == "generation":
                monkeypatch.setattr(env.pipeline, "_generation_current", lambda: not revoked)
            else:
                monkeypatch.setattr(env.pipeline, "_admission_revoked", lambda: bool(revoked))
            def final_authority_io():
                valid = original_current()
                if resolved and not revoked:
                    revoked.append(True)
                    revocations.append("final authority IO after wrapper preparation")
                return valid
            monkeypatch.setattr(env.pipeline, method, final_authority_io)
            def prepare():
                valid = original_current()
                assert not revoked
                resolved.append(True)
                return valid
            env.provider._client = _CertifiedTushareClient(env.original_client._client, prepare)
            before = len(env.sdk.calls)
            result = await env.invoke()
            assert revocations == ["final authority IO after wrapper preparation"]
            assert len(env.sdk.calls) - before == 0
            assert result is PermissionMaintenanceResult.DEFERRED
            assert env.control.is_permission_blocked(scope)
            rows = persisted_rows(env)
            assert not any(row.kind in {"backoff", "cooldown"} for row in rows)
            assert next(row.retry_at for row in rows if row.scope_key == scope.value) >= (
                env.captured + timedelta(seconds=300)
            )
    asyncio.run(scenario())


@pytest.mark.parametrize("scope", [TushareOperation.DAILY_BARS, TushareOperation.DAILY_LIMITS])
@pytest.mark.parametrize("semantic,offset", [(False, 0), (False, 1), (True, 1), (False, -604801)])
def test_stock_final_time_preserves_legacy_and_semantic_rules(
    tmp_path, monkeypatch, scope, semantic, offset,
):
    async def scenario():
        async with boundary_case(tmp_path, monkeypatch, scope) as env:
            expires = env.captured + timedelta(seconds=1)
            evidence = load_stock_certification(
                tmp_path / "data/live-certification/tushare-stock-live.json",
                now=env.captured, endpoint_url=env.pipeline._endpoint,
            )
            assert evidence is not None
            env.pipeline._stock_evidence = evidence.model_copy(update={
                "observed_at": expires - timedelta(days=7), "valid_until": expires,
            })
            if not semantic:
                env.pipeline._semantic_bindings = None
                env.pipeline._stock_semantics = None
            prepared = []
            def certification_read():
                valid = semantic or env.clock.now() <= expires
                if prepared:
                    env.clock.current = expires + timedelta(seconds=offset)
                return valid
            monkeypatch.setattr(env.pipeline, "_stock_certification_current", certification_read)
            def prepare():
                valid = certification_read()
                prepared.append(True)
                return valid
            env.provider._client = _CertifiedTushareClient(env.original_client._client, prepare)
            calls_before = len(env.sdk.calls)
            expected = (PermissionMaintenanceResult.PROBED if semantic or offset == 0
                        else PermissionMaintenanceResult.DEFERRED)
            assert await env.invoke() is expected
            assert len(env.sdk.calls) - calls_before == int(
                expected is PermissionMaintenanceResult.PROBED
            )
    asyncio.run(scenario())
