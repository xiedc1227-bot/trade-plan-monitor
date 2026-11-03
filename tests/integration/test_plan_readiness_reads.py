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
from tests.integration.test_runtime_status_projection import _current_status
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_authority import _confirm, _save
from tests.integration.test_source_coverage_authority_save import _NOW
from tests.integration.test_source_coverage_authority_save import state as state

AXES = {
    "SOURCE_COVERAGE", "REVIEW_ACTIVATION", "RUNTIME_OWNERSHIP",
    "DATA_EVALUATION", "INVENTORY_CAPITAL", "NOTIFICATION_DELIVERY",
}


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


@pytest.mark.parametrize("repeated", [False, True])
def test_relevant_real_book_revision_is_reread_and_churn_is_unknown(saved, monkeypatch, repeated):
    from trade_plan_monitor.state.p3_capital_repository import CapitalRepository
    from trade_plan_monitor.state.p3_models import CapitalBook
    from trade_plan_monitor.web import plan_readiness_service as projection

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


def test_relevant_actual_inventory_change_is_not_joined_to_the_old_proof(current, monkeypatch):
    from trade_plan_monitor.web import plan_readiness_service as projection

    original = projection.read_readiness_binding
    calls = []
    before = current.result.snapshot["inventory"]["revision"]

    def changed(*args):
        if not calls:
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
    assert result.snapshot.context.inventory_revision == before + 1
    assert next(a for a in result.axes if a.axis == "DATA_EVALUATION").state == "UNKNOWN"
    assert all(rule.state == "UNKNOWN" for rule in result.rules)


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
