"""Completed-session recovery targets and exact persisted coverage."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.market_data.sessions import SHANGHAI
from trade_plan_monitor.runtime.recovery_targets import (
    RecoveryPhase,
    RecoveryTarget,
    check_minute_coverage,
    completed_minute_ends,
    derive_recovery_target,
    select_current_day_rows,
)


def stamp(clock: str, day: str = "2026-09-21") -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=SHANGHAI)


def target_at(clock: str):
    return derive_recovery_target(now=stamp(clock), is_open_on=lambda _: True)


def minute(clock: str, day: str = "2026-09-21") -> MinuteBar:
    return MinuteBar(
        symbol="600000.SH", bar_end=stamp(clock, day), received_at=stamp(clock, day),
        open_fen=1000, high_fen=1000, low_fen=1000, close_fen=1000,
        volume_shares=100, amount_yuan=Decimal("1000"),
    )


@pytest.mark.parametrize(
    ("clock", "phase", "cutoff", "count"),
    [
        ("08:00:00", RecoveryPhase.PREOPEN, None, 0),
        ("09:30:59", RecoveryPhase.PREOPEN, None, 0),
        ("09:31:00", RecoveryPhase.INTRADAY, "09:31:00", 1),
        ("10:12:59", RecoveryPhase.INTRADAY, "10:12:00", 42),
        ("11:30:00", RecoveryPhase.LUNCH, "11:30:00", 120),
        ("12:40:00", RecoveryPhase.LUNCH, "11:30:00", 120),
        ("13:00:59", RecoveryPhase.INTRADAY, "11:30:00", 120),
        ("13:01:00", RecoveryPhase.INTRADAY, "13:01:00", 121),
        ("15:00:00", RecoveryPhase.AFTER_CLOSE, "15:00:00", 240),
        ("23:59:59", RecoveryPhase.AFTER_CLOSE, "15:00:00", 240),
    ],
)
def test_target_is_latest_completed_session_minute(clock, phase, cutoff, count):
    target = target_at(clock)
    assert target.phase is phase
    assert target.completed_minute_end == (stamp(cutoff) if cutoff else None)
    assert len(completed_minute_ends(target)) == count


@pytest.mark.parametrize("day", ["2026-09-20", "2026-10-01"])
def test_closed_calendar_uses_explicit_last_completed_day(day):
    previous = date(2026, 9, 18)
    target = derive_recovery_target(
        now=stamp("10:00:00", day), is_open_on=lambda value: value == previous,
        last_completed_trade_date=previous,
    )
    assert target.phase is RecoveryPhase.CLOSED
    assert target.completed_minute_end == stamp("15:00:00", previous.isoformat())
    assert not target.requires_calendar_refresh


def test_unknown_calendar_is_explicit_and_has_no_fabricated_weekday_target():
    target = derive_recovery_target(now=stamp("10:00:00"), is_open_on=lambda _: None)
    assert target.phase is RecoveryPhase.CALENDAR_UNKNOWN
    assert target.completed_minute_end is None
    assert target.requires_calendar_refresh


def test_failed_calendar_lookup_is_unknown():
    def unavailable(_):
        raise OSError("offline")

    assert derive_recovery_target(
        now=stamp("10:00:00"), is_open_on=unavailable,
    ).requires_calendar_refresh


def test_closed_calendar_without_known_previous_day_requires_refresh():
    target = derive_recovery_target(now=stamp("10:00:00"), is_open_on=lambda _: False)
    assert target.phase is RecoveryPhase.CLOSED
    assert target.completed_minute_end is None
    assert target.requires_calendar_refresh


def test_previous_completed_day_cannot_be_today_or_future():
    with pytest.raises(ValueError, match="precede"):
        derive_recovery_target(
            now=stamp("10:00:00"), is_open_on=lambda _: False,
            last_completed_trade_date=date(2026, 9, 21),
        )


@pytest.mark.parametrize("previous_open", [None, False, "open"])
def test_unknown_or_invalid_previous_calendar_does_not_manufacture_close(previous_open):
    target = derive_recovery_target(
        now=stamp("10:00:00", "2026-09-20"),
        is_open_on=lambda day: False if day == date(2026, 9, 20) else previous_open,
        last_completed_trade_date=date(2026, 9, 18),
    )
    assert target.completed_minute_end is None
    assert target.requires_calendar_refresh


def test_invalid_weekend_open_calendar_does_not_create_nonexistent_minutes():
    target = derive_recovery_target(
        now=stamp("10:00:00", "2026-09-20"), is_open_on=lambda _: True,
    )
    assert target.phase is RecoveryPhase.CALENDAR_UNKNOWN
    assert completed_minute_ends(target) == ()


def test_direct_target_cannot_admit_an_uncompleted_cutoff():
    with pytest.raises(ValueError, match="completed"):
        RecoveryTarget(
            observed_at=stamp("09:31:59"), phase=RecoveryPhase.INTRADAY,
            trade_date=date(2026, 9, 21), completed_minute_end=stamp("09:32:00"),
        )


def test_direct_target_requires_matching_date_and_canonical_session_cutoff():
    for cutoff in (stamp("09:31:00", "2026-09-18"), stamp("12:00:00")):
        with pytest.raises(ValueError):
            RecoveryTarget(
                observed_at=stamp("13:31:59"), phase=RecoveryPhase.INTRADAY,
                trade_date=date(2026, 9, 21), completed_minute_end=cutoff,
            )


@pytest.mark.parametrize("persisted", [(), (stamp("09:31:00"),)])
def test_empty_or_partial_persisted_minutes_do_not_establish_coverage(persisted):
    required = (stamp("09:31:00"), stamp("09:32:00"))
    coverage = check_minute_coverage(
        required_ends=required, persisted_ends=persisted, cutoff=stamp("09:32:00"),
    )
    assert not coverage.complete
    assert coverage.missing_ends == tuple(value for value in required if value not in persisted)


def test_future_and_other_date_rows_cannot_substitute_for_missing_identities():
    coverage = check_minute_coverage(
        required_ends=(stamp("09:31:00"), stamp("09:32:00")),
        persisted_ends=(stamp("09:31:00"), stamp("09:33:00"),
                        stamp("09:32:00", "2026-09-18")),
        cutoff=stamp("09:32:00"),
    )
    assert coverage.covered_ends == (stamp("09:31:00"),)
    assert coverage.missing_ends == (stamp("09:32:00"),)


def test_complete_and_empty_requirements_are_explicit():
    required = (stamp("09:31:00"), stamp("09:32:00"))
    assert check_minute_coverage(
        required_ends=required, persisted_ends=required, cutoff=stamp("09:32:00"),
    ).complete
    assert check_minute_coverage(
        required_ends=(), persisted_ends=(), cutoff=stamp("09:30:00"),
    ).complete


def test_required_future_minute_is_rejected():
    with pytest.raises(ValueError, match="cutoff"):
        check_minute_coverage(
            required_ends=(stamp("09:33:00"),), persisted_ends=(),
            cutoff=stamp("09:32:00"),
        )


def test_cross_day_requirements_preserve_the_missing_previous_session():
    previous = stamp("15:00:00", "2026-09-18")
    current = stamp("09:31:00")
    coverage = check_minute_coverage(
        required_ends=(previous, current), persisted_ends=(current,), cutoff=current,
    )
    assert not coverage.complete
    assert coverage.missing_ends == (previous,)


def test_required_minutes_must_be_canonical_unique_and_ordered():
    for values in ((stamp("09:31:00"),) * 2, (stamp("09:32:00"), stamp("09:31:00")),
                   (stamp("12:00:00"),), (stamp("09:31:01"),)):
        with pytest.raises(ValueError):
            check_minute_coverage(
                required_ends=values, persisted_ends=(), cutoff=stamp("15:00:00"),
            )


def test_acquisition_retains_frozen_cutoff_when_provider_returns_newer_rows():
    target = target_at("09:32:30")
    rows = (minute("09:31:00"), minute("09:32:00"), minute("09:33:00"))
    selected = select_current_day_rows(
        rows=rows, symbol="600000.SH", target=target, now=stamp("09:34:00"),
    )
    assert tuple(row.bar_end for row in selected) == (stamp("09:31:00"), stamp("09:32:00"))


@pytest.mark.parametrize("now", [stamp("09:31:00"), stamp("00:00:00", "2026-09-22")])
def test_clock_reversal_and_rollover_force_retarget_before_persistence(now):
    with pytest.raises(ValueError, match="retarget"):
        select_current_day_rows(
            rows=(minute("09:31:00"),), symbol="600000.SH",
            target=target_at("09:32:30"), now=now,
        )


def test_current_day_endpoint_cannot_recover_previous_session():
    target = derive_recovery_target(
        now=stamp("10:00:00", "2026-09-20"),
        is_open_on=lambda value: value == date(2026, 9, 18),
        last_completed_trade_date=date(2026, 9, 18),
    )
    with pytest.raises(ValueError, match="current-day"):
        select_current_day_rows(
            rows=(minute("09:31:00", "2026-09-18"),), symbol="600000.SH",
            target=target, now=stamp("10:00:00", "2026-09-20"),
        )


def test_wrong_symbol_and_conflicting_duplicate_rows_are_rejected():
    row = minute("09:31:00")
    for rows in ((row.model_copy(update={"symbol": "000001.SZ"}),),
                 (row, row.model_copy(update={"volume_shares": 200})),
                 (minute("09:31:00", "2026-09-18"),)):
        with pytest.raises(ValueError):
            select_current_day_rows(
                rows=rows, symbol="600000.SH", target=target_at("09:32:30"),
                now=stamp("09:33:00"),
            )


def test_coverage_and_acquisition_collections_are_bounded():
    with pytest.raises(ValueError, match="240"):
        check_minute_coverage(
            required_ends=(), persisted_ends=(stamp("09:31:00"),) * 241,
            cutoff=stamp("15:00:00"),
        )
    with pytest.raises(ValueError, match="240"):
        select_current_day_rows(
            rows=(minute("09:31:00"),) * 241, symbol="600000.SH",
            target=target_at("15:00:00"), now=stamp("15:01:00"),
        )


def test_target_recomputed_after_clock_reversal_excludes_previously_completed_rows():
    later = target_at("10:00:00")
    earlier = derive_recovery_target(
        now=later.observed_at - timedelta(minutes=10), is_open_on=lambda _: True,
    )
    assert earlier.completed_minute_end == stamp("09:50:00")
    assert stamp("10:00:00") not in completed_minute_ends(earlier)
