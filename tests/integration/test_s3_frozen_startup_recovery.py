"""F2 frozen startup acquisition, invocation isolation and transaction fences."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
from datetime import timedelta
from decimal import Decimal
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import httpx
import pytest
import requests
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from test_live_pipeline_acceptance import (
    NOW,
    ControlledClock,
    OfflineSDK,
    VirtualPace,
    _activate_plans,
    _sample_plan,
    _write_configuration_and_evidence,
)
from test_production_semantic_gate import _pipeline
from test_recovery_activation_fences import replace_or_reactivate
from test_runtime_recovery_coverage import (
    SIBLING,
    SYMBOL,
    minute,
    setup_service,
    stamp,
)
from test_runtime_recovery_coverage import history as history
from test_s3_startup_outcome_association import _DeadlineClock

from trade_plan_monitor.domain.plan_models import TradingDayActivation
from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.runtime.recovery import RecoveryAdmissionChangedError
from trade_plan_monitor.runtime.recovery_targets import derive_recovery_target
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import RuntimeLiveness
from trade_plan_monitor.state.repositories import MarketHistoryRepository
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


@asynccontextmanager
async def _running(root, monkeypatch, mode):
    """Self-contained real startup fixture; imports only committed offline helpers."""
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as composition_module

    assert mode == "empty"
    database = root / "monitor.sqlite3"
    seed_clock = ControlledClock(NOW.replace(hour=9, minute=0, second=0))
    plan = _sample_plan().model_copy(update={
        "activation": TradingDayActivation(trading_day=NOW.date()),
    })
    _activate_plans(database, seed_clock, (plan,))
    engine = create_sqlite_engine(database)
    sessions = create_session_factory(engine)
    try:
        with sessions.begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0, last_alive_at=seed_clock.now().isoformat(),
            ))
    finally:
        engine.dispose()
    configuration = _write_configuration_and_evidence(root, observed_at=NOW, include_index=False)
    clock = _DeadlineClock(NOW)

    class EmptySDK(OfflineSDK):
        def _stock_minutes(self, name, kwargs):
            return super()._stock_minutes(name, kwargs).iloc[:0].copy()

    sdk = EmptySDK(clock, (plan.symbol,))
    make_controller = composition_module.create_live_tushare_request_controller

    def controller_factory(*, clock, require_repository_binding=False):
        pace = VirtualPace()
        return make_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
            require_repository_binding=require_repository_binding,
        )

    def forbid_network(*_args, **_kwargs):
        pytest.fail("offline F2 composition must not access the network")

    monkeypatch.setattr(requests.Session, "request", forbid_network)
    monkeypatch.setattr(httpx.Client, "send", forbid_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid_network)
    monkeypatch.setattr(composition_module, "SystemClock", lambda: clock)
    monkeypatch.setattr(composition_module, "create_live_tushare_request_controller",
                        controller_factory)
    monkeypatch.setattr(production, "create_tushare_client", lambda _configuration: sdk)
    composition = composition_module.create_monitor_composition(
        config_path=configuration, database_path=database,
    )

    def state():
        with composition._runtime._liveness_owner.unit_of_work_factory() as work:
            rows = work.history.list_minutes(
                plan.symbol, start=NOW.replace(hour=9, minute=31, second=0),
                end=NOW.replace(hour=15, minute=0, second=0),
            )
        return {"minutes": tuple(row.bar_end.isoformat() for row in rows)}

    try:
        async with asyncio.timeout(20):
            health = await composition.start()
            assert health.status.value == "RUNNING"
            await clock.park()
            yield SimpleNamespace(composition=composition, state=state)
    finally:
        await asyncio.wait_for(composition.stop(), timeout=10)


def test_scoped_persistence_is_invocation_local(history):
    async def scenario():
        clock, provider, controller, service = setup_service(
            history, {SYMBOL: [minute("09:31:00")]},
            persist=lambda _: pytest.fail("shared persistence callback was selected"),
        )
        calls = []

        def selected(rows):
            calls.append(rows)
            history.persist(rows)

        try:
            result = await service.recover_scope(
                symbol=SYMBOL,
                target=derive_recovery_target(now=clock.now(), is_open_on=lambda _: True),
                required_ends=(stamp("09:31:00"),), read_persisted_ends=history.read,
                now=clock.now, persist_selected=selected,
            )
            assert result.ready and calls == [(minute("09:31:00"),)]
            assert provider.calls == [SYMBOL]
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def test_concurrent_scoped_fetch_and_persist_callbacks_are_not_shared(history):
    async def scenario():
        clock, provider, controller, service = setup_service(history, {})
        calls = []

        async def one(symbol):
            row = minute("09:31:00", symbol)

            def fetch():
                calls.append(("fetch", symbol))
                return [row]

            def persist(rows):
                assert rows == (row,)
                calls.append(("persist", symbol))
                history.persist(rows)

            return await service.recover_scope(
                symbol=symbol,
                target=derive_recovery_target(now=clock.now(), is_open_on=lambda _: True),
                required_ends=(stamp("09:31:00"),), read_persisted_ends=history.read,
                now=clock.now, persist_selected=persist, fetch_current_day=fetch,
                admission_current=lambda: True,
            )

        try:
            results = await asyncio.gather(one(SYMBOL), one(SIBLING))
            assert all(result.ready for result in results)
            assert calls == [("fetch", SYMBOL), ("persist", SYMBOL),
                             ("fetch", SIBLING), ("persist", SIBLING)]
            assert provider.calls == []
        finally:
            await controller.aclose()

    asyncio.run(scenario())


def _bar(capture, end=None, *, price=6405, received_at=NOW):
    return MinuteBar(
        symbol=capture.symbol, bar_end=end or capture.required_ends[-1],
        open_fen=price, high_fen=price, low_fen=price, close_fen=price,
        volume_shares=1000, amount_yuan=Decimal("64000"), received_at=received_at,
    )


def test_production_capture_is_immutable_and_has_exact_identity(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            assert capture is not None
            assert capture.target.observed_at == NOW
            assert capture.target.completed_minute_end == NOW.replace(second=0)
            assert len(capture.required_ends) == 30
            assert capture.required_ends[0] == NOW.replace(hour=9, minute=31, second=0)
            with work() as transaction:
                active = transaction.plans.get_active(capture.symbol)
                version = transaction.plans.get_version(_sample_plan().plan_id, 1)
            assert capture.plan_version_id == active.plan_version_id == version.id
            assert capture.activation_revision == active.revision == 1
            assert capture.plan_hash == version.plan_hash
            assert capture.payload_json == version.payload_json
            with pytest.raises(FrozenInstanceError):
                capture.required_ends = ()
            pipeline._clock.current += timedelta(minutes=1)
            assert capture.target.completed_minute_end == NOW.replace(second=0)

    asyncio.run(scenario())


def test_fresh_missing_difference_preserves_concurrent_minute_and_quote(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            winner = _bar(capture, price=6500)
            with work() as transaction:
                transaction.history.upsert_minutes((winner,))
                transaction.commit()
                quote = transaction.history.get_latest_quote(capture.symbol)
            incoming = _bar(capture, price=6600, received_at=NOW + timedelta(seconds=1))
            first = _bar(capture, capture.required_ends[0])
            pipeline._persist_recovery_capture(capture, (first, incoming), cancelled=Event())
            with work() as transaction:
                rows = transaction.history.list_minutes(
                    capture.symbol, start=capture.required_ends[0], end=capture.required_ends[-1],
                )
                assert rows == (first, winner)
                assert transaction.history.get_latest_quote(capture.symbol) == quote

    asyncio.run(scenario())


def test_reactivation_rejects_old_capture_without_writing(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            replacement = replace_or_reactivate(work, pipeline, _sample_plan())
            with pytest.raises(RecoveryAdmissionChangedError):
                pipeline._persist_recovery_capture(capture, (_bar(capture),), cancelled=Event())
            with work() as transaction:
                assert transaction.plans.get_active(capture.symbol).revision == replacement.revision
                assert transaction.history.get_latest_quote(capture.symbol) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", (
    "rollover", "reversal", "revoked", "epoch", "generation", "source", "semantics",
    "cancellation", "calendar",
))
def test_final_transaction_rejects_each_changed_capture(tmp_path, monkeypatch, mutation):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            cancelled = Event()
            if mutation == "rollover":
                pipeline._clock.current = NOW + timedelta(days=1)
            elif mutation == "reversal":
                pipeline._clock.current = NOW - timedelta(microseconds=1)
            elif mutation == "revoked":
                pipeline._recovery_authority_revoked.set()
            elif mutation == "epoch":
                pipeline._recovery_authority_epoch = lambda: capture.authority_epoch + 1
            elif mutation == "generation":
                pipeline._generation_current = lambda: False
            elif mutation == "source":
                pipeline.provider._client._client = object()
            elif mutation == "semantics":
                pipeline._stock_semantics = None
            elif mutation == "cancellation":
                cancelled.set()
            else:
                from trade_plan_monitor.market_data.models import TradingDay

                with work() as transaction:
                    transaction.references.upsert_trading_days((
                        TradingDay(exchange="SSE", cal_date=NOW.date(), is_open=False,
                                   previous_trade_date=NOW.date() - timedelta(days=1)),
                    ))
                    transaction.commit()
            with pytest.raises(RecoveryAdmissionChangedError):
                pipeline._persist_recovery_capture(capture, (_bar(capture),), cancelled=cancelled)
            with work() as transaction:
                assert transaction.history.get_latest_quote(capture.symbol) is None

    asyncio.run(scenario())


def test_real_two_connection_reactivation_makes_read_snapshot_unwritable(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            original = pipeline._recovery_covered_ends
            attempts = []
            replacement = []

            def rotate_after_a_read(transaction, observed_capture):
                ends = original(transaction, observed_capture)
                assert observed_capture is capture
                session = transaction._require_session()
                assert session.connection().connection.driver_connection.in_transaction
                a_connection = session.connection().connection.driver_connection
                with work() as b:
                    b_connection = b._require_session().connection().connection.driver_connection
                    assert b_connection is not a_connection
                replacement.append(replace_or_reactivate(work, pipeline, _sample_plan()))
                attempts.append(ends)
                return ends

            monkeypatch.setattr(pipeline, "_recovery_covered_ends", rotate_after_a_read)
            with pytest.raises(OperationalError) as caught:
                pipeline._persist_recovery_capture(capture, (_bar(capture),), cancelled=Event())
            assert caught.value.orig.sqlite_errorname == "SQLITE_BUSY_SNAPSHOT"
            assert len(attempts) == 1  # No reconnect/retry with the old capture.
            with work() as transaction:
                active = transaction.plans.get_active(capture.symbol)
                assert active.revision == replacement[0].revision
                assert transaction.history.get_latest_quote(capture.symbol) is None
                assert transaction.history.list_minutes(
                    capture.symbol, start=capture.required_ends[0], end=capture.required_ends[-1],
                ) == ()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ("staging", "external-validation"))
def test_revocation_before_final_lock_rolls_back_all_staged_facts(tmp_path, monkeypatch, phase):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            stage = MarketHistoryRepository.upsert_minutes
            validate = pipeline._decision_commit_current
            entered = []

            def revoke():
                assert not pipeline._recovery_authority_lock._is_owned()
                with pipeline._recovery_authority_lock:
                    pipeline._recovery_authority_revoked.set()
                entered.append("revoked")

            def staged(repository, rows):
                stage(repository, rows)
                assert not repository._session.new and not repository._session.dirty
                if phase == "staging":
                    thread = Thread(target=revoke)
                    thread.start()
                    thread.join(timeout=2)
                    assert not thread.is_alive()

            checks = 0

            def validation():
                nonlocal checks
                checks += 1
                result = validate()
                if phase == "external-validation" and checks == 2:
                    revoke()  # Reentrant owner validation publishes before the final fence.
                return result

            monkeypatch.setattr(MarketHistoryRepository, "upsert_minutes", staged)
            monkeypatch.setattr(pipeline, "_decision_commit_current", validation)
            with pytest.raises(RecoveryAdmissionChangedError):
                pipeline._persist_recovery_capture(capture, (_bar(capture),), cancelled=Event())
            assert entered == ["revoked"]
            with work() as transaction:
                assert transaction.history.get_latest_quote(capture.symbol) is None
                assert transaction.history.list_minutes(
                    capture.symbol, start=capture.required_ends[0], end=capture.required_ends[-1],
                ) == ()

    asyncio.run(scenario())


def test_commit_wins_authority_lock_before_worker_revocation(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            attempted = Event()
            published = Event()
            workers = []
            commit = SqlAlchemyUnitOfWork.commit

            def revoke():
                attempted.set()
                with pipeline._recovery_authority_lock:
                    pipeline._recovery_authority_revoked.set()
                    published.set()

            def commit_first(transaction):
                assert pipeline._recovery_authority_lock._is_owned()
                session = transaction._require_session()
                assert not session.new and not session.dirty and not session.deleted
                worker = Thread(target=revoke)
                workers.append(worker)
                worker.start()
                assert attempted.wait(timeout=2)
                assert not published.is_set()
                commit(transaction)
                assert not published.is_set()

            monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", commit_first)
            pipeline._persist_recovery_capture(capture, (_bar(capture),), cancelled=Event())
            for worker in workers:
                worker.join(timeout=2)  # Only after releasing the lock.
                assert not worker.is_alive()
            assert published.is_set()
            with work() as transaction:
                assert transaction.history.get_latest_quote(capture.symbol).price_fen == 6405

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ("read", "persist"))
def test_scoped_programming_errors_are_not_storage_failures(history, stage):
    sentinel = AssertionError("private programming error sentinel")

    def broken(*_):
        raise sentinel

    async def scenario():
        clock, _, controller, service = setup_service(
            history, {SYMBOL: [minute("09:31:00")]},
            persist=broken if stage == "persist" else None,
        )
        try:
            with pytest.raises(AssertionError) as caught:
                await service.recover_scope(
                    symbol=SYMBOL,
                    target=derive_recovery_target(now=clock.now(), is_open_on=lambda _: True),
                    required_ends=(stamp("09:31:00"),),
                    read_persisted_ends=broken if stage == "read" else history.read,
                    now=clock.now,
                )
            assert caught.value is sentinel
        finally:
            await controller.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("read_number", (1, 2))
def test_guard_change_at_either_coverage_read_is_typed_retarget(history, read_number):
    async def scenario():
        clock, provider, controller, service = setup_service(
            history, {SYMBOL: [minute("09:31:00")]},
        )
        reads = 0

        def read(symbol, required):
            nonlocal reads
            reads += 1
            if reads == read_number:
                raise RecoveryAdmissionChangedError("original identity changed")
            return history.read(symbol, required)

        try:
            result = await service.recover_scope(
                symbol=SYMBOL,
                target=derive_recovery_target(now=clock.now(), is_open_on=lambda _: True),
                required_ends=(stamp("09:31:00"),), read_persisted_ends=read, now=clock.now,
            )
            assert result.retarget_required and not result.ready
            assert result.error_code is None and result.persistence_error is None
            assert provider.calls == ([] if read_number == 1 else [SYMBOL])
        finally:
            await controller.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ("read", "persist"))
def test_storage_error_retains_original_cause_without_retry(history, phase):
    sentinel = OSError("private storage cause")

    def fail(*_):
        raise sentinel

    async def scenario():
        clock, provider, controller, service = setup_service(
            history, {SYMBOL: [minute("09:31:00")]},
        )
        try:
            result = await service.recover_scope(
                symbol=SYMBOL,
                target=derive_recovery_target(now=clock.now(), is_open_on=lambda _: True),
                required_ends=(stamp("09:31:00"),), now=clock.now,
                read_persisted_ends=fail if phase == "read" else history.read,
                persist_selected=fail if phase == "persist" else None,
            )
            assert result.error_code.value == "PERSISTENCE_FAILED"
            assert result.persistence_error is sentinel and not result.retarget_required
            assert "private" not in repr(result)
            assert provider.calls == ([] if phase == "read" else [SYMBOL])
        finally:
            await controller.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ("normal", "reversal", "rollover", "revoked", "source"))
def test_actual_wrapper_finishes_before_frozen_business_sdk_guard(tmp_path, monkeypatch, change):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            sdk.calls.clear()
            client = pipeline.provider._client
            validation = client._current
            calls = []

            def after_wrapper_validation():
                result = validation()
                calls.append("wrapper")
                if change == "normal":
                    pipeline._clock.current += timedelta(seconds=1)
                elif change == "reversal":
                    pipeline._clock.current -= timedelta(microseconds=1)
                elif change == "rollover":
                    pipeline._clock.current += timedelta(days=1)
                elif change == "revoked":
                    pipeline._recovery_authority_revoked.set()
                elif change == "source":
                    client._client = type(sdk)(pipeline._clock, (_sample_plan().symbol,))
                return result

            monkeypatch.setattr(client, "_current", after_wrapper_validation)
            result = await pipeline._recover_frozen_scope(capture)
            assert calls == ["wrapper"]
            if change == "normal":
                assert result.ready
                assert [name for name, _ in sdk.calls] == ["rt_min_daily"]
            else:
                assert result.retarget_required and result.error_code is None
                assert sdk.calls == []
                with work() as transaction:
                    assert transaction.history.get_latest_quote(capture.symbol) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ("configuration", "semantics"))
def test_real_worker_revocation_uses_baseline_lock_and_notifies_after_release(
    tmp_path, monkeypatch, kind,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            runtime = run.composition._runtime._liveness_owner
            pipeline = runtime._pipeline
            baseline = runtime._process_baseline
            assert pipeline._recovery_authority_lock is baseline.authority_lock
            assert pipeline._recovery_authority_revoked is baseline.revoked
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            published_epoch = baseline.authority_epoch
            stage = MarketHistoryRepository.upsert_minutes
            notify_name = (
                "_set_configuration_restart_required" if kind == "configuration"
                else "_set_semantic_reload_blocked"
            )
            notify = getattr(runtime, notify_name)
            notifications = []

            def notified():
                assert not baseline.authority_lock._is_owned()
                assert baseline.revoked.is_set()
                assert baseline.authority_epoch == published_epoch + 1
                notifications.append(kind)
                notify()

            def staged(repository, rows):
                stage(repository, rows)
                worker = Thread(target=getattr(runtime, f"_revoke_{kind}"))
                worker.start()
                worker.join(timeout=2)
                assert not worker.is_alive()
                assert baseline.revoked.is_set()
                assert baseline.authority_epoch == published_epoch + 1
                assert notifications == []  # Notification is marshalled to this owner loop.

            monkeypatch.setattr(runtime, notify_name, notified)
            monkeypatch.setattr(MarketHistoryRepository, "upsert_minutes", staged)
            with pytest.raises(RecoveryAdmissionChangedError):
                pipeline._persist_recovery_capture(capture, (_bar(capture),), cancelled=Event())
            await asyncio.sleep(0)
            assert notifications == [kind]
            assert run.state()["minutes"] == ()
            with runtime.unit_of_work_factory() as transaction:
                assert transaction.history.get_latest_quote(capture.symbol) is None

    asyncio.run(scenario())


def test_real_database_ready_publication_is_locked_but_migration_and_disposal_are_not(
    tmp_path, monkeypatch,
):
    from sqlalchemy import Engine

    import trade_plan_monitor.web.monitor_composition as composition

    assigned = []
    migrated = []
    disposed = []
    states = []
    original_set = composition._ProductionRuntimeState.__setattr__
    migrate = composition.upgrade_database
    dispose = Engine.dispose

    def set_attribute(runtime, name, value):
        if name in {"_database_status", "_wal_status"} and value.value == "READY":
            assert runtime._process_baseline.authority_lock._is_owned()
            assigned.append(name)
        original_set(runtime, name, value)
        if name == "_process_baseline":
            states.append(runtime)

    def migration(engine):
        assert all(not state._process_baseline.authority_lock._is_owned() for state in states)
        migrated.append(engine)
        return migrate(engine)

    def disposal(engine, *args, **kwargs):
        assert all(not state._process_baseline.authority_lock._is_owned() for state in states)
        disposed.append(engine)
        return dispose(engine, *args, **kwargs)

    monkeypatch.setattr(composition._ProductionRuntimeState, "__setattr__", set_attribute)
    monkeypatch.setattr(composition, "upgrade_database", migration)
    monkeypatch.setattr(Engine, "dispose", disposal)

    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            assert assigned == ["_database_status", "_wal_status"]
            assert run.composition._runtime._liveness_owner._engine in migrated
        assert run.composition._runtime._liveness_owner._engine in disposed

    asyncio.run(scenario())


@pytest.mark.parametrize("field", (
    "_stopping", "_cleanup_complete", "_cleanup_failed", "_liveness_failed",
))
def test_final_fence_preserves_all_actual_lifecycle_admission_dependencies(
    tmp_path, monkeypatch, field,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            lifecycle = run.composition._runtime
            pipeline = lifecycle._liveness_owner._pipeline
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            original = getattr(lifecycle, field)
            try:
                setattr(lifecycle, field, True)
                assert not lifecycle.business_commit_admission_open
                with pytest.raises(RecoveryAdmissionChangedError):
                    pipeline._persist_recovery_capture(capture, (_bar(capture),), cancelled=Event())
                assert run.state()["minutes"] == ()
            finally:
                setattr(lifecycle, field, original)

    asyncio.run(scenario())


def test_startup_fence_does_not_add_accepting_work_as_a_dependency(tmp_path, monkeypatch):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            lifecycle = run.composition._runtime
            pipeline = lifecycle._liveness_owner._pipeline
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            original = lifecycle._accepting_work
            try:
                lifecycle._accepting_work = False
                assert lifecycle.business_commit_admission_open
                pipeline._persist_recovery_capture(capture, (_bar(capture),), cancelled=Event())
                assert run.state()["minutes"] == (capture.required_ends[-1].isoformat(),)
            finally:
                lifecycle._accepting_work = original

    asyncio.run(scenario())


def test_business_worker_has_no_sql_and_final_lock_has_only_clean_commit(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            with work() as transaction:
                engine = transaction._require_session().get_bind()
            owner_thread = get_ident()
            commits = []
            statements = []

            def sql(_connection, _cursor, statement, _parameters, _context, _executemany):
                assert get_ident() == owner_thread
                assert not pipeline._recovery_authority_lock._is_owned()
                statements.append(statement)

            def commit(_connection):
                assert get_ident() == owner_thread
                assert pipeline._recovery_authority_lock._is_owned()
                commits.append(True)

            event.listen(engine, "before_cursor_execute", sql)
            event.listen(engine, "commit", commit)
            try:
                result = await pipeline._recover_frozen_scope(capture)
                assert result.ready and commits == [True]
                assert statements.count("BEGIN") == 3  # pre-read, final owned write, post-read
            finally:
                event.remove(engine, "before_cursor_execute", sql)
                event.remove(engine, "commit", commit)

    asyncio.run(scenario())


@pytest.mark.parametrize(("hour", "minute_value", "expected"), (
    (9, 30, 0), (9, 31, 1), (11, 30, 120), (12, 15, 120),
    (13, 0, 120), (13, 1, 121), (15, 0, 240), (15, 30, 240),
))
def test_capture_uses_exact_bounded_trading_prefix_excluding_lunch(
    tmp_path, monkeypatch, hour, minute_value, expected,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            pipeline._clock.current = NOW.replace(hour=hour, minute=minute_value, second=0)
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            if expected == 0:
                assert capture is None
            else:
                assert len(capture.required_ends) == expected
                assert not any(11 * 60 + 30 < end.hour * 60 + end.minute <= 13 * 60
                               for end in capture.required_ends)
                assert capture.required_ends[-1] == capture.target.completed_minute_end

    asyncio.run(scenario())


def test_capture_authority_failure_is_not_silently_skipped(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            pipeline._generation_current = lambda: False
            with pytest.raises(RecoveryAdmissionChangedError):
                pipeline._capture_recovery_scope(_sample_plan().symbol)

    asyncio.run(scenario())


def test_real_provider_wait_preserves_concurrent_winner_despite_later_response_receipt(
    tmp_path, monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            entered, release = Event(), Event()
            fetch = sdk._stock_minutes
            entries = []

            def waiting_endpoint(name, kwargs):
                entries.append(name)
                entered.set()
                assert release.wait(timeout=5)
                return fetch(name, kwargs)

            monkeypatch.setattr(sdk, "_stock_minutes", waiting_endpoint)
            task = asyncio.create_task(pipeline._recover_frozen_scope(capture))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                winner = _bar(capture, price=6500).model_copy(update={"volume_shares": 2000})
                with work() as transaction:
                    transaction.history.upsert_minutes((winner,))
                    transaction.commit()
                    quote = transaction.history.get_latest_quote(capture.symbol)
                pipeline._clock.current += timedelta(seconds=1)
                release.set()
                result = await task
                assert result.ready and entries == ["rt_min_daily"]
                with work() as transaction:
                    rows = transaction.history.list_minutes(
                        capture.symbol, start=capture.required_ends[0],
                        end=capture.required_ends[-1],
                    )
                    assert tuple(row.bar_end for row in rows) == capture.required_ends
                    assert rows[-1] == winner  # Includes every OHLC, volume and receipt field.
                    assert all(row.received_at == NOW + timedelta(seconds=1) for row in rows[:-1])
                    assert transaction.history.get_latest_quote(capture.symbol) == quote
            finally:
                release.set()
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_waiting_for_serial_scope_rechecks_original_activation_before_fetch(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            sdk.calls.clear()
            await pipeline.recovery._serial.acquire()
            task = asyncio.create_task(pipeline._recover_frozen_scope(capture))
            try:
                await asyncio.sleep(0)
                replacement = replace_or_reactivate(work, pipeline, _sample_plan())
            finally:
                pipeline.recovery._serial.release()
            result = await task
            assert result.retarget_required and result.error_code is None
            assert result.target == capture.target and sdk.calls == []
            with work() as transaction:
                assert transaction.plans.get_active(capture.symbol).revision == replacement.revision
                assert transaction.history.get_latest_quote(capture.symbol) is None

    asyncio.run(scenario())


def test_scoped_commit_storage_failure_rolls_back_and_preserves_original_error(
    tmp_path, monkeypatch,
):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            sdk.calls.clear()
            sentinel = OperationalError("COMMIT", {}, OSError("private test storage cause"))
            commits = []

            def fail_commit(transaction):
                assert not transaction._require_session().dirty
                commits.append(True)
                raise sentinel

            monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", fail_commit)
            result = await pipeline._recover_frozen_scope(capture)
            assert result.persistence_error is sentinel
            assert result.error_code.value == "PERSISTENCE_FAILED"
            assert not result.retarget_required and commits == [True]
            assert [name for name, _ in sdk.calls] == ["rt_min_daily"]
            with work() as transaction:
                assert transaction.history.get_latest_quote(capture.symbol) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("at_wrapper", (True, False), ids=("before-SDK", "after-SDK"))
def test_begin_shutdown_synchronously_revokes_attempt_before_cancel_or_drain(
    tmp_path, monkeypatch, at_wrapper,
):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            lifecycle = run.composition._runtime
            state = lifecycle._liveness_owner
            pipeline = state._pipeline
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            entered, release = Event(), Event()
            tokens = []
            client = pipeline.provider._client
            sdk = client._client
            initial_calls = len(sdk.calls)
            validation, fetch = client._current, sdk._stock_minutes
            recover = pipeline.recovery.recover_scope

            async def record_token(**kwargs):
                tokens.append(kwargs["cancelled"])
                return await recover(**kwargs)

            def wait():
                entered.set()
                assert release.wait(timeout=5)

            def wrapper():
                valid = validation()
                wait()
                return valid

            def endpoint(name, kwargs):
                wait()
                return fetch(name, kwargs)

            monkeypatch.setattr(pipeline.recovery, "recover_scope", record_token)
            monkeypatch.setattr(client, "_current", wrapper) if at_wrapper else monkeypatch.setattr(
                sdk, "_stock_minutes", endpoint,
            )
            task = asyncio.create_task(pipeline._recover_frozen_scope(capture))
            lifecycle._work_tasks.add(task)
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                assert len(tokens) == 1 and not tokens[0].is_set()
                lifecycle.begin_shutdown()
                # No await/sleep between shutdown and these observations.
                assert tokens[0].is_set()
                assert task.cancelling() == 0 and not task.done()
                assert not release.is_set() and pipeline._controller.active_count == 1
                assert state._database_status.value == "READY"
                assert lifecycle._database_opened
                assert not state._process_baseline.revoked.is_set()
                lifecycle.begin_shutdown()
                assert tokens[0].is_set()
                release.set()
                result = await task
                assert result.retarget_required
                assert len(sdk.calls) - initial_calls == (0 if at_wrapper else 1)
                assert run.state()["minutes"] == ()
                assert pipeline._active_recovery_attempts == set()
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
                lifecycle._work_tasks.discard(task)

    asyncio.run(scenario())


def test_revoker_failure_latches_through_repeated_shutdown_until_stop_reports_it():
    from test_runtime_lifecycle import _service

    async def scenario():
        events = []
        service = _service(events=events)
        await service.start()
        sentinel = RuntimeError("private revoker failure")
        calls = 0

        def revoke():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sentinel

        service._revoke_active_recovery_attempts = revoke
        service.begin_shutdown()  # Must not interrupt admission/resource shutdown.
        service.begin_shutdown()  # A successful repeat cannot erase the unreported error.
        assert "controller-close" in events
        with pytest.raises(RuntimeError) as caught:
            await service.stop()
        assert caught.value is sentinel and service.cleanup_failed
        assert "dispatcher-close" in events and "database-close" in events
        assert not service._cleanup_complete
        # The original failure was observed; existing cleanup retry may finish.
        await service.stop()
        assert service._cleanup_complete and not service.cleanup_failed

    asyncio.run(scenario())


@pytest.mark.parametrize("drain", ("heartbeat", "dispatcher", "provider"))
def test_revoker_error_does_not_replace_primary_drain_error_or_its_cause(drain):
    from test_runtime_lifecycle import _service

    async def scenario():
        events = []
        service = _service(events=events, shutdown_timeout_seconds=0.01)
        await service.start()
        revoker_error = RuntimeError("private revoker sentinel")
        drain_cause = TimeoutError("private original drain cause")
        drain_error = RuntimeError("private original drain failure")

        def revoke():
            raise revoker_error

        async def broken_drain():
            raise drain_error from drain_cause

        service._revoke_active_recovery_attempts = revoke
        heartbeat = None
        if drain == "heartbeat":
            heartbeat = asyncio.create_task(asyncio.Event().wait())
            service._heartbeat_task = heartbeat
        elif drain == "dispatcher":
            service._dispatcher.aclose = broken_drain
        else:
            service._request_controller.aclose = broken_drain
        try:
            with pytest.raises(RuntimeError) as caught:
                await service.stop()
            if drain == "heartbeat":
                assert str(caught.value) == "runtime heartbeat did not drain"
                assert isinstance(caught.value.__cause__, TimeoutError)
            else:
                assert caught.value is drain_error and caught.value.__cause__ is drain_cause
            assert caught.value.recovery_revocation_error is revoker_error
            assert service.cleanup_failed
            assert "database-close" not in events and "wal-checkpoint" not in events
            assert service._database_opened
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)

    asyncio.run(scenario())


def test_late_attempt_is_revoked_before_first_await_and_cannot_enter_sdk(tmp_path, monkeypatch):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, _):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            sdk.calls.clear()
            pipeline._generation_current = lambda: False
            with pytest.raises(RecoveryAdmissionChangedError):
                await pipeline._recover_frozen_scope(capture)
            assert pipeline._active_recovery_attempts == set() and sdk.calls == []

    asyncio.run(scenario())


def test_unpublished_candidate_with_no_pipeline_can_be_stopped_repeatedly(tmp_path, monkeypatch):
    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            published = run.composition._runtime
            candidate = run.composition._runtime_factory()
            state = candidate._liveness_owner
            assert state._pipeline is None and candidate is not published
            candidate.begin_shutdown()
            candidate.begin_shutdown()
            assert candidate._stopping and not state._process_baseline.revoked.is_set()
            assert published.business_commit_admission_open
            await candidate.stop()
            await candidate.stop()
            assert candidate._cleanup_complete

    asyncio.run(scenario())


def test_new_legal_generation_registers_fresh_tokens_instead_of_old_cancelled_tokens(
    tmp_path, monkeypatch,
):
    from trade_plan_monitor.runtime.recovery import RecoveryService

    observations = []
    original = RecoveryService.recover_scope

    async def observe(service, **kwargs):
        token = kwargs["cancelled"]
        observations.append((token, token.is_set()))
        return await original(service, **kwargs)

    monkeypatch.setattr(RecoveryService, "recover_scope", observe)

    async def scenario():
        async with _running(tmp_path, monkeypatch, "empty") as run:
            old = run.composition._runtime
            old_generation = old.runtime_generation
            old_token = observations[-1][0]
            await run.composition.stop()
            assert old_token.is_set()
            candidate = run.composition._runtime_factory()
            try:
                await candidate.start()
                assert candidate.runtime_generation != old_generation
                token, was_cancelled = observations[-1]
                assert token is not old_token and not was_cancelled
                assert candidate._liveness_owner._pipeline._active_recovery_attempts == set()
            finally:
                await candidate.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("callback", (False, 1, "not callable"))
def test_lifecycle_rejects_noncallable_revocation_callback(monkeypatch, callback):
    import test_runtime_lifecycle as lifecycle_tests

    constructor = lifecycle_tests.RuntimeLifecycleService
    monkeypatch.setattr(
        lifecycle_tests, "RuntimeLifecycleService",
        lambda **kwargs: constructor(**kwargs, revoke_active_recovery_attempts=callback),
    )
    with pytest.raises(TypeError, match="revoke_active_recovery_attempts must be callable"):
        lifecycle_tests._service()


def test_lifecycle_honors_a_valid_falsey_revocation_callable(monkeypatch):
    import test_runtime_lifecycle as lifecycle_tests

    calls = []

    class FalseyRevoker:
        def __bool__(self):
            return False

        def __call__(self):
            calls.append("revoked")

    constructor = lifecycle_tests.RuntimeLifecycleService
    callback = FalseyRevoker()
    monkeypatch.setattr(
        lifecycle_tests, "RuntimeLifecycleService",
        lambda **kwargs: constructor(**kwargs, revoke_active_recovery_attempts=callback),
    )
    service = lifecycle_tests._service()
    service.begin_shutdown()
    assert calls == ["revoked"]


@pytest.mark.parametrize("at_wrapper", (True, False), ids=("before-SDK", "after-SDK"))
def test_cancel_sets_attempt_token_and_drains_without_late_write(tmp_path, monkeypatch, at_wrapper):
    async def scenario():
        with _pipeline(tmp_path, monkeypatch, with_plan=True) as (pipeline, sdk, _, _, work):
            sdk.stock_symbols = (_sample_plan().symbol,)
            await pipeline.refresh_references(NOW.date())
            capture = pipeline._capture_recovery_scope(_sample_plan().symbol)
            sdk.calls.clear()
            entered, release = Event(), Event()
            client = pipeline.provider._client
            validation = client._current
            stock_minutes = sdk._stock_minutes

            def wait():
                entered.set()
                assert release.wait(timeout=5)

            def wrapper():
                valid = validation()
                wait()
                return valid

            def endpoint(name, kwargs):
                wait()
                return stock_minutes(name, kwargs)

            if at_wrapper:
                monkeypatch.setattr(client, "_current", wrapper)
            else:
                monkeypatch.setattr(sdk, "_stock_minutes", endpoint)
            task = asyncio.create_task(pipeline._recover_frozen_scope(capture))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()  # Physical worker is still owned and draining.
                assert pipeline._controller.active_count == 1
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert pipeline._controller.active_count == 0
                assert len(sdk.calls) == (0 if at_wrapper else 1)
                with work() as transaction:
                    assert transaction.history.get_latest_quote(capture.symbol) is None
            finally:
                release.set()
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
