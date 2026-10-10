"""RP-T01: independent declared oracle, not evidence that replay already supports it."""

import json
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import LoopAccountInput, LoopCosts, MonitorLoopInput
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.models import DailyLimit, MinuteBar, TradingDay

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def fixture():
    return json.loads((FIXTURES / "monitor_loop_continuity.json").read_text(encoding="utf-8"))


def test_four_complete_synthetic_sources_have_explicit_chronology_and_valid_snapshots(fixture):
    assert fixture["provenance"]["kind"] == "SYNTHETIC_OFFLINE"
    assert fixture["provenance"]["user_market_data"] is False
    assert fixture["symbol"] == "601021.SH"
    sources = fixture["sources"]
    assert [item["source_id"] for item in sources] == [
        "source-1", "source-2", "source-3", "source-4",
    ]
    assert [item["effective_trade_date"] for item in sources] == [
        "2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25",
    ]
    for item in sources:
        assert item["scope"] == "FULL_REPLACEMENT"
        assert item["source_hash"] == sha256(item["text"].encode("utf-8")).hexdigest()
        assert item["text"].startswith("SYNTHETIC OFFLINE COMPLETE TRADING PLAN")
        assert item["effective_trade_date"] in item["text"]
        authored = datetime.fromisoformat(item["authored_at"])
        available = datetime.fromisoformat(item["available_at"])
        effective = datetime.fromisoformat(item["effective_trade_date"] + "T09:30:00+08:00")
        assert authored <= available < effective
        assert available.utcoffset() == timedelta(hours=8)
        plan = UnifiedTradePlan.model_validate_json(json.dumps(item["snapshot"]))
        assert plan.symbol == fixture["symbol"]
        assert plan.position.max_qty == 300
        assert plan.trading_rules.settlement == "NEXT_EXCHANGE_SESSION"
    assert [item["stated_quantity"] for item in sources] == [0, 0, 200, 0]


def test_declared_opening_and_costs_are_explicit_and_valid(fixture):
    opening = LoopAccountInput.model_validate_json(json.dumps(fixture["opening_account"]))
    assert opening.cash.balance_fen == 1_000_000
    assert opening.inventory_known and opening.lots == ()
    assert opening.snapshot_at.isoformat() == "2026-08-20T09:00:00+08:00"
    costs = LoopCosts.model_validate_json(json.dumps(fixture["costs"]))
    assert costs.minimum_commission_fen == 500
    assert costs.commission_rate == costs.stamp_duty_rate == costs.transfer_fee_rate == 0
    assert costs.buy_slippage_fen == costs.sell_slippage_fen == 0
    assert fixture["response"] == {
        "mode": "FOLLOW_REMINDERS", "response_delay_seconds": 0,
        "fill_model": "NEXT_ELIGIBLE_MINUTE_CLOSE",
    }
    assert fixture["recorded_actions"] == []


def test_literal_account_oracle_at_all_four_version_boundaries(fixture):
    boundaries = fixture["expected"]["version_boundaries"]
    assert [(item["version_id"], item["cash_fen"], item["quantity"],
             item["sellable_quantity"], item["cost_basis_fen"], item["paid_fees_fen"],
             item["realized_pnl_fen"]) for item in boundaries] == [
        ("p1", 1_000_000, 0, 0, 0, 0, 0),
        ("p2", 899_500, 100, 100, 100_500, 500, 0),
        ("p3", 899_500, 100, 100, 100_500, 500, 0),
        ("p4", 1_019_000, 0, 0, 0, 1_000, 19_000),
    ]
    expected_lot = {
        "origin": "p1-buy", "bucket": "TACTICAL", "quantity": 100,
        "acquired_trade_date": "2026-08-20", "cost_basis_fen": 100_500,
        "sellable_quantity": 100,
    }
    assert boundaries[0]["lots"] == boundaries[3]["lots"] == []
    assert boundaries[1]["lots"] == boundaries[2]["lots"] == [expected_lot]
    assert fixture["expected"]["after_buy"] == {
        "cash_fen": 899_500, "quantity": 100, "sellable_quantity": 0,
        "cost_basis_fen": 100_500, "paid_fees_fen": 500, "realized_pnl_fen": 0,
        "lots": [expected_lot | {"sellable_quantity": 0}],
    }
    assert fixture["expected"]["final_account"] == {
        "cash_fen": 1_019_000, "quantity": 0, "sellable_quantity": 0,
        "cost_basis_fen": 0, "paid_fees_fen": 1_000, "realized_pnl_fen": 19_000,
        "lots": [],
    }


def test_oracle_arithmetic_is_checked_without_runtime_accounting(fixture):
    buy, sell = fixture["expected"]["fills"]
    assert [(item["side"], item["quantity"], item["price_fen"], item["fees_fen"])
            for item in (buy, sell)] == [("BUY", 100, 1000, 500), ("SELL", 100, 1200, 500)]
    assert 1_000_000 - buy["quantity"] * buy["price_fen"] - buy["fees_fen"] == 899_500
    assert 899_500 + sell["quantity"] * sell["price_fen"] - sell["fees_fen"] == 1_019_000
    assert buy["fees_fen"] + sell["fees_fen"] == 1_000
    assert sell["quantity"] * sell["price_fen"] - sell["fees_fen"] - 100_500 == 19_000
    assert fixture["expected"]["account_initializations"] == 1
    assert fixture["expected"]["run_count"] == fixture["expected"]["result_count"] == 1


def test_fills_require_future_completed_intervals_and_t_plus_one(fixture):
    for key, model in (("minute_bars", MinuteBar), ("calendar", TradingDay),
                       ("daily_limits", DailyLimit)):
        for raw in fixture[key]:
            model.model_validate_json(json.dumps(raw))
    bars = {item["bar_end"]: item for item in fixture["minute_bars"]}
    for fill in fixture["expected"]["fills"]:
        decision = datetime.fromisoformat(fill["reminder_available_at"])
        end = datetime.fromisoformat(fill["bar_end"])
        available = datetime.fromisoformat(fill["available_at"])
        assert end - timedelta(minutes=1) >= decision
        assert end - timedelta(minutes=2) < decision  # Earlier interval is ineligible.
        assert available >= end
        assert bars[fill["bar_end"]]["close_fen"] == fill["price_fen"]
        assert bars[fill["bar_end"]]["received_at"] == fill["available_at"]
    buy, sell = fixture["expected"]["fills"]
    assert buy["bar_end"] == "2026-08-20T09:37:00+08:00"
    assert sell["bar_end"] == "2026-08-24T09:37:00+08:00"
    assert date.fromisoformat(sell["bar_end"][:10]) > date.fromisoformat(buy["bar_end"][:10])
    assert [item["cal_date"] for item in fixture["calendar"] if item["is_open"]] == [
        "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25",
    ]


def test_later_account_descriptions_are_differences_not_ledger_changes(fixture):
    assert fixture["expected"]["account_context"] == [
        {"version_id": "p2", "stated_quantity": 0, "simulated_quantity": 100,
         "difference_quantity": -100, "account_mutated": False},
        {"version_id": "p3", "stated_quantity": 200, "simulated_quantity": 100,
         "difference_quantity": 100, "account_mutated": False},
        {"version_id": "p4", "stated_quantity": 0, "simulated_quantity": 0,
         "difference_quantity": 0, "account_mutated": False},
    ]
    incompatible = fixture["variants"]["account_dependent_instruction"]
    assert incompatible["required_quantity"] == 200
    assert incompatible["actual_quantity"] == 100
    assert incompatible["expected"] == {
        "instruction_blocked": True, "fabricated_fills": 0, "cash_fen": 899_500,
        "quantity": 100, "cost_basis_fen": 100_500, "paid_fees_fen": 500,
    }


def test_replacement_fixture_distinguishes_ordinary_closure_from_risk_survival(fixture):
    case = fixture["variants"]["replacement_with_pending_authority"]
    assert case["switch_at"] == "2026-08-21T09:00:00+08:00"
    assert case["old_ordinary_intent"]["execution_window"] == "NEXT_EXCHANGE_SESSION_ONLY"
    assert case["old_ordinary_intent"]["owner_version_id"] == "p1"
    assert case["expected"]["ordinary_status"] == "CLOSED_REPLACED"
    assert case["expected"]["transferred_authority"] is False
    assert case["expected"]["fills_before_successor_evaluation"] == 0
    assert case["expected"]["risk_obligation"] == case["risk_obligation"]
    assert case["expected"]["account_after_switch"] == fixture["expected"]["version_boundaries"][1]
    assert case["draft_only_expected"] == {"active_version_id": "p1", "ordinary_closed": False}


def test_frozen_single_version_input_bytes_hashes_and_rejection_stay_compatible(fixture):
    legacy = fixture["compatibility"]["monitor_loop_input_v1"]
    value = MonitorLoopInput.model_validate_json(legacy["json"])
    assert value.model_dump_json() == legacy["json"]
    assert canonical_json(value) == legacy["canonical_json"]
    assert value.input_hash == legacy["input_hash"]
    assert value.run_id == legacy["run_id"]
    assert value.schema_version == "monitor-loop-input-v1"
    assert value.run_formula_version == "backtest-run-v5"
    assert value.initial_account.accounting_cost_fen == 401050
    assert value.initial_account.cash.balance_fen == 0
    assert value.initial_account.lots[0].acquired_trade_date is None
    assert value.initial_account.lots[0].sellable_quantity is None
    raw = json.loads(legacy["json"])
    raw["schedule"]["entries"].append(raw["schedule"]["entries"][0])
    with pytest.raises(ValidationError):
        MonitorLoopInput.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "name", ["v1_identity_goldens.json", "v1_result_summary.json", "v1_fills.csv"],
)
def test_existing_frozen_report_identity_and_export_bytes_are_unchanged(fixture, name):
    assert sha256((FIXTURES / "backtest" / name).read_bytes()).hexdigest() == (
        fixture["compatibility"]["legacy_artifact_sha256"][name]
    )
