"""Real cutover risks stay observable while only verified causes offer exits."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import insert
from tests.integration.test_source_action_cutover import _REVIEW, _daily, _risk_payload
from tests.integration.test_source_action_cutover import legacy as legacy
from tests.integration.test_source_coverage_risk_simulation import (
    _AT,
    _SESSIONS,
    _retained_core_case,
)

from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.market_data.daily_data import (
    CertifiedDailyBar,
    DailyExecutionQuote,
    DailySeries,
)
from trade_plan_monitor.runtime.daily_service import (
    DailyRuntimeEvaluationService,
    DailyRuntimeInputs,
)
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def _series(case, now, close):
    return DailySeries(symbol=case.draft.symbol,
        bars=(CertifiedDailyBar(bar_id="offline-official-" + str(now.date()),
            symbol=case.draft.symbol, trade_date=now.date(), open=Decimal(close),
            high=Decimal(close + 20), low=Decimal(close - 20), close=Decimal(close),
            volume_shares=1000, official=True, provider="offline", basis_id="offline-qfq",
            adjustment_as_of=now.date(), received_at=now, available_at=now),),
        basis_id="offline-qfq", adjustment_as_of=now.date(), provider="offline",
        quote_comparable=True, session_dates=(now.date(),), suspended_dates=(), cutoff=now)


def _observed(case):
    with case.work() as work:
        for previous, day in zip((date(2026, 10, 22), *_SESSIONS[:-1]), _SESSIONS, strict=True):
            work.daily.session.add(TradingCalendar(exchange=case.draft.market, cal_date=day,
                is_open=True, previous_trade_date=previous))
        work.daily.session.flush()
        DailyAccounting(work.daily).initialize(symbol=case.draft.symbol, core_qty=100,
            tactical_qty=200, expected_revision=0, now=_AT)
        work.commit()
    quote = DailyExecutionQuote(symbol=case.draft.symbol, price_fen=2600, quote_at=_AT,
        available_at=_AT, evaluated_at=_AT, tradable=True, special_state_verified=True,
        liquidity_available=True)
    return DailyRuntimeEvaluationService(case.work).run_inputs(plan=case.draft.to_executable(),
        expected_activation_revision=1, inputs=DailyRuntimeInputs(evaluated_at=_AT,
            official_trade_date=None, series=None, session_dates=_SESSIONS,
            suspended_dates=(), quote=quote, data_blockers=()))


@pytest.mark.parametrize("options", [{}, {"buy_only_failure": True}, {"expired": True}])
def test_original_latched_risk_keeps_its_exit_when_ordinary_source_or_window_is_unavailable(
    legacy, options
):
    case = legacy(**options)
    result = _observed(case)
    action = result.snapshot["risk_action"]
    assert action["cause_id"] == case.cause_id and action["status"] == "RISK_EXIT"
    assert (action["core_qty"], action["tactical_qty"], action["blockers"]) == (100, 200, [])
    assert "SOURCE_COVERAGE_REQUIRED" in result.snapshot["data_blockers"]
    assert result.snapshot["signals"] == [] and len(result.event_ids) == 1
    with case.work() as work:
        event = work.alerts.get(UUID(result.event_ids[0]))
        assert event.signal_type == "RISK_EXIT" and event.quantity == 300


@pytest.mark.parametrize("extra", ["所有风险退出必须先等待蓝灯。",
                                   "Only buy when turnover exceeds 3 percent."])
def test_unknown_source_remains_visible_but_cannot_offer_a_risk_exit(legacy, extra):
    case = legacy(extra=extra)
    result = _observed(case)
    assert result.snapshot["risk_action"]["status"] == "NONE"
    assert result.snapshot["next_action"] == "WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION"
    assert "SOURCE_COVERAGE_REQUIRED" in result.snapshot["data_blockers"]
    assert result.event_ids == ()
    with case.work() as work:
        assert work.daily.get(case.cause_id)["payload"]["status"] == "CONFIRMED"
        assert work.daily.list(symbol=case.draft.symbol, kind="SIMULATION") == ()


def test_a_latched_risk_without_the_real_cutover_cannot_produce_an_exit_event(legacy):
    case = legacy(upgraded=False)
    result = _observed(case)
    assert result.snapshot["risk_action"]["status"] == "NONE" and result.event_ids == ()
    assert "SOURCE_COVERAGE_UPGRADE_REQUIRED" in result.snapshot["data_blockers"]
    assert any(row["risk_id"] == case.cause_id and row["status"] == "CONFIRMED"
               for row in result.snapshot["risks"])


def test_unproved_severe_sibling_cannot_donate_quantity_or_own_the_new_runtime_offer(legacy):
    case = _retained_core_case(legacy)
    severe_id, severe = _risk_payload(case.draft, index=1)
    severe["technical_evidence"], severe["evidence_ids"] = [], []
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord), _daily(severe_id, "RISK", case.draft, severe))
    result = _observed(case)
    action = result.snapshot["risk_action"]
    assert action["cause_id"] == case.cause_id
    assert (action["core_qty"], action["tactical_qty"]) == (0, 200)
    assert any(risk["risk_id"] == severe_id and risk["status"] == "CONFIRMED"
               for risk in result.snapshot["risks"])
    assert "SOURCE_COVERAGE_REQUIRED" in result.snapshot["data_blockers"]
    with case.work() as work:
        event = work.alerts.get(UUID(result.event_ids[0]))
        assert event.cause_id == case.cause_id and event.quantity == 200


@pytest.mark.parametrize("extra", [None, "所有买入必须先等待蓝灯。"])
def test_zero_issue_legacy_source_cannot_generate_new_signals_even_when_facts_are_satisfied(
    legacy, extra
):
    now = _AT.replace(hour=16, minute=1)
    case = legacy(extra=extra, clock_at=now)
    series = _series(case, now, 3970)
    with case.work() as work:
        old = work.daily.get(case.cause_id)
        work.daily.save(case.cause_id, kind="RISK", symbol=case.draft.symbol,
            lineage=case.draft.symbol, expected_revision=old["revision"],
            payload={**old["payload"], "status": "CLEAR", "earliest_execution_date": None,
                "confirmed_trade_date": None, "breach_trade_date": None, "second_close_date": None})
        for kind in ("PRICE_STRUCTURE", "VOLUME_OR_CANDLE", "TECHNICAL", "SEVERE_STRUCTURE",
                     "SEVERE_DETERIORATION"):
            work.daily.save("offline-" + kind, kind="FACT", symbol=case.draft.symbol,
                lineage=case.draft.symbol, expected_revision=0, payload=dict(
                    plan_version_id=case.id, content_hash=case.content_hash, kind=kind,
                    trade_date=str(now.date()), signal_id=None,
                    evidence="Synthetic reviewed complete technical structure evidence",
                    verified=True, satisfied=not kind.startswith("SEVERE_"),
                    verified_at=now.isoformat(), available_at=now.isoformat(),
                    official_evidence=None))
        facts = tuple(row["payload"] | {"id": row["id"]}
                      for row in work.daily.list(symbol=case.draft.symbol, kind="FACT"))
        assert evaluate_unified_condition(case.draft.ordinary_rules[0].condition, series,
            facts=facts).outcome == "SATISFIED"
        assert not work.plans.get_version_details(case.id).daily_issues
        assert work.daily.get("review-" + case.id)["payload"]["review_id"] == _REVIEW
        work.commit()
    result = DailyRuntimeEvaluationService(case.work).run_inputs(plan=case.draft.to_executable(),
        inputs=DailyRuntimeInputs(evaluated_at=now, official_trade_date=now.date(), series=series,
            session_dates=(*_SESSIONS, now.date() + timedelta(days=1)), suspended_dates=(),
            quote=None, data_blockers=()))
    assert result.snapshot["signals"] == [] and result.event_ids == ()
    assert "SOURCE_COVERAGE_REQUIRED" in result.snapshot["data_blockers"]


def test_original_risk_policy_can_form_a_new_protective_cause_despite_buy_only_source_failure(
    legacy,
):
    case = legacy(buy_only_failure=True)
    clock = [_AT.replace(hour=16, minute=3)]
    case.work = lambda: SqlAlchemyUnitOfWork(case.sessions, clock=lambda: clock[0])
    sessions = tuple(_AT.date() + timedelta(days=n) for n in range(3))
    with case.work() as work:
        for previous, day in zip((date(2026, 10, 26), *sessions[:-1]), sessions, strict=True):
            work.daily.session.add(TradingCalendar(exchange=case.draft.market, cal_date=day,
                is_open=True, previous_trade_date=previous))
        work.daily.session.flush()
        DailyAccounting(work.daily).initialize(symbol=case.draft.symbol, core_qty=100,
            tactical_qty=200, expected_revision=0, now=clock[0])
        old = work.daily.get(case.cause_id)
        work.daily.save(case.cause_id, kind="RISK", symbol=case.draft.symbol,
            lineage=case.draft.symbol, expected_revision=old["revision"],
            payload={**old["payload"], "status": "CLEAR", "earliest_execution_date": None,
                "confirmed_trade_date": None, "breach_trade_date": None,
                "second_close_date": None, "evidence_ids": []})
        work.commit()
    runtime = DailyRuntimeEvaluationService(case.work)
    for number, expected in enumerate(("PENDING", "CONFIRMED")):
        clock[0] = clock[0].replace(day=sessions[number].day)
        result = runtime.run_inputs(plan=case.draft.to_executable(), inputs=DailyRuntimeInputs(
            evaluated_at=clock[0], official_trade_date=clock[0].date(),
            series=_series(case, clock[0], case.draft.levels.risk_line_fen - 1),
            session_dates=sessions, suspended_dates=(), quote=None, data_blockers=()))
        ordinary = next(row for row in result.snapshot["risks"]
                        if row["kind"] == "ORDINARY_TECHNICAL")
        assert ordinary["status"] == expected
        assert result.snapshot["signals"] == [] and result.event_ids == ()
    assert ordinary["breach_trade_date"] == str(sessions[0])
    assert ordinary["second_close_date"] == str(sessions[1])
    assert ordinary["earliest_execution_date"] == str(sessions[2])
    clock[0] = clock[0].replace(day=sessions[2].day, hour=10)
    quote = DailyExecutionQuote(symbol=case.draft.symbol, price_fen=2600,
        quote_at=clock[0], available_at=clock[0], evaluated_at=clock[0], tradable=True,
        special_state_verified=True, liquidity_available=True)
    final = runtime.run_inputs(plan=case.draft.to_executable(), inputs=DailyRuntimeInputs(
        evaluated_at=clock[0], official_trade_date=None, series=None, session_dates=sessions,
        suspended_dates=(), quote=quote, data_blockers=()))
    action = final.snapshot["risk_action"]
    assert action["status"] == "RISK_EXIT" and action["cause_id"] == case.cause_id
    assert (action["core_qty"], action["tactical_qty"], action["blockers"]) == (100, 200, [])
    assert "SOURCE_COVERAGE_REQUIRED" in final.snapshot["data_blockers"]
    assert len(final.event_ids) == 1
