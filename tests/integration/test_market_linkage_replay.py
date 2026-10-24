from datetime import timedelta

import pytest
from tests.integration.test_market_linkage_runtime import index_snapshot
from tests.unit.test_market_linkage_contract import linked_payload

from trade_plan_monitor.backtest.market_linkage_input import LinkedIndexReplaySource
from trade_plan_monitor.domain.market_linkage_models import MarketLinkedTradePlan


def source_fixture():
    plan = MarketLinkedTradePlan.model_validate(linked_payload())
    snapshot, days = index_snapshot(plan)
    return (
        plan,
        snapshot,
        days,
        LinkedIndexReplaySource(
            reference_market=plan.reference_market, bars=snapshot.official_daily_bars
        ),
    )


def test_linked_replay_cutoff_and_future_correction_do_not_change_past():
    plan, snapshot, days, source = source_fixture()
    now = snapshot.observed_at
    future = source.bars[-1].model_copy(
        update={
            "provider_revision": 2,
            "observed_at": now + timedelta(hours=1),
            "low_points": source.bars[-1].low_points - 1,
        }
    )
    changed = LinkedIndexReplaySource(
        reference_market=plan.reference_market, bars=(*source.bars, future)
    )
    assert source.snapshot_at(now, days) == changed.snapshot_at(now, days)
    assert changed.snapshot_at(now + timedelta(hours=1), days) != source.snapshot_at(now, days)
    assert (
        source.snapshot_at(now - timedelta(hours=2), days).official_daily_bars[-1].bar_at.date()
        == days[-2]
    )
    assert LinkedIndexReplaySource.model_validate_json(source.model_dump_json()) == source


def test_missing_historical_scope_rejects_before_replay():
    plan, snapshot, days, source = source_fixture()
    with pytest.raises(ValueError, match="HISTORY_MISSING"):
        source.validate_scope(
            binding=plan.reference_market,
            session_dates=days,
            started_at=snapshot.observed_at,
            cutoff=snapshot.observed_at,
        )


def test_fact_only_daily_confirmation_keeps_missing_price_basis_blocker():
    from trade_plan_monitor.backtest.loop_replay import _Frames

    raw = linked_payload()
    raw.update(risk_branches=[], alert_rules=[])
    raw["ordinary_rules"] = raw["ordinary_rules"][:1]
    raw["ordinary_rules"][0]["condition"] = {
        "type": "REVIEWED_FACT", "fact_kind": "TECHNICAL",
        "evidence_requirement": "Reviewed complete S0", "validity_scope": "TRADE_DATE",
    }
    plan = MarketLinkedTradePlan.model_validate(raw)
    _, snapshot, _, _ = source_fixture()
    frames = _Frames(None, plan, None, (), None, None)
    inputs = frames._inputs(snapshot.observed_at, snapshot.decision_cutoff.date())
    assert inputs.series is None
    assert "PRICE_BASIS_UNVERIFIED" in inputs.data_blockers


def test_frozen_dataset_replays_linked_decision_and_publishes_zero_trade_cause(tmp_path):
    from datetime import datetime, time
    from decimal import Decimal

    from tests.integration.test_backtest_runner import (
        PROFILE,
        SHANGHAI,
        SYMBOL,
        TRADE_DATE,
        _execution_config,
        _seed_dataset,
    )
    from tests.unit.test_unified_replay_input import research_input

    from trade_plan_monitor.backtest.dataset import DatasetScope
    from trade_plan_monitor.backtest.market_store import BacktestMarketStore
    from trade_plan_monitor.backtest.research_input import ResearchAdjustmentProof, ResearchFactor
    from trade_plan_monitor.backtest.runner import OfflineBacktestRunner
    from trade_plan_monitor.market_data.models import DailyBar, TradingDay
    from trade_plan_monitor.market_index.models import MarketIndexBar

    store = BacktestMarketStore(tmp_path / "market.sqlite")
    _seed_dataset(store)
    start = TRADE_DATE - timedelta(days=100)
    previous = start - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    calendars, daily, indexes = [], [], []
    for offset in range(101):
        day = start + timedelta(days=offset)
        opened = day.weekday() < 5
        calendars.append(
            TradingDay(exchange="SSE", cal_date=day, is_open=opened, previous_trade_date=previous)
        )
        if not opened:
            continue
        close = datetime.combine(day, time(15), SHANGHAI)
        daily.append(
            DailyBar(
                symbol=SYMBOL,
                trade_date=day,
                open_fen=6400,
                high_fen=6420,
                low_fen=6380,
                close_fen=6400,
                volume_shares=2_000_000,
                amount_yuan=Decimal("128000000"),
                is_official=True,
                received_at=close + timedelta(minutes=20),
            )
        )
        points = Decimal(100 + len(indexes))
        indexes.append(
            MarketIndexBar(
                index_code="000001.SH",
                interval="OFFICIAL_DAILY",
                bar_at=close,
                observed_at=close + timedelta(minutes=20),
                open_points=points,
                high_points=points + 1,
                low_points=points - 1,
                close_points=points,
                source_kind="OFFICIAL",
                provider_revision=1,
            )
        )
        previous = day
    store.record_trading_days(tuple(calendars))
    store.record_daily_bars(tuple(daily))
    store.record_index_bars(tuple(indexes))
    result = store.freeze_dataset_v2(
        DatasetScope(
            symbols=(SYMBOL,),
            start=TRADE_DATE,
            end=TRADE_DATE,
            warmup_start=start,
            historical_profile=PROFILE,
        )
    )
    assert result.ready, result.blockers
    raw = linked_payload()
    raw.update(symbol=SYMBOL, risk_branches=[])
    raw["position"]["max_qty"] = 1000
    raw["levels"]["low_buy"].update(low_fen=6300, high_fen=6500)
    raw["levels"]["pressure"].update(low_fen=6600, high_fen=6800)
    raw["ordinary_rules"][0].update(
        validity={"mode": "PLAN_ACTIVE"},
        independent_signal={"mode": "ONCE_PER_RULE"},
        condition={
            "type": "DAILY_PRICE_IN_RANGE",
            "field": "close",
            "offset": 0,
            "range": raw["levels"]["low_buy"],
        },
    )
    plan = MarketLinkedTradePlan.model_validate(raw)
    from tests.unit.test_monitor_loop_cutoff import request

    from trade_plan_monitor.backtest.loop_dataset import LoopDatasetManifest
    from trade_plan_monitor.backtest.loop_input_store import _validate_linked_source

    loop_request = request(
        plan=plan, warmup_start=start, cutoff=datetime.combine(TRADE_DATE, time(16), SHANGHAI)
    )
    loop = store.freeze_loop_dataset(loop_request)
    assert loop.ready, loop.blockers
    assert loop.manifest.linked_index_source is not None
    assert len(loop.manifest.linked_index_source.bars) >= 60
    assert LoopDatasetManifest.model_validate_json(loop.manifest.model_dump_json()) == loop.manifest
    _validate_linked_source(loop_request.schedule, loop.manifest)
    _publish_linked_loop(tmp_path, store, plan, loop_request)
    with pytest.raises(ValueError, match="HISTORY_MISSING"):
        payload = loop.manifest.model_dump(exclude={"dataset_hash", "linked_index_source"})
        _validate_linked_source(loop_request.schedule, LoopDatasetManifest.build(**payload))
    at = datetime.combine(TRADE_DATE, time(15, 20), SHANGHAI)
    proof = ResearchAdjustmentProof(
        proof_id="linked-proof",
        dataset_hash=result.dataset_hash,
        symbol=SYMBOL,
        provider="TUSHARE",
        adjustment_as_of=TRADE_DATE,
        available_at=at,
        received_at=at,
        quote_basis_factor=Decimal(1),
        evidence="Synthetic certified constant factor",
        factors=tuple(
            ResearchFactor(trade_date=bar.trade_date, factor=Decimal(1)) for bar in daily
        ),
    )
    frozen = research_input(plan).model_copy(
        update={
            "started_at": at.replace(hour=9, minute=0),
            "adjustment_proofs": (proof,),
            "calendar_extension": (
                TradingDay(
                    exchange="SSE",
                    cal_date=TRADE_DATE + timedelta(days=1),
                    is_open=True,
                    previous_trade_date=TRADE_DATE,
                ),
            ),
        }
    )
    report = OfflineBacktestRunner(store).run(
        plan=plan,
        dataset_hash=result.dataset_hash,
        initial_cash_fen=10_000_000,
        execution_config=_execution_config(),
        manual_event_risk=False,
        research_input=frozen,
    )
    assert report.metrics.trade_count == 0
    decisions = [event for event in report.current_events if event.market_linkage]
    assert decisions
    assert decisions[-1].market_linkage[0].calculation.authorized_quantity == 300
    assert decisions[-1].signals[0].planned_qty == 300
    assert decisions[-1].signals[0].executable_qty == 0  # next exchange session, not today
    assert any(
        "CONFIRMATION_UNKNOWN" in event.market_linkage[0].calculation.blockers
        for event in decisions[:-1]
    )


def _publish_linked_loop(tmp_path, market, plan, request):
    """Exercise reviewed preparation, copied inputs, worker and report publication."""
    from uuid import UUID

    from tests.integration.test_market_linkage_review import source_mapping
    from tests.integration.test_plan_preparation_review import review_command
    from tests.unit.test_monitor_loop_extraction import extract
    from tests.unit.test_monitor_loop_input import costs

    from trade_plan_monitor.backtest.control import CancellationToken
    from trade_plan_monitor.backtest.jobs.models import BacktestRunJobResult, MonitorLoopJobRequest
    from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
    from trade_plan_monitor.backtest.loop_input import LoopResponsePolicy, MonitorLoopInput
    from trade_plan_monitor.backtest.loop_replay import run_frozen_loop
    from trade_plan_monitor.backtest.preparation_models import (
        PreparationSource,
        SinglePlanPreparationInput,
    )
    from trade_plan_monitor.backtest.preparation_review import frozen_preparation
    from trade_plan_monitor.backtest.preparation_store import PreparationStore
    from trade_plan_monitor.backtest.results import BacktestResultStore
    from trade_plan_monitor.domain.market_linkage_validation import MarketLinkedPlanDraft

    draft = MarketLinkedPlanDraft.from_executable(plan)
    text, mapping = source_mapping(draft)
    source = PreparationSource(
        source_id="source-1",
        text=text,
        authored_at=request.boundary.started_at,
        available_at=request.boundary.started_at,
        effective_trade_date=request.scope.start,
    )
    extracted = extract(
        {
            "schema_version": "monitor-loop-extraction-v1",
            "draft": draft.model_dump(mode="json"),
            "clauses": [clause.model_dump(mode="json") for clause in mapping.clauses],
            "bindings": [binding.model_dump(mode="json") for binding in mapping.bindings],
            "opening_account": {
                "inventory_quantity": None,
                "lots": [],
                "cash_fen": None,
                "snapshot_at": None,
            },
        },
        text,
        authored_at=source.authored_at,
        available_at=source.available_at,
        effective_trade_date=source.effective_trade_date,
    )
    preparation = PreparationStore(
        tmp_path / "linked-preparation.sqlite3", clock=lambda: request.boundary.started_at
    )
    created = preparation.create(
        SinglePlanPreparationInput(
            preparation_id="linked-source",
            sources=(source,),
        ),
        idempotency_key="create",
    )
    running = preparation.start_attempt(
        created.preparation_id, expected_revision=created.revision, idempotency_key="start"
    )
    attempt = running.attempts[-1].attempt_id
    extracted = extracted.model_copy(update={"request_id": UUID(attempt)})
    ready = preparation.finish_attempt(
        running.preparation_id,
        attempt_id=attempt,
        expected_revision=running.revision,
        candidate=extracted.to_preparation_candidate(),
        idempotency_key="finish",
    )
    prepared = frozen_preparation(
        preparation.review_and_freeze(
            ready.preparation_id,
            command=review_command(ready, draft=draft, mapping=mapping),
            idempotency_key="linked-review",
        )
    )
    frozen = market.freeze_loop_dataset(request.model_copy(update={"schedule": prepared.schedule}))
    assert frozen.ready, frozen.blockers
    run = MonitorLoopInput(
        schedule=prepared.schedule,
        initial_account=prepared.account,
        boundary=request.boundary,
        dataset_hash=frozen.manifest.dataset_hash,
        response=LoopResponsePolicy(mode="FOLLOW_REMINDERS"),
        costs=costs(),
    )
    jobs = BacktestJobRepository(
        tmp_path / "linked-results.sqlite3", clock=lambda: request.boundary.evidence_cutoff
    )
    results = BacktestResultStore(jobs.database_path)
    reference = results.record_loop_input(
        prepared=prepared,
        run_input=run,
        dataset=frozen.manifest,
        market_source=market,
    )
    assert (
        BacktestResultStore(jobs.database_path).get_loop_input(reference).dataset == frozen.manifest
    )
    receipt = jobs.submit(MonitorLoopJobRequest(input_reference=reference), "linked-loop")
    claim = jobs.claim_next()
    report = run_frozen_loop(
        results,
        reference,
        cancellation_token=CancellationToken(),
        progress_callback=lambda _: None,
    )
    assert jobs.complete(
        claim.job_id,
        claim.claim_token.get_secret_value(),
        BacktestRunJobResult(
            run_id=reference.run_id,
            report_hash=report.report_hash,
            reused=False,
        ),
    )
    assert jobs.get(receipt.job_id).status.value == "COMPLETED"
    assert BacktestResultStore(jobs.database_path).get_loop_report(reference.run_id) == report
