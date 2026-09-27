"""F1 original-plan accounting and pre-commit stale boundaries, entirely offline."""

import asyncio
import threading
from dataclasses import replace
from datetime import timedelta

import httpx
import pandas as pd
import pytest
import requests
from pydantic import BaseModel
from sqlalchemy import text
from test_explicit_runtime_production import (
    NOW,
    PIPELINE_NOW,
    TARGET,
    _database,
    _ExplicitPipelineSDK,
    _pipeline_fixture,
    _plan,
    _seed_active,
    _seed_pipeline_facts,
    _work,
)
from test_live_pipeline_acceptance import (
    ControlledClock,
    VirtualPace,
    _write_configuration_and_evidence,
)

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.runtime.explicit_service import (
    ExplicitRuntimeEvaluationService,
    StaleExplicitDecisionError,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import RuntimeLiveness
from trade_plan_monitor.state.repositories import ManualEventRiskStatus
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


class _DeadlineClock(ControlledClock):
    """Release real scheduler deadlines without depending on another pending test file."""

    def __init__(self, current):
        super().__init__(current)
        self.waits = asyncio.Queue()
        self.parked = None
        self.released = 0

    async def sleep_until(self, deadline):
        self.sleep_calls.append(deadline)
        permit = asyncio.get_running_loop().create_future()
        await self.waits.put((deadline, permit))
        await permit

    async def park(self, *, failed=lambda: False):
        while self.waits.empty():
            if failed():
                return False
            await asyncio.sleep(0.005)
        self.parked = await self.waits.get()
        return True

    async def drive(self, through, *, stop_when=lambda: False, failed=lambda: False):
        while self.parked[0] <= through and not stop_when():
            deadline, permit = self.parked
            assert self.released < 64, "fixture wake guard exceeded"
            self.released += 1
            self.current = max(self.current, deadline)
            permit.set_result(None)
            # The next requested sleep proves the preceding scheduled work returned.
            if not await self.park(failed=failed):
                return


def _business(engine, symbol=None):
    with engine.connect() as connection:
        return {
            name: tuple(tuple(row) for row in connection.execute(
                text(f"SELECT * FROM {name}" + (
                    " WHERE json_extract(payload_json, '$.symbol')=:symbol"
                    if symbol and name == "alert_event"
                    else " WHERE symbol=:symbol" if symbol else ""
                )),
                {"symbol": symbol},
            ))
            for name in (
                "explicit_evaluation_ledger", "explicit_rule_occurrence_state", "alert_event",
                "evaluation_ledger", "evaluation_result", "symbol_decision_head",
                "risk_state", "pending_official_close",
            )
        }


def _deadline():
    return MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE, trade_date=TARGET.date(),
        due_at=PIPELINE_NOW, bar_end=TARGET,
    )


def test_coordinator_accounts_explicit_activation_changed_before_final_commit(
    tmp_path, monkeypatch,
):
    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = _pipeline_fixture(
            tmp_path, monkeypatch, current_volume=60,
        )
        before = _business(engine)

        def deactivate(_result):
            with work() as transaction:
                transaction.plans.deactivate(plan.symbol, expected_revision=1)
                transaction.commit()

        pipeline.explicit_evaluations._after_evaluate = deactivate
        try:
            await pipeline.refresh_references(TARGET.date())
            assert await pipeline.run_deadline(_deadline()) == ()
            assert _business(engine) == before
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("duplicate", (False, True))
def test_explicit_rejects_wrong_result_activation_before_persistence(
    tmp_path, monkeypatch, duplicate,
):
    import trade_plan_monitor.runtime.explicit_service as explicit

    engine, plan = _database(tmp_path, "identity.sqlite3")
    service = ExplicitRuntimeEvaluationService(lambda: _work(engine))
    original = explicit.evaluate_explicit_rules
    try:
        if duplicate:
            from trade_plan_monitor.state.explicit_rules import ExplicitDecisionRepository

            evaluated = {}

            def record(**kwargs):
                evaluated.update(kwargs)
                return original(**kwargs)

            monkeypatch.setattr(explicit, "evaluate_explicit_rules", record)
            service.run_intraday(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
            wrong = original(**(evaluated | {"activation_revision": 2}))
            monkeypatch.setattr(
                ExplicitDecisionRepository, "get",
                lambda *_args, **_kwargs: wrong,
            )
        else:
            monkeypatch.setattr(
                explicit, "evaluate_explicit_rules",
                lambda **kwargs: original(**(kwargs | {"activation_revision": 2})),
            )
        before = _business(engine)
        with pytest.raises(RuntimeError, match="identity"):
            service.run_intraday(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
        assert _business(engine) == before
    finally:
        engine.dispose()


@pytest.mark.parametrize("error_type", (StaleExplicitDecisionError, RuntimeError))
def test_post_commit_explicit_publisher_error_is_never_accounted_as_stale(
    tmp_path, monkeypatch, error_type,
):
    async def scenario():
        engine, _, _, _, _, controller, pipeline, _ = _pipeline_fixture(
            tmp_path, monkeypatch, current_volume=60,
        )

        def fail(_event):
            raise error_type("publisher failure after durable commit")

        pipeline.explicit_evaluations._publisher = fail
        try:
            await pipeline.refresh_references(TARGET.date())
            with pytest.raises(error_type, match="publisher failure"):
                await pipeline.run_deadline(_deadline())
            assert len(_business(engine)["alert_event"]) == 1
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_explicit_public_default_still_returns_result_and_standalone_stale_raises(tmp_path):
    engine, plan = _database(tmp_path, "public-default.sqlite3")
    service = ExplicitRuntimeEvaluationService(lambda: _work(engine))
    try:
        result = service.run_intraday(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
        assert result.evaluation_result.activation_revision == 1
        with _work(engine) as work:
            work.plans.deactivate(plan.symbol, expected_revision=1)
            work.commit()
        with pytest.raises(StaleExplicitDecisionError):
            service.run_intraday(
                plan=plan, target_bucket_end=TARGET + timedelta(minutes=5),
                evaluated_at=NOW + timedelta(minutes=5),
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "mutation", ("provider-reactivation", "final-reactivation", "inventory", "risk"),
)
def test_real_composition_accounts_stale_scope_preserves_sibling_and_next_deadline(
    tmp_path, monkeypatch, mutation,
):
    import trade_plan_monitor.runtime.explicit_service as explicit
    import trade_plan_monitor.runtime.production as production
    import trade_plan_monitor.runtime.service as runtime
    import trade_plan_monitor.web.monitor_composition as composition_module

    async def scenario():
        initial = TARGET - timedelta(minutes=1) + timedelta(seconds=15)
        clock = _DeadlineClock(initial)
        first = _plan(safety=True)
        second = first.model_copy(update={"plan_id": "healthy-sibling", "symbol": "000002.SZ"})
        plans = (first, second)
        database = tmp_path / "composition.sqlite3"
        engine = create_sqlite_engine(database)
        upgrade_database(engine)
        sessions = create_session_factory(engine)

        def work():
            return SqlAlchemyUnitOfWork(sessions, clock=clock.now)

        for plan in plans:
            _seed_active(engine, plan)
            _seed_pipeline_facts(engine, plan)
        # Seed a genuine earlier ledger row; the exercised deadlines remain scheduler-owned.
        ExplicitRuntimeEvaluationService(work).run_intraday(
            plan=first, target_bucket_end=TARGET - timedelta(minutes=5), evaluated_at=initial,
        )
        with sessions.begin() as session:
            session.add(RuntimeLiveness(
                id=1, schema_version=1, revision=0, last_alive_at=initial.isoformat(),
            ))
        config = _write_configuration_and_evidence(
            tmp_path, observed_at=initial, include_index=False,
        )
        entered, release = threading.Event(), threading.Event()

        class SDK(_ExplicitPipelineSDK):
            def __getattr__(self, name):
                request = super().__getattr__(name)

                def invoke(**kwargs):
                    self.source_time = clock.now().replace(second=0, microsecond=0) - timedelta(
                        minutes=1,
                    )
                    frame = request(**kwargs)
                    if name not in {"rt_min", "rt_min_daily"}:
                        return frame
                    symbols = str(kwargs["ts_code"]).split(",")
                    frame = pd.concat(
                        [frame.assign(ts_code=symbol) for symbol in symbols], ignore_index=True,
                    )
                    if name == "rt_min" and clock.now().replace(second=0) == TARGET:
                        entered.set()
                        assert release.wait(8), "test did not release physical SDK"
                    return frame

                return invoke

        sdk = SDK(current_volume=60)
        real_controller = composition_module.create_live_tushare_request_controller

        def controller_factory(*, clock, require_repository_binding=False):
            pace = VirtualPace()
            return real_controller(
                clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep,
                require_repository_binding=require_repository_binding,
            )

        def forbid_http(*_args, **_kwargs):
            raise AssertionError("F1 fixture must never access HTTP")

        monkeypatch.setattr(requests.Session, "request", forbid_http)
        monkeypatch.setattr(httpx.Client, "send", forbid_http)
        monkeypatch.setattr(httpx.AsyncClient, "send", forbid_http)
        monkeypatch.setattr(production, "create_tushare_client", lambda _config: sdk)
        monkeypatch.setattr(composition_module, "SystemClock", lambda: clock)
        monkeypatch.setattr(
            composition_module, "create_live_tushare_request_controller", controller_factory,
        )

        def mutate():
            with work() as transaction:
                if mutation in {"provider-reactivation", "final-reactivation"}:
                    transaction.plans.deactivate(first.symbol, expected_revision=1)
                    transaction.plans.activate(
                        first, expected_revision=2, validation=PlanValidationResult(issues=()),
                    )
                elif mutation == "inventory":
                    transaction.positions.confirm_inventory(
                        symbol=first.symbol, as_of_trade_date=TARGET.date(),
                        total_quantity=100, sellable_quantity=100, included_lot_ids=(),
                        complete_registration=True, expected_revision=1,
                    )
                else:
                    transaction.manual_event_risk.upsert(
                        symbol=first.symbol, plan_hash=plan_sha256(first),
                        status=ManualEventRiskStatus.RISK_PRESENT,
                        expires_on=TARGET.date(), expected_revision=1,
                    )
                transaction.commit()

        real_evaluate = explicit.evaluate_explicit_rules
        real_account = runtime._account_plan_outcomes
        accounted = []

        def observe_accounting(expected, outcomes):
            result = real_account(expected, outcomes)
            accounted.append((expected, outcomes))
            return result

        monkeypatch.setattr(runtime, "_account_plan_outcomes", observe_accounting)
        changed = False

        def evaluate_then_mutate(**kwargs):
            nonlocal changed
            result = real_evaluate(**kwargs)
            if not changed and kwargs["plan"].symbol == first.symbol:
                changed = True
                mutate()
            return result

        composition = composition_module.create_monitor_composition(
            config_path=config, database_path=database,
        )
        try:
            await composition.start()
            await clock.park()
            generation = composition.health().runtime_generation
            before = _business(engine, first.symbol)
            assert before["explicit_evaluation_ledger"]

            def failed():
                return composition.health().degraded_reason == "RUNTIME_RUNNER_FAILED"
            drive = asyncio.create_task(clock.drive(TARGET + timedelta(seconds=12), failed=failed))
            while not entered.is_set():
                assert not drive.done(), "scheduler returned before entering physical SDK"
                await asyncio.sleep(0.005)
            if mutation == "provider-reactivation":
                mutate()
            else:
                monkeypatch.setattr(explicit, "evaluate_explicit_rules", evaluate_then_mutate)
            release.set()
            await drive
            assert not failed(), "normal pre-commit stale must not fault the runner"
            assert composition.health().runtime_generation == generation
            with engine.connect() as connection:
                rows = connection.execute(text(
                    "SELECT symbol, activation_revision, target_value "
                    "FROM explicit_evaluation_ledger ORDER BY symbol"
                )).all()
            assert [tuple(row) for row in rows] == [
                (second.symbol, 1, TARGET.isoformat()),
                (first.symbol, 1, (TARGET - timedelta(minutes=5)).isoformat()),
            ]
            assert _business(engine, first.symbol) == before
            original = runtime.PlanCycleIdentity.capture(
                first, activation_revision=1, target=TARGET,
            )
            first_outcome, = [item for item in accounted[0][1] if item.identity == original]
            assert first_outcome.stale is runtime.PlanCycleStale.EXPLICIT
            assert first_outcome.result is None
            await clock.drive(TARGET + timedelta(minutes=5, seconds=12), failed=failed)
            assert not failed()
            assert composition.health().runtime_generation == generation
            with engine.connect() as connection:
                first_rows = connection.execute(text(
                    "SELECT activation_revision, target_value FROM explicit_evaluation_ledger "
                    "WHERE symbol=:symbol ORDER BY target_value"
                ), {"symbol": first.symbol}).all()
            assert [tuple(row) for row in first_rows] == [
                (1, (TARGET - timedelta(minutes=5)).isoformat()), (
                3 if "reactivation" in mutation else 1,
                (TARGET + timedelta(minutes=5)).isoformat(),
            )]
        finally:
            release.set()
            await asyncio.wait_for(composition.stop(), timeout=10)
            engine.dispose()

    async def bounded():
        async with asyncio.timeout(45):
            await scenario()

    asyncio.run(bounded())


@pytest.mark.parametrize("defect", (
    "missing", "duplicate", "extra", "consumer_kind", "symbol", "plan_id", "version",
    "plan_hash", "activation_revision", "target_bucket_end", "formula_version",
))
def test_accounting_rejects_every_inexact_origin_before_extracting_results(defect):
    import trade_plan_monitor.runtime.service as runtime

    first = runtime.PlanCycleIdentity.capture(_plan(), activation_revision=1, target=TARGET)
    second = replace(first, symbol="000002.SZ", plan_id="other")
    outcome = runtime.PlanCycleOutcome(identity=first, stale=runtime.PlanCycleStale.EXPLICIT)
    sibling = runtime.PlanCycleOutcome(identity=second, stale=runtime.PlanCycleStale.EXPLICIT)
    outcomes = (outcome, sibling)
    if defect == "missing":
        outcomes = (sibling,)
    elif defect == "duplicate":
        outcomes = (outcome, outcome, sibling)
    elif defect == "extra":
        outcomes += (replace(outcome, identity=replace(first, plan_id="extra")),)
    else:
        wrong = {
            "consumer_kind": "LEGACY", "symbol": "000001.SZ", "plan_id": "wrong",
            "version": 2, "plan_hash": "0" * 64, "activation_revision": 2,
            "target_bucket_end": TARGET + timedelta(minutes=5), "formula_version": "wrong",
        }[defect]
        outcomes = (replace(outcome, identity=replace(first, **{defect: wrong})), sibling)
    with pytest.raises(RuntimeError, match="outcome"):
        runtime._account_plan_outcomes((first, second), outcomes)


def test_accounting_keeps_original_order_and_facts_none_without_fabrication():
    from test_ten_symbol_runtime import _runtime_plan

    import trade_plan_monitor.runtime.service as runtime

    first = runtime.PlanCycleIdentity.capture(_runtime_plan(), activation_revision=1, target=TARGET)
    second = replace(first, symbol="000002.SZ", plan_id="other")
    incomplete = runtime.IntradayCycleResult(
        status=runtime.IntradayCycleStatus.INCOMPLETE, facts=None, evaluation_result=None,
        claim_created=False, committed_event=None,
    )
    outcome = runtime.PlanCycleOutcome(identity=first, result=incomplete)
    stale = runtime.PlanCycleOutcome(identity=second, stale=runtime.PlanCycleStale.LEGACY)
    assert runtime._account_plan_outcomes((first, second), (stale, outcome)) == (incomplete,)
    assert runtime._account_plan_outcomes((second,), (stale,)) == ()
    with pytest.raises((AttributeError, TypeError)):
        outcome.identity = second


@pytest.mark.parametrize("phase", ("evaluate", "persist", "commit", "after-commit"))
def test_same_typed_error_outside_guard_is_never_a_stale_disposition(tmp_path, monkeypatch, phase):
    from trade_plan_monitor.state.explicit_rules import ExplicitDecisionRepository

    engine, plan = _database(tmp_path, "error-origin.sqlite3")

    def fail(*_args, **_kwargs):
        raise StaleExplicitDecisionError(f"unexpected {phase} failure")

    service = ExplicitRuntimeEvaluationService(
        lambda: _work(engine), after_evaluate=fail if phase == "evaluate" else None,
    )
    if phase == "persist":
        monkeypatch.setattr(ExplicitDecisionRepository, "persist", fail)
    if phase in {"commit", "after-commit"}:
        real_commit = SqlAlchemyUnitOfWork.commit

        def commit(work):
            if phase == "after-commit":
                real_commit(work)
            fail()

        monkeypatch.setattr(SqlAlchemyUnitOfWork, "commit", commit)
    try:
        with pytest.raises(StaleExplicitDecisionError, match=f"unexpected {phase}"):
            asyncio.run(service.run_intraday_associated_and_publish(
                plan=plan, target_bucket_end=TARGET, evaluated_at=NOW,
                expected_activation_revision=1,
            ))
        state = _business(engine)
        assert len(state["explicit_evaluation_ledger"]) == int(phase == "after-commit")
        assert len(state["alert_event"]) == int(phase == "after-commit")
    finally:
        engine.dispose()


@pytest.mark.parametrize("error_type", ("typed", "ordinary", "cancelled"))
def test_legacy_batch_does_not_swallow_publisher_failure(tmp_path, error_type):
    from test_ten_symbol_runtime import (
        _at,
        _bar,
        _runtime_context,
        _runtime_plan,
        _runtime_uow_factory,
    )

    import trade_plan_monitor.runtime.service as runtime

    engine = create_sqlite_engine(tmp_path / "legacy-publisher.sqlite3")
    upgrade_database(engine)
    plan = _runtime_plan()
    bucket = _at(9, 35)
    error = {
        "typed": runtime.StaleActivationGenerationError(plan.symbol),
        "ordinary": RuntimeError("unexpected publication error"),
        "cancelled": asyncio.CancelledError(),
    }[error_type]

    async def fetch(_symbol, _target):
        return tuple(_bar(plan.symbol, _at(9, minute)) for minute in range(31, 36))

    def fail(_event):
        raise error

    service = runtime.RuntimeEvaluationService(
        fetch_minutes=fetch,
        unit_of_work_factory=_runtime_uow_factory(
            engine, {"active": 0}, now=bucket + timedelta(seconds=12),
        ), context_builder=_runtime_context, committed_event_publisher=fail,
    )
    try:
        with pytest.raises(type(error)):
            asyncio.run(service.run_intraday_batch(
                plans=(plan,), bucket_end=bucket, evaluated_at=bucket + timedelta(seconds=12),
            ))
        assert len(_business(engine)["evaluation_result"]) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("field, wrong", (
    ("symbol", "000001.SZ"), ("plan_hash", "0" * 64),
    ("activation_revision", 2), ("target_bucket_end", TARGET - timedelta(minutes=5)),
))
def test_explicit_payload_mismatch_is_not_accepted_under_a_correct_envelope(
    tmp_path, field, wrong,
):
    import trade_plan_monitor.runtime.service as runtime
    from trade_plan_monitor.decision.explicit_rules import ExplicitEvaluationResult
    from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeCycleResult

    engine, plan = _database(tmp_path, "payload.sqlite3", current_volume=1)
    try:
        actual = ExplicitRuntimeEvaluationService(lambda: _work(engine)).run_intraday(
            plan=plan, target_bucket_end=TARGET, evaluated_at=NOW,
        )
        values = actual.evaluation_result.model_dump(mode="python", exclude={"result_hash"})
        wrong_result = ExplicitEvaluationResult.build(**(values | {field: wrong}))
        wrong_cycle = ExplicitRuntimeCycleResult(
            status=actual.status, evaluation_result=wrong_result, committed_events=(),
        )
        identity = runtime.PlanCycleIdentity.capture(plan, activation_revision=1, target=TARGET)
        with pytest.raises(RuntimeError, match="payload identity"):
            runtime._account_plan_outcomes(
                (identity,), (runtime.PlanCycleOutcome(identity, result=wrong_cycle),),
            )
    finally:
        engine.dispose()


def test_mixed_consumers_preserve_original_due_order(tmp_path):
    from test_ten_symbol_runtime import _runtime_plan

    import trade_plan_monitor.runtime.service as runtime

    engine, plan = _database(tmp_path, "mixed-order.sqlite3")
    try:
        explicit_result = ExplicitRuntimeEvaluationService(lambda: _work(engine)).run_intraday(
            plan=plan, target_bucket_end=TARGET, evaluated_at=NOW,
        )
        explicit_id = runtime.PlanCycleIdentity.capture(plan, activation_revision=1, target=TARGET)
        legacy_id = runtime.PlanCycleIdentity.capture(
            _runtime_plan(), activation_revision=1, target=TARGET,
        )
        incomplete = runtime.IntradayCycleResult(
            status=runtime.IntradayCycleStatus.INCOMPLETE, facts=None, evaluation_result=None,
            claim_created=False, committed_event=None,
        )
        outcomes = (
            runtime.PlanCycleOutcome(legacy_id, result=incomplete),
            runtime.PlanCycleOutcome(explicit_id, result=explicit_result),
        )
        assert runtime._account_plan_outcomes((explicit_id, legacy_id), outcomes) == (
            explicit_result, incomplete,
        )
    finally:
        engine.dispose()


def test_legacy_strict_batch_keeps_stale_original_and_healthy_sibling(tmp_path):
    from test_ten_symbol_runtime import (
        _at,
        _bar,
        _runtime_context,
        _runtime_plan,
        _runtime_uow_factory,
    )

    import trade_plan_monitor.runtime.service as runtime
    from trade_plan_monitor.decision.engine import evaluate

    engine = create_sqlite_engine(tmp_path / "legacy-stale.sqlite3")
    upgrade_database(engine)
    first = _runtime_plan()
    second = first.model_copy(update={"plan_id": "legacy-sibling", "symbol": "000002.SZ"})
    plans = (first, second)
    bucket = _at(9, 35)
    now = bucket + timedelta(seconds=12)
    factory = _runtime_uow_factory(engine, {"active": 0}, now=now)
    for plan in plans:
        _seed_active(engine, plan)

    def evaluate_then_deactivate(context):
        result = evaluate(context)
        if context.plan.symbol == first.symbol:
            with factory() as transaction:
                transaction.plans.deactivate(first.symbol, expected_revision=1)
                transaction.commit()
        return result

    async def forbidden_fetch(*_args):
        raise AssertionError("strict prefetched batch must not reacquire")

    service = runtime.RuntimeEvaluationService(
        fetch_minutes=forbidden_fetch, unit_of_work_factory=factory,
        context_builder=_runtime_context, evaluator=evaluate_then_deactivate,
        committed_event_publisher=lambda _event: None,
    )
    identities = tuple(runtime.PlanCycleIdentity.capture(
        plan, activation_revision=1, target=bucket,
    ) for plan in plans)
    try:
        outcomes = asyncio.run(service.run_intraday_outcomes_from_minutes(
            plans=plans, identities=identities, bucket_end=bucket, evaluated_at=now,
            minutes_by_symbol={plan.symbol: tuple(
                _bar(plan.symbol, _at(9, minute)) for minute in range(31, 36)
            ) for plan in plans},
        ))
        assert outcomes[0].identity == identities[0]
        assert outcomes[0].stale is runtime.PlanCycleStale.LEGACY
        assert outcomes[1].identity == identities[1]
        assert outcomes[1].result.status is runtime.IntradayCycleStatus.COMMITTED
        assert runtime._account_plan_outcomes(identities, outcomes) == (outcomes[1].result,)
        assert not _business(engine, first.symbol)["evaluation_result"]
        assert len(_business(engine, second.symbol)["evaluation_result"]) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("part, field, wrong", (
    ("facts", "symbol", "000001.SZ"), ("facts", "formula_version", "wrong"),
    ("facts", "bucket_end", TARGET),
    ("identity", "symbol", "000001.SZ"), ("identity", "plan_hash", "0" * 64),
    ("identity", "formula_version", "wrong"), ("identity", "bucket_end", TARGET),
    ("snapshot", "plan_id", "wrong"), ("snapshot", "plan_version", 2),
))
def test_legacy_payload_mismatch_is_not_accepted_under_a_correct_envelope(
    tmp_path, part, field, wrong,
):
    from test_ten_symbol_runtime import (
        _at,
        _bar,
        _runtime_context,
        _runtime_plan,
        _runtime_uow_factory,
    )

    import trade_plan_monitor.runtime.service as runtime

    engine = create_sqlite_engine(tmp_path / "legacy-payload.sqlite3")
    upgrade_database(engine)
    plan = _runtime_plan()
    bucket = _at(9, 35)
    now = bucket + timedelta(seconds=12)

    async def fetch(_symbol, _target):
        return tuple(_bar(plan.symbol, _at(9, minute)) for minute in range(31, 36))

    service = runtime.RuntimeEvaluationService(
        fetch_minutes=fetch,
        unit_of_work_factory=_runtime_uow_factory(engine, {"active": 0}, now=now),
        context_builder=_runtime_context, committed_event_publisher=lambda _event: None,
    )
    try:
        cycle = asyncio.run(service.run_intraday(
            plan=plan, bucket_end=bucket, evaluated_at=now,
        ))
        # Deliberately corrupt a returned payload past model validation to exercise association.
        if part == "facts":
            updates = {"facts": BaseModel.model_copy(cycle.facts, update={field: wrong})}
        else:
            key = "evaluation_identity" if part == "identity" else "snapshot"
            changed = BaseModel.model_copy(
                getattr(cycle.evaluation_result, key), update={field: wrong},
            )
            updates = {"evaluation_result": BaseModel.model_copy(
                cycle.evaluation_result, update={key: changed},
            )}
        wrong_cycle = BaseModel.model_copy(cycle, update=updates)
        identity = runtime.PlanCycleIdentity.capture(plan, activation_revision=1, target=bucket)
        with pytest.raises(RuntimeError, match="identity"):
            runtime._account_plan_outcomes(
                (identity,), (runtime.PlanCycleOutcome(identity, result=wrong_cycle),),
            )
    finally:
        engine.dispose()
