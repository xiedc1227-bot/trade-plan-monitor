"""Create self-contained synthetic minute/daily research files; never contact providers."""

import argparse
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.research_input import (
    ResearchAdjustmentProof,
    ResearchFactor,
    ResearchReview,
    UnifiedResearchInput,
)
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_json
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256
from trade_plan_monitor.market_data.historical_provider import (
    HistoricalMinuteBatch,
    HistoricalMinuteProfile,
    HistoricalOpeningSpecial,
)
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends

SH = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 8, 24)
SYMBOL = "600000.SH"
PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1


def create_fixture(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("fixture output directory must be empty")
    store = BacktestMarketStore(directory / "market.sqlite")
    beginning = DAY - timedelta(days=60)
    previous = beginning - timedelta(days=3)
    calendar, daily = [], []
    for offset in range(61):
        day = beginning + timedelta(days=offset)
        opened = day.weekday() < 5
        calendar.append(
            TradingDay(exchange="SSE", cal_date=day, is_open=opened, previous_trade_date=previous)
        )
        if opened:
            daily.append(
                DailyBar(
                    symbol=SYMBOL,
                    trade_date=day,
                    open_fen=6400,
                    high_fen=6420,
                    low_fen=6380,
                    close_fen=6400,
                    volume_shares=2_000_000,
                    amount_yuan=Decimal("128000000"),
                    is_official=True,
                    received_at=datetime.combine(day, time(15, 20), SH),
                )
            )
            previous = day
    store.record_trading_days(tuple(calendar))
    store.record_daily_bars(tuple(daily))
    bars = tuple(
        MinuteBar(
            symbol=SYMBOL,
            bar_end=end,
            open_fen=6400,
            high_fen=6401,
            low_fen=6399,
            close_fen=6400,
            volume_shares=1000,
            amount_yuan=Decimal("64000"),
            received_at=end + timedelta(seconds=12),
        )
        for end in expected_minute_ends(DAY, is_open=True)
    )
    store.record_minute_batch(
        HistoricalMinuteBatch(
            symbol=SYMBOL,
            trade_date=DAY,
            contract_version=PROFILE,
            bars=bars,
            opening_special=HistoricalOpeningSpecial(
                symbol=SYMBOL,
                source_time=datetime.combine(DAY, time(9, 30), SH),
                open_fen=6400,
                high_fen=6401,
                low_fen=6399,
                close_fen=6400,
                volume_shares=500,
                amount_yuan=Decimal("32000"),
            ),
        )
    )
    store.record_daily_limits(
        (
            DailyLimit(
                symbol=SYMBOL,
                trade_date=DAY,
                up_limit_fen=7040,
                down_limit_fen=5760,
                received_at=datetime.combine(DAY, time(9, 30), SH),
            ),
        )
    )
    frozen = store.freeze_dataset(
        DatasetScope(
            symbols=(SYMBOL,),
            start=DAY,
            end=DAY,
            warmup_start=beginning,
            historical_profile=PROFILE,
        )
    )
    if not frozen.ready or frozen.dataset_hash is None:
        raise ValueError("synthetic fixture failed dataset admission")
    source = Path(__file__).resolve().parents[1] / "tests/fixtures/unified-replay"
    for mode, filename in (("minute", "plan.json"), ("daily", "daily-plan.json")):
        plan = load_plan_json((source / filename).read_text(encoding="utf-8"))
        research = UnifiedResearchInput(
            started_at=datetime.combine(DAY, time(9), SH),
            inventory_known=True,
            review=ResearchReview(
                content_hash=daily_plan_content_sha256(plan),
                reviewed_at=datetime(2026, 10, 3, 9, tzinfo=SH),
                confirmed=True,
                evidence=(
                    "Synthetic research declaration only; no historical or AI review attestation"
                ),
            ),
        )
        if mode == "daily":
            proof_at = datetime.combine(DAY, time(15, 20), SH)
            research = research.model_copy(
                update={
                    "adjustment_proofs": (
                        ResearchAdjustmentProof(
                            proof_id="synthetic-verified-factor-proof",
                            dataset_hash=frozen.dataset_hash,
                            symbol=SYMBOL,
                            provider="TUSHARE",
                            adjustment_as_of=DAY,
                            available_at=proof_at,
                            received_at=proof_at,
                            quote_basis_factor=Decimal("1"),
                            factors=tuple(
                                ResearchFactor(trade_date=bar.trade_date, factor=Decimal("1"))
                                for bar in daily
                            ),
                            evidence=(
                                "Explicit synthetic constant factors, "
                                "never inferred for real raw data"
                            ),
                        ),
                    ),
                    "calendar_extension": (
                        TradingDay(
                            exchange="SSE",
                            cal_date=DAY + timedelta(days=1),
                            is_open=True,
                            previous_trade_date=DAY,
                        ),
                    ),
                }
            )
        (directory / f"{mode}-plan.json").write_text(dump_plan_json(plan), encoding="utf-8")
        (directory / f"{mode}-research.json").write_text(
            research.model_dump_json(indent=2), encoding="utf-8"
        )
    (directory / "dataset.json").write_text(
        json.dumps({"datasetHash": frozen.dataset_hash}, indent=2), encoding="utf-8"
    )
    return frozen.dataset_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="also run both real local CLI examples")
    args = parser.parse_args()
    directory = args.output.resolve()
    dataset_hash = create_fixture(directory)
    print(json.dumps({"directory": str(directory), "datasetHash": dataset_hash}))
    if args.run:
        from trade_plan_monitor.cli import main as cli

        for mode in ("minute", "daily"):
            result = cli(
                [
                    "backtest",
                    "run",
                    "--dataset",
                    dataset_hash,
                    "--plan",
                    str(directory / f"{mode}-plan.json"),
                    "--research-input",
                    str(directory / f"{mode}-research.json"),
                    "--initial-cash-yuan",
                    "10000",
                    "--commission-rate",
                    "0.0003",
                    "--minimum-commission-yuan",
                    "5",
                    "--stamp-duty-rate",
                    "0.0005",
                    "--transfer-fee-rate",
                    "0.00001",
                    "--buy-slippage-bps",
                    "1",
                    "--sell-slippage-bps",
                    "1",
                    "--no-event-risk",
                    "--market-db",
                    str(directory / "market.sqlite"),
                    "--results-db",
                    str(directory / "results.sqlite"),
                    "--report-dir",
                    str(directory / "reports"),
                ]
            )
            if result:
                raise SystemExit(result)


if __name__ == "__main__":
    main()
