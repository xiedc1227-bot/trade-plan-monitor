"""Original source bindings observe real SQL changes without flushing or scanning history."""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, text, update
from tests.integration import test_market_linkage_review, test_plan_risk_evaluation_output
from tests.integration.preparation_review_current_fixtures import field_source, reviewed_mapping
from tests.integration.test_daily_plan_chain import Chain, official_proof
from tests.integration.test_plan_risk_evaluation_output import MONDAY_CLOSE, TUESDAY_CLOSE
from tests.integration.test_plan_risk_evaluation_output import risk_case as risk_case
from tests.integration.test_risk_origin_reads import change_daily, native_risk, read_origin

from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import PlanSource, PlanVersion, PlanVersionReview
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.state.source_coverage_models import (
    COVERAGE_TRIGGER_SQL,
    CoverageAssessmentRow,
    CoverageReviewRow,
)
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore

pytestmark = pytest.mark.parametrize(
    "risk_case", [{"early_activation": True, "line": 6500, "severe": "true"}], indirect=True
)


def test_actual_fulfilled_cause_remains_diagnosable(risk_case):
    case = risk_case
    case.run(MONDAY_CLOSE)
    tuesday = TUESDAY_CLOSE.replace(hour=10, minute=5, second=15)
    chain = Chain(case.tmp_path)
    chain.plan, chain.now = case.plan, tuesday
    with chain.client:
        chain.post(
            "plan-facts",
            {
                "planVersionId": case.result.snapshot["plan_version_id"],
                "contentHash": case.result.snapshot["content_hash"],
                "factId": "tuesday-tradability",
                "kind": "TRADABILITY",
                "tradeDate": str(tuesday.date()),
                "expectedRevision": 0,
                "evidence": "Synthetic verified current-day tradability and liquidity fixture.",
                "officialEvidence": official_proof(chain),
            },
        )
    case.pipeline._clock.current = tuesday
    case.sdk.source_time = tuesday.replace(second=0) - timedelta(minutes=1)

    async def recover():
        await case.pipeline.refresh_references(tuesday.date())
        await case.pipeline.recover_startup(tuesday.date())

    asyncio.run(recover())
    current = case.run(tuesday)
    action = current.snapshot["risk_action"]
    assert action["status"] == "RISK_EXIT" and action["tactical_qty"] == 100
    before = read_origin(case, action["cause_id"])
    assert before is not None
    with chain.client:
        chain.post(
            "simulated-trades",
            {
                "planVersionId": current.snapshot["plan_version_id"],
                "causeId": action["cause_id"],
                "expectedCauseRevision": action["cause_revision"],
                "expectedInventoryRevision": current.snapshot["inventory"]["revision"],
                "quantity": 100,
            },
        )
    result = read_origin(case, action["cause_id"])
    assert result is not None and result.cause.status == "FULFILLED"
    assert result.cause.origin_evaluation_id == before.cause.origin_evaluation_id
    assert result.binding != before.binding


@pytest.fixture
def fact_plan(monkeypatch):
    original = test_plan_risk_evaluation_output.risk_plan

    def plan(options):
        raw = original(options).model_dump(mode="json")
        branch = next(row for row in raw["risk_branches"] if row["rule_id"] == "severe-risk")
        branch["condition"] = {
            "type": "REVIEWED_FACT",
            "fact_kind": "SEVERE_STRUCTURE",
            "evidence_requirement": "Review technical evidence for SEVERE_STRUCTURE",
            "validity_scope": "TRADE_DATE",
        }
        return load_plan_json(canonical(raw))

    monkeypatch.setattr(test_plan_risk_evaluation_output, "risk_plan", plan)


@pytest.fixture
def fact_origin_case(fact_plan, risk_case):
    case = risk_case
    case.run(MONDAY_CLOSE)
    case.pipeline._clock.current = MONDAY_CLOSE + timedelta(seconds=1)
    chain = Chain(case.tmp_path)
    chain.plan, chain.now = case.plan, case.pipeline._clock.now()
    case.fact_owner_id = case.result.snapshot["plan_version_id"]
    with chain.client:
        original_runtime = chain.runtime
        chain.runtime = case.pipeline.daily_evaluations
        chain.post(
            "plan-facts",
            {
                "planVersionId": case.fact_owner_id,
                "contentHash": case.result.snapshot["content_hash"],
                "factId": "actual-structure",
                "kind": "SEVERE_STRUCTURE",
                "tradeDate": str(MONDAY_CLOSE.date()),
                "expectedRevision": 0,
                "evidence": "Synthetic complete technical failure independently verified",
            },
        )
        case.result = case.run(MONDAY_CLOSE + timedelta(seconds=2))
        assert native_risk(case, "severe-risk")["status"] == "CONFIRMED"
        chain.runtime = original_runtime
        chain.now = case.pipeline._clock.now()
        chain.activate(version=2, activation_revision=1)
    case.active_version_id = chain.version["id"]
    return case


def test_actual_fact_and_its_older_version_are_in_the_origin_binding(fact_origin_case):
    case = fact_origin_case
    risk = native_risk(case, "severe-risk")
    result = read_origin(case, risk["risk_id"])
    assert result is not None and result.birth.close_date == MONDAY_CLOSE.date()
    with case.work() as work:
        fact = work.daily.get(risk["evidence_ids"][0])
        assert fact["payload"]["plan_version_id"] == case.fact_owner_id
        assert case.fact_owner_id == result.origin.plan_version_id != case.active_version_id
        held = work.daily.session.get(PlanVersion, case.fact_owner_id)
        revision = held.revision
        work.daily.session.execute(
            update(PlanVersion)
            .where(PlanVersion.id == held.id)
            .values(revision=revision + 1)
            .execution_options(synchronize_session=False)
        )
        assert held.revision == revision
        changed = read_origin(case, risk["risk_id"], work=work)
        assert changed is not None and changed.binding != result.binding


@pytest.mark.parametrize("mutation", ["new-revision", "new-verification", "different-owner"])
def test_later_fact_verification_or_another_owner_cannot_replace_birth_evidence(
    fact_origin_case, mutation
):
    case = fact_origin_case
    risk = native_risk(case, "severe-risk")
    assert read_origin(case, risk["risk_id"]) is not None
    with case.work() as work:
        fact = work.daily.get(risk["evidence_ids"][0])
        payload = dict(fact["payload"])
        if mutation == "new-revision":
            change_daily(work, fact["id"], revision=fact["revision"] + 1)
        elif mutation == "new-verification":
            case.pipeline._clock.current += timedelta(minutes=1)
            payload["verified_at"] = case.pipeline._clock.now().isoformat()
            change_daily(work, fact["id"], payload=payload)
        else:
            payload["plan_version_id"] = "00000000-0000-0000-0000-000000000999"
            change_daily(work, fact["id"], payload=payload)
        assert read_origin(case, risk["risk_id"], work=work) is None


@pytest.fixture
def supplemented_plan(monkeypatch):
    def source_mapping(draft):
        source = field_source(draft, missing=("position.max_qty",))
        return source, reviewed_mapping(draft, source)

    monkeypatch.setattr(test_market_linkage_review, "source_mapping", source_mapping)


def test_registered_supplement_is_point_read_and_bound(supplemented_plan, risk_case):
    case = risk_case
    risk = native_risk(case)
    before = read_origin(case, risk["risk_id"])
    assert before is not None
    with case.work() as work:
        identity = daily_hash(
            "daily-human-supplements-v1",
            dict(symbol=case.plan.symbol, content_hash=case.result.snapshot["content_hash"]),
        )
        supplement = work.daily.get(identity)
        assert supplement is not None and supplement["payload"]["supplements"]
        change_daily(work, identity, revision=supplement["revision"] + 1)
        changed = read_origin(case, risk["risk_id"], work=work)
        assert changed is not None and changed.binding != before.binding
        change_daily(work, identity, payload={**supplement["payload"], "supplements": []})
        assert read_origin(case, risk["risk_id"], work=work) is None


@pytest.mark.parametrize("owner", ["cause", "version", "source", "version-review", "shadow"])
def test_actual_sql_owner_changes_are_visible_through_held_orm_rows(risk_case, owner):
    case = risk_case
    risk = native_risk(case)
    before = read_origin(case, risk["risk_id"])
    assert before is not None
    with case.work() as work:
        session = work.daily.session
        version = session.get(PlanVersion, before.origin.plan_version_id)
        if owner in {"cause", "shadow"}:
            identity = risk["risk_id"] if owner == "cause" else "review-" + version.id
            held = session.get(DailyRecord, identity)
            old = held.revision
            change_daily(work, identity, revision=old + 1)
            assert held.revision == old
        elif owner == "version":
            old = version.revision
            session.execute(
                update(PlanVersion)
                .where(PlanVersion.id == version.id)
                .values(revision=old + 1)
                .execution_options(synchronize_session=False)
            )
            assert version.revision == old
        elif owner == "source":
            held = session.get(PlanSource, version.source_id)
            old = held.created_at
            session.execute(
                update(PlanSource)
                .where(PlanSource.id == held.id)
                .values(created_at=(datetime.fromisoformat(old) - timedelta(seconds=1)).isoformat())
                .execution_options(synchronize_session=False)
            )
            assert held.created_at == old
        else:
            held = session.get(PlanVersionReview, version.id)
            old = held.review_issues_json
            session.execute(
                update(PlanVersionReview)
                .where(PlanVersionReview.plan_version_id == version.id)
                .values(review_issues_json='["synthetic concurrent raw review value"]')
                .execution_options(synchronize_session=False)
            )
            assert held.review_issues_json == old
        changed = read_origin(case, risk["risk_id"], work=work)
        assert changed is not None and changed.binding != before.binding


@pytest.mark.parametrize(
    "owner", ["cause", "evaluation", "version", "source", "receipt", "assessment"]
)
def test_pending_exact_owners_are_rejected_without_autoflush_or_lost_edits(risk_case, owner):
    case = risk_case
    risk = native_risk(case)
    with case.work() as work:
        session = work.daily.session
        version = session.get(PlanVersion, case.result.snapshot["plan_version_id"])
        if owner in {"cause", "evaluation"}:
            held = session.get(
                DailyRecord, risk["risk_id"] if owner == "cause" else case.result.evaluation_id
            )
            held.revision += 1
        elif owner == "version":
            held = version
            held.revision += 1
        elif owner == "source":
            held = session.get(PlanSource, version.source_id)
            held.source_text += " synthetic unflushed edit"
        elif owner == "receipt":
            held = session.get(CoverageReviewRow, case.result.snapshot["review_id"])
            held.evidence_hash = "0" * 64
        else:
            held = session.get(CoverageAssessmentRow, (version.id, 1))
            held.evidence_hash = "0" * 64
        dirty = set(session.dirty)

        def forbidden(*_args):
            raise AssertionError("origin diagnosis must not flush pending changes")

        event.listen(session, "before_flush", forbidden)
        try:
            assert read_origin(case, risk["risk_id"], work=work) is None
            assert set(session.dirty) == dirty and session.is_modified(held)
        finally:
            event.remove(session, "before_flush", forbidden)


def test_reads_are_bounded_points_and_perform_no_business_writes(risk_case, monkeypatch):
    case = risk_case
    risk = native_risk(case)
    evaluations, comparisons = len(case.calls), len(case.comparisons)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unbounded history or latest assessment must not be read")

    monkeypatch.setattr(ActionOwnerReader, "risks", forbidden)
    monkeypatch.setattr(SourceCoverageStore, "cutover", forbidden)
    monkeypatch.setattr(SourceCoverageStore, "latest", forbidden)
    with case.work() as work:
        session = work.daily.session
        session.add(
            DailyRecord(
                id="unrelated-pending",
                kind="DRAFT",
                symbol=case.plan.symbol,
                lineage="unrelated",
                revision=1,
                payload_json="{}",
                created_at=case.pipeline._clock.now().isoformat(),
                updated_at=case.pipeline._clock.now().isoformat(),
            )
        )
        new = set(session.new)
        event.listen(case.engine, "before_cursor_execute", capture)
        try:
            result = read_origin(case, risk["risk_id"], work=work)
            assert result is not None and set(session.new) == new
        finally:
            event.remove(case.engine, "before_cursor_execute", capture)
    assert not any(
        sql.lstrip().startswith(("insert", "update", "delete", "create", "alter"))
        for sql in statements
    )
    assert not any("from source_coverage_cutover" in sql for sql in statements)
    for sql in statements:
        if "from daily_plan_record" in sql:
            assert "where daily_plan_record.id =" in sql
        if "from source_coverage_assessment" in sql:
            assert "plan_version_id =" in sql and "revision =" in sql
    assert len(statements) < 55
    assert len(case.calls) == evaluations and len(case.comparisons) == comparisons


@pytest.mark.parametrize("missing", ["receipt", "upgrade"])
def test_missing_assurance_returns_unknown_without_repairing_storage(risk_case, missing):
    case = risk_case
    risk = native_risk(case)
    with case.work() as work:
        session = work.daily.session
        if missing == "upgrade":
            session.execute(text("DROP TABLE source_coverage_review"))
        else:
            trigger = "pma_seal_source_coverage_review_delete"
            session.execute(text("DROP TRIGGER " + trigger))
            session.execute(
                text("DELETE FROM source_coverage_review WHERE review_id = :identity"),
                {"identity": case.result.snapshot["review_id"]},
            )
            session.execute(text(COVERAGE_TRIGGER_SQL[trigger]))
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())

        event.listen(case.engine, "before_cursor_execute", capture)
        try:
            assert read_origin(case, risk["risk_id"], work=work) is None
        finally:
            event.remove(case.engine, "before_cursor_execute", capture)
        assert not any(
            sql.lstrip().startswith(("insert", "update", "delete", "create", "alter"))
            for sql in statements
        )
