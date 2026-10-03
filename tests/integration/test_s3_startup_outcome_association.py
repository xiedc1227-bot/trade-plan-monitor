"""F1 original-plan accounting and pre-commit stale boundaries, entirely offline."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import BaseModel
from sqlalchemy import text
from test_explicit_runtime_production import (
    NOW,
    PIPELINE_NOW,
    TARGET,
    _database,
    _plan,
    _seed_active,
    _seed_pipeline_facts,
    _work,
)
from test_live_pipeline_acceptance import (
    ControlledClock,
)

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.runtime.explicit_service import (
    ExplicitRuntimeEvaluationService,
    StaleExplicitDecisionError,
)
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.database import (
    create_sqlite_engine,
    upgrade_database,
)
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
            name: tuple(
                tuple(row)
                for row in connection.execute(
                    text(
                        f"SELECT * FROM {name}"
                        + (
                            " WHERE json_extract(payload_json, '$.symbol')=:symbol"
                            if symbol and name == "alert_event"
                            else " WHERE symbol=:symbol"
                            if symbol
                            else ""
                        )
                    ),
                    {"symbol": symbol},
                )
            )
            for name in (
                "explicit_evaluation_ledger",
                "explicit_rule_occurrence_state",
                "alert_event",
                "evaluation_ledger",
                "evaluation_result",
                "symbol_decision_head",
                "risk_state",
                "pending_official_close",
            )
        }


def _deadline():
    return MarketDeadline(
        kind=DeadlineKind.REALTIME_MINUTE,
        trade_date=TARGET.date(),
        due_at=PIPELINE_NOW,
        bar_end=TARGET,
    )


def test_frozen_association_accounts_activation_changed_before_final_commit(tmp_path):
    # Schema3 association is a frozen isolated codec/runtime oracle. Current
    # production selects schema5; no historical plan is admitted into it here.
    engine, plan = _database(tmp_path, "frozen-association.sqlite3")

    def work():
        return _work(engine)

    before = _business(engine)

    def deactivate(_result):
        with work() as transaction:
            transaction.plans.deactivate(plan.symbol, expected_revision=1)
            transaction.commit()

    service = ExplicitRuntimeEvaluationService(work, after_evaluate=deactivate)
    try:
        outcome = asyncio.run(
            service.run_intraday_associated_and_publish(
                plan=plan,
                target_bucket_end=TARGET,
                evaluated_at=NOW,
                expected_activation_revision=1,
            )
        )
        assert outcome.reason.value == "STALE_EXPLICIT_DECISION"
        assert _business(engine) == before
    finally:
        engine.dispose()


@pytest.mark.parametrize("duplicate", (False, True))
def test_explicit_rejects_wrong_result_activation_before_persistence(
    tmp_path,
    monkeypatch,
    duplicate,
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
                ExplicitDecisionRepository,
                "get",
                lambda *_args, **_kwargs: wrong,
            )
        else:
            monkeypatch.setattr(
                explicit,
                "evaluate_explicit_rules",
                lambda **kwargs: original(**(kwargs | {"activation_revision": 2})),
            )
        before = _business(engine)
        with pytest.raises(RuntimeError, match="identity"):
            service.run_intraday(plan=plan, target_bucket_end=TARGET, evaluated_at=NOW)
        assert _business(engine) == before
    finally:
        engine.dispose()


@pytest.mark.parametrize("error_type", (StaleExplicitDecisionError, RuntimeError))
def test_frozen_post_commit_publisher_error_is_never_accounted_as_stale(
    tmp_path,
    monkeypatch,
    error_type,
):
    engine, plan = _database(tmp_path, "frozen-publisher.sqlite3")

    def fail(_event):
        raise error_type("publisher failure after durable commit")

    service = ExplicitRuntimeEvaluationService(
        lambda: _work(engine), committed_event_publisher=fail
    )
    try:
        with pytest.raises(error_type, match="publisher failure"):
            asyncio.run(
                service.run_intraday_associated_and_publish(
                    plan=plan,
                    target_bucket_end=TARGET,
                    evaluated_at=NOW,
                    expected_activation_revision=1,
                )
            )
        assert len(_business(engine)["alert_event"]) == 1
    finally:
        engine.dispose()


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
                plan=plan,
                target_bucket_end=TARGET + timedelta(minutes=5),
                evaluated_at=NOW + timedelta(minutes=5),
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "mutation",
    ("provider-reactivation", "final-reactivation", "inventory", "risk"),
)
def test_frozen_association_rejects_changed_scope_preserves_sibling_and_next_target(
    tmp_path,
    monkeypatch,
    mutation,
):
    # EXPLICIT outcome envelopes belong to the frozen schema3 compatibility
    # evaluator. Current scheduled capture/restart/delivery authority is exercised
    # separately by the schema5 stock recovery identity and delivery suites.
    engine, first = _database(tmp_path, "frozen-sibling.sqlite3", safety=True)
    second = first.model_copy(update={"plan_id": "healthy-sibling", "symbol": "000002.SZ"})
    _seed_active(engine, second)
    _seed_pipeline_facts(engine, second)

    def work():
        return _work(engine)

    def mutate():
        with work() as transaction:
            if mutation in {"provider-reactivation", "final-reactivation"}:
                transaction.plans.deactivate(first.symbol, expected_revision=1)
                transaction.plans.activate(
                    first, expected_revision=2, validation=PlanValidationResult(issues=())
                )
            elif mutation == "inventory":
                transaction.positions.confirm_inventory(
                    symbol=first.symbol,
                    as_of_trade_date=TARGET.date(),
                    total_quantity=100,
                    sellable_quantity=100,
                    included_lot_ids=(),
                    complete_registration=True,
                    expected_revision=1,
                )
            else:
                transaction.manual_event_risk.upsert(
                    symbol=first.symbol,
                    plan_hash=plan_sha256(first),
                    status=ManualEventRiskStatus.RISK_PRESENT,
                    expires_on=TARGET.date(),
                    expected_revision=1,
                )
            transaction.commit()

    changed = False

    def after_evaluate(result):
        nonlocal changed
        if result.symbol == first.symbol and not changed:
            changed = True
            mutate()

    original = ExplicitRuntimeEvaluationService(work)
    service = ExplicitRuntimeEvaluationService(
        work, after_evaluate=None if mutation == "provider-reactivation" else after_evaluate
    )
    try:
        prior = TARGET - timedelta(minutes=5)
        original.run_intraday(
            plan=first, target_bucket_end=prior, evaluated_at=prior + timedelta(seconds=15)
        )
        before = _business(engine, first.symbol)
        if mutation == "provider-reactivation":
            mutate()
        outcome = asyncio.run(
            service.run_intraday_associated_and_publish(
                plan=first,
                target_bucket_end=TARGET,
                evaluated_at=NOW,
                expected_activation_revision=1,
            )
        )
        assert outcome.reason.value == "STALE_EXPLICIT_DECISION"
        assert _business(engine, first.symbol) == before
        sibling = asyncio.run(
            service.run_intraday_associated_and_publish(
                plan=second,
                target_bucket_end=TARGET,
                evaluated_at=NOW,
                expected_activation_revision=1,
            )
        )
        assert sibling.evaluation_result.activation_revision == 1
        assert sibling.evaluation_result.target_bucket_end == TARGET
        next_target = TARGET + timedelta(minutes=5)
        # Populate real typed frozen input rows for the subsequent target.
        with work() as transaction:
            from decimal import Decimal

            from trade_plan_monitor.market_data.models import MinuteBar

            transaction.history.upsert_minutes(
                tuple(
                    MinuteBar(
                        symbol=first.symbol,
                        bar_end=next_target - timedelta(minutes=offset),
                        open_fen=990,
                        high_fen=990,
                        low_fen=990,
                        close_fen=990,
                        volume_shares=60,
                        amount_yuan=Decimal("0"),
                        received_at=next_target + timedelta(seconds=15),
                    )
                    for offset in (4, 3, 2, 1, 0)
                )
            )
            transaction.commit()
        fresh = original.run_intraday(
            plan=first,
            target_bucket_end=next_target,
            evaluated_at=next_target + timedelta(seconds=15),
        )
        assert fresh.evaluation_result.activation_revision == (
            3 if "reactivation" in mutation else 1
        )
        assert fresh.evaluation_result.target_bucket_end == next_target
        rows = _business(engine, first.symbol)["explicit_evaluation_ledger"]
        assert len(rows) == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "defect",
    (
        "missing",
        "duplicate",
        "extra",
        "consumer_kind",
        "symbol",
        "plan_id",
        "version",
        "plan_hash",
        "activation_revision",
        "target_bucket_end",
        "formula_version",
    ),
)
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
            "consumer_kind": "LEGACY",
            "symbol": "000001.SZ",
            "plan_id": "wrong",
            "version": 2,
            "plan_hash": "0" * 64,
            "activation_revision": 2,
            "target_bucket_end": TARGET + timedelta(minutes=5),
            "formula_version": "wrong",
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
        status=runtime.IntradayCycleStatus.INCOMPLETE,
        facts=None,
        evaluation_result=None,
        claim_created=False,
        committed_event=None,
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
        lambda: _work(engine),
        after_evaluate=fail if phase == "evaluate" else None,
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
            asyncio.run(
                service.run_intraday_associated_and_publish(
                    plan=plan,
                    target_bucket_end=TARGET,
                    evaluated_at=NOW,
                    expected_activation_revision=1,
                )
            )
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
            engine,
            {"active": 0},
            now=bucket + timedelta(seconds=12),
        ),
        context_builder=_runtime_context,
        committed_event_publisher=fail,
    )
    try:
        with pytest.raises(type(error)):
            asyncio.run(
                service.run_intraday_batch(
                    plans=(plan,),
                    bucket_end=bucket,
                    evaluated_at=bucket + timedelta(seconds=12),
                )
            )
        assert len(_business(engine)["evaluation_result"]) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "field, wrong",
    (
        ("symbol", "000001.SZ"),
        ("plan_hash", "0" * 64),
        ("activation_revision", 2),
        ("target_bucket_end", TARGET - timedelta(minutes=5)),
    ),
)
def test_explicit_payload_mismatch_is_not_accepted_under_a_correct_envelope(
    tmp_path,
    field,
    wrong,
):
    import trade_plan_monitor.runtime.service as runtime
    from trade_plan_monitor.decision.explicit_rules import ExplicitEvaluationResult
    from trade_plan_monitor.runtime.explicit_service import ExplicitRuntimeCycleResult

    engine, plan = _database(tmp_path, "payload.sqlite3", current_volume=1)
    try:
        actual = ExplicitRuntimeEvaluationService(lambda: _work(engine)).run_intraday(
            plan=plan,
            target_bucket_end=TARGET,
            evaluated_at=NOW,
        )
        values = actual.evaluation_result.model_dump(mode="python", exclude={"result_hash"})
        wrong_result = ExplicitEvaluationResult.build(**(values | {field: wrong}))
        wrong_cycle = ExplicitRuntimeCycleResult(
            status=actual.status,
            evaluation_result=wrong_result,
            committed_events=(),
        )
        identity = runtime.PlanCycleIdentity.capture(plan, activation_revision=1, target=TARGET)
        with pytest.raises(RuntimeError, match="payload identity"):
            runtime._account_plan_outcomes(
                (identity,),
                (runtime.PlanCycleOutcome(identity, result=wrong_cycle),),
            )
    finally:
        engine.dispose()


def test_mixed_consumers_preserve_original_due_order(tmp_path):
    from test_ten_symbol_runtime import _runtime_plan

    import trade_plan_monitor.runtime.service as runtime

    engine, plan = _database(tmp_path, "mixed-order.sqlite3")
    try:
        explicit_result = ExplicitRuntimeEvaluationService(lambda: _work(engine)).run_intraday(
            plan=plan,
            target_bucket_end=TARGET,
            evaluated_at=NOW,
        )
        explicit_id = runtime.PlanCycleIdentity.capture(plan, activation_revision=1, target=TARGET)
        legacy_id = runtime.PlanCycleIdentity.capture(
            _runtime_plan(),
            activation_revision=1,
            target=TARGET,
        )
        incomplete = runtime.IntradayCycleResult(
            status=runtime.IntradayCycleStatus.INCOMPLETE,
            facts=None,
            evaluation_result=None,
            claim_created=False,
            committed_event=None,
        )
        outcomes = (
            runtime.PlanCycleOutcome(legacy_id, result=incomplete),
            runtime.PlanCycleOutcome(explicit_id, result=explicit_result),
        )
        assert runtime._account_plan_outcomes((explicit_id, legacy_id), outcomes) == (
            explicit_result,
            incomplete,
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
        fetch_minutes=forbidden_fetch,
        unit_of_work_factory=factory,
        context_builder=_runtime_context,
        evaluator=evaluate_then_deactivate,
        committed_event_publisher=lambda _event: None,
    )
    identities = tuple(
        runtime.PlanCycleIdentity.capture(
            plan,
            activation_revision=1,
            target=bucket,
        )
        for plan in plans
    )
    try:
        outcomes = asyncio.run(
            service.run_intraday_outcomes_from_minutes(
                plans=plans,
                identities=identities,
                bucket_end=bucket,
                evaluated_at=now,
                minutes_by_symbol={
                    plan.symbol: tuple(
                        _bar(plan.symbol, _at(9, minute)) for minute in range(31, 36)
                    )
                    for plan in plans
                },
            )
        )
        assert outcomes[0].identity == identities[0]
        assert outcomes[0].stale is runtime.PlanCycleStale.LEGACY
        assert outcomes[1].identity == identities[1]
        assert outcomes[1].result.status is runtime.IntradayCycleStatus.COMMITTED
        assert runtime._account_plan_outcomes(identities, outcomes) == (outcomes[1].result,)
        assert not _business(engine, first.symbol)["evaluation_result"]
        assert len(_business(engine, second.symbol)["evaluation_result"]) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "part, field, wrong",
    (
        ("facts", "symbol", "000001.SZ"),
        ("facts", "formula_version", "wrong"),
        ("facts", "bucket_end", TARGET),
        ("identity", "symbol", "000001.SZ"),
        ("identity", "plan_hash", "0" * 64),
        ("identity", "formula_version", "wrong"),
        ("identity", "bucket_end", TARGET),
        ("snapshot", "plan_id", "wrong"),
        ("snapshot", "plan_version", 2),
    ),
)
def test_legacy_payload_mismatch_is_not_accepted_under_a_correct_envelope(
    tmp_path,
    part,
    field,
    wrong,
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
        context_builder=_runtime_context,
        committed_event_publisher=lambda _event: None,
    )
    try:
        cycle = asyncio.run(
            service.run_intraday(
                plan=plan,
                bucket_end=bucket,
                evaluated_at=now,
            )
        )
        # Deliberately corrupt a returned payload past model validation to exercise association.
        if part == "facts":
            updates = {"facts": BaseModel.model_copy(cycle.facts, update={field: wrong})}
        else:
            key = "evaluation_identity" if part == "identity" else "snapshot"
            changed = BaseModel.model_copy(
                getattr(cycle.evaluation_result, key),
                update={field: wrong},
            )
            updates = {
                "evaluation_result": BaseModel.model_copy(
                    cycle.evaluation_result,
                    update={key: changed},
                )
            }
        wrong_cycle = BaseModel.model_copy(cycle, update=updates)
        identity = runtime.PlanCycleIdentity.capture(plan, activation_revision=1, target=bucket)
        with pytest.raises(RuntimeError, match="identity"):
            runtime._account_plan_outcomes(
                (identity,),
                (runtime.PlanCycleOutcome(identity, result=wrong_cycle),),
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("mutation", ("reactivation", "deactivation"))
def test_current_activation_changed_after_acquisition_preserves_committed_business(
    tmp_path, monkeypatch, mutation
):
    from tests.integration.current_pipeline_fixture import current_pipeline_fixture

    async def scenario():
        engine, work, plan, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=60
        )
        original = pipeline.daily_evaluations.run_inputs
        changed = False

        def rows():
            with engine.connect() as connection:
                return tuple(
                    tuple(row)
                    for row in connection.execute(
                        text("SELECT id, revision, payload_json FROM daily_plan_record ORDER BY id")
                    )
                )

        before = rows()

        def before_commit(**kwargs):
            nonlocal changed
            if not changed:
                changed = True
                with work() as transaction:
                    transaction.plans.deactivate(plan.symbol, expected_revision=1)
                    if mutation == "reactivation":
                        transaction.plans.activate(
                            plan, expected_revision=2, validation=PlanValidationResult(issues=())
                        )
                    transaction.commit()
            return original(**kwargs)

        monkeypatch.setattr(pipeline.daily_evaluations, "run_inputs", before_commit)
        try:
            await pipeline.refresh_references(TARGET.date())
            assert await pipeline.run_deadline(_deadline()) == ()
            assert changed and rows() == before
            assert _business(engine)["alert_event"] == ()
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("typed", (False, True))
def test_current_post_commit_publisher_error_is_never_accounted_as_stale(
    tmp_path, monkeypatch, typed
):
    from tests.integration.current_pipeline_fixture import current_pipeline_fixture

    from trade_plan_monitor.runtime.daily_service import DailyActivationChangedError

    async def scenario():
        engine, _, _, _, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=60
        )
        error_type = DailyActivationChangedError if typed else RuntimeError

        def fail(_event):
            raise error_type("publisher failure after durable current commit")

        pipeline.daily_evaluations._publish = fail
        try:
            await pipeline.refresh_references(TARGET.date())
            with pytest.raises(error_type, match="publisher failure"):
                await pipeline.run_deadline(_deadline())
            assert len(_business(engine)["alert_event"]) == 1
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())
