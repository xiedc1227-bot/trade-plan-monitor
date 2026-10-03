# Spec: backtest-results

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-backtest-results.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Persist immutable completed research results in `backtest-results.sqlite3`, expose only verified materialized records, retain summaries and simulated fills long term, bound diagnostic detail, and provide integrity-checked pagination, export, pinning, retention, and reconstruction.

## Relationship and Scope

`backtest-results` consumes canonical output from `backtest-engine`. It owns completed run inputs/results, plan snapshots used by materialized runs, publication integrity, query projections, exports, mutable pin metadata, and bounded retention. It does not own historical bars, provider calls, replay, job execution, HTTP routing, Vue, live positions, or notifications.

`run_id` is deterministic research-output identity; `job_id` is one durable submitted operation, and its `attempt` counts worker-claim generations. New writes persist only complete materialized runs. Failed and cancelled jobs belong to `backtest-jobs`, so a later job can complete the same `run_id`. Existing `BacktestRunStatus.FAILED` and `BacktestRunStatus.CANCELLED` remain code-level compatibility values for old serialized data; the first job-schema migration must prove that no such database row occupies a `run_id`, and the new database write path cannot create one.

## Commands

The CLI compatibility surface remains:

```powershell
python -m trade_plan_monitor backtest list --limit 20 --offset 0
python -m trade_plan_monitor backtest prune --batch-size 1000
```

CLI files remain local projections. Web export streams verified content through `backtest-api` and never exposes a local report path.

## Public Contracts

Retain `BacktestRunSummary`, `BacktestFillRecord`, `BacktestDetailRecord`, `BacktestDetailKind`, `BacktestResultStatistics`, `RetentionPruneResult`, canonical set hashes, report persistence, summary JSON, and fill CSV projection.

Provide bounded application contracts:

- `get_run(run_id)` returns one materialized run or `NOT_FOUND`;
- `list_runs(filters, limit, cursor)` uses `limit` in `1..100` and an opaque bounded cursor;
- `list_fills(run_id, limit, cursor)` orders by `(filledAt, fillId)`;
- `list_details(run_id, kind, limit, cursor)` orders by `(eventAt, detailId)` and requires a declared public detail kind;
- `get_equity_series(run_id)` returns at most 2,000 ordered daily points;
- `set_pinned(run_id, pinned, expected_revision, idempotency_key)` participates in the application Unit of Work and changes only mutable retention metadata;
- `iter_export_summary(run_id, cancelled)` and `iter_export_fills(run_id, cancelled)` rebuild stable verified projections without replay through bounded incremental iteration; they never construct a complete export in memory;
- `prune_result_rows(as_of, remaining_budget)` is an internal maintenance participant that deletes only eligible result stage/detail rows and reports exact budget use; `backtest-jobs` owns the one production `prune(as_of, batchSize <= 1000)` Unit of Work across job/stage/detail rows.

Pages expose `items`, `limit`, `nextCursor`, and `hasMore`. Public detail and equity availability is explicit: `AVAILABLE`, `EXPIRED`, or `NOT_RECORDED`. The immutable publication ledger stores original counts per detail kind plus the original equity-point count. Mutable retention metadata stores an atomic expiry marker per kind/equity series before physical rows are deleted: original count zero means `NOT_RECORDED`, positive count without an expiry marker means `AVAILABLE`, and a marker means `EXPIRED` even while bounded physical cleanup continues. `DEBUG_TRACE` is not exposed in the first Web release.

## Storage and Publication Contract

`backtest-results.sqlite3` owns deduplicated canonical plan snapshots used by completed runs, immutable run inputs/assumptions, materialized summaries, fills, bounded details, publication metadata, export reconstruction facts, pin revision, and retention metadata. It references `dataset_hash` and never copies market bars.

Publication stages the canonical summary, fills, and detail rows idempotently. Every stage mutation atomically increments a `stageRevision`; staged data is invisible to ordinary list/get/fill/detail/statistics/export reads. A stable WAL read snapshot then scans at most 1,000 staged rows at a time, revalidates every SQL identity/payload hash, and computes exact canonical `(identity, contentHash)` set hashes without holding a writer or using `fetchall`. After that snapshot closes, a short `BEGIN IMMEDIATE` transaction rechecks unchanged `stageRevision`, expected/stored row counts, and set hashes. Applying a detail-kind filter occurs only after integrity verification and cannot hide corrupt rows.

The same publication validation recomputes `plan_sha256` from the persisted canonical plan snapshot, derives the exact versioned `run_id` from the persisted `BacktestRunInput`, and matches report formula version, plan hash/version/symbol, `dataset_hash`, date range, initial state, and assumptions. A lookup-only `planVersionId` never substitutes for this content check.

For a `BACKTEST_RUN` job, `backtest-jobs` owns the shared result-database Unit of Work. After all bounded result validations, it verifies current job status/claim, invokes `backtest-results` transaction participants, sets `materialized=1`, transitions the job to `COMPLETED`, and releases the slot in the same short transaction. `backtest-results` never imports jobs. If cancellation commits first, publication fails and no partial run becomes visible. If publication commits first, later cancellation observes the terminal completed job.

Before enabling completed-only job publication, migration preflight counts legacy database `backtest_run` rows with `FAILED` or `CANCELLED`. The expected count for the current local/uncommitted baseline is zero. Any nonzero count aborts the migration before schema mutation with `LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION`; it is never overwritten or silently deleted, and requires a separately approved offline export/conversion to job diagnostics. The completed-only constraint is installed only after the zero-row assertion passes.

A legacy `COMPLETED` row that lacks the canonical plan snapshot or `BacktestRunInput` remains readable and exportable through the compatibility projection, but it is not eligible for verified completed-run reuse by the new job path. A matching new submission fails closed with a sanitized conflict until a separately approved adoption migration supplies independently verifiable input; implementation never guesses, rewrites, or deletes the legacy row.

The local uncommitted MVP also wrote UTC-normalized `backtest-run-summary-v1`, `backtest-fill-record-v1`, `backtest-detail-record-v1`, content-set, summary-JSON, and fill-CSV projections. Those v1 bytes remain immutable compatibility artifacts even when their plan/run input is otherwise known. The active China-time path writes new explicit v2 result/content-set domains plus `backtest-report-summary-v2` and `backtest-simulated-fills-v2` exports. It preserves the existing `run_id`, `dataset_hash`, and `backtest-report-v1` semantic identities but never publishes or reuses a UTC v1 projection through the new API until a separately approved adoption migration verifies and records the v2 content.

Pin state and pin revision remain outside canonical summary/report identity. A state-changing pin operation is idempotent, requires `expectedRevision`, and atomically records its canonical request/response under the application-owned 14-day pin-idempotency window.

## Result and Export Contract

Completed summaries expose closed typed coverage, assumptions, formula versions, final metrics, costs, limitation Tokens, plan/dataset/run identities, timestamps, and counts. Every active persisted, queried, cursor-bound, published, and exported datetime is canonical timezone-aware `Asia/Shanghai` RFC 3339 text in exact `YYYY-MM-DDTHH:MM:SS.ffffff+08:00` form; `Z`, offsetless values, more than 6 fractional digits, and other offsets are rejected before persistence/publication. Arbitrary `dict[str, object]` payloads are never a public API contract.

The original complete `reportHash` remains the audit identity after bounded details expire. Stable active `backtest-report-summary-v2` JSON and `backtest-simulated-fills-v2` CSV can be reconstructed incrementally from verified long-lived v2 summary/fill rows without provider access, strategy replay, new database rows, or a complete in-memory export. Immutable UTC-normalized v1 artifacts remain available only through explicitly identified offline compatibility tooling; they are never silently emitted as the active export version. Iterators use bounded reads, observe caller cancellation between batches, and let `backtest-api` emit chunks no larger than 64 KiB. Expired decisions, signals, outcomes, and equity detail remain expired and cannot be reconstructed. Exports never contain database/report paths, live state, credentials, or raw provider responses.

## Retention Contract

| Record class | Default retention |
|---|---|
| materialized run summary, canonical input hashes/snapshots, assumptions, final metrics, and fill ledger | long term |
| successful decision/signal/outcome/daily-equity detail | newest 100 runs and no more than 90 days; whichever bound is reached first |
| failed/cancelled job diagnostics and explicitly enabled debug trace | 14 days |
| abandoned unmaterialized, unpinned staged summary/fill/detail | 14 days |
| pinned run detail | exempt until unpinned |
| dataset/market revision referenced by a retained run | retained by `backtest-data` |

Cleanup is indexed and bounded. `backtest-jobs` supplies one total budget of at most 1,000 rows and calls result cleanup as a one-way dependency; results never start a second budget or prune job rows. It never runs a large `VACUUM` while monitoring or backtesting is active. WAL checkpoint is passive and occurs only at a safe/quiescent boundary; `VACUUM` remains an explicit offline maintenance action.

## Security and Observability

Trust boundaries are canonical engine output, on-disk staged content, API query filters/cursors, pin commands, and export requests. Every SQL statement is parameterized; cursors are signed or integrity-protected opaque values with bounded length and declared ordering.

Structured events cover stage start, stage conflict, materialization, reconstruction, pin change, prune, corruption block, and failure. Fields are allowlisted and correlated by `jobId`/`runId`; no full plan document, initial-lot payload, SQL, path, secret, raw exception, or report body is logged. Corruption is an error-level invariant break; ordinary expiry is not an error.

## Performance Budgets

- Public page size is `1..100`; no Web read returns an unbounded run/fill/detail collection.
- Equity contains daily rather than minute account points and is capped at 2,000 points.
- Stage writes, publication verification reads, and one coordinated prune invocation process at most 1,000 rows per batch/budget.
- Queries use indexes matching stable run completion, fill `(run_id, filled_at, fill_id)`, detail `(run_id, kind, event_at, detail_id)`, and retention ordering.
- Maximum-page JSON must remain below the shared 4 MiB response boundary.
- Every materialized public item, including a complete `BacktestDecisionView`, is serialized and rejected before publication if it exceeds 32 KiB; publication never truncates hashed evidence.
- Acceptance measures p50/p95 query time, peak memory, database/WAL growth, and repeated-run row growth on a fixed multi-day fixture before optimization.

## Project Structure

Result values, store, publication participants, retention, integrity checks, and report projection remain under `src/trade_plan_monitor/backtest/`. The job Unit of Work may call result transaction participants, but this module never imports the job coordinator. HTTP schemas and streaming responses belong to `backtest-api`; Vue formatting belongs to `backtest-web`. Generated report directories are runtime artifacts and remain outside Git.

## Code Style

Use frozen strict values, exact canonical JSON, explicit schema versions, parameterized SQL, immutable content rows, deterministic ordering, opaque bounded cursors, typed discriminated detail variants, and short transactions. Keep mutable metadata visibly separate from hashed content.

## Testing Strategy

Cover staged invisibility, 1,000-row read-snapshot verification and short-writer revision fencing, exact count/set-hash publication, persisted-input-to-`run_id` recomputation for v1/v2, plan/dataset/range mismatch, canonical `Asia/Shanghai`/`+08:00` persistence/query/export round trips and rejection of alternate datetime forms, immutable UTC v1 compatibility fixtures and verified v2 adoption conflicts, identical no-op persistence, conflicting content, job completion/cancel race in both orders, corrupt SQL identity/payload, seeded legacy terminal-row migration refusal, per-run detail identity, cursor pagination without duplicates/gaps on a static set, pin revision conflicts, original-count/expiry availability including partial physical cleanup, all retention classes, one shared prune budget, reopen/WAL, byte-stable versioned export, reconstruction without replay, expired-detail non-reconstruction, and zero additional rows during file recovery.

## Boundaries

- Always: expose only materialized, hash-verified, typed results and preserve long-term summary/fill audit facts.
- Always: keep retention/indexing bounded and distinguish `AVAILABLE`, `EXPIRED`, and `NOT_RECORDED`.
- Ask first: change result/export schema, status semantics, retention defaults, pagination ceilings, pin behavior, destructive run deletion, or online `VACUUM`.
- Never: expose staged/partial data, copy bars, reconstruct expired details, return unbounded collections, hide corruption through filtering, mutate canonical completed content, or disclose paths/secrets/provider bodies.

## Success Criteria

- A staged run contributes zero public rows until exact materialization succeeds.
- Identical persistence is a no-op; conflicting identity/content fails closed.
- Job completion and result visibility are atomic against cancellation.
- Cursor pages contain no duplicates or gaps over a static ordered result set.
- Summary/fill exports are byte-stable and reconstructable without replay; expired detail stays unavailable.
- All active persisted, paginated, and exported datetimes use `Asia/Shanghai`/`+08:00`; existing `run_id`/`dataset_hash`/`reportHash` identities remain unchanged, UTC v1 result/export bytes remain immutable compatibility artifacts, and active v2 result/export goldens are byte-stable.
- Long-term rows do not grow on an identical repeated run, while detail/job retention remains bounded.
- Pin/unpin uses explicit revision and correctly changes retention eligibility without changing `reportHash`.

## Open Questions

Destructive deletion of a completed run and server-side comparison exports remain deferred. Per-run JSON/CSV export, paginated details, and client-side comparison of explicitly selected summaries are sufficient for the first release.
