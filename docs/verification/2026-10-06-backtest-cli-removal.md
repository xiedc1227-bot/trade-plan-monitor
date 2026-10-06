# Backtest CLI removal verification — 2026-10-06

## Scope

The user explicitly requested removal without CLI compatibility. Removed the `backtest` command tree (`sync`, `verify`, `run`, `list`, `prune`), dedicated argument parsing and service injection, `BacktestApplicationService`, its command-owned coordinator and shutdown policy, and the synthetic fixture generator's `--run` dispatch. The shared worker factory remains for production Web/API composition. Application startup and unrelated monitoring/AI commands remain.

The implementation plan, task list, proposal, current specifications, README and replay guide were updated in English and Chinese. Historical verification reports and completed task history remain historical evidence. No backtest compatibility alias or replacement CLI was added.

## Verification

- Before implementation, the six new command-surface cases failed against the previous CLI. After removal they pass, including rejection before creating files and preservation of Web startup arguments.
- Focused command/configuration, coordinator, storage, current HTTP replay, packaging and report reconstruction tests: **73 passed**.
- Production composition and data/job/run/result/export API tests: **235 passed, 1 skipped**. The skip requires POSIX ownership semantics and is inapplicable on Windows. Both batches reported the existing Starlette/httpx deprecation warning.
- Scoped Ruff checks, source compilation and `git diff --check` passed. Actual application help excludes `backtest`; fixture help excludes `--run`.
- Removed tests cover retired interfaces. Storage-isolation assertions now use production composition; persisted-report reconstruction is tested directly at the reporting boundary. Current HTTP/job/publication/export coverage remains.

Reproduce the two test batches from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_command_surface.py tests/unit/test_config.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_results.py tests/integration/test_unified_replay_entries.py tests/integration/test_packaging.py tests/integration/test_backtest_runner.py::test_missing_report_files_are_rebuilt_from_materialized_results -q -m 'not live'
.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_data_api.py tests/integration/test_backtest_job_api.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_result_api.py tests/integration/test_backtest_export_api.py tests/integration/test_backtest_exports.py -q -m 'not live'
```

## Boundaries

This intentionally breaks old backtest command invocations and the removed Python facade. Web/API and frozen result formats remain supported. The shared bounded retention service remains an internal domain capability; removal of the `prune` command does not add an automatic cleanup scheduler or replacement public endpoint.

No provider/AI/broker calls, production data changes, dependency changes, commits or pushes were performed for this removal. The new monitor-loop backtest remains planned, not implemented by this change. The complete suite and browser tests were not rerun for this backend removal; the earlier recorded OpenAPI approval-digest mismatch is outside these checks and has not been changed or declared resolved.
