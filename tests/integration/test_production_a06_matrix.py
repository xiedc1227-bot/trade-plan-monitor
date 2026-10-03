"""Offline current stock isolation plus retained index research through the real composition."""

import asyncio
import json
from datetime import timedelta

import pytest
from requests import ConnectionError as ProviderConnectionError
from sqlalchemy import func, select
from test_live_pipeline_acceptance import (
    NOW,
    _write_configuration_and_evidence,
)
from test_production_certification_gate import _composition
from test_s3_permission_reservation_process import _business_rows
from tests.integration.current_activation_fixture import current_sample_plan, seed_current

from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.aggregation import (
    aggregate_five_minute_bar,
    expected_five_minute_ends,
    five_minute_bucket_end,
)
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import MarketIndexHealth, MarketIndexIssueCode
from trade_plan_monitor.notifications.channels import ChannelDeliveryResult, DeliveryChannel
from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.daily_models import DailyRecord as DailyPlanRecord
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    AlertEvent,
    EvaluationResult,
    ExplicitEvaluationLedger,
    MarketIndexSnapshot,
    RuntimeLiveness,
    SymbolDecisionHead,
)
from trade_plan_monitor.state.repositories import MarketHistoryRepository
from trade_plan_monitor.web.monitor_composition import create_monitor_composition


async def _complete_pending_explicit_prefetch(composition, sdk, database, *, startup_calls):
    """Prepare the one remaining family, not a second startup or a business evaluation."""
    startup_history = [
        (name, kwargs) for name, kwargs in sdk.calls[startup_calls:] if name == "rt_min_daily"
    ]
    assert len(startup_history) == 1 and startup_history[0][1]["ts_code"] == "003043.SZ"
    state = composition._runtime._probe_capabilities.__self__
    pipeline = state._pipeline
    sdk.clock.current = max(sdk.clock.now(), pipeline.next_stock_recovery_at())
    assert pipeline.next_stock_recovery_at() <= sdk.clock.now()
    capture = pipeline._capture_recovery_scope("300001.SZ")
    assert capture is not None and capture.required_ends
    before_calls = len(sdk.calls)
    before = _business_rows(database)
    current_before = business_rows(state)
    result = await state.run_deadline(
        MarketDeadline(
            kind=DeadlineKind.STOCK_RECOVERY,
            trade_date=sdk.clock.now().date(),
            due_at=sdk.clock.now(),
        )
    )
    assert result.ready and result.symbol == "300001.SZ" and result.target == capture.target
    assert [(name, kwargs["ts_code"]) for name, kwargs in sdk.calls[before_calls:]] == [
        ("rt_min_daily", "300001.SZ"),
    ]
    after = _business_rows(database)
    assert business_rows(state) == current_before
    source_tables = {"minute_bar", "latest_quote", "five_minute_bar"}
    assert {key: value for key, value in after.items() if key not in source_tables} == {
        key: value for key, value in before.items() if key not in source_tables
    }
    existing = set(before["five_minute_bar"])
    assert existing <= set(after["five_minute_bar"])
    existing_keys = {(row[0], row[1], row[2]) for row in existing}
    with state._session_factory() as session:
        minutes = MarketHistoryRepository(session).list_minutes(
            capture.symbol,
            start=capture.required_ends[0],
            end=capture.required_ends[-1],
        )
    by_end = {bar.bar_end: bar for bar in minutes}
    required = frozenset(capture.required_ends)
    expected = set()
    for bucket in sorted({five_minute_bucket_end(end) for end in required}):
        key = (capture.symbol, bucket.isoformat(), "ta-v1")
        if bucket > capture.target.completed_minute_end or key in existing_keys:
            continue
        ends = expected_five_minute_ends(bucket)
        if not all(end in required and end in by_end for end in ends):
            continue
        aggregate = aggregate_five_minute_bar(
            tuple(by_end[end] for end in ends),
            bucket_end=bucket,
            is_open=True,
        )
        assert aggregate is not None
        expected.add(
            (
                aggregate.symbol,
                aggregate.bar_end.isoformat(),
                aggregate.formula_version,
                aggregate.open_fen,
                aggregate.high_fen,
                aggregate.low_fen,
                aggregate.close_fen,
                aggregate.volume_shares,
                str(aggregate.amount_yuan),
            )
        )
    assert expected
    assert set(after["five_minute_bar"]) - existing == expected


@pytest.mark.parametrize("failed_family", ("legacy", "explicit"))
def test_one_malformed_stock_row_does_not_block_other_plan_family_or_indexes(
    tmp_path,
    monkeypatch,
    failed_family,
):
    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path,
            monkeypatch,
            active_plan=True,
            include_index=True,
            persisted_calendar=True,
        )
        legacy_symbol = "003043.SZ"
        payload = current_sample_plan().model_dump(mode="json")
        payload.update(plan_id="offline-a06-second", symbol="300001.SZ", name="A06 second stock")
        explicit_plan = UnifiedTradePlan.model_validate(payload)
        seed_current(tmp_path, plan=explicit_plan)
        sdk.stock_symbols = (legacy_symbol, explicit_plan.symbol)
        failed_symbol = legacy_symbol if failed_family == "legacy" else explicit_plan.symbol
        original_minutes = sdk._stock_minutes

        def one_bad_row(name, kwargs):
            frame = original_minutes(name, kwargs)
            if name == "rt_min":
                frame.loc[frame["ts_code"] == failed_symbol, "close"] = "malformed"
            return frame

        sdk._stock_minutes = one_bad_row
        sdk.clock.current = NOW.replace(minute=59, hour=9, second=30)
        _write_configuration_and_evidence(tmp_path, observed_at=sdk.clock.now(), include_index=True)
        try:
            startup_calls = len(sdk.calls)
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            await _complete_pending_explicit_prefetch(
                composition,
                sdk,
                tmp_path / "monitor.sqlite3",
                startup_calls=startup_calls,
            )
            sdk.clock.current = NOW
            await state.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=NOW.date(),
                    due_at=NOW,
                    bar_end=NOW.replace(second=0),
                )
            )
            with state._session_factory() as session:
                rows = work_rows(session)
                legacy_results = len([r for r in rows if r["symbol"] == legacy_symbol])
                explicit_results = len([r for r in rows if r["symbol"] == explicit_plan.symbol])
                index_rows = session.scalar(select(func.count()).select_from(MarketIndexSnapshot))
            assert (legacy_results, explicit_results) == (1, 1)
            failed = next(row for row in rows if row["symbol"] == failed_symbol)
            healthy = next(row for row in rows if row["symbol"] != failed_symbol)
            assert failed["data_blockers"]
            assert failed["signals"] == failed["risks"] == []
            assert not healthy["data_blockers"]
            assert index_rows >= 5
            assert sum(name == "rt_min" for name, _ in sdk.calls) == 1
        finally:
            await composition.stop()

        sdk._stock_minutes = original_minutes
        sdk.clock.current = NOW + timedelta(minutes=5)
        replacement = create_monitor_composition(
            config_path=tmp_path / "config/app.yaml",
            database_path=tmp_path / "monitor.sqlite3",
        )
        try:
            startup_calls = len(sdk.calls)
            assert (await replacement.start()).status is RuntimeServiceStatus.RUNNING
            state = replacement._runtime._probe_capabilities.__self__
            await _complete_pending_explicit_prefetch(
                replacement,
                sdk,
                tmp_path / "monitor.sqlite3",
                startup_calls=startup_calls,
            )
            await state.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=NOW.date(),
                    due_at=sdk.clock.now(),
                    bar_end=NOW.replace(second=0) + timedelta(minutes=5),
                )
            )
            target = (NOW.replace(second=0) + timedelta(minutes=5)).isoformat()
            with state._session_factory() as session:
                rows = work_rows(session)
                for plan in (current_sample_plan(), explicit_plan):
                    selected = [
                        r
                        for r in rows
                        if r["symbol"] == plan.symbol and r["minute_target"] == target
                    ]
                    assert len(selected) == 1
                    assert selected[0]["plan_hash"] == plan_sha256(plan)
                    assert selected[0]["activation_revision"] == 1
                    head = session.get(DailyPlanRecord, "evaluation-head-" + plan.symbol)
                    assert json.loads(head.payload_json) == selected[0]
            assert sum(name == "rt_min" for name, _ in sdk.calls) == 2
        finally:
            await replacement.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("requires_index", (False, True))
def test_required_index_failure_isolates_mixed_family_deadline(
    tmp_path, monkeypatch, requires_index
):
    """The frozen predicate remains readable; current stock rules are index independent."""
    from sqlalchemy import delete
    from tests.integration.test_s3_index_retry_process import _seed

    async def scenario():
        composition, sdk, _ = _composition(
            tmp_path, monkeypatch, active_plan=False, include_index=True, persisted_calendar=True
        )
        database = tmp_path / "monitor.sqlite3"
        engine = create_sqlite_engine(database)
        with create_session_factory(engine).begin() as session:
            session.execute(delete(RuntimeLiveness))
        engine.dispose()
        dependent, independent = _seed(tmp_path, monkeypatch, requires_index=requires_index)
        assert dependent.entry.condition.type == (
            "INDEX_CLOSE_GTE_MA" if requires_index else "NON_DECREASING_CLOSE"
        )
        raw = current_sample_plan().model_dump(mode="json")
        raw.update(version=2, plan_id="a06-current-first")
        first = seed_current(
            tmp_path, plan=UnifiedTradePlan.model_validate(raw), activation_revision=1
        )
        sdk.stock_symbols = (first.symbol, independent.symbol)
        required_code = dependent.reference_market.index_code.value
        original = sdk._index_minutes

        def fail(kwargs):
            if kwargs["ts_code"] == required_code:
                raise ProviderConnectionError("offline required-index interruption")
            return original(kwargs)

        sdk._index_minutes = fail
        delivered = []

        class Channel:
            channel = DeliveryChannel.IN_APP
            enabled = True

            async def deliver(self, event):
                delivered.append(event.symbol)
                return ChannelDeliveryResult(channel=self.channel, delivered=True, retryable=False)

        try:
            startup_calls = len(sdk.calls)
            assert (await composition.start()).status is RuntimeServiceStatus.RUNNING
            state = composition._runtime._probe_capabilities.__self__
            state._dispatcher._channels = (Channel(),)
            await _complete_pending_explicit_prefetch(
                composition, sdk, database, startup_calls=startup_calls
            )
            results = await state.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.REALTIME_MINUTE,
                    trade_date=NOW.date(),
                    due_at=NOW,
                    bar_end=NOW.replace(second=0),
                )
            )
            assert len(results) == 2
            assert delivered == [independent.symbol]
            assert sum(len(item.event_ids) for item in results) == 1
            failed = state._pipeline.index_service.latest_snapshots()[
                MarketIndexCode(required_code)
            ]
            assert failed.health is MarketIndexHealth.BLOCKED
            assert MarketIndexIssueCode.PROVIDER_UNAVAILABLE in failed.issues
            retry_at = state.next_index_recovery_at()
            assert retry_at is not None
            with state._session_factory() as session:
                assert len(work_rows(session)) == 2
                for model in (EvaluationResult, ExplicitEvaluationLedger, SymbolDecisionHead):
                    assert session.scalar(select(func.count()).select_from(model)) == 0
            failed_hash = failed.snapshot_hash
        finally:
            await composition.stop()
        sdk._index_minutes = original
        sdk.clock.current = NOW + timedelta(minutes=4)
        replacement = create_monitor_composition(
            config_path=tmp_path / "config/app.yaml", database_path=database
        )
        try:
            assert (await replacement.start()).status is RuntimeServiceStatus.RUNNING
            state = replacement._runtime._probe_capabilities.__self__
            state._dispatcher._channels = (Channel(),)
            assert state.next_index_recovery_at() == retry_at
            persisted = state._pipeline.index_service.latest_snapshots()[
                MarketIndexCode(required_code)
            ]
            assert persisted.snapshot_hash == failed_hash
            before = business_rows(state)
            calls = len(sdk.calls)
            await state.run_deadline(
                MarketDeadline(
                    kind=DeadlineKind.INDEX_RECOVERY, trade_date=NOW.date(), due_at=retry_at
                )
            )
            assert sdk.calls[calls:]
            assert all(
                name in {"idx_mins", "rt_idx_min_daily", "index_daily"}
                and kwargs["ts_code"] == required_code
                for name, kwargs in sdk.calls[calls:]
            )
            recovered = state._pipeline.index_service.latest_snapshots()[
                MarketIndexCode(required_code)
            ]
            assert recovered.health is MarketIndexHealth.LIVE
            assert recovered.snapshot_hash != failed_hash
            assert recovered.decision_cutoff == NOW.replace(second=0)
            assert state.next_index_recovery_at() is None
            assert business_rows(state) == before
            assert delivered == [independent.symbol]
        finally:
            await replacement.stop()

    asyncio.run(scenario())


def work_rows(session):
    return [
        json.loads(row.payload_json)
        for row in session.scalars(
            select(DailyPlanRecord).where(DailyPlanRecord.kind == "EVALUATION")
        )
        if not row.id.startswith("evaluation-head-")
        and json.loads(row.payload_json).get("minute_target")
    ]


def business_rows(state):
    with state._session_factory() as session:
        return tuple(
            (row.id, row.revision, row.payload_json)
            for row in session.scalars(select(DailyPlanRecord).order_by(DailyPlanRecord.id))
        ), tuple(
            (row.id, row.payload_json)
            for row in session.scalars(select(AlertEvent).order_by(AlertEvent.id))
        )
