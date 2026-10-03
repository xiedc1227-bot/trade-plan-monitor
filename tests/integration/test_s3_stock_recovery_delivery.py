"""Recovered explicit facts reach real current-delivery admission, entirely offline."""

import asyncio
import inspect
import json
from datetime import timedelta

import httpx
import pytest
import requests
from sqlalchemy import text
from test_explicit_runtime_production import TARGET, _ExplicitPipelineSDK
from test_live_pipeline_acceptance import VirtualPace, _write_configuration_and_evidence
from test_production_semantic_gate import _replace_stock_contract
from test_s3_startup_outcome_association import _DeadlineClock
from tests.integration.current_activation_fixture import current_sample_plan
from tests.integration.test_daily_plan_chain import Chain

from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.notifications.current_delivery import CurrentDeliveryAdmission
from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
from trade_plan_monitor.runtime.scheduler import DeadlineKind
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
)
from trade_plan_monitor.state.models import RuntimeLiveness
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle


def _facts(engine):
    with engine.connect() as connection:
        return {
            table: tuple(
                dict(row)
                for row in connection.execute(
                    text(
                        f"SELECT * FROM {table} ORDER BY rowid",
                    )
                ).mappings()
            )
            for table in (
                "daily_plan_record",
                "alert_event",
                "alert_delivery_eligibility",
                "delivery_attempt",
                "minute_bar",
            )
        }


@pytest.mark.parametrize("mutation", ["metadata", "reactivation"])
def test_scheduled_current_repair_keeps_real_final_send_authority(
    tmp_path,
    monkeypatch,
    mutation,
):
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.web.monitor_composition as composition_module

    async def scenario():
        initial = TARGET - timedelta(minutes=5) + timedelta(seconds=15)
        clock = _DeadlineClock(initial)
        payload = current_sample_plan().model_dump(mode="json")
        payload["ordinary_rules"][0]["condition"]["price_fen"] = 1000
        from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

        plan = UnifiedTradePlan.model_validate(payload)
        database = tmp_path / "monitor.sqlite3"
        chain = Chain(tmp_path)
        chain.plan = plan
        chain.plans = PersistentPlanWebLifecycle(database_path=database, clock=lambda: chain.now)
        from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService

        chain.runtime = DailyRuntimeEvaluationService(
            chain.plans._unit_of_work, clock=lambda: chain.now
        )
        with chain.client:
            chain.now = TARGET - timedelta(days=3)
            with chain.plans._unit_of_work() as transaction:
                transaction.references.upsert_trading_days(
                    (
                        TradingDay(
                            exchange=plan.market,
                            cal_date=chain.now.date(),
                            is_open=True,
                            previous_trade_date=chain.now.date() - timedelta(days=1),
                        ),
                    )
                )
                transaction.commit()
            chain.post(
                "simulation-position-confirmations",
                {"symbol": plan.symbol, "coreQty": 0, "tacticalQty": 100, "expectedRevision": 0},
            )
            chain.now = initial - timedelta(minutes=5)
            chain.activate()
            stamp = chain.now.isoformat()
            chain.post(
                "plan-facts",
                {
                    "planVersionId": chain.version["id"],
                    "contentHash": chain.version["contentHash"],
                    "factId": "delivery-tradability",
                    "kind": "TRADABILITY",
                    "tradeDate": str(TARGET.date()),
                    "evidence": "Verified tradability fixture",
                    "officialEvidence": {
                        "issuer": "Synthetic exchange evidence fixture",
                        "documentTitle": "Verified tradeability fixture",
                        "documentUrl": "https://example.test/tradability",
                        "publishedAt": stamp,
                        "verifiedAt": stamp,
                        "applicableAssertion": "Synthetic official evidence verifies tradability",
                    },
                    "expectedRevision": 0,
                },
            )
        engine = create_sqlite_engine(database)
        sessions = create_session_factory(engine)

        def work():
            return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

        with work() as transaction:
            transaction.references.upsert_trading_days(
                (
                    TradingDay(
                        exchange=plan.market,
                        cal_date=TARGET.date(),
                        is_open=True,
                        previous_trade_date=(TARGET - timedelta(days=3)).date(),
                    ),
                )
            )
            transaction.commit()
        with sessions.begin() as session:
            session.add(
                RuntimeLiveness(
                    id=1,
                    schema_version=1,
                    revision=0,
                    last_alive_at=initial.isoformat(),
                )
            )
        config = _write_configuration_and_evidence(
            tmp_path,
            observed_at=initial,
            include_index=False,
        )

        active_deadlines, maintenance_calls = {}, []

        class SDK(_ExplicitPipelineSDK):
            history_available = False

            def __getattr__(self, name):
                request = super().__getattr__(name)

                def call(**kwargs):
                    if name == "rt_min_daily" and self.history_available:
                        ((owner, deadline),) = active_deadlines.items()
                        assert deadline.kind is DeadlineKind.STOCK_RECOVERY
                        assert owner in runtime._work_tasks and not owner.done()
                        (scope,) = pipeline._stock_recovery_schedule.snapshot()
                        assert scope.requirement.scope_key == f"stock-prefix:{plan.symbol}"
                        assert scope.in_progress
                        maintenance_calls.append(deadline)
                    self.source_time = clock.now().replace(second=0, microsecond=0) - timedelta(
                        minutes=1,
                    )
                    frame = request(**kwargs)
                    if name == "rt_min_daily" and not self.history_available:
                        return frame.iloc[:0].copy()
                    return frame

                return call

        sdk = SDK(current_volume=60)
        sent, holds, claimed, origins = [], [], [], []

        class Channel:
            channel = DeliveryChannel.CONSOLE
            enabled = True

            async def deliver(self, event):
                sent.append(event)
                return ChannelDeliveryResult(
                    channel=self.channel,
                    delivered=True,
                    retryable=False,
                )

        real_controller = composition_module.create_live_tushare_request_controller

        def controller_factory(*, clock, require_repository_binding=False):
            pace = VirtualPace()
            return real_controller(
                clock=clock,
                monotonic=pace.monotonic,
                pace_sleep=pace.sleep,
                require_repository_binding=require_repository_binding,
            )

        def forbid_http(*_args, **_kwargs):
            pytest.fail("offline delivery fixture must not access HTTP")

        monkeypatch.setattr(requests.Session, "request", forbid_http)
        monkeypatch.setattr(httpx.Client, "send", forbid_http)
        monkeypatch.setattr(httpx.AsyncClient, "send", forbid_http)
        monkeypatch.setattr(composition_module, "SystemClock", lambda: clock)
        monkeypatch.setattr(
            composition_module, "create_live_tushare_request_controller", controller_factory
        )
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        original_commit = SqlAlchemyUnitOfWork.commit

        def observe_initial_hold(transaction):
            session = transaction._require_session()
            if not holds and session.scalar(text("SELECT count(*) FROM alert_event")):
                assert session.scalar(text("SELECT count(*) FROM alert_delivery_eligibility")) == 0
                head = session.scalar(
                    text("SELECT payload_json FROM daily_plan_record WHERE id=:id"),
                    {"id": "evaluation-head-" + plan.symbol},
                )
                assert json.loads(head)["activation_revision"] == 1
                holds.append("CURRENT_BINDING_STAGED")
            return original_commit(transaction)

        monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", observe_initial_hold)
        original_claim = NotificationDispatcher._claim_attempt

        def after_real_claim(dispatcher, event_id, channel, attempt, claimed_at):
            claim = original_claim(dispatcher, event_id, channel, attempt, claimed_at)
            if claim is None:
                return None
            before = _facts(engine)
            assert before["delivery_attempt"][0]["status"] == "CLAIMED"
            assert not claimed
            claimed.append(claim)
            origins.append(before)
            if mutation == "metadata":
                semantic_path = tmp_path / "data/live-certification/stock-semantic.json"
                revision = json.loads(semantic_path.read_text(encoding="utf-8"))["semanticRevision"]
                _replace_stock_contract(tmp_path / "data/live-certification")
                assert (
                    json.loads(semantic_path.read_text(encoding="utf-8"))["semanticRevision"]
                    == revision
                    == pipeline._stock_semantics.semantic_revision
                )
            else:
                with work() as transaction:
                    transaction.plans.deactivate(plan.symbol, expected_revision=1)
                    transaction.plans.activate(
                        plan,
                        expected_revision=2,
                        validation=PlanValidationResult(issues=()),
                    )
                    transaction.commit()
                with work() as transaction:
                    assert transaction.plans.get_active(plan.symbol).revision == 3
            return claim

        monkeypatch.setattr(NotificationDispatcher, "_claim_attempt", after_real_claim)
        composition = composition_module.create_monitor_composition(
            config_path=config,
            database_path=database,
        )
        runtime = composition._runtime
        runtime._dispatcher._channels = (Channel(),)
        assert isinstance(
            inspect.getclosurevars(runtime._dispatcher._admission).nonlocals[
                "current_delivery_admission"
            ],
            CurrentDeliveryAdmission,
        )
        try:
            assert (await composition.start()).status.value == "RUNNING"
            await clock.park()
            generation = runtime.runtime_generation
            pipeline = runtime._run_deadline.__self__._pipeline
            real_run_deadline = runtime._run_deadline

            async def observe_deadline(deadline):
                owner = asyncio.current_task()
                active_deadlines[owner] = deadline
                try:
                    return await real_run_deadline(deadline)
                finally:
                    del active_deadlines[owner]

            monkeypatch.setattr(runtime, "_run_deadline", observe_deadline)
            assert sdk.calls.count("rt_min_daily") == 1
            assert _facts(engine)["minute_bar"] == ()
            sdk.history_available = True
            await clock.drive(TARGET - timedelta(microseconds=1))
            repaired = _facts(engine)
            assert repaired["minute_bar"] and sdk.calls.count("rt_min_daily") >= 2
            assert maintenance_calls
            assert not [
                row
                for row in repaired["daily_plan_record"]
                if row["kind"] == "EVALUATION"
                and json.loads(row["payload_json"])["minute_target"] is not None
            ]
            assert repaired["alert_event"] == ()
            await clock.drive(
                TARGET + timedelta(seconds=12), failed=lambda: composition._runner_task.done()
            )
            assert not composition._runner_task.done(), composition.health()
            assert runtime.runtime_generation == generation
            assert composition.health().degraded_reason != "RUNTIME_RUNNER_FAILED"
            final = _facts(engine)
            assert holds == ["CURRENT_BINDING_STAGED"] and len(claimed) == 1
            for table in (
                "daily_plan_record",
                "alert_event",
                "minute_bar",
            ):
                assert final[table] == origins[0][table]
            evaluations = [
                json.loads(row["payload_json"])
                for row in final["daily_plan_record"]
                if row["kind"] == "EVALUATION"
                and not row["id"].startswith("evaluation-head-")
                and json.loads(row["payload_json"])["minute_target"] is not None
            ]
            (ledger,) = evaluations
            assert ledger["activation_revision"] == 1
            assert ledger["minute_target"] == TARGET.isoformat()
            assert ledger["evaluated_at"] == (TARGET + timedelta(seconds=12)).isoformat()
            (signal,) = ledger["signals"]
            assert signal["side"] == "BUY" and signal["executable_qty"] == 100
            assert len(sent) == (1 if mutation == "metadata" else 0)
            (attempt,) = final["delivery_attempt"]
            assert attempt["status"] == ("DELIVERED" if mutation == "metadata" else "CLAIMED")
            if mutation == "reactivation":
                assert final["alert_delivery_eligibility"] == ()
                with work() as transaction:
                    assert transaction.plans.get_active(plan.symbol).revision == 3
        finally:
            await asyncio.wait_for(composition.stop(), timeout=10)
            engine.dispose()

    async def bounded():
        async with asyncio.timeout(30):
            await scenario()

    asyncio.run(bounded())
