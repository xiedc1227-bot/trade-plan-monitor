"""Actual HTTP, SQLite and outbox reverse boundaries for technical-only monitoring."""

import json
from hashlib import sha256

import pytest
from sqlalchemy import func, select
from tests.integration.test_daily_plan_chain import TUESDAY, ready_chain
from tests.integration.test_daily_plan_chain import chain as chain_fixture
from tests.unit.test_daily_review import reviewed_mapping

from trade_plan_monitor.domain.daily_plan_validation import DailyPlanDraft, daily_draft_json
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
        "/api/v1/daily-plan-facts", json=payload, headers={"Idempotency-Key": "excluded-" + kind}
    )
    assert response.status_code == 422
    assert counts(chain) == before


def test_relabelled_technical_fact_rejects_without_mutation(chain):
    ready_chain(chain)
    before = counts(chain)
    response = chain.client.post(
        "/api/v1/daily-plan-facts",
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
    draft = DailyPlanDraft.from_executable(chain.plan)
    source = "Announcement verification is outside daily monitoring。公司订单持续改善。"
    preview = chain.post(
        "daily-plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source},
    )
    clauses = preview["review"]["mapping"]["clauses"]
    assert clauses[0]["disposition"] == "BACKGROUND"
    assert not any(
        i["path"] == "source." + clauses[0]["clause_id"] for i in preview["review"]["issues"]
    )
    selected = clauses[1]
    narrowed = chain.post(
        "daily-plan-review-previews",
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
    draft = DailyPlanDraft.from_executable(chain.plan)
    mapping = reviewed_mapping(draft, source).model_copy(
        update={"clauses": daily_source_clauses(source)}
    )
    assert build_daily_review(draft, mapping, source).issues == ()


def test_obsolete_development_draft_preserves_raw_document_and_rejects_activation(chain):
    from trade_plan_monitor.domain.daily_hash import canonical

    with chain.plans._unit_of_work() as work:
        row = work.daily.session.get(PlanVersion, chain.version["id"])
        raw = json.loads(row.payload_json)
        raw["risk_branches"].append({"kind": "FUNDAMENTAL_INVALIDATION", "priority": 1})
        raw["execution_policy"]["risk_priority"] = "FUNDAMENTAL_THEN_SEVERE_THEN_ORDINARY"
        obsolete = canonical(raw)
        row.payload_json = obsolete
        row.plan_hash = sha256(obsolete.encode()).hexdigest()
        row.status = "DRAFT"
        work.commit()
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


def test_background_rebound_review_preserves_same_technical_runtime_result(tmp_path):
    from datetime import date

    from tests.integration.test_daily_plan_chain import FRIDAY, WEDNESDAY, Chain

    from trade_plan_monitor.state.models import TradingCalendar

    projections = []
    for index, source in enumerate(
        (
            "Synthetic human-reviewed supplements for this fixture.",
            "Synthetic human-reviewed supplements for this fixture. "
            "Announcement verification is outside daily monitoring.",
        )
    ):
        directory = tmp_path / str(index)
        directory.mkdir()
        current = Chain(directory)
        with current.client:
            current.activate(source=source)
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


def test_explicit_human_scope_selection_cannot_hide_technical_or_tradability_clause(chain):
    source = "收盘跌破风险线或者全日停牌时停止加仓。"
    draft = DailyPlanDraft.from_executable(chain.plan)
    preview = chain.post(
        "daily-plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source},
    )
    clause = preview["review"]["mapping"]["clauses"][0]
    before = counts(chain)
    chain.post(
        "daily-plan-review-previews",
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
    draft = DailyPlanDraft.from_executable(chain.plan)
    baseline = chain.post(
        "daily-plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source},
    )
    assert any(i["code"] == "DAILY_SOURCE_CLAUSE_REQUIRED" for i in baseline["review"]["issues"])
    clause = baseline["review"]["mapping"]["clauses"][0]
    before = counts(chain)
    chain.post(
        "daily-plan-review-previews",
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
        "daily-plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source, "mapping": mapping},
        status=422,
    )
    assert counts(chain) == before


@pytest.mark.parametrize("variant", ["SAME_FACT", "SAME_INDICATOR", "ANY_BYPASS"])
def test_public_review_blocks_missing_independent_dimension_on_success_path(chain, variant):
    draft = DailyPlanDraft.from_executable(chain.plan)
    source = "Synthetic three independent technical dimensions explicitly reviewed."
    baseline = chain.post(
        "daily-plan-review-previews",
        {"candidateJson": daily_draft_json(draft), "sourceText": source},
    )
    assert not any(i["code"] == "DAILY_PARAMETER_INVALID" for i in baseline["review"]["issues"])
    raw = draft.model_dump(mode="json")
    fact = raw["ordinary_rules"][0]["technical"]
    if variant == "SAME_INDICATOR":
        fact = {
            "type": "DAILY_INDICATOR_COMPARE",
            "indicator": "RSI14",
            "formula_version": "daily-ta-v2",
            "parameters": {"period": 14},
            "offset": 0,
            "comparator": "GT",
            "reference": {
                "mode": "FIXED",
                "value": "50",
                "unit": "INDICATOR",
                "as_of": "2026-09-18",
                "source": "Synthetic reviewed RSI",
            },
        }
    if variant == "ANY_BYPASS":
        raw["ordinary_rules"][0]["price_structure"] = {
            "type": "ANY",
            "conditions": [raw["ordinary_rules"][0]["price_structure"], fact],
        }
    else:
        for key in ("price_structure", "volume_or_candle", "technical"):
            raw["ordinary_rules"][0][key] = fact
    candidate = DailyPlanDraft.model_validate(raw)
    preview = chain.post(
        "daily-plan-review-previews",
        {"candidateJson": daily_draft_json(candidate), "sourceText": source},
    )
    assert any(
        i["code"] == "DAILY_PARAMETER_INVALID" and i["path"].startswith("ordinary_rules.0")
        for i in preview["review"]["issues"]
    )
    assert candidate.to_executable() is None


def test_public_preview_rejects_impossible_macd_warmup_plus_offset(chain):
    from trade_plan_monitor.domain.daily_plan_models import DailyTradePlan

    raw = chain.plan.model_dump(mode="json")
    raw["monitoring"]["macd_min_observations"] = 500
    raw["ordinary_rules"][0]["technical"] = {
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
    baseline = DailyPlanDraft.from_executable(DailyTradePlan.model_validate(raw))
    source = "Synthetic three independent technical dimensions explicitly reviewed."
    preview = chain.post(
        "daily-plan-review-previews",
        {"candidateJson": daily_draft_json(baseline), "sourceText": source},
    )
    assert not any(i["code"] == "DAILY_PARAMETER_INVALID" for i in preview["review"]["issues"])
    raw = baseline.model_dump(mode="json")
    raw["ordinary_rules"][0]["technical"]["offset"] = 1
    candidate = DailyPlanDraft.model_validate(raw)
    before = counts(chain)
    preview = chain.post(
        "daily-plan-review-previews",
        {"candidateJson": daily_draft_json(candidate), "sourceText": source},
    )
    assert any(i["code"] == "DAILY_PARAMETER_INVALID" for i in preview["review"]["issues"])
    assert candidate.to_executable() is None
    assert counts(chain) == before
