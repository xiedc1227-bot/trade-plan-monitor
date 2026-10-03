"""Actual official-close commits remain current only for their owned applicable target."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event
from tests.integration import test_daily_plan_chain as chain_fixture

from trade_plan_monitor.decision.models import OfficialCloseEvaluationTarget
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline

current_chain = chain_fixture.chain


@pytest.mark.parametrize("full_history", [False, True])
def test_frozen_official_close_source_proof_stays_readonly_without_current_authority(
    tmp_path,
    monkeypatch,
    full_history,
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
            tmp_path,
            observed_at=clock.now(),
            include_index=False,
        )
        sdk = fixture.OfflineSDK(
            clock,
            (plan.symbol,),
            official_closes={clock.now().date(): "55.00"},
        )
        monkeypatch.setattr(
            "trade_plan_monitor.runtime.production.create_tushare_client",
            lambda _config: sdk,
        )
        pace = fixture.VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock,
            monotonic=pace.monotonic,
            pace_sleep=pace.sleep,
        )
        engine, work = fixture._work_factory(database, clock)
        sessions = work()._session_factory
        generation = uuid4()
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data/live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(),
                endpoint_url=fixture.ENDPOINT,
                capabilities=fixture._ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work,
            runtime_generation=generation,
            publisher=lambda _event: None,
            recovery_session_factory=sessions,
            enable_runtime_status=True,
        )
        other, _, _, health = _setup(tmp_path)
        other.dispose()
        day = clock.now().date()

        def authority():
            token, configuration, plans = pipeline.runtime_status_snapshot()
            observed = clock.now()
            return RuntimeReadAuthority(
                token=token,
                lifecycle="RUNNING",
                health=health,
                configuration_revision=configuration,
                plans=plans,
                progress=ProgressSnapshot(
                    generation,
                    observed,
                    "SCHEDULED",
                    observed,
                    observed + timedelta(seconds=10),
                    observed + timedelta(seconds=30),
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
                    unit.history.upsert_daily_bars(
                        tuple(
                            DailyBar(
                                symbol=plan.symbol,
                                trade_date=previous,
                                open_fen=6400,
                                high_fen=6410,
                                low_fen=6390,
                                close_fen=6405,
                                volume_shares=100_000,
                                amount_yuan=Decimal("64000"),
                                is_official=True,
                                received_at=clock.now() - timedelta(seconds=1),
                            )
                            for previous in reversed(dates)
                        )
                    )
                    unit.commit()
            await pipeline.refresh_references(day)
            await fixture._warm_frozen_references(pipeline, (plan,), day, work)
            outcome = await pipeline.evaluations.run_official_close(
                plan=plan,
                trade_date=day,
                evaluated_at=clock.now(),
                close_attempt=1,
            )
            assert outcome.status is OfficialCloseCycleStatus.COMMITTED
            assert pipeline.evaluations.pending_close_date(plan.symbol) is None
            proof = pipeline._runtime_status_proofs[plan.symbol]
            assert proof is not None
            assert proof.target == OfficialCloseEvaluationTarget(trade_date=day)
            assert pipeline.runtime_status_snapshot()[2][0].target is None
            assert pipeline.runtime_status_snapshot()[2][0].blocked
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
            assert row.availability == "UNAVAILABLE"
            assert row.scope.status == "BLOCKED" and row.scope.read_only
            assert row.reason_code == "LEGACY_PLANS_REQUIRE_REVIEW"
            assert row.scope.required_target is None
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
            assert (await reader.get_dashboard()).symbols[0].availability == "UNAVAILABLE"
            if full_history:
                with work() as unit:
                    oldest = unit.history.list_daily_bars(
                        plan.symbol,
                        start=dates[-1],
                        end=dates[-1],
                    )[0]
                    unit.history.upsert_daily_bars(
                        (
                            oldest.model_copy(
                                update={
                                    "open_fen": 6406,
                                    "close_fen": 6406,
                                    "received_at": clock.now(),
                                }
                            ),
                        )
                    )
                    unit.commit()
                from trade_plan_monitor.runtime.status_authority import capture_input_stamp

                with sessions() as session, session.begin():
                    changed = capture_input_stamp(
                        session, plan=plan, result=outcome.evaluation_result, now=clock.now()
                    )
                    assert changed != proof.input_stamp
                assert (await reader.get_dashboard()).symbols[0].availability == "UNAVAILABLE"
            # Next session's actual completed five-minute target cannot inherit
            # the previous day's completed official-close proof.
            clock.current = (clock.current + timedelta(days=1)).replace(hour=10, minute=0)
            scope = pipeline.runtime_status_snapshot()[2][0]
            assert scope.completion is None
            assert scope.target != proof.target
            assert (await reader.get_dashboard()).symbols[0].availability == "UNAVAILABLE"
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("correction", ("source", "blocked_basis", "expired_day", "expired_range"))
def test_current_official_status_rechecks_owned_target_source_and_basis(
    tmp_path, monkeypatch, correction
):
    import json

    import test_live_pipeline_acceptance as fixture
    from test_persistent_monitor_read_service import _setup
    from tests.integration.current_activation_fixture import current_sample_plan, seed_current
    from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.live_profiles import create_stock_certification
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel
    from trade_plan_monitor.runtime.progress import ProgressSnapshot
    from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller
    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    async def scenario():
        clock = fixture.ControlledClock(fixture.NOW.replace(hour=9, minute=0))
        raw = current_sample_plan().model_dump(mode="json")
        raw["ordinary_rules"] = []
        raw["monitoring"] = unified_payload()["monitoring"]
        raw["alert_rules"] = [
            {
                "kind": "RISK_ALERT",
                "rule_id": "official-source-status",
                "condition": {
                    "type": "DAILY_PRICE_COMPARE",
                    "field": "close",
                    "offset": 0,
                    "comparator": "LT",
                    "reference": {
                        "mode": "FIXED",
                        "value": "6200",
                        "unit": "FEN",
                        "as_of": str(fixture.NOW.date()),
                        "source": "Synthetic reviewed official source threshold",
                    },
                },
                "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
            }
        ]
        if correction == "expired_day":
            raw["activation"] = {"mode": "TRADING_DAY", "trading_day": str(clock.now().date())}
        elif correction == "expired_range":
            raw["activation"] = {
                "mode": "DATE_RANGE",
                "start_date": str(clock.now().date()),
                "end_date": str(clock.now().date()),
            }
        plan = UnifiedTradePlan.model_validate(raw)
        seed_current(tmp_path, plan=plan, clock=clock)
        database = tmp_path / "monitor.sqlite3"
        clock.current = fixture.NOW.replace(hour=15, minute=35)
        config = fixture._write_configuration_and_evidence(
            tmp_path, observed_at=clock.now(), include_index=False
        )
        sdk = CurrentCloseSDK(clock, (plan.symbol,), official_closes={clock.now().date(): "55.00"})
        monkeypatch.setattr(
            "trade_plan_monitor.runtime.production.create_tushare_client", lambda _: sdk
        )
        pace = fixture.VirtualPace()
        controller = create_live_tushare_request_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep
        )
        engine, work = fixture._work_factory(database, clock)
        sessions = work()._session_factory
        generation = uuid4()
        pipeline = ProductionMonitorPipeline(
            configuration=load_application_config(config).tushare,
            certification_directory=tmp_path / "data/live-certification",
            stock_certification=create_stock_certification(
                observed_at=clock.now(),
                endpoint_url=fixture.ENDPOINT,
                capabilities=fixture._ready_stock_capabilities(),
                source_time_label=SourceTimeLabel.START,
            ),
            clock=clock,
            request_controller=controller,
            unit_of_work_factory=work,
            runtime_generation=generation,
            publisher=lambda _: None,
            recovery_session_factory=sessions,
            enable_runtime_status=True,
        )
        other, _, _, health = _setup(tmp_path)
        other.dispose()

        def authority():
            token, configuration, plans = pipeline.runtime_status_snapshot()
            observed = clock.now()
            return RuntimeReadAuthority(
                token=token,
                lifecycle="RUNNING",
                health=health,
                configuration_revision=configuration,
                plans=plans,
                progress=ProgressSnapshot(
                    generation,
                    observed,
                    "SCHEDULED",
                    observed,
                    observed + timedelta(seconds=10),
                    observed + timedelta(seconds=30),
                ),
            )

        reader = RuntimeStatusReadService(sessions, authority, clock=clock.now)
        try:
            day = clock.now().date()
            await pipeline.refresh_references(day)
            outcome = await pipeline.daily_evaluations.run_target(
                plan=plan, official_trade_date=day, evaluated_at=clock.now()
            )
            assert not outcome.duplicate
            proof = pipeline.runtime_status_snapshot()[2][0].completion
            assert proof is not None and proof.target == OfficialCloseEvaluationTarget(
                trade_date=day
            )
            writes = []

            def record(_conn, _cursor, sql, _params, _context, _many):
                if sql.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                    writes.append(sql)

            event.listen(engine, "before_cursor_execute", record)
            try:
                row = (await reader.get_dashboard()).symbols[0]
                assert row.availability == "CURRENT" and row.scope.status == "READY"
                assert row.scope.required_target.kind == "OFFICIAL_CLOSE"
                assert row.plan_runtime.alerts[0].outcome == "SATISFIED"
                assert not row.current_actionable
                assert writes == []
            finally:
                event.remove(engine, "before_cursor_execute", record)
            for stale in (
                replace(proof, runtime_generation=uuid4()),
                replace(proof, configuration_revision="obsolete-config"),
                replace(proof, activation_revision=proof.activation_revision + 1),
                replace(proof, plan_version_id=str(uuid4())),
            ):
                pipeline._runtime_status_proofs[plan.symbol] = stale
                assert pipeline.runtime_status_snapshot()[2][0].completion is None
                assert (await reader.get_dashboard()).symbols[0].availability == "CACHED"
            pipeline._runtime_status_proofs[plan.symbol] = proof
            clock.current += timedelta(minutes=1)
            assert (await reader.get_dashboard()).symbols[0].availability == "CURRENT"
            if correction.startswith("expired_"):
                from sqlalchemy import inspect

                def whole_database():
                    with engine.connect() as connection:
                        return {
                            table: tuple(
                                sorted(
                                    repr(tuple(row))
                                    for row in connection.exec_driver_sql(
                                        f'SELECT * FROM "{table}"'
                                    )
                                )
                            )
                            for table in inspect(connection).get_table_names()
                        }

                before = whole_database()
                calls = tuple(sdk.calls)
                clock.current = (clock.current + timedelta(days=1)).replace(hour=10, minute=0)
                # The previous official close is still the latest completed close, but the
                # activation has expired. Reading must not revive or rewrite its proof.
                event.listen(engine, "before_cursor_execute", record)
                try:
                    assert pipeline.runtime_status_snapshot()[2][0].completion is None
                    row = (await reader.get_dashboard()).symbols[0]
                    assert row.availability == "CACHED"
                    assert row.scope.read_only and not row.current_actionable
                    assert row.scope.required_target is None
                    assert row.plan_runtime.alerts[0].outcome == "SATISFIED"
                    await reader.get_symbol(symbol=plan.symbol)
                    await reader.get_symbol_health(symbol=plan.symbol)
                    await reader.get_health()
                    assert whole_database() == before
                    assert tuple(sdk.calls) == calls
                    assert writes == []
                    assert pipeline._runtime_status_proofs[plan.symbol] == proof
                finally:
                    event.remove(engine, "before_cursor_execute", record)
                return
            # Latest applicable official date advances at the next observed completed close.
            clock.current += timedelta(days=1)
            assert pipeline.runtime_status_snapshot()[2][0].completion is None
            assert (await reader.get_dashboard()).symbols[0].availability == "CACHED"
            clock.current -= timedelta(days=1)
            if correction == "source":
                with sessions.begin() as session:
                    head = session.get(DailyRecord, "evaluation-head-" + plan.symbol)
                    changed = json.loads(head.payload_json)
                    changed["daily_evidence"]["bars"][-1].update(
                        open="5600", high="5600", low="5600", close="5600"
                    )
                    head.payload_json = json.dumps(changed)
                assert (await reader.get_dashboard()).symbols[0].availability == "CACHED"
            else:
                inputs = pipeline.daily_evaluations._current_inputs[plan.symbol]
                changed = inputs.model_copy(
                    update={
                        "evaluated_at": clock.now(),
                        "series": None,
                        "data_blockers": ("PRICE_BASIS_UNVERIFIED",),
                    }
                )
                pipeline.daily_evaluations.run_inputs(
                    plan=plan, inputs=changed, expected_activation_revision=1
                )
                assert pipeline._runtime_status_proofs[plan.symbol] is None
                assert (await reader.get_dashboard()).symbols[0].availability == "CACHED"
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("window", ("TRADING_DAY", "DATE_RANGE"))
def test_expired_status_keeps_only_nonalert_locked_risk(current_chain, window):
    from trade_plan_monitor.domain.plan_models import activation_is_eligible_on
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.runtime.status_authority import (
        condition_status_eligible,
        condition_status_target,
    )

    chain = current_chain
    raw = chain.plan.model_dump(mode="json")
    raw["activation"] = (
        {"mode": "TRADING_DAY", "trading_day": str(chain_fixture.FRIDAY)}
        if window == "TRADING_DAY"
        else {
            "mode": "DATE_RANGE",
            "start_date": str(chain_fixture.FRIDAY),
            "end_date": str(chain_fixture.FRIDAY),
        }
    )
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    chain.position()
    chain.evaluate(series=chain.series(), official=chain_fixture.FRIDAY)
    chain.facts()
    chain.now += timedelta(seconds=1)
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        chain.post(
            "plan-facts",
            {
                "planVersionId": chain.version["id"],
                "contentHash": chain.version["contentHash"],
                "factId": "locked-status-" + kind,
                "kind": kind,
                "tradeDate": str(chain_fixture.FRIDAY),
                "evidence": "Synthetic complete official technical evidence independently reviewed",
                "expectedRevision": 0,
            },
        )
    result = chain.evaluate(series=chain.series(), price=3970)
    assert any(r["status"] == "CONFIRMED" for r in result.snapshot["risks"])
    chain.now = chain.now.replace(day=22, hour=10)
    assert not activation_is_eligible_on(chain.plan.activation, chain.now.date())
    with chain.plans._unit_of_work() as work:
        assert condition_status_eligible(work.daily.session, plan=chain.plan, now=chain.now)
        assert (
            condition_status_target(work.daily.session, plan=chain.plan, now=chain.now) is not None
        )
    # The existing risk owner can still evaluate its locked risk after ordinary expiry.
    continued = chain.evaluate(series=chain.series(), price=3970)
    assert any(r["status"] == "CONFIRMED" for r in continued.snapshot["risks"])
    raw["ordinary_rules"] = []
    raw["risk_branches"] = []
    raw["alert_rules"] = [
        {
            "kind": "RISK_ALERT",
            "rule_id": "expired-alert",
            "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000},
            "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        }
    ]
    alert = UnifiedTradePlan.model_validate(raw)
    with chain.plans._unit_of_work() as work:
        assert not condition_status_eligible(work.daily.session, plan=alert, now=chain.now)
        assert condition_status_target(work.daily.session, plan=alert, now=chain.now) is None
