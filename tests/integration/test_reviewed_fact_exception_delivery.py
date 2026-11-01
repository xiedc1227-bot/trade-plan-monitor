"""Actual old kind-only exception seeds and alert evidence need current attribution."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from tests.integration.test_daily_plan_chain import SH, TUESDAY, Chain
from tests.integration.test_market_exception_runtime import exception_chain, exception_inputs
from tests.integration.test_reviewed_fact_current_authority import _fact
from tests.integration.test_source_coverage_exception_actions import _approval_command, _ledger
from tests.integration.test_unified_runtime import (
    current_plan,
    minute_inputs,
    persist_minute_inputs,
)

from trade_plan_monitor.decision.market_exception_decision import evaluate_market_exception
from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.decision.unified_lifecycle import confirm_signal
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
from trade_plan_monitor.runtime.market_exceptions import (
    _current_exception_inputs,
    apply_exception_decision,
    current_exception_authority,
    record_candidate,
)
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
from trade_plan_monitor.state.market_exception_service import (
    ExceptionAuthorityError,
    ExceptionDecisionCommand,
    ExceptionPreviewCommand,
    preview_exception,
)


def _condition(mode):
    if mode == "unique":
        return _fact("成交不异常放大")
    return dict(type="ALL" if mode == "ambiguous" else "ANY", conditions=[
        _fact("成交不异常放大"), _fact("明显下影"),
        *([dict(type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=4000)]
          if mode == "numeric-any" else [])])


@contextmanager
def _old_exception(tmp_path, route):
    fixture = exception_chain.__wrapped__(tmp_path, SimpleNamespace(param=route))
    chain = next(fixture)
    try:
        raw = chain.plan.model_dump(mode="json")
        raw["ordinary_rules"][0]["condition"] = _condition("ambiguous")
        chain.plan = type(chain.plan).model_validate(raw)
        chain.activate(version=2, activation_revision=1, supplement_revision=1)
        inputs = exception_inputs(chain)
        chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        chain.post("plan-facts", dict(planVersionId=chain.version["id"],
            contentHash=chain.version["contentHash"], factId="old-volume-only",
            kind="VOLUME_OR_CANDLE", tradeDate=str(chain.now.date()),
            evidence="Only volume was checked; the distinct wick condition is unverified.",
            expectedRevision=0))
        chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        with chain.plans._unit_of_work() as work:
            active = work.plans.get_active(chain.plan.symbol)
            review = work.daily.get("review-" + chain.version["id"])["payload"]
            facts = tuple(dict(id=row["id"], **row["payload"])
                          for row in work.daily.list(symbol=chain.plan.symbol, kind="FACT"))
            rule = chain.plan.ordinary_rules[0]
            decision = evaluate_market_exception(chain.plan, rule, series=inputs.series,
                index_bars=inputs.linked_index.official_daily_bars,
                session_dates=inputs.session_dates, decision_session=inputs.official_trade_date,
                cutoff=chain.now, facts=facts,
                inventory=DailyAccounting(work.daily).snapshot(chain.plan.symbol, chain.now.date()),
                risk="UNSATISFIED")
            assert decision.calculation.route == route
            assert decision.confirmation[0].outcome == "SATISFIED"
            seed = confirm_signal(chain.plan, rule, series=inputs.series, facts=facts,
                previous=(), session_dates=inputs.session_dates,
                plan_version_id=chain.version["id"], review_id=review["review_id"],
                linkage=decision, candidate_only=True)
            assert seed is not None
            row = record_candidate(work, chain.plan, active, review, decision, seed,
                sessions=inputs.session_dates, now=chain.now)
            candidate = ExceptionCandidate.model_validate(row["payload"])
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)
            work.daily.save(head["id"], kind="EVALUATION", symbol=chain.plan.symbol,
                lineage=head["lineage"], expected_revision=head["revision"], payload={
                    **head["payload"], "market_linkage": [decision.model_dump(mode="json")]})
            work.commit()
        yield chain, candidate
    finally:
        fixture.close()


@pytest.mark.parametrize("route", ["WEAK_MINIMUM", "BROKEN_STRONG"])
@pytest.mark.parametrize("stage", ["preview", "approve"])
def test_old_exception_fact_collision_cannot_grant_a_new_permission(tmp_path, route, stage):
    with _old_exception(tmp_path, route) as (chain, candidate):
        command = ExceptionPreviewCommand(candidate_id=candidate.candidate_id,
            expected_revision=1, proposed_quantity=None if route == "WEAK_MINIMUM" else 300)
        shown = None
        if stage == "approve":
            # Genuine pre-fix preview arrangement; no current source authority is mocked.
            with chain.plans._unit_of_work() as work:
                shown = preview_exception(work.daily, command,
                    current=lambda c: _current_exception_inputs(work, c, chain.now), now=chain.now)
                work.commit()
        before = _ledger(chain)
        with pytest.raises(ExceptionAuthorityError, match="REVIEWED_FACT_REQUIRED"):
            with chain.plans._unit_of_work() as work:
                if stage == "preview":
                    preview_exception(work.daily, command,
                        current=lambda c: current_exception_authority(work, c, chain.now),
                        now=chain.now)
                else:
                    apply_exception_decision(work, _approval_command(shown), now=chain.now)
                work.commit()
        assert _ledger(chain) == before


@pytest.mark.parametrize("route", ["WEAK_MINIMUM", "BROKEN_STRONG"])
def test_old_exception_reminder_is_not_current_but_rejection_remains_available(tmp_path, route):
    with _old_exception(tmp_path, route) as (chain, candidate):
        binding = candidate.binding
        with chain.plans._unit_of_work() as work:
            active = work.plans.get_active(chain.plan.symbol)
            review = work.daily.get("review-" + chain.version["id"])["payload"]
            identity = chain.runtime._enqueue(work, chain.plan, active, review, chain.now,
                cause_id=candidate.candidate_id, side="REMINDER", quantity=None, simulated=0,
                confirmed=str(binding.decision_session), execution=None, scope=None,
                evidence=[binding.model_dump(mode="json")], rule_id=binding.rule_id,
                alert_kind="EXCEPTION_REVIEW")
            work.commit()
        with chain.plans._unit_of_work() as work:
            event = work.alerts.get(UUID(identity))
            assert not daily_delivery_allowed(work.daily.session, event, chain.now)
            assert not work.alerts.is_current_actionable(event, market_date=chain.now.date())
            result = apply_exception_decision(work, ExceptionDecisionCommand(
                command_id="reject-old-fact-collision", candidate_id=candidate.candidate_id,
                expected_revision=1, decision="REJECT", reason="Decline an ambiguous old seed"),
                now=chain.now)
            work.commit()
        assert result.candidate.state == "REJECTED"
        before = _ledger(chain)
        with chain.plans._unit_of_work() as work:
            replay = apply_exception_decision(work, ExceptionDecisionCommand(
                command_id="reject-old-fact-collision", candidate_id=candidate.candidate_id,
                expected_revision=1, decision="REJECT", reason="Decline an ambiguous old seed"),
                now=chain.now)
            work.commit()
        assert replay == result and _ledger(chain) == before


@pytest.mark.parametrize("mode", ["ambiguous", "unique", "numeric-any"])
def test_old_alert_message_checks_fact_attribution_without_losing_numeric_any(tmp_path, mode):
    chain = Chain(tmp_path)
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw.update(ordinary_rules=[], alert_rules=[dict(kind="RISK_ALERT", rule_id="fact-alert",
        confirmation=dict(kind="COMPLETED_BAR_CLOSE", timeframe_minutes=5),
        condition=_condition(mode))])
    chain.plan = UnifiedTradePlan.model_validate(raw)
    with chain.client:
        chain.activate()
        chain.now = datetime(2026, 9, 22, 9, 35, 12, tzinfo=SH)
        inputs = minute_inputs(chain)
        persist_minute_inputs(chain, inputs)
        chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        chain.post("plan-facts", dict(planVersionId=chain.version["id"],
            contentHash=chain.version["contentHash"], factId="old-alert-volume-only",
            kind="VOLUME_OR_CANDLE", tradeDate=str(TUESDAY),
            evidence="Only volume was checked; the distinct wick condition is unverified.",
            expectedRevision=0))
        chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        with chain.plans._unit_of_work() as work:
            active = work.plans.get_active(chain.plan.symbol)
            review = work.daily.get("review-" + chain.version["id"])["payload"]
            facts = tuple(dict(id=r["id"], **r["payload"])
                          for r in work.daily.list(symbol=chain.plan.symbol, kind="FACT"))
            evidence = evaluate_unified_condition(chain.plan.alert_rules[0].condition, None,
                facts=facts, bars=inputs.five_minute_bars, target=inputs.minute_target)
            assert evidence.outcome == "SATISFIED"
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)
            alert = {**head["payload"]["alerts"][0], "cause_id": "old-fact-alert-cause",
                     "outcome": "SATISFIED", "evidence": [evidence.model_dump(mode="json")]}
            work.daily.save(head["id"], kind="EVALUATION", symbol=chain.plan.symbol,
                lineage=head["lineage"], expected_revision=head["revision"],
                payload={**head["payload"], "alerts": [alert]})
            chain.now += timedelta(microseconds=1)
            identity = chain.runtime._enqueue(work, chain.plan, active, review,
                chain.now, cause_id=alert["cause_id"],
                side="REMINDER", quantity=None, simulated=0, confirmed=str(TUESDAY),
                execution=None, scope=None, evidence=alert["evidence"],
                rule_id="fact-alert", alert_kind="RISK_ALERT")
            work.commit()
        chain.now += timedelta(microseconds=2)
        with chain.plans._unit_of_work() as work:
            event = work.alerts.get(UUID(identity))
            assert daily_delivery_allowed(work.daily.session, event, chain.now) == (
                mode != "ambiguous")
            assert work.alerts.is_current_actionable(event, market_date=chain.now.date()) == (
                mode != "ambiguous")
