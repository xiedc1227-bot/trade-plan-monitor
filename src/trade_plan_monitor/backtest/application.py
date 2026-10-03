"""CLI-facing composition for isolated historical synchronization and backtests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import isfinite
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from trade_plan_monitor.backtest.control import (
    BacktestCancellationResult,
    BacktestOperationCancelled,
    BacktestProgress,
    CancellationToken,
)
from trade_plan_monitor.backtest.dataset import (
    BacktestDatasetCoverage,
    DatasetFreezeResult,
    DatasetScope,
    exchange_for_symbol,
)
from trade_plan_monitor.backtest.jobs import (
    BacktestDatasetScopeRequest,
    BacktestDatasetVerificationJobResult,
    BacktestDataSyncJobResult,
    BacktestJobCoordinator,
    BacktestJobOperations,
    BacktestJobRepository,
    BacktestJobRequest,
    BacktestJobResult,
    BacktestJobStatus,
    BacktestRunJobRequest,
    BacktestRunJobResult,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
)
from trade_plan_monitor.backtest.jobs.maintenance import BacktestJobMaintenance
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.models import ExecutionConfig
from trade_plan_monitor.backtest.reporting import (
    _chunks,
    _detail_records,
    _summary_for_report,
)
from trade_plan_monitor.backtest.reporting import (
    write_persisted_report_files as write_report_files,
)
from trade_plan_monitor.backtest.results import (
    BacktestFillRecord,
    BacktestResultStore,
    BacktestRunSummary,
    RetentionPruneResult,
)
from trade_plan_monitor.backtest.run_input import BacktestRunInput
from trade_plan_monitor.backtest.runner import (
    OfflineBacktestRunner,
)
from trade_plan_monitor.backtest.sync import BacktestSyncResult, BlockingBacktestSyncCore
from trade_plan_monitor.backtest.time import SHANGHAI
from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.domain.plan_codec import load_plan_json, load_plan_yaml
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.tushare_client import create_tushare_client
from trade_plan_monitor.market_data.tushare_historical import TushareHistoricalMinuteProvider
from trade_plan_monitor.runtime.clock import SystemClock

DEFAULT_MARKET_DATABASE = Path("data/backtest-market.sqlite3")
DEFAULT_RESULTS_DATABASE = Path("data/backtest-results.sqlite3")
DEFAULT_REPORT_DIRECTORY = Path("backtest-reports")
DEFAULT_WARMUP_CALENDAR_DAYS = 400
VERIFIED_HISTORICAL_PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1
_MAX_SUPPORTED_FEN = (1 << 63) - 1


@dataclass(frozen=True, slots=True)
class _LocalBacktestShutdownPolicy:
    """One auditable source for the local worker's five-second shutdown budget."""

    shutdown_timeout_seconds: float = 5.0
    provider_timeout_seconds: int = 2
    sqlite_busy_timeout_ms: int = 2_000
    cancellation_safe_boundary_seconds: float = 4.5

    def __post_init__(self) -> None:
        if type(self.provider_timeout_seconds) is not int or self.provider_timeout_seconds <= 0:
            raise ValueError("provider_timeout_seconds must be a positive integer")
        if type(self.sqlite_busy_timeout_ms) is not int or self.sqlite_busy_timeout_ms <= 0:
            raise ValueError("sqlite_busy_timeout_ms must be a positive integer")
        numeric_limits = (
            self.shutdown_timeout_seconds,
            self.cancellation_safe_boundary_seconds,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not isfinite(value)
            or value <= 0
            for value in numeric_limits
        ):
            raise ValueError("shutdown policy seconds must be positive numbers")
        if self.shutdown_timeout_seconds != 5.0:
            raise ValueError("local backtest shutdown deadline must be five seconds")
        sequential_wait_seconds = (
            self.provider_timeout_seconds + self.sqlite_busy_timeout_ms / 1_000
        )
        if sequential_wait_seconds > self.cancellation_safe_boundary_seconds:
            raise ValueError("external waits exceed the cancellation safe-boundary budget")
        if self.cancellation_safe_boundary_seconds >= self.shutdown_timeout_seconds:
            raise ValueError("cancellation safe boundary must be below the shutdown deadline")


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


class BacktestJobUseCases(Protocol):
    """One durable request-to-terminal-result boundary shared by CLI and HTTP."""

    def execute(
        self,
        request: BacktestJobRequest,
        *,
        request_id: str | None = None,
    ) -> Awaitable[BacktestJobResult]: ...


class BacktestApplicationService:
    """Keep sync network-capable and every other backtest command local-only."""

    def __init__(
        self,
        *,
        config_path: str | Path,
        market_database: str | Path = DEFAULT_MARKET_DATABASE,
        results_database: str | Path = DEFAULT_RESULTS_DATABASE,
        report_directory: str | Path = DEFAULT_REPORT_DIRECTORY,
        job_use_cases: BacktestJobUseCases | None = None,
    ) -> None:
        self._config_path = Path(config_path).expanduser().resolve()
        self._market_database = Path(market_database).expanduser().resolve()
        self._results_database = Path(results_database).expanduser().resolve()
        self._report_directory = Path(report_directory).expanduser().resolve()
        if job_use_cases is not None and not callable(getattr(job_use_cases, "execute", None)):
            raise TypeError("job_use_cases must expose execute")
        self._job_use_cases = job_use_cases
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
        result = await self._execute_job(
            DataSyncJobRequest(
                scope=_scope_request(scope),
                refresh=refresh,
                allow_network=True,
            ),
            request_id=uuid4().hex,
        )
        if not isinstance(result, BacktestDataSyncJobResult):
            raise RuntimeError("durable sync returned an invalid result kind")
        return BacktestSyncResult.model_validate(result.model_dump(mode="python", exclude={"kind"}))

    def verify(
        self,
        *,
        symbols: tuple[str, ...],
        start: date,
        end: date,
        warmup_start: date | None,
    ) -> DatasetFreezeResult:
        scope = _scope(symbols, start, end, warmup_start)
        result = self._execute_job_sync(DatasetVerifyJobRequest(scope=_scope_request(scope)))
        if not isinstance(result, BacktestDatasetVerificationJobResult):
            raise RuntimeError("durable verification returned an invalid result kind")
        return DatasetFreezeResult(
            ready=result.ready,
            dataset_hash=result.dataset_hash,
            blockers=result.blockers,
        )

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
        research_input_path: str | Path | None = None,
    ) -> BacktestRunCommandResult:
        plan = _load_plan(plan_path)
        from trade_plan_monitor.backtest.research_input import UnifiedResearchInput
        research_input = (None if research_input_path is None else
            UnifiedResearchInput.model_validate_json(Path(research_input_path).read_bytes()))
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
        manifest = BacktestMarketStore(self._market_database).dataset_manifest(dataset_hash)
        run_input = BacktestRunInput.create(
            plan=plan,
            manifest=manifest,
            initial_cash_fen=initial_cash_fen,
            initial_lots=(),
            execution_config=execution_config,
            manual_event_risk=manual_event_risk,
            research_input=research_input,
        )
        result = self._execute_job_sync(BacktestRunJobRequest(run_input=run_input))
        if not isinstance(result, BacktestRunJobResult) or result.run_id != run_input.run_id:
            raise RuntimeError("durable run returned an invalid result identity")
        result_store = BacktestResultStore(self._results_database)
        summary = result_store.get_verified_run(result.run_id)
        if summary is None:
            raise RuntimeError("completed durable run is missing its verified result")
        json_path = self._report_directory / f"{result.run_id}.json"
        csv_path = self._report_directory / f"{result.run_id}.fills.csv"
        if research_input is not None:
            from trade_plan_monitor.backtest.reporting import (
                _atomic_write,
                iter_export_fills,
                iter_export_summary,
            )
            _atomic_write(json_path, b"".join(iter_export_summary(
                result_store, result.run_id, lambda: False)).decode("utf-8"))
            _atomic_write(csv_path, b"".join(iter_export_fills(
                result_store, result.run_id, lambda: False)).decode("utf-8"))
        else:
            write_report_files(
                summary, result_store.list_fills(result.run_id),
                json_path=json_path, csv_path=csv_path)
        result_store.checkpoint_wal()
        return BacktestRunCommandResult(
            run_id=result.run_id,
            report_hash=result.report_hash,
            reused=result.reused,
            json_report=str(json_path),
            csv_report=str(csv_path),
            metrics=summary.final_metrics,
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
        cutoff = datetime.now(SHANGHAI) if as_of is None else as_of
        results = BacktestResultStore(self._results_database)
        return BacktestJobMaintenance(
            repository=BacktestJobRepository(self._results_database),
            results=results,
        ).prune(
            as_of=cutoff,
            batch_size=batch_size,
        )

    async def _execute_job(
        self,
        request: BacktestJobRequest,
        *,
        request_id: str | None = None,
    ) -> BacktestJobResult:
        use_cases = self._job_use_cases or _LocalBacktestJobUseCases(
            config_path=self._config_path,
            market_database=self._market_database,
            results_database=self._results_database,
        )
        result = await use_cases.execute(request, request_id=request_id)
        if not isinstance(
            result,
            (
                BacktestDataSyncJobResult,
                BacktestDatasetVerificationJobResult,
                BacktestRunJobResult,
            ),
        ):
            raise TypeError("durable use cases returned an invalid job result")
        return result

    def _execute_job_sync(self, request: BacktestJobRequest) -> BacktestJobResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("synchronous CLI facade cannot run inside an event loop")
        return asyncio.run(self._execute_job(request))


def create_backtest_job_operations(
    *,
    config_path: str | Path,
    market_store: BacktestMarketStore,
    result_store: BacktestResultStore,
) -> BacktestJobOperations:
    """Bind long-lived worker operations to explicitly owned backtest stores.

    Configuration loading and historical-provider construction remain inside the
    data-sync operation so creating a production composition is local-only.
    """

    if not isinstance(market_store, BacktestMarketStore):
        raise TypeError("market_store must be a BacktestMarketStore")
    if not isinstance(result_store, BacktestResultStore):
        raise TypeError("result_store must be a BacktestResultStore")
    owner = _BacktestWorkerOperationOwner(
        config_path=Path(config_path).expanduser().resolve(),
        market_store=market_store,
        result_store=result_store,
        provider_timeout_seconds=_LocalBacktestShutdownPolicy().provider_timeout_seconds,
    )
    return BacktestJobOperations(
        data_sync=owner.data_sync,
        dataset_verify=owner.dataset_verify,
        backtest_run=owner.backtest_run,
    )


class _BacktestWorkerOperationOwner:
    """Retain the dependencies behind one public worker-operation dispatcher."""

    def __init__(
        self,
        *,
        config_path: Path,
        market_store: BacktestMarketStore,
        result_store: BacktestResultStore,
        provider_timeout_seconds: int,
    ) -> None:
        self._config_path = config_path
        self._market_store = market_store
        self._results = result_store
        self._provider_timeout_seconds = provider_timeout_seconds

    def data_sync(
        self,
        request: BacktestJobRequest,
        *,
        cancellation_token: CancellationToken,
        progress_callback,
    ) -> BacktestJobResult:
        if not isinstance(request, DataSyncJobRequest):
            raise TypeError("sync operation requires DataSyncJobRequest")
        configuration = load_application_config(self._config_path)
        provider_configuration = configuration.tushare.model_copy(
            update={
                "timeout_seconds": min(
                    configuration.tushare.timeout_seconds,
                    self._provider_timeout_seconds,
                )
            }
        )
        clock = SystemClock()
        provider = TushareHistoricalMinuteProvider(
            create_tushare_client(provider_configuration),
            now=clock.now,
            profile=VERIFIED_HISTORICAL_PROFILE,
        )
        result = BlockingBacktestSyncCore(
            provider=provider,
            store=self._market_store,
            today=lambda: clock.now().date(),
        ).sync(
            _dataset_scope(request.scope),
            refresh=request.refresh,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
        )
        return BacktestDataSyncJobResult.model_validate(
            result.model_dump(mode="python", round_trip=True)
        )

    def dataset_verify(
        self,
        request: BacktestJobRequest,
        *,
        cancellation_token: CancellationToken,
        progress_callback,
    ) -> BacktestJobResult:
        if not isinstance(request, DatasetVerifyJobRequest):
            raise TypeError("verification operation requires DatasetVerifyJobRequest")
        outcome = self._market_store.freeze_dataset(
            _dataset_scope(request.scope),
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
        )
        coverage = (
            self._market_store.dataset_summary(outcome.dataset_hash).coverage
            if outcome.dataset_hash is not None
            else BacktestDatasetCoverage(
                symbol_count=len(request.scope.symbols),
                trading_day_count=0,
                calendar_row_count=0,
                minute_day_count=0,
                minute_bar_count=0,
                daily_limit_row_count=0,
                daily_bar_row_count=0,
                blockers=outcome.blockers,
            )
        )
        return BacktestDatasetVerificationJobResult(
            ready=outcome.ready,
            dataset_hash=outcome.dataset_hash,
            coverage=coverage,
            blockers=outcome.blockers,
        )

    def backtest_run(
        self,
        request: BacktestJobRequest,
        *,
        cancellation_token: CancellationToken,
        progress_callback,
    ) -> BacktestJobResult:
        if not isinstance(request, BacktestRunJobRequest):
            raise TypeError("run operation requires BacktestRunJobRequest")
        run_input = request.run_input
        report = OfflineBacktestRunner(self._market_store).run(
            plan=run_input.plan_snapshot,
            dataset_hash=run_input.dataset_hash,
            initial_cash_fen=run_input.initial_cash_fen,
            initial_lots=run_input.initial_lots,
            execution_config=run_input.execution_config,
            manual_event_risk=run_input.manual_event_risk,
            plan_version_id=run_input.plan_version_id,
            research_input=run_input.research_input,
            cancellation_token=cancellation_token,
        )
        if isinstance(report, BacktestCancellationResult):
            raise BacktestOperationCancelled(report.phase, report.last_safe_event_id)
        cancellation_token.raise_if_cancelled("RUN_FINALIZE")
        existing = self._results.get_verified_run(run_input.run_id)
        if existing is not None:
            report_hash = existing.assumptions.get("reportHash")
            if not isinstance(report_hash, str):
                raise RuntimeError("stored completed run is missing reportHash")
            return BacktestRunJobResult(
                run_id=run_input.run_id,
                report_hash=report_hash,
                reused=True,
            )

        summary = _summary_for_report(
            report,
            completed_at=report.daily_equity[-1].marked_at,
            run_input=run_input,
        )
        fills = tuple(BacktestFillRecord.from_value(fill, version="v2") for fill in report.fills)
        self._results.record_verified_run(summary, run_input=run_input)
        for start in range(0, len(fills), 1_000):
            cancellation_token.raise_if_cancelled("RUN_FINALIZE")
            self._results.record_fills(run_input.run_id, fills[start : start + 1_000])
        for batch in _chunks(_detail_records(report, version="v2"), 100):
            cancellation_token.raise_if_cancelled("RUN_FINALIZE")
            self._results.record_details(run_input.run_id, batch)
        cancellation_token.raise_if_cancelled("RUN_REPORT_HANDOFF")
        progress_callback(
            BacktestProgress(
                phase="RUN_REPORT_HANDOFF",
                completed_units=1,
                total_units=1,
            )
        )
        return BacktestRunJobResult(
            run_id=run_input.run_id,
            report_hash=report.report_hash,
            reused=False,
        )


class _LocalBacktestJobUseCases:
    """Execute CLI commands through the same durable repository/coordinator path."""

    def __init__(
        self,
        *,
        config_path: Path,
        market_database: Path,
        results_database: Path,
    ) -> None:
        self._config_path = config_path
        self._shutdown_policy = _LocalBacktestShutdownPolicy()
        self._market_store = BacktestMarketStore(
            market_database,
            busy_timeout_ms=self._shutdown_policy.sqlite_busy_timeout_ms,
        )
        self._repository = BacktestJobRepository(
            results_database,
            busy_timeout_ms=self._shutdown_policy.sqlite_busy_timeout_ms,
        )
        self._results = BacktestResultStore(
            results_database,
            busy_timeout_ms=self._shutdown_policy.sqlite_busy_timeout_ms,
        )
        self._operations = create_backtest_job_operations(
            config_path=self._config_path,
            market_store=self._market_store,
            result_store=self._results,
        )

    async def execute(
        self,
        request: BacktestJobRequest,
        *,
        request_id: str | None = None,
    ) -> BacktestJobResult:
        receipt = self._repository.submit(
            request,
            f"cli-{uuid4().hex}",
            request_id=request_id,
        )
        view = self._repository.get(receipt.job_id)
        if view is None:
            raise RuntimeError("durable job disappeared after submission")
        if view.status is not BacktestJobStatus.COMPLETED:
            coordinator = BacktestJobCoordinator(
                repository=self._repository,
                operations=self._operations,
                shutdown_timeout_seconds=self._shutdown_policy.shutdown_timeout_seconds,
            )
            await coordinator.start()
            try:
                while True:
                    view = self._repository.get(receipt.job_id)
                    if view is None:
                        raise RuntimeError("durable job disappeared during execution")
                    if view.status in {
                        BacktestJobStatus.COMPLETED,
                        BacktestJobStatus.FAILED,
                        BacktestJobStatus.CANCELLED,
                    }:
                        break
                    await asyncio.sleep(0.01)
            finally:
                await coordinator.shutdown()
        if view.status is BacktestJobStatus.FAILED:
            raise RuntimeError(f"{view.error_code}: {view.error_message}")
        if view.status is BacktestJobStatus.CANCELLED:
            raise RuntimeError("BACKTEST_OPERATION_CANCELLED")
        if view.status is not BacktestJobStatus.COMPLETED or view.result is None:
            raise RuntimeError("durable job did not produce a terminal result")
        return view.result


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


def _scope_request(scope: DatasetScope) -> BacktestDatasetScopeRequest:
    return BacktestDatasetScopeRequest(
        symbols=scope.symbols,
        start=scope.start,
        end=scope.end,
        warmup_start=scope.warmup_start,
        historical_profile=scope.historical_profile,
        adjustment_policy=scope.adjustment_policy,
    )


def _dataset_scope(scope: BacktestDatasetScopeRequest) -> DatasetScope:
    return DatasetScope(
        symbols=scope.symbols,
        start=scope.start,
        end=scope.end,
        warmup_start=scope.warmup_start,
        historical_profile=scope.historical_profile,
        adjustment_policy=scope.adjustment_policy,
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
    "create_backtest_job_operations",
]
