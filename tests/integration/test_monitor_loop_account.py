"""Money, inventory, consumed causes and receipts share one private transaction."""

import pytest
from tests.integration.test_monitor_loop_reminders import inputs
from tests.unit.test_monitor_loop_input import account, frozen
from tests.unit.test_monitor_loop_schedule import calendar

from trade_plan_monitor.backtest.loop_input import KnownLoopCash, UnknownLoopCash
from trade_plan_monitor.state.simulation import SimulationCommand


def funded():
    return frozen(initial_account=account(cash=KnownLoopCash(balance_fen=500000)))


def command(loop):
    loop.evaluate(inputs())
    with loop.work() as work:
        cause = work.daily.list(symbol=loop.plan.symbol, kind="SIGNAL")[0]
        return SimulationCommand(
            plan_version_id=loop.identity("version"),
            cause_id=cause["id"],
            expected_cause_revision=cause["revision"],
            expected_inventory_revision=loop.inventory()["revision"],
            quantity=100,
        )


def test_funded_buy_preserves_opening_cost_and_commits_all_states_once(tmp_path):
    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(tmp_path, funded(), calendar()) as loop:
        assert loop.account().accounting_cost_fen == 401050
        assert loop.account().paid_fees_fen == 0
        offered = command(loop)
        receipt = loop.execute(offered, request_key="buy-1")
        assert receipt.settlement.fill_price_fen == 3971
        assert receipt.settlement.total_fees_fen == 504
        assert receipt.account.cash.balance_fen == 102396
        assert receipt.account.accounting_cost_fen == 798654
        assert receipt.account.lots[0].cost_basis_fen == 401050
        assert loop.inventory()["total_qty"] == 200
        assert loop.inventory()["sellable_tactical"] == 0
        with loop.work() as work:
            assert work.daily.get(offered.cause_id)["payload"]["state"] == "SIMULATED"
            assert len(work.daily.list(symbol=loop.plan.symbol, kind="SIMULATION")) == 1
        assert loop.execute(offered, request_key="buy-1") == receipt
        assert loop.account() == receipt.account
        with pytest.raises(ValueError, match="LOOP_FILL_REQUEST_CONFLICT"):
            loop.execute(offered.model_copy(update={"quantity": 200}), request_key="buy-1")


@pytest.mark.parametrize(
    "cash", [KnownLoopCash(balance_fen=0), KnownLoopCash(balance_fen=397603), UnknownLoopCash()]
)
def test_missing_or_insufficient_full_quantity_cash_changes_nothing(tmp_path, cash):
    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(tmp_path, frozen(initial_account=account(cash=cash)), calendar()) as loop:
        offered = command(loop)
        before_money, before_inventory = loop.account(), loop.inventory()
        with pytest.raises(ValueError, match="LOOP_CASH_(INSUFFICIENT|UNKNOWN)"):
            loop.execute(offered, request_key="failed-buy")
        assert loop.account() == before_money and loop.inventory() == before_inventory
        with loop.work() as work:
            assert work.daily.get(offered.cause_id)["payload"]["state"] == "READY"
            assert work.daily.list(symbol=loop.plan.symbol, kind="SIMULATION") == ()


def test_failure_after_inventory_mutation_rolls_back_money_signal_receipt_and_audit(
    tmp_path, monkeypatch
):
    from sqlalchemy import select

    from trade_plan_monitor.backtest.loop_account import LoopAccountParticipant
    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.state.models import AuditLog

    with LoopSession(tmp_path, funded(), calendar()) as loop:
        offered = command(loop)
        before_money, before_inventory = loop.account(), loop.inventory()
        with loop.work() as work:
            audit_before = tuple(work.daily.session.scalars(select(AuditLog.id)))
        original_save = LoopAccountParticipant._save

        def fail(*args, **kwargs):
            raise RuntimeError("injected money write failure")

        monkeypatch.setattr(LoopAccountParticipant, "_save", fail)
        with pytest.raises(RuntimeError, match="injected money write failure"):
            loop.execute(offered, request_key="retry-buy")
        assert loop.account() == before_money and loop.inventory() == before_inventory
        with loop.work() as work:
            assert work.daily.get(offered.cause_id)["payload"]["state"] == "READY"
            assert work.daily.list(symbol=loop.plan.symbol, kind="SIMULATION") == ()
            assert tuple(work.daily.session.scalars(select(AuditLog.id))) == audit_before
        monkeypatch.setattr(LoopAccountParticipant, "_save", original_save)
        assert loop.execute(offered, request_key="retry-buy").account.cash.balance_fen == 102396


@pytest.mark.parametrize("basis", [574205, None])
def test_sell_uses_actual_debited_lot_retains_residual_fen_and_unknown_cost(tmp_path, basis):
    from tests.unit.test_monitor_loop_input import lot
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
            lot(),
            lot(
                "tactical",
                bucket="TACTICAL",
                quantity=200,
                sellable_quantity=100,
                cost_basis_fen=basis,
                evidence="Reviewed tactical opening lot and explicit available 100 shares.",
            ),
        )
    )
    run_input = frozen(
        schedule=LoopSchedule(entries=(row(value=version(plan=plan)),)), initial_account=opening
    )
    with LoopSession(tmp_path, run_input, calendar()) as loop:
        receipt = loop.execute(command(loop), request_key="sell-1")
        assert receipt.settlement.fill_price_fen == 3969
        assert receipt.settlement.total_fees_fen == 703
        assert receipt.account.cash.balance_fen == 396197
        assert receipt.account.lots[0].cost_basis_fen == 401050
        tactical = receipt.account.lots[1]
        assert tactical.quantity == 100 and tactical.acquired_trade_date is None
        assert loop.inventory()["total_qty"] == 200
        assert loop.inventory()["sellable_tactical"] == 0
        if basis is None:
            assert receipt.released_cost_fen is None
            assert tactical.cost_basis_fen is None
            assert receipt.account.realized_pnl_fen is None
            assert receipt.account.accounting_cost_fen is None
        else:
            assert receipt.released_cost_fen == 287102
            assert tactical.cost_basis_fen == 287103
            assert receipt.account.realized_pnl_fen == 109095
            assert receipt.account.accounting_cost_fen == 688153


@pytest.mark.parametrize("field", ["expected_inventory_revision", "expected_cause_revision"])
def test_stale_authority_cannot_commit_money_or_inventory(tmp_path, field):
    from trade_plan_monitor.backtest.loop_session import LoopSession
    from trade_plan_monitor.state.repositories import RevisionConflictError

    with LoopSession(tmp_path, funded(), calendar()) as loop:
        offered = command(loop)
        before_money, before_inventory = loop.account(), loop.inventory()
        with pytest.raises(RevisionConflictError):
            loop.execute(offered.model_copy(update={field: 0}), request_key="stale")
        assert loop.account() == before_money and loop.inventory() == before_inventory
        assert loop.execute(offered, request_key="stale").account.cash.balance_fen == 102396


def test_exact_cash_boundary_and_observation_mode(tmp_path):
    from trade_plan_monitor.backtest.loop_input import LoopResponsePolicy
    from trade_plan_monitor.backtest.loop_session import LoopSession

    exact = frozen(initial_account=account(cash=KnownLoopCash(balance_fen=397604)))
    with LoopSession(tmp_path / "exact", exact, calendar()) as loop:
        assert loop.execute(command(loop), request_key="exact").account.cash.balance_fen == 0
    observe = funded().model_copy(update={"response": LoopResponsePolicy(mode="OBSERVE_ONLY")})
    with LoopSession(tmp_path / "observe", observe, calendar()) as loop:
        offered = command(loop)
        before = loop.account()
        with pytest.raises(ValueError, match="LOOP_OBSERVE_ONLY"):
            loop.execute(offered, request_key="no-trade")
        assert loop.account() == before and loop.inventory()["total_qty"] == 100


def test_late_failure_after_all_money_receipts_still_rolls_back(tmp_path, monkeypatch):
    from trade_plan_monitor.backtest.loop_account import LoopAccountParticipant
    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(tmp_path, funded(), calendar()) as loop:
        offered = command(loop)
        before_money, before_inventory = loop.account(), loop.inventory()
        original = LoopAccountParticipant.apply

        def fail_late(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected before outer commit")

        monkeypatch.setattr(LoopAccountParticipant, "apply", fail_late)
        with pytest.raises(RuntimeError, match="injected before outer commit"):
            loop.execute(offered, request_key="late-failure")
        assert loop.account() == before_money and loop.inventory() == before_inventory
        monkeypatch.setattr(LoopAccountParticipant, "apply", original)
        receipt = loop.execute(offered, request_key="late-failure")
        assert receipt.account.revision == 2
        assert receipt.account.cash.balance_fen == 102396


def test_minute_correction_after_evaluation_cannot_commit_a_fill(tmp_path):
    from datetime import timedelta

    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(tmp_path, funded(), calendar()) as loop:
        offered = command(loop)
        before_money, before_inventory = loop.account(), loop.inventory()
        loop.set_time(loop.now + timedelta(seconds=1))
        with loop.work() as work:
            work.history.upsert_minutes(
                (
                    inputs()
                    .minute_prefix[0]
                    .model_copy(update={"volume_shares": 200, "received_at": loop.now}),
                )
            )
            work.commit()
        with pytest.raises(ValueError, match="LOOP_CURRENT_MINUTE_EVIDENCE_REQUIRED"):
            loop.execute(offered, request_key="corrected-minute")
        assert loop.account() == before_money and loop.inventory() == before_inventory


def test_non_execution_record_cannot_be_used_as_a_money_cause(tmp_path):
    from trade_plan_monitor.backtest.loop_session import LoopSession

    with LoopSession(tmp_path, funded(), calendar()) as loop:
        offered = command(loop).model_copy(update={"cause_id": "review-" + loop.details.id})
        before_money, before_inventory = loop.account(), loop.inventory()
        with pytest.raises(ValueError, match="LOOP_EXECUTION_EVIDENCE_MISSING"):
            loop.execute(offered, request_key="wrong-cause")
        assert loop.account() == before_money and loop.inventory() == before_inventory
