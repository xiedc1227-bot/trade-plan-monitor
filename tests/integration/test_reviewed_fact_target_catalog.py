"""Actual FIELD review and FACT owners; the catalog does not wire runtime guards."""

from hashlib import sha256

import pytest
from sqlalchemy import event, select
from tests.integration.test_daily_plan_chain import SH, TUESDAY, Chain
from tests.integration.test_unified_runtime import current_plan, minute_inputs

from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.domain.reviewed_fact_targets import (
    assess_unbound_fact,
    filter_unbound_facts,
)
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_state_models import DailyFactState
from trade_plan_monitor.state.models import PlanSource, PlanVersion
from trade_plan_monitor.state.source_coverage_authority import read_version_coverage
from trade_plan_monitor.state.source_coverage_models import (
    CoverageAssessmentRow,
    CoverageCutoverRow,
    CoverageInputRow,
    CoverageInstallationRow,
    CoverageReviewRow,
)


def _plan(requirements):
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"] = dict(type="ALL", conditions=[
        dict(type="REVIEWED_FACT", fact_kind="VOLUME_OR_CANDLE",
             evidence_requirement=requirement, validity_scope="TRADE_DATE")
        for requirement in requirements])
    return UnifiedTradePlan.model_validate(raw)


def _register(chain):
    chain.now = chain.now.replace(year=2026, month=9, day=22, hour=9, minute=35,
                                  second=12, microsecond=0, tzinfo=SH)
    before = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
    assert before.snapshot["signals"] == []
    receipt = chain.post("plan-facts", dict(
        planVersionId=chain.version["id"], contentHash=chain.version["contentHash"],
        factId="actual-volume-only", kind="VOLUME_OR_CANDLE", tradeDate=str(TUESDAY),
        evidence="人工仅确认成交不异常放大；未核验任何下影线条件，不表示该条件已经满足。",
        expectedRevision=0))
    assert receipt["revision"] == 1
    return receipt["id"]


def _stored_bytes(session):
    models = (CoverageInstallationRow, CoverageCutoverRow, CoverageInputRow,
              CoverageAssessmentRow, CoverageReviewRow, PlanSource, PlanVersion, DailyRecord)
    return tuple((model.__tablename__, tuple(tuple(row) for row in session.execute(
        select(model.__table__).order_by(*model.__table__.primary_key.columns))))
        for model in models)


def _catalog_read(chain, fact_id, owner_version_id):
    with chain.plans._unit_of_work() as work:
        details = work.plans.get_version_details(owner_version_id)
        actual_plan = load_plan_json(details.payload_json)
        actual_row = work.daily.get(fact_id)
        actual_fact = DailyFactState.model_validate(actual_row["payload"])
        assert actual_fact.plan_version_id == details.id
        assert actual_fact.content_hash == details.content_hash == daily_plan_content_sha256(
            actual_plan)
        proof_before = read_version_coverage(work, details)
        assert proof_before.assessment.coverage_complete
        assert proof_before.assessment.rules_version == "source-coverage-rules-v1"
        before = _stored_bytes(work.daily.session)
        native_before = (actual_plan.model_dump_json(), plan_sha256(actual_plan),
                         daily_plan_content_sha256(actual_plan), details.source_text,
                         sha256(details.source_text.encode()).hexdigest(),
                         proof_before.model_dump_json())
        attempted_writes = []

        def observed(_connection, _cursor, statement, _parameters, _context, _many):
            normalized = statement.lstrip().upper()
            if normalized.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE",
                                      "ALTER", "DROP", "BEGIN IMMEDIATE")):
                attempted_writes.append(statement)

        engine = work.daily.session.get_bind()
        event.listen(engine, "before_cursor_execute", observed)
        try:
            decision = assess_unbound_fact(actual_plan, actual_fact)
            value = {**actual_row["payload"], "id": actual_row["id"]}
            projected = filter_unbound_facts(actual_plan, (value,))
            assert assess_unbound_fact(actual_plan, value) == decision
            proof_after = read_version_coverage(work, details)
            assert _stored_bytes(work.daily.session) == before
            assert (actual_plan.model_dump_json(), plan_sha256(actual_plan),
                    daily_plan_content_sha256(actual_plan), details.source_text,
                    sha256(details.source_text.encode()).hexdigest(),
                    proof_after.model_dump_json()) == native_before
            assert attempted_writes == []
        finally:
            event.remove(engine, "before_cursor_execute", observed)
        return actual_plan, value, decision, projected


@pytest.mark.parametrize(("requirements", "reason", "count"), [
    (("成交不异常放大",), "UNIQUE_DEFINITION", 1),
    (("成交不异常放大", "明显下影"), "AMBIGUOUS_DEFINITION", 2),
    (("成交不异常放大", "成交不异常放大"), "UNIQUE_DEFINITION", 1),
])
def test_actual_reviewed_field_source_and_registered_fact_have_readonly_catalog(
    tmp_path, requirements, reason, count,
):
    chain = Chain(tmp_path)
    chain.plan = _plan(requirements)
    with chain.client:
        chain.activate()
        view = chain.client.get("/api/v1/plan-versions/" + chain.version["id"]).json()
        assert view["sourceCoverage"]["coverageComplete"] is True
        assert view["sourceCoverage"]["currentReviewBound"] is True
        assert view["canActivate"] is True
        fact_id = _register(chain)
        plan, fact, decision, projected = _catalog_read(chain, fact_id, chain.version["id"])
        assert decision.reason == reason and decision.definition_count == count
        assert len(decision.definitions) == len(requirements)
        assert len(projected) == (0 if reason == "AMBIGUOUS_DEFINITION" else 1)
        if projected:
            assert projected[0] is fact
        # Compare the actual still-unwired evaluator; this is not a runtime fix claim.
        inputs = minute_inputs(chain)
        baseline = evaluate_unified_condition(plan.ordinary_rules[0].condition, None,
            facts=(fact,), target=inputs.minute_target)
        assert baseline.outcome == "SATISFIED"
        projected_evidence = evaluate_unified_condition(plan.ordinary_rules[0].condition, None,
            facts=projected, target=inputs.minute_target)
        assert projected_evidence.outcome == (
            "MISSING_INPUT" if reason == "AMBIGUOUS_DEFINITION" else "SATISFIED")


def test_catalog_uses_the_actual_fact_original_owner_without_rebasing_to_active_sibling(tmp_path):
    chain = Chain(tmp_path)
    chain.plan = _plan(("成交不异常放大",))
    with chain.client:
        chain.activate()
        original_id = chain.version["id"]
        fact_id = _register(chain)
        chain.plan = _plan(("成交不异常放大", "明显下影"))
        chain.activate(version=2, activation_revision=1)
        active_id = chain.version["id"]
        assert active_id != original_id
        original, fact, decision, projected = _catalog_read(chain, fact_id, original_id)
        assert decision.usable and projected[0] is fact
        with chain.plans._unit_of_work() as work:
            active = load_plan_json(work.plans.get_version_details(active_id).payload_json)
        assert assess_unbound_fact(active, fact).reason == "CONTENT_MISMATCH"
        assert filter_unbound_facts(active, (fact,)) == ()
        assert daily_plan_content_sha256(original) == fact["content_hash"]
