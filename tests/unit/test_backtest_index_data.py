from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_plan_monitor.backtest.index_data import (
    IndexArtifactMembership,
    MarketIndexReplaySeries,
    build_backtest_index_requirement,
    build_reference_market_result,
    market_index_data_hash,
)
from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import migrate_trade_plan_to_schema_v2
from trade_plan_monitor.market_data.sessions import expected_minute_ends
from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexInterval,
    MarketIndexSourceKind,
)
from trade_plan_monitor.market_index.snapshots import build_market_index_snapshot

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _base_plan() -> TradePlan:
    document = Path("config/plans/003043.SZ.sample.yaml").read_text(encoding="utf-8")
    return migrate_trade_plan_to_schema_v2(load_plan_yaml(document), new_version=2)


def _plan_with_conditions(*conditions: dict[str, object]) -> TradePlan:
    payload = _base_plan().model_dump(mode="python", round_trip=True)
    payload["entry"] = {
        "condition": {
            "type": "ALL",
            "conditions": list(conditions),
        }
    }
    return TradePlan.model_validate(payload)


def _bar(
    *,
    at: datetime,
    interval: MarketIndexInterval,
    close: str,
    revision: int = 1,
) -> MarketIndexBar:
    points = Decimal(close)
    return MarketIndexBar(
        index_code=MarketIndexCode.SHENZHEN_COMPONENT,
        interval=interval,
        bar_at=at,
        open_points=points,
        high_points=points,
        low_points=points,
        close_points=points,
        volume=Decimal("0"),
        amount=Decimal("0"),
        observed_at=at,
        source_kind=(
            MarketIndexSourceKind.OFFICIAL
            if interval is MarketIndexInterval.OFFICIAL_DAILY
            else MarketIndexSourceKind.PROVISIONAL
        ),
        provider_revision=revision,
    )


def test_plan_specific_requirement_uses_exact_paths_and_combined_maximum() -> None:
    plan = _plan_with_conditions(
        {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 20,
        },
        {
            "type": "INDEX_MA_NON_DECREASING",
            "index_role": "BOARD_REFERENCE",
            "period": 50,
            "lookback": 10,
        },
        {
            "type": "INDEX_RETURN_GTE",
            "index_role": "BOARD_REFERENCE",
            "window": "OFFICIAL_OPEN_DAYS",
            "window_size": 15,
            "threshold_ratio": "0.01",
        },
        {
            "type": "INDEX_RETURN_LTE",
            "index_role": "BOARD_REFERENCE",
            "window": "FIVE_MINUTE_BUCKETS",
            "window_size": 7,
            "threshold_ratio": "-0.02",
        },
    )

    requirement = build_backtest_index_requirement(plan)

    assert requirement.required is True
    assert requirement.required_five_minute_count == 8
    assert requirement.required_official_day_count == 60
    assert requirement.condition_paths == (
        "entry.condition.conditions[0]",
        "entry.condition.conditions[1]",
        "entry.condition.conditions[2]",
        "entry.condition.conditions[3]",
    )
    assert len(requirement.index_requirement_hash) == 64


def test_official_only_requirement_does_not_invent_five_minute_warmup() -> None:
    plan = _plan_with_conditions(
        {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 20,
        },
        {
            "type": "INDEX_RETURN_GTE",
            "index_role": "BOARD_REFERENCE",
            "window": "OFFICIAL_OPEN_DAYS",
            "window_size": 5,
            "threshold_ratio": "0",
        },
    )

    requirement = build_backtest_index_requirement(plan)

    assert requirement.required_five_minute_count == 0
    assert requirement.required_official_day_count == 20


def test_requirement_hash_changes_with_threshold_and_path() -> None:
    condition = {
        "type": "INDEX_RETURN_GTE",
        "index_role": "BOARD_REFERENCE",
        "window": "OFFICIAL_OPEN_DAYS",
        "window_size": 5,
        "threshold_ratio": "0.01",
    }
    first = build_backtest_index_requirement(_plan_with_conditions(condition))
    changed = dict(condition, threshold_ratio="0.02")
    second = build_backtest_index_requirement(_plan_with_conditions(changed))

    payload = _base_plan().model_dump(mode="python", round_trip=True)
    payload["blockers"] = {"condition": condition}
    third = build_backtest_index_requirement(TradePlan.model_validate(payload))

    assert first.index_requirement_hash != second.index_requirement_hash
    assert first.index_requirement_hash != third.index_requirement_hash


def test_index_membership_hash_is_order_independent_and_revision_sensitive() -> None:
    first_bar = _bar(
        at=datetime(2026, 8, 31, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        close="100",
    )
    second_bar = _bar(
        at=datetime(2026, 9, 1, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        close="101",
    )
    memberships = (
        IndexArtifactMembership.from_bar(first_bar),
        IndexArtifactMembership.from_bar(second_bar),
    )

    assert market_index_data_hash(memberships) == market_index_data_hash(
        tuple(reversed(memberships))
    )
    corrected = second_bar.model_copy(
        update={
            "high_points": Decimal("102"),
            "close_points": Decimal("102"),
            "provider_revision": 2,
        }
    )
    assert market_index_data_hash(memberships) != market_index_data_hash(
        (memberships[0], IndexArtifactMembership.from_bar(corrected))
    )


def test_replay_series_is_cutoff_safe_and_interns_equal_snapshots() -> None:
    plan = _plan_with_conditions(
        {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
        }
    )
    requirement = build_backtest_index_requirement(plan)
    prior = _bar(
        at=datetime(2026, 8, 31, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        close="100",
    )
    current = _bar(
        at=datetime(2026, 9, 1, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        close="102",
    )
    completed = _bar(
        at=datetime(2026, 9, 1, 14, 55, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.FIVE_MINUTE,
        close="102",
    )
    future = _bar(
        at=datetime(2026, 9, 1, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.FIVE_MINUTE,
        close="999",
    )
    series = MarketIndexReplaySeries(
        index_code=MarketIndexCode.SHENZHEN_COMPONENT,
        bars=(prior, completed, current, future),
        dataset_revision=7,
    )
    cutoff = datetime(2026, 9, 1, 14, 55, tzinfo=SHANGHAI)

    first = series.snapshot(
        decision_cutoff=cutoff,
        requests=requirement.fact_requests,
        observed_no_later_than=cutoff,
    )
    second = series.snapshot(
        decision_cutoff=cutoff,
        requests=requirement.fact_requests,
        observed_no_later_than=cutoff,
    )

    assert first is second
    assert first.latest_completed_five_minute is completed
    assert first.official_daily_bars == (prior,)
    assert all(bar.close_points != Decimal("999") for bar in first.five_minute_bars)


def test_replay_snapshot_matches_live_builder_for_identical_content() -> None:
    plan = _plan_with_conditions(
        {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
        }
    )
    requests = build_backtest_index_requirement(plan).fact_requests
    first_daily = _bar(
        at=datetime(2026, 8, 28, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        close="99",
    )
    prior = _bar(
        at=datetime(2026, 8, 31, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        close="100",
    )
    current = _bar(
        at=datetime(2026, 9, 1, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        close="102",
    )
    completed = _bar(
        at=datetime(2026, 9, 1, 14, 55, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.FIVE_MINUTE,
        close="102",
    )
    cutoff = completed.bar_at
    observed_no_later_than = cutoff + timedelta(minutes=1)
    irrelevant_old_bar = _bar(
        at=datetime(2026, 8, 27, 15, 0, tzinfo=SHANGHAI),
        interval=MarketIndexInterval.OFFICIAL_DAILY,
        close="98",
        revision=9,
    ).model_copy(update={"observed_at": observed_no_later_than})
    expected = build_market_index_snapshot(
        index_code=MarketIndexCode.SHENZHEN_COMPONENT,
        decision_cutoff=cutoff,
        requests=requests,
        five_minute_bars=(completed,),
        official_daily_bars=(first_daily, prior),
        content_revision=1,
        observed_at=cutoff,
        observed_no_later_than=observed_no_later_than,
    )
    replay = MarketIndexReplaySeries(
        index_code=MarketIndexCode.SHENZHEN_COMPONENT,
        bars=(irrelevant_old_bar, first_daily, prior, completed, current),
        dataset_revision=7,
    ).snapshot(
        decision_cutoff=cutoff,
        requests=requests,
        observed_no_later_than=observed_no_later_than,
    )

    assert replay.model_dump_json() == expected.model_dump_json()
    assert replay.snapshot_hash == expected.snapshot_hash


def test_reference_market_coverage_rejects_a_gapped_official_warmup() -> None:
    plan = _plan_with_conditions(
        {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
        }
    )
    event_start = datetime(2026, 9, 2, tzinfo=SHANGHAI).date()
    official_open_dates = (
        datetime(2026, 8, 28, tzinfo=SHANGHAI).date(),
        datetime(2026, 8, 31, tzinfo=SHANGHAI).date(),
        datetime(2026, 9, 1, tzinfo=SHANGHAI).date(),
        event_start,
    )
    official_bars = tuple(
        _bar(
            at=datetime.combine(day, datetime.min.time(), SHANGHAI).replace(hour=15),
            interval=MarketIndexInterval.OFFICIAL_DAILY,
            close="100",
        )
        for day in (official_open_dates[0], official_open_dates[2], event_start)
    )
    event_five_minute = tuple(
        _bar(
            at=bar_at,
            interval=MarketIndexInterval.FIVE_MINUTE,
            close="100",
        )
        for bar_at in expected_minute_ends(event_start, is_open=True)[4::5]
    )

    result = build_reference_market_result(
        plan=plan,
        dataset_hash="a" * 64,
        market_data_hash="b" * 64,
        event_start=event_start,
        dataset_warmup_start=official_open_dates[0],
        official_open_dates=official_open_dates,
        bars=official_bars + event_five_minute,
    )

    assert result.blockers == ("GAPPED_INDEX_OFFICIAL_WARMUP",)
    assert result.coverage_status == "BLOCKED"


def test_reference_market_coverage_rejects_a_gapped_event_bucket() -> None:
    plan = _plan_with_conditions(
        {
            "type": "INDEX_CLOSE_GTE_MA",
            "index_role": "BOARD_REFERENCE",
            "period": 2,
        }
    )
    event_start = datetime(2026, 9, 2, tzinfo=SHANGHAI).date()
    official_open_dates = (
        datetime(2026, 8, 31, tzinfo=SHANGHAI).date(),
        datetime(2026, 9, 1, tzinfo=SHANGHAI).date(),
        event_start,
    )
    official_bars = tuple(
        _bar(
            at=datetime.combine(day, datetime.min.time(), SHANGHAI).replace(hour=15),
            interval=MarketIndexInterval.OFFICIAL_DAILY,
            close="100",
        )
        for day in official_open_dates
    )
    complete_event_buckets = expected_minute_ends(event_start, is_open=True)[4::5]
    event_five_minute = tuple(
        _bar(
            at=bar_at,
            interval=MarketIndexInterval.FIVE_MINUTE,
            close="100",
        )
        for bar_at in complete_event_buckets
        if bar_at != complete_event_buckets[12]
    )

    result = build_reference_market_result(
        plan=plan,
        dataset_hash="a" * 64,
        market_data_hash="b" * 64,
        event_start=event_start,
        dataset_warmup_start=official_open_dates[0],
        official_open_dates=official_open_dates,
        bars=official_bars + event_five_minute,
    )

    assert result.blockers == ("GAPPED_INDEX_FIVE_MINUTE_EVENT",)
    assert result.coverage_status == "BLOCKED"


def test_plan_without_index_leaves_has_no_required_index_coverage() -> None:
    requirement = build_backtest_index_requirement(_base_plan())

    assert requirement.required is False
    assert requirement.condition_paths == ()
    assert requirement.fact_requests == ()
    assert requirement.required_five_minute_count == 0
    assert requirement.required_official_day_count == 0
    assert len(requirement.index_requirement_hash) == 64
