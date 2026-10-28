"""Frozen replay authority belongs to one decoded session and one private engine."""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import update
from tests.integration.test_monitor_loop_cycle import cycle_input, frames
from tests.integration.test_monitor_loop_plan_switch import continuity_calendar, continuity_input
from tests.unit.test_monitor_loop_schedule import SHANGHAI, calendar
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.backtest.loop_runner import LoopRunner
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    ActivePlan,
    AuditLog,
    PlanActivationState,
    PlanSource,
    PlanVersion,
)
from trade_plan_monitor.state.simulation import (
    SimulationAuthorityError,
    SimulationCommand,
    simulate_inventory,
)
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_store import SourceCoverageIntegrityError
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def test_real_frozen_cycle_keeps_its_historical_fills_without_claiming_live_coverage(tmp_path):
    with LoopSession(tmp_path, cycle_input(), calendar()) as session:
        result = LoopRunner(session).run(frames())
        assert result.fills == result.intents == 2
        assert session.account().cash.balance_fen == 503590
        assert session.inventory()["total_qty"] == 200


def test_real_scheduled_activation_uses_frozen_source_and_the_original_shared_transition(tmp_path):
    with LoopSession(tmp_path, continuity_input(), continuity_calendar()) as session:
        changed = session.advance(datetime(2026, 8, 21, 9, tzinfo=SHANGHAI))
        assert session.selection.version.version_id == "p2"
        assert any(row.kind == "REPLACED" for row in changed)
        with session.work() as work:
            active = work.plans.get_active(session.plan.symbol)
            assert active.plan_version_id == session.details.id and active.revision == 2


def _read(session):
    with session.work() as work:
        return session._source_authority_reader(work, session.details.id)


def _ready(session):
    for frame in frames(end=35):
        result = session.evaluate(frame.runtime)
    signal, = result.snapshot["signals"]
    assert signal["executable_qty"] == 100
    with session.work() as work:
        row = work.daily.get(signal["signal_id"])
        inventory = DailyAccounting(work.daily).snapshot(session.plan.symbol, session.now.date())
    return SimulationCommand(plan_version_id=UUID(session.details.id), cause_id=row["id"],
        expected_cause_revision=row["revision"], expected_inventory_revision=inventory["revision"],
        quantity=100)


def test_capability_has_only_an_independent_observation_role_and_is_not_reissued(tmp_path):
    from trade_plan_monitor.backtest.loop_source_authority import _issue_loop_source_authority

    with LoopSession(tmp_path, cycle_input(), calendar()) as session:
        basis = _read(session)
        assert basis.basis == "REPLAY_OBSERVATION"
        assert not hasattr(basis, "coverage_complete") and not hasattr(basis, "status")
        assert "_source_authority_reader" not in SimulationCommand.model_fields
        for owner in (SimpleNamespace(), session):
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                _issue_loop_source_authority(owner)


@pytest.mark.parametrize("clone", [False, True])
def test_capability_cannot_move_to_another_engine_even_with_the_identical_database(tmp_path, clone):
    with LoopSession(tmp_path / "original", cycle_input(), calendar()) as session:
        path = session.engine.url.database
        if clone:
            path = str(tmp_path / "copy.sqlite")
            with sqlite3.connect(session.engine.url.database) as original:
                with sqlite3.connect(path) as copied:
                    original.backup(copied)
        other = create_sqlite_engine(path)
        try:
            factory = create_session_factory(other)
            with SqlAlchemyUnitOfWork(factory, clock=lambda: session.now) as work:
                with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                    session._source_authority_reader(work, session.details.id)
        finally:
            other.dispose()


@pytest.mark.parametrize("mutation", ["equal-input-clone", "nested-input", "selection", "view",
                                    "closed"])
def test_capability_retains_original_object_bytes_and_exact_session_context(tmp_path, mutation):
    value = cycle_input()
    if mutation == "nested-input":
        plan = value.schedule.entries[0].version.snapshot
        buy = plan.ordinary_rules[0].model_copy(update={"condition": dict(
            type="DAILY_PRICE_COMPARE", field="close", offset=0, comparator="GT",
            reference=dict(mode="DYNAMIC", indicator="MA20",
                offset=0, formula_version="daily-ta-v2", parameters={"period": 20}))})
        value = cycle_input(plan=plan.model_copy(update={"ordinary_rules": (buy,),
            "monitoring": type(plan).model_validate(unified_payload()).monitoring}))
    with LoopSession(tmp_path, value, calendar()) as session:
        assert _read(session).basis == "REPLAY_OBSERVATION"
        if mutation == "equal-input-clone":
            session.run_input = type(session.run_input).model_validate_json(
                session.run_input.model_dump_json())
        elif mutation == "nested-input":
            session.run_input.schedule.entries[0].version.snapshot.ordinary_rules[
                0].condition.reference.parameters["period"] = 21
        elif mutation == "selection":
            session.selection = session.selection.model_copy(update={"activated_at": session.now})
        elif mutation == "view":
            session.details = replace(session.details, content_hash="a" * 64)
        else:
            session._closed = True
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _read(session)


@pytest.mark.parametrize("mutation", ["policy", "plan-hash", "plan-revision", "manifest", "review",
    "activation-time", "self-consistent-epoch", "registration-time"])
def test_actual_sql_owners_cannot_be_replaced_by_self_consistent_local_metadata(tmp_path, mutation):
    with LoopSession(tmp_path, continuity_input(), continuity_calendar()) as session:
        with session.work() as work:
            sql = work.daily.session
            if mutation == "policy":
                changed = session.plan.model_copy(update={"position":
                    session.plan.position.model_copy(
                        update={"max_qty": session.plan.position.max_qty + 100})})
                sql.execute(update(PlanVersion).values(payload_json=dump_plan_json(changed),
                    plan_hash=plan_sha256(changed)))
            elif mutation == "plan-hash":
                sql.execute(update(PlanVersion).values(plan_hash="b" * 64))
            elif mutation == "plan-revision":
                sql.execute(update(PlanVersion).values(revision=2))
            elif mutation == "manifest":
                sql.execute(update(PlanSource).values(source_text='{"forged":true}',
                    source_hash=sha256(b'{"forged":true}').hexdigest()))
            elif mutation == "review":
                old = work.daily.get("review-" + session.details.id)
                sql.execute(update(DailyRecord).where(DailyRecord.id == old["id"]).values(
                    payload_json=canonical(old["payload"] | dict(evidence_hash="c" * 64))))
            elif mutation == "activation-time":
                stamp = session.now.isoformat()
                sql.execute(update(ActivePlan).values(activated_at=stamp))
                sql.execute(update(PlanActivationState).values(changed_at=stamp))
            elif mutation == "self-consistent-epoch":
                sql.execute(update(ActivePlan).values(revision=2))
                sql.execute(update(PlanActivationState).values(revision=2))
                sql.execute(update(PlanVersion).values(revision=2))
            else:
                stamp = (session.now - timedelta(seconds=1)).isoformat()
                sql.execute(update(PlanVersion).values(created_at=stamp))
                sql.execute(update(PlanSource).values(created_at=stamp))
                sql.execute(update(DailyRecord).where(DailyRecord.kind == "REVIEW").values(
                    created_at=stamp, updated_at=stamp))
            work.commit()
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _read(session)


@pytest.mark.parametrize("claim", ["none", "current", "coverage", "version", "revision"])
def test_simulation_private_reader_rejects_counterfeit_roles_and_bindings(tmp_path, claim):
    with LoopSession(tmp_path, cycle_input(), calendar()) as session:
        command = _ready(session)
        before = session.inventory()
        value = dict(basis="REPLAY_OBSERVATION", plan_version_id=session.details.id,
            activation_revision=1, risk_rows=())
        if claim == "current":
            value["basis"] = "CURRENT"
        elif claim == "coverage":
            value["coverage_complete"] = True
        elif claim == "version":
            value["plan_version_id"] = "another-version"
        elif claim == "revision":
            value["activation_revision"] = 2
        with session.work() as work, pytest.raises(SimulationAuthorityError):
            simulate_inventory(work, command, session.now,
                _source_authority_reader=lambda *_a, **_kw: None if claim == "none" else
                    SimpleNamespace(**value))
        assert session.inventory() == before


def test_frozen_review_without_explicit_private_reader_never_becomes_live_coverage(tmp_path):
    with LoopSession(tmp_path, cycle_input(), calendar()) as session:
        command = _ready(session)
        before = session.inventory()
        with session.work() as work, pytest.raises(SourceCoverageIntegrityError):
            simulate_inventory(work, command, session.now)
        assert session.inventory() == before


def test_completed_account_receipt_is_read_before_any_new_source_or_execution_check(tmp_path):
    from trade_plan_monitor.backtest.loop_account import LoopAccountParticipant

    events = []
    with LoopSession(tmp_path, cycle_input(), calendar()) as session:
        LoopRunner(session, emit=events.append).run(frames(end=37))
        receipt, = (event.receipt for event in events if event.status == "FILLED")
        before = session.account()

        def forbidden(*_args, **_kwargs):
            raise AssertionError("A completed receipt must not execute or read source again")

        with session.work() as work:
            replay = LoopAccountParticipant(work).apply(receipt.command,
                request_key=receipt.request_key, costs=receipt.costs, now=session.now,
                identity_factory=forbidden, _source_authority_reader=forbidden)
            assert replay == receipt
        assert session.account() == before


def _owners(session):
    with session.work() as work:
        tables = (PlanSource.__table__, PlanVersion.__table__, ActivePlan.__table__,
            PlanActivationState.__table__, DailyRecord.__table__, AuditLog.__table__)
        return {table.name: tuple(work.daily.session.execute(table.select().order_by(
            *table.primary_key.columns)).all()) for table in tables}


@pytest.mark.parametrize("fault", ["target-policy", "target-manifest", "target-review",
                                  "old-active"])
def test_staged_successor_and_old_active_are_read_from_sql_and_rollback_together(tmp_path,
                                                                             monkeypatch, fault):
    from trade_plan_monitor.backtest.loop_source_authority import _LoopSourceAuthority

    original = _LoopSourceAuthority.require_activation
    with LoopSession(tmp_path, continuity_input(), continuity_calendar()) as session:
        session.advance(datetime(2026, 8, 20, 9, 30, tzinfo=SHANGHAI))
        before = _owners(session)
        original_selection, original_details, original_time = (
            session.selection, session.details, session.now)

        def corrupted(cap, sql, target_id):
            # Hold stale ORM projections while mutating the real rows, so this
            # proves actual SQL ownership rather than identity-map consistency.
            held = []
            if fault == "target-policy":
                held.append(sql.get(PlanVersion, target_id))
                changed = session.plan.model_copy(update={"position":
                    session.plan.position.model_copy(update={"max_qty": 400})})
                statement = update(PlanVersion).where(PlanVersion.id == target_id).values(
                    payload_json=dump_plan_json(changed), plan_hash=plan_sha256(changed))
            elif fault == "target-manifest":
                target = sql.get(PlanVersion, target_id)
                held.append(sql.get(PlanSource, target.source_id))
                statement = update(PlanSource).where(PlanSource.id == target.source_id).values(
                    source_text='{"different":true}',
                    source_hash=sha256(b'{"different":true}').hexdigest())
            elif fault == "target-review":
                held.append(sql.get(DailyRecord, "review-" + target_id))
                payload = json.loads(held[0].payload_json) | dict(evidence_hash="d" * 64)
                statement = update(DailyRecord).where(DailyRecord.id == held[0].id).values(
                    payload_json=canonical(payload))
            else:
                held.append(sql.get(ActivePlan, session.plan.symbol))
                statement = update(ActivePlan).values(activated_at=session.now.isoformat())
            sql.execute(statement.execution_options(synchronize_session=False))
            assert held
            return original(cap, sql, target_id)

        monkeypatch.setattr(_LoopSourceAuthority, "require_activation", corrupted)
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            session.advance(datetime(2026, 8, 21, 9, tzinfo=SHANGHAI))
        assert _owners(session) == before
        assert (session.selection, session.details, session.now) == (
            original_selection, original_details, original_time)


def _ended_schedule():
    value = continuity_input()
    # The fourth version is known to end after its effective day. Jumping over
    # it cannot make the first version the valid retained risk owner.
    rows = value.schedule.entries
    last = rows[-1]
    plan = last.version.snapshot.model_copy(update={"activation": dict(mode="DATE_RANGE",
        start_date=last.effective_trade_date, end_date=last.effective_trade_date)})
    replaced = last.version.model_copy(update={"snapshot": plan,
        "plan_hash": plan_sha256(plan), "review": last.version.review.model_copy(update={
            "content_hash": daily_plan_content_sha256(plan)})})
    value = value.model_copy(update={"schedule": value.schedule.model_copy(update={
        "entries": (*rows[:-1], last.model_copy(update={"version": replaced}))})})
    return value


def test_retained_authority_cannot_skip_a_successor_that_should_already_have_activated(tmp_path):
    value = _ended_schedule()
    with LoopSession(tmp_path, value, continuity_calendar()) as session:
        end = value.boundary.evidence_cutoff
        session.set_time(end)
        if value.schedule.select(end) is not None:
            pytest.fail("Fixture must have ended its final authority")
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _read(session)


def test_the_last_actual_activation_stays_observable_after_ordinary_authority_ends(tmp_path):
    value = _ended_schedule()
    with LoopSession(tmp_path, value, continuity_calendar()) as session:
        session.advance(value.boundary.evidence_cutoff)
        assert value.schedule.select(session.now) is None and not session._authority_available
        basis = _read(session)
        assert session.selection.version.version_id == "p4"
        assert basis.basis == "REPLAY_OBSERVATION" and basis.activation_revision == 4


def test_reactivating_a_frozen_version_keeps_its_first_review_and_exact_revision_history(tmp_path):
    value = continuity_input()
    rows = value.schedule.entries
    value = value.model_copy(update={"schedule": value.schedule.model_copy(update={
        "entries": (*rows[:-1], rows[-1].model_copy(update={"version": rows[1].version}))})})
    with LoopSession(tmp_path, value, continuity_calendar()) as session:
        session.advance(datetime(2026, 8, 21, 9, tzinfo=SHANGHAI))
        identity = session.details.id
        with session.work() as work:
            original_review = work.daily.get("review-" + identity)
        session.advance(datetime(2026, 8, 25, 9, tzinfo=SHANGHAI))
        assert session.details.id == identity and session.selection.version.version_id == "p2"
        basis = _read(session)
        assert basis.activation_revision == 4
        with session.work() as work:
            assert work.daily.session.get(PlanVersion, identity).revision == 4
            assert work.daily.get("review-" + identity) == original_review
