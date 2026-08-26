# ADR 0001: Isolate Durable Backtest Jobs from Deterministic Results

> Canonical agent-facing English version. The human-review Chinese version is `0001-isolate-backtest-jobs-from-results.zh-CN.md`; both documents must remain semantically equivalent.

- Status: `Accepted`
- Date: `2026-08-26`
- Initiative: `backtest`
- Modules: `backtest-engine`, `backtest-results`, `backtest-jobs`, `backtest-api`, `backtest-web`

## Context

Historical synchronization, dataset verification, and multi-day replay can exceed an HTTP request lifetime and must survive a local process restart. At the same time, an identical research input must retain one deterministic identity regardless of how many times execution is submitted, cancelled, interrupted, or retried.

The project already isolates `backtest-market.sqlite3` from `backtest-results.sqlite3` and from the live monitor database. Adding a third queue database or treating failed attempts as immutable research results would increase coordination risk and can prevent a cancelled deterministic input from later completing.

## Decision

1. `backtest-engine` owns the exact versioned `run_id` preimage. An empty normalized initial-lot list preserves the byte-identical `backtest-run-v1` preimage; a non-empty public initial-lot list selects `backtest-run-v2` and uses normalized `BacktestInitialLotInput` values with stable `lotKey`. `planVersionId` is lookup/audit metadata and participates in neither identity.
2. `job_id` identifies one durable submitted operation. `attempt` identifies a worker-claim generation within that job and increments during lease recovery without changing `job_id`. Resubmitting a terminal failed or cancelled job creates a new `job_id` while retaining the same `run_id` for unchanged research input.
3. New `backtest_run` writes publish materialized `COMPLETED` results only. Failed and cancelled attempts remain bounded diagnostic job records and do not occupy `run_id`.
4. Durable job records live in `backtest-results.sqlite3`; no third database is introduced. One local coordinator owns one active execution slot across `DATA_SYNC`, `DATASET_VERIFY`, and `BACKTEST_RUN`. Blocking provider, SQLite, and replay work runs only in a dedicated bounded `ThreadPoolExecutor(max_workers=1)`, never in the event loop or default executor; coordination, polling, lease recovery, and heartbeat remain on the event loop.
5. `backtest-jobs` owns the shared result-database Unit of Work. It validates the current job claim and invokes a bounded `backtest-results` transaction participant; `backtest-results` never imports the job coordinator. Result materialization, transition of the owning `BACKTEST_RUN` job to `COMPLETED`, and active-slot release occur atomically in one short result-database transaction. Market-cache progress remains independently idempotent; there is no cross-database transaction.
6. `backtest-jobs` also owns the only production maintenance Unit of Work and one total `batchSize <= 1000` prune budget across job, stage, and result-detail rows. It passes only the remaining budget to the `backtest-results` participant, which never prunes job rows or starts another budget.
7. A Web run submission may read exactly one immutable plan version in one read-only live-store transaction. It validates and durably persists the canonical plan snapshot before responding, performs zero live-store writes, and gives the post-durable worker/replay no live-store read or write capability. Direct CLI runs receive an explicit `--plan` file.
8. HTTP handlers otherwise validate and enqueue work only. The first Web release observes durable job state through bounded REST polling and adds no backtest WebSocket event.
9. A `DATA_SYNC` request persists literal `allowNetwork: true` in its canonical request and `requestHash`, plus server-authored `networkAuthorizedAt` and `requestId`, as a job-scoped audited authorization fact. Credentials are resolved only from current server configuration at execution time and are never persisted; a new job requires new explicit authorization.
10. Persisted requests contain canonical resource identities and a validated plan snapshot, never credentials, arbitrary file paths, raw provider bodies, stack traces, or worker claim tokens.
11. Before enabling completed-only publication, migration preflight requires zero legacy `backtest_run` rows with `FAILED` or `CANCELLED`. Any nonzero count fails closed before schema mutation with `LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION`; conversion to job diagnostics requires a separately approved offline migration.
12. Crash recovery replays immutable input from the frozen beginning and relies on content-addressed/idempotent writes. Strategy event-cursor resume remains deferred acceptance work.

## Alternatives Considered

### Execute inside CLI or HTTP requests

Rejected for the Web path because cancellation, restart recovery, bounded concurrency, and reliable progress cannot be guaranteed across request lifetimes. The CLI remains a compatibility adapter over the same domain capabilities.

### Use `run_id` as the job identity

Rejected because a failed or cancelled job would either block a later successful resubmission or require mutating an immutable result identity.

### Add a third queue database

Rejected because job/result publication would require another coordination boundary without improving the single-host first release.

### Reuse the monitor WebSocket

Rejected for the first release because REST polling provides authoritative recovery after refresh or sleep without expanding the live-monitor event contract. A later event hint may be proposed separately.

### Support portfolio/shared-cash replay now

Rejected from the first release. One run continues to mean one reviewed plan version and one symbol; a dataset may still cache facts for 1–10 symbols.

## Consequences

- Cancellation and operational failure remain distinguishable from valid research output.
- The same deterministic input can complete after a failed, cancelled, or reclaimed attempt without duplicating a result.
- One execution slot favors predictable local resource use over throughput; portfolio and distributed workers require a new decision.
- The dedicated `ThreadPoolExecutor(max_workers=1)` keeps blocking work off HTTP polling and heartbeat paths while making lifecycle shutdown an explicit responsibility.
- API and Vue contracts must expose job state separately from completed-result availability.
- Recovery can repeat deterministic CPU work, but it does not depend on an unimplemented event cursor and must not duplicate provider facts, fills, or details.
- Existing readable `BacktestRunStatus.FAILED` and `BacktestRunStatus.CANCELLED` values remain compatibility-only and are not the new write path; a database containing such rows cannot adopt completed-only publication without an approved migration.
- Job-scoped network authorization can survive process recovery without storing or transferring a credential.

## Security and Operational Effects

The job boundary is an untrusted command boundary. Submission uses bounded typed inputs, idempotency claims, sanitized fixed errors, persisted job-scoped network authorization for sync, and dependency-injected services. The plan-resolution transaction is read-only; after durable submission the worker cannot access live state, notifications, brokers, or caller-supplied database paths. Credentials are never persisted. Logs and metrics use bounded identifiers and never expose secrets or raw provider content.

## Reversal and Migration

Before implementation, rejection requires only revising the proposed specifications and this ADR. The completed-only migration must first pass the zero-row legacy terminal gate; `LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION` blocks schema mutation until a separate offline conversion is approved. After implementation, changing a `backtest-run-v1`/`backtest-run-v2` preimage, concurrency, storage placement, transport, or result-status semantics requires a new superseding ADR plus a migration that preserves existing `run_id`, exports, retained results, and job audit records. Rollback may stop the worker and hide the new API/Web entry points without deleting immutable market data or completed results.

## Review Status

The user accepted this durable-job/deterministic-result isolation decision and approved the `local-web` Backtest Extension Boundary on 2026-08-26. This ADR is therefore `Accepted` with decision date `2026-08-26`. The later API/engine/results/jobs consistency corrections did not change this storage, identity-separation, or execution-ownership decision; the corrected aggregate detailed-specification set and Section 15 of the bilingual implementation plan were approved on 2026-08-26. The Section 15 approval authorizes only generating the bilingual `BT009`–`BT050` task list. The generated task list still requires separate explicit approval; schema or API changes, implementation, commit, push, dependency installation, and any network access remain unauthorized.
