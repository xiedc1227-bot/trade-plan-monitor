"""Immutable cutoff selection, genuine gaps and old readiness remain separate."""

import sqlite3
from datetime import timedelta

import pytest
from tests.integration.test_backtest_market_store import (
    PROFILE,
    _calendar,
    _daily,
    _limit,
    _minute_batch,
    _scope,
    _seed_complete,
)
from tests.unit.test_monitor_loop_cutoff import daily_plan, request, scheduled_request
from tests.unit.test_monitor_loop_schedule import at, row, version

from trade_plan_monitor.backtest.control import BacktestOperationCancelled, CancellationToken
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.loop_dataset import LoopDatasetManifest, LoopDatasetRequest
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary, LoopSchedule


def test_daily_warmup_missing_blocks_and_missing_required_close_stays_visible(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    value = request(plan=daily_plan())
    result = store.freeze_loop_dataset(value)
    assert not result.ready and result.blockers == ("LOOP_DAILY_WARMUP_INSUFFICIENT:0:1",)
    prior = value.scope.start - timedelta(days=3)
    store.record_trading_days(
        (
            _calendar().model_copy(
                update={"cal_date": prior, "previous_trade_date": prior - timedelta(days=1)}
            ),
            _calendar().model_copy(
                update={"cal_date": prior + timedelta(days=1), "is_open": False}
            ),
            _calendar().model_copy(
                update={"cal_date": prior + timedelta(days=2), "is_open": False}
            ),
        )
    )
    store.record_daily_bars(
        (
            _daily().model_copy(
                update={
                    "trade_date": prior,
                    "received_at": at(21, 15, 20),
                }
            ),
        )
    )
    assert store.freeze_loop_dataset(request(plan=daily_plan(), warmup_start=prior)).ready
    delayed = store.freeze_loop_dataset(
        request(
            cutoff=at(24, 15, 0, 12),
            plan=daily_plan(),
            warmup_start=prior,
        )
    )
    assert not delayed.ready and any("OFFICIAL_CLOSE_NOT_AVAILABLE" in b for b in delayed.blockers)


def test_holiday_end_is_not_shifted_or_filled_with_price_data(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    start = at(21, 9)
    prior = start.date()
    store.record_trading_days(
        (
            _calendar().model_copy(
                update={"cal_date": prior, "previous_trade_date": at(20).date()}
            ),
            _calendar().model_copy(update={"cal_date": at(22).date(), "is_open": False}),
            _calendar().model_copy(update={"cal_date": at(23).date(), "is_open": False}),
        )
    )
    store.record_daily_limits(
        (
            _limit().model_copy(
                update={
                    "trade_date": prior,
                    "received_at": at(21, 9, 30),
                }
            ),
        )
    )
    store.record_daily_bars(
        (
            _daily().model_copy(
                update={
                    "trade_date": prior,
                    "received_at": at(21, 15, 20),
                }
            ),
        )
    )
    store.record_minute_batch(_minute_batch(trade_date=prior))
    plan = request().schedule.entries[0].version.snapshot
    boundary = LoopEndBoundary.resolve(
        started_at=start,
        submitted_at=at(24),
        end_date=at(23).date(),
    )
    value = LoopDatasetRequest(
        scope=DatasetScope(
            symbols=(plan.symbol,),
            start=prior,
            end=at(23).date(),
            warmup_start=prior,
            historical_profile=PROFILE,
        ),
        schedule=LoopSchedule(entries=(row(21, value=version(plan=plan, available=at(21, 8))),)),
        boundary=boundary,
    )
    manifest = store.freeze_loop_dataset(value).manifest
    assert manifest.boundary == boundary and manifest.days[-1].state == "CLOSED"
    with store.open_frozen_loop_dataset(manifest) as reader:
        days = tuple(reader)
        assert len(days) == 3 and len(days[0].minutes) == 240
        assert days[-1].minutes == days[-1].daily_bars == days[-1].daily_limits == ()


def test_missing_calendar_and_unverified_partial_profiles_reject(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    assert store.freeze_loop_dataset(request()).blockers == ("LOOP_CALENDAR_MISSING:2026-08-24",)
    with pytest.raises((TypeError, ValueError)):
        store.record_completed_loop_minutes(
            _minute_batch().bars[:5], historical_profile="UNVERIFIED"
        )
    assert store.statistics().minute_artifact_count == 0


def test_complete_day_requires_arrived_official_close_and_rejects_forged_state(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    partial = store.freeze_loop_dataset(request(cutoff=at(24, 15, 0, 12))).manifest
    assert partial.days[0].state == "PARTIAL" and len(partial.days[0].minutes) == 240
    complete = store.freeze_loop_dataset(request(cutoff=at(24, 15, 20))).manifest
    assert complete.days[0].state == "COMPLETE"
    assert LoopDatasetManifest.model_validate_json(complete.model_dump_json()) == complete
    with store.open_frozen_loop_dataset(complete) as reader:
        assert tuple(reader)[0].state == "COMPLETE"
    short = store.freeze_loop_dataset(request()).manifest
    changed = short.days[0].model_copy(update={"state": "COMPLETE"})
    values = short.model_dump(mode="python", exclude={"dataset_hash", "schema_version"})
    values["days"] = (changed,)
    with pytest.raises(ValueError, match="complete"):
        LoopDatasetManifest.build(**values)


def test_missing_and_delayed_limit_remain_explicit(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    store.record_trading_days((_calendar(),))
    store.record_completed_loop_minutes(_minute_batch().bars[:5], historical_profile=PROFILE)
    with pytest.raises(ValueError, match="deterministic 09:30"):
        store.record_daily_limits((_limit().model_copy(update={"received_at": at(24, 10)}),))
    result = store.freeze_loop_dataset(request())
    assert not result.ready and any("LIMIT_NOT_AVAILABLE" in item for item in result.blockers)


def test_initial_minute_warmup_requires_all_five_constituents(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    prior = request().scope.start - timedelta(days=3)
    store.record_trading_days(
        (
            _calendar().model_copy(
                update={"cal_date": prior, "previous_trade_date": prior - timedelta(days=1)}
            ),
            _calendar().model_copy(
                update={"cal_date": prior + timedelta(days=1), "is_open": False}
            ),
            _calendar().model_copy(
                update={"cal_date": prior + timedelta(days=2), "is_open": False}
            ),
            _calendar(),
        )
    )
    store.record_daily_limits((_limit(),))
    bars = _minute_batch(trade_date=prior).bars
    store.record_completed_loop_minutes((bars[-1],), historical_profile=PROFILE)
    store.record_completed_loop_minutes(_minute_batch().bars[:5], historical_profile=PROFILE)
    result = store.freeze_loop_dataset(request(warmup_start=prior))
    assert result.ready and result.manifest.warmup_blockers == (
        "LOOP_INITIAL_MINUTE_WARMUP_INSUFFICIENT:0:1",
    )
    store.record_completed_loop_minutes(bars[-5:], historical_profile=PROFILE)
    assert store.freeze_loop_dataset(request(warmup_start=prior)).manifest.warmup_blockers == ()


def test_available_price_outside_its_known_limit_blocks_selection(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    original = _minute_batch().bars[0]
    bad = original.model_copy(update={"high_fen": 1200, "received_at": at(24, 9, 34)})
    store.record_completed_loop_minutes((bad,), historical_profile=PROFILE)
    result = store.freeze_loop_dataset(request())
    assert not result.ready and any("PRICE_OUTSIDE_DAILY_LIMIT" in b for b in result.blockers)


def test_future_daily_corruption_does_not_change_earlier_selection(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    before = store.freeze_loop_dataset(request()).manifest
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE market_artifact SET content_json = ? WHERE kind = 'DAILY'",
            (_daily().model_copy(update={"close_fen": 1030}).model_dump_json(),),
        )
    assert store.freeze_loop_dataset(request()).manifest == before
    with pytest.raises(RuntimeError):
        store.freeze_loop_dataset(request(cutoff=at(24, 15, 20)))


def test_cancelled_freeze_does_not_publish_partial_catalog(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(BacktestOperationCancelled):
        store.freeze_loop_dataset(request(), cancellation_token=token)
    assert store.list_dataset_summaries(limit=20) == ()


def test_today_is_frozen_as_partial_without_fabricating_official_close(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    result = store.freeze_loop_dataset(request())
    assert result.ready and not result.blockers
    manifest = result.manifest
    assert manifest.schema_version == "monitor-loop-dataset-v1"
    assert manifest.boundary.evidence_cutoff == at(24, 9, 35, 12)
    assert manifest.days[0].state == "PARTIAL"
    assert len(manifest.days[0].minutes) == 5
    assert manifest.days[0].daily == ()
    with store.open_frozen_loop_dataset(manifest) as reader:
        (day,) = reader
        assert len(day.minutes) == 5 and day.daily_bars == ()
        assert day.state == "PARTIAL"
        assert day.minutes[-1].received_at == manifest.boundary.evidence_cutoff


def test_partial_recording_never_grants_legacy_full_day_readiness(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    store.record_trading_days((_calendar(),))
    store.record_daily_limits((_limit(),))
    store.record_completed_loop_minutes(_minute_batch().bars[:5], historical_profile=PROFILE)
    result = store.freeze_loop_dataset(request())
    assert result.ready
    assert not store.freeze_dataset(_scope()).ready
    assert store.list_dataset_summaries(limit=20) == ()


def test_latest_closed_minute_not_received_is_a_visible_gap_not_an_earlier_cutoff(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    value = request(cutoff=at(24, 9, 35, 0))
    result = store.freeze_loop_dataset(value)
    assert not result.ready and result.manifest is None
    assert any(
        "MINUTE_NOT_AVAILABLE" in blocker and "09:35" in blocker for blocker in result.blockers
    )
    assert value.boundary.evidence_cutoff == at(24, 9, 35, 0)


def test_missing_interval_blocks_even_if_newer_minutes_exist(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    store.record_trading_days((_calendar(),))
    store.record_daily_limits((_limit(),))
    bars = _minute_batch().bars
    store.record_completed_loop_minutes((bars[0], *bars[2:5]), historical_profile=PROFILE)
    result = store.freeze_loop_dataset(request())
    assert not result.ready
    assert any(
        "MINUTE_NOT_AVAILABLE" in blocker and "09:32" in blocker for blocker in result.blockers
    )


def test_later_heads_and_future_corrections_cannot_change_a_frozen_selection(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    value = request()
    original = store.freeze_loop_dataset(value).manifest
    bar = _minute_batch().bars[0]
    correction = bar.model_copy(update={"close_fen": 1001, "received_at": at(24, 10)})
    store.record_completed_loop_minutes((correction,), historical_profile=PROFILE)
    assert store.freeze_loop_dataset(value).manifest == original
    with store.open_frozen_loop_dataset(original) as reader:
        (day,) = reader
        assert day.minutes[0].close_fen == 1000
    later = store.freeze_loop_dataset(request(cutoff=at(24, 10, 0, 12))).manifest
    assert len([ref for ref in later.days[0].minutes if ref.bar_end == bar.bar_end]) == 2


def test_corrupt_referenced_artifact_fails_closed_instead_of_loading_current_head(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    manifest = store.freeze_loop_dataset(request()).manifest
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE market_minute_artifact SET content_json = ? WHERE artifact_hash = ?",
            ("{}", manifest.days[0].minutes[0].artifact_hash),
        )
    with pytest.raises((RuntimeError, ValueError)):
        with store.open_frozen_loop_dataset(manifest) as reader:
            tuple(reader)


def test_cutoff_selection_does_not_change_existing_manifest_bytes_or_catalog(tmp_path):
    store = BacktestMarketStore(tmp_path / "market.sqlite3")
    _seed_complete(store)
    legacy = store.freeze_dataset(_scope())
    before = store.dataset_manifest(legacy.dataset_hash).model_dump_json()
    catalog = store.list_dataset_summaries(limit=20)
    assert store.freeze_loop_dataset(request()).ready
    assert store.freeze_dataset(_scope()) == legacy
    assert store.dataset_manifest(legacy.dataset_hash).model_dump_json() == before
    assert store.list_dataset_summaries(limit=20) == catalog


def seed_scheduled_market(store, *, successor_daily=True, initial_daily=True):
    store.record_minute_batch(_minute_batch())
    store.record_trading_days((_calendar(),))
    store.record_daily_limits((_limit(),))
    if initial_daily:
        store.record_daily_bars((_daily(),))
    store.record_trading_days((_calendar().model_copy(update={
        "cal_date": at(25).date(), "previous_trade_date": at(24).date(),
    }),))
    store.record_daily_limits((_limit().model_copy(update={
        "trade_date": at(25).date(), "received_at": at(25, 9, 30),
    }),))
    store.record_minute_batch(_minute_batch(trade_date=at(25).date()))
    if successor_daily:
        store.record_daily_bars((_daily().model_copy(update={
            "trade_date": at(25).date(), "received_at": at(25, 15, 20),
        }),))


def test_scheduled_successor_daily_warmup_accumulates_during_run_and_missing_close_blocks(tmp_path):
    from trade_plan_monitor.backtest.loop_dataset import freeze_scheduled_loop_dataset

    store = BacktestMarketStore(tmp_path / "scheduled-market.sqlite")
    seed_scheduled_market(store, successor_daily=False)
    value = scheduled_request()
    missing = freeze_scheduled_loop_dataset(store, value)
    assert not missing.ready and missing.manifest is None
    assert any("OFFICIAL_CLOSE_NOT_AVAILABLE" in reason and "2026-08-25" in reason
               for reason in missing.blockers)
    assert not any("DAILY_WARMUP" in reason for reason in missing.blockers)
    store.record_daily_bars((_daily().model_copy(update={
        "trade_date": at(25).date(), "received_at": at(25, 15, 20),
    }),))
    result = freeze_scheduled_loop_dataset(store, value)
    assert result.ready and result.blockers == ()
    assert result.manifest.requirements.daily_observations == 1
    assert result.manifest.requirements.minute_observations == 1
    assert [binding.version_id for binding in result.manifest.plan_bindings] == [
        "scheduled-24", "scheduled-25",
    ]
    assert [binding.effective_trade_date for binding in result.manifest.plan_bindings] == [
        at(24).date(), at(25).date(),
    ]


def test_scheduled_cutoff_and_later_plans_do_not_change_earlier_manifest_or_v1_bytes(tmp_path):
    from trade_plan_monitor.backtest.loop_dataset import (
        freeze_scheduled_loop_dataset,
        open_frozen_scheduled_loop_dataset,
    )

    store = BacktestMarketStore(tmp_path / "scheduled-market.sqlite")
    seed_scheduled_market(store)
    legacy = store.freeze_loop_dataset(request()).manifest.model_dump_json()
    value = scheduled_request(cutoff=at(24, 9, 35, 12))
    original = freeze_scheduled_loop_dataset(store, value).manifest
    assert original.schema_version == "monitor-loop-dataset-v2"
    assert len(original.plan_bindings) == 1 and not original.requirements.requires_daily
    changed = scheduled_request(cutoff=at(24, 9, 35, 12), future_plan=daily_plan())
    assert freeze_scheduled_loop_dataset(store, changed).manifest == original
    bar = _minute_batch().bars[0]
    store.record_completed_loop_minutes((bar.model_copy(update={
        "close_fen": 1001, "received_at": at(24, 10),
    }),), historical_profile=PROFILE)
    assert freeze_scheduled_loop_dataset(store, value).manifest == original
    with open_frozen_scheduled_loop_dataset(store, original) as reader:
        (day,) = reader
        assert len(day.minutes) == 5 and day.minutes[0].close_fen == 1000
    assert store.freeze_loop_dataset(request()).manifest.model_dump_json() == legacy
    assert store.list_dataset_summaries(limit=20) == ()


@pytest.mark.parametrize("field", ["plan_hash", "version_id", "requirements", "artifact"])
def test_scheduled_manifest_rejects_content_hash_tampering_and_v1_decoder(tmp_path, field):
    from trade_plan_monitor.backtest.loop_dataset import (
        ScheduledLoopDatasetManifest,
        freeze_scheduled_loop_dataset,
    )

    store = BacktestMarketStore(tmp_path / "scheduled-market.sqlite")
    seed_scheduled_market(store)
    manifest = freeze_scheduled_loop_dataset(store, scheduled_request()).manifest
    assert ScheduledLoopDatasetManifest.model_validate_json(manifest.model_dump_json()) == manifest
    with pytest.raises(ValueError):
        LoopDatasetManifest.model_validate_json(manifest.model_dump_json())
    raw = manifest.model_dump(mode="python")
    if field in {"plan_hash", "version_id"}:
        raw["plan_bindings"][1][field] = "f" * 64 if field == "plan_hash" else "forged-version"
    elif field == "requirements":
        raw["requirements"]["daily_observations"] = 2
    else:
        raw["days"][0]["minutes"][0]["artifact_hash"] = "f" * 64
    with pytest.raises(ValueError):
        ScheduledLoopDatasetManifest.model_validate(raw)


def test_scheduled_cancelled_selection_does_not_publish_and_reader_rejects_corruption(tmp_path):
    from trade_plan_monitor.backtest.loop_dataset import (
        freeze_scheduled_loop_dataset,
        open_frozen_scheduled_loop_dataset,
    )

    store = BacktestMarketStore(tmp_path / "scheduled-market.sqlite")
    seed_scheduled_market(store)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(BacktestOperationCancelled):
        freeze_scheduled_loop_dataset(store, scheduled_request(), cancellation_token=token)
    assert store.list_dataset_summaries(limit=20) == ()
    manifest = freeze_scheduled_loop_dataset(store, scheduled_request()).manifest
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE market_minute_artifact SET content_json = ? WHERE artifact_hash = ?",
            ("{}", manifest.days[0].minutes[0].artifact_hash),
        )
    with pytest.raises((RuntimeError, ValueError)):
        with open_frozen_scheduled_loop_dataset(store, manifest) as reader:
            tuple(reader)


def test_scheduled_successor_warmup_excludes_its_later_official_close(tmp_path):
    from trade_plan_monitor.backtest.loop_dataset import freeze_scheduled_loop_dataset

    store = BacktestMarketStore(tmp_path / "scheduled-market.sqlite")
    seed_scheduled_market(store, initial_daily=False)
    result = freeze_scheduled_loop_dataset(store, scheduled_request())
    assert not result.ready
    assert any("DAILY_WARMUP" in reason and "scheduled-25" in reason for reason in result.blockers)


def test_scheduled_successor_minute_warmup_shortage_is_visible_without_extra_gate(tmp_path):
    from trade_plan_monitor.backtest.loop_dataset import freeze_scheduled_loop_dataset

    store = BacktestMarketStore(tmp_path / "scheduled-market.sqlite")
    seed_scheduled_market(store)
    long_window = scheduled_request().schedule.entries[2].version.snapshot
    result = freeze_scheduled_loop_dataset(store, scheduled_request(successor_plan=long_window))
    assert result.ready and not result.blockers
    # One complete prior trading day supplies exactly 48 five-minute bars.
    assert any("scheduled-25" in reason and "48:501" in reason
               for reason in result.manifest.warmup_blockers)
