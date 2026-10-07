"""Private replay uses the online monitor and delivery fences without a sink."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from tests.unit.test_monitor_loop_input import frozen
from tests.unit.test_monitor_loop_schedule import at, calendar

from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import Base, TradingCalendar
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork


def inputs():
    from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
    from trade_plan_monitor.market_data.daily_data import DailyExecutionQuote
    from trade_plan_monitor.market_data.models import MinuteBar
    from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs

    now = at(20, 9, 35, 12)
    target = now.replace(second=0)
    prefix = tuple(
        MinuteBar(
            symbol="601021.SH",
            bar_end=target - timedelta(minutes=4 - i),
            open_fen=3970,
            high_fen=3980,
            low_fen=3960,
            close_fen=3970,
            volume_shares=100,
            amount_yuan=Decimal("3970"),
            received_at=now,
        )
        for i in range(5)
    )
    bar = aggregate_five_minute_bar(prefix, bucket_end=target, is_open=True)
    return DailyRuntimeInputs(
        evaluated_at=now,
        official_trade_date=None,
        series=None,
        session_dates=tuple(day.cal_date for day in calendar() if day.is_open),
        suspended_dates=(),
        quote=DailyExecutionQuote(
            symbol="601021.SH",
            price_fen=3970,
            quote_at=target,
            available_at=now,
            evaluated_at=now,
            tradable=True,
            special_state_verified=True,
            liquidity_available=True,
        ),
        data_blockers=(),
        minute_target=target,
        minute_prefix=prefix,
        five_minute_bars=(bar,),
        trading_calendar=calendar(),
    )


def test_private_monitor_captures_valid_reminder_once_without_trading(tmp_path):
    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        before = loop.inventory()
        result = loop.evaluate(inputs())
        assert len(result.event_ids) == 1
        captured = loop.capture(result.event_ids)
        assert captured[0].status == "CAPTURED"
        assert captured[0].event.signal_type == "BUY"
        assert captured[0].execution_candidate
        assert captured[0].cause_revision >= 1
        assert loop.capture(result.event_ids) == captured
        assert loop.reminders() == captured
        assert loop.evaluate(inputs()).duplicate
        assert loop.inventory() == before
        assert before["total_qty"] == 100 and before["sellable_core"] is None


@pytest.mark.parametrize(
    "change", ["quote_age", "minute", "inventory", "activation", "review", "fact"]
)
def test_capture_uses_online_fences_to_suppress_changed_evidence(tmp_path, change):
    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.state.models import ActivePlan

    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        prepared = inputs()
        result = loop.evaluate(prepared)
        if change == "minute":
            loop.set_time(loop.now + timedelta(seconds=1))
        with loop.work() as work:
            if change == "minute":
                work.history.upsert_minutes(
                    (
                        prepared.minute_prefix[0].model_copy(
                            update={"volume_shares": 200, "received_at": loop.now}
                        ),
                    )
                )
            elif change == "activation":
                work.daily.session.get(ActivePlan, loop.plan.symbol).revision += 1
            elif change in {"inventory", "review"}:
                key = (
                    "simulation-position-" + loop.plan.symbol
                    if change == "inventory"
                    else "review-" + loop.details.id
                )
                row = work.daily.get(key)
                payload = (
                    row["payload"]
                    if change == "inventory"
                    else {
                        **row["payload"],
                        "confirmed": False,
                        "review_id": None,
                        "review_revision": 0,
                    }
                )
                work.daily.save(
                    key,
                    kind=row["kind"],
                    symbol=row["symbol"],
                    lineage=row["lineage"],
                    expected_revision=row["revision"],
                    payload=payload,
                )
            elif change == "fact":
                work.daily.save(
                    "new-fact",
                    kind="FACT",
                    symbol=loop.plan.symbol,
                    lineage=loop.plan.plan_id,
                    expected_revision=0,
                    payload={
                        "plan_version_id": loop.details.id,
                        "content_hash": loop.details.content_hash,
                        "kind": "TECHNICAL",
                        "trade_date": str(loop.now.date()),
                        "signal_id": None,
                        "evidence": "Reviewed completed minute pattern changed",
                        "verified": True,
                        "verified_at": loop.now.isoformat(),
                        "available_at": loop.now.isoformat(),
                        "official_evidence": None,
                    },
                )
            work.commit()
        captured = loop.capture(
            result.event_ids,
            at=loop.now + timedelta(minutes=5) if change == "quote_age" else loop.now,
        )
        assert captured[0].status == "SUPPRESSED"
        assert not captured[0].execution_candidate
        assert loop.inventory()["total_qty"] == 100


def test_reminder_identity_is_repeatable_across_single_plan_dataset_revisions(tmp_path):
    from trade_plan_monitor.backtest.loop_session import LoopSession

    first = frozen()
    later = first.model_copy(update={"dataset_hash": "4" * 64})
    assert first.run_id != later.run_id
    outputs = []
    for index, frozen_input in enumerate((first, first, later)):
        with LoopSession(tmp_path / str(index), frozen_input, calendar()) as loop:
            result = loop.evaluate(inputs())
            outputs.append(loop.capture(result.event_ids)[0].model_dump_json())
    assert outputs[0] == outputs[1] == outputs[2]


def test_pure_technical_alert_never_becomes_execution_candidate(tmp_path):
    from tests.unit.test_monitor_loop_input import account
    from tests.unit.test_monitor_loop_schedule import row, version
    from tests.unit.test_unified_replay_input import research_plan

    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.backtest.plan_schedule import LoopSchedule

    plan = research_plan().model_copy(
        update={
            "ordinary_rules": (),
            "alert_rules": (
                {
                    "kind": "RISK_ALERT",
                    "rule_id": "minute-alert",
                    "condition": {
                        "type": "MINUTE_CLOSE_BELOW",
                        "timeframe_minutes": 5,
                        "price_fen": 4000,
                    },
                    "confirmation": {"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
                },
            ),
        }
    )
    run_input = frozen(
        schedule=LoopSchedule(entries=(row(value=version(plan=plan)),)),
        initial_account=account(inventory_known=False, lots=()),
    )
    with LoopSession(tmp_path, run_input, calendar()) as loop:
        result = loop.evaluate(inputs())
        captured = loop.capture(result.event_ids)
        assert len(captured) == 1 and captured[0].status == "CAPTURED"
        assert captured[0].event.signal_type == "REMINDER"
        assert captured[0].event.quantity is None
        assert not captured[0].execution_candidate
        assert not loop.inventory()["known"]
        with loop.work() as work:
            assert work.daily.list(symbol=plan.symbol, kind="SIGNAL") == ()
            assert work.daily.list(symbol=plan.symbol, kind="SIMULATION") == ()


def test_capture_overflow_and_late_failure_roll_back_without_partial_receipts(tmp_path):
    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.backtest.reminder_capture import ReminderCapture

    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        result = loop.evaluate(inputs())
        with pytest.raises(ValueError, match="LOOP_REMINDER_NOT_FOUND"):
            loop.capture((*result.event_ids, str(loop.identity("missing"))))
        assert loop.reminders() == ()
        with pytest.raises(RuntimeError, match="injected after capture"):
            with loop.work() as work:
                capture = ReminderCapture(work, limit=1)
                from uuid import UUID

                event = work.alerts.get(UUID(result.event_ids[0]))
                capture.capture(event, loop.now)
                # Same receipt is idempotent even when the finite bound is reached.
                assert capture.capture(event, loop.now).sequence == 1
                another = event.model_copy(update={"event_id": loop.identity("another")})
                with pytest.raises(ValueError, match="LOOP_REMINDER_LIMIT_EXCEEDED"):
                    capture.capture(another, loop.now)
                raise RuntimeError("injected after capture")
        assert loop.reminders() == ()
        assert loop.capture(result.event_ids)[0].sequence == 1
        assert loop.reminders(after_sequence=1) == ()
        for options in ({"limit": 501}, {"after_sequence": -1}, {"limit": True}):
            with pytest.raises(ValueError, match="invalid reminder page"):
                loop.reminders(**options)


def test_private_loop_never_loads_provider_or_live_sink(tmp_path, monkeypatch):
    import builtins
    import socket

    original_import = builtins.__import__
    forbidden = (
        "trade_plan_monitor.market_data.provider",
        "trade_plan_monitor.market_data.historical_provider",
        "trade_plan_monitor.notifications.channels",
        "trade_plan_monitor.web",
        "trade_plan_monitor.ai.providers",
    )

    def guarded_import(name, *args, **kwargs):
        if name.startswith(forbidden):
            raise AssertionError("unexpected live dependency: " + name)
        return original_import(name, *args, **kwargs)

    def no_network(*args, **kwargs):
        raise AssertionError("unexpected network call")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(socket, "create_connection", no_network)
    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        result = loop.evaluate(inputs())
        assert loop.capture(result.event_ids)[0].status == "CAPTURED"


def test_private_session_rejects_existing_database_and_out_of_interval_time(tmp_path):
    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(tmp_path, frozen(), calendar()) as loop:
        for instant in (at(19), at(28)):
            with pytest.raises(ValueError, match="LOOP_TIME_OUTSIDE_FROZEN_INTERVAL"):
                loop.set_time(instant)
        loop.set_time(at(20, 9, 40))
        with pytest.raises(ValueError, match="LOOP_TIME_OUTSIDE_FROZEN_INTERVAL"):
            loop.evaluate(inputs())
    with pytest.raises(ValueError, match="FRESH_PRIVATE_DATABASE"):
        LoopSession(tmp_path, frozen(), calendar())


@pytest.mark.parametrize("sellable", [None, 0, 100])
def test_shared_monitor_requires_known_sellable_inventory_for_sell_reminder(tmp_path, sellable):
    from tests.unit.test_monitor_loop_input import account, lot
    from tests.unit.test_monitor_loop_schedule import row, version
    from tests.unit.test_unified_replay_input import research_plan

    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.backtest.plan_schedule import LoopSchedule

    original = research_plan()
    plan = original.model_copy(
        update={"ordinary_rules": (original.ordinary_rules[0].model_copy(update={"side": "SELL"}),)}
    )
    opening = account(
        lots=(
            lot(
                bucket="TACTICAL",
                sellable_quantity=sellable,
                evidence="Reviewed tactical opening lot; acquisition date is unknown.",
            ),
        )
    )
    run_input = frozen(
        schedule=LoopSchedule(entries=(row(value=version(plan=plan)),)), initial_account=opening
    )
    with LoopSession(tmp_path, run_input, calendar()) as loop:
        result = loop.evaluate(inputs())
        assert len(result.event_ids) == (1 if sellable == 100 else 0)
        if result.event_ids:
            captured = loop.capture(result.event_ids)[0]
            assert captured.event.signal_type == "SELL" and captured.execution_candidate
        assert loop.inventory()["total_qty"] == 100


@pytest.mark.parametrize("sellable", [None, 0, 100])
def test_opening_lot_keeps_unknown_acquisition_and_explicit_availability(tmp_path, sellable):
    engine = create_sqlite_engine(tmp_path / "opening.sqlite")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        with SqlAlchemyUnitOfWork(factory, clock=lambda: at()) as work:
            work.daily.session.add_all([TradingCalendar(**day.model_dump()) for day in calendar()])
            row = work.daily.save(
                "simulation-position-601021.SH",
                kind="POSITION",
                symbol="601021.SH",
                lineage="601021.SH",
                expected_revision=0,
                payload={
                    "simulation_version": "daily-simulation-v1",
                    "initialized_at": at().isoformat(),
                    "initial_core_qty": 100,
                    "initial_tactical_qty": 0,
                    "batches": [
                        {
                            "origin": "monitor-loop-opening-v1",
                            "id": "reviewed-opening",
                            "bucket": "CORE",
                            "quantity": 100,
                            "acquired_trade_date": None,
                            "observed_trade_date": str(at().date()),
                            "sellable_quantity": sellable,
                        }
                    ],
                },
            )
            accounting = DailyAccounting(work.daily)
            assert accounting.snapshot("601021.SH", at().date())["sellable_core"] == sellable
            assert accounting.snapshot("601021.SH", date(2026, 8, 21))["sellable_core"] == sellable
            if sellable == 100:
                after = accounting.simulate(
                    symbol="601021.SH",
                    identity="sale",
                    side="SELL",
                    quantities={"CORE": 100},
                    expected_revision=row["revision"],
                    now=at(20, 10),
                )
                assert after["payload"]["batches"] == []
            else:
                with pytest.raises(ValueError, match="SETTLED_QUANTITY_INSUFFICIENT"):
                    accounting.simulate(
                        symbol="601021.SH",
                        identity="sale",
                        side="SELL",
                        quantities={"CORE": 100},
                        expected_revision=row["revision"],
                        now=at(20, 10),
                    )
            assert row["payload"]["batches"][0]["acquired_trade_date"] is None
    finally:
        engine.dispose()
