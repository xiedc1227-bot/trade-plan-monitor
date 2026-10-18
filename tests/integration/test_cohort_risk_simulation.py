"""Synthetic reviewed cohorts use the production risk, inventory and money chain."""

import json
from datetime import date
from decimal import Decimal

from tests.integration.test_monitor_loop_reminders import inputs
from tests.unit.test_daily_plan import synthetic_plan_payload
from tests.unit.test_monitor_loop_input import account, frozen, lot
from tests.unit.test_monitor_loop_schedule import at, calendar, row, version
from tests.unit.test_unified_replay_input import research_plan

from trade_plan_monitor.backtest.loop_input import KnownLoopCash, ScheduledLoopInput
from trade_plan_monitor.backtest.loop_session import LoopSession
from trade_plan_monitor.backtest.plan_schedule import (
    LoopSchedule,
    ScheduledLoopSchedule,
    ScheduledPlanVersion,
    ScheduledScheduleEntry,
)
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.daily_data import CertifiedDailyBar, DailySeries
from trade_plan_monitor.market_data.models import TradingDay
from trade_plan_monitor.runtime.daily_service import DailyRuntimeInputs
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.simulation import SimulationCommand


def _plan(*, new_stop=False):
    payload = research_plan().model_dump(mode="json")
    ordinary = synthetic_plan_payload()["risk_branches"][0]
    old = {
        **ordinary,
        "condition": None,
        "rule_id": "old-holding-protection",
        "risk_line_fen": 3818,
        "risk_comparison": "LT",
        "holding_scope": {"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-08-21"},
    }
    payload["risk_branches"] = [old]
    if new_stop:
        payload["risk_branches"].append({
            **old,
            "rule_id": "new-holding-protection",
            "risk_line_fen": 3600,
            "holding_scope": {"mode": "FROM_TRADE_DATE", "trade_date": "2026-08-21"},
        })
    return UnifiedTradePlan.model_validate_json(json.dumps(payload))


def _run_input(*, new_stop=False):
    plan = _plan(new_stop=new_stop)
    opening = account(
        cash=KnownLoopCash(balance_fen=500000),
        lots=(lot(
            "old-opening-tactical",
            bucket="TACTICAL",
            cost_basis_fen=301050,
            sellable_quantity=100,
            evidence="Synthetic reviewed old holding, 100 shares, acquisition date unknown.",
        ),),
    )
    return frozen(
        initial_account=opening,
        schedule=LoopSchedule(entries=(row(value=version(plan=plan)),)),
    )


def _daily_inputs(day, *, closes, minute=False, market_calendar=None, suspended=()):
    template = inputs()
    market_calendar = calendar() if market_calendar is None else market_calendar
    sessions = tuple(day.cal_date for day in market_calendar if day.is_open)
    now = at(day, 9, 35, 12) if minute else at(day, 16)
    shift = now - template.evaluated_at
    bars = tuple(CertifiedDailyBar(
        bar_id=f"synthetic-risk-close-{trade_day}",
        symbol="601021.SH",
        trade_date=date(2026, 8, trade_day),
        open=Decimal(price), high=Decimal(price + 20), low=Decimal(price - 20),
        close=Decimal(price), volume_shares=1000, official=True, provider="offline",
        basis_id="synthetic-reviewed-qfq", adjustment_as_of=date(2026, 8, closes[-1][0]),
        received_at=at(trade_day, 16), available_at=at(trade_day, 16),
    ) for trade_day, price in closes)
    series = DailySeries(
        symbol="601021.SH", bars=bars, basis_id="synthetic-reviewed-qfq",
        adjustment_as_of=bars[-1].trade_date, provider="offline", quote_comparable=True,
        session_dates=sessions, suspended_dates=suspended, cutoff=now,
    )
    return DailyRuntimeInputs(
        evaluated_at=now, official_trade_date=None, series=series,
        session_dates=sessions, suspended_dates=suspended, data_blockers=(),
        quote=template.quote.model_copy(update={
            "quote_at": now, "available_at": now, "evaluated_at": now,
        }),
        trading_calendar=market_calendar,
        **({
            "minute_target": template.minute_target + shift,
            "minute_prefix": tuple(bar.model_copy(update={
                "bar_end": bar.bar_end + shift, "received_at": bar.received_at + shift,
            }) for bar in template.minute_prefix),
            "five_minute_bars": tuple(bar.model_copy(update={
                "bar_end": bar.bar_end + shift,
            }) for bar in template.five_minute_bars),
        } if minute else {}),
    )


def _command(loop, cause, quantity):
    return SimulationCommand(
        plan_version_id=loop.identity("version"),
        cause_id=cause.get("signal_id", cause.get("cause_id")),
        expected_cause_revision=cause.get("revision", cause.get("cause_revision")),
        expected_inventory_revision=loop.inventory()["revision"],
        quantity=quantity,
    )


def _buy_new_while_old_protection_is_pending(loop):
    loop.evaluate(_daily_inputs(20, closes=((20, 3700),)))
    offered = loop.evaluate(_daily_inputs(21, closes=((20, 3700),), minute=True))
    with loop.work() as work:
        old = next(row["payload"] for row in work.daily.list(
            symbol=loop.plan.symbol, kind="RISK"
        ) if row["payload"]["rule_id"] == "old-holding-protection")
    assert old["status"] == "PENDING"
    signal = offered.snapshot["signals"][0]
    assert signal["executable_qty"] == 100
    assert "HIGHER_PRIORITY_RISK" not in signal["blockers"]
    return loop.execute(_command(loop, signal, 100), request_key="new-cohort-buy")


def test_pending_old_holding_protection_allows_new_plan_buy_and_records_plan_origin(tmp_path):
    with LoopSession(tmp_path, _run_input(), calendar()) as loop:
        buy = _buy_new_while_old_protection_is_pending(loop)

        assert buy.authority_receipt.side == "BUY"
        assert loop.inventory()["tactical_qty"] == 200
        assert loop.inventory()["sellable_tactical"] == 100
        new = next(item for item in buy.account.lots if item.lot_key != "old-opening-tactical")
        assert new.acquired_trade_date == date(2026, 8, 21)
        assert new.plan_version_id == loop.details.id
        with loop.work() as work:
            batches = DailyAccounting(work.daily).lots(loop.plan.symbol, loop.now.date())
        assert next(b for b in batches if b["id"] == new.lot_key)["plan_version_id"] == (
            loop.details.id
        )


def test_risk_sale_releases_only_old_cost_and_fulfills_with_new_holdings_remaining(tmp_path):
    with LoopSession(tmp_path, _run_input(), calendar()) as loop:
        buy = _buy_new_while_old_protection_is_pending(loop)
        new = next(item for item in buy.account.lots if item.lot_key != "old-opening-tactical")
        assert new.cost_basis_fen == 397604
        loop.evaluate(_daily_inputs(21, closes=((20, 3700), (21, 3700))))
        ready = loop.evaluate(_daily_inputs(24, closes=((20, 3700), (21, 3700)), minute=True))
        action = ready.snapshot["risk_action"]
        assert action["lot_allocations"] == [{
            "id": "old-opening-tactical", "bucket": "TACTICAL", "quantity": 100,
        }]
        assert (action["core_qty"], action["tactical_qty"]) == (0, 100)

        sale = loop.execute(_command(loop, action, 100), request_key="old-cohort-risk-sale")

        assert sale.released_cost_fen == 301050
        assert sale.account.lots == (new,)
        assert sale.account.accounting_cost_fen == 397604
        assert sale.account.realized_pnl_fen == 95147
        assert loop.inventory()["tactical_qty"] == 100
        with loop.work() as work:
            risk = work.daily.get(action["cause_id"])["payload"]
            remaining = DailyAccounting(work.daily).lots(loop.plan.symbol, loop.now.date())
        assert risk["status"] == "FULFILLED"
        assert [(item["id"], item["quantity"]) for item in remaining] == [(new.lot_key, 100)]
        after = loop.evaluate(_daily_inputs(24, closes=((20, 3700), (21, 3700)), minute=True))
        assert after.snapshot["risk_action"]["status"] == "NONE"


def test_same_kind_old_and_new_risk_rules_confirm_independently_at_reviewed_prices(tmp_path):
    with LoopSession(tmp_path, _run_input(new_stop=True), calendar()) as loop:
        _buy_new_while_old_protection_is_pending(loop)
        loop.evaluate(_daily_inputs(21, closes=((20, 3700), (21, 3500))))
        with loop.work() as work:
            before = {row["payload"]["rule_id"]: row for row in work.daily.list(
                symbol=loop.plan.symbol, kind="RISK"
            )}
        old, new = before["old-holding-protection"], before["new-holding-protection"]
        assert old["id"] != new["id"]
        assert old["payload"]["status"] == "CONFIRMED"
        assert old["payload"]["risk_line_fen"] == 3818
        assert new["payload"]["status"] == "PENDING"
        assert new["payload"]["risk_line_fen"] == 3600
        assert new["payload"]["breach_trade_date"] == "2026-08-21"

        loop.evaluate(_daily_inputs(24, closes=((21, 3500), (24, 3550))))

        with loop.work() as work:
            current = {row["payload"]["rule_id"]: row["payload"] for row in work.daily.list(
                symbol=loop.plan.symbol, kind="RISK"
            )}
        assert current["old-holding-protection"]["confirmed_trade_date"] == "2026-08-21"
        assert current["new-holding-protection"]["status"] == "CONFIRMED"
        assert current["new-holding-protection"]["confirmed_trade_date"] == "2026-08-24"


def test_pending_risk_survives_scheduled_narrowing_suspension_and_later_omitted_scope(tmp_path):
    scoped = _plan()
    unscoped = scoped.model_copy(update={"risk_branches": (
        scoped.risk_branches[0].model_copy(update={"holding_scope": None}),
    )})
    later = unscoped.model_copy(update={"name": "Synthetic later unrelated plan update"})
    entries = []
    for day, plan in ((20, unscoped), (21, scoped), (24, later)):
        reviewed = version(
            f"cohort-version-{day}", plan=plan, available=at(day, 8),
            authored=at(day, 7), evidence=at(day, 7),
        )
        entries.append(ScheduledScheduleEntry(
            effective_trade_date=date(2026, 8, day),
            version=ScheduledPlanVersion.model_validate(reviewed.model_dump()),
        ))
    base = _run_input()
    run_input = ScheduledLoopInput(
        schedule=ScheduledLoopSchedule(entries=tuple(entries)),
        initial_account=base.initial_account, boundary=base.boundary,
        dataset_hash=base.dataset_hash, response=base.response, costs=base.costs,
    )
    market_calendar = (*calendar(), TradingDay(
        exchange="SSE", cal_date=date(2026, 8, 25), is_open=True,
        previous_trade_date=date(2026, 8, 24),
    ))
    suspended = (date(2026, 8, 21),)

    def evaluate(day, closes, *, minute=False):
        return loop.evaluate(_daily_inputs(
            day, closes=closes, minute=minute, market_calendar=market_calendar,
            suspended=suspended,
        ))

    def risk():
        with loop.work() as work:
            rows = work.daily.list(symbol=loop.plan.symbol, kind="RISK")
        assert len(rows) == 1
        return rows[0]

    with LoopSession(tmp_path, run_input, market_calendar) as loop:
        evaluate(20, ((20, 3700),))
        original = risk()
        assert original["payload"]["status"] == "PENDING"
        assert original["payload"]["breach_trade_date"] == "2026-08-20"

        evaluate(21, ((20, 3700),))
        narrowed = risk()
        assert narrowed["id"] == original["id"]
        assert narrowed["payload"]["holding_scope"] == {
            "mode": "BEFORE_TRADE_DATE", "trade_date": "2026-08-21",
        }
        assert narrowed["payload"]["breach_trade_date"] == "2026-08-20"
        assert narrowed["payload"]["suspension_confirmation_policy"] == "RESUME_FIRST_CLOSE"
        assert narrowed["payload"]["status"] == "PENDING"

        ready = evaluate(24, ((20, 3700),), minute=True)
        carried = risk()
        assert loop.selection.version.version_id == "cohort-version-24"
        assert carried["payload"]["holding_scope"] == narrowed["payload"]["holding_scope"]
        assert carried["payload"]["status"] == "PENDING"
        signal = ready.snapshot["signals"][0]
        assert signal["executable_qty"] == 100
        buy = loop.execute(_command(loop, signal, 100), request_key="resume-new-buy")
        new = next(item for item in buy.account.lots if item.lot_key != "old-opening-tactical")

        evaluate(24, ((20, 3700), (24, 3700)))
        confirmed = risk()["payload"]
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["breach_trade_date"] == "2026-08-20"
        assert confirmed["confirmed_trade_date"] == "2026-08-24"
        assert confirmed["earliest_execution_date"] == "2026-08-25"
        assert confirmed["holding_scope"] == narrowed["payload"]["holding_scope"]

        action = evaluate(25, ((20, 3700), (24, 3700)), minute=True).snapshot["risk_action"]
        assert action["lot_allocations"] == [{
            "id": "old-opening-tactical", "bucket": "TACTICAL", "quantity": 100,
        }]
        sale = loop.execute(_command(loop, action, 100), request_key="switched-old-risk-sale")
        assert sale.account.lots == (new,)
        assert sale.released_cost_fen == 301050
        assert risk()["payload"]["status"] == "FULFILLED"
