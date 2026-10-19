"""Read-only market requirements derived from exact reviewed plan authority."""

from datetime import datetime, time, timedelta

from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.loop_dataset import (
    LoopDatasetRequest,
    ScheduledLoopDatasetRequest,
    loop_dataset_requirements,
    scheduled_dataset_requirements,
)
from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary
from trade_plan_monitor.backtest.preparation_review import FrozenPreparedCollection
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile


def now():
    return datetime.now(SHANGHAI)


def prepared_dataset_request(market, prepared, *, submitted_at, end_date, expand_missing=False):
    scheduled = isinstance(prepared, FrozenPreparedCollection)
    source = prepared.items[0].source if scheduled else prepared.source
    version = prepared.schedule.entries[0].version
    start = max(source.execution_available_at,
                datetime.combine(source.effective_trade_date, time.min, SHANGHAI))
    if scheduled:
        start = max(start, prepared.account.snapshot_at)
    boundary = LoopEndBoundary.resolve(
        started_at=start, submitted_at=submitted_at, end_date=end_date,
    )
    requirements = (scheduled_dataset_requirements(prepared.schedule, boundary) if scheduled
                    else loop_dataset_requirements(version.snapshot))
    warmup_start = min(start.date(), source.effective_trade_date)
    needed = max(requirements.daily_observations,
                 (max(requirements.minute_observations - 1, 0) + 47) // 48)
    calendar = market.current_trading_day(version.snapshot.market, start.date())
    for _ in range(needed):
        previous = (market.current_trading_day(
            version.snapshot.market, calendar.previous_trade_date,
        ) if calendar is not None else None)
        if previous is None:
            # Missing calendars must not silently reduce the required warm-up.
            if expand_missing:
                warmup_start = min(warmup_start,
                                   start.date() - timedelta(days=min(needed * 2 + 14, 729)))
            break
        if not previous.is_open:
            raise RuntimeError("loop warmup calendar chain is inconsistent")
        warmup_start = min(warmup_start, previous.cal_date)
        calendar = previous
    request_type = ScheduledLoopDatasetRequest if scheduled else LoopDatasetRequest
    return request_type(
        scope=DatasetScope(
            symbols=(version.snapshot.symbol,), start=start.date(),
            end=boundary.resolved_end_date, warmup_start=warmup_start,
            historical_profile=HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1,
        ),
        schedule=prepared.schedule, boundary=boundary,
    )
