"""Frozen loop boundaries, account facts and limits without legacy codec changes."""

from datetime import date
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError
from tests.unit.test_monitor_loop_schedule import at, row, version

from trade_plan_monitor.backtest.loop_input import (
    LOOP_INPUT_SCHEMA_VERSION,
    LOOP_RUN_FORMULA_VERSION,
    MAX_BATCH_EXTRACTIONS,
    MAX_EXTRACTION_ATTEMPTS,
    MAX_LOOP_RECORDS,
    MAX_SOURCE_BYTES,
    KnownLoopCash,
    LoopAccountInput,
    LoopCosts,
    LoopInitialLot,
    LoopLimits,
    LoopOpeningMark,
    LoopResponsePolicy,
    LoopSource,
    LoopSourceBatch,
    MonitorLoopInput,
    UnknownLoopCash,
)
from trade_plan_monitor.backtest.plan_schedule import LoopEndBoundary, LoopSchedule
from trade_plan_monitor.backtest.run_input import MAX_SAFE_INTEGER


def source(key="source-1", text="Known first-plan source"):
    return LoopSource(source_id=key, text=text)


def lot(key="opening-core", **changes):
    values = dict(
        lot_key=key,
        bucket="CORE",
        quantity=100,
        cost_basis_fen=401050,
        acquired_trade_date=None,
        sellable_quantity=None,
        evidence="Source explicitly states 100 CORE at 40.105/share.",
    )
    return LoopInitialLot(**(values | changes))


def account(**changes):
    values = dict(
        snapshot_at=at(),
        inventory_known=True,
        cash=KnownLoopCash(balance_fen=0),
        lots=(lot(),),
        opening_mark=None,
        evidence="Explicit reviewed opening account; no acquisition-date inference.",
    )
    return LoopAccountInput(**(values | changes))


def costs():
    return LoopCosts(
        commission_rate=Decimal("0.0003"),
        minimum_commission_fen=500,
        stamp_duty_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
        buy_slippage_fen=1,
        sell_slippage_fen=1,
    )


def frozen(**changes):
    values = dict(
        schedule=LoopSchedule(entries=(row(),)),
        initial_account=account(),
        boundary=LoopEndBoundary.resolve(started_at=at(), submitted_at=at(27, 10)),
        dataset_hash="3" * 64,
        response=LoopResponsePolicy(mode="FOLLOW_REMINDERS"),
        costs=costs(),
    )
    return MonitorLoopInput(**(values | changes))


def test_new_input_is_frozen_strict_roundtrippable_and_separately_versioned():
    value = frozen()
    assert value.schema_version == LOOP_INPUT_SCHEMA_VERSION == "monitor-loop-input-v1"
    assert value.run_formula_version == LOOP_RUN_FORMULA_VERSION == "backtest-run-v5"
    assert MonitorLoopInput.model_validate_json(value.model_dump_json()) == value
    assert len(value.run_id) == len(value.input_hash) == 64
    with pytest.raises(ValidationError):
        value.dataset_hash = "4" * 64
    for update in (
        {"dataset_hash": "bad"},
        {"initial_cash_fen": 100},
        {"schema_version": "backtest-run-input-v1"},
    ):
        with pytest.raises(ValidationError):
            value.model_copy(update=update)


def test_opening_cost_zero_cash_unknown_cash_and_market_value_stay_distinct():
    first = account()
    assert first.accounting_cost_fen == 401050
    assert first.opening_equity_fen is None
    assert first.lots[0].acquired_trade_date is None
    assert first.lots[0].sellable_quantity is None
    mark = LoopOpeningMark(
        price_fen=2898,
        price_at=at(20, 8, 59),
        available_at=at(),
        evidence="Frozen completed historical quote",
    )
    valued = first.model_copy(update={"opening_mark": mark})
    assert valued.opening_equity_fen == 289800
    unknown = first.model_copy(update={"cash": UnknownLoopCash()})
    assert unknown.cash.kind == "UNKNOWN"
    assert unknown.opening_equity_fen is None
    assert frozen(initial_account=unknown).run_id != frozen().run_id
    for invalid in (
        {"kind": "UNKNOWN", "balance_fen": 0},
        {"kind": "KNOWN", "balance_fen": True},
        {"kind": "KNOWN", "balance_fen": -1},
    ):
        with pytest.raises(ValidationError):
            first.model_copy(update={"cash": invalid})


def test_unknown_inventory_or_cost_does_not_create_a_zero_valued_account():
    unknown = account(inventory_known=False, lots=())
    assert unknown.accounting_cost_fen is None
    with pytest.raises(ValidationError):
        account(inventory_known=False)
    assert account(lots=(lot(cost_basis_fen=None),)).accounting_cost_fen is None
    flat = account(lots=())
    assert flat.accounting_cost_fen == flat.opening_equity_fen == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": True},
        {"quantity": 50},
        {"quantity": 0},
        {"cost_basis_fen": -1},
        {"sellable_quantity": 200},
        {"sellable_quantity": 1},
        {"quantity": MAX_SAFE_INTEGER + 1},
    ],
)
def test_initial_lot_rejects_invalid_full_quantities_and_costs(changes):
    with pytest.raises(ValidationError):
        lot(**changes)


def test_initial_account_rejects_future_acquisition_sellability_and_duplicate_lots():
    for lots in (
        (lot(acquired_trade_date=date(2026, 8, 21)),),
        (lot(acquired_trade_date=date(2026, 8, 20), sellable_quantity=100),),
        (lot(), lot()),
    ):
        with pytest.raises(ValidationError):
            account(lots=lots)
    with pytest.raises(ValidationError):
        account(cash=KnownLoopCash(balance_fen=MAX_SAFE_INTEGER))
    mark = LoopOpeningMark(
        price_fen=2800, price_at=at(), available_at=at(20, 9, 1), evidence="Late quote"
    )
    with pytest.raises(ValidationError):
        frozen(initial_account=account(opening_mark=mark))
    with pytest.raises(ValidationError):
        account(
            cash=UnknownLoopCash(),
            opening_mark=mark.model_copy(
                update={"price_fen": MAX_SAFE_INTEGER},
            ),
        )


def test_initial_account_snapshot_precedes_monitoring_without_rebuying_holdings():
    earlier = account(snapshot_at=at(19))
    assert frozen(initial_account=earlier).initial_account.snapshot_at == at(19)
    with pytest.raises(ValidationError, match="snapshot"):
        frozen(initial_account=account(snapshot_at=at(21)))
    plan = version().snapshot.model_copy(update={"position": {"max_qty": 100}})
    schedule = LoopSchedule(entries=(row(value=version(plan=plan)),))
    with pytest.raises(ValidationError, match="maximum"):
        frozen(schedule=schedule, initial_account=account(lots=(lot(quantity=200),)))
    assert frozen().initial_account.lots[0].cost_basis_fen == 401050


def test_absolute_fen_slippage_and_exact_rates_never_use_floats_or_basis_points():
    value = costs()
    assert value.buy_slippage_fen == value.sell_slippage_fen == 1
    assert LoopCosts.model_validate_json(value.model_dump_json()) == value
    for update in (
        {"commission_rate": 0.0003},
        {"commission_rate": "NaN"},
        {"commission_rate": "1.01"},
        {"buy_slippage_bps": "1"},
        {"buy_slippage_fen": -1},
        {"minimum_commission_fen": True},
    ):
        with pytest.raises(ValidationError):
            value.model_copy(update=update)


def test_response_mode_is_explicit_and_allows_no_unsolicited_recorded_actions():
    with pytest.raises(ValidationError):
        LoopResponsePolicy()
    for mode in ("FOLLOW_REMINDERS", "OBSERVE_ONLY", "RECORDED_ACTIONS"):
        assert LoopResponsePolicy(mode=mode).response_delay_seconds == 0
    assert frozen(response=LoopResponsePolicy(mode="OBSERVE_ONLY")).run_id != frozen().run_id


def test_single_source_limits_preserve_utf8_hashes_and_character_ceiling():
    value = source(text="原文")
    assert value.source_hash == sha256("原文".encode()).hexdigest()
    for text in ("", " \n\t", "x" * 150001):
        with pytest.raises(ValidationError):
            source(text=text)
    with pytest.raises(ValidationError):
        LoopSourceBatch(sources=(value, value))
    # The unchanged character cap is stricter than the existing UTF-8 guard for one source.
    for text in ("x" * 150000, "文" * 150000):
        assert LoopSourceBatch(sources=(source(text=text),)).sources[0].text == text
    assert MAX_SOURCE_BYTES == 8 * 1024 * 1024
    with pytest.raises(ValidationError):
        LoopSourceBatch(sources=())


def test_single_plan_source_contract_rejects_a_second_source():
    with pytest.raises(ValidationError):
        LoopSourceBatch(sources=(source("first"), source("second")))
    original = LoopSourceBatch(sources=(source(),))
    with pytest.raises(ValidationError):
        original.model_copy(update={"sources": (source("first"), source("second"))})
    payload = original.model_dump(mode="json")
    payload["sources"].append(source("second").model_dump(mode="json"))
    with pytest.raises(ValidationError):
        LoopSourceBatch.model_validate(payload)


def test_lot_event_and_evaluation_caps_are_finite_and_cannot_be_raised():
    assert MAX_EXTRACTION_ATTEMPTS == 3
    assert MAX_BATCH_EXTRACTIONS == 1
    assert len(account(lots=tuple(lot(str(i)) for i in range(200))).lots) == 200
    with pytest.raises(ValidationError):
        account(lots=tuple(lot(str(i)) for i in range(201)))
    limits = LoopLimits()
    assert limits.max_evaluations == limits.max_reminders == MAX_LOOP_RECORDS == 70000
    assert limits.max_intents == limits.max_execution_attempts == 70000
    for field in ("max_evaluations", "max_reminders", "max_intents", "max_execution_attempts"):
        with pytest.raises(ValidationError):
            limits.model_copy(update={field: 70001})


def test_identity_separates_run_dataset_and_policy_from_single_plan_authority():
    original = frozen()
    for changed in (
        frozen(dataset_hash="4" * 64),
        frozen(response=LoopResponsePolicy(mode="OBSERVE_ONLY")),
    ):
        assert original.run_id != changed.run_id
        assert (
            original.schedule.select(at()).authority_id
            == changed.schedule.select(at()).authority_id
        )
    payload = original.model_dump(mode="json")
    payload["schedule"]["entries"].append(row(21).model_dump(mode="json"))
    with pytest.raises(ValidationError):
        MonitorLoopInput.model_validate(payload)


def test_review_must_already_exist_when_the_run_is_submitted():
    original = frozen()
    late = version().model_copy(
        update={
            "review": version().review.model_copy(update={"reviewed_at": at(28)}),
        }
    )
    with pytest.raises(ValidationError, match="review"):
        original.model_copy(update={"schedule": LoopSchedule(entries=(row(value=late),))})
