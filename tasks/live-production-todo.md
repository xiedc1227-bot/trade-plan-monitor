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

- [ ] `LPC005` — Harden the zero-network/default and one-shot live stock harness.
  - Acceptance: direct `config/app.yaml` token loading, serial single-concurrency, `>=1.25 s` starts, 15-second timeout, no retry, and stop on 429; a stock profile becomes `READY` only from fresh gated evidence with a verified `SourceTimeLabel`, otherwise it remains explicitly blocked or `NOT_RUN_MARKET_WINDOW`.
  - Verify: offline contract tests and candidate secret scan.
  - Blocked evidence: direct configuration loading, seven-day profiles, and the real stock probe are implemented and offline-tested. The local `config/app.yaml` has no Tushare token, so no open-market call was attempted; fresh `READY`/`SourceTimeLabel` evidence is still required.
- [ ] `LPC006` — Compose the certified stock provider and one-batch recoverable runtime.
  - Acceptance: depends on a `READY` LPC005 stock profile; reference refresh/recovery/supervisor work; one `rt_min` batch per deadline for at most ten symbols; no evaluation refetch or network in transaction. Until that dependency passes, production stays `DEGRADED` with no token read, provider call, or actionable deadline coordinator.
  - Verify: provider, request-controller, deadline, recovery, restart, and ten-symbol tests.
  - Blocked evidence: the runtime path is implemented and offline-tested, but production intentionally exposes only the non-actionable `DEGRADED` composition until `LPC005` becomes `READY`.

## Board-Index Runtime

- [ ] `LPC007` — Establish separate live board-index certification evidence.
  - Acceptance: separate authorization/profile/`SourceTimeLabel`; unsuitable market window records `NOT_RUN_MARKET_WINDOW`; no stock evidence is reused.
  - Verify: offline harness tests and, only when gated, the serial live selector.
  - Blocked evidence: the separate authorization, profile, timestamp-label derivation, and per-index `idx_mins`/`index_daily` probe are implemented and offline-tested. The local application configuration has no Tushare token, so no separately authorized open-market observation was performed.
- [ ] `LPC008` — Compose the independent board-index provider and isolated condition failures.
  - Acceptance: each required index is fetched at most once per cutoff; one failure affects only dependent condition paths.
  - Verify: focused market-index runtime and decision tests.
  - Blocked evidence: the independent provider, per-cutoff fetch boundary, and failure isolation are implemented and offline-tested, but actionable production composition remains gated by a fresh `LPC007` profile.

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
  - Blocked evidence: all live-chain-focused gates and the secret scan pass, but the repository-wide offline pytest gate remains red on the pre-existing 252-day backtest performance budget; real stock and board-index gates also remain intentionally incomplete.
