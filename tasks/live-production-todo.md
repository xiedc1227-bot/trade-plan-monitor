# Task List: live-production-chain

> Canonical English task list. The Chinese review copy is `live-production-todo.zh-CN.md`; IDs, commands, files, and acceptance criteria stay aligned.

## P0 Contract

- [x] `LPC001` — Register the new capability map and non-overlapping `LPC` namespace.
  - Acceptance: no historical task ID is reused; live index certification has the new identity `LPC007`.
  - Verify: bilingual file structure and task-ID scan.
- [x] `LPC002` — Accept ADR 0004 and freeze `SPEC-live-production-chain`.
  - Acceptance: typed 200 unavailable union, true 503 faults, migration/transaction/provider/Web boundaries are explicit.
  - Verify: bilingual section, enum, path, command, and threshold parity.

## Persistent State

- [x] `LPC003` — Add migration 0009 and exact preservation tests.
  - Acceptance: six additive tables/heads exist; prior identities, rows, and hashes are byte-stable; unsafe downgrade refuses before DDL.
  - Verify: focused migration and repository pytest.
- [x] `LPC004` — Persist complete evaluation projections atomically and read them across restart.
  - Acceptance: claim/result/head/risk/episode/event/outbox/pending-close share one transaction; rollback and publish-after-commit tests pass; hash-only history is unavailable.
  - Verify: focused transaction, persistent-read, and restart pytest.

## Stock Runtime

- [x] `LPC005` — Harden the zero-network/default and one-shot live stock harness.
  - Acceptance: direct `config/app.yaml` token loading, serial single-concurrency, `>=1.25 s` starts, 15-second timeout, no retry, and stop on 429; a stock profile becomes `READY` only from fresh gated evidence with a verified `SourceTimeLabel`, otherwise it remains explicitly blocked or `NOT_RUN_MARKET_WINDOW`.
  - Verify: offline contract tests and candidate secret scan.
  - Evidence: the 2026-09-08 09:52:53 `SourceTimeLabel=START` conclusion was an insufficient early-market inference and is superseded. On 2026-09-09, two 13:10 attempts and bounded retries correctly recorded `current_day_minutes=ERROR/UNVERIFIED` under the old label logic; each redacted diagnostic had 139 rows from `09:30` through `13:18`, included `11:30`, and excluded `13:00`. The strict corrected run at `14:48:40.405317+08` certified all five capabilities `READY` with `SourceTimeLabel=END`, valid through `2026-09-16 14:48:40.405317+08`. It proves an independent `09:30` snapshot followed by end-labeled minutes. QuickSync's omitted fixed `freq` echo is accepted only because the request is fixed to `1MIN`; an explicitly returned non-`1MIN` value still fails closed.
- [x] `LPC006` — Compose the certified stock provider and one-batch recoverable runtime.
  - Acceptance: depends on a `READY` LPC005 stock profile; reference refresh/recovery/supervisor work; one `rt_min` batch per deadline for at most ten symbols; no evaluation refetch or network in transaction. Startup may validate the unified ignored `config/app.yaml`, but until that dependency passes production stays `DEGRADED`, constructs no credentialed provider client, makes no provider request, and creates no actionable deadline coordinator.
  - Verify: provider, request-controller, deadline, recovery, restart, and ten-symbol tests.
  - Evidence: the installed production run started at 2026-09-08 16:54:10.565727 Asia/Shanghai, consumed the fresh five-capability `READY` stock profile, naturally started its scheduled 17:00 deadline at 17:00:00.011473, committed both official-close evaluations, replayed the committed identities with zero results and zero provider requests, and restarted `RUNNING` with Dashboard sequence `11` preserved. This production proof is separate from component tests and live profile generation.

## Board-Index Runtime

- [x] `LPC007` — Establish separate live board-index certification evidence for the current trading scope.
  - Acceptance: separate authorization/profile/`SourceTimeLabel`; unsuitable market window records `NOT_RUN_MARKET_WINDOW`; no stock evidence is reused. The current scope contains `000001.SH`, `399001.SZ`, `399006.SZ`, and `000688.SH`. `899050.BJ` remains a known identity but is `DEFERRED` until BSE stocks enter the trading scope, and certification makes no provider request for it.
  - Verify: offline harness tests and, only when gated, the serial live selector.
  - Evidence: the 2026-09-09 renewal observed at `13:10:41.07832+08` certified all four in-scope indexes as `READY` with `SourceTimeLabel=END`, valid through `2026-09-16 13:10:41.07832+08`. `899050.BJ` remains `DEFERRED` and receives no `idx_mins`, `rt_idx_min_daily`, or `index_daily` request. Index and stock certification both use `config/app.yaml`; the configured `connect_ip` succeeds without a temporary per-run proxy change.
- [x] `LPC008` — Compose the independent board-index provider and isolated condition failures.
  - Acceptance: within each deadline's immutable due-plan batch, each required index endpoint is called at most once and every dependent plan shares the same `snapshot_hash`; replay of an already committed evaluation identity makes zero provider requests. The 15:00 intraday evaluation and `OFFICIAL_CLOSE` are distinct evaluation kinds and may each make their own revision-aware request even though both cutoffs are 15:00. One index failure affects only dependent condition paths.
  - Verify: focused market-index runtime and decision tests.
  - Evidence: the installed production run consumed the independent profile, shared `LIVE` Shanghai/Shenzhen snapshots within each due-plan batch, committed two `OFFICIAL_CLOSE` evaluations, and proved committed-identity replay with zero provider requests. Its two-stage 15:00 intraday/`OFFICIAL_CLOSE` exercise called each required index endpoint once per distinct evaluation kind, as allowed by the revision-aware contract. A deferred BSE 50 profile fails before request control if requested.

## Web Availability

- [x] `LPC009` — Implement typed availability in FastAPI/OpenAPI/generated TypeScript.
  - Acceptance: successful shapes remain compatible; normal unavailable responses are 200; true storage/composition failures are 503.
  - Verify: Web API, OpenAPI snapshot, and generation checks.
- [x] `LPC010` — Replace WEBF13 Health fallback and lazy-load ECharts.
  - Acceptance: `SNAPSHOT`/`UNAVAILABLE`/`STALE`/`DISCONNECTED` are distinct; unavailable opens no socket; non-chart routes fetch no chart chunk.
  - Verify: focused Vitest, type-check, Chrome Playwright with zero console error/warning and `requestfailed`.

## Integration and Evidence

- [x] `LPC011` — Run installed production restart and browser acceptance.
  - Acceptance: persisted projections survive restart; empty/no-plan/first-result remain honest; runtime supervision remains visible.
  - Verify: production-composition pytest and installed loopback Chrome journey.
- [x] `LPC012` — Complete bilingual acceptance report and all gates.
  - Acceptance: exact commands/results/files/risks recorded; all required offline gates and secret scan pass; live results are not overstated.
  - Verify: commands in `tasks/live-production-plan.md`, parity audit, `git diff --check`, and `git status --short`.
  - Evidence: the performance root cause was `EvaluationContext.current_bucket_minutes` scanning all day minutes for every evaluation. Profiling the first symbol recorded `833,504,828` calls, `35.57s` cumulative attribute time, and `7,493,472` `five_minute_bucket_end` calls. The repair reads the last five values directly from validated ordered complete five-minute buckets; the regression is old `105` calls versus new `<=2`. The exact capacity node passes as `1 passed, 1 warning in 1443.66s`, proving ten symbols each `<=120s` and the resource ceilings. A later 100,000-fill export tail failure was repaired without changing the `5 MiB/s` floor: the `(run_id, fill_id)` verification index removes SQLite's temporary sort and the same read snapshot no longer repeats an already-proven timestamp/domain check. The unchanged node then measured `7.485 MiB/s` minimum throughput, `299.645 MiB` database plus WAL, and `36,864` bytes export-memory growth. The final complete unexcluded repository gate passes as `2326 passed, 1 skipped, 1 warning in 2761.04s`; bilingual evidence, focused live-chain gates, browser E2E, static checks, and the secret scan are also green.
