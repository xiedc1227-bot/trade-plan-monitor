"""Actual HTTP, SQLite and outbox reverse boundaries for technical-only monitoring."""

import json
from hashlib import sha256

import pytest
from sqlalchemy import func, select
from tests.integration.test_daily_plan_chain import TUESDAY, ready_chain
from tests.integration.test_daily_plan_chain import chain as chain_fixture
from tests.unit.test_daily_review import reviewed_mapping

from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import AlertEvent, PlanVersion

chain = chain_fixture


def counts(chain):
    with chain.plans._unit_of_work() as work:
        return tuple(
            work.daily.session.scalar(select(func.count()).select_from(model))
            for model in (DailyRecord, AlertEvent, PlanVersion)
        )


@pytest.mark.parametrize("kind", ["FUNDAMENTAL_INVALIDATION", "ANNOUNCEMENT_CHECK"])
def test_fact_http_injection_has_no_fact_risk_or_outbox_mutation(chain, kind):
    ready_chain(chain)
    payload = {
        "planVersionId": chain.version["id"],
        "contentHash": chain.version["contentHash"],
        "factId": "excluded",
        "kind": kind,
        "tradeDate": str(TUESDAY),
        "expectedRevision": 0,
        "evidence": "Synthetic verified technical evidence for current holding",
    }
    before = counts(chain)
    response = chain.client.post(
        "/api/v1/plan-facts", json=payload, headers={"Idempotency-Key": "excluded-" + kind}
    )
    assert response.status_code == 422
    assert counts(chain) == before


def test_relabelled_technical_fact_rejects_without_mutation(chain):
    ready_chain(chain)
    before = counts(chain)
    response = chain.client.post(
        "/api/v1/plan-facts",
        json={
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": "relabelled",
            "kind": "TECHNICAL",
            "tradeDate": str(TUESDAY),
            "expectedRevision": 0,
            "evidence": "Synthetic fundamental holding thesis verification required",
        },
        headers={"Idempotency-Key": "relabelled-fact"},
    )
    assert response.status_code == 422
    assert counts(chain) == before


def test_no_mapping_preview_exposes_background_and_explicit_unknown_wording_route(chain):
    draft = UnifiedPlanDraft.from_executable(chain.plan)
    source = "Announcement verification is outside daily monitoring。公司订单持续改善。"
    preview = chain.post(
        "plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source},
    )
    clauses = preview["review"]["mapping"]["clauses"]
    assert clauses[0]["disposition"] == "BACKGROUND"
    assert not any(
        i["path"] == "source." + clauses[0]["clause_id"] for i in preview["review"]["issues"]
    )
    selected = clauses[1]
    narrowed = chain.post(
        "plan-review-previews",
        {
            "candidateJson": daily_draft_json(draft),
            "sourceText": source,
            "mapping": preview["review"]["mapping"],
            "scopeSelections": [
                {
                    "source_hash": sha256(source.encode()).hexdigest(),
                    "start": selected["start"],
                    "end": selected["end"],
                    "excerpt": selected["excerpt"],
                    "origin": "HUMAN_SCOPE_SELECTION",
                    "reason": "FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION",
                }
            ],
        },
    )
    assert narrowed["review"]["mapping"]["clauses"][1]["disposition"] == "BACKGROUND"
    assert not any(
        i["code"] == "DAILY_SOURCE_CLAUSE_REQUIRED" for i in narrowed["review"]["issues"]
    )


def test_background_complete_candidate_has_no_fundamental_review_blocker(chain):
    from trade_plan_monitor.ai.daily_review import build_daily_review, daily_source_clauses

    source = "Announcement verification is outside daily monitoring。"
    draft = UnifiedPlanDraft.from_executable(chain.plan)
    mapping = reviewed_mapping(draft, source).model_copy(
        update={"clauses": daily_source_clauses(source)}
    )
    assert build_daily_review(draft, mapping, source).issues == ()


@pytest.fixture
def historical_draft_chain(tmp_path):
    from uuid import UUID

    from sqlalchemy import insert
    from tests.integration.test_daily_plan_chain import Chain
    from tests.integration.test_live_monitor_projection_migration import _upgrade
    from tests.unit.test_daily_plan import synthetic_plan_payload

    from trade_plan_monitor.ai.daily_review import DailyMapping, daily_source_clauses
    from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
    from trade_plan_monitor.state.database import create_sqlite_engine
    from trade_plan_monitor.state.models import (
        ActivePlan,
        PlanReviewProvenance,
        PlanSource,
        PlanVersionReview,
        RuntimeLiveness,
    )

    chain = Chain(tmp_path)
    raw = synthetic_plan_payload()
    raw["risk_branches"].append({"kind": "FUNDAMENTAL_INVALIDATION", "priority": 1})
    raw["execution_policy"]["risk_priority"] = "FUNDAMENTAL_THEN_SEVERE_THEN_ORDINARY"
    obsolete = canonical(raw)
    source = "Synthetic preserved historical fundamental development draft."
    source_hash, plan_hash = (sha256(text.encode()).hexdigest() for text in (source, obsolete))
    content = {key: value for key, value in raw.items()
               if key not in {"plan_id", "version", "name", "metadata"}}
    mapping = DailyMapping(mapping_version="daily-mapping-v1",
        candidate_content_hash=daily_hash("daily-plan-review-content-v1", content),
        clauses=daily_source_clauses(source), bindings=(), supplements=())
    source_id, identity = (str(UUID(int=n)) for n in (1, 2))
    stamp = chain.now.isoformat()
    models = (PlanSource, PlanVersion, PlanVersionReview, PlanReviewProvenance)
    engine = create_sqlite_engine(tmp_path / "daily.sqlite")
    try:
        _upgrade(engine, "0027_simulation_capital")
        with engine.begin() as connection:
            connection.execute(insert(PlanSource), dict(id=source_id, source_text=source,
                source_hash=source_hash, created_at=stamp))
            connection.execute(insert(PlanVersion), dict(id=identity, plan_id=raw["plan_id"],
                version=raw["version"], symbol=raw["symbol"], plan_hash=plan_hash, status="DRAFT",
                payload_json=obsolete, source_id=source_id, revision=0, created_at=stamp))
            connection.execute(insert(PlanVersionReview), dict(plan_version_id=identity,
                review_issues_json="[]"))
            connection.execute(insert(PlanReviewProvenance), dict(plan_version_id=identity,
                origin="LEGACY_PENDING", extraction_id=None, source_hash=source_hash,
                draft_hash=plan_hash, confirmed_at=None, content_hash=None,
                review_evidence_hash=None, mapping_json=mapping.model_dump_json(),
                required_issues_json=None, resolutions_json=None,
                review_id=None, review_revision=0))
            before = {m.__tablename__: connection.execute(m.__table__.select()).all()
                      for m in models}
            assert all(len(rows) == 1 for rows in before.values())
            assert connection.execute(ActivePlan.__table__.select()).all() == []
            assert connection.execute(RuntimeLiveness.__table__.select()).all() == []
        _upgrade(engine, "0029_native_fact_lookup")
        with engine.connect() as connection:
            assert {m.__tablename__: connection.execute(m.__table__.select()).all()
                    for m in models} == before
            assert connection.exec_driver_sql(
                "SELECT plan_version_id FROM source_coverage_cutover"
            ).all() == [(identity,)]
            for table in ("source_coverage_input", "source_coverage_assessment",
                          "source_coverage_review", "daily_plan_record", "active_plan",
                          "runtime_liveness"):
                assert connection.exec_driver_sql(f'SELECT COUNT(*) FROM "{table}"').scalar() == 0
    finally:
        engine.dispose()
    chain.version = {"id": identity}
    with chain.client:
        yield chain, obsolete


def test_obsolete_development_draft_preserves_raw_document_and_rejects_activation(
    historical_draft_chain,
):
    chain, obsolete = historical_draft_chain
    response = chain.client.get("/api/v1/plan-versions/" + chain.version["id"])
    assert response.status_code == 200
    view = response.json()
    assert view["planJson"] == obsolete
    assert view["sourceText"]
    assert not view["canActivate"]
    assert view["dailyIssues"][0]["code"] == "DAILY_DRAFT_OBSOLETE"
    before = counts(chain)
    rejected = chain.client.post(
        "/api/v1/plan-activations",
        json={
            "planVersionId": view["id"],
            "contentHash": view["contentHash"],
            "sourceHash": view["sourceHash"],
            "reviewEvidenceHash": view["reviewEvidenceHash"],
            "reviewId": view["reviewId"],
            "reviewRevision": 1,
            "expectedRevision": 1,
        },
        headers={"Idempotency-Key": "obsolete-activation"},
    )
    assert rejected.status_code == 409
    assert counts(chain) == before


def test_corrupt_current_document_is_not_reclassified_as_obsolete(chain):
    with chain.plans._unit_of_work() as work:
        row = work.daily.session.get(PlanVersion, chain.version["id"])
        raw = json.loads(row.payload_json)
        raw["risk_branches"].append({"kind": "FUNDAMENTAL_INVALIDATION", "priority": 1})
        row.payload_json = json.dumps(raw)
        row.status = "DRAFT"
        work.commit()
    from trade_plan_monitor.state.source_coverage_store import SourceCoverageIntegrityError

    with pytest.raises(
        SourceCoverageIntegrityError, match="Stored source coverage evidence is invalid"
    ):
        chain.client.get("/api/v1/plan-versions/" + chain.version["id"])


def test_background_rebound_review_preserves_same_technical_runtime_result(tmp_path):
    from datetime import date

    from tests.integration.test_current_plan_api import review_payload
    from tests.integration.test_daily_plan_chain import FRIDAY, WEDNESDAY, Chain
    from tests.integration.test_market_linkage_review import source_mapping

    from trade_plan_monitor.ai.daily_review import daily_source_clauses
    from trade_plan_monitor.state.models import TradingCalendar

    projections = []
    policy_inputs = []
    for index in range(2):
        directory = tmp_path / str(index)
        directory.mkdir()
        current = Chain(directory)
        with current.client:
            draft = UnifiedPlanDraft.from_executable(current.plan)
            source, mapping = source_mapping(draft)
            policy_inputs.append((source, mapping))
            if index:
                source += "\nAnnouncement verification is outside daily monitoring."
                native = daily_source_clauses(source)
                assert len(native) == len(mapping.clauses) + 1
                assert native[-1].disposition == "BACKGROUND" and native[-1].exclusions
                mapping = mapping.model_copy(update={"clauses": (*mapping.clauses, native[-1])})
            assert mapping.supplements == ()
            saved = current.post("plan-drafts", {
                "planJson": daily_draft_json(draft), "sourceText": source,
                "dailyMapping": mapping.model_dump(mode="json"), "expectedRevision": 0,
            })
            response = current.client.get(f"/api/v1/plan-versions/{saved['id']}/source-coverage")
            assert response.status_code == 200, response.text
            coverage = response.json()
            proof = coverage["summary"]
            assert proof["status"] == "COMPLETE" and proof["coverageComplete"], coverage
            assert (proof["contentHash"], proof["sourceHash"]) == (
                saved["contentHash"], saved["sourceHash"],
            )
            reviewed = current.post("plan-review-confirmations", review_payload(saved,
                coverageEvidenceHash=proof["coverageEvidenceHash"],
                coverageRulesVersion=proof["rulesVersion"]))
            current.post("plan-activations", review_payload(saved,
                reviewId=reviewed["reviewId"], reviewRevision=1))
            current.version = saved
            with current.plans._unit_of_work() as work:
                for previous, day in (
                    (date(2026, 9, 17), FRIDAY),
                    (FRIDAY, TUESDAY),
                    (TUESDAY, WEDNESDAY),
                ):
                    work.daily.session.add(
                        TradingCalendar(
                            exchange="SSE", cal_date=day, is_open=True, previous_trade_date=previous
                        )
                    )
                work.commit()
            _, result = ready_chain(current)
            snapshot = result.snapshot
            projections.append(
                {
                    "risks": snapshot["risks"],
                    "risk_action": snapshot["risk_action"],
                    "signals": [
                        {
                            key: s[key]
                            for key in (
                                "state",
                                "planned_qty",
                                "simulated_qty",


                                "executable_qty",
                                "blockers",
                                "confirmed_trade_date",
                                "execution_date",
                            )
                        }
                        for s in snapshot["signals"]
                    ],
                }
            )
    assert projections[0] == projections[1]
    assert projections[1]["signals"][0]["executable_qty"] == 100
    assert policy_inputs[0] == policy_inputs[1]


def test_explicit_human_scope_selection_cannot_hide_technical_or_tradability_clause(chain):
    source = "收盘跌破风险线或者全日停牌时停止加仓。"
    draft = UnifiedPlanDraft.from_executable(chain.plan)
    preview = chain.post(
        "plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source},
    )
    clause = preview["review"]["mapping"]["clauses"][0]
    before = counts(chain)
    chain.post(
        "plan-review-previews",
        {
            "candidateJson": daily_draft_json(draft),
            "sourceText": source,
            "scopeSelections": [
                {
                    "source_hash": sha256(source.encode()).hexdigest(),
                    "start": clause["start"],
                    "end": clause["end"],
                    "excerpt": clause["excerpt"],
                    "origin": "HUMAN_SCOPE_SELECTION",
                    "reason": "FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION",
                }
            ],
        },
        status=422,
    )
    assert counts(chain) == before


@pytest.mark.parametrize("source", ["股价低于39.45元时买入100股。", "收盘跌破38.18元时停止加仓。"])
def test_public_preview_cannot_hide_common_technical_policy_as_scope_or_inventory(chain, source):
    draft = UnifiedPlanDraft.from_executable(chain.plan)
    baseline = chain.post(
        "plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source},
    )
    assert any(i["code"] == "DAILY_SOURCE_CLAUSE_REQUIRED" for i in baseline["review"]["issues"])
    clause = baseline["review"]["mapping"]["clauses"][0]
    before = counts(chain)
    chain.post(
        "plan-review-previews",
        {
            "candidateJson": daily_draft_json(draft),
            "sourceText": source,
            "scopeSelections": [
                {
                    "source_hash": sha256(source.encode()).hexdigest(),
                    "start": clause["start"],
                    "end": clause["end"],
                    "excerpt": clause["excerpt"],
                    "origin": "HUMAN_SCOPE_SELECTION",
                    "reason": "FUNDAMENTALS_REVIEWED_AT_PLAN_GENERATION",
                }
            ],
        },
        status=422,
    )
    mapping = baseline["review"]["mapping"]
    mapping["clauses"][0].update(
        disposition="INVENTORY_ASSERTION",
        paths=[],
        reason="Synthetic concrete holdings assertion with explicit review and no trading policy",
    )
    chain.post(
        "plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source, "mapping": mapping},
        status=422,
    )
    assert counts(chain) == before


@pytest.mark.parametrize("missing", ["condition", "confirmation", "quantity"])
def test_public_review_blocks_incomplete_current_rule_on_success_path(chain, missing):
    draft = UnifiedPlanDraft.from_executable(chain.plan)
    source = "Synthetic explicitly reviewed current rule."
    baseline = chain.post(
        "plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source},
    )
    assert not any(i["code"] == "DAILY_PARAMETER_INVALID" for i in baseline["review"]["issues"])
    raw = draft.model_dump(mode="json")
    raw["ordinary_rules"][0][missing] = None
    candidate = UnifiedPlanDraft.model_validate(raw)
    preview = chain.post(
        "plan-review-previews",
        {"candidateJson": daily_draft_json(candidate), "sourceText": source},
    )
    assert any(
        i["code"] == "PLAN_PARAMETER_REQUIRED" and i["path"].startswith("ordinary_rules.0")
        for i in preview["review"]["issues"]
    )
    assert candidate.to_executable() is None


def test_public_preview_rejects_impossible_macd_warmup_plus_offset(chain):
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = chain.plan.model_dump(mode="json")
    raw["monitoring"]["macd_min_observations"] = 500
    raw["ordinary_rules"][0]["condition"]["conditions"][2] = {
        "type": "DAILY_INDICATOR_COMPARE",
        "indicator": "MACD_HIST",
        "formula_version": "daily-ta-v2",
        "parameters": {"fast": 12, "slow": 26, "signal": 9},
        "offset": 0,
        "comparator": "GT",
        "reference": {
            "mode": "FIXED",
            "value": "0",
            "unit": "INDICATOR",
            "as_of": "2026-09-18",
            "source": "Synthetic MACD threshold reviewed with 500 official observations",
        },
    }
    baseline = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))
    source = "Synthetic three independent technical dimensions explicitly reviewed."
    preview = chain.post(
        "plan-review-previews",
        {"candidateJson": daily_draft_json(baseline), "sourceText": source},
    )
    assert not any(i["code"] == "DAILY_PARAMETER_INVALID" for i in preview["review"]["issues"])
    raw = baseline.model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"]["conditions"][2]["offset"] = 1
    candidate = UnifiedPlanDraft.model_validate(raw)
    before = counts(chain)
    preview = chain.post(
        "plan-review-previews",
        {"candidateJson": daily_draft_json(candidate), "sourceText": source},
    )
    assert any(i["code"] == "PLAN_PARAMETER_INVALID" for i in preview["review"]["issues"])
    assert candidate.to_executable() is None
    assert counts(chain) == before
