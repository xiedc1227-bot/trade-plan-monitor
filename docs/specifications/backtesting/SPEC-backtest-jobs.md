# Spec: backtest-jobs

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-backtest-jobs.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Run `DATA_SYNC`, `DATASET_VERIFY`, and `BACKTEST_RUN` asynchronously through one durable local worker slot with persistent progress, atomic idempotency, cooperative cancellation, lease-based crash recovery, and no blocking work inside HTTP request handlers.

## Relationship and Scope

`backtest-jobs` orchestrates `backtest-data`, `backtest-engine`, and `backtest-results`. It owns durable operation identity, worker-claim generations, queue admission, worker ownership, progress, cancellation, recovery, terminal diagnostics, and result/job atomic publication. It does not own provider mapping, strategy/execution formulas, canonical completed results, HTTP schemas, Vue state, live monitoring, or notifications.

Jobs share `backtest-results.sqlite3` with result records but use their own tables and prefixes; no third backtest database is introduced. There is one in-process coordinator and one durable execution slot. Synchronous provider/replay work and operation-thread progress persistence run in one dedicated bounded `ThreadPoolExecutor(max_workers=1)`, while event-loop-facing potentially blocking SQLite coordination calls run in a second coordinator-owned `ThreadPoolExecutor(max_workers=1)`. Neither executor is the default executor, neither nests another executor, and the repository executor cannot increase durable operation concurrency above one. Subprocesses, distributed workers, automatic logical retries, and durable operation concurrency above one are outside the first release.

## Commands

No new direct worker command is public in the first release. The production FastAPI lifespan starts and stops one explicitly injected coordinator plus both owned executors. Coordination, polling, lease-recovery, and heartbeat decisions remain on the event loop; their event-loop-facing synchronous SQLite calls run only in the owned repository executor, operation progress persists from the operation executor, and execution receives a cross-thread-safe cancellation token. Shutdown stops new claims, requests cancellation, closes queued futures, and releases both executors after the bounded provider/SQLite/safe-boundary contract, including when the background task fails. `asyncio.to_thread`, the default executor, and untracked request tasks are forbidden. Backtest CLI adapters and their standalone command-owned coordinator are removed; the Web/API lifespan owns job execution. The shared maintenance transaction remains an internal domain capability; removal does not add an automatic cleanup scheduler or a replacement public command.

## Job Model

Job kinds are `DATA_SYNC`, `DATASET_VERIFY`, and `BACKTEST_RUN`. Public status is closed over:

```text
QUEUED
RUNNING
CANCEL_REQUESTED
COMPLETED
FAILED
CANCELLED
```

Legal transitions are `QUEUED -> RUNNING`, `QUEUED -> CANCELLED`, `RUNNING -> CANCEL_REQUESTED`, `RUNNING -> COMPLETED`, `RUNNING -> FAILED`, and `CANCEL_REQUESTED -> CANCELLED`. Terminal states never transition. An already materialized identical run may be inserted directly as a `COMPLETED` reused receipt without occupying the worker slot.

`job_id` identifies one durable submission/operation. `attempt=0` means no worker has claimed the job, including queued, queued-cancelled, and immediately reused completed jobs. The first claim sets `attempt=1`; each lease recovery increments it without changing `job_id`, with at most three total claim generations. `run_id` identifies deterministic completed research output. Resubmitting a terminal failed/cancelled `BACKTEST_RUN` creates a new `job_id` but retains the same `run_id`.

## Public Contracts

`BacktestJobView` contains `jobId`, `kind`, `status`, `requestHash`, optional `runId`/`datasetHash`, structured `phase`, `completedUnits`, optional `totalUnits`, `attempt`, `revision`, `createdAt`, `startedAt`, `updatedAt`, `finishedAt`, `cancelRequestedAt`, `reused`, and sanitized `errorCode`/`errorMessage`. Every persisted/public lifecycle, authorization, idempotency, claim/lease, heartbeat, and deadline datetime uses aware `Asia/Shanghai` RFC 3339 text in exact `YYYY-MM-DDTHH:MM:SS.ffffff+08:00` form; `Z`, offsetless values, overprecision, and other offsets are rejected. Elapsed scheduling may use an injected monotonic clock, but no monotonic value is persisted or exposed as a wall-clock timestamp.

Application operations are `submit(request, idempotency_key)`, `get(job_id)`, `list(filters, limit, cursor)`, and `request_cancel(job_id, idempotency_key)`. Submission and cancellation atomically bind the key to their canonical request hash and canonical response in the same Unit of Work as the resource/state change. New public run intent resolution additionally uses atomic `claim_run_submission`, renewable `renew_run_submission`, generation-fenced finalize/release, and the same jobs-owned maintenance transaction. Internal worker operations are `claim_next`, `heartbeat`, `update_progress`, `complete`, `fail`, `acknowledge_cancel`, `recover_expired`, and `prune_jobs`.

Canonical request payload is at most 256 KiB and contains only typed resource values. A run submission stores an immutable validated plan snapshot and normalized `BacktestInitialLotInput`; it never stores a plan/report/database path. A `DATA_SYNC` request persists literal `allowNetwork: true` inside canonical request JSON and `requestHash`, plus server-authored `networkAuthorizedAt` and submitting `requestId`. This authorizes recovery of that job only; no credential is persisted, and a new job requires a new explicit authorization. Public error text is at most 512 characters. Claim tokens and raw diagnostic context are never public.

## Idempotency and Admission

`Idempotency-Key` is 1–128 allowlisted characters. Submission atomically inserts or replays under a unique constraint; a check-then-insert sequence is forbidden.

- Same key and same canonical request hash returns the same job/receipt.
- Same key and different hash fails as `IDEMPOTENCY_CONFLICT` and creates zero additional jobs.
- The same active operation hash returns the existing active operation.
- A different key may resubmit completed sync/verify work so current immutable heads can be inspected again.
- An identical completed run returns an immediately completed `reused=true` job linked to the existing materialized `run_id` and performs no replay.
- A failed/cancelled retry requires a new key and `job_id`; deterministic validation/provider failures are never automatically retried.

The same-key submission/cancellation replay guarantee lasts while a job is nonterminal and for 14 days after `finishedAt`, matching terminal job/idempotency-record retention. A cancellation replay returns its original canonical cancellation response even if later worker progress changed the current job representation; the client then reads the authoritative job resource. After expiry, the key may create a new intent; deterministic completed-run reuse still prevents duplicate research results.

Resolving a new public run intent atomically reserves its key before the single live plan-snapshot read. The unresolved reservation has a renewable 30-second lease with a 10-second owner heartbeat. Another request may observe and poll the reservation but never deletes or takes it over merely because its deadline passed. Expired unresolved reservations are removed only by the jobs-owned maintenance transaction within the shared `<=1,000` row budget; the next request may claim only after that cleanup. Finalize and release are fenced by the original claim generation, so one new intent persists at most one immutable plan snapshot and creates at most one job.

At most 100 `QUEUED` jobs may exist. Admission beyond that bound fails with a stable queue-full condition. At all times, the count of `RUNNING` plus `CANCEL_REQUESTED` jobs is at most one.

## Worker Lease and Recovery

The single active slot is protected by an atomic database claim and opaque claim token. Lease duration is 30 seconds; an active worker heartbeats at least every 10 seconds. A stale claim cannot update progress, finish, cancel, or publish a result. Progress persists at most once per second except for phase and terminal transitions, is monotonic within an attempt, and may reset only when `attempt` increments.

An expired `RUNNING` claim with `attempt < 3` is reclaimed with a new token and `attempt + 1`; expiry at `attempt=3` ends as `FAILED` with `WORKER_RECOVERY_EXHAUSTED`. An expired `CANCEL_REQUESTED` job becomes `CANCELLED`. Recovery resumes sync only when its persisted `allowNetwork: true` authorization remains present, through immutable-head deduplication; it may reuse an already published dataset and reruns strategy replay from the frozen beginning. Strategy event cursors remain deferred.

## Cancellation and Publication Race

Queued cancellation becomes `CANCELLED` in one transaction. Running cancellation becomes `CANCEL_REQUESTED` immediately and retains the active slot until worker acknowledgement or lease recovery.

Sync starts no new provider call after observing cancellation; one already in-flight validated response may commit as reusable cache. Verify checks between symbol-day batches and before manifest publication. Replay checks within one logical minute iteration and before result hand-off. Cancellation never exposes a partial run result.

For `BACKTEST_RUN`, `backtest-jobs` owns the shared Unit of Work. The completion transaction verifies that status is `RUNNING` and the claim token is current, consumes the bounded `backtest-results` publication participant, sets `materialized=1`, marks the job `COMPLETED`, and releases the active slot in the same `backtest-results.sqlite3` `BEGIN IMMEDIATE` transaction. If cancellation commits first, publication is rejected and the job ends `CANCELLED`; if publication commits first, cancellation observes `COMPLETED` and changes nothing.

## Security and Observability

Trust boundaries are browser/API requests, persisted canonical request JSON, worker claim tokens, provider/engine failures, and process restart. Assets are local availability, immutable result identity, provider credentials, plan contents, and the guarantee of zero live side effects.

- Persist only the bounded canonical structured plan snapshot required by a run; never persist raw natural-language source or extraction evidence in a job. Never log secrets, provider bodies, stack traces, SQL, client-supplied database paths, plan contents, or claim tokens.
- Treat persisted `allowNetwork: true` as a job-scoped audited authorization fact. Resolve credentials only from current server configuration at execution time; cancellation/terminal state never transfers authorization to a resubmission.
- Use parameterized SQL, unique constraints, revision/claim checks, and stable sanitized error codes.
- Structured events cover submission, replay, claim, phase/progress, heartbeat loss, cancellation, recovery, completion, failure, and prune; every event carries bounded `requestId`, `jobId`, and optional `runId` correlation.
- Operational health exposes queue depth, active kind/phase, oldest queued age, recovery count, and last sanitized failure. Metric labels never contain job/run/request IDs.

On-call questions are: What is running and how old is it? Why is a job blocked/failed? Did cancellation take effect before publication? Did restart recovery duplicate any provider fact or result row?

## Performance Budgets

- Exactly one active execution slot and at most 100 queued jobs.
- Job payload is at most 256 KiB; progress writes occur at most once per second outside transitions.
- Public list page size is `1..100`; job request/diagnostic metadata is retained 14 days.
- This module owns one maintenance Unit of Work that deletes at most 1,000 eligible job/stage/detail rows across one coordinated budget and calls `backtest-results` only with the remaining budget.
- HTTP submission/status/cancellation performs no provider call or replay and returns after a durable transaction.
- Queue age, claim latency, job duration, peak worker memory, database/WAL growth, and cancellation latency are recorded during implementation, but they do not close `BC01` until the approved implementation plan names the fixture volume, machine/throttle conditions, sample count, and numeric pass limits.

## Project Structure

Job values, repository, coordinator, dedicated single-thread executor, cross-thread cancellation token, maintenance Unit of Work, and lifecycle composition belong under `src/trade_plan_monitor/backtest/` or a focused `backtest/jobs/` subpackage if the approved implementation plan justifies it. Jobs may depend on result transaction/cleanup participants; results never import the coordinator. FastAPI routers remain adapters under `src/trade_plan_monitor/web/`; no module-level import starts a thread or opens SQLite.

## Code Style

Use frozen strict request/view values, explicit transition functions, parameterized SQL, short `BEGIN IMMEDIATE` transactions, monotonic progress validation, injected clock/worker functions, structured stable error codes, and exhaustive status/kind handling. Avoid generic queues, event buses, or distributed abstractions for one local slot.

## Testing Strategy

Use deterministic fake operations and clocks. Cover twenty concurrent identical submissions, key/payload conflict and 14-day expiry, canonical `Asia/Shanghai`/`+08:00` lifecycle/deadline persistence and rejection of alternate datetime forms, active-operation deduplication, `attempt=0` queued/reused jobs, three total claim generations across two worker objects, stale-token fencing, monotonic progress, queued/running cancellation, both cancel/publication transaction orders, queue capacity, restart after every safe boundary, persisted sync authorization/no credential/re-authorization on resubmission, no duplicate facts/manifests/fills/details, reused completed run, failed/cancelled rerun under the same `run_id`, renewable run-intent reservation fencing and orphan cleanup inside one 1,000-row maintenance budget, both dedicated executors/lifespan cleanup after success, timeout, and background failure, a blocking synchronous fake that does not block HTTP polling/heartbeat, and zero request-handler replay/provider work.

## Boundaries

- Always: persist before acknowledging submission, atomically claim/state-transition, fence stale workers, and check cancellation at module safe boundaries.
- Always: keep one slot, one result database, typed bounded payloads, and zero live-state/notification effects.
- Ask first: change concurrency, 30-second lease, 10-second heartbeat, three total claim generations, 100-job queue, 14-day retention/idempotency window, add logical retries, subprocesses, distributed workers, or live-state access.
- Never: run work in an HTTP handler/event loop/default executor, spawn untracked request tasks, accept two active jobs, let stale workers publish, expose claim tokens/secrets/paths, inherit network authorization across jobs, or treat cancellation as a completed research result.

## Success Criteria

- Twenty concurrent identical submissions create one job and execute once.
- Two workers produce one valid active claim; stale tokens perform zero successful writes.
- `RUNNING + CANCEL_REQUESTED <= 1` always holds.
- Cancellation/publication races produce exactly one terminal outcome and zero partial result visibility.
- Crash recovery creates no duplicate provider facts, datasets, fills, or details.
- A cancelled/failed run later completes under the same `run_id` and a new `job_id`.
- Submission, polling, and cancellation never execute provider/replay work in the request handler.
- Every persisted/public job datetime uses `Asia/Shanghai`/`+08:00`; lease/heartbeat elapsed behavior remains exact and independent of host timezone.
- Live database state and notification count remain exactly unchanged.

## Confirmed First-Release Decisions

The confirmed first-release decisions are: keep `DATASET_VERIFY` asynchronous; use one in-process coordinator, one single-thread operation executor, one single-thread repository executor, and one durable operation slot; allow at most three total worker-claim generations; and recover strategy replay from the frozen beginning. Subprocess isolation, event-cursor resume, and logical automatic retries are deferred.
