"""Frozen research uses private observation proof and real isolated SQL owners."""

import sqlite3
from dataclasses import replace
from datetime import datetime, time, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from tests.integration.test_monitor_loop_cycle import frames
from tests.unit.test_monitor_loop_schedule import SHANGHAI, calendar
from tests.unit.test_unified_plan_domain import unified_payload
from tests.unit.test_unified_replay_input import create, research_input, research_plan

from trade_plan_monitor.backtest.research_input import ResearchSimulation
from trade_plan_monitor.backtest.research_session import ResearchSession
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanSource, PlanVersion
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def _run_input(*, nested=False, late_review=False):
    plan = research_plan()
    if nested:
        rule = plan.ordinary_rules[0].model_copy(update={"condition": dict(
            type="DAILY_PRICE_COMPARE", field="close", offset=0, comparator="GT",
            reference=dict(mode="DYNAMIC", indicator="MA20", offset=0,
                           formula_version="daily-ta-v2", parameters={"period": 20}))})
        plan = plan.model_copy(update={"ordinary_rules": (rule,),
                                      "monitoring": unified_payload()["monitoring"]})
    research = research_input(plan)
    if late_review:
        research = research.model_copy(update={"review": research.review.model_copy(update={
            "reviewed_at": research.started_at + timedelta(days=6)})})
    return create(plan, research)


def _read(owner):
    with owner.work() as work:
        return owner._source_authority_reader(work, owner.details.id)


def test_research_observation_has_actual_private_sql_owners_and_no_current_coverage_claim(tmp_path):
    run = _run_input()
    session = ResearchSession(tmp_path, run, calendar())
    try:
        with session.work() as work:
            actual = work.daily.session.get(ActivePlan, session.plan.symbol)
            assert actual is not None and actual.plan_version_id == session.details.id
            version = work.daily.session.get(PlanVersion, actual.plan_version_id)
            assert version is not None and version.status == "ACTIVE" and version.revision == 1
            source = work.daily.session.get(PlanSource, version.source_id)
            assert source is not None and "FROZEN_REVIEWED_RESEARCH" in source.source_text
            basis = session._source_authority_reader(work, session.details.id)
            assert basis.basis == "REPLAY_OBSERVATION" and basis.activation_revision == 1
            assert not hasattr(basis, "coverage_complete") and not hasattr(basis, "status")
            assert not hasattr(basis, "coverage_evidence_hash")
    finally:
        session.close()


def test_original_input_hashes_and_later_research_review_time_keep_their_existing_meaning(tmp_path):
    run = _run_input(late_review=True)
    wire, run_hash, authority = run.model_dump_json(), run.run_id, run.authority_id
    owner = ResearchSession(tmp_path, run, calendar())
    try:
        assert run.research_input.review.reviewed_at > owner.now
        assert _read(owner).basis == "REPLAY_OBSERVATION"
        assert (owner.run_input.model_dump_json(), owner.run_input.run_id,
                owner.run_input.authority_id) == (wire, run_hash, authority)
    finally:
        owner.close()


@pytest.mark.parametrize("mutation", ["input-clone", "nested", "details", "virtual-active",
                                    "plan", "clock-before", "clock-after", "closed"])
def test_private_research_capability_checks_original_input_bytes_and_session_owners(tmp_path,
                                                                                  mutation):
    owner = ResearchSession(tmp_path, _run_input(nested=mutation == "nested"), calendar())
    try:
        assert _read(owner).basis == "REPLAY_OBSERVATION"
        if mutation == "input-clone":
            owner.run_input = type(owner.run_input).model_validate_json(
                owner.run_input.model_dump_json())
        elif mutation == "nested":
            reference = owner.run_input.plan_snapshot.ordinary_rules[0].condition.reference
            parameters = reference.parameters
            parameters["period"] = 21
        elif mutation == "details":
            owner.details = replace(owner.details, content_hash="a" * 64)
        elif mutation == "virtual-active":
            owner.active = replace(owner.active, revision=2)
        elif mutation == "plan":
            owner.plan = owner.plan.model_copy(update={"position": owner.plan.position.model_copy(
                update={"max_qty": 900})})
        elif mutation == "clock-before":
            owner.now -= timedelta(seconds=1)
        elif mutation == "clock-after":
            owner.now = datetime.combine(owner.run_input.end + timedelta(days=1),
                                         time.min, SHANGHAI)
        else:
            owner.close()
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _read(owner)
    finally:
        owner.close()


@pytest.mark.parametrize("clone", [False, True])
def test_research_capability_cannot_move_to_another_engine_or_identical_copy(tmp_path, clone):
    owner = ResearchSession(tmp_path, _run_input(), calendar())
    try:
        path = owner.engine.url.database
        if clone:
            path = str(tmp_path / "copy.sqlite")
            with sqlite3.connect(owner.engine.url.database) as original:
                with sqlite3.connect(path) as copied:
                    original.backup(copied)
        engine = create_sqlite_engine(path)
        try:
            with SqlAlchemyUnitOfWork(create_session_factory(engine),
                                       clock=lambda: owner.now) as work:
                with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                    owner._source_authority_reader(work, owner.details.id)
        finally:
            engine.dispose()
    finally:
        owner.close()


@pytest.mark.parametrize("mutation", ["policy", "plan-hash", "plan-revision", "manifest",
                                    "review", "review-time", "activation", "state"])
def test_research_capability_reads_actual_sql_despite_held_orm_values(tmp_path, mutation):
    owner = ResearchSession(tmp_path, _run_input(), calendar())
    try:
        with owner.work() as work:
            sql = work.daily.session
            basis = owner._source_authority_reader(work, owner.details.id)
            assert basis.basis == "REPLAY_OBSERVATION"
            held = [sql.get(PlanVersion, owner.details.id), sql.get(ActivePlan, owner.plan.symbol)]
            if mutation in {"policy", "plan-hash", "plan-revision"}:
                values = ({"payload_json": dump_plan_json(owner.plan.model_copy(update={
                    "position": owner.plan.position.model_copy(update={"max_qty": 900})}))}
                    if mutation == "policy" else {"plan_hash": "b" * 64}
                    if mutation == "plan-hash" else {"revision": 2})
                statement = update(PlanVersion).where(
                    PlanVersion.id == owner.details.id).values(**values)
            elif mutation == "manifest":
                held.append(sql.get(PlanSource, held[0].source_id))
                statement = update(PlanSource).values(source_text="different frozen manifest")
            elif mutation in {"review", "review-time"}:
                row = sql.get(DailyRecord, "review-" + owner.details.id)
                held.append(row)
                values = ({"payload_json": canonical(work.daily._value(row)["payload"] | dict(
                    evidence_hash="c" * 64))} if mutation == "review" else
                    {"created_at": (owner.now - timedelta(hours=1)).isoformat()})
                statement = update(DailyRecord).where(DailyRecord.id == row.id).values(**values)
            elif mutation == "activation":
                statement = update(ActivePlan).values(revision=2)
            else:
                held.append(sql.get(PlanActivationState, owner.plan.symbol))
                statement = update(PlanActivationState).values(revision=2)
            sql.execute(statement.execution_options(synchronize_session=False))
            assert held
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                owner._source_authority_reader(work, owner.details.id)
    finally:
        owner.close()


def test_research_session_rejects_reused_private_database_without_changing_old_bytes(tmp_path):
    owner = ResearchSession(tmp_path, _run_input(), calendar())
    owner.close()
    path = tmp_path / "runtime.sqlite"
    before = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="RESEARCH_SESSION_REQUIRES_FRESH_PRIVATE_DATABASE"):
        ResearchSession(tmp_path, _run_input(), calendar())
    assert sha256(path.read_bytes()).hexdigest() == before


def test_private_research_issuer_never_accepts_a_foreign_object_or_reissues_a_session(tmp_path):
    from trade_plan_monitor.backtest.research_source_authority import (
        _issue_research_source_authority,
    )

    owner = ResearchSession(tmp_path, _run_input(), calendar())
    try:
        for candidate in (SimpleNamespace(), owner):
            with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
                _issue_research_source_authority(candidate)
    finally:
        owner.close()


def _ready(owner):
    result = None
    for frame in frames(end=37):
        inputs = frame.runtime
        owner.now = inputs.evaluated_at
        with owner.work() as work:
            work.history.upsert_minutes(inputs.minute_prefix)
            for bar in inputs.five_minute_bars:
                work.history.upsert_five_minute(**bar.model_dump())
            work.commit()
        result = owner.runtime.run_inputs(plan=owner.plan, inputs=inputs)
    signal, = result.snapshot["signals"]
    assert signal["executable_qty"] == 100 and result.event_ids == ()
    return signal


def test_actual_research_runtime_and_simulation_use_explicit_private_authority(tmp_path):
    owner = ResearchSession(tmp_path, _run_input(), calendar())
    try:
        signal = _ready(owner)
        operation = ResearchSimulation(kind="SIMULATE", operation_id="research-source-fill",
            at=owner.now, order=1, rule_id=signal["rule_id"], occurrence=1, quantity=100)
        outcome = owner.apply_operation(operation, ended=False)
        assert outcome.status == "APPLIED" and outcome.inventory_after.total_qty == 100
        before = owner.inventory()
        repeated = owner.apply_operation(operation, ended=False)
        assert repeated.status == "BLOCKED" and owner.inventory() == before
    finally:
        owner.close()


def test_frozen_research_sql_rows_cannot_be_read_as_live_current_source_coverage(tmp_path):
    from trade_plan_monitor.state.source_action_authority import require_source_action_authority

    owner = ResearchSession(tmp_path, _run_input(), calendar())
    try:
        assert _read(owner).basis == "REPLAY_OBSERVATION"
        with owner.work() as work, pytest.raises(SourceCoverageAuthorityError):
            require_source_action_authority(work, owner.details.id)
    finally:
        owner.close()
