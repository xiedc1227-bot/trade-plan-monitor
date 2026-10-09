"""Worker operations for isolated historical synchronization and backtests."""

from __future__ import annotations

from pathlib import Path

from trade_plan_monitor.backtest.control import (
    BacktestCancellationResult,
    BacktestOperationCancelled,
    BacktestProgress,
    CancellationToken,
)
from trade_plan_monitor.backtest.dataset import (
    BacktestDatasetCoverage,
    DatasetScope,
)
from trade_plan_monitor.backtest.jobs import (
    BacktestDatasetScopeRequest,
    BacktestDatasetVerificationJobResult,
    BacktestDataSyncJobResult,
    BacktestJobOperations,
    BacktestJobRequest,
    BacktestJobResult,
    BacktestRunJobRequest,
    BacktestRunJobResult,
    DatasetVerifyJobRequest,
    DataSyncJobRequest,
)
from trade_plan_monitor.backtest.jobs.models import MonitorLoopJobRequest
from trade_plan_monitor.backtest.loop_replay import run_frozen_loop
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.reporting import (
    _chunks,
    _detail_records,
    _summary_for_report,
)
from trade_plan_monitor.backtest.results import (
    BacktestFillRecord,
    BacktestResultStore,
)
from trade_plan_monitor.backtest.runner import (
    OfflineBacktestRunner,
)
from trade_plan_monitor.backtest.sync import BlockingBacktestSyncCore
from trade_plan_monitor.config import load_application_config
from trade_plan_monitor.market_data.historical_provider import HistoricalMinuteProfile
from trade_plan_monitor.market_data.tushare_client import create_tushare_client
from trade_plan_monitor.market_data.tushare_historical import TushareHistoricalMinuteProvider
from trade_plan_monitor.runtime.clock import SystemClock

_PROVIDER_TIMEOUT_SECONDS = 2
VERIFIED_HISTORICAL_PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1


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
        provider_timeout_seconds=_PROVIDER_TIMEOUT_SECONDS,
    )
    return BacktestJobOperations(
        data_sync=owner.data_sync,
        dataset_verify=owner.dataset_verify,
        backtest_run=owner.backtest_run,
        after_completion=owner.after_completion,
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
        if isinstance(request, MonitorLoopJobRequest):
            cancellation_token.raise_if_cancelled("RUN_DAY_TRANSITION")
            report = self._results.get_loop_report(request.input_reference.run_id)
            reused = report is not None
            if report is None:
                report = run_frozen_loop(
                    self._results,
                    request.input_reference,
                    cancellation_token=cancellation_token,
                    progress_callback=progress_callback,
                )
            return BacktestRunJobResult(
                run_id=report.run_id, report_hash=report.report_hash, reused=reused
            )
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

    def after_completion(
        self, result, *, repository, cancellation_token: CancellationToken
    ) -> None:
        """Existing bounded maintenance on the same owned worker, after publication."""
        if not isinstance(result, BacktestRunJobResult):
            return
        from datetime import datetime

        from trade_plan_monitor.backtest.jobs.maintenance import BacktestJobMaintenance
        from trade_plan_monitor.backtest.time import SHANGHAI

        maintenance = BacktestJobMaintenance(
            repository=repository,
            results=self._results,
        )
        while not cancellation_token.cancelled:
            if not maintenance.prune(as_of=datetime.now(SHANGHAI)).has_more:
                break


def _dataset_scope(scope: BacktestDatasetScopeRequest) -> DatasetScope:
    return DatasetScope(
        symbols=scope.symbols,
        start=scope.start,
        end=scope.end,
        warmup_start=scope.warmup_start,
        historical_profile=scope.historical_profile,
        adjustment_policy=scope.adjustment_policy,
    )


__all__ = ["create_backtest_job_operations"]
