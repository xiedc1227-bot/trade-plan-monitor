"""A frozen plan discovers trades through monitoring; fixtures supply only market facts."""

from datetime import timedelta
from decimal import Decimal

import pytest
from tests.unit.test_monitor_loop_input import account, frozen, lot
from tests.unit.test_monitor_loop_schedule import at, calendar, row, version
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.backtest.control import BacktestOperationCancelled, CancellationToken
from trade_plan_monitor.backtest.loop_input import KnownLoopCash, LoopResponsePolicy
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.plan_schedule import LoopSchedule
from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.market_data.daily_data import (
    CertifiedDailyBar,
    DailyExecutionQuote,
    DailySeries,
)
from trade_plan_monitor.market_data.models import DailyLimit, MinuteBar
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs


def cycle_input(*, plan=None, **changes):
    plan = plan or research_plan()
    buy = plan.ordinary_rules[0]
    sell = buy.model_copy(
        update={
            "rule_id": "sell-high",
            "side": "SELL",
            "condition": {
                "type": "MINUTE_CLOSE_IN_RANGE",
                "timeframe_minutes": 5,
                "low_fen": 4001,
                "high_fen": 4500,
                "include_low": True,
                "include_high": True,
            },
        }
    )
    plan = plan.model_copy(update={"ordinary_rules": (buy, sell)})
    opening = account(
        cash=KnownLoopCash(balance_fen=500000),
        lots=(
            lot(),
            lot(
                "opening-tactical",
                bucket="TACTICAL",
                cost_basis_fen=397000,
                acquired_trade_date=at(19).date(),
                sellable_quantity=100,
            ),
        ),
    )
    return frozen(
        **(
            {
                "schedule": LoopSchedule(entries=(row(value=version(plan=plan)),)),
                "initial_account": opening,
            }
            | changes
        )
    )


def frames(*, day=20, end=43, delay=12, up_limit=5000):
    from trade_plan_monitor.backtest.loop_runner import LoopFrame

    history, fives = [], []
    for minute in range(31, end + 1):
        price = 3970 if minute < 38 else 4020
        bar = MinuteBar(
            symbol="601021.SH",
            bar_end=at(day, 9, minute),
            open_fen=price,
            high_fen=price + 10,
            low_fen=price - 10,
            close_fen=price,
            volume_shares=1000,
            amount_yuan=Decimal(price * 10),
            received_at=at(day, 9, minute, delay),
        )
        history.append(bar)
        if minute % 5 == 0:
            fives.append(
                aggregate_five_minute_bar(tuple(history[-5:]), bucket_end=bar.bar_end, is_open=True)
            )
        target = None if not fives else fives[-1].bar_end
        runtime = DailyRuntimeInputs(
            evaluated_at=bar.received_at,
            official_trade_date=None,
            series=None,
            suspended_dates=(),
            data_blockers=(),
            session_dates=tuple(d.cal_date for d in calendar() if d.is_open),
            quote=DailyExecutionQuote(
                symbol=bar.symbol,
                price_fen=price,
                quote_at=bar.bar_end,
                available_at=bar.received_at,
                evaluated_at=bar.received_at,
                tradable=True,
                special_state_verified=True,
                liquidity_available=True,
            ),
            minute_target=target,
            minute_prefix=tuple(
                b
                for b in history
                if target is not None and target - timedelta(minutes=5) < b.bar_end <= target
            ),
            five_minute_bars=tuple(fives),
            trading_calendar=calendar(),
        )
        yield LoopFrame(
            runtime=runtime,
            minute=bar,
            daily_limit=DailyLimit(
                symbol=bar.symbol,
                trade_date=bar.bar_end.date(),
                up_limit_fen=up_limit,
                down_limit_fen=3000,
                received_at=at(day, 8),
            ),
        )


def test_one_plan_discovers_buy_then_sell_and_feedback_without_scripted_trades(tmp_path):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    events = []
    with LoopSession(tmp_path, cycle_input(), calendar()) as session:
        result = LoopRunner(session, emit=events.append).run(frames())
        fills = [e for e in events if e.status == "FILLED"]
        assert [e.receipt.authority_receipt.side for e in fills] == ["BUY", "SELL"]
        # 09:35:12 decision excludes the 09:35–09:36 interval.
        assert [e.minute.bar_end for e in fills] == [at(20, 9, 37), at(20, 9, 42)]
        assert all(e.receipt.authority_receipt.quantity == 100 for e in fills)
        assert result.fills == result.intents == 2 and result.unfilled_intents == 0
        assert session.inventory()["total_qty"] == 200
        assert session.inventory()["sellable_tactical"] == 0
        assert session.account().cash.balance_fen == 503590
        assert session.account().accounting_cost_fen == 798654
        with session.work() as work:
            assert all(
                s["payload"]["state"] == "SIMULATED"
                for s in work.daily.list(symbol=session.plan.symbol, kind="SIGNAL")
            )
        assert result.evaluations == 15  # 13 market frames plus two post-fill refreshes.


@pytest.mark.parametrize("mode", ["OBSERVE_ONLY", "RECORDED_ACTIONS"])
def test_nonautomatic_modes_capture_but_never_generate_trades(tmp_path, mode):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    with LoopSession(
        tmp_path, cycle_input(response=LoopResponsePolicy(mode=mode)), calendar()
    ) as s:
        before = s.account()
        result = LoopRunner(s).run(frames())
        assert result.fills == result.intents == result.attempts == 0
        assert s.account() == before
        assert s.reminders()


def test_delay_and_cutoff_leave_a_visible_unfilled_intent(tmp_path):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    value = cycle_input(
        response=LoopResponsePolicy(mode="FOLLOW_REMINDERS", response_delay_seconds=120)
    )
    with LoopSession(tmp_path, value, calendar()) as s:
        result = LoopRunner(s).run(frames(end=37))
        assert result.fills == result.attempts == 0
        assert result.unfilled_intents == result.intents == 1


def test_price_limit_blocks_whole_fill_then_retries_on_later_eligible_interval(tmp_path):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    events = []
    source = list(frames(end=37, up_limit=3971))
    source += list(frames(end=38))[-1:]
    with LoopSession(tmp_path, cycle_input(), calendar()) as s:
        result = LoopRunner(s, emit=events.append).run(source)
        assert [e.status for e in events] == ["BLOCKED", "FILLED"]
        assert events[0].reason == "LIMIT_UP_LOCKED"
        assert events[0].minute.bar_end == at(20, 9, 37)
        assert result.fills == 1 and s.inventory()["total_qty"] == 300


def test_cash_block_never_consumes_or_repeats_an_interval(tmp_path):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    opening = cycle_input().initial_account.model_copy(
        update={"cash": KnownLoopCash(balance_fen=0)}
    )
    events = []
    source = list(frames(end=37))
    source.append(source[-1])
    with LoopSession(tmp_path, cycle_input(initial_account=opening), calendar()) as s:
        before = s.account()
        result = LoopRunner(s, emit=events.append).run(source)
        assert result.attempts == 1 and result.fills == 0 and result.unfilled_intents == 1
        assert events[0].reason == "LOOP_CASH_INSUFFICIENT"
        assert s.account() == before


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_closed_session_cannot_authorize_a_fill(tmp_path, missing):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    source = list(frames(end=37))
    days = (
        tuple(day for day in calendar() if day.cal_date != at().date())
        if missing
        else tuple(
            day.model_copy(update={"is_open": False}) if day.cal_date == at().date() else day
            for day in calendar()
        )
    )
    source[-1] = source[-1].model_copy(
        update={"runtime": source[-1].runtime.model_copy(update={"trading_calendar": days})}
    )
    events = []
    with LoopSession(tmp_path, cycle_input(), calendar()) as s:
        before = s.account()
        result = LoopRunner(s, emit=events.append).run(source)
        assert result.fills == 0 and result.attempts == 1
        assert events[0].reason == "LOOP_TRADING_DAY_UNVERIFIED"
        assert s.account() == before


@pytest.mark.parametrize("volume", [0, 50])
def test_insufficient_minute_volume_cannot_substitute_a_partial_fill(tmp_path, volume):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    source = list(frames(end=37))
    source[-1] = source[-1].model_copy(update={
        "minute": source[-1].minute.model_copy(update={"volume_shares": volume}),
    })
    events = []
    with LoopSession(tmp_path, cycle_input(), calendar()) as s:
        before = s.account()
        result = LoopRunner(s, emit=events.append).run(source)
        assert result.fills == 0 and result.attempts == 1 and result.unfilled_intents == 1
        assert events[0].reason == (
            "LOOP_MINUTE_NOT_TRADABLE" if volume == 0 else "LOOP_MINUTE_LIQUIDITY_INSUFFICIENT"
        )
        assert s.account() == before


def test_future_quote_binding_and_backwards_frames_are_rejected(tmp_path):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    source = list(frames(end=32))
    wrong = source[-1].runtime.quote.model_copy(update={"price_fen": 3999})
    with pytest.raises(ValueError, match="BINDING"):
        source[-1].model_copy(
            update={"runtime": source[-1].runtime.model_copy(update={"quote": wrong})}
        )
    with LoopSession(tmp_path, cycle_input(), calendar()) as s:
        with pytest.raises(ValueError, match="TIME"):
            LoopRunner(s).run(reversed(source))


def test_cancel_and_bounds_fail_without_an_extra_trade(tmp_path):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    token = CancellationToken()
    token.cancel()
    with LoopSession(tmp_path, cycle_input(), calendar()) as s:
        before = s.account()
        with pytest.raises(BacktestOperationCancelled):
            LoopRunner(s).run(frames(), cancellation_token=token)
        assert s.account() == before
        runner = LoopRunner(s)
        runner.evaluations = s.run_input.limits.max_evaluations
        with pytest.raises(ValueError, match="EVALUATION_LIMIT"):
            runner.run(frames())
        assert s.account() == before


def test_repeated_signal_never_creates_a_zero_time_trade_loop(tmp_path):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    source = list(frames(end=37))
    events = []
    with LoopSession(tmp_path, cycle_input(), calendar()) as s:
        result = LoopRunner(s, emit=events.append).run(source + [source[-1]] * 5)
        assert result.intents == result.fills == result.attempts == 1
        assert len(events) == 1 and s.inventory()["total_qty"] == 300


@pytest.mark.parametrize("after_expiry", [False, True])
def test_new_risk_blocks_pending_buy_and_keeps_its_exit_authority_after_expiry(
    tmp_path, after_expiry
):
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    plan = research_plan()
    risk = unified_payload()["risk_branches"][1]
    risk["condition"] = {
        "type": "DAILY_PRICE_COMPARE",
        "field": "close",
        "offset": 0,
        "comparator": "GT",
        "reference": {
            "mode": "FIXED",
            "value": "4000",
            "unit": "FEN",
            "as_of": str(at(19).date()),
            "source": "Reviewed synthetic risk",
        },
    }
    plan = plan.model_copy(
        update={
            "activation": {
                "mode": "DATE_RANGE",
                "start_date": at(19).date(),
                "end_date": at().date(),
            },
            "risk_branches": (risk,),
            "monitoring": unified_payload()["monitoring"],
        }
    )
    opening = cycle_input().initial_account.model_copy(
        update={
            "lots": (
                lot(acquired_trade_date=at(19).date(), sellable_quantity=100),
                lot(
                    "opening-tactical",
                    bucket="TACTICAL",
                    cost_basis_fen=397000,
                    acquired_trade_date=at(19).date(),
                    sellable_quantity=100,
                ),
            )
        }
    )
    source = list(frames(end=41 if after_expiry else 43, up_limit=3971))
    if after_expiry:
        source += list(frames(day=21, end=33))
    for index, frame in enumerate(source):
        now = frame.runtime.evaluated_at
        revised = now >= at(20, 9, 40, 12)
        available = at(20, 9, 40, 12) if revised else at(19, 16)
        price = Decimal(4020 if revised else 3970)
        bar = CertifiedDailyBar(
            bar_id="revised-daily" if revised else "initial-daily",
            symbol=plan.symbol,
            trade_date=at(19).date(),
            open=price,
            high=price,
            low=price,
            close=price,
            volume_shares=1000,
            official=True,
            provider="synthetic",
            available_at=available,
            received_at=available,
            basis_id="synthetic-qfq",
            adjustment_as_of=at(19).date(),
        )
        series = DailySeries(
            symbol=plan.symbol,
            bars=(bar,),
            basis_id="synthetic-qfq",
            adjustment_as_of=at(19).date(),
            provider="synthetic",
            quote_comparable=True,
            session_dates=(at(19).date(),),
            suspended_dates=(),
            cutoff=now,
        )
        source[index] = frame.model_copy(
            update={
                "runtime": frame.runtime.model_copy(
                    update={
                        "series": series,
                        "official_trade_date": at(19).date(),
                    }
                )
            }
        )
    schedule = LoopSchedule(
        entries=(
            row(
                19,
                value=version(
                    plan=plan,
                    available=at(19, 8),
                    authored=at(18, 18),
                    evidence=at(18, 15),
                ),
            ),
        )
    )
    events = []
    with LoopSession(
        tmp_path, cycle_input(plan=plan, schedule=schedule, initial_account=opening), calendar()
    ) as s:
        result = LoopRunner(s, emit=events.append).run(source)
        fills = [e for e in events if e.status == "FILLED"]
        assert len(fills) == result.fills == 1
        assert fills[0].receipt.authority_receipt.side == "SELL"
        assert fills[0].receipt.authority_receipt.quantity == 200
        assert fills[0].minute.bar_end == (at(21, 9, 31) if after_expiry else at(20, 9, 42))
        assert s.inventory()["total_qty"] == 0
        assert any(e.status in {"BLOCKED", "CLOSED"} and "RISK" in (e.reason or "") for e in events)
        with s.work() as work:
            risks = work.daily.list(symbol=s.plan.symbol, kind="RISK")
            assert len(risks) == 1 and risks[0]["payload"]["status"] == "FULFILLED"
            assert work.plans.get_active(s.plan.symbol).plan_version_id == s.details.id


def test_expired_plan_closes_delayed_ordinary_intent_without_reactivation(tmp_path):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    plan = research_plan().model_copy(
        update={
            "activation": {"mode": "TRADING_DAY", "trading_day": at().date()},
        }
    )
    response = LoopResponsePolicy(mode="FOLLOW_REMINDERS", response_delay_seconds=86400)
    events = []
    with LoopSession(tmp_path, cycle_input(plan=plan, response=response), calendar()) as s:
        result = LoopRunner(s, emit=events.append).run(
            list(frames(end=37)) + list(frames(day=21, end=37))
        )
        assert result.fills == 0 and result.unfilled_intents == 0
        assert [e.status for e in events] == ["CLOSED"]
        assert events[0].reason == "INVALIDATED;OUTSIDE_EXECUTION_SESSION"
        assert s.inventory()["total_qty"] == 200


@pytest.mark.parametrize("bound", ["max_intents", "max_execution_attempts", "max_evaluations"])
def test_finite_cycle_bounds_stop_before_an_extra_account_commit(tmp_path, bound):
    from trade_plan_monitor.backtest.loop_runner import LoopRunner

    value = cycle_input()
    events = []
    with LoopSession(tmp_path, value, calendar()) as s:
        runner = LoopRunner(s, emit=events.append)
        # Inject the boundary in the private participant; frozen limits remain 70000.
        if bound == "max_intents":
            runner.policy.limit = 1
        elif bound == "max_execution_attempts":
            runner.attempts = value.limits.max_execution_attempts - 1
        else:
            runner.evaluations = value.limits.max_evaluations - 7
        source = frames(up_limit=3971 if bound == "max_execution_attempts" else 5000)
        with pytest.raises(ValueError, match="LIMIT_EXCEEDED"):
            runner.run(source)
        fills = [e for e in events if e.status == "FILLED"]
        assert len(fills) == (1 if bound == "max_intents" else 0)
        assert s.inventory()["total_qty"] == (300 if bound == "max_intents" else 200)
