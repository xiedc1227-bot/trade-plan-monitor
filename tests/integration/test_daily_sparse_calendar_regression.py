"""Sparse certified calendars extend production warmup without truncating evidence."""

from datetime import date, datetime, timedelta

from test_daily_plan_chain import FRIDAY, SH, SYMBOL
from test_daily_production_reevaluation import DailyRecoverySDK, ProductionDailyChain

import trade_plan_monitor.runtime.production as production
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline

HOLIDAY_START = FRIDAY - timedelta(days=750)


class SparseDailyCalendarSDK(DailyRecoverySDK):
    """Fifty synthetic holidays force 750 -> 1500 days through the real provider."""

    holidays = frozenset(
        (HOLIDAY_START + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(70)
        if (HOLIDAY_START + timedelta(days=offset)).weekday() < 5
    )

    @staticmethod
    def _calendar(kwargs):
        frame = DailyRecoverySDK._calendar(kwargs)
        frame.loc[frame.cal_date.isin(SparseDailyCalendarSDK.holidays), "is_open"] = 0
        previous = date.fromisoformat(kwargs["start_date"]) - timedelta(days=1)
        while previous.weekday() > 4:
            previous -= timedelta(days=1)
        for index, row in frame.iterrows():
            frame.at[index, "pretrade_date"] = previous.strftime("%Y%m%d")
            if row.is_open:
                previous = date.fromisoformat(row.cal_date)
        return frame

    def _stock_daily(self, kwargs):
        frame = super()._stock_daily(kwargs)
        return frame.loc[~frame.trade_date.isin(self.holidays)].copy()


def test_production_extends_sparse_calendar_and_keeps_complete_runtime_proof(tmp_path, monkeypatch):
    chain = ProductionDailyChain(
        tmp_path, monkeypatch, sdk_type=SparseDailyCalendarSDK,
        initial_now=datetime(2026, 9, 18, 14, tzinfo=SH),
    )
    assert len(chain.sdk.holidays) == 50
    with chain.client:
        chain.activate()
        state = chain.composition._runtime._run_deadline.__self__
        assert isinstance(state._pipeline, production.ProductionMonitorPipeline)
        chain.now = datetime(2026, 9, 18, 16, tzinfo=SH)
        chain.sdk.calls.clear()
        deadline = MarketDeadline(
            kind=DeadlineKind.OFFICIAL_CLOSE, trade_date=FRIDAY,
            due_at=chain.now, close_attempt=1,
        )
        # Official production dispatch performs calendar fetch, persistence, adapter and evaluation.
        chain.client.portal.call(state.run_deadline, deadline)
        current = chain.current()
        assert current["dataBlockers"] == []
        ordinary = next(r for r in current["risks"] if r["kind"] == "ORDINARY_TECHNICAL")
        assert ordinary["status"] == "PENDING"
        assert current["officialTradeDate"] == str(FRIDAY)

        calendars = [call for name, call in chain.sdk.calls if name == "trade_cal"]
        assert [call["start_date"] for call in calendars] == [
            (FRIDAY - timedelta(days=750)).strftime("%Y%m%d"),
            (FRIDAY - timedelta(days=1500)).strftime("%Y%m%d"),
        ]
        assert all(call["end_date"] == (FRIDAY + timedelta(days=32)).strftime("%Y%m%d")
                   for call in calendars)
        assert 0 < sum(
            row.is_open and date.fromisoformat(row.cal_date) < FRIDAY
            for row in chain.sdk._calendar(calendars[0]).itertuples()
        ) < 500

        with state._pipeline._work() as work:
            persisted = work.references.list_trading_days(
                "SSE", FRIDAY - timedelta(days=1500), FRIDAY + timedelta(days=32),
            )
        assert len(persisted) == 1533
        assert persisted[0].cal_date == FRIDAY - timedelta(days=1500)
        assert persisted[-1].cal_date == FRIDAY + timedelta(days=32)
        assert sum(row.is_open for row in persisted) == 1044

        inputs = state._pipeline.daily_evaluations._current_inputs[SYMBOL]
        assert len(inputs.session_dates) == 1044  # Complete >1000-date runtime proof is accepted.
        assert inputs.session_dates == tuple(row.cal_date for row in persisted if row.is_open)
        assert inputs.series is not None
        assert len(inputs.series.bars) == 500
        assert len(inputs.series.session_dates) == 500  # DailySeries owns only its actual interval.
        assert inputs.series.bars[0].trade_date < FRIDAY - timedelta(days=750)
        assert inputs.series.bars[-1].trade_date == FRIDAY
        assert len(current["dailyEvidence"]["bars"]) == 500
        daily_request = next(call for name, call in chain.sdk.calls if name == "daily")
        assert daily_request["start_date"] == inputs.series.bars[0].trade_date.strftime("%Y%m%d")
        assert daily_request["end_date"] == FRIDAY.strftime("%Y%m%d")
