# Index close recovery verification

## Scope and cause

On 2026-09-14 at 15:20:16 +08:00, `000001.SH` persisted a `BLOCKED` snapshot with `PROVIDER_UNAVAILABLE`. The original exception was not recovered from available logs. An independent acquisition later succeeded. No pending index recovery remained in SQLite.

With no eligible plan evaluation, `_refresh_dashboard_indexes` previously acquired indexes only for `close_attempt == 1`. The 16:00 and 17:00 close tasks therefore could not replace the failed 15:20 snapshot. A deterministic regression reproduced both missed recovery opportunities.

## Changes and boundaries

- Every scheduled `OFFICIAL_CLOSE` task now refreshes dashboard indexes when no eligible plan evaluation is selected. Empty `plans=()` preserves display-only behavior and does not evaluate plans or send alerts.
- Normal index acquisition, publication-lag recovery, and transient recovery retain at least 2 official daily bars, so a newly available current-day close does not displace the previous session needed by the dashboard.
- Dashboard `priorClosePoints` and `sessionChangeRatio` now use the last official daily bar strictly before the cutoff date. A missing prior session yields `BLOCKED` with `MISSING_OFFICIAL_DAILY_BAR` and unavailable headline facts.
- Immutable stored snapshots and their hashes remain unchanged; the previous-close correction belongs to the read projection. Existing transient retry limits, provider pacing, and plan evaluation rules remain unchanged.

## Validation

The 16:00 and 17:00 recovery tests failed before the scheduling change and passed afterward. Both previous-close regression cases failed before the projection change and passed afterward. The existing simulated close test now advances its clock before executing the future deadline.

Across `test_live_pipeline_acceptance.py`, `test_market_index_runtime.py`, `test_market_index_snapshots.py`, `test_market_index_web.py`, `test_tushare_market_index.py`, `test_monitor_runtime.py`, and `test_persistent_monitor_read_service.py`, 186 selected tests passed. The main run passed 183 tests; a separate run passed the 3 remaining unaffected startup variants. Ruff and `git diff --check` passed. The complete repository suite was not run.

Two additional selected tests failed and reproduced the same failures with the original `HEAD` version of `runtime/production.py` loaded:

- `test_market_index_persistence_reuses_an_older_canonical_content_revision`: the head timestamp remains 10:36 instead of the expected 10:38.
- `test_startup_batches_persisted_pending_closes_by_date_and_shared_index[index_error]`: the reference snapshot is `LIVE` instead of the expected `BLOCKED`.

These pre-existing failures were not disabled or altered. They remain separate investigation items.

## Local recovery outcome

A one-time acquisition for `000001.SH` reused the existing failed cutoff and fact requests, required 48 five-minute bars and 2 official daily bars, and published only after obtaining a validated `LIVE` snapshot. The existing persistence transaction appended one `market.index.updated` event (sequence 633). No plan evaluation or notification was executed.

The existing PyCharm `dev` backend was restarted; `/api/v1/health` reported `RUNNING` with `startedAt` 2026-09-14T17:03:05.929554+08:00. `/api/v1/dashboard` and the browser confirmed:

- `000001.SH`: `LIVE`, close 3885.333, prior close 3888.1106, displayed change -0.07%.
- Completed data through 2026-09-14T15:00:00+08:00.
- Shanghai/Shenzhen turnover displayed as 1.61 trillion CNY.

The next poll is 2026-09-15T09:31:12+08:00. Later close recovery depends on successful provider responses at the scheduled attempts; this change does not add unlimited after-hours retries.
