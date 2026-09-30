"""Actual official-close commits remain current only for their owned applicable target."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline


@pytest.mark.parametrize("full_history", [False, True])
def test_real_official_close_proof_and_current_projection_are_target_fenced(
    tmp_path, monkeypatch, full_history,
):
    import test_live_pipeline_acceptance as fixture
    from test_persistent_monitor_read_service import _setup

    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.live_profiles import create_stock_certification
    from trade_plan_monitor.market_data.models import DailyBar
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel
    from trade_plan_monitor.runtime.progress import ProgressSnapshot
    from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
    from trade_plan_monitor.runtime.service import OfficialCloseCycleStatus
    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    async def scenario():
        clock = fixture.ControlledClock(fixture.NOW.replace(hour=9, minute=0))
        plan = fixture._sample_plan()
        database = tmp_path / "official-status.sqlite3"
        fixture._activate_plans(database, clock, (plan,))
        clock.current = fixture.NOW.replace(hour=15, minute=35)
        config = fixture._write_configuration_and_evidence(
            tmp_path, observed_at=clock.now(), include_index=False,
        )
        sdk = fixture.OfflineSDK(
            clock, (plan.symbol,), official_closes={clock.now().date(): "55.00"},
        )
        monkeypatch.setattr(
            "trade_plan_monitor.runtime.production.create_tushare_client", lambda _config: sdk,
        )
        pace = fixture.VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
        )
        engine, work = fixture._work_factory(database, clock)
        sessions = work()._session_factory
        generation = uuid4()
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data/live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(), endpoint_url=fixture.ENDPOINT,
                capabilities=fixture._ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock, request_controller=controller, unit_of_work_factory=work,
            runtime_generation=generation, publisher=lambda _event: None,
            recovery_session_factory=sessions, enable_runtime_status=True,
        )
        other, _, _, health = _setup(tmp_path)
        other.dispose()
        day = clock.now().date()

        def authority():
            token, configuration, plans = pipeline.runtime_status_snapshot()
            observed = clock.now()
            return RuntimeReadAuthority(
                token=token, lifecycle="RUNNING", health=health,
                configuration_revision=configuration, plans=plans,
                progress=ProgressSnapshot(
                    generation, observed, "SCHEDULED", observed,
                    observed + timedelta(seconds=10), observed + timedelta(seconds=30),
                ),
            )

        reader = RuntimeStatusReadService(sessions, authority, clock=clock.now)
        try:
            if full_history:
                dates = []
                previous = day - timedelta(days=1)
                while len(dates) < 500:
                    if previous.weekday() < 5:
                        dates.append(previous)
                    previous -= timedelta(days=1)
                with work() as unit:
                    unit.history.upsert_daily_bars(tuple(DailyBar(
                        symbol=plan.symbol, trade_date=previous,
                        open_fen=6400, high_fen=6410, low_fen=6390, close_fen=6405,
                        volume_shares=100_000, amount_yuan=Decimal("64000"),
                        is_official=True, received_at=clock.now() - timedelta(seconds=1),
                    ) for previous in reversed(dates)))
                    unit.commit()
            await pipeline.refresh_references(day)
            outcome = await pipeline.evaluations.run_official_close(
                plan=plan, trade_date=day, evaluated_at=clock.now(), close_attempt=1,
            )
            assert outcome.status is OfficialCloseCycleStatus.COMMITTED
            assert pipeline.evaluations.pending_close_date(plan.symbol) is None
            proof = pipeline._runtime_status_proofs[plan.symbol]
            assert proof is not None
            assert proof.target == OfficialCloseEvaluationTarget(trade_date=day)
            assert pipeline.runtime_status_snapshot()[2][0].target == proof.target
            writes = []

            def record(_conn, _cursor, statement, _params, _context, _many):
                if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                    writes.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                row = (await reader.get_dashboard()).symbols[0]
                assert writes == []
            finally:
                event.remove(engine, "before_cursor_execute", record)
            assert row.availability == "CURRENT"
            assert row.scope.status == "READY"
            assert row.scope.required_target.kind == "OFFICIAL_CLOSE"
            for stale in (
                replace(proof, runtime_generation=uuid4()),
                replace(proof, configuration_revision="obsolete-config"),
                replace(proof, activation_revision=proof.activation_revision + 1),
                replace(proof, plan_version_id=str(uuid4())),
            ):
                pipeline._runtime_status_proofs[plan.symbol] = stale
                assert pipeline.runtime_status_snapshot()[2][0].completion is None
            pipeline._runtime_status_proofs[plan.symbol] = proof
            clock.current += timedelta(minutes=1)
            assert (await reader.get_dashboard()).symbols[0].availability == "CURRENT"
            if full_history:
                with work() as unit:
                    oldest = unit.history.list_daily_bars(
                        plan.symbol, start=dates[-1], end=dates[-1],
                    )[0]
                    unit.history.upsert_daily_bars((oldest.model_copy(update={
                        "open_fen": 6406, "close_fen": 6406, "received_at": clock.now(),
                    }),))
                    unit.commit()
                assert (await reader.get_dashboard()).symbols[0].availability == "CACHED"
            # Next session's actual completed five-minute target cannot inherit
            # the previous day's completed official-close proof.
            clock.current = (clock.current + timedelta(days=1)).replace(hour=10, minute=0)
            scope = pipeline.runtime_status_snapshot()[2][0]
            assert scope.completion is None
            assert scope.target != proof.target
            assert (await reader.get_dashboard()).symbols[0].availability == "CACHED"
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())
