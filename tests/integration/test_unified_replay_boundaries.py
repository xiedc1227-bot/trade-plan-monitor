"""Independent expected states for current replay boundaries and isolation."""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.integration.test_unified_replay import fixture, run
from tests.unit.test_unified_replay_input import research_input

from trade_plan_monitor.backtest.control import BacktestCancellationResult, CancellationToken
from trade_plan_monitor.backtest.research_input import (
    ResearchAdjustmentProof,
    ResearchFact,
    ResearchFactor,
    ResearchSimulation,
)
from trade_plan_monitor.backtest.research_runner import _calendar_context
from trade_plan_monitor.backtest.research_session import ResearchSession
from trade_plan_monitor.backtest.research_valuation import ResearchValuation
from trade_plan_monitor.market_data.models import TradingDay


@pytest.mark.parametrize("eligible", [True, False])
def test_reminder_only_has_actual_evidence_without_inventory_or_authority_outside_window(
    tmp_path, eligible
):
    store, dataset_hash, original, frozen = fixture(tmp_path)
    raw = original.model_dump(mode="python")
    raw.update(
        ordinary_rules=[],
        alert_rules=[
            {
                "kind": "RISK_ALERT",
                "rule_id": "remind-only",
                "condition": raw["ordinary_rules"][0]["condition"],
                "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            }
        ],
    )
    if not eligible:
        raw["activation"] = {
            "mode": "DATE_RANGE",
            "start_date": "2026-08-25",
            "end_date": "2026-08-26",
        }
    plan = type(original).model_validate(raw)
    frozen = research_input(plan).model_copy(update={"started_at": frozen.started_at})
    report = run(store, dataset_hash, plan, frozen)
    assert all(not event.signals for event in report.current_events)
    assert report.final_inventory.total_qty == 0
    assert report.operations == ()
    alerts = [alert for event in report.current_events for alert in event.alerts]
    if eligible:
        assert alerts[0].outcome == "SATISFIED"
        assert alerts[0].confirmed_at == frozen.started_at.replace(hour=9, minute=35)
        assert alerts[0].cause_id
        assert alerts[0].evidence[0].bar_ids == ("2026-08-24T09:35:00+08:00",)
    else:
        assert not alerts
        assert all(
            "PLAN_ACTIVATION_WINDOW_INACTIVE" in event.blockers for event in report.current_events
        )


@pytest.mark.parametrize(
    "validity, expected",
    [
        ({"mode": "PLAN_ACTIVE"}, True),
        ({"mode": "DATE_RANGE", "start_date": "2026-08-20", "end_date": "2026-08-23"}, False),
        ({"mode": "DATE_RANGE", "start_date": "2026-08-24", "end_date": "2026-08-24"}, True),
    ],
)
def test_rule_date_range_and_plan_active_are_separate(tmp_path, validity, expected):
    store, dataset_hash, original, frozen = fixture(tmp_path)
    raw = original.model_dump(mode="python")
    raw["ordinary_rules"][0]["validity"] = validity
    plan = type(original).model_validate(raw)
    report = run(
        store,
        dataset_hash,
        plan,
        research_input(plan).model_copy(update={"started_at": frozen.started_at}),
    )
    assert any(event.signals for event in report.current_events) is expected


def test_intraday_start_uses_completed_context_only_after_start(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    started = frozen.started_at.replace(hour=14, minute=1)
    fact = ResearchFact(
        kind="FACT",
        operation_id="start-observation",
        order=0,
        at=started,
        fact_id="technical",
        fact_kind="TECHNICAL",
        trade_date=started.date(),
        satisfied=False,
        evidence="Synthetic start event, explicitly negative independent technical fact",
    )
    report = run(
        store,
        dataset_hash,
        plan,
        frozen.model_copy(update={"started_at": started, "operations": (fact,)}),
    )
    assert all(event.at >= started for event in report.current_events)
    assert all(mark.marked_at >= started for mark in report.daily_equity)
    assert report.current_events[0].signals[0].confirmed_at == started.replace(minute=0)
    assert report.final_inventory.total_qty == 0


def test_mid_replay_cancellation_returns_no_partial_completed_report(tmp_path, monkeypatch):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    token = CancellationToken()
    from trade_plan_monitor.backtest import research_runner

    evaluate = research_runner._Replay.evaluate

    def stop_after_first(self, *args):
        evaluate(self, *args)
        token.cancel()

    monkeypatch.setattr(research_runner._Replay, "evaluate", stop_after_first)
    result = run(store, dataset_hash, plan, frozen, cancellation_token=token)
    assert isinstance(result, BacktestCancellationResult)
    assert result.phase == "RUN_EVALUATION"
    assert result.last_safe_event_id
    assert not (tmp_path / "results.sqlite").exists()


def test_calendar_context_has_no_unneeded_future_and_at_most_512_rows():
    beginning = date(2024, 1, 1)
    calendar = tuple(
        TradingDay(
            exchange="SSE",
            cal_date=beginning + timedelta(days=i),
            is_open=(beginning + timedelta(days=i)).weekday() < 5,
            previous_trade_date=beginning - timedelta(days=1),
        )
        for i in range(1000)
    )
    current = date(2026, 1, 2)
    context = _calendar_context(calendar, current)
    assert len(context) == 512
    assert context[-1].cal_date == date(2026, 1, 5)
    assert [d.cal_date for d in context if d.cal_date > current and d.is_open] == [date(2026, 1, 5)]


def test_event_capacity_fails_before_another_runtime_mutation():
    from trade_plan_monitor.backtest.research_runner import _Replay

    replay = object.__new__(_Replay)
    replay.events = [None] * 70000
    with pytest.raises(ValueError, match="RESEARCH_EVENT_LIMIT_EXCEEDED"):
        replay.evaluate(None, None, ())


def test_cause_resolution_reaches_occurrence_501_in_stored_ledger(tmp_path):
    from tests.unit.test_unified_replay_input import create, research_plan

    plan = research_plan()
    session = ResearchSession(tmp_path, create(plan, research_input(plan)), ())
    payload = json.loads(
        (Path(__file__).parents[2] / "web/tests/fixtures/unified-replay-decision.json").read_text(
            encoding="utf-8"
        )
    )["researchDecision"]["signals"][0]
    payload["rule_id"] = "same-rule"
    try:
        with session.work() as work:
            for i in range(501):
                work.daily.save(
                    f"occurrence-{i:04d}",
                    kind="SIGNAL",
                    symbol=plan.symbol,
                    lineage=plan.plan_id,
                    expected_revision=0,
                    payload={**payload, "signal_id": f"occurrence-{i:04d}"},
                )
            work.commit()
        assert session.resolve_cause(rule_id="same-rule", occurrence=501)["id"] == "occurrence-0500"
    finally:
        session.close()


def test_money_projection_rejects_cumulative_unsafe_cost():
    from tests.unit.test_unified_replay_input import create, research_plan

    plan = research_plan()
    valuation = ResearchValuation(create(plan, research_input(plan)))
    valuation.cost = 9_007_199_254_740_990
    with pytest.raises(ValueError, match="RESEARCH_VALUATION_SAFE_NUMBER_EXCEEDED"):
        valuation.operation(
            SimpleNamespace(
                kind="SIMULATE", status="APPLIED", side="BUY", monitor_price_fen=6400, quantity=100
            )
        )


def test_future_market_mutation_with_early_proof_preserves_every_prior_event(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    with store.open_frozen_dataset(dataset_hash) as reader:
        days, scope = tuple(reader), reader.scope
    at = frozen.started_at
    proof = ResearchAdjustmentProof(
        proof_id="early-proof",
        dataset_hash=dataset_hash,
        symbol=plan.symbol,
        provider="TUSHARE",
        adjustment_as_of=date(2026, 8, 21),
        available_at=at,
        received_at=at,
        quote_basis_factor=Decimal("1"),
        factors=tuple(
            ResearchFactor(trade_date=day.trade_date, factor=Decimal("1"))
            for day in days
            if day.daily_bar is not None and day.trade_date < at.date()
        ),
        evidence="Synthetic verified factors independently available before the future close",
    )
    frozen = frozen.model_copy(update={"adjustment_proofs": (proof,)})
    original = run(store, dataset_hash, plan, frozen)
    future = next(day.daily_bar for day in days if day.trade_date == at.date())
    store.record_daily_bars((future.model_copy(update={"close_fen": 6410}),))
    changed_hash = store.freeze_dataset(scope).dataset_hash
    assert changed_hash != dataset_hash
    changed = run(
        store,
        changed_hash,
        plan,
        frozen.model_copy(
            update={"adjustment_proofs": (proof.model_copy(update={"dataset_hash": changed_hash}),)}
        ),
    )
    assert original.run_id != changed.run_id
    assert [
        event.model_dump() for event in original.current_events if event.at < future.received_at
    ] == [event.model_dump() for event in changed.current_events if event.at < future.received_at]
    assert original.current_events[0].at == proof.received_at


def test_only_explicit_independent_fact_grants_a_second_whole_occurrence(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    first = ResearchSimulation(
        kind="SIMULATE",
        operation_id="first",
        order=0,
        at=frozen.started_at.replace(hour=9, minute=35, second=12),
        rule_id=plan.ordinary_rules[0].rule_id,
        occurrence=1,
        quantity=100,
    )
    independent = ResearchFact(
        kind="FACT",
        operation_id="new-occurrence",
        order=0,
        at=first.at.replace(minute=40),
        fact_id="independent-2",
        fact_kind="INDEPENDENT_EVENT",
        trade_date=first.at.date(),
        satisfied=True,
        rule_id=first.rule_id,
        occurrence=1,
        evidence="Synthetic independent technical occurrence after the consumed first signal",
    )
    second = first.model_copy(
        update={"operation_id": "second", "at": first.at.replace(minute=45), "occurrence": 2}
    )
    report = run(
        store,
        dataset_hash,
        plan,
        frozen.model_copy(update={"operations": (first, independent, second)}),
    )
    assert [outcome.status for outcome in report.operations] == ["APPLIED"] * 3
    assert report.operations[0].cause_id != report.operations[2].cause_id
    assert report.final_inventory.total_qty == 200
    assert all(signal.state == "SIMULATED" for signal in report.current_events[-1].signals)


def test_replay_cannot_reach_provider_ai_live_lifecycle_or_delivery(tmp_path, monkeypatch):
    import socket

    from trade_plan_monitor.ai.openai_compatible import OpenAICompatibleProvider
    from trade_plan_monitor.backtest import research_session
    from trade_plan_monitor.market_data.tushare_client import (
        _DefaultTushareQuery,
        _DirectTushareQuery,
    )
    from trade_plan_monitor.notifications.channels import (
        ConsoleChannel,
        InAppChannel,
        WebhookChannel,
    )
    from trade_plan_monitor.notifications.outbox import AlertOutbox
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

    store, dataset_hash, plan, frozen = fixture(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("offline replay reached a forbidden external/live/delivery boundary")

    for cls, name in [
        (socket.socket, "connect"),
        (OpenAICompatibleProvider, "_request_once"),
        (_DefaultTushareQuery, "__call__"),
        (_DirectTushareQuery, "__call__"),
        (PersistentPlanWebLifecycle, "__init__"),
        (AlertOutbox, "enqueue_daily"),
        (AlertOutbox, "enqueue"),
        (AlertOutbox, "enqueue_explicit"),
        (ConsoleChannel, "deliver"),
        (InAppChannel, "deliver"),
        (WebhookChannel, "deliver"),
    ]:
        monkeypatch.setattr(cls, name, forbidden)
    create = research_session.create_sqlite_engine
    opened = []

    def isolated_engine(path):
        assert path.name == "runtime.sqlite" and path.parent.name.startswith("unified-research-")
        opened.append(path)
        return create(path)

    monkeypatch.setattr(research_session, "create_sqlite_engine", isolated_engine)
    report = run(store, dataset_hash, plan, frozen)
    assert report.current_events[0].signals
    assert len(opened) == 1 and not opened[0].exists()


def _minute_batch(day, *, delay=False, shift=0):
    from trade_plan_monitor.market_data.historical_provider import (
        HistoricalMinuteBatch,
        HistoricalMinuteProfile,
        HistoricalOpeningSpecial,
    )

    delta = timedelta(days=shift)
    bars = tuple(
        bar.model_copy(
            update={
                "bar_end": bar.bar_end + delta,
                "received_at": bar.received_at
                + delta
                + (
                    timedelta(minutes=6)
                    if delay and bar.bar_end.minute == 34 and bar.bar_end.hour == 9
                    else timedelta()
                ),
            }
        )
        for bar in day.minutes
    )
    return HistoricalMinuteBatch(
        symbol=day.symbol,
        trade_date=day.trade_date + delta,
        contract_version=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        bars=bars,
        opening_special=HistoricalOpeningSpecial(
            symbol=day.symbol,
            source_time=bars[0].bar_end.replace(hour=9, minute=30),
            open_fen=6400,
            high_fen=6401,
            low_fen=6399,
            close_fen=6400,
            volume_shares=500,
            amount_yuan=Decimal("32000"),
        ),
    )


def test_profile_rejects_delayed_minutes_and_incomplete_visible_bucket_cannot_confirm(tmp_path):
    store, dataset_hash, plan, frozen = fixture(tmp_path)
    with store.open_frozen_dataset(dataset_hash) as reader:
        days = tuple(reader)
    day = next(day for day in days if day.minutes)
    # This dataset profile explicitly fixes receipt grace. Do not forge a new profile.
    with pytest.raises(ValueError, match="deterministic grace"):
        _minute_batch(day, delay=True)
    fact = ResearchFact(
        kind="FACT",
        operation_id="before-close",
        order=0,
        at=frozen.started_at.replace(hour=9, minute=33, second=12),
        fact_id="negative-early",
        fact_kind="TECHNICAL",
        trade_date=day.trade_date,
        satisfied=False,
        evidence="Synthetic negative technical observation before the complete five-minute close",
    )
    report = run(store, dataset_hash, plan, frozen.model_copy(update={"operations": (fact,)}))
    first = report.current_events[0]
    assert first.at == fact.at
    assert first.signals == ()
    assert first.conditions[0].evidence.outcome == "MISSING_INPUT"
    assert next(event for event in report.current_events if event.signals).at == (
        frozen.started_at.replace(hour=9, minute=35, second=12)
    )


def test_daily_next_session_execution_and_minute_expiry_share_calendar(tmp_path):
    from trade_plan_monitor.domain.plan_codec import load_plan_json

    store, dataset_hash, minute_plan, frozen = fixture(tmp_path)
    with store.open_frozen_dataset(dataset_hash) as reader:
        days, scope = tuple(reader), reader.scope
    day = next(day for day in days if day.minutes)
    following = day.trade_date + timedelta(days=1)
    store.record_trading_days(
        (
            day.trading_day.model_copy(
                update={"cal_date": following, "previous_trade_date": day.trade_date}
            ),
        )
    )
    store.record_daily_bars(
        (
            day.daily_bar.model_copy(
                update={
                    "trade_date": following,
                    "received_at": day.daily_bar.received_at + timedelta(days=1),
                }
            ),
        )
    )
    store.record_daily_limits(
        (
            day.daily_limit.model_copy(
                update={
                    "trade_date": following,
                    "received_at": day.daily_limit.received_at + timedelta(days=1),
                }
            ),
        )
    )
    store.record_minute_batch(_minute_batch(day, shift=1))
    dataset_hash = store.freeze_dataset(scope.model_copy(update={"end": following})).dataset_hash
    minute_report = run(store, dataset_hash, minute_plan, frozen)
    next_event = next(
        event for event in minute_report.current_events if event.at.date() == following
    )
    assert next_event.signals[0].state == "EXPIRED"
    assert next_event.signals[0].executable_qty == 0
    assert len(next_event.signals) == 1
    plan = load_plan_json(
        (Path(__file__).parents[1] / "fixtures/unified-replay/daily-plan.json").read_text(
            encoding="utf-8"
        )
    )
    proof = ResearchAdjustmentProof(
        proof_id="daily-proof",
        dataset_hash=dataset_hash,
        symbol=plan.symbol,
        provider="TUSHARE",
        adjustment_as_of=day.trade_date,
        available_at=day.daily_bar.received_at,
        received_at=day.daily_bar.received_at,
        quote_basis_factor=Decimal("1"),
        factors=tuple(
            ResearchFactor(trade_date=d.trade_date, factor=Decimal("1"))
            for d in days
            if d.daily_bar is not None
        ),
        evidence="Explicit synthetic verified adjustment proof for next-session simulation",
    )
    operation = ResearchSimulation(
        kind="SIMULATE",
        operation_id="next-session",
        order=0,
        at=frozen.started_at.replace(hour=9, minute=35, second=12) + timedelta(days=1),
        rule_id=plan.ordinary_rules[0].rule_id,
        occurrence=1,
        quantity=100,
    )
    daily_report = run(
        store,
        dataset_hash,
        plan,
        research_input(plan).model_copy(
            update={
                "started_at": frozen.started_at,
                "adjustment_proofs": (proof,),
                "operations": (operation,),
            }
        ),
    )
    assert daily_report.operations[0].status == "APPLIED"
    assert daily_report.final_inventory.total_qty == 100
    event = next(event for event in daily_report.current_events if event.at == operation.at)
    assert event.signals[0].execution_date == following
    assert event.signals[0].execution_window == "NEXT_EXCHANGE_SESSION_ONLY"


def test_mixed_tree_needs_daily_minute_and_delayed_positive_fact_at_one_cutoff(tmp_path):
    from trade_plan_monitor.domain.plan_codec import load_plan_json

    store, dataset_hash, plan, frozen = fixture(tmp_path)
    daily = load_plan_json(
        (Path(__file__).parents[1] / "fixtures/unified-replay/daily-plan.json").read_text(
            encoding="utf-8"
        )
    )
    raw = plan.model_dump(mode="python")
    raw["monitoring"] = daily.monitoring.model_dump(mode="python")
    raw["ordinary_rules"][0]["condition"] = {
        "type": "ALL",
        "conditions": [
            daily.ordinary_rules[0].condition.model_dump(mode="python"),
            raw["ordinary_rules"][0]["condition"],
            {
                "type": "REVIEWED_FACT",
                "fact_kind": "TECHNICAL",
                "validity_scope": "TRADE_DATE",
                "evidence_requirement": "Synthetic separately reviewed technical structure",
            },
        ],
    }
    plan = type(plan).model_validate(raw)
    with store.open_frozen_dataset(dataset_hash) as reader:
        dates = [day.trade_date for day in reader if day.daily_bar is not None]
    proof = ResearchAdjustmentProof(
        proof_id="mixed-tree-completed-close",
        dataset_hash=dataset_hash,
        symbol=plan.symbol,
        provider="TUSHARE",
        adjustment_as_of=date(2026, 8, 24),
        available_at=frozen.started_at.replace(hour=15, minute=20),
        received_at=frozen.started_at.replace(hour=15, minute=20),
        quote_basis_factor=Decimal("1"),
        factors=tuple(ResearchFactor(trade_date=day, factor=Decimal("1")) for day in dates),
        evidence="Explicit synthetic verified factors for the completed official daily close",
    )
    negative = ResearchFact(
        kind="FACT",
        operation_id="negative-mixed",
        order=0,
        at=frozen.started_at.replace(hour=15, minute=21),
        fact_id="mixed-technical",
        fact_kind="TECHNICAL",
        trade_date=frozen.started_at.date(),
        satisfied=False,
        evidence="Synthetic technical structure explicitly absent at the first completed bucket",
    )
    positive = negative.model_copy(
        update={
            "operation_id": "positive-mixed",
            "satisfied": True,
            "at": negative.at.replace(minute=22),
        }
    )
    early = negative.model_copy(
        update={
            "operation_id": "early-mixed",
            "at": frozen.started_at.replace(hour=9, minute=35, second=12),
        }
    )
    report = run(
        store,
        dataset_hash,
        plan,
        research_input(plan).model_copy(
            update={
                "started_at": frozen.started_at,
                "adjustment_proofs": (proof,),
                "operations": (early, negative, positive),
            }
        ),
    )
    assert report.operations[0].status == "BLOCKED"
    assert report.operations[0].blockers == ("RESEARCH_FACT_REJECTED",)
    assert all(outcome.status == "APPLIED" for outcome in report.operations[1:])
    blocked = next(event for event in report.current_events if event.at == negative.at)
    assert blocked.signals == ()
    assert [child.outcome for child in blocked.conditions[0].evidence.children] == [
        "SATISFIED",
        "SATISFIED",
        "UNSATISFIED",
    ]
    confirmed = next(event for event in report.current_events if event.signals)
    assert confirmed.at == positive.at
    signal = confirmed.signals[0]
    assert signal.confirmed_at == positive.at.replace(minute=0, second=0)
    assert signal.execution_window == "CURRENT_SESSION"
    assert signal.planned_qty == 100
    assert signal.executable_qty == 0
    evidence = confirmed.conditions[0].evidence
    assert all(child.outcome == "SATISFIED" for child in evidence.children)
    assert evidence.children[0].session_dates == (date(2026, 8, 24),)
    assert evidence.children[1].bar_ids == ("2026-08-24T15:00:00+08:00",)
    assert len(evidence.children[2].fact_ids) == 1
    assert report.final_inventory.total_qty == 0
