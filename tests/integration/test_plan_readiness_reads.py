"""Readiness observes committed native output; it never evaluates or repairs it."""

import asyncio
import socket
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import requests
from sqlalchemy import event
from tests.integration.test_plan_buy_suspension_recovery import chain as _suspension_chain
from tests.integration.test_plan_readiness_execution_reads import execution_case as execution_case
from tests.integration.test_runtime_status_projection import _current_status
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_authority import _confirm, _save
from tests.integration.test_source_coverage_authority_save import _NOW
from tests.integration.test_source_coverage_authority_save import state as state

suspension_chain = _suspension_chain

AXES = {
    "SOURCE_COVERAGE", "REVIEW_ACTIVATION", "RUNTIME_OWNERSHIP",
    "DATA_EVALUATION", "INVENTORY_CAPITAL", "NOTIFICATION_DELIVERY",
}


@pytest.fixture
def guarded_read_case(request, monkeypatch):
    from functools import partial

    from tests.integration.test_plan_buy_suspension_activation import (
        guard_draft,
        public_activate,
        public_production_guard,
    )
    from tests.integration.test_plan_buy_suspension_recovery import advance
    from tests.integration.test_plan_buy_suspension_runtime import inputs
    from tests.integration.test_plan_readiness_notification_service import ProgressOwner

    from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    chain = request.getfixturevalue("suspension_chain")
    mode = getattr(request, "param", "latched")
    if mode == "sell-missing":
        from tests.integration.test_plan_buy_suspension_runtime import prepare
        pipeline, saved = prepare(chain, side="SELL"), chain.version
    else:
        pipeline, saved = public_production_guard(chain)
    sessions = chain.plans._unit_of_work()._session_factory
    # Install the native post-commit proof observer, never a fabricated proof.
    pipeline._runtime_status_enabled = True
    pipeline._runtime_status_sessions = sessions
    pipeline.daily_evaluations._observe = pipeline._observe_status_commit
    progress_owner = ProgressOwner(pipeline._runtime_generation, pipeline._clock)
    progress = progress_owner.tracker
    if mode in {"latched", "inherited"}:
        chain.sdk.breach = chain.now.replace(minute=35, second=0, microsecond=0)
    row = advance(chain)
    original_version = saved["id"]
    if mode == "inherited":
        saved = public_activate(chain, guard_draft(chain, plan_id="ordinary-continuation"))
    if mode == "retired-future":
        saved = public_activate(chain,
            guard_draft(chain, plan_id="explicit-retirement", retire=True),
            replacement=True, retire=True, start=chain.now + timedelta(minutes=5))
    captured = inputs(chain, revision=row["revision"]).model_copy(update={
        "runtime_generation": str(pipeline._runtime_generation)})
    with chain.plans._unit_of_work() as work:
        for bar in captured.five_minute_bars:
            work.history.upsert_five_minute(**bar.model_dump())
        if mode in {"missing", "sell-missing"}:
            from trade_plan_monitor.state.daily_models import DailyRecord
            work.daily.session.delete(work.daily.session.get(DailyRecord, row["id"]))
        work.commit()
    if mode in {"missing", "sell-missing", "retired-future"}:
        captured = captured.model_copy(update={"buy_suspension_revision": None})
    token = progress.begin_step(timeout_seconds=30)
    result = chain.client.portal.call(partial(pipeline.daily_evaluations.run_inputs,
        plan=chain.plan, inputs=captured))
    progress.complete_step(token, next_wake_at=chain.now + timedelta(seconds=30))
    from trade_plan_monitor.notifications.channels import InAppChannel
    from trade_plan_monitor.notifications.dispatcher import NotificationDispatcher
    from trade_plan_monitor.web.monitor_composition import _ProductionRuntimeState

    dispatcher = NotificationDispatcher(sessions, channels=(InAppChannel(),),
        clock=lambda: chain.now)
    state = _ProductionRuntimeState(config_path=chain.config, database_path=chain.database,
        engine=sessions.kw["bind"], session_factory=sessions, clock=pipeline._clock,
        request_controller=pipeline._controller, dispatcher=dispatcher,
        runtime_generation=lambda: pipeline._runtime_generation,
        progress_owner=lambda: progress_owner)
    state._pipeline = pipeline
    if mode in {"latched", "inherited", "retired-future"}:
        # Perform the real local storage check before observing it. No event is sent.
        check_context = state._notification_context()
        chain.client.portal.call(dispatcher.dispatch_pending)
        state._bind_notification_check(check_context)
    frozen = [None]

    def authority():
        if frozen[0] is not None:
            return frozen[0]
        token, configuration, plans = pipeline.runtime_status_snapshot()
        return RuntimeReadAuthority(token=token, lifecycle="RUNNING", health=None,
            progress=progress.snapshot(), configuration_revision=configuration, plans=plans,
            notification_configuration=state.notification_configuration_snapshot(),
            notification_service=state.notification_service_snapshot(
                runtime_generation=pipeline._runtime_generation,
                configuration_revision=configuration, plans=plans))

    owner = authority()
    assert owner.plans[0].completion is not None
    sessions = pipeline._runtime_status_sessions
    reader = RuntimeStatusReadService(sessions, authority, clock=lambda: chain.now)
    case = SimpleNamespace(chain=chain, pipeline=pipeline, row=row, result=result,
        sessions=sessions, engine=sessions.kw["bind"], reader=reader, owner=authority,
        frozen=frozen, version=saved["id"], mode=mode, original_version=original_version,
        captured=captured, progress=progress)
    yield case
    chain.client.portal.call(reader.stop)


@pytest.mark.parametrize("guarded_read_case", ["latched", "clear", "missing"], indirect=True)
def test_buy_suspension_reads_real_state_suppression_and_absence(guarded_read_case):
    case = guarded_read_case
    result = asyncio.run(case.reader.get_plan_readiness(version_id=case.version))
    guard = result.snapshot.buy_suspension
    assert guard is not None and guard.owner_plan_version_id == case.version
    assert guard.birth_activation_revision == 1
    assert guard.definition.condition.price_fen == 2420
    assert result.authority_granted is False and len(result.axes) == 6
    if case.mode == "missing":
        assert guard.outcome == "UNVERIFIED" and guard.state is None
        assert guard.state_revision is None and guard.maintenance.state == "UNKNOWN"
    else:
        assert guard.state_revision >= case.row["revision"]
        assert guard.maintenance.state == "PASS"
        assert guard.outcome == ("LATCHED" if case.mode == "latched" else "CLEAR_THROUGH_TARGET")
        if case.mode == "latched":
            assert result.rules[0].state == "BUY_SUSPENDED"
            assert result.rules[0].facts.root_outcome is None
            assert next(a for a in result.axes if a.axis == "DATA_EVALUATION").state == "PASS"
            assert result.summary == "READY_FOR_MONITORING"


@pytest.mark.parametrize("guarded_read_case", ["inherited", "retired-future"], indirect=True)
def test_buy_suspension_inherited_owner_and_explicit_retirement_start(guarded_read_case):
    case = guarded_read_case
    result = asyncio.run(case.reader.get_plan_readiness(version_id=case.version))
    guard = result.snapshot.buy_suspension
    assert case.version != case.original_version
    assert guard.maintenance.state == "PASS"
    assert result.rules[0].state == "BUY_SUSPENDED"
    if case.mode == "inherited":
        assert guard.owner_plan_version_id == case.original_version
        assert guard.birth_activation_revision == 1
        assert guard.state.trigger.close_fen == 2419
    else:
        assert guard.owner_plan_version_id is None and guard.state is None
        assert guard.outcome is None and guard.blocker == "STRATEGY_START_NOT_REACHED"
        assert guard.strategy_effective_from == case.chain.now + timedelta(minutes=5)
        assert guard.replacement.predecessor_guard_owner_plan_version_id == case.original_version


def test_buy_suspension_revision_churn_revokes_currency_without_erasing_trigger(
    guarded_read_case, monkeypatch,
):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = guarded_read_case
    original = projection.read_plan_readiness
    revisions = []

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        with case.chain.plans._unit_of_work() as work:
            row = work.daily.get_buy_suspension(symbol=case.chain.plan.symbol,
                owner_plan_version_id=case.original_version)
            work.daily.save(row["id"], kind="BUY_SUSPENSION", symbol=row["symbol"],
                lineage=row["lineage"], expected_revision=row["revision"], payload=row["payload"])
            work.commit()
            revisions.append(row["revision"])
        return result

    monkeypatch.setattr(projection, "read_plan_readiness", changed)
    result = asyncio.run(case.reader.get_plan_readiness(version_id=case.version))
    assert len(revisions) == 2 and revisions[1] > revisions[0]
    assert result.snapshot.buy_suspension.state.trigger.close_fen == 2419
    assert result.snapshot.buy_suspension.maintenance.reason == "CONTEXT_CHANGED"
    assert result.fresh_until is None and result.summary == "UNKNOWN"


def test_buy_suspension_stopped_owner_keeps_trigger_but_revokes_health(guarded_read_case):
    case = guarded_read_case
    case.frozen[0] = replace(case.owner(), lifecycle="STOPPED")
    result = asyncio.run(case.reader.get_plan_readiness(version_id=case.version))
    assert result.snapshot.buy_suspension.state.trigger.close_fen == 2419
    assert result.snapshot.buy_suspension.outcome == "LATCHED"
    assert result.snapshot.buy_suspension.maintenance.state == "UNKNOWN"
    assert result.summary == "UNKNOWN" and result.fresh_until is None


@pytest.mark.parametrize("pending", ["payload", "identity", "delete"])
def test_buy_suspension_read_preserves_pending_guard_changes(guarded_read_case, pending):
    import json

    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.web.plan_readiness_service import read_plan_readiness

    case = guarded_read_case
    writes = []

    def readonly(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            writes.append(statement)
            raise AssertionError("pending read flushed business state")

    with case.sessions() as session, session.begin():
        row = session.get(DailyRecord, case.row["id"])
        if pending == "payload":
            payload = json.loads(row.payload_json)
            payload["evaluated_at"] = (case.chain.now + timedelta(seconds=1)).isoformat()
            row.payload_json = json.dumps(payload)
        elif pending == "identity":
            row.id = "pending-rename"
        else:
            session.delete(row)
        before = row.id, row.payload_json
        event.listen(case.engine, "before_cursor_execute", readonly)
        try:
            with session.no_autoflush:
                read_plan_readiness(session, case.owner(), case.version, case.chain.now)
            assert (row.id, row.payload_json) == before
            assert row in (session.deleted if pending == "delete" else session.dirty)
        finally:
            event.remove(case.engine, "before_cursor_execute", readonly)
            session.rollback()
    assert writes == []


@pytest.mark.parametrize("guarded_read_case", ["sell-missing"], indirect=True)
def test_buy_suspension_missing_guard_does_not_replace_actual_sell_comparison(guarded_read_case):
    case = guarded_read_case
    result = asyncio.run(case.reader.get_plan_readiness(version_id=case.version))
    sell = result.rules[0]
    assert sell.facts.side == "SELL" and sell.state == "CONDITION_TRUE"
    assert sell.facts.root_outcome == "SATISFIED"
    assert case.result.snapshot["signals"][0]["executable_qty"] == 100
    assert sell.facts.execution.reason not in {
        "BUY_SUSPENSION_LATCHED", "BUY_SUSPENSION_UNVERIFIED", "HISTORY_PENDING"}
    assert result.snapshot.buy_suspension.outcome == "UNVERIFIED"


@pytest.mark.parametrize("guarded_read_case", ["missing"], indirect=True)
def test_buy_suspension_reviewed_absent_predecessor_receipt_does_not_recover(guarded_read_case):
    from tests.integration.test_plan_buy_suspension_activation import guard_draft, public_review

    case = guarded_read_case
    saved, _command = public_review(case.chain,
        guard_draft(case.chain, plan_id="reviewed-only-retirement", retire=True),
        replacement=True, retire=True)
    result = asyncio.run(case.reader.get_plan_readiness(version_id=saved["id"]))
    guard = result.snapshot.buy_suspension
    assert guard.maintenance.state == "UNKNOWN" and guard.state is None
    assert guard.replacement.predecessor_state_revision == 0
    assert guard.replacement.predecessor_state_hash is None
    assert guard.replacement.predecessor_guard_owner_plan_version_id == case.original_version
    assert guard.replacement.predecessor_guard_owner_hash is not None
    assert result.summary == "NEEDS_REVIEW" and result.authority_granted is False
    with case.chain.plans._unit_of_work() as work:
        active = work.plans.get_active(case.chain.plan.symbol)
        assert active.plan_version_id == case.original_version
        assert work.daily.get_buy_suspension(symbol=case.chain.plan.symbol,
            owner_plan_version_id=case.original_version) is None


def test_buy_suspension_missing_calendar_keeps_latch_without_current_monitoring(guarded_read_case):
    from sqlalchemy import delete

    from trade_plan_monitor.state.models import TradingCalendar

    case = guarded_read_case
    with case.chain.plans._unit_of_work() as work:
        work.daily.session.execute(delete(TradingCalendar).where(
            TradingCalendar.exchange == case.chain.plan.market,
            TradingCalendar.cal_date == case.chain.now.date()))
        work.commit()
    result = asyncio.run(case.reader.get_plan_readiness(version_id=case.version))
    guard = result.snapshot.buy_suspension
    assert guard.target is None and guard.outcome == "LATCHED"
    assert guard.state.trigger.close_fen == 2419 and guard.maintenance.state == "UNKNOWN"
    assert result.summary == "UNKNOWN" and result.fresh_until is None


@pytest.fixture
def current(tmp_path, monkeypatch):
    case = _current_status(tmp_path, monkeypatch)
    try:
        yield case
    finally:
        case.close()


@pytest.fixture
def legacy_current(tmp_path, monkeypatch):
    """Run the real producer with its old omission of the private observation sink."""
    from trade_plan_monitor.runtime import daily_service

    original = daily_service.confirm_signal

    def old_confirmation(*args, **kwargs):
        kwargs.pop("_evaluation_observer", None)
        return original(*args, **kwargs)

    monkeypatch.setattr(daily_service, "confirm_signal", old_confirmation)
    case = _current_status(tmp_path, monkeypatch)
    try:
        yield case
    finally:
        case.close()


def read(case, version_id=None):
    return asyncio.run(case.reader.get_plan_readiness(
        version_id=version_id or case.result.snapshot["plan_version_id"]))


def test_missing_ordinary_output_is_unknown_not_false_or_an_invented_evaluation(legacy_current):
    current = legacy_current
    result = read(current)
    assert result.authority_granted is False
    assert {axis.axis for axis in result.axes} == AXES
    expected = {(kind, identity) for kind, identities in (
        ("ORDINARY_RULE", [r.rule_id for r in current.plan.ordinary_rules]),
        ("ALERT_RULE", [r.rule_id for r in current.plan.alert_rules]),
    ) for identity in identities}
    assert {(r.facts.owner_kind, r.facts.owner_id) for r in result.rules} == expected
    ordinary = [r for r in result.rules if r.facts.owner_kind == "ORDINARY_RULE"]
    assert ordinary and all(r.state == "UNKNOWN" for r in ordinary)
    assert all(r.reason == "DEPENDENCY_UNVERIFIED" for r in ordinary)
    assert all(r.facts.root_outcome is None for r in ordinary)
    assert all(r.facts.evaluated_at is None and r.facts.evaluated_target is None for r in ordinary)
    data = next(axis for axis in result.axes if axis.axis == "DATA_EVALUATION")
    assert data.state == "UNKNOWN" and data.reason == "DEPENDENCY_UNVERIFIED"
    assert result.summary != "READY_FOR_MONITORING"


def test_actual_alert_false_keeps_complete_evidence_instead_of_signal_inference(current):
    assert current.result.snapshot["alerts"][0]["outcome"] == "UNSATISFIED"
    result = read(current)
    alert = next(r for r in result.rules if r.facts.owner_kind == "ALERT_RULE")
    assert alert.state == "CONDITION_FALSE"
    assert alert.facts.root_outcome == "UNSATISFIED"
    assert alert.facts.leaves and all(leaf.evidence_refs for leaf in alert.facts.leaves)
    assert alert.facts.observation.availability == "CURRENT"
    assert alert.facts.evaluated_at == current.now
    assert alert.facts.leaves[0].condition_path == "condition"


@pytest.mark.parametrize("authority", ["absent", "stopped", "raises"])
def test_persisted_or_cached_rows_cannot_certify_current_owner(current, authority):
    if authority == "absent":
        current.current[0] = None
    elif authority == "stopped":
        current.current[0] = replace(current.current[0], lifecycle="STOPPED")
    else:
        def unavailable():
            raise RuntimeError("owner unavailable")
        current.reader._authority = unavailable
    result = read(current)
    runtime = next(a for a in result.axes if a.axis == "RUNTIME_OWNERSHIP")
    assert runtime.state == "UNKNOWN"
    assert runtime.reason == "AUTHORITY_UNAVAILABLE"
    assert all(r.state == "UNKNOWN" for r in result.rules)
    assert result.fresh_until is None
    assert result.summary != "READY_FOR_MONITORING"


def test_unknown_version_does_not_borrow_the_active_sibling(current):
    assert read(current, str(uuid4())) is None


def test_real_read_has_no_business_sql_network_or_new_evaluation(current, monkeypatch):
    writes, network = [], []

    def sql(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split()[0].upper() in {
            "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP",
        }:
            writes.append(statement)
            raise AssertionError("readiness attempted a business write")

    def denied(*args, **kwargs):
        network.append(True)
        raise AssertionError("readiness attempted external I/O or evaluation")

    from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService
    # Windows creates its event-loop wakeup socketpair before the read begins.
    with asyncio.Runner() as runner:
        runner.get_loop()
        event.listen(current.engine, "before_cursor_execute", sql)
        with monkeypatch.context() as patch:
            patch.setattr(socket.socket, "connect", denied)
            patch.setattr(socket.socket, "connect_ex", denied)
            patch.setattr(requests.Session, "request", denied)
            patch.setattr(httpx.Client, "send", denied)
            patch.setattr(httpx.AsyncClient, "send", denied)
            patch.setattr(DailyRuntimeEvaluationService, "run_inputs", denied)
            try:
                result = runner.run(current.reader.get_plan_readiness(
                    version_id=current.result.snapshot["plan_version_id"]))
            finally:
                event.remove(current.engine, "before_cursor_execute", sql)
    assert result.authority_granted is False
    assert writes == [] and network == []


@pytest.fixture
def saved(state):
    from trade_plan_monitor.domain.plan_validation import PlanValidationResult
    from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    identity, draft = _save(state)
    _confirm(state, identity)
    now = _NOW + timedelta(minutes=3)
    with SqlAlchemyUnitOfWork(state.sessions, clock=lambda: now) as work:
        work.plans.activate(draft.to_executable(), expected_revision=0,
                            validation=PlanValidationResult(issues=()))
        work.commit()
    return SimpleNamespace(**vars(state), identity=identity, draft=draft, now=now,
        reader=RuntimeStatusReadService(state.sessions, lambda: None, clock=lambda: now))


def test_new_coverage_bundle_during_read_cannot_keep_the_old_review(saved, monkeypatch):
    from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
    from trade_plan_monitor.web import plan_readiness_service as projection

    original = projection.read_readiness_binding
    calls = []

    def changed(*args):
        if not calls:
            with saved.work() as work:
                store = SourceCoverageStore(work.daily.session)
                previous = store.latest(saved.identity)
                store.append(saved.identity, previous.assessment, inputs=previous.inputs,
                    expected_revision=previous.revision, command_id="readiness-new-bundle",
                    now=saved.now)
                work.commit()
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    result = asyncio.run(saved.reader.get_plan_readiness(version_id=saved.identity))
    assert len(calls) == 2
    assert result.summary == "NEEDS_REVIEW"
    assert next(a for a in result.axes if a.axis == "REVIEW_ACTIVATION").state == "BLOCKED"


def test_actual_review_change_between_snapshots_is_reloaded(state, monkeypatch):
    from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
    from trade_plan_monitor.web import plan_readiness_service as projection
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    identity, _ = _save(state)
    reader = RuntimeStatusReadService(state.sessions, lambda: None,
                                     clock=lambda: _NOW + timedelta(minutes=3))
    original = projection.read_readiness_binding
    receipts = []

    def changed(*args):
        if not receipts:
            _confirm(state, identity)
            with state.work() as work:
                details = work.plans.get_version_details(identity)
                receipts.append(SourceCoverageStore(work.daily.session).receipt(
                    details.review_id).evidence_hash)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    result = asyncio.run(reader.get_plan_readiness(version_id=identity))
    assert result.snapshot.context.review_receipt_hash == receipts[0]


@pytest.fixture
def saved_open_cost(state):
    """A retained-cost policy owns book changes; market value has no such dependency."""
    from tests.integration.test_market_linkage_review import source_mapping
    from tests.unit.test_p3_policy_contract import p3_payload

    from trade_plan_monitor.ai.daily_review import build_daily_review
    from trade_plan_monitor.domain.p3_validation import P3PlanDraft
    from trade_plan_monitor.domain.plan_validation import PlanValidationResult
    from trade_plan_monitor.state.daily_review_store import save_daily_draft
    from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    draft = P3PlanDraft.model_validate(p3_payload("OPEN_COST_CAP"))
    source, mapping = source_mapping(draft)
    assert build_daily_review(draft, mapping, source).issues == ()
    with state.work() as work:
        identity = save_daily_draft(work, draft, mapping=mapping, source_text=source,
                                    clock=lambda: _NOW)
        work.commit()
    _confirm(state, identity)
    now = _NOW + timedelta(minutes=3)
    with SqlAlchemyUnitOfWork(state.sessions, clock=lambda: now) as work:
        work.plans.activate(draft.to_executable(), expected_revision=0,
                            validation=PlanValidationResult(issues=()))
        work.commit()
    return SimpleNamespace(**vars(state), identity=identity, draft=draft, now=now,
        reader=RuntimeStatusReadService(state.sessions, lambda: None, clock=lambda: now))


@pytest.mark.parametrize("repeated", [False, True])
def test_relevant_real_book_revision_is_reread_and_churn_is_unknown(
    saved_open_cost, monkeypatch, repeated,
):
    from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
    from trade_plan_monitor.state.p3_models import CapitalBook
    from trade_plan_monitor.web import plan_readiness_service as projection

    saved = saved_open_cost

    def advance():
        with saved.sessions() as session, session.begin():
            repo = CapitalRepository(session)
            previous = repo.get(saved.draft.symbol)
            revision = 0 if previous is None else previous.revision
            book = CapitalBook.build(symbol=saved.draft.symbol, revision=revision + 1,
                inventory_revision=1, lots=(), updated_at=saved.now)
            repo.write(book, expected_revision=revision, command_id=f"book-{revision}",
                request_hash="a" * 64, kind="OPENING" if revision == 0 else "RECONCILIATION",
                now=saved.now, details={})

    advance()
    original = projection.read_readiness_binding
    calls = []

    def changed(*args):
        if repeated or not calls:
            advance()
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    result = asyncio.run(saved.reader.get_plan_readiness(version_id=saved.identity))
    assert len(calls) == 2
    if repeated:
        assert result.summary == "UNKNOWN"
        assert all(a.reason == "CONTEXT_CHANGED" for a in result.axes)
    else:
        assert result.snapshot.context.book_revision == 2


def test_read_context_change_does_not_certify_an_old_activation(current, monkeypatch):
    from sqlalchemy import update

    from trade_plan_monitor.state.models import ActivePlan, PlanActivationState
    from trade_plan_monitor.web import plan_readiness_service as projection

    original = projection.read_readiness_binding
    calls = []

    def changed(*args):
        if not calls:
            with current.engine.begin() as connection:
                for model in (ActivePlan, PlanActivationState):
                    connection.execute(update(model).where(model.symbol == current.plan.symbol)
                        .values(revision=model.revision + 1))
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    result = read(current)
    assert len(calls) == 2
    assert result.snapshot.context.activation_revision == 2
    assert all(r.state == "AWAITING_FIRST_EVALUATION" for r in result.rules)
    assert all(r.facts.root_outcome is None for r in result.rules)


def test_generation_replacement_retries_and_preserves_no_current_old_proof(current):
    before = current.current[0]
    generation = uuid4()
    after = replace(before, token="replacement",
                    progress=replace(before.progress, runtime_generation=generation))
    calls = []

    def owner():
        calls.append(True)
        return before if len(calls) == 1 else after

    current.reader._authority = owner
    result = read(current)
    assert len(calls) == 4
    assert result.snapshot.context.runtime_generation == generation
    assert all(r.state == "UNKNOWN" for r in result.rules)


@pytest.mark.parametrize("missing", ["plan", "version", "hash", "family"])
def test_running_process_cannot_certify_an_unowned_requested_version(current, missing):
    owner = current.current[0]
    plan = owner.plans[0]
    changes = {"version": {"plan_version_id": str(uuid4())}, "hash": {"plan_hash": "f" * 64},
               "family": {"plan_family": "LEGACY_LOW_BUY"}}
    plans = () if missing == "plan" else (replace(plan, **changes[missing]),)
    current.current[0] = replace(owner, plans=plans)
    result = read(current)
    runtime = next(axis for axis in result.axes if axis.axis == "RUNTIME_OWNERSHIP")
    assert runtime.state == "UNKNOWN"
    assert runtime.reason == "AUTHORITY_UNAVAILABLE"


@pytest.mark.parametrize("attack", ["unknown-outcome", "missing-outcome", "unknown-key",
                                   "invalid-bar-ids", "wrong-condition"])
def test_untyped_alert_evidence_cannot_fabricate_complete_false(attack):
    from pydantic import TypeAdapter

    from trade_plan_monitor.domain.unified_plan_models import UnifiedCondition
    from trade_plan_monitor.web.plan_readiness_service import _leaves

    condition = TypeAdapter(UnifiedCondition).validate_python({
        "type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 1200})
    evidence = dict(condition=condition.model_dump(mode="json"), outcome="UNSATISFIED",
                    bar_ids=["actual-bar"])
    if attack == "unknown-outcome":
        evidence["outcome"] = "NO_RESULT"
    elif attack == "missing-outcome":
        del evidence["outcome"]
    elif attack == "unknown-key":
        evidence["clientVerified"] = True
    elif attack == "invalid-bar-ids":
        evidence["bar_ids"] = "not-a-list"
    else:
        evidence["condition"] = evidence["condition"] | {"price_fen": 1100}
    result = _leaves(condition, "condition", evidence, reference="actual-evaluation")
    assert result[0].state == "UNKNOWN"
    assert result[0].reason == "DEPENDENCY_UNVERIFIED"


def test_original_risk_is_unknown_without_bounded_provenance_and_never_uses_sibling(
    legacy, monkeypatch,
):
    from trade_plan_monitor.domain.risk_scope import risk_identity
    from trade_plan_monitor.state import source_action_authority
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    case = legacy()

    def forbidden(*args, **kwargs):
        pytest.fail("readiness must not scan historical cutover membership")

    monkeypatch.setattr(source_action_authority, "_membership_root", forbidden)
    reader = RuntimeStatusReadService(case.sessions, lambda: None,
                                     clock=lambda: _NOW + timedelta(minutes=3))
    result = asyncio.run(reader.get_plan_readiness(version_id=case.id))
    risks = [rule for rule in result.rules if rule.facts.owner_kind == "RISK_BRANCH"]
    assert {rule.facts.owner_id for rule in risks} == {
        risk_identity(branch) for branch in case.draft.risk_branches}
    retained = next(rule for rule in risks if rule.facts.owner_id == case.risk["kind"])
    assert retained.state == "UNKNOWN"
    assert retained.facts.observation.evidence_refs == ("risk:" + case.cause_id,)
    assert retained.facts.observation.availability == "CACHED"
    assert all(rule.facts.root_outcome is None for rule in risks)
    assert all(not leaf.condition_path.startswith("risk_branches[")
               for rule in risks for leaf in rule.facts.leaves)
    no_condition = {risk_identity(branch) for branch in case.draft.risk_branches
                    if branch.condition is None}
    assert all(rule.facts.leaves == () for rule in risks if rule.facts.owner_id in no_condition)


def test_no_completed_evaluation_is_first_evaluation_not_false(saved):
    result = asyncio.run(saved.reader.get_plan_readiness(version_id=saved.identity))
    assert all(rule.state == "AWAITING_FIRST_EVALUATION" for rule in result.rules)
    assert all(rule.facts.evaluated_at is None and rule.facts.root_outcome is None
               for rule in result.rules)


@pytest.mark.parametrize("owner", ["assessment", "receipt"])
def test_same_summary_cannot_hide_actual_proof_or_receipt_row_change(saved, monkeypatch, owner):
    from sqlalchemy import text, update

    from trade_plan_monitor.state.source_coverage_models import (
        COVERAGE_TRIGGER_SQL,
        CoverageAssessmentRow,
        CoverageReviewRow,
    )
    from trade_plan_monitor.state.source_coverage_store import SourceCoverageIntegrityError
    from trade_plan_monitor.web import plan_readiness_service as projection

    original = projection.read_readiness_binding
    changed_once = []

    def corrupt(*args):
        if not changed_once:
            table = "source_coverage_" + ("assessment" if owner == "assessment" else "review")
            trigger = "pma_seal_" + table + "_update"
            with saved.engine.begin() as connection:
                connection.execute(text("DROP TRIGGER " + trigger))
                if owner == "assessment":
                    connection.execute(update(CoverageAssessmentRow).where(
                        CoverageAssessmentRow.plan_version_id == saved.identity
                    ).values(command_id="changed-outside-the-public-summary"))
                else:
                    connection.execute(update(CoverageReviewRow).where(
                        CoverageReviewRow.plan_version_id == saved.identity
                    ).values(review_revision=2))
                connection.execute(text(COVERAGE_TRIGGER_SQL[trigger]))
            changed_once.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", corrupt)
    with pytest.raises(SourceCoverageIntegrityError):
        asyncio.run(saved.reader.get_plan_readiness(version_id=saved.identity))


@pytest.mark.parametrize("repeated", [False, True])
def test_relevant_actual_inventory_change_is_not_joined_to_the_old_proof(
    execution_case, monkeypatch, repeated,
):
    from copy import deepcopy

    from trade_plan_monitor.runtime.status_authority import (
        condition_completion_matches,
        condition_market_completion_matches,
    )
    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.web import plan_readiness_service as projection

    current = execution_case
    initial = read(current)
    initial_rules = {r.facts.owner_id: r for r in initial.rules}
    buy = next(r for r in initial.rules if r.facts.side == "BUY")
    assert buy.state == "CONDITION_TRUE" and buy.facts.execution.eligible is True
    assert buy.facts.execution.observation.availability == "CURRENT"
    assert next(r for r in initial.rules if r.facts.side == "SELL").state == "CONDITION_FALSE"
    assert next(r for r in initial.rules if r.facts.owner_kind == "ALERT_RULE").state == (
        "CONDITION_FALSE")
    proof = current.owner().plans[0].completion
    original_proof = deepcopy(proof)
    original_snapshot = deepcopy(current.result.snapshot)
    record_id = proof.input_stamp.immutable_record_id
    result_hash = proof.result_hash
    signal_id = buy.facts.execution.signal_id
    identities = (record_id, "evaluation-head-" + current.plan.symbol, signal_id)

    def records():
        with current.sessions() as session:
            rows = {}
            for identity in identities:
                row = session.get(DailyRecord, identity)
                assert row is not None
                rows[identity] = tuple(getattr(row, c.name) for c in DailyRecord.__table__.columns)
            return rows

    original_rows = records()
    with current.sessions() as session, session.begin():
        assert condition_completion_matches(session, proof=proof,
            snapshot=original_snapshot, now=current.now)
    original = projection.read_readiness_binding
    calls = []
    before = current.result.snapshot["inventory"]["revision"]
    assert initial.snapshot.context.inventory_revision == before

    def changed(*args):
        if repeated or not calls:
            with current.work() as work:
                row = work.daily.get("simulation-position-" + current.plan.symbol)
                work.daily.save(row["id"], kind=row["kind"], symbol=row["symbol"],
                    lineage=row["lineage"], payload=row["payload"],
                    expected_revision=row["revision"])
                work.commit()
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    result = read(current)
    assert len(calls) == 2
    with current.work() as work:
        position = work.daily.get("simulation-position-" + current.plan.symbol)
    assert position["revision"] == before + (2 if repeated else 1)
    assert current.owner().plans[0].completion is proof
    assert proof == original_proof
    assert proof.input_stamp.immutable_record_id == record_id
    assert proof.result_hash == result_hash
    assert current.result.snapshot == original_snapshot
    assert records() == original_rows
    with current.sessions() as session, session.begin():
        assert condition_market_completion_matches(session, proof=proof,
            snapshot=original_snapshot, now=current.now)
        assert not condition_completion_matches(session, proof=proof,
            snapshot=original_snapshot, now=current.now)
    if repeated:
        assert result.snapshot.context.inventory_revision < position["revision"]
        assert next(a for a in result.axes if a.axis == "DATA_EVALUATION").state == "UNKNOWN"
        assert all(a.reason == "CONTEXT_CHANGED" for a in result.axes)
        assert all(rule.state == "UNKNOWN" for rule in result.rules)
        assert all(rule.facts.root_outcome is None for rule in result.rules)
        assert all(rule.facts.execution.eligible is None for rule in result.rules)
        assert result.summary == "UNKNOWN" and result.fresh_until is None
    else:
        assert result.snapshot.context.inventory_revision == before + 1
        assert next(a for a in result.axes if a.axis == "DATA_EVALUATION").state == "PASS"
        for rule in result.rules:
            previous = initial_rules[rule.facts.owner_id]
            assert rule.state == previous.state
            assert rule.facts.root_outcome == previous.facts.root_outcome
            assert rule.facts.evaluated_target == previous.facts.evaluated_target
            assert rule.facts.evaluated_at == previous.facts.evaluated_at
            assert rule.facts.leaves == previous.facts.leaves
            assert rule.facts.observation.availability == "CURRENT"
            assert rule.facts.observation.evidence_refs == previous.facts.observation.evidence_refs
        observed = next(r.facts.execution for r in result.rules if r.facts.side == "BUY")
        assert observed.eligible is None and observed.observation.availability == "CACHED"
        assert observed.signal_id == signal_id
        assert observed.signal_revision == buy.facts.execution.signal_revision
        assert observed.approved_quantity == buy.facts.execution.approved_quantity
        assert observed.approved_quantity > 0
        assert observed.consumed == buy.facts.execution.consumed
        assert observed.blockers == buy.facts.execution.blockers
        assert result.authority_granted is False and result.fresh_until is None


def test_missing_assurance_storage_stays_unknown_without_creating_tables(legacy):
    from sqlalchemy import inspect

    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    case = legacy(upgraded=False)
    tables = inspect(case.engine).get_table_names()
    reader = RuntimeStatusReadService(case.sessions, lambda: None,
                                     clock=lambda: _NOW + timedelta(minutes=3))
    result = asyncio.run(reader.get_plan_readiness(version_id=case.id))
    source = next(a for a in result.axes if a.axis == "SOURCE_COVERAGE")
    assert source.state == "UNKNOWN" and source.reason == "UPGRADE_REQUIRED"
    assert inspect(case.engine).get_table_names() == tables


def test_expired_progress_cannot_be_renewed_by_a_read(current):
    owner = current.current[0]
    current.current[0] = replace(owner, progress=replace(
        owner.progress, progress_due_at=current.now))
    result = read(current)
    assert next(a for a in result.axes if a.axis == "RUNTIME_OWNERSHIP").state == "UNKNOWN"
    assert all(rule.state == "UNKNOWN" for rule in result.rules)


def test_cancelled_observer_retains_the_real_read_lease_until_physical_drain(saved, monkeypatch):
    from threading import Event

    from trade_plan_monitor.web import plan_readiness_service as projection

    original = projection.read_plan_readiness
    release = Event()

    async def scenario():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()

        def blocked(*args):
            result = original(*args)
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3)
            return result

        monkeypatch.setattr(projection, "read_plan_readiness", blocked)
        task = asyncio.create_task(saved.reader.get_plan_readiness(version_id=saved.identity))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert saved.reader.outstanding_work == 1
            with pytest.raises(TimeoutError):
                await saved.reader.stop(timeout=0.01)
        finally:
            release.set()
            await saved.reader.stop(timeout=2)
        assert saved.reader.outstanding_work == 0

    asyncio.run(scenario())


def test_complete_utf8_view_bound_rejects_instead_of_omitting_rules(saved, monkeypatch):
    from trade_plan_monitor.web import plan_readiness_service as projection
    from trade_plan_monitor.web.errors import ApiError, ApiErrorCode

    assert projection.MAX_READINESS_BYTES == 1024 * 1024
    result = asyncio.run(saved.reader.get_plan_readiness(version_id=saved.identity))
    assert len(result.rules) == len(saved.draft.ordinary_rules) + len(saved.draft.risk_branches)
    assert len(result.axes) == 6
    full_size = len(result.model_dump_json(by_alias=True).encode("utf-8"))
    monkeypatch.setattr(projection, "MAX_READINESS_BYTES", full_size - 1)
    with pytest.raises(ApiError) as error:
        asyncio.run(saved.reader.get_plan_readiness(version_id=saved.identity))
    assert error.value.code == ApiErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.parametrize("closed", ["pause", "shutdown"])
def test_readiness_obeys_existing_read_owner_storage_and_shutdown_fence(saved, closed):
    from trade_plan_monitor.web.errors import ApiError, ApiErrorCode

    if closed == "pause":
        saved.reader._read_owner.pause_storage("existing-owner")
    else:
        saved.reader.begin_shutdown()
    with pytest.raises(ApiError) as error:
        asyncio.run(saved.reader.get_plan_readiness(version_id=saved.identity))
    assert error.value.code == ApiErrorCode.SERVICE_UNAVAILABLE
