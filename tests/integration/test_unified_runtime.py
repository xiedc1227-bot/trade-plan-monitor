"""Current public plan workflow, mixed periods and explicit whole-lot simulation."""

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.integration import test_daily_plan_chain as fixture
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.market_data.models import MinuteBar, TradingDay
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline

PATHS = {
    "daily-plan-review-supplements": "plan-review-supplements",
    "daily-position-confirmations": "simulation-position-confirmations",
    "daily-plan-facts": "plan-facts",
}

chain = fixture.chain


def current_plan(*, mixed=True, risk=False):
    raw = unified_payload()
    raw["risk_branches"] = raw["risk_branches"][:1] if risk else []
    rule = raw["ordinary_rules"][0]
    rule.update(validity={"mode": "PLAN_ACTIVE"}, zone=None,
                confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
                execution_window="CURRENT_SESSION")
    minute = {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000}
    rule["condition"] = {"type": "ALL", "conditions": [
        {"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
         "comparator": "LT", "reference": {"mode": "FIXED", "value": "4000",
             "unit": "FEN", "as_of": "2026-09-18",
             "source": "Synthetic reviewed threshold"}},
        minute]} if mixed else minute
    if not mixed and not risk:
        raw["monitoring"] = None
    return UnifiedTradePlan.model_validate(raw)


def minute_inputs(chain, *, series=None, missing=False):
    target = chain.now.replace(hour=9, minute=35, second=0, microsecond=0)
    prefix = tuple(MinuteBar(symbol=fixture.SYMBOL, bar_end=target-timedelta(minutes=4-i),
        open_fen=3970, high_fen=3980, low_fen=3960, close_fen=3970,
        volume_shares=100, amount_yuan=Decimal("3970"), received_at=chain.now)
        for i in range(5))
    bar = aggregate_five_minute_bar(prefix, bucket_end=target, is_open=True)
    from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
    return DailyRuntimeInputs(evaluated_at=chain.now, official_trade_date=None,
        series=series, session_dates=(fixture.FRIDAY, fixture.TUESDAY, fixture.WEDNESDAY),
        suspended_dates=(), quote=DailyExecutionQuote(symbol=fixture.SYMBOL,
            price_fen=3970, quote_at=target, available_at=chain.now, evaluated_at=chain.now,
            tradable=True, special_state_verified=True, liquidity_available=True),
        data_blockers=("CURRENT_DAY_MINUTE_PREFIX_MISSING",) if missing else (),
        minute_target=target, minute_prefix=() if missing else prefix,
        five_minute_bars=() if missing else (bar,), trading_calendar=(TradingDay(exchange="SSE",
            cal_date=fixture.TUESDAY, is_open=True, previous_trade_date=fixture.FRIDAY),))


def persist_minute_inputs(chain, inputs):
    with chain.plans._unit_of_work() as work:
        work.history.upsert_minutes(inputs.minute_prefix)
        for bar in inputs.five_minute_bars:
            work.history.upsert_five_minute(**bar.model_dump())
        work.commit()


@pytest.fixture
def current_chain(tmp_path, monkeypatch):
    chain = fixture.Chain(tmp_path)
    chain.plan = current_plan()
    old_post = chain.post
    chain.post = lambda path, data, **kwargs: old_post(PATHS.get(path, path), data, **kwargs)
    with chain.client:
        chain.activate()
        from trade_plan_monitor.state.models import TradingCalendar
        with chain.plans._unit_of_work() as work:
            for previous, day in ((fixture.FRIDAY-timedelta(days=1), fixture.FRIDAY),
                (fixture.FRIDAY, fixture.TUESDAY), (fixture.TUESDAY, fixture.WEDNESDAY)):
                work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=day,
                    is_open=True, previous_trade_date=previous))
            work.commit()
        chain.now = datetime(2026, 9, 22, 9, 35, 12, tzinfo=fixture.SH)
        chain.position()
        yield chain


def test_mixed_completed_daily_and_minute_signal_simulates_full_quantity_once(current_chain):
    chain = current_chain
    inputs = minute_inputs(chain, series=chain.series())
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    signal = result.snapshot["signals"][0]
    assert signal["executable_qty"] == 100
    assert signal["execution_date"] == str(fixture.TUESDAY)
    assert signal["confirmation_kind"] == "COMPLETED_BAR_CLOSE"
    with chain.plans._unit_of_work() as work:
        before = work.daily.get("simulation-position-" + fixture.SYMBOL)["revision"]
    command = {"planVersionId": chain.version["id"], "causeId": signal["signal_id"],
        "expectedCauseRevision": signal["revision"], "expectedInventoryRevision": before,
        "quantity": 100}
    key = uuid4().hex
    receipt = chain.post("simulated-trades", command, key=key)
    assert receipt["inventory"]["totalQty"] == 200
    assert receipt["inventory"]["sellableTactical"] == 0
    assert chain.post("simulated-trades", command, key=key) == receipt
    chain.post("simulated-trades", command, status=409)


def test_missing_minute_prefix_cannot_satisfy_mixed_conditions(current_chain):
    chain = current_chain
    result = chain.runtime.run_inputs(plan=chain.plan,
        inputs=minute_inputs(chain, series=chain.series(), missing=True))
    assert result.snapshot["signals"] == []


def test_minute_scoped_reviewed_fact_uses_exact_completed_bar_without_daily_series(tmp_path):
    chain = fixture.Chain(tmp_path)
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"] = {"type": "ALL", "conditions": [
        raw["ordinary_rules"][0]["condition"],
        {"type": "REVIEWED_FACT", "fact_kind": "TECHNICAL",
         "evidence_requirement": "Human verified the completed minute pattern",
         "validity_scope": "TRADE_DATE"},
    ]}
    chain.plan = UnifiedTradePlan.model_validate(raw)
    with chain.client:
        chain.activate()
        chain.now = datetime(2026, 9, 22, 9, 35, 12, tzinfo=fixture.SH)
        before = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
        assert before.snapshot["signals"] == []
        fact = chain.post("plan-facts", {
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": "minute-technical-review", "kind": "TECHNICAL",
            "tradeDate": str(fixture.TUESDAY),
            "evidence": "Synthetic human review of the exact completed five-minute bar",
            "expectedRevision": 0,
        })
        assert fact["revision"] == 1
        after = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
        assert after.snapshot["signals"][0]["evidence"][0]["outcome"] == "SATISFIED"


def test_reviewed_fact_only_minute_confirmation_acquires_production_bar(
    tmp_path, monkeypatch,
):
    import asyncio

    from tests.integration.current_pipeline_fixture import (
        PIPELINE_NOW,
        TARGET,
        current_pipeline_fixture,
        current_three_rule_plan,
    )

    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    raw = current_three_rule_plan().model_dump(mode="json")
    raw["ordinary_rules"] = raw["ordinary_rules"][:1]
    raw["ordinary_rules"][0]["condition"] = {
        "type": "REVIEWED_FACT", "fact_kind": "TECHNICAL",
        "evidence_requirement": "Human verifies the completed five-minute pattern",
        "validity_scope": "TRADE_DATE",
    }
    raw["alert_rules"] = []
    plan = UnifiedTradePlan.model_validate(raw)

    async def scenario():
        engine, work, _, sdk, _, controller, pipeline, _ = current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=60, plan=plan,
        )
        try:
            await pipeline.refresh_references(TARGET.date())
            await pipeline.run_deadline(MarketDeadline(
                kind=DeadlineKind.REALTIME_MINUTE, trade_date=TARGET.date(),
                due_at=PIPELINE_NOW, bar_end=TARGET,
            ))
            assert "rt_min" in sdk.calls
            with work() as transaction:
                head = transaction.daily.get("evaluation-head-" + plan.symbol)
                assert head["payload"]["minute_target"] == TARGET.isoformat()
                assert len(head["payload"]["minute_prefix"]) == 5
                assert head["payload"]["five_minute_bars"][-1]["bar_end"] == TARGET.isoformat()
                assert head["payload"]["signals"] == []
        finally:
            await controller.aclose()
            engine.dispose()

    asyncio.run(scenario())


def test_mixed_condition_rejects_stale_official_daily_series(current_chain):
    chain = current_chain
    stale = chain.series(fixture.FRIDAY - timedelta(days=1))
    result = chain.runtime.run_inputs(plan=chain.plan,
        inputs=minute_inputs(chain, series=stale))
    assert result.snapshot["signals"] == []


def test_production_preparer_reuses_exact_persisted_prefix_without_extra_quote(current_chain):
    import asyncio
    chain = current_chain
    chain.plan = current_plan(mixed=False)
    inputs = minute_inputs(chain)
    with chain.plans._unit_of_work() as work:
        work.history.upsert_minutes(inputs.minute_prefix)
        work.history.upsert_five_minute(**inputs.five_minute_bars[0].model_dump())
        work.commit()
    class NoProvider:
        def __getattr__(self, name):
            raise AssertionError("minute-only plan made unexpected provider call " + name)
    pipeline = SimpleNamespace(_work=chain.plans._unit_of_work,
        _clock=SimpleNamespace(now=lambda: chain.now), provider=NoProvider(),
        _daily_basis_cache={}, _runtime_generation=uuid4(), is_open_on=lambda day: True)
    prepared = asyncio.run(ProductionMonitorPipeline.prepare_daily_inputs(
        pipeline, chain.plan, chain.now, None, inputs.minute_prefix))
    assert prepared.minute_prefix == inputs.minute_prefix
    assert prepared.five_minute_bars == inputs.five_minute_bars
    assert prepared.series is None


def test_close_only_preparer_needs_no_derived_history(current_chain):
    import asyncio
    chain = current_chain
    chain.plan = current_plan(mixed=False)
    inputs = minute_inputs(chain)
    with chain.plans._unit_of_work() as work:
        work.history.upsert_minutes(inputs.minute_prefix)
        work.commit()
    class NoProvider:
        def __getattr__(self, name):
            raise AssertionError("minute-only plan made unexpected provider call " + name)
    pipeline = SimpleNamespace(_work=chain.plans._unit_of_work,
        _clock=SimpleNamespace(now=lambda: chain.now), provider=NoProvider(),
        _daily_basis_cache={}, _runtime_generation=uuid4(), is_open_on=lambda day: True)
    prepared = asyncio.run(ProductionMonitorPipeline.prepare_daily_inputs(
        pipeline, chain.plan, chain.now, None, inputs.minute_prefix))
    assert prepared.minute_prefix == inputs.minute_prefix
    assert prepared.five_minute_bars == inputs.five_minute_bars
    assert prepared.series is None


def test_unified_daily_permission_demand_uses_current_active_binding(current_chain):
    chain = current_chain
    class NoLegacyReader:
        def inspect_permission_demand_in_session(self, *args):
            raise AssertionError("current demand used legacy proof parser")
        def validate_permission_demand_in_session(self, *args):
            raise AssertionError("current demand used legacy proof parser")
    owner = SimpleNamespace(_daily_bar_demand_cursors={},
        _daily_bar_demand_receipts={}, _daily_bar_history_after=None)
    reader = NoLegacyReader()
    with chain.plans._unit_of_work() as work:
        evidence = ProductionMonitorPipeline._permission_evidence_from_repositories(
            chain.now, work.references, work.history, (chain.plan,), include_history=True)
        assert evidence.legacy_bar_symbols == (fixture.SYMBOL,)
        ProductionMonitorPipeline._refresh_daily_bar_demand(
            owner, work.daily.session, (chain.plan,), chain.now, reader)
        receipt = owner._daily_bar_demand_receipts[fixture.SYMBOL]
        assert ProductionMonitorPipeline._validate_daily_bar_demand(
            work.daily.session, receipt, chain.now, reader)
        assert not ProductionMonitorPipeline._validate_daily_bar_demand(
            work.daily.session, receipt, chain.now + timedelta(days=1), reader)


def test_reminder_only_condition_emits_one_alert_without_simulation(current_chain):
    chain = current_chain
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["ordinary_rules"] = []
    raw["alert_rules"] = [{"kind": "RISK_ALERT", "rule_id": "price-risk-alert",
        "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5,
            "price_fen": 4000}}]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    persist_minute_inputs(chain, minute_inputs(chain))
    with chain.plans._unit_of_work() as work:
        before = work.daily.get("simulation-position-" + fixture.SYMBOL)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
    assert result.snapshot["signals"] == []
    assert result.snapshot["alerts"][0]["outcome"] == "SATISFIED"
    assert len(result.event_ids) == 1, (result.duplicate, result.snapshot["alerts"])
    with chain.plans._unit_of_work() as work:
        assert work.daily.get("simulation-position-" + fixture.SYMBOL) == before
        event = work.alerts.get(__import__("uuid").UUID(result.event_ids[0]))
        assert event.signal_type == "REMINDER"
        assert event.quantity is None
        from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    from trade_plan_monitor.web.alert_service import PersistentAlertOperationService

    chain.app.state.alert_operation_service = PersistentAlertOperationService(
        unit_of_work_factory=chain.plans._unit_of_work, clock=lambda: chain.now)
    filtered = chain.client.get("/api/v1/alerts", params={
        "symbol": fixture.SYMBOL, "signalType": "RISK_ALERT"})
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    public = filtered.json()["items"][0]
    assert (public["signalType"], public["alertKind"], public["ruleId"],
        public["quantity"], public["nextStep"]) == (
            "REMINDER", "RISK_ALERT", "price-risk-alert", None, "REVIEW_ALERT")
    assert chain.client.get("/api/v1/alerts", params={
        "symbol": fixture.SYMBOL, "signalType": "BUY"}).json()["total"] == 0
    repeated = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
    assert repeated.event_ids == ()
    chain.now = chain.now.replace(minute=40)
    target = chain.now.replace(second=0)
    next_minutes = tuple(MinuteBar(symbol=fixture.SYMBOL,
        bar_end=target - timedelta(minutes=4-i), open_fen=3970,
        high_fen=3980, low_fen=3960, close_fen=3970,
        volume_shares=100, amount_yuan=Decimal("3970"), received_at=chain.now)
        for i in range(5))
    later = DailyRuntimeInputs(evaluated_at=chain.now, official_trade_date=None,
        series=None, session_dates=(fixture.FRIDAY, fixture.TUESDAY, fixture.WEDNESDAY),
        suspended_dates=(), quote=None, data_blockers=(), minute_target=target,
        minute_prefix=next_minutes, five_minute_bars=(aggregate_five_minute_bar(
            next_minutes, bucket_end=target, is_open=True),))
    next_bucket = chain.runtime.run_inputs(plan=chain.plan, inputs=later)
    assert len(next_bucket.event_ids) == 1
    assert next_bucket.snapshot["alerts"][0]["cause_id"] != result.snapshot["alerts"][0]["cause_id"]


def test_daily_reminder_ignores_missing_unrelated_minute_prefix(current_chain):
    from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed

    chain = current_chain
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["monitoring"] = unified_payload()["monitoring"]
    raw["alert_rules"] = [{"kind": "RISK_ALERT", "rule_id": "daily-risk-alert",
        "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
        "condition": {"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
            "comparator": "LT", "reference": {"mode": "FIXED", "value": "4000",
                "unit": "FEN", "as_of": "2026-09-18",
                "source": "Synthetic reviewed daily threshold"}}}]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.now = datetime(2026, 9, 18, 16, 1, tzinfo=fixture.SH)
    chain.activate(version=2, activation_revision=1)
    chain.now = datetime(2026, 9, 22, 9, 35, 12, tzinfo=fixture.SH)
    inputs = minute_inputs(chain, series=chain.series(), missing=True).model_copy(update={
        "official_trade_date": fixture.FRIDAY,
    })
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    assert result.snapshot["signals"] == []
    assert result.snapshot["alerts"][0]["outcome"] == "SATISFIED"
    assert len(result.event_ids) == 1
    with chain.plans._unit_of_work() as work:
        event = work.alerts.get(__import__("uuid").UUID(result.event_ids[0]))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    chain.now += timedelta(seconds=1)
    basis_failed = inputs.model_copy(update={
        "evaluated_at": chain.now,
        "data_blockers": ("CURRENT_QUOTE_BASIS_UNVERIFIED",),
    })
    chain.runtime.run_inputs(plan=chain.plan, inputs=basis_failed)
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)


@pytest.mark.parametrize("official_target", [None, fixture.FRIDAY])
def test_stored_daily_reminder_loses_authority_without_official_calendar(
    current_chain, official_target,
):
    import asyncio

    from sqlalchemy import delete

    from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
    from trade_plan_monitor.state.models import TradingCalendar

    chain = current_chain
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["monitoring"] = unified_payload()["monitoring"]
    raw["ordinary_rules"] = []
    raw["alert_rules"] = [{"kind": "RISK_ALERT", "rule_id": "daily-risk-alert",
        "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
        "condition": {"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
            "comparator": "LT", "reference": {"mode": "FIXED", "value": "4000",
                "unit": "FEN", "as_of": "2026-09-18",
                "source": "Synthetic reviewed daily threshold"}}}]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.now = datetime(2026, 9, 18, 16, 1, tzinfo=fixture.SH)
    chain.activate(version=2, activation_revision=1)
    chain.now = datetime(2026, 9, 22, 9, 35, 12, tzinfo=fixture.SH)
    initial = DailyRuntimeInputs(evaluated_at=chain.now, official_trade_date=fixture.FRIDAY,
        series=chain.series(), session_dates=(fixture.FRIDAY, fixture.TUESDAY),
        suspended_dates=(), quote=None, data_blockers=())
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=initial)
    assert result.snapshot["alerts"][0]["outcome"] == "SATISFIED"
    assert len(result.event_ids) == 1
    with chain.plans._unit_of_work() as work:
        event = work.alerts.get(__import__("uuid").UUID(result.event_ids[0]))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
        work.daily.session.execute(delete(TradingCalendar))
        work.commit()
    pipeline = SimpleNamespace(_work=chain.plans._unit_of_work,
        _clock=SimpleNamespace(now=lambda: chain.now), _runtime_generation=uuid4())
    prepared = asyncio.run(ProductionMonitorPipeline.prepare_daily_inputs(
        pipeline, chain.plan, chain.now, official_target, ()))
    assert prepared.series is None
    assert prepared.official_trade_date is None
    assert "OFFICIAL_DAILY_SESSION_UNVERIFIED" in prepared.data_blockers
    after = chain.runtime.run_inputs(plan=chain.plan, inputs=prepared)
    assert after.snapshot["alerts"][0]["outcome"] == "MISSING_INPUT"
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)


def test_reminder_delivery_rechecks_reviewed_fact_after_evaluation(current_chain):
    from sqlalchemy import select

    from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
    from trade_plan_monitor.state.models import AlertEvent

    chain = current_chain
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["ordinary_rules"] = []
    raw["alert_rules"] = [{"kind": "RISK_ALERT", "rule_id": "reviewed-reminder",
        "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        "condition": {"type": "ALL", "conditions": [
            {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 4000},
            {"type": "REVIEWED_FACT", "fact_kind": "TECHNICAL",
             "evidence_requirement": "Human verifies the completed minute pattern",
             "validity_scope": "TRADE_DATE"},
        ]}}]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    persist_minute_inputs(chain, minute_inputs(chain))
    before = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
    assert before.snapshot["alerts"][0]["outcome"] == "MISSING_INPUT", before.snapshot["alerts"]
    assert before.event_ids == ()
    fact = {"planVersionId": chain.version["id"],
        "contentHash": chain.version["contentHash"],
        "factId": "reviewed-minute-reminder", "kind": "TECHNICAL",
        "tradeDate": str(fixture.TUESDAY),
        "evidence": "Synthetic human review of the completed minute pattern"}
    chain.post("plan-facts", {**fact, "expectedRevision": 0})
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
    assert result.snapshot["alerts"][0]["outcome"] == "SATISFIED"
    with chain.plans._unit_of_work() as work:
        events = tuple(work.alerts.get(__import__("uuid").UUID(identity))
            for identity in work.daily.session.scalars(select(AlertEvent.id)))
        event = next(event for event in events
            if event.signal_type == "REMINDER" and event.plan_version_id == chain.version["id"])
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    chain.now += timedelta(seconds=1)
    chain.post("plan-facts", {**fact, "expectedRevision": 1, "satisfied": False})
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)


def test_reminder_delivery_rechecks_prior_volume_source_correction(current_chain):
    from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed

    chain = current_chain
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["ordinary_rules"] = []
    raw["alert_rules"] = [{"kind": "RISK_ALERT", "rule_id": "volume-reminder",
        "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        "condition": {"type": "MINUTE_VOLUME_TO_MEAN_GTE", "timeframe_minutes": 5,
            "window_bars": 1, "minimum_ratio": "1.5",
            "history_scope": "CONTIGUOUS_TRADING_BARS"}}]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    base = minute_inputs(chain)
    chain.now = chain.now.replace(minute=40)
    target = chain.now.replace(second=0)
    prior = tuple(MinuteBar(symbol=fixture.SYMBOL,
        bar_end=base.minute_target - timedelta(minutes=4-i),
        open_fen=3970, high_fen=3980, low_fen=3960, close_fen=3970,
        volume_shares=20, amount_yuan=Decimal("794"),
        received_at=base.evaluated_at)
        for i in range(5))
    prior_bar = aggregate_five_minute_bar(prior,
        bucket_end=base.minute_target, is_open=True)
    current = tuple(MinuteBar(symbol=fixture.SYMBOL,
        bar_end=target - timedelta(minutes=4-i),
        open_fen=3970, high_fen=3980, low_fen=3960, close_fen=3970,
        volume_shares=100, amount_yuan=Decimal("3970"), received_at=chain.now)
        for i in range(5))
    current_bar = aggregate_five_minute_bar(current, bucket_end=target, is_open=True)
    inputs = base.model_copy(update={"evaluated_at": chain.now,
        "minute_target": target, "minute_prefix": current,
        "five_minute_bars": (prior_bar, current_bar),
        "quote": base.quote.model_copy(update={"quote_at": target,
            "available_at": chain.now, "evaluated_at": chain.now})})
    with chain.plans._unit_of_work() as work:
        work.history.upsert_minutes((*prior, *current))
        work.history.upsert_five_minute(**prior_bar.model_dump())
        work.commit()
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    assert result.snapshot["alerts"][0]["outcome"] == "SATISFIED"
    with chain.plans._unit_of_work() as work:
        event = work.alerts.get(__import__("uuid").UUID(result.event_ids[0]))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    chain.now += timedelta(seconds=1)
    corrected = MinuteBar.model_validate({**prior[-1].model_dump(),
        "volume_shares": 500, "received_at": chain.now})
    with chain.plans._unit_of_work() as work:
        work.history.upsert_minutes((corrected,))
        work.commit()
    with chain.plans._unit_of_work() as work:
        assert not daily_delivery_allowed(work.daily.session, event, chain.now)


def test_alert_only_plan_ignores_preserved_legacy_report_without_simulation(current_chain):
    from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
    from trade_plan_monitor.state.daily_models import DailyRecord

    chain = current_chain
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["ordinary_rules"] = []
    raw["alert_rules"] = [{"kind": "RISK_ALERT", "rule_id": "legacy-safe-reminder",
        "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5,
                      "price_fen": 4000}}]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    persist_minute_inputs(chain, minute_inputs(chain))
    with chain.plans._unit_of_work() as work:
        legacy = DailyRecord(id="preserved-old-report", kind="REPORT",
            symbol=fixture.SYMBOL, lineage="old-plan", revision=1,
            payload_json='{"old_report": true}',
            created_at=chain.now.isoformat(), updated_at=chain.now.isoformat())
        work.daily.session.add(legacy)
        work.daily.session.add(DailyRecord(id="preserved-old-signal", kind="SIGNAL",
            symbol=fixture.SYMBOL, lineage="old-plan", revision=7,
            payload_json='{"legacy_signal": true}',
            created_at=chain.now.isoformat(), updated_at=chain.now.isoformat()))
        work.commit()
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
    assert result.snapshot["alerts"][0]["outcome"] == "SATISFIED"
    assert len(result.event_ids) == 1
    assert result.snapshot["signals"] == []
    view = chain.client.get("/api/v1/plan-runtime/" + fixture.SYMBOL)
    assert view.status_code == 200
    assert view.json()["status"] == "CURRENT"
    with chain.plans._unit_of_work() as work:
        assert work.daily.session.get(DailyRecord, "preserved-old-report").payload_json == (
            '{"old_report": true}'
        )
        old_signal = work.daily.session.get(DailyRecord, "preserved-old-signal")
        assert (old_signal.revision, old_signal.payload_json) == (7, '{"legacy_signal": true}')
        event = work.alerts.get(__import__("uuid").UUID(result.event_ids[0]))
        assert daily_delivery_allowed(work.daily.session, event, chain.now)
    assert chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain)).event_ids == ()
    chain.post("simulated-trades", {"planVersionId": chain.version["id"],
        "causeId": result.snapshot["alerts"][0]["cause_id"],
        "expectedCauseRevision": 1, "expectedInventoryRevision": 1,
        "quantity": 100}, status=409)


def _seed_prior_latched_risk(chain):
    _, initial = fixture.ready_chain(chain)
    for kind in ("SEVERE_STRUCTURE", "SEVERE_DETERIORATION"):
        chain.post("plan-facts", {
            "planVersionId": chain.version["id"],
            "contentHash": chain.version["contentHash"],
            "factId": "prior-latched-" + kind, "kind": kind,
            "tradeDate": str(fixture.FRIDAY),
            "evidence": "Synthetic complete official technical evidence independently reviewed",
            "expectedRevision": 0,
        })
    confirmed = chain.evaluate(series=chain.series(), price=3970)
    assert any(r["status"] == "CONFIRMED" for r in confirmed.snapshot["risks"])


def _real_pipeline_for_expired_risk_test(chain, tmp_path, monkeypatch):
    import test_live_pipeline_acceptance as live_fixture

    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.live_profiles import create_stock_certification
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel
    from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller

    clock = live_fixture.ControlledClock(chain.now)
    sdk = live_fixture.OfflineSDK(clock, (fixture.SYMBOL,))
    monkeypatch.setattr("trade_plan_monitor.runtime.production.create_tushare_client",
        lambda _config: sdk)
    config_path = live_fixture._write_configuration_and_evidence(
        tmp_path, observed_at=clock.now(), include_index=False)
    pace = live_fixture.VirtualPace()
    controller = create_live_tushare_request_controller(
        clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep)
    pipeline = ProductionMonitorPipeline(
        configuration=load_application_config(config_path).tushare,
        certification_directory=tmp_path / "data/live-certification",
        stock_certification=create_stock_certification(
            observed_at=clock.now(), endpoint_url=live_fixture.ENDPOINT,
            capabilities=live_fixture._ready_stock_capabilities(),
            source_time_label=SourceTimeLabel.START),
        clock=clock, request_controller=controller,
        unit_of_work_factory=chain.plans._unit_of_work,
        runtime_generation=uuid4(), publisher=lambda _event: None,
        recovery_session_factory=chain.plans._session_factory,
    )
    return pipeline, controller, sdk


def test_expired_alert_only_plan_cannot_inherit_latched_prior_risk(
    chain, tmp_path, monkeypatch,
):
    import asyncio

    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    _seed_prior_latched_risk(chain)
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["ordinary_rules"] = []
    raw["risk_branches"] = []
    raw["activation"] = {"mode": "TRADING_DAY", "trading_day": str(fixture.TUESDAY)}
    raw["alert_rules"] = [{"kind": "RISK_ALERT", "rule_id": "one-day-alert",
        "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
        "condition": {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5,
                      "price_fen": 4000}}]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    chain.now = datetime(2026, 9, 23, 9, 35, 12, tzinfo=fixture.SH)
    with pytest.raises(ValueError, match="admission is closed"):
        chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
    with chain.plans._unit_of_work() as work:
        assert not work.daily.list(symbol=fixture.SYMBOL, kind="EVALUATION")[-1]["payload"].get(
            "alerts"
        )
    pipeline, controller, sdk = _real_pipeline_for_expired_risk_test(
        chain, tmp_path, monkeypatch)
    try:
        assert pipeline.active_symbols() == ()
        deadline = MarketDeadline(kind=DeadlineKind.REALTIME_MINUTE,
            trade_date=chain.now.date(), due_at=chain.now,
            bar_end=chain.now.replace(second=0))
        asyncio.run(pipeline.run_deadline(deadline))
        assert not any(name in {"rt_min", "rt_min_daily"} for name, _ in sdk.calls)
    finally:
        asyncio.run(controller.aclose())


def test_expired_current_risk_plan_keeps_latched_stock_acquisition(
    chain, tmp_path, monkeypatch,
):
    import asyncio

    from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

    _seed_prior_latched_risk(chain)
    raw = current_plan(mixed=False, risk=True).model_dump(mode="json")
    raw["activation"] = {"mode": "TRADING_DAY", "trading_day": str(fixture.TUESDAY)}
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    chain.now = datetime(2026, 9, 23, 9, 35, 12, tzinfo=fixture.SH)
    pipeline, controller, sdk = _real_pipeline_for_expired_risk_test(
        chain, tmp_path, monkeypatch)
    try:
        assert pipeline.active_symbols() == (fixture.SYMBOL,)
        deadline = MarketDeadline(kind=DeadlineKind.REALTIME_MINUTE,
            trade_date=chain.now.date(), due_at=chain.now,
            bar_end=chain.now.replace(second=0))
        asyncio.run(pipeline.run_deadline(deadline))
        assert any(name == "rt_min" for name, _ in sdk.calls)
    finally:
        asyncio.run(controller.aclose())


def test_real_production_pipeline_prepares_minute_only_rule_from_fake_sdk(
    current_chain, tmp_path, monkeypatch,
):
    import asyncio

    import test_live_pipeline_acceptance as live_fixture

    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.live_profiles import create_stock_certification
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel
    from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller

    chain = current_chain
    chain.plan = current_plan(mixed=False)
    inputs = minute_inputs(chain)
    with chain.plans._unit_of_work() as work:
        work.history.upsert_minutes(inputs.minute_prefix)
        work.commit()
    clock = live_fixture.ControlledClock(chain.now)
    sdk = live_fixture.OfflineSDK(clock, (fixture.SYMBOL,))
    monkeypatch.setattr("trade_plan_monitor.runtime.production.create_tushare_client",
        lambda _config: sdk)
    config_path = live_fixture._write_configuration_and_evidence(
        tmp_path, observed_at=clock.now(), include_index=False)
    pace = live_fixture.VirtualPace()
    controller = create_live_tushare_request_controller(
        clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep)
    pipeline = ProductionMonitorPipeline(
        configuration=load_application_config(config_path).tushare,
        certification_directory=tmp_path / "data/live-certification",
        stock_certification=create_stock_certification(
            observed_at=clock.now(), endpoint_url=live_fixture.ENDPOINT,
            capabilities=live_fixture._ready_stock_capabilities(),
            source_time_label=SourceTimeLabel.START),
        clock=clock, request_controller=controller,
        unit_of_work_factory=chain.plans._unit_of_work,
        runtime_generation=uuid4(), publisher=lambda _event: None,
        recovery_session_factory=chain.plans._session_factory,
    )
    prepared = asyncio.run(pipeline.prepare_daily_inputs(
        chain.plan, chain.now, None, inputs.minute_prefix))
    assert prepared.five_minute_bars == inputs.five_minute_bars
    assert prepared.series is None
    assert sdk.calls == []


@pytest.mark.parametrize("linked", [False, True])
def test_real_production_adapter_keeps_official_daily_and_minute_cutoffs_separate(
    current_chain, tmp_path, monkeypatch, linked,
):
    import asyncio

    import test_live_pipeline_acceptance as live_fixture

    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.live_profiles import create_stock_certification
    from trade_plan_monitor.market_data.models import DailyBar
    from trade_plan_monitor.market_data.sessions import SourceTimeLabel
    from trade_plan_monitor.runtime.request_control import create_live_tushare_request_controller

    chain = current_chain
    inputs = minute_inputs(chain)
    if linked:
        from tests.integration.test_market_linkage_runtime import index_snapshot
        from tests.unit.test_market_linkage_contract import linked_payload

        from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan

        chain.plan = MarketLinkedTradePlan.model_validate(linked_payload())
        linked_snapshot, _ = index_snapshot(chain.plan)
    with chain.plans._unit_of_work() as work:
        work.history.upsert_minutes(inputs.minute_prefix)
        work.commit()
    clock = live_fixture.ControlledClock(chain.now)
    monkeypatch.setattr("trade_plan_monitor.runtime.production.create_tushare_client",
        lambda _config: live_fixture.OfflineSDK(clock, (fixture.SYMBOL,)))
    config_path = live_fixture._write_configuration_and_evidence(
        tmp_path, observed_at=clock.now(), include_index=False)
    pace = live_fixture.VirtualPace()
    pipeline = ProductionMonitorPipeline(
        configuration=load_application_config(config_path).tushare,
        certification_directory=tmp_path / "data/live-certification",
        stock_certification=create_stock_certification(
            observed_at=clock.now(), endpoint_url=live_fixture.ENDPOINT,
            capabilities=live_fixture._ready_stock_capabilities(),
            source_time_label=SourceTimeLabel.START),
        clock=clock, request_controller=create_live_tushare_request_controller(
            clock=clock, monotonic=pace.monotonic, pace_sleep=pace.sleep),
        unit_of_work_factory=chain.plans._unit_of_work,
        runtime_generation=uuid4(), publisher=lambda _event: None,
        recovery_session_factory=chain.plans._session_factory,
    )
    calls = []
    class FakeProvider:
        def historical_daily_bars(self, symbol, start, end):
            calls.append(("historical_daily_bars", start, end))
            return (DailyBar(symbol=symbol, trade_date=fixture.FRIDAY,
                open_fen=3970, high_fen=3980, low_fen=3960, close_fen=3970,
                volume_shares=1000, amount_yuan=Decimal("39700"),
                is_official=True,
                received_at=datetime(2026, 9, 18, 16, tzinfo=fixture.SH)),)
        def daily_adjustment_factors(self, symbol, start, end):
            calls.append(("daily_adjustment_factors", start, end))
            return ({fixture.FRIDAY: Decimal(1), fixture.TUESDAY: Decimal(1)},
                chain.now)
    class FakeController:
        async def execute(self, _operation, call, **_kwargs):
            return call()
    pipeline.provider = FakeProvider()
    pipeline._controller = FakeController()
    if linked:
        # Capture belongs to the real shared service, not a second index fetcher.
        pipeline.index_service._latest_by_index[linked_snapshot.index_code] = linked_snapshot
    prepared = asyncio.run(pipeline.prepare_daily_inputs(
        chain.plan, chain.now, fixture.FRIDAY, inputs.minute_prefix))
    assert prepared.series.bars[-1].trade_date == fixture.FRIDAY
    if linked:
        assert prepared.minute_target is None
        assert prepared.five_minute_bars == ()
    else:
        assert prepared.minute_target.date() == fixture.TUESDAY
        assert prepared.five_minute_bars == inputs.five_minute_bars
    assert prepared.data_blockers == ()
    assert prepared.linked_index == (linked_snapshot if linked else None)
    assert [call[0] for call in calls] == [
        "historical_daily_bars", "daily_adjustment_factors"]


def test_quantified_severe_risk_uses_condition_evidence_and_next_session(current_chain):
    chain = current_chain
    raw = current_plan().model_dump(mode="json")
    severe = unified_payload()["risk_branches"][1]
    severe["condition"] = raw["ordinary_rules"][0]["condition"]["conditions"][0]
    raw["risk_branches"] = [severe]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    chain.now = chain.now.replace(hour=16)
    result = chain.evaluate(series=chain.series(fixture.TUESDAY), official=fixture.TUESDAY)
    risk = result.snapshot["risks"][0]
    assert risk["status"] == "CONFIRMED"
    assert risk["earliest_execution_date"] == str(fixture.WEDNESDAY)
    assert risk["technical_evidence"][0]["outcome"] == "SATISFIED"
    assert risk["evidence_ids"] == ["synthetic-" + str(fixture.TUESDAY)]
    assert result.snapshot["risk_action"]["status"] == "WAITING"


def test_unknown_declared_severe_risk_blocks_ordinary_simulation(current_chain):
    chain = current_chain
    raw = current_plan().model_dump(mode="json")
    raw["risk_branches"] = [unified_payload()["risk_branches"][1]]
    chain.plan = UnifiedTradePlan.model_validate(raw)
    chain.activate(version=2, activation_revision=1)
    result = chain.runtime.run_inputs(plan=chain.plan,
        inputs=minute_inputs(chain, series=chain.series()))
    signal = result.snapshot["signals"][0]
    assert result.snapshot["risk_input_known"] is False
    assert signal["executable_qty"] == 0
    assert "RISK_INPUT_UNKNOWN" in signal["blockers"]


def test_capture_revision_fences_activation_change(current_chain):
    chain = current_chain
    inputs = minute_inputs(chain, series=chain.series())
    with pytest.raises(ValueError, match="activation changed"):
        chain.runtime.run_inputs(plan=chain.plan, inputs=inputs,
            expected_activation_revision=99)
    with chain.plans._unit_of_work() as work:
        assert work.daily.current_signals(symbol=fixture.SYMBOL) == ()
