"""CLI-facing composition for isolated historical synchronization and backtests."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from trade_plan_monitor.backtest.dataset import (
    DatasetFreezeResult,
    DatasetScope,
    exchange_for_symbol,
)
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.reporting import (
    persist_report,
    write_persisted_report_files,
    write_report_files,
)
from trade_plan_monitor.backtest.results import (
    BacktestResultStore,
    BacktestRunSummary,
    RetentionPruneResult,
)
from trade_plan_monitor.backtest.runner import (
    OfflineBacktestRunner,
    backtest_run_id,
)
from trade_plan_monitor.backtest.sync import BacktestSyncResult, BacktestSyncService
from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.domain.plan_codec import load_plan_json, load_plan_yaml
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.tushare_client import create_tushare_client
from trade_plan_monitor.market_data.tushare_historical import TushareHistoricalMinuteProvider
from trade_plan_monitor.runtime.clock import SystemClock
from trade_plan_monitor.runtime.request_control import TushareRequestController

DEFAULT_MARKET_DATABASE = Path("data/backtest-market.sqlite3")
DEFAULT_RESULTS_DATABASE = Path("data/backtest-results.sqlite3")
DEFAULT_REPORT_DIRECTORY = Path("backtest-reports")
DEFAULT_WARMUP_CALENDAR_DAYS = 400
VERIFIED_HISTORICAL_PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1
_MAX_SUPPORTED_FEN = (1 << 63) - 1


class _ApplicationValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BacktestRunCommandResult(_ApplicationValue):
    run_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reused: bool
    json_report: str
    csv_report: str
    metrics: dict[str, object]


class BacktestListResult(_ApplicationValue):
    runs: tuple[BacktestRunSummary, ...]


class BacktestApplicationService:
    """Keep sync network-capable and every other backtest command local-only."""

    def __init__(
        self,
        *,
        config_path: str | Path,
        market_database: str | Path = DEFAULT_MARKET_DATABASE,
        results_database: str | Path = DEFAULT_RESULTS_DATABASE,
        report_directory: str | Path = DEFAULT_REPORT_DIRECTORY,
    ) -> None:
        self._config_path = Path(config_path).expanduser().resolve()
        self._market_database = Path(market_database).expanduser().resolve()
        self._results_database = Path(results_database).expanduser().resolve()
        self._report_directory = Path(report_directory).expanduser().resolve()
        if _same_path(self._market_database, self._results_database):
            raise ValueError("market_database and results_database must be different files")

    async def sync(
        self,
        *,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        warmup_start: date | None,
        refresh: bool,
        allow_network: bool,
    ) -> BacktestSyncResult:
        """Perform the only network-capable command after an explicit CLI grant."""

        if type(allow_network) is not bool:
            raise TypeError("allow_network must be a bool")
        if not allow_network:
            raise PermissionError("backtest sync requires explicit --allow-network authorization")
        scope = _scope(symbols, start, end, warmup_start)
        unsupported = tuple(
            symbol for symbol in scope.symbols if exchange_for_symbol(symbol) == "BSE"
        )
        if unsupported:
            raise ValueError("UNSUPPORTED_HISTORICAL_CALENDAR:BSE")
        configuration = load_application_config(self._config_path)
        clock = SystemClock()
        client = create_tushare_client(configuration.tushare)
        provider = TushareHistoricalMinuteProvider(
            client,
            now=clock.now,
            profile=VERIFIED_HISTORICAL_PROFILE,
        )
        controller = TushareRequestController(clock=clock)
        try:
            service = BacktestSyncService(
                provider=provider,
                store=BacktestMarketStore(self._market_database),
                request_controller=controller,
                today=lambda: clock.now().date(),
            )
            return await service.sync(scope, refresh=refresh)
        finally:
            controller.close()

    def verify(
        self,
        *,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        warmup_start: date | None,
    ) -> DatasetFreezeResult:
        scope = _scope(symbols, start, end, warmup_start)
        return BacktestMarketStore(self._market_database).freeze_dataset(scope)

    def run(
        self,
        *,
        dataset_hash: str,
        plan_path: str | Path,
        initial_cash_yuan: Decimal,
        commission_rate: Decimal,
        minimum_commission_yuan: Decimal,
        stamp_duty_rate: Decimal,
        transfer_fee_rate: Decimal,
        buy_slippage_bps: Decimal,
        sell_slippage_bps: Decimal,
        manual_event_risk: bool,
    ) -> BacktestRunCommandResult:
        market_store = BacktestMarketStore(self._market_database)
        result_store = BacktestResultStore(self._results_database)
        plan = _load_plan(plan_path)
        initial_cash_fen = _yuan_to_fen(initial_cash_yuan, "initial_cash_yuan", positive=True)
        execution_config = ExecutionConfig(
            commission_rate=commission_rate,
            minimum_commission_fen=_yuan_to_fen(
                minimum_commission_yuan,
                "minimum_commission_yuan",
                positive=False,
            ),
            stamp_duty_rate=stamp_duty_rate,
            transfer_fee_rate=transfer_fee_rate,
            buy_slippage_bps=buy_slippage_bps,
            sell_slippage_bps=sell_slippage_bps,
        )
        manifest = market_store.dataset_manifest(dataset_hash)
        expected_run_id = backtest_run_id(
            plan=plan,
            manifest=manifest,
            initial_cash_fen=initial_cash_fen,
            execution_config=execution_config,
            manual_event_risk=manual_event_risk,
        )
        json_path = self._report_directory / f"{expected_run_id}.json"
        csv_path = self._report_directory / f"{expected_run_id}.fills.csv"
        existing = result_store.get_run(expected_run_id)
        if existing is not None:
            report_hash = existing.assumptions.get("reportHash")
            if not isinstance(report_hash, str):
                raise RuntimeError("stored completed run is missing reportHash")
            write_persisted_report_files(
                existing,
                result_store.list_fills(expected_run_id),
                json_path=json_path,
                csv_path=csv_path,
            )
            return BacktestRunCommandResult(
                run_id=expected_run_id,
                report_hash=report_hash,
                reused=True,
                json_report=str(json_path),
                csv_report=str(csv_path),
                metrics=existing.final_metrics,
            )

        report = OfflineBacktestRunner(market_store).run(
            plan=plan,
            dataset_hash=dataset_hash,
            initial_cash_fen=initial_cash_fen,
            execution_config=execution_config,
            manual_event_risk=manual_event_risk,
        )
        persist_report(result_store, report)
        write_report_files(report, json_path=json_path, csv_path=csv_path)
        result_store.checkpoint_wal()
        return BacktestRunCommandResult(
            run_id=report.run_id,
            report_hash=report.report_hash,
            reused=False,
            json_report=str(json_path),
            csv_report=str(csv_path),
            metrics=report.metrics.model_dump(mode="json"),
        )

    def list_runs(self, *, limit: int = 100, offset: int = 0) -> BacktestListResult:
        runs = BacktestResultStore(self._results_database).list_runs(limit=limit, offset=offset)
        return BacktestListResult(runs=runs)

    def prune(
        self,
        *,
        as_of: datetime | None = None,
        batch_size: int = 1_000,
    ) -> RetentionPruneResult:
        cutoff = datetime.now(UTC) if as_of is None else as_of
        return BacktestResultStore(self._results_database).prune_details(
            as_of=cutoff,
            batch_size=batch_size,
        )


def _scope(
    symbols: tuple[str, ...],
    start: date,
    end: date,
    warmup_start: date | None,
) -> DatasetScope:
    resolved_warmup = start - timedelta(days=DEFAULT_WARMUP_CALENDAR_DAYS)
    if warmup_start is not None:
        resolved_warmup = warmup_start
    return DatasetScope(
        symbols=symbols,
        start=start,
        end=end,
        warmup_start=resolved_warmup,
        historical_profile=VERIFIED_HISTORICAL_PROFILE,
    )


def _load_plan(path: str | Path):
    resolved = Path(path).expanduser().resolve()
    document = resolved.read_bytes()
    if resolved.suffix.casefold() in {".yaml", ".yml"}:
        return load_plan_yaml(document)
    if resolved.suffix.casefold() == ".json":
        return load_plan_json(document)
    raise ValueError("plan_path must use .yaml, .yml, or .json")


def _yuan_to_fen(value: Decimal, name: str, *, positive: bool) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise TypeError(f"{name} must be a finite Decimal")
    if value.is_zero():
        if positive:
            raise ValueError(f"{name} must be positive")
        return 0
    if value.is_signed() and not value.is_zero():
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be {qualifier}")

    _sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover - finite guard above
        raise TypeError(f"{name} must be a finite Decimal")
    shifted_exponent = exponent + 2
    integer_digits = digits
    if shifted_exponent < 0:
        fractional_count = -shifted_exponent
        if fractional_count >= len(digits):
            if any(digits):
                raise ValueError(f"{name} must have at most two decimal places")
            integer_digits = ()
        else:
            if any(digits[-fractional_count:]):
                raise ValueError(f"{name} must have at most two decimal places")
            integer_digits = digits[:-fractional_count]
    elif shifted_exponent > 0:
        if len(digits) + shifted_exponent > len(str(_MAX_SUPPORTED_FEN)):
            raise ValueError(f"{name} exceeds the maximum supported amount")
        integer_digits = digits + (0,) * shifted_exponent

    fen = 0
    for digit in integer_digits:
        fen = fen * 10 + digit
        if fen > _MAX_SUPPORTED_FEN:
            raise ValueError(f"{name} exceeds the maximum supported amount")
    if positive and fen == 0:
        raise ValueError(f"{name} must be positive")
    return fen


def _same_path(first: Path, second: Path) -> bool:
    if os.path.normcase(str(first)) == os.path.normcase(str(second)):
        return True
    if first.exists() and second.exists():
        try:
            return os.path.samefile(first, second)
        except OSError:
            return False
    return False


__all__ = [
    "BacktestApplicationService",
    "BacktestListResult",
    "BacktestRunCommandResult",
    "DEFAULT_MARKET_DATABASE",
    "DEFAULT_REPORT_DIRECTORY",
    "DEFAULT_RESULTS_DATABASE",
    "DEFAULT_WARMUP_CALENDAR_DAYS",
    "VERIFIED_HISTORICAL_PROFILE",
]
