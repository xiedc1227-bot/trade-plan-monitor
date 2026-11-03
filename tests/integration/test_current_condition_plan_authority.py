"""Current codec families retain actual production authority, without new admission."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event
from tests.integration import current_pipeline_fixture as fixture
from tests.integration.test_explicit_runtime_production import _database
from tests.integration.test_persistent_monitor_read_service import _seed_plan, _setup
from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
from tests.unit.test_market_exception_contract import exception_payload
from tests.unit.test_market_linkage_contract import linked_payload
from tests.unit.test_p2_policy_contract import p2_payload
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.market_index.identity import resolve_board_reference
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.progress import RuntimeProgress
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


class OwnedProgress:
    """Track only real bounded production units, using the installed owner adapter."""

    def __init__(self, generation, clock):
        self.tracker = RuntimeProgress(generation, clock=clock.now,
                                      monotonic=lambda: clock.now().timestamp())

    def begin_progress_step(self, *, timeout_seconds):
        return self.tracker.begin_step(timeout_seconds=timeout_seconds)

    def begin_progress_step_at(self, *, deadline):
        return self.tracker.begin_step_at(deadline=deadline)

    def complete_progress_step(self, token, *, next_wake_at):
        return self.tracker.complete_step(token, next_wake_at=next_wake_at)

    def progress_monotonic_now(self):
        return self.tracker.monotonic_now()


def current_plan(schema):
    if schema == 5:
        return fixture.current_three_rule_plan()
    raw = {6: linked_payload, 7: exception_payload, 8: p2_payload, 9: p3_payload}[schema]()
    original_symbol = raw["symbol"]
    raw.update(symbol="003043.SZ", market="SZSE", activation={"mode": "MANUAL"},
               reference_market=resolve_board_reference("003043.SZ").binding.model_dump(mode="json"))
    raw["position"].update(core_target_qty=0, tactical_target_qty=100)

    def align(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if child == original_symbol:
                    value[key] = raw["symbol"]
                elif key == "as_of":
                    value[key] = "2026-09-11"
                elif key == "effective_from":
                    value[key] = "2026-01-01"
                elif key == "effective_through":
                    value[key] = "2026-12-31"
                else:
                    align(child)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if child == original_symbol:
                    value[index] = raw["symbol"]
                else:
                    align(child)

    align(raw)
    return load_plan_json(json.dumps(raw))


@pytest.fixture(params=[5, 6, 7, 8, 9])
def owned_family(tmp_path, monkeypatch, request):
    plan = current_plan(request.param)
    gates = dict(configuration=True, generation=True, revoked=False)
    progress = []
    construction = []

    def pipeline_factory(**kwargs):
        owned = OwnedProgress(kwargs["runtime_generation"], kwargs["clock"])
        progress.append(owned.tracker)
        kwargs.update(enable_runtime_status=True,
            progress_owner=owned,
            configuration_current=lambda: gates["configuration"],
            generation_current=lambda: gates["generation"],
            admission_revoked=lambda: gates["revoked"])
        construction.append(kwargs)
        return ProductionMonitorPipeline(**kwargs)

    monkeypatch.setattr(fixture, "ProductionMonitorPipeline", pipeline_factory)
    engine, work, plan, sdk, _, controller, pipeline, _ = fixture.current_pipeline_fixture(
        tmp_path, monkeypatch, current_volume=300, plan=plan)
    try:
        first = pipeline.runtime_status_snapshot()[2][0]
        source = CurrentCloseSDK(pipeline._clock, (plan.symbol,))
        sdk.daily, sdk.adj_factor = source.daily, source.adj_factor
        deadline = MarketDeadline(kind=DeadlineKind.REALTIME_MINUTE,
            trade_date=fixture.TARGET.date(), due_at=fixture.PIPELINE_NOW,
            bar_end=fixture.TARGET)

        async def run():
            await pipeline.refresh_references(fixture.TARGET.date())
            return (await pipeline.run_deadline(deadline))[0]

        result = asyncio.run(run())
        other, _, _, health = _setup(tmp_path)
        other.dispose()

        def owner():
            token, configuration, plans = pipeline.runtime_status_snapshot()
            return RuntimeReadAuthority(token=token, lifecycle="RUNNING", health=health,
                configuration_revision=configuration, plans=plans, progress=progress[0].snapshot())

        reader = RuntimeStatusReadService(create_session_factory(engine), owner,
                                         clock=pipeline._clock.now)
        yield SimpleNamespace(plan=plan, pipeline=pipeline, result=result, first=first,
                              engine=engine, work=work, source=source, gates=gates, reader=reader,
                              construction=construction[0], tmp_path=tmp_path, owner=owner)
    finally:
        asyncio.run(controller.aclose())
        engine.dispose()


def test_codec_current_family_keeps_real_completion_and_existing_rejections(owned_family):
    case = owned_family
    pipeline, plan = case.pipeline, case.plan
    assert type(load_plan_json(dump_plan_json(plan))) is type(plan)
    assert load_plan_json(dump_plan_json(plan)) == plan
    assert case.result.snapshot["plan_hash"] == plan_sha256(plan)
    token, configuration, plans = pipeline.runtime_status_snapshot()
    current = plans[0]
    assert current.plan_family == "CONDITION_PLAN"
    assert not current.blocked
    proof = current.completion
    assert case.first.plan_family == "CONDITION_PLAN"
    assert case.first.completion is None and not case.first.blocked
    assert case.first.pending_reason == "AWAITING_FIRST_EVALUATION"
    if plan.schema_version != 5:
        assert current.daily_admission is not None
        assert current.daily_admission.accepted_at <= pipeline._clock.now()
        assert {name for name, _ in case.source.calls} >= {"daily", "adj_factor"}
        assert case.result.snapshot["daily_evidence"] is not None
        # This stock-only fixture has no complete index history. Classification
        # must accept the family without manufacturing a completion proof.
        assert case.result.snapshot["linked_index_source"]["health"] == "BLOCKED"
        assert case.result.snapshot["linked_index_source"]["official_daily_bars"] == []
        assert proof is None
    else:
        assert proof is not None
        assert proof == pipeline._runtime_status_proofs[plan.symbol]
        assert proof.runtime_generation == token[0] == pipeline._runtime_generation
        assert proof.configuration_revision == configuration
        assert proof.plan_hash == plan_sha256(plan)
        assert proof.plan_version_id == case.result.snapshot["plan_version_id"]
        assert proof.activation_revision == case.result.snapshot["activation_revision"]
        assert proof.target == current.target

    writes = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(case.engine, "before_cursor_execute", record)
    try:
        dashboard = asyncio.run(case.reader.get_dashboard())
        summary = dashboard.symbols[0]
        assert summary.plan_family == "CONDITION_PLAN"
        assert summary.scope.plan_family == "CONDITION_PLAN"
        assert summary.scope.reason_code != "LEGACY_PLANS_REQUIRE_REVIEW"
        assert asyncio.run(case.reader.list_symbols(offset=0, limit=10)).items == dashboard.symbols
        assert asyncio.run(case.reader.get_symbol(symbol=plan.symbol)).summary == summary
        if proof is None:
            assert summary.availability == "CACHED" and not summary.current_actionable
            assert summary.scope.read_only
            assert writes == []
            return
        for field, value in (("runtime_generation", uuid4()),
                             ("configuration_revision", "other"),
                             ("plan_version_id", "other"), ("plan_hash", "a" * 64),
                             ("activation_revision", proof.activation_revision + 1)):
            pipeline._runtime_status_proofs[plan.symbol] = replace(proof, **{field: value})
            assert pipeline.runtime_status_snapshot()[2][0].completion is None
        pipeline._runtime_status_proofs.pop(plan.symbol)
        assert pipeline.runtime_status_snapshot()[2][0].completion is None
        pipeline._runtime_status_proofs[plan.symbol] = proof
        for gate, value, reason in (("configuration", False, "NEEDS_RESTART"),
                                   ("generation", False, "GENERATION_CHANGED"),
                                   ("revoked", True, "GENERATION_CHANGED")):
            case.gates[gate] = value
            rejected = pipeline.runtime_status_snapshot()[2][0]
            assert rejected.completion is None and rejected.blocked
            assert rejected.pending_reason == reason
            case.gates[gate] = not value
        assert pipeline.runtime_status_snapshot()[2][0].completion == proof
        assert writes == []
    finally:
        event.remove(case.engine, "before_cursor_execute", record)

    if plan.schema_version == 5:
        legacy_engine, legacy_work, _, _ = _setup(case.tmp_path)
        _seed_plan(legacy_work, active=True)
        explicit_engine, _ = _database(case.tmp_path, "explicit-rejected.db")
        for old_engine, family in ((legacy_engine, "LEGACY_LOW_BUY"),
                                   (explicit_engine, "EXPLICIT_RULES")):
            try:
                sessions = create_session_factory(old_engine)
                kwargs = {**case.construction, "recovery_session_factory": sessions,
                    "unit_of_work_factory": lambda sessions=sessions: SqlAlchemyUnitOfWork(
                        sessions, clock=pipeline._clock.now)}
                old_pipeline = ProductionMonitorPipeline(**kwargs)
                rejected = old_pipeline.runtime_status_snapshot()[2][0]
                assert rejected.plan_family == family and rejected.blocked
                assert rejected.completion is None and rejected.daily_admission is None
                assert rejected.pending_reason == "LEGACY_PLANS_REQUIRE_REVIEW"
                def old_owner(old_pipeline=old_pipeline):
                    token, configuration, plans = old_pipeline.runtime_status_snapshot()
                    return replace(case.owner(), token=token,
                                   configuration_revision=configuration, plans=plans)

                old_reader = RuntimeStatusReadService(sessions, old_owner,
                                                     clock=pipeline._clock.now)
                old_summary = asyncio.run(old_reader.get_dashboard()).symbols[0]
                assert old_summary.plan_family == family
                assert old_summary.scope.reason_code == "LEGACY_PLANS_REQUIRE_REVIEW"
                assert not old_summary.current_actionable
            finally:
                old_engine.dispose()
