"""One caller-budgeted maintenance pass for jobs and result artifacts."""

from __future__ import annotations

from datetime import datetime

from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.results import BacktestResultStore, RetentionPruneResult


class BacktestJobMaintenance:
    """Spend one bounded row budget across job retention and result cleanup."""

    def __init__(
        self,
        *,
        repository: BacktestJobRepository,
        results: BacktestResultStore,
    ) -> None:
        if not isinstance(repository, BacktestJobRepository):
            raise TypeError("repository must be a BacktestJobRepository")
        if not isinstance(results, BacktestResultStore):
            raise TypeError("results must be a BacktestResultStore")
        if repository.database_path != results.database_path:
            raise ValueError("job and result maintenance must share one database")
        self._repository = repository
        self._results = results

    def prune(
        self,
        *,
        as_of: datetime,
        batch_size: int = 1_000,
    ) -> RetentionPruneResult:
        if type(batch_size) is not int or not 1 <= batch_size <= 1_000:
            raise ValueError("batch_size must be between 1 and 1000")
        with self._repository.maintenance_unit_of_work() as connection:
            jobs = self._repository.prune_job_rows_participant(
                connection,
                as_of=as_of,
                remaining_budget=batch_size,
            )
            results = self._results.prune_result_rows_participant(
                connection,
                as_of=as_of,
                remaining_budget=batch_size - jobs.deleted_count,
            )
        return RetentionPruneResult(
            deleted_count=jobs.deleted_count + results.deleted_count,
            has_more=jobs.has_more or results.has_more,
        )


__all__ = ["BacktestJobMaintenance"]
