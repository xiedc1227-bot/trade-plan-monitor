"""V2 status reads use real committed SQLite evidence without receipt writes."""

import asyncio
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import event
from test_explicit_runtime_production import NOW, TARGET, _database

from trade_plan_monitor.notifications.recovery_eligibility import RecoveryBarrierEvidence
from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeEvaluationService
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.runtime_status_eligibility import explicit_rule_eligibility


def test_real_explicit_source_expiry_and_cached_reads_never_write(tmp_path):
    engine, plan = _database(tmp_path, "status-eligibility.db")
    sessions = create_session_factory(engine)
    outcome = asyncio.run(
        ExplicitRuntimeEvaluationService(
            lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW),
            recovery_delivery=True,
        ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
    )
    result = outcome.evaluation_result
    generation = uuid4()
    barrier = RecoveryBarrierEvidence(
        symbol=plan.symbol,
        plan_hash=result.plan_hash,
        activation_revision=1,
        runtime_generation=generation,
        target_bucket_end=TARGET,
        reconciled_through=TARGET,
        pending_obligations=0,
        observed_at=NOW,
    )
    writes = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    with sessions() as session, session.begin():
        common = dict(
            session=session, plan=plan, result=result, generation=generation, barrier=barrier
        )
        current = explicit_rule_eligibility(
            **common, now=TARGET + timedelta(seconds=89), current=True
        )
        expired = explicit_rule_eligibility(
            **common, now=TARGET + timedelta(seconds=90), current=True
        )
        cached = explicit_rule_eligibility(**common, now=NOW, current=False)
    assert current[0]["current_actionable"] is True
    assert current[0]["source_alert"]["result_hash"] == result.result_hash
    assert current[0]["actionable_until"] == TARGET + timedelta(seconds=90)
    assert expired[0]["reason_code"] == "INTRADAY_EXPIRED"
    assert cached[0]["reason_code"] == "CACHED_RESULT"
    assert writes == []
    engine.dispose()


def test_real_257_alert_history_keeps_bounded_current_rule_provenance(tmp_path):
    from decimal import Decimal

    import test_explicit_runtime_production as fixture
    from sqlalchemy import func, select

    from trade_plan_monitor.market_data.models import TradingDay
    from trade_plan_monitor.market_data.sessions import expected_minute_ends
    from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database
    from trade_plan_monitor.state.models import AlertEvent

    payload = fixture._plan().model_dump(mode="python")
    payload["activation"] = {
        "mode": "DATE_RANGE", "start_date": fixture.TARGET_DATE,
        "end_date": fixture.TARGET_DATE + timedelta(days=8),
    }
    payload["rules"][0].update(
        condition={"type": "COMPLETED_CLOSE_BELOW", "price_fen": 1200},
        action={"type": "RISK_ALERT"},
        repeat_policy={"mode": "EACH_QUALIFYING_BAR"},
    )
    plan = fixture.ExplicitTradePlan.model_validate(payload)
    engine = create_sqlite_engine(tmp_path / "retained-alert-history.db")
    upgrade_database(engine)
    fixture._seed_active(engine, plan)
    fixture._seed_facts(engine, plan)
    sessions = create_session_factory(engine)
    now = [fixture.NOW]

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: now[0])

    days = tuple(fixture.TARGET_DATE + timedelta(days=i) for i in range(9))
    calendar = []
    for day in days:
        previous = day - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        calendar.append(TradingDay(
            exchange=plan.market, cal_date=day, is_open=day.weekday() < 5,
            previous_trade_date=previous,
        ))
    with work() as transaction:
        transaction.references.upsert_trading_days(tuple(calendar))
        transaction.commit()

    async def scenario():
        runtime = ExplicitRuntimeEvaluationService(work, recovery_delivery=True)
        targets = tuple(
            target for day in days if day.weekday() < 5
            for target in expected_minute_ends(day, is_open=True)
            if target.minute % 5 == 0 and target >= fixture.TARGET
        )
        for target in targets[:257]:
            now[0] = target + timedelta(seconds=2)
            with work() as transaction:
                transaction.history.upsert_five_minute(
                    symbol=plan.symbol, bar_end=target, formula_version="ta-v1",
                    open_fen=990, high_fen=990, low_fen=990, close_fen=990,
                    volume_shares=300, amount_yuan=Decimal("0"),
                )
                transaction.commit()
            outcome = await runtime.run_intraday_and_publish(
                plan=plan, target_bucket_end=target, evaluated_at=now[0],
            )
        result = outcome.evaluation_result
        writes = []

        def record(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                writes.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            with sessions() as session, session.begin():
                assert session.scalar(select(func.count()).select_from(AlertEvent)) == 257
                values = explicit_rule_eligibility(
                    session=session, plan=plan, result=result, generation=uuid4(),
                    barrier=None, now=now[0], current=False,
                )
            assert values[0]["reason_code"] == "CACHED_RESULT"
            assert values[0]["source_alert"]["result_hash"] == result.result_hash
            assert values[0]["source_alert"]["data_cutoff"] == result.target_bucket_end
            assert writes == []
        finally:
            event.remove(engine, "before_cursor_execute", record)

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_old_explicit_risk_source_survives_new_suppressed_result_and_expired_sell(tmp_path):
    from decimal import Decimal

    from test_explicit_runtime_production import _seed_active, _seed_facts, _three_rule_plan

    from trade_plan_monitor.state.database import create_sqlite_engine, upgrade_database

    engine = create_sqlite_engine(tmp_path / "mixed-risk.db")
    upgrade_database(engine)
    plan = _three_rule_plan(overlapping_risk=True)
    payload = plan.model_dump(mode="python")
    payload["rules"][1]["condition"].update(low_fen=980, high_fen=1000)
    plan = type(plan).model_validate(payload)
    _seed_active(engine, plan)
    _seed_facts(engine, plan)
    sessions = create_session_factory(engine)
    clock = [NOW]

    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: clock[0])

    consumed = []
    runtime = ExplicitRuntimeEvaluationService(
        work, recovery_delivery=True,
        committed_result_observer=lambda _plan, _result, inputs: consumed.append(inputs),
    )
    first = asyncio.run(
        runtime.run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
    ).evaluation_result
    next_target = TARGET + timedelta(minutes=5)
    clock[0] = next_target + timedelta(seconds=2)
    with work() as transaction:
        transaction.history.upsert_five_minute(
            symbol=plan.symbol,
            bar_end=next_target,
            formula_version="ta-v1",
            open_fen=990,
            high_fen=990,
            low_fen=990,
            close_fen=990,
            volume_shares=300,
            amount_yuan=Decimal("0"),
        )
        transaction.commit()
    second = asyncio.run(
        runtime.run_intraday_and_publish(
            plan=plan, target_bucket_end=next_target, evaluated_at=clock[0]
        )
    ).evaluation_result
    generation = uuid4()
    from trade_plan_monitor.runtime.status_authority import capture_completion_proof

    with sessions() as session, session.begin():
        common = dict(session=session, plan=plan, result=second,
                      runtime_generation=generation, configuration_revision="installed",
                      now=clock[0])
        assert capture_completion_proof(**common, consumed_inputs=consumed[-1]) is not None
        risk_id = next(
            item.rule_id for item in second.rule_results if item.action.type == "RISK_ALERT"
        )
        altered = consumed[-1].model_copy(update={
            "rule_states": tuple(
                item.model_copy(update={"revision": 0, "has_emitted": False,
                                        "last_emitted_bucket_end": None})
                if item.rule_id == risk_id else item
                for item in consumed[-1].rule_states
            )
        })
        assert capture_completion_proof(**common, consumed_inputs=altered) is None
    barrier = RecoveryBarrierEvidence(
        symbol=plan.symbol,
        plan_hash=second.plan_hash,
        activation_revision=1,
        runtime_generation=generation,
        target_bucket_end=next_target,
        reconciled_through=next_target,
        pending_obligations=0,
        observed_at=clock[0],
    )
    with sessions() as session, session.begin():
        values = explicit_rule_eligibility(
            session=session,
            plan=plan,
            result=second,
            generation=generation,
            barrier=barrier,
            now=next_target + timedelta(seconds=90),
            current=True,
        )
    risk = next(item for item in values if item["action"] == "RISK_ALERT")
    sell = next(item for item in values if item["action"] == "SELL")
    assert risk["current_actionable"] is True
    assert risk["actionable_until"] is None
    assert risk["source_alert"]["result_hash"] == first.result_hash
    assert risk["source_alert"]["evaluated_at"] == first.evaluated_at
    assert risk["source_alert"]["data_cutoff"] == TARGET
    assert first.result_hash != second.result_hash
    assert sell["reason_code"] == "INTRADAY_EXPIRED"
    engine.dispose()


def test_owner_replacement_retries_once_and_unreadable_authority_is_not_absence(tmp_path):
    import pytest
    from test_persistent_monitor_read_service import _NOW, _setup

    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    engine, _, _, health = _setup(tmp_path)
    calls = []

    def authority():
        calls.append(len(calls))
        return RuntimeReadAuthority(
            token=len(calls), lifecycle="STOPPED", progress=None, health=health, owner_absent=True
        )

    service = RuntimeStatusReadService(
        create_session_factory(engine), authority, clock=lambda: _NOW
    )
    with pytest.raises(ApiError) as failure:
        asyncio.run(service.get_dashboard())
    assert failure.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
    assert len(calls) == 4
    service = RuntimeStatusReadService(
        create_session_factory(engine), lambda: None, clock=lambda: _NOW
    )
    with pytest.raises(ApiError) as failure:
        asyncio.run(service.get_dashboard())
    assert failure.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
    engine.dispose()


def test_real_explicit_proof_is_invalidated_by_current_inventory_change(tmp_path):
    from test_persistent_monitor_read_service import _setup

    from trade_plan_monitor.runtime.progress import ProgressSnapshot
    from trade_plan_monitor.runtime.status_authority import (
        PlanReadAuthority,
        RuntimeReadAuthority,
        capture_completion_proof,
    )
    from trade_plan_monitor.state.models import PositionInventoryConfirmation
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    engine, plan = _database(tmp_path, "complete-proof.db")
    sessions = create_session_factory(engine)
    result = asyncio.run(
        ExplicitRuntimeEvaluationService(
            lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW),
            recovery_delivery=True,
        ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
    ).evaluation_result
    generation = uuid4()
    with sessions() as session, session.begin():
        proof = capture_completion_proof(
            session,
            plan=plan,
            result=result,
            runtime_generation=generation,
            configuration_revision="configuration-1",
            now=NOW,
        )
    assert proof is not None
    other, _, _, health = _setup(tmp_path)
    other.dispose()
    plan_authority = PlanReadAuthority(
        symbol=plan.symbol,
        plan_version_id=proof.plan_version_id,
        plan_hash=result.plan_hash,
        activation_revision=1,
        plan_family="EXPLICIT_RULES",
        target=proof.target,
        completion=proof,
        evaluation_due=True,
    )
    progress = ProgressSnapshot(
        generation, NOW, "SCHEDULED", NOW, NOW + timedelta(seconds=10), NOW + timedelta(seconds=30)
    )
    authority = RuntimeReadAuthority(
        token="owner",
        lifecycle="RUNNING",
        progress=progress,
        health=health,
        configuration_revision="configuration-1",
        plans=(plan_authority,),
    )
    service = RuntimeStatusReadService(sessions, lambda: authority, clock=lambda: NOW)
    row = asyncio.run(service.get_dashboard()).symbols[0]
    assert row.availability == "CURRENT"
    assert row.scope.status == "READY"
    assert row.scope.read_only is False
    assert row.current_actionable is True
    with sessions.begin() as session:
        session.delete(session.get(PositionInventoryConfirmation, plan.symbol))
    invalidated = asyncio.run(service.get_dashboard()).symbols[0]
    assert invalidated.availability == "CACHED"
    assert invalidated.scope.read_only is True
    assert invalidated.current_actionable is False
    engine.dispose()


def test_real_offline_pipeline_publishes_status_proof_only_after_new_commit(tmp_path, monkeypatch):
    import test_explicit_runtime_production as fixture

    from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    original = ProductionMonitorPipeline

    def status_pipeline(**kwargs):
        kwargs["enable_runtime_status"] = True
        kwargs["recovery_session_factory"] = kwargs["unit_of_work_factory"]()._session_factory
        return original(**kwargs)

    monkeypatch.setattr(fixture, "ProductionMonitorPipeline", status_pipeline)

    async def scenario():
        engine, _, _, _, build, controller, pipeline, _ = fixture._pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300
        )
        try:
            await pipeline.refresh_references(TARGET.date())
            deadline = MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE,
                trade_date=TARGET.date(),
                due_at=fixture.PIPELINE_NOW,
                bar_end=TARGET,
            )
            await pipeline.run_deadline(deadline)
            token, _, plans = pipeline.runtime_status_snapshot()
            assert len(plans) == 1
            assert plans[0].completion is not None
            assert plans[0].completion.runtime_generation == token[0]
            await pipeline.run_deadline(deadline)
            assert pipeline.runtime_status_snapshot()[0] == token
            another_controller, restarted, _ = build()
            try:
                await restarted.refresh_references(TARGET.date())
                await restarted.run_deadline(deadline)
                assert restarted.runtime_status_snapshot()[2][0].completion is None
            finally:
                await another_controller.aclose()
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_real_legacy_pipeline_proof_does_not_depend_on_optional_index(tmp_path, monkeypatch):
    import test_live_pipeline_acceptance as fixture
    from test_persistent_monitor_read_service import _setup

    from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
    from trade_plan_monitor.runtime.progress import ProgressSnapshot
    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.runtime_status_read_service import (
        RuntimeStatusReadService,
        build_dependency_scopes,
    )

    proofs = []
    projections = []
    other, _, _, health = _setup(tmp_path)
    other.dispose()

    class StatusPipeline(ProductionMonitorPipeline):
        def __init__(self, **kwargs):
            kwargs["enable_runtime_status"] = True
            kwargs["recovery_session_factory"] = kwargs["unit_of_work_factory"]()._session_factory
            super().__init__(**kwargs)
            from trade_plan_monitor.domain.plan_hash import plan_sha256
            from trade_plan_monitor.state.repositories import ManualEventRiskStatus

            with SqlAlchemyUnitOfWork(
                kwargs["recovery_session_factory"],
                clock=lambda: fixture.INDEX_CUTOFF - timedelta(seconds=1),
            ) as work:
                for plan in self.active_plans():
                    work.manual_event_risk.upsert(
                        symbol=plan.symbol,
                        plan_hash=plan_sha256(plan),
                        status=ManualEventRiskStatus.CLEAR,
                        expires_on=fixture.INDEX_CUTOFF.date(),
                        expected_revision=0,
                    )
                work.commit()

        def _observe_status_commit(self, plan, result, consumed_inputs):
            super()._observe_status_commit(plan, result, consumed_inputs)
            proofs.append(self._runtime_status_proofs[plan.symbol])
            token, configuration, plans = self.runtime_status_snapshot()
            now = self._clock.now()
            authority = RuntimeReadAuthority(
                token=token, lifecycle="RUNNING", health=health,
                configuration_revision=configuration, plans=plans,
                dependencies=build_dependency_scopes(self.runtime_status_dependencies_snapshot()),
                progress=ProgressSnapshot(self._runtime_generation, now, "SCHEDULED", now,
                                          now + timedelta(seconds=10), now + timedelta(seconds=30)),
            )
            writes = []

            def record(_conn, _cursor, statement, _params, _context, _many):
                if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                    writes.append(statement)

            engine = self._runtime_status_sessions.kw["bind"]
            event.listen(engine, "before_cursor_execute", record)
            try:
                reader = RuntimeStatusReadService(
                    self._runtime_status_sessions, lambda: authority, clock=lambda: now
                )
                dashboard = reader._assemble(authority, now)[0][0]
                projections.append(dashboard.symbols[0])
                assert writes == []
            finally:
                event.remove(engine, "before_cursor_execute", record)

    monkeypatch.setattr(fixture, "ProductionMonitorPipeline", StatusPipeline)
    fixture.test_optional_index_failure_does_not_change_stock_only_plan_evaluation(
        tmp_path, monkeypatch
    )
    assert len(proofs) == 2
    assert all(proof is not None for proof in proofs)
    assert all(proof.plan_family == "LEGACY_LOW_BUY" for proof in proofs)
    assert all(row.availability == "CURRENT" for row in projections)
    assert all(row.scope.status == "READY" for row in projections)


def test_missing_legacy_result_is_local_and_known_inactive_has_no_fake_identity(tmp_path):
    from test_persistent_monitor_read_service import _NOW, _seed_plan, _setup

    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    engine, work, _, health = _setup(tmp_path)
    _seed_plan(work, active=True)
    authority = RuntimeReadAuthority(
        token="absent", lifecycle="STOPPED", progress=None, health=health, owner_absent=True
    )
    service = RuntimeStatusReadService(
        create_session_factory(engine), lambda: authority, clock=lambda: _NOW
    )
    dashboard = asyncio.run(service.get_dashboard())
    assert dashboard.symbols[0].availability == "UNAVAILABLE"
    assert dashboard.symbols[0].current_actionable is False
    assert dashboard.runtime_generation is None
    assert dashboard.counts.actionable == 0
    assert dashboard.symbols[0].scope in dashboard.runtime_status.scopes
    engine.dispose()


def test_real_both_families_cached_legacy_and_waiting_explicit_coexist(tmp_path):
    from test_explicit_runtime_production import _plan, _seed_active
    from test_persistent_monitor_read_service import _seed_claim, _seed_plan, _setup

    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    engine, work, _, health = _setup(tmp_path)
    _seed_plan(work, active=True)
    result = _seed_claim(work, complete=True)
    explicit = _plan().model_copy(update={"symbol": "600000.SH", "market": "SSE"})
    _seed_active(engine, explicit)
    authority = RuntimeReadAuthority(
        token="absent", lifecycle="STOPPED", progress=None, health=health, owner_absent=True
    )
    service = RuntimeStatusReadService(
        create_session_factory(engine), lambda: authority, clock=lambda: NOW
    )
    dashboard = asyncio.run(service.get_dashboard())
    legacy, waiting = dashboard.symbols
    assert legacy.availability == "CACHED"
    assert legacy.decision.result_hash == result.result_hash
    assert legacy.decision.evaluated_at == result.snapshot.evaluated_at
    assert waiting.availability == "UNAVAILABLE"
    assert waiting.plan_family == "EXPLICIT_RULES"
    assert dashboard.counts.stale == 1
    assert len(dashboard.runtime_status.scopes) == 2
    details = asyncio.run(service.get_symbol(symbol=legacy.symbol))
    assert details.legacy_details is not None
    assert asyncio.run(service.get_explicit_plan_runtime(symbol=legacy.symbol)) is None
    assert asyncio.run(service.get_symbol_health(symbol=waiting.symbol)).scope == waiting.scope
    assert asyncio.run(service.list_symbols(offset=1, limit=1)).items == (waiting,)
    assert asyncio.run(service.get_health()).runtime_status == dashboard.runtime_status
    engine.dispose()


def test_explicit_cached_projection_uses_original_runtime_and_preserves_result(tmp_path):
    from test_persistent_monitor_read_service import _setup

    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    engine, plan = _database(tmp_path, "explicit-cached.db")
    sessions = create_session_factory(engine)
    outcome = asyncio.run(
        ExplicitRuntimeEvaluationService(
            lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW),
            recovery_delivery=True,
        ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
    )
    other, _, _, health = _setup(tmp_path)
    other.dispose()
    authority = RuntimeReadAuthority(
        token="absent", lifecycle="STOPPED", progress=None, health=health, owner_absent=True
    )
    service = RuntimeStatusReadService(sessions, lambda: authority, clock=lambda: NOW)
    dashboard = asyncio.run(service.get_dashboard())
    row = dashboard.symbols[0]
    assert row.availability == "CACHED"
    assert row.result_hash == outcome.evaluation_result.result_hash
    assert row.explicit_runtime.target_bucket_end == TARGET
    assert row.rule_eligibility[0].source_alert.result_hash == row.result_hash
    assert row.rule_eligibility[0].reason_code == "CACHED_RESULT"
    assert row.actionable_rule_ids == ()
    engine.dispose()


def test_completion_proof_rejects_different_consumed_inventory(tmp_path):
    from trade_plan_monitor.runtime.status_authority import capture_completion_proof

    engine, plan = _database(tmp_path, "consumed-inventory.db")
    sessions = create_session_factory(engine)
    captured = []
    service = ExplicitRuntimeEvaluationService(
        lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW),
        committed_result_observer=lambda _plan, _result, inputs: captured.append(inputs),
    )
    result = service.run_intraday(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
    inputs = captured[0]
    changed = inputs.model_copy(update={
        "inventory": inputs.inventory.model_copy(update={"total_qty": 200})
    })
    with sessions() as session, session.begin():
        common = dict(session=session, plan=plan, result=result.evaluation_result,
                      runtime_generation=uuid4(), configuration_revision="installed", now=NOW)
        assert capture_completion_proof(**common, consumed_inputs=inputs) is not None
        assert capture_completion_proof(**common, consumed_inputs=changed) is None
        from types import SimpleNamespace

        from trade_plan_monitor.decision.explicit_rules import ExplicitRuleStateSnapshot

        prior_inputs = inputs.model_dump(mode="python", exclude={"rule_states"})
        wrong_state = SimpleNamespace(**prior_inputs, rule_states=(
            ExplicitRuleStateSnapshot(
                rule_id=result.evaluation_result.rule_results[0].rule_id,
                activation_revision=1, revision=1,
                has_emitted=True, last_emitted_bucket_end=TARGET,
            ),
        ))
        # A first emission consumed no prior emitted state. Its post-commit row
        # cannot be substituted as though the evaluator had consumed it.
        wrong_state.inventory = inputs.inventory
        wrong_state.bars = inputs.bars
        wrong_state.trading_calendar = inputs.trading_calendar
        assert capture_completion_proof(**common, consumed_inputs=wrong_state) is None
    engine.dispose()


def test_future_delivery_receipt_is_storage_failure_even_for_cached_read(tmp_path):
    import pytest

    from trade_plan_monitor.state.models import AlertDeliveryEligibility
    from trade_plan_monitor.state.projections import ProjectionError

    engine, plan = _database(tmp_path, "future-receipt.db")
    sessions = create_session_factory(engine)
    outcome = asyncio.run(ExplicitRuntimeEvaluationService(
        lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW), recovery_delivery=True,
    ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW))
    with sessions.begin() as session:
        receipt = session.get(AlertDeliveryEligibility, str(outcome.committed_events[0].event_id))
        receipt.updated_at = (NOW + timedelta(seconds=1)).isoformat()
    with sessions() as session, session.begin(), pytest.raises(ProjectionError):
        explicit_rule_eligibility(session=session, plan=plan, result=outcome.evaluation_result,
                                  generation=uuid4(), barrier=None, now=NOW, current=False)
    engine.dispose()


def test_expired_suppressed_receipt_preserves_intraday_expired_reason(tmp_path):
    from trade_plan_monitor.state.models import AlertDeliveryEligibility

    engine, plan = _database(tmp_path, "suppressed-expiry.db")
    sessions = create_session_factory(engine)
    outcome = asyncio.run(ExplicitRuntimeEvaluationService(
        lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW), recovery_delivery=True,
    ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW))
    observed = TARGET + timedelta(seconds=90)
    with sessions.begin() as session:
        row = session.get(AlertDeliveryEligibility, str(outcome.committed_events[0].event_id))
        row.status = "SUPPRESS"
        row.reason = "SOURCE_EXPIRED"
        row.updated_at = observed.isoformat()
    with sessions() as session, session.begin():
        value = explicit_rule_eligibility(
            session=session, plan=plan, result=outcome.evaluation_result,
            generation=uuid4(), barrier=None, now=observed, current=True,
        )[0]
    assert value["reason_code"] == "INTRADAY_EXPIRED"
    assert value["current_actionable"] is False
    engine.dispose()


def test_config_generation_and_block_reason_invalidate_proof_without_any_read_writes(tmp_path):
    from dataclasses import replace

    from test_persistent_monitor_read_service import _setup

    from trade_plan_monitor.runtime.progress import ProgressSnapshot
    from trade_plan_monitor.runtime.status_authority import (
        PlanReadAuthority,
        RuntimeReadAuthority,
        capture_completion_proof,
    )
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    engine, plan = _database(tmp_path, "authority-invalidation.db")
    sessions = create_session_factory(engine)
    result = ExplicitRuntimeEvaluationService(
        lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW), recovery_delivery=True,
    ).run_intraday(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW).evaluation_result
    generation = uuid4()
    with sessions() as session, session.begin():
        proof = capture_completion_proof(
            session, plan=plan, result=result, runtime_generation=generation,
            configuration_revision="installed", now=NOW,
        )
    assert proof is not None
    other, _, _, health = _setup(tmp_path)
    other.dispose()
    owner = RuntimeReadAuthority(
        token="owner", lifecycle="RUNNING", health=health,
        progress=ProgressSnapshot(generation, NOW, "SCHEDULED", NOW,
                                  NOW + timedelta(seconds=10), NOW + timedelta(seconds=30)),
        configuration_revision="installed",
        plans=(PlanReadAuthority(
            symbol=plan.symbol, plan_version_id=proof.plan_version_id, plan_hash=result.plan_hash,
            activation_revision=1, plan_family="EXPLICIT_RULES", target=proof.target,
            completion=proof, evaluation_due=True,
        ),),
    )
    current = [owner]
    service = RuntimeStatusReadService(sessions, lambda: current[0], clock=lambda: NOW)
    writes = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    assert asyncio.run(service.get_dashboard()).symbols[0].availability == "CURRENT"
    from trade_plan_monitor.web.runtime_status_websocket import RuntimeStatusEventStream

    stream = RuntimeStatusEventStream(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW),
        read_service=service,
    )
    first = asyncio.run(stream._current_heartbeat_frame(7))
    second = asyncio.run(stream._current_heartbeat_frame(7))
    assert first == second
    assert first["sequence"] == 7
    assert first["runtimeStatus"]["lastProgressAt"] == NOW.isoformat(timespec="microseconds")
    for changed in (
        replace(owner, configuration_revision="replacement"),
        replace(owner, progress=replace(owner.progress, runtime_generation=uuid4())),
        replace(owner, block_reason="NEEDS_RESTART"),
    ):
        current[0] = changed
        dashboard = asyncio.run(service.get_dashboard())
        assert dashboard.symbols[0].availability == "CACHED"
        assert dashboard.symbols[0].current_actionable is False
        assert dashboard.symbols[0].scope.read_only is True
        assert asyncio.run(service.get_health()).runtime_status == dashboard.runtime_status
        assert asyncio.run(service.get_symbol(symbol=plan.symbol)).summary == dashboard.symbols[0]
        assert asyncio.run(service.get_symbol_health(symbol=plan.symbol)).scope.read_only is True
        assert asyncio.run(service.list_symbols(offset=0, limit=1)).items == dashboard.symbols
        assert asyncio.run(service.get_explicit_plan_runtime(symbol=plan.symbol)).summary == (
            dashboard.symbols[0]
        )
    assert dashboard.runtime_status.mode == "BLOCKED"
    assert dashboard.runtime_status.reason_code == "NEEDS_RESTART"
    assert writes == []
    current[0] = owner
    from trade_plan_monitor.state.models import TradingCalendar

    with sessions.begin() as session:
        session.get(TradingCalendar, (plan.market, TARGET.date())).is_open = False
    unavailable = asyncio.run(service.get_dashboard()).symbols[0]
    assert unavailable.availability == "CACHED"
    assert unavailable.scope.status == "WAITING"
    assert unavailable.current_actionable is False
    with sessions.begin() as session:
        session.get(TradingCalendar, (plan.market, TARGET.date())).is_open = True
    assert asyncio.run(service.get_dashboard()).symbols[0].availability == "CURRENT"

    from trade_plan_monitor.state.models import PlanActivationState
    from trade_plan_monitor.web.errors import ApiError, ApiErrorCode

    with sessions.begin() as session:
        session.get(PlanActivationState, plan.symbol).revision += 1
    import pytest

    with pytest.raises(ApiError) as error:
        asyncio.run(service.get_dashboard())
    assert error.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
    engine.dispose()


def test_unchanged_bar_and_event_reads_reuse_existing_committed_reader(tmp_path):
    from test_persistent_monitor_read_service import _NOW, _seed_plan, _setup

    from trade_plan_monitor.web.routers.symbols import BarInterval
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    engine, _, legacy, _ = _setup(tmp_path)
    sessions = create_session_factory(engine)
    def work():
        return SqlAlchemyUnitOfWork(sessions, clock=lambda: _NOW)
    _seed_plan(work, active=True)
    service = RuntimeStatusReadService(
        sessions, lambda: None, clock=lambda: _NOW, legacy_read_service=legacy
    )
    kwargs = dict(symbol="003043.SZ", start_at=_NOW - timedelta(days=1), end_at=_NOW,
                  offset=0, limit=20)
    bars = asyncio.run(service.list_symbol_bars(**kwargs, interval=BarInterval.FIVE_MINUTES))
    assert bars is not None
    assert bars == (
        asyncio.run(legacy.list_symbol_bars(**kwargs, interval=BarInterval.FIVE_MINUTES))
    )
    assert asyncio.run(service.list_symbol_events(**kwargs)) == (
        asyncio.run(legacy.list_symbol_events(**kwargs))
    )
    engine.dispose()
