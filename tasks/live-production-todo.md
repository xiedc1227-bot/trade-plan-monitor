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
  - Evidence: the authorized 2026-09-08 09:52:53 Asia/Shanghai open-market run recorded all five stock capabilities as `READY` and `SourceTimeLabel=START`; the profile remains valid through 2026-09-15 09:52:53. QuickSync's omitted fixed `freq` echo is accepted only because the request is fixed to `1MIN`; an explicitly returned non-`1MIN` value still fails closed.
- [x] `LPC006` — Compose the certified stock provider and one-batch recoverable runtime.
  - Acceptance: depends on a `READY` LPC005 stock profile; reference refresh/recovery/supervisor work; one `rt_min` batch per deadline for at most ten symbols; no evaluation refetch or network in transaction. Startup may validate the unified ignored `config/app.yaml`, but until that dependency passes production stays `DEGRADED`, constructs no credentialed provider client, makes no provider request, and creates no actionable deadline coordinator.
  - Verify: provider, request-controller, deadline, recovery, restart, and ten-symbol tests.
  - Evidence: the installed production run started at 2026-09-08 16:54:10.565727 Asia/Shanghai, consumed the fresh five-capability `READY` stock profile, naturally started its scheduled 17:00 deadline at 17:00:00.011473, committed both official-close evaluations, replayed the committed identities with zero results and zero provider requests, and restarted `RUNNING` with Dashboard sequence `11` preserved. This production proof is separate from component tests and live profile generation.

## Board-Index Runtime

- [ ] `LPC007` — Establish separate live board-index certification evidence.
  - Acceptance: separate authorization/profile/`SourceTimeLabel`; unsuitable market window records `NOT_RUN_MARKET_WINDOW`; no stock evidence is reused.
  - Verify: offline harness tests and, only when gated, the serial live selector.
  - Current evidence: the authorized 2026-09-08 15:16:52 Asia/Shanghai run selected `SourceTimeLabel=END`. `000001.SH`, `399001.SZ`, `399006.SZ`, and `000688.SH` are `READY`; `899050.BJ` is `ERROR`. The profile remains valid through 2026-09-15 15:16:52. This supersedes the earlier blanket permission-block conclusion, but does not certify `899050.BJ` or close LPC007.
- [x] `LPC008` — Compose the independent board-index provider and isolated condition failures.
  - Acceptance: within each deadline's immutable due-plan batch, each required index endpoint is called at most once and every dependent plan shares the same `snapshot_hash`; replay of an already committed evaluation identity makes zero provider requests. The 15:00 intraday evaluation and `OFFICIAL_CLOSE` are distinct evaluation kinds and may each make their own revision-aware request even though both cutoffs are 15:00. One index failure affects only dependent condition paths.
  - Verify: focused market-index runtime and decision tests.
  - Evidence: the installed production run consumed the independent profile, kept `899050.BJ=ERROR`, shared `LIVE` Shanghai/Shenzhen snapshots within each due-plan batch, committed two `OFFICIAL_CLOSE` evaluations, and proved committed-identity replay with zero provider requests. Its two-stage 15:00 intraday/`OFFICIAL_CLOSE` exercise called each required index endpoint once per distinct evaluation kind, as allowed by the revision-aware contract.

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
- [ ] `LPC012` — Complete bilingual acceptance report and all gates.
  - Acceptance: exact commands/results/files/risks recorded; all required offline gates and secret scan pass; live results are not overstated.
  - Verify: commands in `tasks/live-production-plan.md`, parity audit, `git diff --check`, and `git status --short`.
  - Blocked evidence: the live-chain-focused gates, secret scan, and LPC006/LPC008 installed-production acceptance pass, but the repository-wide offline pytest gate remains red on the pre-existing 252-day backtest performance budget. Stock certification is current; board-index certification remains partial because `899050.BJ` is `ERROR`.
