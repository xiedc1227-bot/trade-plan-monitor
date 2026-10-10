"""RP-T03: real monitoring discovers trades from the independent synthetic oracle."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from tests.unit.test_monitor_loop_input import scheduled_input

from trade_plan_monitor.backtest.loop_input import LoopAccountInput, LoopCosts, LoopResponsePolicy
from trade_plan_monitor.backtest.loop_runner import LoopFrame, LoopRunner
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.plan_schedule import LoopAccountContext
from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
from trade_plan_monitor.market_data.models import DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs


def continuity_fixture():
    return json.loads((Path(__file__).parents[1] / "fixtures" /
                       "monitor_loop_continuity.json").read_text(encoding="utf-8"))


def continuity_calendar():
    return tuple(TradingDay.model_validate_json(json.dumps(raw))
                 for raw in continuity_fixture()["calendar"])


def continuity_input(*, dependent=False):
    data, value = continuity_fixture(), scheduled_input()
    rows = tuple(row.model_copy(update={"version": row.version.model_copy(update={
        "account_context": LoopAccountContext(
            core_qty=0, tactical_qty=source["stated_quantity"], evidence=source["source_id"],
            dependent_rule_ids=("ordinary-chain",) if dependent and index == 2 else (),
        ),
    })}) for index, (row, source) in enumerate(zip(
        value.schedule.entries, data["sources"], strict=True,
    )))
    return value.model_copy(update={
        "schedule": value.schedule.model_copy(update={"entries": rows}),
        "initial_account": LoopAccountInput.model_validate_json(
            json.dumps(data["opening_account"]),
        ),
        "costs": LoopCosts.model_validate_json(json.dumps(data["costs"])),
        "response": LoopResponsePolicy.model_validate(data["response"]),
    })


def observation(at):
    return LoopFrame(runtime=DailyRuntimeInputs(
        evaluated_at=at, official_trade_date=None, series=None, suspended_dates=(),
        data_blockers=(),
        session_dates=tuple(d.cal_date for d in continuity_calendar() if d.is_open),
        quote=None, trading_calendar=continuity_calendar(),
    ))


def continuity_frames(day):
    data, history, fives = continuity_fixture(), [], []
    limits = {item["trade_date"]: DailyLimit.model_validate_json(json.dumps(item))
              for item in data["daily_limits"]}
    for raw in data["minute_bars"]:
        if raw["bar_end"][:10] != day:
            continue
        bar = MinuteBar.model_validate_json(json.dumps(raw))
        history.append(bar)
        if bar.bar_end.minute % 5 == 0:
            fives.append(aggregate_five_minute_bar(
                tuple(history[-5:]), bucket_end=bar.bar_end, is_open=True,
            ))
        target = fives[-1].bar_end if fives else None
        runtime = observation(bar.received_at).runtime.model_copy(update={
            "quote": DailyExecutionQuote(
                symbol=bar.symbol, price_fen=bar.close_fen, quote_at=bar.bar_end,
                available_at=bar.received_at, evaluated_at=bar.received_at,
                tradable=True, special_state_verified=True, liquidity_available=True,
            ),
            "minute_target": target, "five_minute_bars": tuple(fives),
            "minute_prefix": tuple(b for b in history if target is not None and
                                   target - timedelta(minutes=5) < b.bar_end <= target),
        })
        yield LoopFrame(runtime=runtime, minute=bar, daily_limit=limits[day])


def assert_account(session, expected):
    account, inventory = session.account(), session.inventory()
    assert account.cash.balance_fen == expected["cash_fen"]
    assert inventory["total_qty"] == expected["quantity"]
    assert (inventory["sellable_core"] + inventory["sellable_tactical"]
            == expected["sellable_quantity"])
    assert account.accounting_cost_fen == expected["cost_basis_fen"]
    assert account.paid_fees_fen == expected["paid_fees_fen"]
    assert account.realized_pnl_fen == expected["realized_pnl_fen"]
    assert [(lot.bucket, lot.quantity, str(lot.acquired_trade_date), lot.cost_basis_fen)
            for lot in account.lots] == [
        (lot["bucket"], lot["quantity"], lot["acquired_trade_date"], lot["cost_basis_fen"])
        for lot in expected["lots"]
    ]


def test_four_versions_share_one_actual_ledger_and_obey_t_plus_one(tmp_path):
    data, events = continuity_fixture(), []
    with LoopSession(tmp_path, continuity_input(), continuity_calendar()) as session:
        runner = LoopRunner(session, emit=events.append)
        for boundary in data["expected"]["version_boundaries"]:
            now = datetime.fromisoformat(boundary["at"])
            runner.run((observation(now),))
            assert session.selection.version.version_id == boundary["version_id"]
            assert_account(session, boundary)
            result = runner.run(continuity_frames(now.date().isoformat()))
            if boundary["version_id"] == "p1":
                assert_account(session, data["expected"]["after_buy"])
        assert_account(session, data["expected"]["final_account"])
        fills = [event for event in events if event.status == "FILLED"]
        assert result.fills == len(fills) == 2
        assert [(event.receipt.authority_receipt.side, event.minute.bar_end.isoformat(),
                 event.receipt.settlement.quantity, event.receipt.settlement.fill_price_fen,
                 event.receipt.settlement.total_fees_fen) for event in fills] == [
            (item["side"], item["bar_end"], item["quantity"], item["price_fen"], item["fees_fen"])
            for item in data["expected"]["fills"]
        ]


def test_account_dependent_instruction_is_blocked_without_fabricating_inventory(tmp_path):
    data = continuity_fixture()
    with LoopSession(tmp_path, continuity_input(dependent=True), continuity_calendar()) as session:
        runner = LoopRunner(session)
        for day in ("2026-08-20", "2026-08-21", "2026-08-24"):
            result = runner.run(continuity_frames(day))
        assert result.fills == 1
        assert session.blocked_rule_ids == ("ordinary-chain",)
        assert [(item.bucket, item.stated_qty, item.actual_qty)
                for item in session.context_mismatches] == [("TACTICAL", 200, 100)]
        assert_account(session, data["expected"]["version_boundaries"][2])
        with session.work() as work:
            signals = work.daily.list(symbol=session.plan.symbol, kind="SIGNAL")
            blocked = [row["payload"] for row in signals if
                       "LOOP_ACCOUNT_CONTEXT_INCOMPATIBLE" in row["payload"]["blockers"]]
            assert blocked and all(row["executable_qty"] == 0 for row in blocked)


def test_replacement_closes_pending_ordinary_intent_without_a_fill_minute(tmp_path):
    value = continuity_input()
    value = value.model_copy(update={"response": value.response.model_copy(update={
        "response_delay_seconds": 86_400,
    })})
    with LoopSession(tmp_path, value, continuity_calendar()) as session:
        runner = LoopRunner(session)
        runner.run(continuity_frames("2026-08-20"))
        pending, = runner.policy.pending()
        before = session.account()
        result = runner.run((observation(datetime.fromisoformat("2026-08-21T09:00:00+08:00")),))
        assert pending.status == "CLOSED"
        assert result.fills == result.attempts == result.unfilled_intents == 0
        assert session.account() == before
        assert session.selection.version.version_id == "p2"


def test_same_version_next_day_keeps_authority_consumption_and_account(tmp_path):
    value = continuity_input()
    first, next_row = value.schedule.entries[:2]
    repeated = next_row.model_copy(update={"version": first.version})
    value = value.model_copy(update={"schedule": value.schedule.model_copy(update={
        "entries": (first, repeated),
    })})
    with LoopSession(tmp_path, value, continuity_calendar()) as session:
        runner = LoopRunner(session)
        runner.run(continuity_frames("2026-08-20"))
        before, authority = session.account(), session.selection.authority_id
        with session.work() as work:
            signals = work.daily.list(symbol=session.plan.symbol, kind="SIGNAL")
        result = runner.run(continuity_frames("2026-08-21"))
        assert result.fills == 1 and session.account() == before
        assert session.selection.authority_id == authority
        assert session.inventory()["sellable_tactical"] == 100
        with session.work() as work:
            current = work.daily.list(symbol=session.plan.symbol, kind="SIGNAL")
            assert [(row["id"], row["payload"]["state"]) for row in current] == [
                (row["id"], "SIMULATED") for row in signals
            ]


def test_replacement_retains_real_latched_risk_state_before_successor_evaluation(tmp_path):
    from datetime import date

    from trade_plan_monitor.state.daily_state_models import DailyRiskState

    with LoopSession(tmp_path, continuity_input(), continuity_calendar()) as session:
        LoopRunner(session).run(continuity_frames("2026-08-20"))
        risk = DailyRiskState(
            kind="SEVERE_TECHNICAL", status="CONFIRMED", priority=2,
            target_core_qty=0, target_tactical_qty=100, involves_core=False,
            scope_evidence="Synthetic retained exit obligation", evidence_ids=("synthetic-close",),
            earliest_execution_date=date(2026, 8, 21), blockers=(), risk_id="synthetic-risk",
            confirmed_trade_date=date(2026, 8, 20),
        )
        with session.work() as work:
            work.daily.save("synthetic-risk", kind="RISK", symbol=session.plan.symbol,
                            lineage=session.plan.symbol, expected_revision=0,
                            payload=risk.model_dump(mode="json"))
            work.commit()
        before = session.account()
        transitions = session.advance(datetime.fromisoformat("2026-08-21T09:00:00+08:00"))
        assert any(item.kind == "REPLACED" and item.version_id == "p2" for item in transitions)
        assert session.account() == before
        with session.work() as work:
            assert work.daily.get("synthetic-risk")["payload"] == risk.model_dump(mode="json")


def test_v2_writer_streams_bound_replacement_and_account_discrepancy_events(tmp_path):
    from trade_plan_monitor.backtest.loop_report import LoopReportWriter, ScheduledLoopAuditEvent

    events = []
    with LoopSession(tmp_path, continuity_input(), continuity_calendar()) as session:
        writer = LoopReportWriter(session, sink=events.append)
        runner = LoopRunner(session, report_writer=writer)
        runner.run(frame for day in ("2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25")
                   for frame in continuity_frames(day))
        assert all(type(event) is ScheduledLoopAuditEvent for event in events)
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        for event in events:
            assert ScheduledLoopAuditEvent.model_validate_json(event.model_dump_json()) == event
        replacements = [event for event in events if event.payload.kind == "REPLACED"]
        assert [(event.payload.from_version_id, event.version_id) for event in replacements] == [
            ("p1", "p2"), ("p2", "p3"), ("p3", "p4"),
        ]
        assert [[(item.stated_qty, item.actual_qty) for item in event.payload.context_mismatches]
                for event in replacements] == [[(0, 100)], [(200, 100)], []]
        assert all(event.authority_id == event.payload.authority_id for event in replacements)
        for event in replacements:
            assert event.at <= next(item.at for item in events[event.sequence:]
                                    if item.payload.kind == "EVALUATED")


def test_expired_authority_closes_pending_without_reactivating_the_plan(tmp_path):
    from tests.unit.test_monitor_loop_schedule import scheduled_row, version

    from trade_plan_monitor.backtest.loop_report import LoopReportWriter

    value = continuity_input()
    first = value.schedule.entries[0]
    plan = first.version.snapshot.model_copy(update={"activation": {
        "mode": "TRADING_DAY", "trading_day": first.effective_trade_date,
    }})
    value = value.model_copy(update={
        "schedule": value.schedule.model_copy(update={"entries": (
            scheduled_row(value=version(plan=plan)),
        )}),
        "response": value.response.model_copy(update={"response_delay_seconds": 86_400}),
    })
    events = []
    with LoopSession(tmp_path, value, continuity_calendar()) as session:
        runner = LoopRunner(session, report_writer=LoopReportWriter(session, sink=events.append))
        runner.run((*continuity_frames("2026-08-20"),
                    observation(datetime.fromisoformat("2026-08-21T09:00:00+08:00"))))
        pending, = runner.policy.intents.values()
        assert pending.status == "CLOSED" and session.account().cash.balance_fen == 1_000_000
        ended = [event for event in events if event.payload.kind == "NO_AUTHORITY"]
        assert len(ended) == 1
        assert ended[0].version_id is ended[0].authority_id is None
        assert ended[0].payload.closed_intent_ids == (pending.intent_id,)
        observations = [event for event in events if event.at >= ended[0].at
                        and event.payload.kind in {"EVALUATED", "VALUATION"}]
        assert {event.payload.kind for event in observations} == {"EVALUATED", "VALUATION"}
        assert all(event.version_id is event.authority_id is None for event in observations)


def test_advance_traverses_every_skipped_version_without_resetting_account(tmp_path):
    with LoopSession(tmp_path, continuity_input(), continuity_calendar()) as session:
        LoopRunner(session).run(continuity_frames("2026-08-20"))
        before = session.account()
        transitions = session.advance(datetime.fromisoformat("2026-08-25T09:00:00+08:00"))
        replacements = [item for item in transitions if item.kind == "REPLACED"]
        assert [(item.from_version_id, item.version_id, item.at.isoformat())
                for item in replacements] == [
            ("p1", "p2", "2026-08-21T00:00:00+08:00"),
            ("p2", "p3", "2026-08-24T00:00:00+08:00"),
            ("p3", "p4", "2026-08-25T00:00:00+08:00"),
        ]
        assert session.account() == before
        assert session.selection.version.version_id == "p4"


def test_failed_activation_rolls_back_database_and_memory_then_retries(tmp_path, monkeypatch):
    from trade_plan_monitor.state.repositories import PlanRepository

    with LoopSession(tmp_path, continuity_input(), continuity_calendar()) as session:
        LoopRunner(session).run(continuity_frames("2026-08-20"))
        before = session.account(), session.selection, session.now, session.details
        with session.work() as work:
            active = work.plans.get_active(session.plan.symbol)
            pointer = active.plan_version_id, active.revision
        original = PlanRepository.activate

        def fail_after_activate(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise RuntimeError("synthetic failure after shared activation")

        monkeypatch.setattr(PlanRepository, "activate", fail_after_activate)
        now = datetime.fromisoformat("2026-08-21T09:00:00+08:00")
        with pytest.raises(RuntimeError, match="synthetic failure"):
            session.advance(now)
        assert (session.account(), session.selection, session.now, session.details) == before
        with session.work() as work:
            active = work.plans.get_active(session.plan.symbol)
            assert (active.plan_version_id, active.revision) == pointer
        monkeypatch.setattr(PlanRepository, "activate", original)
        assert any(item.kind == "REPLACED" for item in session.advance(now))
        assert session.account() == before[0]
        assert session.selection.version.version_id == "p2"


def test_distinct_frozen_versions_can_share_original_snapshot_identity(tmp_path):
    from sqlalchemy import select
    from tests.unit.test_monitor_loop_schedule import at, scheduled_row

    from trade_plan_monitor.domain.plan_codec import dump_plan_json
    from trade_plan_monitor.state.models import PlanVersion

    value = continuity_input()
    first = value.schedule.entries[0]
    second = scheduled_row(21, value=first.version.model_copy(update={"version_id": "p2"}))
    value = value.model_copy(update={"schedule": value.schedule.model_copy(update={
        "entries": (first, second),
    })})
    with LoopSession(tmp_path, value, continuity_calendar()) as session:
        before, authority = session.account(), session.selection.authority_id
        transitions = session.advance(at(21))
        assert any(item.kind == "REPLACED" and item.version_id == "p2" for item in transitions)
        assert session.selection.authority_id != authority
        assert session.plan == first.version.snapshot == second.version.snapshot
        assert session.account() == before
        with session.work() as work:
            rows = tuple(work.daily.session.scalars(select(PlanVersion)))
            assert len(rows) == 2
            assert all(row.payload_json == dump_plan_json(first.version.snapshot) for row in rows)
            assert {row.plan_hash for row in rows} == {first.version.plan_hash}
