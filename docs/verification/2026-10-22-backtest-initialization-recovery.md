# Backtest initialization recovery verification

Date: 2026-10-22 (Asia/Shanghai)

## Incident and evidence

The live local service returned `503 SERVICE_UNAVAILABLE` for `GET /api/v1/backtest-runs?limit=20`. Status reported `DEGRADED`, `canRead=false`, `physicallyDrained=true`, generation 1 and `SERVICE_REPAIR_REQUIRED`. The lifecycle caches a failed generation until explicit repair. List refresh does not reinitialize it.

Read-only inventory found current market/result schemas with no pending migration. Result-store sidecars were an empty WAL and a 32768-byte SHM; strict inventory rejected sidecars as designed, while an isolated copy successfully completed the supported empty-WAL initialization. Cursor-key validation passed. Direct production metadata composition subsequently succeeded against the local stores, without starting execution. An explicit `RETRY_PREPARATION` recovery request then advanced the running service to generation 2, `READ_READY`, `canRead=true` and `reason=null`.

The original initialization exception was not retained with its code or stack and did not reproduce. Its exact underlying trigger remains unknown. Sidecars, corruption, a lock or a timeout must not be presented as a proven original cause. The incident is operationally recovered; the initial trigger is not claimed permanently eliminated.

## Changes

Initialization warnings now record exception type, a bounded uppercase migration error code, OS error numbers, the originating function/line and generation. Exception messages, filesystem paths and source lines are excluded; invalid codes become `UNCLASSIFIED`. Imports needed to identify migration errors occur only on failure. API error/status contracts, explicit recovery, drain ownership and database guards remain unchanged.

## Validation

- The two new regression tests failed before the logging change and passed afterwards. They verify actionable local diagnostics and exclusion of private content from logs/API responses.
- Initialization, thread ownership, service recovery and migration protection: 78 tests passed using an isolated `--basetemp` under `.pytest_cache`.
- Ruff checks passed for the changed Python files.
- Live service status: `READ_READY`, generation 2, `canRead=true`; live run list: HTTP 200 with 5 records.
- An isolated Chrome session opened the real `/backtests` page and displayed 5 rows, zero unavailable messages and zero page exceptions; its screenshot was visually inspected.
- Two existing route-snapshot tests in `test_backtest_service_contract.py` fail because their expected additions omit the existing `/api/v1/backtest-runs/{run_id}/review-context` route. No route or schema was changed here. Initial system-temp setup errors were avoided by using an isolated workspace temporary directory.

The running process was recovered through the existing control endpoint and was not restarted. The new logging takes effect on its next normal restart. No historical job was resumed and no new backtest was submitted. Unrelated proposal documents were left untouched.
