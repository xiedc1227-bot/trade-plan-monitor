"""Offline fixed-initial-plan study; reads previously fetched research responses only."""

import argparse
import json
from datetime import date, datetime, time
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.research_input import (
    ResearchAdjustmentProof,
    ResearchFactor,
    ResearchReview,
    ResearchSimulation,
    UnifiedResearchInput,
)
from trade_plan_monitor.backtest.run_input import BacktestInitialLotInput
from trade_plan_monitor.backtest.runner import OfflineBacktestRunner
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.tushare_historical import TushareHistoricalMinuteProvider

SH = ZoneInfo("Asia/Shanghai")
SYMBOL = "002240.SZ"
START, END, WARMUP = date(2026, 9, 11), date(2026, 9, 30), date(2025, 9, 1)
PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1
SOURCE = "https://chatgpt.com/c/6aa21e11-9d54-83ea-8a91-3c401c270008"


class FrozenClient:
    """Expose downloaded frames to the existing strict provider normalization."""

    def __init__(self, directory):
        self.frames = {
            name: pd.DataFrame(json.loads((directory / f"{name}.json").read_text("utf-8"))["data"])
            for name in ("daily", "adj_factor", "trade_cal", "stk_mins", "stk_limit")
        }

    def __getattr__(self, name):
        def fetch(**params):
            frame = self.frames[name]
            column = (
                "trade_time"
                if name == "stk_mins"
                else "cal_date"
                if name == "trade_cal"
                else "trade_date"
            )
            mask = pd.Series(True, index=frame.index)
            for key, comparison in (("start_date", "ge"), ("end_date", "le"), ("trade_date", "eq")):
                if key in params:
                    mask &= getattr(frame[column], comparison)(params[key])
            return frame.loc[mask].copy()

        return fetch


def plan_from_source():
    """Encode the unambiguous initial authority, leaving severe review unknown."""
    template = Path(__file__).resolve().parents[1] / "tests/fixtures/unified-replay/daily-plan.json"
    raw = json.loads(template.read_text("utf-8"))

    def zone(low, high):
        return dict(low_fen=low, high_fen=high, include_low=True, include_high=True)

    raw.update(
        plan_id="shengxin-initial-20260910",
        symbol=SYMBOL,
        name="盛新锂能初始固定计划研究",
        market="SZSE",
    )
    raw["metadata"] = dict(report_at="2026-09-09T01:04:00+08:00", reference_price_fen=2898)
    raw["levels"] = dict(
        low_buy=zone(2850, 2900),
        pressure=zone(2930, 2980),
        risk_line_fen=2599,
        risk_comparison="LT",
    )
    raw["position"] = dict(
        max_qty=300,
        core_target_qty=100,
        tactical_target_qty=200,
        allocation_provenance="PROPOSED",
        allocation_evidence=(
            "Initial user prompt: existing CORE 100, maximum 300; "
            "future independent 100+100 TACTICAL."
        ),
    )
    # No BUY: source explicitly keeps the observation zone disabled.
    raw["ordinary_rules"] = []
    ordinary = dict(
        kind="ORDINARY_TECHNICAL",
        involves_core=True,
        scope_evidence=(
            "Two official closes below 25.99 invalidate the holding structure, "
            "including CORE; target zero."
        ),
        target_core_qty=0,
        target_tactical_qty=0,
        priority=3,
        evidence_mode="TWO_OFFICIAL_CLOSES",
        suspension_confirmation_policy="RESTART_ADJACENT_PAIR",
        condition=None,
    )

    def fact(kind):
        return dict(
            type="REVIEWED_FACT",
            fact_kind=kind,
            evidence_requirement=(
                "Source requires reviewed technical structure and deterioration evidence; "
                "do not infer it."
            ),
            validity_scope="TRADE_DATE",
        )

    severe = dict(
        kind="SEVERE_TECHNICAL",
        involves_core=True,
        scope_evidence=(
            "Confirmed severe technical structure breakdown includes CORE and TACTICAL; "
            "target zero."
        ),
        target_core_qty=0,
        target_tactical_qty=0,
        priority=2,
        evidence_mode="STRUCTURE_AND_DETERIORATION",
        suspension_confirmation_policy=None,
        condition=dict(
            type="ALL", conditions=[fact("SEVERE_STRUCTURE"), fact("SEVERE_DETERIORATION")]
        ),
    )
    raw["risk_branches"] = [ordinary, severe]
    raw["alert_rules"] = []
    return load_plan_json(json.dumps(raw, ensure_ascii=False))


def independent_price_checks(directory):
    """Check source price gates without invoking monitor or execution rules."""

    def rows(name):
        return json.loads((directory / f"{name}.json").read_text("utf-8"))["data"]

    daily = {row["trade_date"]: row for row in rows("daily")}
    index = {row["trade_date"]: row for row in rows("index_daily")}
    calendar = sorted(
        row["cal_date"]
        for row in rows("trade_cal")
        if row["is_open"] == 1 and "20260911" <= row["cal_date"] <= "20260930"
    )
    observations, first, second, execution_day = [], None, None, None
    previous_below = False
    for day in calendar:
        low, close = Decimal(str(daily[day]["low"])), Decimal(str(daily[day]["close"]))
        below = close < Decimal("25.99")
        if below and first is None:
            first = day
        if below and previous_below and second is None:
            second = day
            execution_day = calendar[calendar.index(day) + 1]
        observations.append(
            dict(
                date=day,
                close=str(close),
                below_original_risk=below,
                intraday_breach_only=low < Decimal("25.99") and not below,
            )
        )
        previous_below = below
    minute = next(row for row in rows("stk_mins") if row["trade_time"] == "2026-09-29 09:31:00")
    oracle = dict(
        first_close_breach=first,
        second_close_breach=second,
        first_execution_session=execution_day,
        execution_minute=minute,
        stock_hold_return_pct=str(
            (Decimal(str(daily["20260930"]["close"])) / Decimal("28.50") - 1) * 100
        ),
        index_return_pct=str(
            (
                Decimal(str(index["20260930"]["close"])) / Decimal(str(index["20260910"]["close"]))
                - 1
            )
            * 100
        ),
        observations=observations,
    )
    assert (first, second, execution_day) == ("20260924", "20260928", "20260929")
    post_sale = []
    for day in calendar:
        if day < "20260917":
            continue
        low, close = Decimal(str(daily[day]["low"])), Decimal(str(daily[day]["close"]))
        if day <= "20260922":
            assert low > Decimal("26.70")
            reason = "NO_PULLBACK_IN_OBSERVATION_ZONE"
        elif day == "20260923":
            assert close < Decimal("26.70")
            reason = "NO_CLOSE_RECLAIM_OF_26_70"
        else:
            assert close < Decimal("25.99")
            reason = "CORE_RISK_UNRECOVERED"
        post_sale.append(
            dict(
                trade_date=day,
                low=str(low),
                close=str(close),
                buy_qty=0,
                reason=reason,
                technical_signal_certified=False,
            )
        )
    gates = dict(
        scope="post-sale necessary price gates only; not full engine replay",
        observations=post_sale,
        new_buys=0,
        new_sells=0,
        actual_trade_pnl=None,
    )
    for name, value in (("independent-oracle", oracle), ("post-sale-price-gates", gates)):
        (directory / f"{name}.json").write_text(
            json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def run_study(directory):
    directory = directory.resolve()
    client = FrozenClient(directory)
    provider = TushareHistoricalMinuteProvider(
        client, now=lambda: datetime(2026, 10, 3, 23, 10, tzinfo=SH), profile=PROFILE
    )
    calendar = provider.trading_calendar("SZSE", WARMUP, END)
    daily = provider.daily_bars(SYMBOL, WARMUP, END)
    factor_frame = client.frames["adj_factor"]
    factors = {
        datetime.strptime(row.trade_date, "%Y%m%d").date(): Decimal(str(row.adj_factor))
        for row in factor_frame.itertuples()
    }
    assert len(daily) == 263 and all(bar.trade_date in factors for bar in daily)
    store = BacktestMarketStore(directory / "research-market.sqlite")
    store.record_trading_days(calendar)
    store.record_daily_bars(daily)
    open_days = [day.cal_date for day in calendar if day.is_open and START <= day.cal_date <= END]
    for day in open_days:
        store.record_minute_batch(provider.historical_minute_batch(SYMBOL, day))
        store.record_daily_limits(provider.daily_limits(day))
    frozen = store.freeze_dataset(
        DatasetScope(
            symbols=(SYMBOL,), start=START, end=END, warmup_start=WARMUP, historical_profile=PROFILE
        )
    )
    if not frozen.ready:
        raise ValueError(f"dataset admission failed: {frozen}")
    print(
        json.dumps(
            {
                "ready": True,
                "dataset_hash": frozen.dataset_hash,
                "open_sessions": len(open_days),
                "minutes": len(open_days) * 240,
            }
        ),
        flush=True,
    )
    plan = plan_from_source()
    proofs = []
    for bar in daily:
        if bar.trade_date < date(2026, 9, 10):
            continue
        at = datetime.combine(bar.trade_date, time(15, 20), SH)
        proofs.append(
            ResearchAdjustmentProof(
                proof_id=f"factor-{bar.trade_date}",
                dataset_hash=frozen.dataset_hash,
                symbol=SYMBOL,
                provider="TUSHARE",
                available_at=at,
                received_at=at,
                adjustment_as_of=bar.trade_date,
                quote_basis_factor=factors[bar.trade_date],
                factors=tuple(
                    ResearchFactor(trade_date=d, factor=factors[d])
                    for d in sorted(factors)
                    if d <= bar.trade_date
                ),
                evidence=(
                    "Retrospective configured Tushare-compatible adj_factor response. "
                    "Historical 15:20 availability is a declared research assumption, "
                    "not a contemporaneous collection attestation."
                ),
            )
        )
    research = UnifiedResearchInput(
        started_at=datetime.combine(START, time(9), SH),
        inventory_known=True,
        review=ResearchReview(
            content_hash=daily_plan_content_sha256(plan),
            reviewed_at=datetime(2026, 10, 3, 23, 10, tzinfo=SH),
            confirmed=True,
            evidence=(
                "Research operator extraction of initial source only; ordinary pressure sales "
                "and fundamental events are outside this risk-slice study. "
                "Not saved production/user approval. " + SOURCE
            ),
        ),
        adjustment_proofs=tuple(proofs),
        operations=tuple(
            ResearchSimulation(
                operation_id=f"risk-request-{d}",
                at=datetime.combine(d, time(9, 31, 12), SH),
                order=0,
                kind="SIMULATE",
                risk_kind="ORDINARY_TECHNICAL",
                quantity=100,
            )
            for d in open_days
        ),
    )
    execution = ExecutionConfig(
        commission_rate=Decimal("0.0003"),
        minimum_commission_fen=500,
        stamp_duty_rate=Decimal("0.0005"),
        transfer_fee_rate=Decimal("0.00001"),
        buy_slippage_bps=Decimal("4"),
        sell_slippage_bps=Decimal("4"),
    )
    lot = BacktestInitialLotInput(
        lot_key="initial-study-core",
        bucket="CORE",
        acquired_trade_date=date(2026, 9, 9),
        quantity=100,
        # The lot contract holds TOTAL lot cost in fen, not a per-share quote.
        cost_basis_fen=100 * 2850,
    )
    (directory / "fixed-plan.json").write_text(dump_plan_json(plan), encoding="utf-8")
    (directory / "fixed-research.json").write_text(
        research.model_dump_json(indent=2), encoding="utf-8"
    )
    (directory / "initial-lots.json").write_text(lot.model_dump_json(indent=2), encoding="utf-8")
    runner = OfflineBacktestRunner(store)
    report = runner.run(
        plan=plan,
        dataset_hash=frozen.dataset_hash,
        initial_cash_fen=1,
        initial_lots=(lot,),
        execution_config=execution,
        manual_event_risk=False,
        research_input=research,
    )
    applied = [outcome for outcome in report.operations if outcome.status == "APPLIED"]
    assert report.metrics.initial_equity_fen == 285001
    assert len(applied) == 1 and applied[0].at.date() == date(2026, 9, 29)
    assert applied[0].side == "SELL" and applied[0].quantity == 100
    assert applied[0].monitor_price_fen == 2481
    assert applied[0].valuation.research_price_fen == 2480
    assert applied[0].valuation.fees_fen == 627
    assert report.metrics.final_equity_fen == 247374
    assert report.final_inventory.total_qty == 0
    (directory / "fixed-report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    receipt = [o.model_dump(mode="json") for o in report.operations]
    summary = dict(
        dataset_hash=frozen.dataset_hash,
        report_hash=report.report_hash,
        metrics=report.metrics.model_dump(mode="json"),
        operations=receipt,
        final_inventory=report.final_inventory.model_dump(mode="json"),
        source_response_hashes={
            p.name: sha256(p.read_bytes()).hexdigest()
            for p in directory.glob("*.json")
            if p.stem in client.frames or p.stem == "index_daily"
        },
    )
    (directory / "fixed-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        json.dumps(
            dict(report_hash=report.report_hash, metrics=summary["metrics"]), ensure_ascii=False
        ),
        flush=True,
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--verify-repeat", action="store_true")
    args = parser.parse_args()
    previous = (
        json.loads((args.data / "fixed-summary.json").read_text("utf-8"))["report_hash"]
        if args.verify_repeat
        else None
    )
    independent_price_checks(args.data)
    report = run_study(args.data)
    if args.verify_repeat:
        assert previous == report.report_hash, "Repeat report identity changed"
        verification = dict(
            same_report_hash=True,
            first_report_hash=previous,
            repeated_report_hash=report.report_hash,
            independent_price_checks_passed=True,
            monetary_and_execution_assertions_passed=True,
        )
        (args.data / "verification.json").write_text(
            json.dumps(verification, indent=2), encoding="utf-8"
        )
        print(json.dumps(verification), flush=True)
