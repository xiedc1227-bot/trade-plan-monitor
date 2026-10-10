# Overview retry and stopped monitor investigation

## Scope

Investigate why Monitoring Overview's retry action does not update index trends. Fix the runtime scheduling failure, the secondary monitor-contract `2` health-read failure and a provider quota-message classification defect. No API schema, provider configuration, credential, acquisition interval, trading rule or production database changes are included.

## Observed service state

- The Web process remained available on `127.0.0.1:8765`, while `/api/v1/dashboard` reported lifecycle/coordinator `STOPPED` and reason `RUNTIME_STOPPED`.
- The last production liveness record was `2026-10-08T10:36:46.124891+08:00`. Stored visible-index cutoffs remained `2026-09-16T13:55:00+08:00`.
- The current-day `000001.SH` history query returned `404 NOT_FOUND`. `/api/v1/health` returned `500 INTERNAL_ERROR`.
- `useDashboardMarketIndexTrends.refresh` retries the selected index's stored history read. It does not start provider acquisition or restart the runtime, consistent with `SPEC-monitor-index-trends.md`.

## Root causes and corrections

1. `_reconsider_progress` selects an immediate wake when an installed market deadline is due. `RuntimeProgress.complete_step` reads the wall clock again and previously rejected the resulting negative delay, even for a one-microsecond advance. A diagnostic runtime using a SQLite backup reproduced the exact `ValueError: local reconsideration must be scheduled within 0..30 seconds` from the scheduling loop. The supervisor's bounded replacements use the same failing code.
2. Already elapsed wake times now remain immediately due with zero delay. The 30-second future-wake limit, exact completion token, monotonic overdue detection and stopped-owner protection remain enforced. The correction does not grant a new grace period to an already due wake.
3. The supervisor's legacy `DEGRADED` health projection clears `stopped_at`. Monitor-contract `2` still identifies the physically stopped owner and requires its stop timestamp, producing a validation error. Its read authority now uses the owner's actual health when lifecycle is `STOPPED`, preserving the timestamp and generation without changing the legacy projection.
4. Provider-message classification previously matched permission wording before explicit rate-limit wording. A simulated HTTP `200` application error saying `每分钟最多访问2次，请查看权限说明` incorrectly installed a permission block in both DNS and direct-IP transports. Explicit quota wording now takes precedence and installs the existing cooldown. Structured HTTP authorization failures and genuine permission denials, including denials mentioning a bar frequency, remain permission blocks. This is a reproduced defect; the original October 8 provider message was not retained, so it cannot be established as the cause of that particular provider failure.

## Verification

- Two unit cases failed before correction for one-microsecond and two-second elapsed wakes. A scheduling integration case failed at the same exception before reaching a completed market deadline. A stopped-owner health integration case failed with the missing-stop-timestamp validation error.
- Focused progress/lifecycle/composition checks: **37 passed**.
- Broader monitor scheduling, progress, automatic recovery, status projection/routes and WebSocket checks: **225 passed**. The existing FastAPI test-client deprecation warning remains unrelated.
- Ruff lint and scoped `git diff --check` passed. All five touched Python files already fail Ruff's full-file formatting check in `HEAD`; unrelated formatting was preserved.
- The corrected isolated runtime crossed the real `2026-10-08T11:10:12+08:00` acquisition boundary, published five new index update events to the backup database, and continued running with scheduled progress afterward.
- The quota-message cases failed before correction in both transports. Final provider/client, index acquisition, cooldown and permission-recovery regression checks: **413 passed**. Ruff lint and scoped `git diff --check` passed for the additional adapter and client-test changes.

## October 9 permission verification

- The October 8 isolated acquisition reported `HISTORICAL_MINUTES / BLOCKED_PERMISSION` on `idx_mins` for all five indexes. This was an adapter classification, not proof of an unpurchased entitlement. That backup recorded retry time `2026-10-08T11:15:14.322640+08:00`.
- On October 9, the unchanged configured service `https://api.quicksync.cn` and current Token returned HTTP `200`, provider code `0`, for `trade_cal` and a short `idx_mins` request through both configured IP and DNS. The production-equivalent 30-day historical request also succeeded: 785 rows for the October 8 cutoff and 769 rows for the October 9 cutoff. `rt_idx_min_daily` and `index_daily` succeeded as well. These results supersede the earlier assumption that authorization or credentials must be corrected.
- A fresh runtime against a new production database backup crossed the real `2026-10-09T10:55:12+08:00` acquisition boundary. All five indexes, including the four visible indexes and turnover index `399107.SZ`, subsequently persisted completed bars through `2026-10-09T10:55:00+08:00` with `LIVE` health and no issues. Initial delayed publication for the two Shanghai indexes and one realtime timeout for `399107.SZ` were recovered automatically. The recovery checkpoint table was empty after recovery; no permission block was recorded. The runtime remained `RUNNING / SCHEDULED` until the diagnostic timeout and was then stopped cleanly.
- This investigation introduces no additional endpoint or entitlement requirement. No permission checkpoint, semantic profile or credential was reset or bypassed.

## Production restart and first acquisition

- The user restarted the production service at `2026-10-09T11:01:23.851331+08:00`. Subsequent dashboard and health reads returned HTTP `200`, lifecycle `RUNNING` and standby reason `NO_ACTIVE_PLANS`. Standby does not suppress the independent dashboard-index acquisition path.
- Startup does not immediately acquire the latest display-only index bucket. The scheduler selects future minute deadlines; `_refresh_dashboard_indexes` acquires new index snapshots on a five-minute boundary and retries delayed snapshots afterward. The first new boundary after this restart was `2026-10-09T11:05:12+08:00`, including the 12-second publication grace. Before that acquisition completed, dashboard reads still returned the September 16 snapshots and the current-day history query had no persisted bars. Refreshing the page did not advance the acquisition schedule.
- Production events for the first bucket were recorded from `2026-10-09T11:05:30+08:00` through `2026-10-09T11:06:05.637086+08:00`. The first two Shanghai snapshots were unavailable and the two Shenzhen visible snapshots initially ended at `2026-10-09T11:00:00+08:00`. Automatic retries produced healthy snapshots through `2026-10-09T11:05:00+08:00` for all five indexes by `2026-10-09T11:06:19.734600+08:00`. Both index-recovery state and provider-recovery checkpoint tables were then empty.
- The production history endpoint returned HTTP `200` with 19 current-day five-minute bars from `2026-10-09T09:35:00+08:00` through `2026-10-09T11:05:00+08:00`. A fresh real-browser read subsequently displayed the current-day chart, SSE Composite `3765.10`, change `-1.23%`, cutoff `2026-10-09 11:05:00`, and a confirmed monitor transport.
- The screenshot's old `LIVE` label came from the persisted snapshot's original health; it did not establish freshness at the new observation time. Transport connectivity also does not establish that current-day bars have been acquired. No additional runtime or frontend change was needed for the observed production recovery in this follow-up.

## Operational limits

- Before the user's restart, the October 9 read found the original Web runtime `STOPPED`, last progress at `2026-10-08T10:36:49.179053+08:00`, production index cutoffs at September 16 and `/api/v1/health` returning `500`. That PyCharm-owned process had started at `2026-10-08T10:33:16+08:00`. The later production restart and live-chart verification above supersede the earlier outstanding restart requirement.
- Production data was only read. Diagnostic writes stayed in the ignored `data/retry-diagnostic-20261008/` and `data/permission-diagnostic-20261009/` backups. Provider replies were inspected in memory with credentials redacted, without storing raw replies.
- The full project suite was not run; the reported checks cover the changed monitor and provider boundaries. No frontend or dependency changes were made.
