"""Frozen budget facts have explicit provenance, availability and exact lot references."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from tests.unit.test_p3_policy_contract import p3_payload

from trade_plan_monitor.backtest.p3_replay_input import CapitalReplayProgram, FrozenCapitalOpening
from trade_plan_monitor.domain.p3_policy_models import P3TradePlan
from trade_plan_monitor.domain.plan_hash import plan_sha256

NOW = datetime(2026, 10, 26, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def frozen_opening(**changes):
    values = dict(
        source_event_id="opening-once",
        plan_hash=plan_sha256(P3TradePlan.model_validate(p3_payload())),
        symbol="601021.SH",
        provenance="RESEARCH_SCENARIO",
        observed_at=NOW,
        received_at=NOW,
        available_at=NOW,
        order=0,
        confirmed=True,
        source="Explicit synthetic opening declaration",
        excerpt="Current retained cost450001fen",
        reason="Reviewed scenario assumption",
        recorded_event=None,
        lots=(
            dict(
                source_lot_id=None,
                bucket="TACTICAL",
                quantity=400,
                retained_basis_fen=450001,
                reference=dict(kind="OPENING", lot_key="initial-TACTICAL"),
            ),
        ),
    )
    return FrozenCapitalOpening.build(**(values | changes))


def test_explicit_frozen_opening_roundtrips_without_cash_or_private_counters():
    value = frozen_opening()
    assert FrozenCapitalOpening.model_validate_json(value.model_dump_json()) == value
    program = CapitalReplayProgram(opening_events=(value,))
    assert program.provenances == ("RESEARCH_SCENARIO",)
    assert "cash" not in value.model_dump_json()
    assert value.lots[0].reference.lot_key == "initial-TACTICAL"


@pytest.mark.parametrize(
    "change",
    [
        "future_observation",
        "early_availability",
        "recorded_missing",
        "duplicate_lot",
        "negative_cost",
        "unsafe_cost",
        "boolean_cost",
        "unknown_ref",
        "authority",
    ],
)
def test_frozen_source_rejects_ambiguous_cost_and_authority(change):
    raw = frozen_opening().model_dump(mode="python", exclude={"envelope_hash"})
    if change == "future_observation":
        raw["observed_at"] = NOW + timedelta(seconds=1)
    elif change == "early_availability":
        raw["available_at"] = NOW - timedelta(seconds=1)
    elif change == "recorded_missing":
        raw["provenance"] = "RECORDED_LOCAL"
    elif change == "duplicate_lot":
        raw["lots"] = (raw["lots"][0], raw["lots"][0])
    elif change == "unknown_ref":
        raw["lots"][0]["reference"] = dict(kind="CURRENT_BOOK")
    elif change == "authority":
        raw["approval"] = True
    else:
        raw["lots"][0]["retained_basis_fen"] = {
            "negative_cost": -1,
            "unsafe_cost": 9007199254740992,
            "boolean_cost": True,
        }[change]
    with pytest.raises((ValueError, ValidationError)):
        FrozenCapitalOpening.build(**raw)


def test_future_event_order_and_duplicate_source_identity_are_explicit():
    first = frozen_opening()
    later = frozen_opening(source_event_id="later", order=1, available_at=NOW + timedelta(days=1))
    assert CapitalReplayProgram(opening_events=(first, later)).opening_events[1] == later
    for values in (
        (first, first),
        (later, first),
        (first, frozen_opening(order=1, available_at=NOW + timedelta(days=1))),
    ):
        with pytest.raises(ValueError):
            CapitalReplayProgram(opening_events=values)


def capital_loop_input(*, program=None, combined=False):
    from tests.unit.test_monitor_loop_input import costs

    from trade_plan_monitor.backtest.loop_input import (
        LoopAccountInput,
        LoopInitialLot,
        LoopResponsePolicy,
        MonitorLoopInput,
        PositionLimitFunding,
    )
    from trade_plan_monitor.backtest.p3_replay_input import CapitalExceptionReplayProgram
    from trade_plan_monitor.backtest.plan_schedule import (
        LoopEndBoundary,
        LoopPlanReview,
        LoopPlanVersion,
        LoopSchedule,
        LoopScheduleEntry,
    )
    from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256

    plan = P3TradePlan.model_validate(p3_payload(combined=combined))
    version = LoopPlanVersion(version_id="capital-source", plan_hash=plan_sha256(plan),
        snapshot=plan, source_hashes=("a"*64,), evidence_hash="b"*64,
        available_at=NOW, information_cutoff=NOW,
        review=LoopPlanReview(content_hash=daily_plan_content_sha256(plan), reviewed_at=NOW,
            confirmed=True, source_hashes=("a"*64,), evidence_hash="b"*64,
            evidence="Explicit monetary plan scenario review"))
    return MonitorLoopInput(run_formula_version="backtest-run-v10",
        schedule=LoopSchedule(entries=(LoopScheduleEntry(effective_trade_date=NOW.date(),
                                                        version=version),)),
        initial_account=LoopAccountInput(snapshot_at=NOW, inventory_known=True,
            cash=PositionLimitFunding(), opening_mark=None,
            lots=(LoopInitialLot(lot_key="initial-TACTICAL", bucket="TACTICAL", quantity=400,
                cost_basis_fen=None, acquired_trade_date=None, sellable_quantity=None,
                evidence="Explicit opening quantity, costs are separately unknown"),),
            evidence="Explicit position-limit-only funding, no cash invented"),
        boundary=LoopEndBoundary.resolve(started_at=NOW, submitted_at=NOW+timedelta(days=1),
                                         end_date=NOW.date()), dataset_hash="c"*64,
        response=LoopResponsePolicy(mode="OBSERVE_ONLY"), costs=costs(),
        exception_program=CapitalExceptionReplayProgram(),
        capital_program=program or CapitalReplayProgram())


@pytest.mark.parametrize("combined", [False, True])
def test_v10_loop_freezes_unknown_cost_without_fake_max_or_cash(combined, tmp_path):
    from trade_plan_monitor.backtest.loop_input import decode_monitor_loop_input_json
    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.market_data.models import TradingDay

    value = capital_loop_input(combined=combined)
    assert decode_monitor_loop_input_json(value.model_dump_json()) == value
    assert value.initial_account.cash.kind == "POSITION_LIMIT_ONLY"
    assert value.initial_account.accounting_cost_fen is None
    assert "max_qty" not in value.schedule.entries[0].version.snapshot.position.model_dump()
    calendar = (TradingDay(exchange="SSE", cal_date=NOW.date(), is_open=True,
                           previous_trade_date=NOW.date()-timedelta(days=3)),)
    with LoopSession(tmp_path, value, calendar) as session:
        assert session.inventory()["total_qty"] == 400
        assert session.capital.outcomes == []
    for changes in ({"capital_program": None}, {"run_formula_version": "backtest-run-v9"}):
        with pytest.raises(ValueError):
            value.model_copy(update=changes)


def test_future_capital_facts_change_run_input_but_not_earlier_private_authority():
    first = capital_loop_input()
    later = frozen_opening(available_at=NOW+timedelta(hours=1))
    changed = capital_loop_input(program=CapitalReplayProgram(opening_events=(later,)))
    assert changed.run_id != first.run_id
    assert changed.schedule.select(NOW).authority_id == first.schedule.select(NOW).authority_id
