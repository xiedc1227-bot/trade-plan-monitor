"""Frozen synthetic exchange data and reviewed preparation, with no provider calls."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from tests.integration.test_backtest_runner import PROFILE
from tests.integration.test_daily_plan_chain import FRIDAY, SH, TUESDAY, WEDNESDAY
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_plan_preparation_review import review_command
from tests.unit.test_monitor_loop_extraction import extract

from trade_plan_monitor.backtest.daily_basis import DailyBasisStore, HistoricalAdjustmentFactor
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.market_data.historical_provider import (
    HistoricalMinuteBatch,
    HistoricalOpeningSpecial,
)
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.market_index.models import MarketIndexBar


def market_fixture(directory, plan, route):
    market = BacktestMarketStore(directory / "market.sqlite")
    start = FRIDAY - timedelta(days=100)
    days, daily, indices, factors = [], [], [], []
    previous = start - timedelta(days=3)
    open_days = [
        start + timedelta(days=i)
        for i in range((WEDNESDAY - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
        and start + timedelta(days=i) != TUESDAY - timedelta(days=1)
    ]
    decision_index = open_days.index(FRIDAY)
    for offset in range((WEDNESDAY - start).days + 1):
        day = start + timedelta(days=offset)
        opened = day in open_days
        days.append(
            TradingDay(exchange="SSE", cal_date=day, is_open=opened, previous_trade_date=previous)
        )
        if not opened:
            continue
        previous = day
        if day > TUESDAY:
            continue
        i = open_days.index(day) - decision_index + 59
        price = 100 + i + 2 * (i % 2)
        received = datetime.combine(day, time(15, 20), SH)
        daily.append(
            DailyBar(
                symbol=plan.symbol,
                trade_date=day,
                open_fen=price,
                high_fen=price + 1,
                low_fen=price - 1,
                close_fen=price,
                volume_shares=1000,
                amount_yuan=Decimal(price * 10),
                is_official=True,
                received_at=received,
            )
        )
        point = Decimal(
            200 if i < 58 else 190 if i == 58 else 195 if route == "WEAK_MINIMUM" else 180
        )
        indices.append(
            MarketIndexBar(
                index_code=plan.reference_market.index_code,
                interval="OFFICIAL_DAILY",
                source_kind="OFFICIAL",
                provider_revision=1,
                bar_at=datetime.combine(day, time(15), SH),
                observed_at=received,
                open_points=point,
                close_points=point,
                high_points=point + 1,
                low_points=point - 1,
            )
        )
        factors.append(
            HistoricalAdjustmentFactor(
                symbol=plan.symbol,
                trade_date=day,
                factor=Decimal(1),
                available_at=datetime.combine(day, time(9, 30), SH),
                collected_at=datetime.combine(WEDNESDAY, time(16), SH),
            )
        )
        if day < FRIDAY:
            continue
        bars = tuple(
            MinuteBar(
                symbol=plan.symbol,
                bar_end=end,
                received_at=end + timedelta(seconds=12),
                open_fen=161,
                high_fen=162,
                low_fen=160,
                close_fen=161,
                volume_shares=1000,
                amount_yuan=Decimal(1610),
            )
            for end in expected_minute_ends(day, is_open=True)
        )
        market.record_minute_batch(
            HistoricalMinuteBatch(
                symbol=plan.symbol,
                trade_date=day,
                contract_version=PROFILE,
                bars=bars,
                opening_special=HistoricalOpeningSpecial(
                    symbol=plan.symbol,
                    source_time=datetime.combine(day, time(9, 30), SH),
                    open_fen=161,
                    high_fen=162,
                    low_fen=160,
                    close_fen=161,
                    volume_shares=1000,
                    amount_yuan=Decimal(1610),
                ),
            )
        )
        market.record_daily_limits(
            (
                DailyLimit(
                    symbol=plan.symbol,
                    trade_date=day,
                    up_limit_fen=220,
                    down_limit_fen=50,
                    received_at=datetime.combine(day, time(9, 30), SH),
                ),
            )
        )
    market.record_trading_days(tuple(days))
    market.record_daily_bars(tuple(daily))
    market.record_index_bars(tuple(indices))
    DailyBasisStore(market.database_path).record(tuple(factors))
    scope = DatasetScope(
        symbols=(plan.symbol,),
        start=FRIDAY,
        end=TUESDAY,
        warmup_start=start,
        historical_profile=PROFILE,
    )
    frozen = market.freeze_dataset_v2(scope)
    assert frozen.ready, frozen.blockers
    return market, frozen.dataset_hash, tuple(days), tuple(daily), tuple(indices), tuple(factors)


def prepared_fixture(directory, plan, start, account):
    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    draft = UnifiedPlanDraft.from_executable(plan)
    text, mapping = source_mapping(draft)
    source = PreparationSource(
        source_id="source-1",
        text=text,
        authored_at=start,
        available_at=start,
        effective_trade_date=start.date(),
    )
    extracted = extract(
        {
            "schema_version": "monitor-loop-extraction-v1",
            "draft": draft.model_dump(mode="json"),
            "clauses": [c.model_dump(mode="json") for c in mapping.clauses],
            "bindings": [b.model_dump(mode="json") for b in mapping.bindings],
            "opening_account": {
                "inventory_quantity": None,
                "lots": [],
                "cash_fen": None,
                "snapshot_at": None,
            },
        },
        text,
        authored_at=start,
        available_at=start,
        effective_trade_date=start.date(),
    )
    store = PreparationStore(directory / "preparation.sqlite", clock=lambda: start)
    created = store.create(
        SinglePlanPreparationInput(preparation_id="exception-replay", sources=(source,)),
        idempotency_key="create",
    )
    running = store.start_attempt(
        created.preparation_id, expected_revision=created.revision, idempotency_key="start"
    )
    attempt = running.attempts[-1].attempt_id
    extracted = extracted.model_copy(update={"request_id": UUID(attempt)})
    ready = store.finish_attempt(
        running.preparation_id,
        attempt_id=attempt,
        expected_revision=running.revision,
        candidate=extracted.to_preparation_candidate(),
        idempotency_key="finish",
    )
    command = review_command(ready, draft=draft, mapping=mapping).model_copy(
        update={"account": account}
    )
    return frozen_preparation(
        store.review_and_freeze(
            ready.preparation_id, command=command, idempotency_key="explicit-review"
        )
    )


def frozen_market_approval(directory, chain, calendar, daily, indices, factors,
                           *, run_input_factory=None):
    from tests.integration.test_market_exception_replay import research_run_input

    from trade_plan_monitor.backtest.exception_replay_input import FrozenExceptionEvent
    from trade_plan_monitor.backtest.loop_replay import _Frames
    from trade_plan_monitor.backtest.market_linkage_input import LinkedIndexReplaySource
    from trade_plan_monitor.backtest.research_session import ResearchSession
    from trade_plan_monitor.decision.market_exception_decision import MarketExceptionDecision
    from trade_plan_monitor.domain.plan_hash import plan_sha256
    from trade_plan_monitor.runtime.market_exceptions import (
        apply_exception_decision,
        current_exception_authority,
    )
    from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
    from trade_plan_monitor.state.market_exception_service import (
        ExceptionDecisionCommand,
        ExceptionPreviewCommand,
        preview_exception,
    )

    source = LinkedIndexReplaySource(reference_market=chain.plan.reference_market, bars=indices)
    frames = _Frames(
        None,
        chain.plan,
        None,
        calendar,
        None,
        None,
        adjustment_factors=factors,
        linked_source=source,
    )
    frames.daily = {d.trade_date: d for d in daily if d.received_at <= chain.now}
    inputs = frames._inputs(chain.now, FRIDAY)
    session = ResearchSession(directory, (run_input_factory or research_run_input)(chain), calendar)
    try:
        evaluated = session.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        assert evaluated.snapshot["exception_candidates"], evaluated.snapshot["market_linkage"]
        row = evaluated.snapshot["exception_candidates"][0]
        candidate = ExceptionCandidate.model_validate(row["candidate"])
        with session.work() as work:
            preview = preview_exception(
                work.daily,
                ExceptionPreviewCommand(
                    candidate_id=candidate.candidate_id,
                    expected_revision=1,
                    proposed_quantity=300 if chain.route == "BROKEN_STRONG" else None,
                ),
                current=lambda c: current_exception_authority(work, c, chain.now),
                now=chain.now,
            )
            receipt = apply_exception_decision(
                work,
                ExceptionDecisionCommand(
                    command_id="frozen-source-approval",
                    candidate_id=candidate.candidate_id,
                    expected_revision=1,
                    decision="APPROVE",
                    reason="Explicit research scenario",
                    preview_id=preview.preview_id,
                    preview_hash=preview.preview_hash,
                ),
                now=chain.now,
            )
            work.commit()
        return FrozenExceptionEvent.build(
            plan_hash=plan_sha256(chain.plan),
            candidate=candidate,
            decision=MarketExceptionDecision.model_validate(
                evaluated.snapshot["market_linkage"][0]
            ),
            event=receipt.event,
            provenance="RESEARCH_SCENARIO",
            order=0,
        )
    finally:
        session.close()
