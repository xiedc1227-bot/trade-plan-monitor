"""Original risk births and origin references commit with their immutable evaluation."""

import asyncio
from datetime import timedelta

import pytest
from tests.integration.test_daily_plan_chain import Chain, official_proof
from tests.integration.test_plan_risk_evaluation_output import (
    FRIDAY,
    MONDAY_CLOSE,
    TUESDAY_CLOSE,
    observations,
)
from tests.integration.test_plan_risk_evaluation_output import risk_case as risk_case


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "line": 6500}], indirect=True)
def test_first_real_breach_points_to_its_same_transaction_original_evaluation(risk_case):
    case = risk_case
    snapshot = case.result.snapshot
    risk = next(row for row in snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    assert risk["status"] == "PENDING"
    assert risk.get("origin_evaluation_id") == case.result.evaluation_id
    births = snapshot.get("risk_births")
    assert births and births[0]["risk_identity"] == "ordinary-risk"
    assert births[0]["status_before"] == "CLEAR" and births[0]["status_after"] == "PENDING"
    with case.work() as work:
        origin = work.daily.get(risk["origin_evaluation_id"])
        stored = work.daily.get(risk["risk_id"])
    assert origin["kind"] == "EVALUATION" and not origin["id"].startswith("evaluation-head-")
    assert stored["payload"]["origin_evaluation_id"] == origin["id"]
    assert origin["payload"]["risk_births"] == births
    assert (
        observations(case.result)["ordinary-risk"]["ordinary_close"]["confirmation_close_used"]
        is False
    )
    chain = Chain(case.tmp_path)
    with chain.client:
        public = chain.client.get("/api/v1/plan-runtime/" + case.plan.symbol)
    assert public.status_code == 200 and public.json()["snapshot"] is not None
    assert all(
        name not in public.text for name in ("originEvaluationId", "riskBirths", "riskEvaluations")
    )


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "line": 6500}], indirect=True)
def test_actual_first_second_and_later_skip_keep_original_origin_without_extra_comparisons(
    risk_case,
):
    case = risk_case
    original = next(
        risk for risk in case.result.snapshot["risks"] if risk["rule_id"] == "ordinary-risk"
    )
    assert len(case.comparisons) == 1
    second = case.run(MONDAY_CLOSE)
    fact = observations(second)["ordinary-risk"]["ordinary_close"]
    assert fact["status_before"] == "PENDING" and fact["status_after"] == "CONFIRMED"
    assert fact["confirmation_close_used"] is True
    assert fact["close_date"] == str(MONDAY_CLOSE.date())
    risk = next(risk for risk in second.snapshot["risks"] if risk["rule_id"] == "ordinary-risk")
    assert risk["origin_evaluation_id"] == original["origin_evaluation_id"]
    assert "risk_births" not in second.snapshot
    comparisons = len(case.comparisons)
    skipped = case.run(TUESDAY_CLOSE)
    assert "ordinary-risk" not in observations(skipped)
    assert len(case.comparisons) == comparisons
    assert (
        next(risk for risk in skipped.snapshot["risks"] if risk["rule_id"] == "ordinary-risk")[
            "origin_evaluation_id"
        ]
        == original["origin_evaluation_id"]
    )


@pytest.mark.parametrize(
    "risk_case",
    [{"early_activation": True, "line": 6500, "now": TUESDAY_CLOSE, "ordinary_only": True}],
    indirect=True,
)
def test_recovery_keeps_early_real_birth_and_only_the_last_visited_current_observation(risk_case):
    case = risk_case
    snapshot = case.result.snapshot
    assert len(case.comparisons) == 2
    assert "risk_evaluations" not in snapshot
    birth = next(row for row in snapshot["risk_births"] if row["risk_identity"] == "ordinary-risk")
    assert birth["close_date"] == str(FRIDAY)
    risk = next(row for row in snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    assert risk["status"] == "CONFIRMED" and risk["confirmed_trade_date"] == str(
        MONDAY_CLOSE.date()
    )
    assert risk["origin_evaluation_id"] == case.result.evaluation_id
    assert birth["close_date"] in {bar["trade_date"] for bar in snapshot["daily_evidence"]["bars"]}


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "line": 6500}], indirect=True)
def test_old_pending_without_origin_is_not_backfilled_by_observation_or_confirmation(risk_case):
    case = risk_case
    risk = next(row for row in case.result.snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    # A negative historical fixture: valid persisted old state without the optional origin.
    with case.work() as work:
        row = work.daily.get(risk["risk_id"])
        previous = {
            key: value for key, value in row["payload"].items() if key != "origin_evaluation_id"
        }
        work.daily.save(
            row["id"],
            kind="RISK",
            symbol=row["symbol"],
            lineage=row["lineage"],
            expected_revision=row["revision"],
            payload=previous,
        )
        work.commit()
    result = case.run(MONDAY_CLOSE)
    current = next(row for row in result.snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    assert current["status"] == "CONFIRMED" and "origin_evaluation_id" not in current
    assert "risk_births" not in result.snapshot


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "line": 6500}], indirect=True)
def test_equivalent_successor_and_real_generation_replacement_keep_the_original_cause(risk_case):
    case = risk_case
    original = case.result
    old_risk = next(row for row in original.snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    chain = Chain(case.tmp_path)
    chain.plan, chain.now = case.plan, case.pipeline._clock.now()
    with chain.client:
        chain.activate(version=2, activation_revision=1)
    case.plan = chain.plan
    previous_generation = case.pipeline._runtime_generation
    case.rebuild()
    assert case.pipeline._runtime_generation != previous_generation
    result = case.run(case.pipeline._clock.now() + timedelta(minutes=5, seconds=1))
    assert (
        result.snapshot["plan_version_id"]
        == chain.version["id"]
        != original.snapshot["plan_version_id"]
    )
    assert result.snapshot["activation_revision"] == 2
    assert result.snapshot["runtime_generation"] == str(case.pipeline._runtime_generation)
    assert all(
        row["plan_version_id"] == chain.version["id"]
        and row["activation_revision"] == 2
        and row["review_id"] == result.snapshot["review_id"]
        for row in observations(result).values()
    )
    risk = next(row for row in result.snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    assert risk["origin_evaluation_id"] == old_risk["origin_evaluation_id"]
    assert "risk_births" not in result.snapshot
    with case.work() as work:
        assert work.daily.get(original.evaluation_id)["payload"] == original.snapshot


@pytest.mark.parametrize(
    "risk_case",
    [{"early_activation": True, "line": 6500, "reassessment_scope": True}],
    indirect=True,
)
def test_explicit_clear_keeps_prior_origin_audit_and_only_a_later_real_cause_replaces_it(risk_case):
    case = risk_case
    old = next(row for row in case.result.snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    chain = Chain(case.tmp_path)
    chain.plan, chain.now = case.plan, case.pipeline._clock.now()
    branch = next(item for item in case.plan.risk_branches if item.rule_id == "ordinary-risk")
    with chain.client:
        with chain.plans._unit_of_work() as work:
            active = work.plans.get_active(case.plan.symbol)
            details = work.plans.get_version_details(active.plan_version_id)
        with case.work() as work:
            before = work.daily.get(old["risk_id"])
        sibling = next(item for item in case.plan.risk_branches if item.rule_id == "ordinary-other")
        chain.post(
            "plan-risk-reassessments",
            {
                "symbol": case.plan.symbol,
                "riskId": old["risk_id"],
                "planVersionId": details.id,
                "contentHash": details.content_hash,
                "expectedRevision": old["revision"],
                "removalEvidence": "Synthetic wrong sibling policy must not reset another risk.",
                "targetCoreQty": sibling.target_core_qty,
                "targetTacticalQty": sibling.target_tactical_qty,
                "involvesCore": sibling.involves_core,
                "scopeEvidence": sibling.scope_evidence,
            },
            status=422,
        )
        with case.work() as work:
            assert work.daily.get(old["risk_id"]) == before
        receipt = chain.post(
            "plan-risk-reassessments",
            {
                "symbol": case.plan.symbol,
                "riskId": old["risk_id"],
                "planVersionId": details.id,
                "contentHash": details.content_hash,
                "expectedRevision": old["revision"],
                "removalEvidence": (
                    "Synthetic reviewer confirms the original technical cause is removed."
                ),
                "targetCoreQty": branch.target_core_qty,
                "targetTacticalQty": branch.target_tactical_qty,
                "involvesCore": branch.involves_core,
                "scopeEvidence": branch.scope_evidence,
            },
        )
    with case.work() as work:
        audit = work.daily.get(receipt["id"])
        cleared = work.daily.get(old["risk_id"])
    assert (
        audit["payload"]["prior_risk"]["payload"]["origin_evaluation_id"]
        == old["origin_evaluation_id"]
    )
    assert (
        cleared["payload"]["status"] == "CLEAR" and "origin_evaluation_id" not in cleared["payload"]
    )
    assert cleared["payload"]["rule_id"] == old["rule_id"]
    assert cleared["payload"]["holding_scope"] == old["holding_scope"]
    result = case.run(MONDAY_CLOSE)
    current = next(row for row in result.snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    assert current["status"] == "PENDING"
    assert current["origin_evaluation_id"] == result.evaluation_id != old["origin_evaluation_id"]
    assert next(
        row for row in result.snapshot["risk_births"] if row["risk_identity"] == "ordinary-risk"
    )["close_date"] == str(MONDAY_CLOSE.date())


@pytest.mark.parametrize(
    "risk_case", [{"early_activation": True, "line": 6500, "initial": False}], indirect=True
)
def test_immutable_evaluation_failure_rolls_back_birth_origin_and_risk_updates(
    risk_case, monkeypatch
):
    from sqlalchemy import select

    from trade_plan_monitor.state.daily_models import DailyRecord
    from trade_plan_monitor.state.daily_repository import DailyRepository

    case = risk_case
    native_save, attempted, staged_origins = DailyRepository.save, [], []

    def raw_rows(work):
        return tuple(
            tuple(row)
            for row in work.daily.session.execute(
                select(*DailyRecord.__table__.columns)
                .where(
                    DailyRecord.symbol == case.plan.symbol,
                    DailyRecord.kind.in_(("RISK", "EVALUATION")),
                )
                .order_by(DailyRecord.id)
            )
        )

    with case.work() as work:
        before = raw_rows(work)
        before_head = work.daily.get("evaluation-head-" + case.plan.symbol)
        before_cache = dict(case.pipeline.daily_evaluations._current_inputs)
        assert all(
            row["payload"]["status"] == "CLEAR" and "origin_evaluation_id" not in row["payload"]
            for row in work.daily.list(symbol=case.plan.symbol, kind="RISK")
        )

    def fail(repository, identity, **kwargs):
        if kwargs["kind"] == "EVALUATION" and not identity.startswith("evaluation-head-"):
            attempted.append(identity)
            raise RuntimeError("synthetic immutable EVAL write failure")
        saved = native_save(repository, identity, **kwargs)
        if kwargs["kind"] == "RISK" and kwargs["payload"].get("origin_evaluation_id"):
            staged_origins.append(kwargs["payload"]["origin_evaluation_id"])
        return saved

    monkeypatch.setattr(DailyRepository, "save", fail)
    with pytest.raises(RuntimeError, match="synthetic immutable EVAL write failure"):
        case.run()
    assert len(attempted) == 1
    assert staged_origins == attempted
    with case.work() as work:
        assert raw_rows(work) == before
        assert work.daily.get(attempted[0]) is None
        assert work.daily.get("evaluation-head-" + case.plan.symbol) == before_head
    assert case.pipeline.daily_evaluations._current_inputs == before_cache
    assert case.published == []


@pytest.mark.parametrize(
    "risk_case",
    [{"early_activation": True, "line": 6500, "reassessment_scope": True}],
    indirect=True,
)
def test_legacy_kind_without_id_cannot_choose_between_two_reviewed_sibling_branches(risk_case):
    case = risk_case
    original = next(
        row for row in case.result.snapshot["risks"] if row["rule_id"] == "ordinary-risk"
    )
    with case.work() as work:
        row = work.daily.get(original["risk_id"])
        legacy = {
            key: value
            for key, value in row["payload"].items()
            if key not in {"rule_id", "origin_evaluation_id"}
        }
        before = work.daily.save(
            row["id"],
            kind="RISK",
            symbol=row["symbol"],
            lineage=row["lineage"],
            payload=legacy,
            expected_revision=row["revision"],
        )
        work.commit()
    chain = Chain(case.tmp_path)
    chain.plan, chain.now = case.plan, case.pipeline._clock.now()
    branch = next(item for item in case.plan.risk_branches if item.rule_id == "ordinary-risk")
    with chain.client:
        with chain.plans._unit_of_work() as work:
            active = work.plans.get_active(case.plan.symbol)
            details = work.plans.get_version_details(active.plan_version_id)
        chain.post(
            "plan-risk-reassessments",
            {
                "symbol": case.plan.symbol,
                "riskId": row["id"],
                "planVersionId": details.id,
                "contentHash": details.content_hash,
                "expectedRevision": before["revision"],
                "removalEvidence": "Synthetic ambiguous legacy risk must remain unassigned.",
                "targetCoreQty": branch.target_core_qty,
                "targetTacticalQty": branch.target_tactical_qty,
                "involvesCore": branch.involves_core,
                "scopeEvidence": branch.scope_evidence,
            },
            status=422,
        )
    with case.work() as work:
        assert work.daily.get(row["id"]) == before
        assert work.daily.list(symbol=case.plan.symbol, kind="REASSESSMENT") == ()


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "line": 6500}], indirect=True)
def test_real_fulfillment_keeps_origin_until_a_later_actual_new_cause(risk_case):
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

    async def recover_current_minutes():
        await case.pipeline.refresh_references(tuesday.date())
        await case.pipeline.recover_startup(tuesday.date())

    asyncio.run(recover_current_minutes())
    current = case.run(tuesday)
    action = current.snapshot["risk_action"]
    assert action["status"] == "RISK_EXIT" and action["tactical_qty"] == 100
    old = next(row for row in current.snapshot["risks"] if row["rule_id"] == "ordinary-risk")
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
    with case.work() as work:
        fulfilled = work.daily.get(old["risk_id"])
    assert fulfilled["payload"]["status"] == "FULFILLED"
    assert fulfilled["payload"]["origin_evaluation_id"] == old["origin_evaluation_id"]
    result = case.run(TUESDAY_CLOSE + timedelta(days=1))
    new = next(row for row in result.snapshot["risks"] if row["rule_id"] == "ordinary-risk")
    assert new["origin_evaluation_id"] == result.evaluation_id != old["origin_evaluation_id"]
    birth = next(
        row for row in result.snapshot["risk_births"] if row["risk_identity"] == "ordinary-risk"
    )
    assert birth["close_date"] == str(tuesday.date()) and birth["status_before"] == "CLEAR"
