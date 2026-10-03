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
        "mode": "DATE_RANGE",
        "start_date": fixture.TARGET_DATE,
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
        calendar.append(
            TradingDay(
                exchange=plan.market,
                cal_date=day,
                is_open=day.weekday() < 5,
                previous_trade_date=previous,
            )
        )
    with work() as transaction:
        transaction.references.upsert_trading_days(tuple(calendar))
        transaction.commit()

    async def scenario():
        runtime = ExplicitRuntimeEvaluationService(work, recovery_delivery=True)
        targets = tuple(
            target
            for day in days
            if day.weekday() < 5
            for target in expected_minute_ends(day, is_open=True)
            if target.minute % 5 == 0 and target >= fixture.TARGET
        )
        for target in targets[:257]:
            now[0] = target + timedelta(seconds=2)
            with work() as transaction:
                transaction.history.upsert_five_minute(
                    symbol=plan.symbol,
                    bar_end=target,
                    formula_version="ta-v1",
                    open_fen=990,
                    high_fen=990,
                    low_fen=990,
                    close_fen=990,
                    volume_shares=300,
                    amount_yuan=Decimal("0"),
                )
                transaction.commit()
            outcome = await runtime.run_intraday_and_publish(
                plan=plan,
                target_bucket_end=target,
                evaluated_at=now[0],
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
                    session=session,
                    plan=plan,
                    result=result,
                    generation=uuid4(),
                    barrier=None,
                    now=now[0],
                    current=False,
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
        work,
        recovery_delivery=True,
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
        common = dict(
            session=session,
            plan=plan,
            result=second,
            runtime_generation=generation,
            configuration_revision="installed",
            now=clock[0],
        )
        assert capture_completion_proof(**common, consumed_inputs=consumed[-1]) is not None
        risk_id = next(
            item.rule_id for item in second.rule_results if item.action.type == "RISK_ALERT"
        )
        altered = consumed[-1].model_copy(
            update={
                "rule_states": tuple(
                    item.model_copy(
                        update={
                            "revision": 0,
                            "has_emitted": False,
                            "last_emitted_bucket_end": None,
                        }
                    )
                    if item.rule_id == risk_id
                    else item
                    for item in consumed[-1].rule_states
                )
            }
        )
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


def test_real_current_proof_is_invalidated_by_current_inventory_change(tmp_path, monkeypatch):
    from trade_plan_monitor.state.daily_models import DailyRecord

    env = _current_status(tmp_path, monkeypatch)
    try:
        row = asyncio.run(env.reader.get_dashboard()).symbols[0]
        assert row.availability == "CURRENT" and row.scope.status == "READY"
        assert row.scope.read_only is False and row.current_actionable is True
        with env.sessions.begin() as session:
            session.delete(session.get(DailyRecord, "simulation-position-" + env.plan.symbol))
        invalidated = asyncio.run(env.reader.get_dashboard()).symbols[0]
        assert invalidated.availability == "CACHED" and invalidated.scope.read_only is True
        assert invalidated.current_actionable is False
    finally:
        env.close()


def test_real_offline_pipeline_publishes_status_proof_only_after_new_commit(tmp_path, monkeypatch):
    env = _current_status(tmp_path, monkeypatch)

    async def scenario():
        try:
            token, _, plans = env.pipeline.runtime_status_snapshot()
            assert len(plans) == 1 and plans[0].completion is not None
            assert plans[0].completion.runtime_generation == token[0]
            await env.pipeline.run_deadline(env.deadline)
            assert env.pipeline.runtime_status_snapshot()[0] == token
            controller, restarted, _ = env.build()
            try:
                await restarted.refresh_references(TARGET.date())
                await restarted.run_deadline(env.deadline)
                assert restarted.runtime_status_snapshot()[2][0].completion is None
            finally:
                await controller.aclose()
        finally:
            env.engine.dispose()
            await env.controller.aclose()

    asyncio.run(scenario())


def test_real_current_pipeline_proof_does_not_depend_on_optional_index(tmp_path, monkeypatch):
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

        def _observe_status_commit(self, plan, result, consumed_inputs):
            super()._observe_status_commit(plan, result, consumed_inputs)
            proofs.append(self._runtime_status_proofs[plan.symbol])
            token, configuration, plans = self.runtime_status_snapshot()
            now = self._clock.now()
            authority = RuntimeReadAuthority(
                token=token,
                lifecycle="RUNNING",
                health=health,
                configuration_revision=configuration,
                plans=plans,
                dependencies=build_dependency_scopes(self.runtime_status_dependencies_snapshot()),
                progress=ProgressSnapshot(
                    self._runtime_generation,
                    now,
                    "SCHEDULED",
                    now,
                    now + timedelta(seconds=10),
                    now + timedelta(seconds=30),
                ),
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
    assert all(proof.plan_family == "CONDITION_PLAN" for proof in proofs)
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


def test_frozen_history_and_reviewed_current_waiting_plan_coexist(tmp_path):
    from test_explicit_runtime_production import _plan, _seed_active
    from test_persistent_monitor_read_service import _seed_claim, _seed_plan, _setup
    from tests.integration.current_activation_fixture import current_sample_plan
    from tests.integration.test_daily_plan_chain import Chain

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    engine, work, legacy_reader, health = _setup(tmp_path)
    _seed_plan(work, active=True)
    result = _seed_claim(work, complete=True)
    frozen = _plan().model_copy(update={"symbol": "600000.SH", "market": "SSE"})
    _seed_active(engine, frozen)
    chain = Chain(tmp_path)
    raw = current_sample_plan().model_dump(mode="json")
    raw.update(plan_id="current-waiting", symbol="300001.SZ")
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.now = NOW - timedelta(minutes=30)
    chain.plans = PersistentPlanWebLifecycle(
        database_path=tmp_path / "monitor.db", clock=lambda: chain.now
    )
    with chain.client:
        chain.activate()
    authority = RuntimeReadAuthority(
        token="absent", lifecycle="STOPPED", progress=None, health=health, owner_absent=True
    )
    service = RuntimeStatusReadService(
        create_session_factory(engine), lambda: authority, clock=lambda: NOW
    )
    dashboard = asyncio.run(service.get_dashboard())
    historical = [row for row in dashboard.symbols if row.plan_family != "CONDITION_PLAN"]
    waiting = next(row for row in dashboard.symbols if row.plan_family == "CONDITION_PLAN")
    assert len(historical) == 2
    assert all(
        row.availability == "UNAVAILABLE"
        and row.reason_code == "LEGACY_PLANS_REQUIRE_REVIEW"
        and not row.current_actionable
        and row.scope.read_only
        for row in historical
    )
    assert (
        waiting.availability == "UNAVAILABLE" and waiting.reason_code == "AWAITING_FIRST_EVALUATION"
    )
    assert len(dashboard.runtime_status.scopes) == 3
    # Frozen history remains readable through its retained history reader without current authority.
    with work() as transaction:
        retained = transaction.projections.get_decision_head(result.snapshot.symbol)
        assert retained.result.result_hash == result.result_hash
        assert retained.result.snapshot.evaluated_at == result.snapshot.evaluated_at
    assert asyncio.run(legacy_reader.get_dashboard()).availability == "UNAVAILABLE"
    assert asyncio.run(service.get_symbol_health(symbol=waiting.symbol)).scope == waiting.scope
    assert asyncio.run(service.get_health()).runtime_status == dashboard.runtime_status
    engine.dispose()


def test_current_cached_projection_preserves_committed_runtime_and_source(tmp_path, monkeypatch):
    from dataclasses import replace

    env = _current_status(tmp_path, monkeypatch)
    try:
        env.current[0] = replace(
            env.current[0],
            token="absent",
            lifecycle="STOPPED",
            progress=None,
            plans=(),
            owner_absent=True,
        )
        row = asyncio.run(env.reader.get_dashboard()).symbols[0]
        assert row.availability == "CACHED" and row.plan_family == "CONDITION_PLAN"
        assert row.plan_runtime.plan_hash == env.plan_hash
        assert row.plan_runtime.minute_target == TARGET
        assert row.plan_runtime.minute_prefix[-1].bar_end == TARGET
        assert row.plan_runtime.signals[0].executable_qty == 100
        assert row.current_actionable is False and row.scope.read_only is True
        assert row.plan_runtime.review_id == env.result.snapshot["review_id"]
    finally:
        env.close()


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
    changed = inputs.model_copy(
        update={"inventory": inputs.inventory.model_copy(update={"total_qty": 200})}
    )
    with sessions() as session, session.begin():
        common = dict(
            session=session,
            plan=plan,
            result=result.evaluation_result,
            runtime_generation=uuid4(),
            configuration_revision="installed",
            now=NOW,
        )
        assert capture_completion_proof(**common, consumed_inputs=inputs) is not None
        assert capture_completion_proof(**common, consumed_inputs=changed) is None
        from types import SimpleNamespace

        from trade_plan_monitor.decision.explicit_rules import ExplicitRuleStateSnapshot

        prior_inputs = inputs.model_dump(mode="python", exclude={"rule_states"})
        wrong_state = SimpleNamespace(
            **prior_inputs,
            rule_states=(
                ExplicitRuleStateSnapshot(
                    rule_id=result.evaluation_result.rule_results[0].rule_id,
                    activation_revision=1,
                    revision=1,
                    has_emitted=True,
                    last_emitted_bucket_end=TARGET,
                ),
            ),
        )
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
    outcome = asyncio.run(
        ExplicitRuntimeEvaluationService(
            lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW),
            recovery_delivery=True,
        ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
    )
    with sessions.begin() as session:
        receipt = session.get(AlertDeliveryEligibility, str(outcome.committed_events[0].event_id))
        receipt.updated_at = (NOW + timedelta(seconds=1)).isoformat()
    with sessions() as session, session.begin(), pytest.raises(ProjectionError):
        explicit_rule_eligibility(
            session=session,
            plan=plan,
            result=outcome.evaluation_result,
            generation=uuid4(),
            barrier=None,
            now=NOW,
            current=False,
        )
    engine.dispose()


def test_expired_suppressed_receipt_preserves_intraday_expired_reason(tmp_path):
    from trade_plan_monitor.state.models import AlertDeliveryEligibility

    engine, plan = _database(tmp_path, "suppressed-expiry.db")
    sessions = create_session_factory(engine)
    outcome = asyncio.run(
        ExplicitRuntimeEvaluationService(
            lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: NOW),
            recovery_delivery=True,
        ).run_intraday_and_publish(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
    )
    observed = TARGET + timedelta(seconds=90)
    with sessions.begin() as session:
        row = session.get(AlertDeliveryEligibility, str(outcome.committed_events[0].event_id))
        row.status = "SUPPRESS"
        row.reason = "SOURCE_EXPIRED"
        row.updated_at = observed.isoformat()
    with sessions() as session, session.begin():
        value = explicit_rule_eligibility(
            session=session,
            plan=plan,
            result=outcome.evaluation_result,
            generation=uuid4(),
            barrier=None,
            now=observed,
            current=True,
        )[0]
    assert value["reason_code"] == "INTRADAY_EXPIRED"
    assert value["current_actionable"] is False
    engine.dispose()


def test_config_generation_and_block_reason_invalidate_proof_without_any_read_writes(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    import pytest

    from trade_plan_monitor.state.models import PlanActivationState, TradingCalendar
    from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
    from trade_plan_monitor.web.runtime_status_websocket import RuntimeStatusEventStream

    env = _current_status(tmp_path, monkeypatch)
    owner = env.current[0]
    writes = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(env.engine, "before_cursor_execute", record)
    try:
        assert asyncio.run(env.reader.get_dashboard()).symbols[0].availability == "CURRENT"
        stream = RuntimeStatusEventStream(unit_of_work_factory=env.work, read_service=env.reader)
        first = asyncio.run(stream._current_heartbeat_frame(7))
        assert first == asyncio.run(stream._current_heartbeat_frame(7))
        assert first["sequence"] == 7
        assert first["runtimeStatus"]["lastProgressAt"] == env.now.isoformat(
            timespec="microseconds"
        )
        for changed in (
            replace(owner, configuration_revision="replacement"),
            replace(owner, progress=replace(owner.progress, runtime_generation=uuid4())),
            replace(owner, block_reason="NEEDS_RESTART"),
        ):
            env.current[0] = changed
            dashboard = asyncio.run(env.reader.get_dashboard())
            row = dashboard.symbols[0]
            assert (
                row.availability == "CACHED" and not row.current_actionable and row.scope.read_only
            )
            assert asyncio.run(env.reader.get_health()).runtime_status == dashboard.runtime_status
            assert asyncio.run(env.reader.get_symbol(symbol=env.plan.symbol)).summary == row
            assert asyncio.run(env.reader.get_symbol_health(symbol=env.plan.symbol)).scope.read_only
            assert (
                asyncio.run(env.reader.list_symbols(offset=0, limit=1)).items == dashboard.symbols
            )
            assert asyncio.run(env.reader.get_explicit_plan_runtime(symbol=env.plan.symbol)) is None
        assert dashboard.runtime_status.mode == "BLOCKED"
        assert dashboard.runtime_status.reason_code == "NEEDS_RESTART"
        assert writes == []
    finally:
        event.remove(env.engine, "before_cursor_execute", record)
    env.current[0] = owner
    with env.sessions.begin() as session:
        session.get(TradingCalendar, (env.plan.market, TARGET.date())).is_open = False
    unavailable = asyncio.run(env.reader.get_dashboard()).symbols[0]
    assert unavailable.availability == "CACHED" and not unavailable.current_actionable
    assert unavailable.scope.status == "WAITING"
    with env.sessions.begin() as session:
        session.get(TradingCalendar, (env.plan.market, TARGET.date())).is_open = True
    assert asyncio.run(env.reader.get_dashboard()).symbols[0].availability == "CURRENT"
    with env.sessions.begin() as session:
        session.get(PlanActivationState, env.plan.symbol).revision += 1
    with pytest.raises(ApiError) as error:
        asyncio.run(env.reader.get_dashboard())
    assert error.value.code is ApiErrorCode.SERVICE_UNAVAILABLE
    env.close()


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
    kwargs = dict(
        symbol="003043.SZ", start_at=_NOW - timedelta(days=1), end_at=_NOW, offset=0, limit=20
    )
    bars = asyncio.run(service.list_symbol_bars(**kwargs, interval=BarInterval.FIVE_MINUTES))
    assert bars is not None
    assert bars == (
        asyncio.run(legacy.list_symbol_bars(**kwargs, interval=BarInterval.FIVE_MINUTES))
    )
    assert asyncio.run(service.list_symbol_events(**kwargs)) == (
        asyncio.run(legacy.list_symbol_events(**kwargs))
    )
    engine.dispose()


def _current_status(tmp_path, monkeypatch, *, plan=None, configure_sdk=None):
    from types import SimpleNamespace

    from test_persistent_monitor_read_service import _setup
    from tests.integration import current_pipeline_fixture as fixture

    from trade_plan_monitor.domain.plan_hash import plan_sha256
    from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
    from trade_plan_monitor.runtime.progress import ProgressSnapshot
    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    def status_pipeline(**kwargs):
        kwargs["enable_runtime_status"] = True
        kwargs["recovery_session_factory"] = kwargs["unit_of_work_factory"]()._session_factory
        return ProductionMonitorPipeline(**kwargs)

    monkeypatch.setattr(fixture, "ProductionMonitorPipeline", status_pipeline)
    engine, work, plan, sdk, build, controller, pipeline, _ = fixture.current_pipeline_fixture(
        tmp_path, monkeypatch, current_volume=300, plan=plan
    )
    if configure_sdk is not None:
        configure_sdk(sdk, pipeline._clock, plan)
    deadline = MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=TARGET.date(),
        due_at=fixture.PIPELINE_NOW,
        bar_end=TARGET,
    )

    async def run():
        await pipeline.refresh_references(TARGET.date())
        return (await pipeline.run_deadline(deadline))[0]

    result = asyncio.run(run())
    token, configuration, plans = pipeline.runtime_status_snapshot()
    assert plans[0].completion is not None
    other, _, _, health = _setup(tmp_path)
    other.dispose()
    now = pipeline._clock.now()
    current = [
        RuntimeReadAuthority(
            token=token,
            lifecycle="RUNNING",
            health=health,
            configuration_revision=configuration,
            plans=plans,
            progress=ProgressSnapshot(
                pipeline._runtime_generation,
                now,
                "SCHEDULED",
                now,
                now + timedelta(seconds=10),
                now + timedelta(seconds=30),
            ),
        )
    ]
    sessions = create_session_factory(engine)
    reader = RuntimeStatusReadService(sessions, lambda: current[0], clock=lambda: now)

    def close():
        asyncio.run(controller.aclose())
        engine.dispose()

    return SimpleNamespace(
        engine=engine,
        work=work,
        plan=plan,
        plan_hash=plan_sha256(plan),
        sessions=sessions,
        sdk=sdk,
        build=build,
        controller=controller,
        pipeline=pipeline,
        deadline=deadline,
        result=result,
        reader=reader,
        now=now,
        current=current,
        close=close,
    )


def test_current_status_invalidates_prior_raw_volume_without_reaggregating(tmp_path, monkeypatch):
    env = _current_status(tmp_path, monkeypatch)
    try:
        current = asyncio.run(env.reader.get_dashboard()).symbols[0]
        assert current.availability == "CURRENT" and current.current_actionable
        prior = TARGET - timedelta(minutes=5)
        with env.work() as work:
            stored = work.history.list_five_minute(
                env.plan.symbol, start=prior, end=prior, formula_version="ta-v1"
            )
            source = work.history.list_minutes(
                env.plan.symbol, start=prior - timedelta(minutes=4), end=prior
            )
            assert len(source) == 5 and len(stored) == 1
            work.history.upsert_minutes(
                (
                    source[0].model_copy(
                        update={
                            "volume_shares": source[0].volume_shares + 1,
                            "received_at": env.now,
                        }
                    ),
                )
            )
            work.commit()
        with env.work() as work:
            assert (
                work.history.list_five_minute(
                    env.plan.symbol, start=prior, end=prior, formula_version="ta-v1"
                )
                == stored
            )
        stale = asyncio.run(env.reader.get_dashboard()).symbols[0]
        assert stale.availability == "CACHED" and stale.scope.read_only
        assert not stale.current_actionable
    finally:
        env.close()


def test_current_status_scope_floors_1m_observation_to_required_5m_target(tmp_path, monkeypatch):
    from dataclasses import replace

    from trade_plan_monitor.runtime.status_authority import condition_status_target

    env = _current_status(tmp_path, monkeypatch)
    try:
        observation = TARGET + timedelta(minutes=1, seconds=2)
        with env.sessions() as session, session.begin():
            assert (
                condition_status_target(session, plan=env.plan, now=observation).bucket_end
                == TARGET
            )
        env.pipeline._clock.current = observation
        owner = env.current[0]
        env.reader._clock = lambda: observation
        env.current[0] = replace(
            owner,
            progress=replace(
                owner.progress,
                observed_at=observation,
                last_progress_at=observation,
                next_wake_at=observation + timedelta(seconds=10),
                progress_due_at=observation + timedelta(seconds=30),
            ),
        )
        assert (
            asyncio.run(env.reader.get_dashboard()).symbols[0].scope.required_target.target_end
            == TARGET
        )
    finally:
        env.close()


def test_reviewed_fact_only_confirmation_owns_completed_five_minute_target(tmp_path, monkeypatch):
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.runtime.status_authority import condition_status_target

    env = _current_status(tmp_path, monkeypatch)
    try:
        raw = env.plan.model_dump(mode="json")
        raw["ordinary_rules"] = [raw["ordinary_rules"][0]]
        raw["ordinary_rules"][0]["condition"] = {
            "type": "REVIEWED_FACT",
            "fact_kind": "TECHNICAL",
            "evidence_requirement": "Synthetic technical review",
            "validity_scope": "TRADE_DATE",
        }
        raw["alert_rules"] = []
        plan = UnifiedTradePlan.model_validate(raw)
        with env.sessions() as session, session.begin():
            assert (
                condition_status_target(
                    session, plan=plan, now=TARGET + timedelta(minutes=1)
                ).bucket_end
                == TARGET
            )
    finally:
        env.close()


def test_daily_confirmation_with_minute_reset_owns_current_intraday_target(tmp_path, monkeypatch):
    from tests.integration.current_pipeline_fixture import current_three_rule_plan
    from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
    from trade_plan_monitor.runtime.production import _unified_minute_required

    raw = current_three_rule_plan().model_dump(mode="json")
    raw["ordinary_rules"] = [unified_payload()["ordinary_rules"][0]]
    raw["ordinary_rules"][0].update(
        zone=None,
        condition={
            "type": "DAILY_PRICE_COMPARE",
            "field": "close",
            "offset": 0,
            "comparator": "LT",
            "reference": {
                "mode": "FIXED",
                "value": "6200",
                "unit": "FEN",
                "as_of": "2026-09-11",
                "source": "Synthetic reviewed daily threshold",
            },
        },
        independent_signal={
            "mode": "LATER_CLOSE_RESET_THEN_CONFIRM",
            "reset_condition": {
                "type": "MINUTE_CLOSE_BELOW",
                "timeframe_minutes": 5,
                "price_fen": 1000,
            },
        },
    )
    raw["alert_rules"] = []
    raw["monitoring"] = unified_payload()["monitoring"]
    plan = UnifiedTradePlan.model_validate(raw)
    assert plan.ordinary_rules[0].confirmation.kind == "OFFICIAL_DAILY_CLOSE"
    assert _unified_minute_required(plan)
    daily_sources = []

    def configure_sdk(sdk, clock, current):
        source = CurrentCloseSDK(
            clock, (current.symbol,), official_closes={TARGET.date() - timedelta(days=3): "55.00"}
        )
        sdk.daily = source.daily
        sdk.adj_factor = source.adj_factor
        daily_sources.append(source)

    env = _current_status(tmp_path, monkeypatch, plan=plan, configure_sdk=configure_sdk)
    try:
        assert not env.result.snapshot["data_blockers"]
        assert env.result.snapshot["minute_target"] == TARGET.isoformat()
        assert len(env.result.snapshot["minute_prefix"]) == 5
        assert env.result.snapshot["daily_evidence"] is not None
        assert "rt_min" in env.sdk.calls or "rt_min_daily" in env.sdk.calls
        assert {call[0] for call in daily_sources[0].calls} >= {"daily", "adj_factor"}
        row = asyncio.run(env.reader.get_dashboard()).symbols[0]
        assert row.availability == "CURRENT" and row.scope.status == "READY"
        assert not row.scope.read_only
        assert row.scope.required_target.kind == "INTRADAY"
        assert row.scope.required_target.target_end == TARGET
        assert env.pipeline.runtime_status_snapshot()[2][0].completion.target.bucket_end == TARGET
    finally:
        env.close()
