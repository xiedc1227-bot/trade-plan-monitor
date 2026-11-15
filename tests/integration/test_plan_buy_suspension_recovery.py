"""Production provider + SDK double + isolated SQLite; no public Schema10 activation claim."""

import asyncio
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from functools import partial
from threading import Event

import pandas as pd
import pytest
import requests
from test_daily_plan_chain import FRIDAY, SH, SYMBOL, TUESDAY
from test_daily_production_reevaluation import DailyRecoverySDK, ProductionDailyChain
from tests.integration.test_market_linkage_review import source_mapping

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json, daily_draft_sha256
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.unified_plan_models import BuySuspensionTradePlan
from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import PlanReviewProvenance, PlanSource, PlanVersion


@pytest.mark.parametrize("end", ["cancel", "timeout"])
def test_window_keeps_serial_ownership_until_physical_sdk_finishes(end):
    from test_live_pipeline_acceptance import ControlledClock

    from trade_plan_monitor.runtime.recovery import RecoveryService
    from trade_plan_monitor.runtime.request_control import TushareRequestController

    async def scenario():
        entered, release = Event(), Event()
        calls = []

        class Provider:
            def current_day_minutes(self, symbol):
                return []

            def buy_suspension_minutes(self, symbol, through):
                calls.append(symbol)
                entered.set()
                release.wait(2)
                return object()

        clock = ControlledClock(datetime.combine(FRIDAY, time(10), SH))
        control = TushareRequestController(clock=clock, min_interval=timedelta(0),
            jitter=timedelta(0), timeout_seconds=0.03 if end == "timeout" else 1,
            in_cycle_retries=0)
        provider = Provider()
        service = RecoveryService(provider=provider, request_controller=control,
            active_symbols=lambda: (), persist_minutes=lambda rows: None,
            is_open_on=lambda day: True, realtime_pending=lambda: False)
        first = asyncio.create_task(service.buy_suspension_window(provider, symbol=SYMBOL,
            through=clock.now(), current=lambda: True, source_key="first"))
        second = None
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            if end == "cancel":
                first.cancel()
            await asyncio.sleep(0.08)
            second = asyncio.create_task(service.buy_suspension_window(provider, symbol="600000.SH",
                through=clock.now(), current=lambda: True, source_key="second"))
            await asyncio.sleep(0.05)
            assert calls == [SYMBOL]
        finally:
            release.set()
            await asyncio.gather(first, *(() if second is None else (second,)),
                                 return_exceptions=True)
            await control.aclose()

    asyncio.run(scenario())


class SuspensionSDK(DailyRecoverySDK):
    late = False
    breach = None
    factor = "2.75"
    after_window = None

    def _stock_minutes(self, name, kwargs):
        frame = super()._stock_minutes(name, kwargs)
        frame["open"], frame["high"], frame["low"] = "24.30", "24.30", "24.19"
        frame["close"], frame["vol"], frame["amount"] = "24.30", 100, "2430"
        return frame

    def stk_mins(self, **kwargs):
        self.calls.append(("stk_mins", dict(kwargs)))
        day = datetime.fromisoformat(kwargs["start_date"]).date()
        cutoff = datetime.fromisoformat(kwargs["end_date"]).replace(tzinfo=SH)
        ends = (datetime.combine(day, time(9, 30), SH),
                *expected_minute_ends(day, is_open=True))
        rows = [{"ts_code": kwargs["ts_code"], "trade_time": end.strftime("%Y-%m-%d %H:%M:%S"),
            "open": "24.30", "high": "24.30", "low": "24.19",
            "close": "24.19" if end == self.breach else "24.30",
            "vol": 100, "amount": "2430"} for end in ends if end <= cutoff]
        frame = pd.DataFrame(rows[:-1] if self.late else rows)
        hook, self.after_window = self.after_window, None
        if hook is not None:
            hook()
        return frame

    def adj_factor(self, **kwargs):
        frame = super().adj_factor(**kwargs)
        frame["adj_factor"] = self.factor
        return frame


def seed_schema10(chain, effective):
    """T08 remains closed: seed exact persisted identities after ordinary activation."""
    chain.activate()
    payload = chain.plan.model_dump(mode="python")
    payload.update(schema_version=10, execution_version="condition-plan-v6",
        buy_suspension={"condition": {"type": "MINUTE_CLOSE_BELOW",
            "timeframe_minutes": 5, "price_fen": 2420}, "effective_from": effective})
    chain.plan = BuySuspensionTradePlan.model_validate(payload)
    draft = BuySuspensionPlanDraft.from_executable(chain.plan)
    source, mapping = source_mapping(draft)
    snapshot = build_daily_review(draft, mapping, source)
    assert not snapshot.issues
    with chain.plans._unit_of_work() as work:
        active = work.plans.get_active(SYMBOL)
        row = work.daily.session.get(PlanVersion, active.plan_version_id)
        row.payload_json = daily_draft_json(draft)
        row.plan_hash = daily_draft_sha256(draft)
        source_row = work.daily.session.get(PlanSource, row.source_id)
        source_row.source_text, source_row.source_hash = source, snapshot.source_hash
        provenance = work.daily.session.get(PlanReviewProvenance, row.id)
        provenance.draft_hash = row.plan_hash
        provenance.source_hash = snapshot.source_hash
        provenance.content_hash = snapshot.content_hash
        provenance.review_evidence_hash = snapshot.evidence_hash
        provenance.mapping_json = canonical(mapping.model_dump(mode="json"))
        provenance.required_issues_json = "[]"
        review = work.daily.session.get(DailyRecord, "review-" + active.plan_version_id)
        data = json.loads(review.payload_json)
        data.update(content_hash=snapshot.content_hash, source_hash=snapshot.source_hash,
                    evidence_hash=snapshot.evidence_hash)
        review.payload_json = json.dumps(data)
        work.commit()
    return active.plan_version_id


@pytest.fixture
def chain(tmp_path, monkeypatch, request):
    import test_live_pipeline_acceptance as live

    import trade_plan_monitor.runtime.production as production
    from trade_plan_monitor.market_data.tushare_client import create_tushare_client

    endpoint = getattr(request, "param", "https://api.waditu.com/dataapi")
    monkeypatch.setattr(live, "ENDPOINT", endpoint)
    value = ProductionDailyChain(tmp_path, monkeypatch, sdk_type=SuspensionSDK,
        initial_now=datetime(2026, 9, 18, 9, 36, tzinfo=SH))
    # Exercise the real SDK factory/query path. Only the HTTP response is replaced.
    monkeypatch.setattr(production, "create_tushare_client", create_tushare_client)

    def post(url, **kwargs):
        assert url.startswith(endpoint + "/")
        body = kwargs["json"]
        frame = getattr(value.sdk, body["api_name"])(**body["params"])
        data = json.loads(frame.to_json(orient="split"))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"code": 0, "data": {
            "fields": data["columns"], "items": data["data"]}}).encode()
        return response

    monkeypatch.setattr(requests, "post", post)
    value.client.__enter__()
    try:
        yield value
    finally:
        value.client.__exit__(None, None, None)


def pipeline(chain):
    return chain.composition._runtime._run_deadline.__self__._pipeline


def advance(chain):
    owner = pipeline(chain)
    return chain.client.portal.call(owner.advance_buy_suspension, chain.plan)


def test_production_current_target_has_actual_factor_and_finite_clear(chain):
    version = seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    row = advance(chain)
    assert row["state"].outcome == "CLEAR_THROUGH_TARGET"
    assert row["state"].target == datetime.combine(FRIDAY, time(9, 35), SH)
    assert row["state"].coverage.anchor_factor == Decimal("2.75")
    assert row["state"].owner_plan_version_id == version
    assert any(name == "stk_mins" for name, _ in chain.sdk.calls)
    result = chain.client.portal.call(partial(pipeline(chain).daily_evaluations.run_target,
        plan=chain.plan, evaluated_at=chain.now))
    assert result is not None and result.plan_hash == plan_sha256(chain.plan)


def test_production_cross_day_budget_and_late_data_resume_without_truncation(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    chain.now = datetime.combine(TUESDAY, time(9, 36), SH)
    chain.sdk.late = True
    assert advance(chain)["state"].outcome == "UNVERIFIED"
    chain.sdk.late = False
    outcomes = [advance(chain) for _ in range(5)]
    state = outcomes[-1]["state"]
    assert state.outcome == "CLEAR_THROUGH_TARGET"
    assert state.definition.effective_from == datetime.combine(FRIDAY, time(9, 30), SH)
    requests = [args for name, args in chain.sdk.calls if name == "stk_mins"]
    assert all(datetime.fromisoformat(args["start_date"]).date()
               == datetime.fromisoformat(args["end_date"]).date() for args in requests)
    assert len(requests) <= 4


@pytest.mark.parametrize("change", ["route", "sdk_version"])
def test_unproved_route_or_sdk_never_mints_guard_proof(chain, monkeypatch, change):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    assert advance(chain)["state"].outcome == "CLEAR_THROUGH_TARGET"
    if change == "route":
        client = pipeline(chain).provider._client._client
        client.query._endpoint = "https://unverified.invalid/dataapi"
    else:
        import tushare
        monkeypatch.setattr(tushare, "__version__", "0.0")
    chain.sdk.calls.clear()
    row = advance(chain)
    assert row["state"].outcome == "UNVERIFIED"
    assert row["state"].blocker == "SOURCE_UNVERIFIED"
    assert row["state"].coverage is None
    assert not any(name in {"stk_mins", "adj_factor"} for name, _ in chain.sdk.calls)


def guard_row(chain):
    with chain.plans._unit_of_work() as work:
        active = work.plans.get_active(SYMBOL)
        return work.daily.get_buy_suspension(symbol=SYMBOL,
            owner_plan_version_id=active.plan_version_id)


def test_actual_factor_response_invalidates_clear_before_recheck(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    initial = advance(chain)
    chain.sdk.factor = "2.76"
    pipeline(chain).provider.daily_adjustment_factors(SYMBOL, FRIDAY, FRIDAY)
    invalid = guard_row(chain)
    assert invalid["state"].coverage is None
    assert invalid["revision"] > initial["revision"]
    assert advance(chain)["state"].outcome == "CLEAR_THROUGH_TARGET"


def test_real_minute_correction_rechecks_latches_and_has_no_heartbeat_writes(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    initial = advance(chain)
    target = initial["state"].target
    from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
    with chain.plans._unit_of_work() as work:
        source = work.history.list_minutes(SYMBOL,
            start=target - timedelta(minutes=4), end=target)
        aggregate = aggregate_five_minute_bar(source, bucket_end=target, is_open=True)
        work.history.upsert_five_minute(**aggregate.model_dump())
        work.commit()
    chain.now += timedelta(seconds=1)
    with chain.plans._unit_of_work() as work:
        bar = work.history.list_minutes(SYMBOL, start=target, end=target)[0]
        work.history.upsert_minutes((bar.model_copy(update={
            "close_fen": 2419, "received_at": chain.now}),))
        work.commit()
    assert guard_row(chain)["state"].coverage is None
    chain.sdk.breach = target
    latched = advance(chain)
    assert latched["state"].outcome == "LATCHED"
    with chain.plans._unit_of_work() as work:
        assert work.history.list_five_minute(SYMBOL, start=target, end=target)[0].close_fen == 2430
    chain.now += timedelta(minutes=5)
    unchanged = advance(chain)
    assert unchanged["state_hash"] == latched["state_hash"]
    assert unchanged["revision"] == latched["revision"]


def test_real_restart_discards_old_clear_and_resumes_finite_history(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    initial = advance(chain)
    chain.client.__exit__(None, None, None)
    chain.now = datetime.combine(TUESDAY, time(9, 36), SH)
    chain.compose()
    chain.client.__enter__()
    first = advance(chain)
    assert first["state"].outcome == "UNVERIFIED"
    assert first["state"].coverage.generation != initial["state"].coverage.generation
    for _ in range(4):
        final = advance(chain)
    assert final["state"].outcome == "CLEAR_THROUGH_TARGET"


def test_target_advances_during_sdk_read_without_using_future_bar(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    chain.sdk.breach = datetime.combine(FRIDAY, time(9, 40), SH)
    chain.sdk.after_window = lambda: setattr(chain, "now", chain.now + timedelta(minutes=5))
    partial_row = advance(chain)
    assert partial_row["state"].trigger is None
    assert partial_row["state"].outcome == "UNVERIFIED"
    assert partial_row["state"].target == chain.sdk.breach
    assert advance(chain)["state"].trigger.bar_end == chain.sdk.breach


def test_whole_guard_cancellation_joins_factor_before_next_guard(chain, monkeypatch):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    entered, release = Event(), Event()
    calls = []
    original = chain.sdk.adj_factor

    def blocked(**kwargs):
        calls.append(kwargs)
        entered.set()
        release.wait(2)
        return original(**kwargs)

    monkeypatch.setattr(chain.sdk, "adj_factor", blocked)

    async def scenario():
        owner = pipeline(chain)
        first = asyncio.create_task(owner.advance_buy_suspension(chain.plan))
        second = None
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            first.cancel()
            second = asyncio.create_task(owner.advance_buy_suspension(chain.plan))
            await asyncio.sleep(0.05)
            assert len(calls) == 1
        finally:
            release.set()
            await asyncio.gather(first, *(() if second is None else (second,)),
                                 return_exceptions=True)

    chain.client.portal.call(scenario)


def test_actual_correction_during_acquisition_cannot_reuse_old_prefix(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    initial = advance(chain)
    old_target = initial["state"].target
    chain.now += timedelta(minutes=5)

    def correct():
        chain.now += timedelta(seconds=1)
        with chain.plans._unit_of_work() as work:
            source = work.history.list_minutes(SYMBOL, start=old_target, end=old_target)[0]
            work.history.upsert_minutes((source.model_copy(update={
                "close_fen": 2419, "received_at": chain.now}),))
            work.commit()

    chain.sdk.after_window = correct
    assert advance(chain)["state"].outcome == "UNVERIFIED"
    assert guard_row(chain)["state"].coverage is None
    chain.sdk.breach = old_target
    assert advance(chain)["state"].trigger.bar_end == old_target


def test_latest_target_predicate_fences_stale_revision_and_time(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    row = advance(chain)
    owner = pipeline(chain)
    with chain.plans._unit_of_work() as work:
        work.daily.lock_symbol(SYMBOL)
        assert owner.buy_suspension_current(work, chain.plan, expected_revision=row["revision"])
        assert not owner.buy_suspension_current(work, chain.plan,
                                               expected_revision=row["revision"] - 1)
        chain.now += timedelta(minutes=5)
        assert not owner.buy_suspension_current(work, chain.plan,
                                               expected_revision=row["revision"])
    assert advance(chain)["state"].outcome == "CLEAR_THROUGH_TARGET"


@pytest.mark.parametrize("day", [FRIDAY, FRIDAY + timedelta(days=2)])
def test_missing_calendar_then_late_closed_session_calendar_can_finish(chain, monkeypatch, day):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    chain.now = datetime.combine(day, time(16), SH)
    original = chain.sdk._calendar

    def unavailable(kwargs):
        raise ValueError("offline calendar not published yet")

    monkeypatch.setattr(chain.sdk, "_calendar", unavailable)
    unknown = advance(chain)
    assert unknown is None or unknown["state"].outcome == "UNVERIFIED"
    monkeypatch.setattr(chain.sdk, "_calendar", original)
    chain.now += timedelta(minutes=6)
    result = advance(chain)
    assert result["state"].target == datetime.combine(FRIDAY, time(15), SH)
    assert result["state"].outcome == "CLEAR_THROUGH_TARGET"


def test_clear_receipt_refresh_does_not_keep_invalidating_identical_content(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    initial = advance(chain)
    chain.now += timedelta(seconds=1)
    repeated = advance(chain)
    assert repeated["revision"] == initial["revision"]
    assert repeated["state_hash"] == initial["state_hash"]


@pytest.mark.parametrize("chain", ["https://compatible.invalid/dataapi"], indirect=True)
def test_compatible_endpoint_is_unknown_guard_but_does_not_abort_production_cycle(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    chain.sdk.calls.clear()
    assert advance(chain) is None
    assert not any(name == "stk_mins" for name, _ in chain.sdk.calls)
    owner = pipeline(chain)
    with chain.plans._unit_of_work() as work:
        assert not owner.buy_suspension_current(work, chain.plan)
    result = chain.client.portal.call(partial(owner.daily_evaluations.run_target,
        plan=chain.plan, evaluated_at=chain.now))
    assert result is not None and result.plan_hash == plan_sha256(chain.plan)


def test_record_revision_changing_after_input_capture_rejects_old_cycle(chain):
    from trade_plan_monitor.runtime.daily_service import DailyActivationChangedError

    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    owner = pipeline(chain)
    inputs = chain.client.portal.call(owner.prepare_daily_inputs, chain.plan, chain.now, None, ())
    chain.now += timedelta(seconds=1)
    with chain.plans._unit_of_work() as work:
        target = guard_row(chain)["state"].target
        source = work.history.list_minutes(SYMBOL, start=target, end=target)[0]
        work.history.upsert_minutes((source.model_copy(update={
            "close_fen": 2419, "received_at": chain.now}),))
        work.commit()
    with pytest.raises(DailyActivationChangedError):
        owner.daily_evaluations.run_inputs(plan=chain.plan, inputs=inputs)


def test_current_predicate_rejects_clock_reversal_within_same_completed_target(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    chain.now += timedelta(minutes=1)
    row = advance(chain)
    chain.now -= timedelta(seconds=30)
    with chain.plans._unit_of_work() as work:
        work.daily.lock_symbol(SYMBOL)
        assert not pipeline(chain).buy_suspension_current(work, chain.plan,
                                                         expected_revision=row["revision"])


@pytest.mark.parametrize("latched", [False, True])
def test_actual_closed_calendar_revision_rechecks_earlier_target_without_clearing_latch(
        chain, monkeypatch, latched):
    from trade_plan_monitor.market_data.models import TradingDay

    start = datetime.combine(FRIDAY, time(9, 30), SH)
    seed_schema10(chain, start)
    chain.now = datetime.combine(TUESDAY, time(16), SH)
    if latched:
        chain.sdk.breach = datetime.combine(TUESDAY, time(14, 55), SH)
    for _ in range(5):
        initial = advance(chain)
    assert initial["state"].target == datetime.combine(TUESDAY, time(15), SH)
    assert initial["state"].outcome == ("LATCHED" if latched else "CLEAR_THROUGH_TARGET")

    chain.now += timedelta(seconds=1)
    corrected = TradingDay(exchange="SSE", cal_date=TUESDAY, is_open=False,
                           previous_trade_date=FRIDAY)
    with chain.plans._unit_of_work() as work:
        work.references.upsert_trading_days((corrected,))
        work.commit()
    invalidated = guard_row(chain)
    if not latched:
        assert invalidated["revision"] == initial["revision"] + 1
        assert invalidated["state"].coverage is None
        with chain.plans._unit_of_work() as work:
            from trade_plan_monitor.state.repositories import RevisionConflictError

            target = datetime.combine(FRIDAY, time(15), SH)
            assert work.daily.retarget_buy_suspension_calendar(invalidated["state"],
                target=target, evaluated_at=initial["state"].evaluated_at - timedelta(seconds=1)
            ) is None
            assert work.daily.retarget_buy_suspension_calendar(invalidated["state"],
                target=target - timedelta(minutes=5), evaluated_at=chain.now) is None
            replacement = work.daily.retarget_buy_suspension_calendar(invalidated["state"],
                target=target, evaluated_at=chain.now)
            assert replacement is not None and replacement.coverage is None
            with pytest.raises(RevisionConflictError):
                work.daily.save(invalidated["id"], kind="BUY_SUSPENSION", symbol=SYMBOL,
                    lineage=replacement.owner_plan_version_id,
                    payload=replacement.model_dump(mode="json"),
                    expected_revision=initial["revision"])

    original = chain.sdk._calendar

    def revised(kwargs):
        frame = original(kwargs)
        frame.loc[frame.cal_date == TUESDAY.strftime("%Y%m%d"), "is_open"] = 0
        frame.loc[frame.cal_date == TUESDAY.strftime("%Y%m%d"), "pretrade_date"] = (
            FRIDAY.strftime("%Y%m%d"))
        return frame

    monkeypatch.setattr(chain.sdk, "_calendar", revised)
    result = advance(chain)
    assert result["state"].definition.effective_from == start
    assert result["state"].evaluated_at >= initial["state"].evaluated_at
    if latched:
        assert result["revision"] == initial["revision"]
        assert result["state_hash"] == initial["state_hash"]
    else:
        assert result["state"].target == datetime.combine(FRIDAY, time(15), SH)
        assert result["state"].outcome == "CLEAR_THROUGH_TARGET"
        assert result["revision"] > invalidated["revision"]
        with chain.plans._unit_of_work() as work:
            work.daily.lock_symbol(SYMBOL)
            assert not pipeline(chain).buy_suspension_current(work, chain.plan,
                expected_revision=initial["revision"])


def test_revoked_minute_proof_cannot_retarget_an_open_former_session(chain):
    seed_schema10(chain, datetime.combine(FRIDAY, time(9, 30), SH))
    initial = advance(chain)
    chain.now += timedelta(seconds=1)
    with chain.plans._unit_of_work() as work:
        target = initial["state"].target
        source = work.history.list_minutes(SYMBOL, start=target, end=target)[0]
        work.history.upsert_minutes((source.model_copy(update={
            "close_fen": 2431, "high_fen": 2431, "received_at": chain.now}),))
        work.commit()
    invalidated = guard_row(chain)
    assert invalidated["state"].coverage is None
    earlier = datetime.combine(FRIDAY - timedelta(days=1), time(15), SH)
    with chain.plans._unit_of_work() as work:
        assert work.daily.retarget_buy_suspension_calendar(invalidated["state"],
            target=earlier, evaluated_at=chain.now) is None
        forged = invalidated["state"].model_copy(update={
            "target": earlier, "evaluated_at": chain.now, "blocker": "HISTORY_PENDING"})
        with pytest.raises(ValueError, match="actual revised calendar"):
            work.daily.save(invalidated["id"], kind="BUY_SUSPENSION", symbol=SYMBOL,
                lineage=forged.owner_plan_version_id, payload=forged.model_dump(mode="json"),
                expected_revision=invalidated["revision"])
