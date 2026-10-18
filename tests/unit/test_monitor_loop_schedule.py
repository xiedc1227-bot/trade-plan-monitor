"""Independent time and calendar expectations for the new loop contract."""

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.backtest.plan_schedule import (
    LoopEndBoundary,
    LoopPlanReview,
    LoopPlanVersion,
    LoopSchedule,
    LoopScheduleEntry,
)
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256, plan_sha256
from trade_plan_monitor.market_data.models import TradingDay


def at(day=20, hour=9, minute=0, second=0):
    return datetime(2026, 8, day, hour, minute, second, tzinfo=SHANGHAI)


def version(key="p1", *, plan=None, available=None, authored=None, evidence=None):
    plan = plan or research_plan()
    return LoopPlanVersion(
        version_id=key,
        plan_hash=plan_sha256(plan),
        snapshot=plan,
        source_hashes=("1" * 64,),
        evidence_hash="2" * 64,
        authored_at=authored or at(19, 18),
        available_at=available or at(20, 8),
        information_cutoff=evidence or at(19, 15),
        review=LoopPlanReview(
            content_hash=daily_plan_content_sha256(plan),
            reviewed_at=at(26, 18),
            confirmed=True,
            source_hashes=("1" * 64,),
            evidence_hash="2" * 64,
            evidence="Offline reviewed fixture; retrospective provenance stays explicit.",
        ),
    )


def row(day=20, *, value=None):
    return LoopScheduleEntry(effective_trade_date=date(2026, 8, day), version=value or version())


@pytest.mark.parametrize(
    "second", [row(), row(21), row(21, value=version("p2", available=at(21, 0)))]
)
def test_single_plan_contract_rejects_every_second_entry(second):
    with pytest.raises(ValidationError):
        LoopSchedule(entries=(row(), second))


def calendar():
    return tuple(
        TradingDay(
            exchange="SSE",
            cal_date=date(2026, 8, day),
            is_open=day not in (22, 23),
            previous_trade_date=date(2026, 8, previous),
        )
        for day, previous in ((19, 18), (20, 19), (21, 20), (22, 21), (23, 21), (24, 21))
    )


@pytest.mark.parametrize("requested", [None, date(2026, 8, 24)])
def test_today_default_or_explicit_freezes_the_submission_instant(requested):
    # The UTC day is still August 23. No host clock or timezone may choose the date.
    submitted = datetime(2026, 8, 23, 16, 5, tzinfo=UTC)
    frozen = LoopEndBoundary.resolve(started_at=at(), submitted_at=submitted, end_date=requested)
    assert frozen.resolved_end_date == date(2026, 8, 24)
    assert frozen.evidence_cutoff == at(24, 0, 5)
    assert frozen.origin == ("DEFAULTED" if requested is None else "EXPLICIT")
    assert LoopEndBoundary.model_validate_json(frozen.model_dump_json()) == frozen
    # Rereading after midnight uses only persisted values.
    assert frozen.model_copy().evidence_cutoff == at(24, 0, 5)


def test_past_holiday_end_remains_inclusive_without_shifting_to_a_session():
    frozen = LoopEndBoundary.resolve(
        started_at=at(),
        submitted_at=at(24, 10),
        end_date=date(2026, 8, 23),
    )
    assert frozen.resolved_end_date == date(2026, 8, 23)
    assert frozen.evidence_cutoff == at(23, 23, 59, 59).replace(microsecond=999999)


@pytest.mark.parametrize("end", [date(2026, 8, 19), date(2026, 8, 25)])
def test_before_start_and_future_end_are_rejected(end):
    with pytest.raises(ValueError):
        LoopEndBoundary.resolve(started_at=at(), submitted_at=at(24), end_date=end)


def test_resolution_rejects_naive_clock_future_start_and_forged_frozen_cutoff():
    for submitted in (at(24).replace(tzinfo=None), at(19)):
        with pytest.raises(ValueError):
            LoopEndBoundary.resolve(started_at=at(), submitted_at=submitted)
    frozen = LoopEndBoundary.resolve(started_at=at(), submitted_at=at(24))
    for update in (
        {"evidence_cutoff": at(24) + timedelta(seconds=1)},
        {"resolved_end_date": date(2026, 8, 23)},
        {"origin": "EXPLICIT"},
    ):
        with pytest.raises(ValidationError):
            frozen.model_copy(update=update)


def test_single_plan_carries_across_days_with_the_same_activation():
    first = version()
    schedule = LoopSchedule(entries=(row(value=first),))
    schedule.preflight(calendar(), started_at=at(), evidence_cutoff=at(24, 15))
    initial = schedule.select(at())
    assert initial.version == first
    assert initial.continued is False
    assert schedule.select(at(21, 0)).version == first
    carried = schedule.select(at(24, 12))
    assert carried.version == first
    assert carried.activated_at == initial.activated_at == at(20, 8)
    assert carried.authority_id == initial.authority_id
    assert carried.effective_trade_date == date(2026, 8, 20)
    assert carried.continued is True


def test_intraday_first_plan_never_becomes_visible_before_availability():
    first = version(available=at(20, 10, 15))
    schedule = LoopSchedule(entries=(row(value=first),))
    assert schedule.select(at(20, 10)) is None
    assert schedule.select(at(20, 10, 15)).activated_at == at(20, 10, 15)
    with pytest.raises(ValueError, match="uncovered"):
        schedule.preflight(calendar(), started_at=at(), evidence_cutoff=at(24))
    schedule.preflight(calendar(), started_at=at(20, 10, 15), evidence_cutoff=at(24))


def test_single_plan_cannot_be_backdated_before_its_availability_day():
    with pytest.raises(ValidationError, match="availability"):
        LoopSchedule(entries=(row(value=version(available=at(21, 10))),))


def test_single_plan_rejects_replacements_and_other_symbols():
    changed = research_plan().model_copy(update={"name": "Changed immutable binding"})
    with pytest.raises(ValidationError):
        LoopSchedule(entries=(row(), row(21, value=version(plan=changed))))
    other = research_plan().model_copy(update={"symbol": "002240.SZ", "market": "SZSE"})
    with pytest.raises(ValidationError):
        LoopSchedule(entries=(row(), row(21, value=version("p2", plan=other))))


def test_calendar_preflight_rejects_closed_unknown_duplicate_and_uncovered_dates():
    for day in (22, 25):
        schedule = LoopSchedule(entries=(row(day, value=version(available=at(day, 0))),))
        with pytest.raises(ValueError):
            schedule.preflight(calendar(), started_at=at(day), evidence_cutoff=at(26))
    schedule = LoopSchedule(entries=(row(),))
    with pytest.raises(ValueError):
        schedule.preflight(calendar() + (calendar()[1],), started_at=at(), evidence_cutoff=at(24))
    with pytest.raises(ValueError, match="uncovered"):
        schedule.preflight(calendar(), started_at=at(19), evidence_cutoff=at(24))


def test_single_plan_does_not_extend_expired_activation():
    expired = research_plan().model_copy(
        update={
            "activation": {
                "mode": "DATE_RANGE",
                "start_date": date(2026, 8, 21),
                "end_date": date(2026, 8, 21),
            },
        }
    )
    schedule = LoopSchedule(entries=(row(21, value=version(plan=expired, available=at(21, 0))),))
    assert schedule.select(at(21)).version.snapshot == expired
    assert schedule.select(at(24)) is None
    with pytest.raises(ValueError, match="activation"):
        LoopSchedule(entries=(row(value=version(plan=expired)),))


def test_single_plan_rejects_second_entries_on_copy_and_serialized_input():
    original = LoopSchedule(entries=(row(),))
    with pytest.raises(ValidationError):
        original.model_copy(update={"entries": (row(), row(21))})
    payload = original.model_dump(mode="json")
    payload["entries"].append(row(21).model_dump(mode="json"))
    with pytest.raises(ValidationError):
        LoopSchedule.model_validate(payload)
    assert LoopSchedule.model_validate_json(original.model_dump_json()) == original


def test_review_hashes_offsets_and_information_cutoffs_are_validated():
    good = version()
    for update in (
        {"plan_hash": "0" * 64},
        {"review": good.review.model_copy(update={"content_hash": "0" * 64})},
        {"available_at": at().replace(tzinfo=UTC)},
        {"information_cutoff": at(21)},
        {"source_hashes": ("1" * 64, "1" * 64)},
        {"source_hashes": ("3" * 64,)},
        {"evidence_hash": "3" * 64},
    ):
        with pytest.raises(ValidationError):
            good.model_copy(update=update)
    retrospective = version(authored=at(25, 18))
    assert retrospective.retrospective is True
    assert good.retrospective is False


def test_authoring_date_only_is_preserved_without_an_invented_timestamp():
    original = version()
    dated = original.model_copy(update={"authored_at": None, "authored_date": date(2026, 8, 19)})
    assert dated.authored_at is None
    assert dated.retrospective is False
    later = dated.model_copy(update={"authored_date": date(2026, 8, 25)})
    assert later.retrospective is True
    unknown = dated.model_copy(update={"authored_date": None})
    assert unknown.authored_at is unknown.authored_date is None
    assert unknown.retrospective is False
    with pytest.raises(ValidationError):
        original.model_copy(update={"authored_date": date(2026, 8, 25)})


def test_post_close_plan_never_authorizes_an_earlier_session():
    value = version(authored=at(20, 18), evidence=at(20, 15), available=at(21, 0))
    schedule = LoopSchedule(entries=(row(21, value=value),))
    assert schedule.select(at(20, 15)) is None
    assert schedule.select(at(21, 0)).version == value


def test_single_plan_requires_one_entry_and_keeps_evidence_bindings_independent():
    with pytest.raises(ValidationError):
        LoopSchedule(entries=())
    first = version()
    hashes = ("1" * 64, "3" * 64)
    reviewed = first.model_copy(update={
        "source_hashes": hashes,
        "review": first.review.model_copy(update={"source_hashes": hashes}),
    })
    assert LoopSchedule(entries=(row(value=reviewed),)).select(at()).version == reviewed


def scheduled_row(day=20, *, value=None):
    from trade_plan_monitor.backtest.plan_schedule import (
        ScheduledPlanVersion,
        ScheduledScheduleEntry,
    )

    value = value or version()
    return ScheduledScheduleEntry(
        effective_trade_date=date(2026, 8, day),
        version=ScheduledPlanVersion.model_validate(value.model_dump()),
    )


def continuity_schedule():
    import json
    from pathlib import Path

    from trade_plan_monitor.backtest.plan_schedule import ScheduledLoopSchedule
    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    data = json.loads((Path(__file__).parents[1] / "fixtures" /
                       "monitor_loop_continuity.json").read_text(encoding="utf-8"))
    rows = []
    for item in data["sources"]:
        plan = UnifiedTradePlan.model_validate_json(json.dumps(item["snapshot"]))
        value = version(item["version_id"], plan=plan,
                        authored=datetime.fromisoformat(item["authored_at"]),
                        available=datetime.fromisoformat(item["available_at"]),
                        evidence=datetime.fromisoformat(item["information_cutoff"]))
        value = value.model_copy(update={
            "source_hashes": (item["source_hash"],),
            "review": value.review.model_copy(update={"source_hashes": (item["source_hash"],)}),
        })
        day = date.fromisoformat(item["effective_trade_date"]).day
        rows.append(scheduled_row(day, value=value))
    return ScheduledLoopSchedule(entries=tuple(rows))


def test_scheduled_four_version_selection_canonical_order_and_same_version_continuation():
    schedule = continuity_schedule()
    reversed_schedule = schedule.model_copy(update={"entries": tuple(reversed(schedule.entries))})
    assert reversed_schedule == schedule
    assert [schedule.select(at(day, 10)).version.version_id for day in (20, 21, 24, 25)] == [
        "p1", "p2", "p3", "p4",
    ]
    repeat = schedule.model_copy(update={"entries": (
        schedule.entries[0], scheduled_row(21, value=schedule.entries[0].version),
    )})
    first, carried = repeat.select(at()), repeat.select(at(24))
    assert carried.version == first.version
    assert carried.effective_trade_date == first.effective_trade_date == date(2026, 8, 20)
    assert carried.activated_at == first.activated_at and carried.continued
    assert carried.authority_id == first.authority_id


def test_scheduled_replacement_expiry_does_not_restore_an_older_still_valid_plan():
    from trade_plan_monitor.backtest.plan_schedule import ScheduledLoopSchedule

    expired = research_plan().model_copy(update={"activation": {
        "mode": "TRADING_DAY", "trading_day": date(2026, 8, 21),
    }})
    schedule = ScheduledLoopSchedule(entries=(scheduled_row(), scheduled_row(
        21, value=version("p2", plan=expired, available=at(21, 0)),
    )))
    assert schedule.select(at(21)).version.version_id == "p2"
    assert schedule.select(at(24)) is None


def test_scheduled_rejects_duplicate_days_conflicting_version_ids_symbols_and_oversize():
    from trade_plan_monitor.backtest.plan_schedule import ScheduledLoopSchedule

    first = scheduled_row()
    changed = research_plan().model_copy(update={"name": "Other immutable content"})
    other = research_plan().model_copy(update={"symbol": "002240.SZ", "market": "SZSE"})
    for entries in ((), (first, first),
                    (first, scheduled_row(21, value=version(plan=changed))),
                    (first, scheduled_row(21, value=version("p2", plan=other)))):
        with pytest.raises(ValidationError):
            ScheduledLoopSchedule(entries=entries)
    rows = tuple(first.model_copy(update={"effective_trade_date": date(2026, 8, 20) +
                                         timedelta(days=i)}) for i in range(257))
    assert len(ScheduledLoopSchedule(entries=rows[:256]).entries) == 256
    with pytest.raises(ValidationError):
        ScheduledLoopSchedule(entries=rows)


def test_scheduled_first_intraday_and_successor_opening_availability_are_distinct():
    from trade_plan_monitor.backtest.plan_schedule import ScheduledLoopSchedule

    first = scheduled_row(value=version(available=at(20, 10, 15)))
    schedule = ScheduledLoopSchedule(entries=(first,))
    assert schedule.select(at(20, 10)) is None
    assert schedule.select(at(20, 10, 15)).activated_at == at(20, 10, 15)
    second = scheduled_row(21, value=version("p2", available=at(21, 9, 30)))
    schedule = ScheduledLoopSchedule(entries=(first, second))
    assert schedule.select(at(21, 9, 30)).version == second.version
    late = scheduled_row(21, value=version("p2", available=at(21, 9, 30, 1)))
    with pytest.raises(ValidationError):
        ScheduledLoopSchedule(entries=(first, late))


def test_scheduled_preflight_limits_calendar_requirements_to_run_and_rejects_uncovered_start():
    from trade_plan_monitor.backtest.plan_schedule import ScheduledLoopSchedule

    schedule = continuity_schedule()
    schedule.preflight(calendar(), started_at=at(), evidence_cutoff=at(24, 15))
    with pytest.raises(ValueError):  # p4 is now relevant but its calendar day is missing.
        schedule.preflight(calendar(), started_at=at(), evidence_cutoff=at(25, 15))
    with pytest.raises(ValueError):
        schedule.preflight(calendar(), started_at=at(19), evidence_cutoff=at(24, 15))
    closed = ScheduledLoopSchedule(entries=(scheduled_row(), scheduled_row(
        22, value=version("p2", available=at(21, 18)),
    )))
    with pytest.raises(ValueError):
        closed.preflight(calendar(), started_at=at(), evidence_cutoff=at(24, 15))
