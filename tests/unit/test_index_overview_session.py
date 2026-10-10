"""Exchange phase and completed display target are separate facts."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.web.market_index_overview import resolve_market_session

ZONE = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 10, 9)


@pytest.mark.parametrize(
    "hour,minute,second,phase,target",
    [
        (9, 29, 0, "PREOPEN", "2026-10-08T15:00:00+08:00"),
        (9, 30, 0, "OPEN", None),
        (9, 35, 11, "OPEN", None),
        (9, 35, 12, "OPEN", "2026-10-09T09:35:00+08:00"),
        (11, 30, 0, "BREAK", "2026-10-09T11:30:00+08:00"),
        (13, 0, 0, "OPEN", "2026-10-09T11:30:00+08:00"),
        (15, 0, 0, "CLOSED", "2026-10-09T15:00:00+08:00"),
        (17, 0, 0, "CLOSED", "2026-10-09T15:00:00+08:00"),
    ],
)
def test_phase_uses_trusted_calendar_and_target_remains_session_final(
    hour, minute, second, phase, target
):
    now = datetime.combine(DAY, time(hour, minute, second), ZONE)
    view = resolve_market_session(
        now, is_open=True, previous_open_date=date(2026, 10, 8), stored_date=None
    )
    assert view.phase == phase
    assert (view.expected_bucket_at.isoformat() if view.expected_bucket_at else None) == target
    assert view.display_trade_date == (date(2026, 10, 8) if phase == "PREOPEN" else DAY)


def test_unknown_calendar_never_asserts_closed_or_current():
    view = resolve_market_session(
        datetime.combine(DAY, time(17), ZONE),
        is_open=None,
        previous_open_date=None,
        stored_date=date(2026, 10, 8),
    )
    assert view.phase == "UNKNOWN"
    assert view.calendar_status == "UNKNOWN"
    assert view.expected_bucket_at is None
    assert view.display_trade_date == date(2026, 10, 8)


@pytest.mark.parametrize("day,hour", [(date(2026, 10, 10), 10), (date(2026, 10, 11), 0)])
def test_nontrading_and_midnight_show_explicit_previous_trade_date(day, hour):
    view = resolve_market_session(
        datetime.combine(day, time(hour), ZONE),
        is_open=False,
        previous_open_date=DAY,
        stored_date=DAY,
    )
    assert view.phase == "CLOSED"
    assert view.session_date == day
    assert view.display_trade_date == DAY
    assert view.expected_bucket_at == datetime.combine(DAY, time(15), ZONE)
