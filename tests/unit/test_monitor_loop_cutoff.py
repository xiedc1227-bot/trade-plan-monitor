"""Independent closed-interval and single-snapshot requirements for ML-T16."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.integration.test_backtest_market_store import PROFILE, SYMBOL, TRADE_DATE
from tests.unit.test_monitor_loop_schedule import at, row, version
from tests.unit.test_unified_plan_domain import unified_payload
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.loop_dataset import (
    LoopDatasetRequest,
    closed_minute_ends,
    loop_dataset_requirements,
)
from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary, LoopSchedule
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.domain.unified_plan_models import MinuteVolumeToMeanGte, UnifiedTradePlan


def request(*, cutoff=None, warmup_start=TRADE_DATE, plan=None):
    cutoff = cutoff or at(24, 9, 35, 12)
    plan = plan or research_plan().model_copy(update={"symbol": SYMBOL})
    schedule = LoopSchedule(entries=(row(24, value=version(available=at(24, 8), plan=plan)),))
    boundary = LoopEndBoundary.resolve(started_at=at(24, 9), submitted_at=cutoff)
    return LoopDatasetRequest(
        scope=DatasetScope(
            symbols=(SYMBOL,),
            start=TRADE_DATE,
            end=boundary.resolved_end_date,
            warmup_start=warmup_start,
            historical_profile=PROFILE,
        ),
        schedule=schedule,
        boundary=boundary,
    )


def daily_plan():
    raw = research_plan().model_dump(mode="python")
    raw.update(symbol=SYMBOL, monitoring=unified_payload()["monitoring"])
    raw["ordinary_rules"][0].update(
        condition={
            "type": "DAILY_PRICE_IN_RANGE",
            "field": "close",
            "offset": 0,
            "range": {"low_fen": 900, "high_fen": 1100, "include_low": True, "include_high": True},
        },
        confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
        execution_window="NEXT_EXCHANGE_SESSION_ONLY",
    )
    return UnifiedTradePlan.model_validate(raw)


def test_daily_requirements_use_the_plan_warmup_independently_of_minute_windows():
    result = loop_dataset_requirements(daily_plan())
    assert result.requires_daily and result.daily_observations == 1
    assert not result.requires_minutes and result.minute_observations == 0


@pytest.mark.parametrize(
    "clock,count",
    [
        ((9, 30, 59), 0),
        ((9, 35, 0), 5),
        ((11, 30, 12), 120),
        ((12, 30, 0), 120),
        ((13, 0, 59), 120),
        ((15, 0, 12), 240),
    ],
)
def test_only_closed_minutes_are_required_including_lunch_and_close(clock, count):
    cutoff = datetime(2026, 8, 24, *clock, tzinfo=SHANGHAI)
    ends = closed_minute_ends(TRADE_DATE, cutoff, is_open=True)
    assert len(ends) == count
    assert all(end <= cutoff and end.second == 0 for end in ends)


def test_holiday_has_no_fabricated_price_interval():
    assert closed_minute_ends(date(2026, 8, 23), at(24), is_open=False) == ()


def test_request_rejects_second_symbol_and_unbound_date_scope_on_copy():
    value = request()
    with pytest.raises(ValidationError):
        value.model_copy(
            update={"scope": value.scope.model_copy(update={"symbols": (SYMBOL, "002240.SZ")})}
        )
    with pytest.raises(ValidationError):
        value.model_copy(
            update={"scope": value.scope.model_copy(update={"end": TRADE_DATE + timedelta(days=1)})}
        )


def test_requirements_come_from_only_the_frozen_complete_plan():
    requirements = loop_dataset_requirements(request().schedule.entries[0].version.snapshot)
    assert requirements.daily_observations == 0
    assert requirements.minute_observations == 1
    assert requirements.requires_minutes
    assert not requirements.requires_daily


def test_full_supported_minute_window_is_not_narrowed_by_dataset_requirements():
    plan = research_plan().model_copy(update={"symbol": SYMBOL})
    condition = MinuteVolumeToMeanGte(
        type="MINUTE_VOLUME_TO_MEAN_GTE",
        timeframe_minutes=5,
        window_bars=500,
        minimum_ratio=Decimal("1.5"),
        history_scope="CONTIGUOUS_TRADING_BARS",
    )
    rule = plan.ordinary_rules[0].model_copy(update={"condition": condition})
    plan = plan.model_copy(update={"ordinary_rules": (rule,)})
    assert loop_dataset_requirements(plan).minute_observations == 501
