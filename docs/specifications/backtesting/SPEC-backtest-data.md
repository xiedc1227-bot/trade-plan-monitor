# Spec: backtest-data

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-backtest-data.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Incrementally acquire explicitly authorized historical A-share facts, store immutable content-addressed revisions in `backtest-market.sqlite3`, and freeze reproducible datasets that many offline runs can reuse without copying market rows.

## Relationship and Scope

`backtest-data` is the provider and dataset boundary under the stable `backtest` initiative. It owns historical capability mapping, coverage inspection, synchronization, immutable revisions, verification, and `dataset_hash`. It does not own strategy replay, simulated execution, result persistence, jobs, HTTP, Vue, live monitoring, or notifications.

One dataset may contain 1–10 symbols so synchronized facts can be reused, but `backtest-engine` still runs one reviewed plan version and one symbol at a time. Historical `stk_mins` evidence remains independent of live `rt_min` and `rt_min_daily`; this module cannot complete `T058`.

## Commands

The existing compatibility commands remain:

```powershell
python -m trade_plan_monitor backtest sync --symbols 003043.SZ --start 2025-01-02 --end 2025-12-31 --allow-network
python -m trade_plan_monitor backtest verify --symbols 003043.SZ --start 2025-01-02 --end 2025-12-31
```

`sync` is the only network-capable operation. `verify`, coverage inspection, dataset listing, and frozen reads are local-only. Long-running Web submissions are owned by `backtest-jobs`, not by this command adapter.

## Public Contracts

Retain the provider-independent contracts `HistoricalMinuteProvider`, `DatasetScope`, `DatasetManifest`, `DatasetFreezeResult`, `BacktestSyncResult`, `BacktestSyncService.sync(...)`, `BacktestMarketStore.freeze_dataset(...)`, and frozen reads for calendar, minutes, limits, and official daily bars.

Add bounded read contracts for application/API composition:

- `inspect_coverage(scope)` returns exact available/missing surface counts without provider access;
- `list_datasets(limit, cursor)` returns immutable manifest summaries with `limit` in `1..100`, an opaque bounded cursor, and exact `items`, `limit`, `nextCursor`, and `hasMore` page fields;
- `get_dataset(dataset_hash)` returns a bounded `BacktestDatasetSummary` with scope, profile, adjustment policy, creation time, artifact/trading-day/minute/reference counts, coverage/blocker codes, and no membership rows, or `NOT_FOUND`;
- `open_frozen_dataset(dataset_hash)` is an internal engine/store contract that verifies and iterates full `DatasetManifest` membership by symbol-day without serializing it to HTTP;
- progress and cancellation callbacks are operational side channels and are excluded from `dataset_hash`, artifact hashes, and provider facts.

Full manifest membership is not a public application/API response. If a future diagnostic needs it, that capability requires a separately approved cursor-paginated projection; the first Web release exposes summary and coverage only.

`DatasetScope` continues to carry symbols, `start`, `end`, `warmup_start`, historical label profile, and adjustment policy. JSON adapters use camelCase while Python contracts retain snake_case.

## Data and Storage Contract

- `backtest-market.sqlite3` owns normalized historical artifacts, immutable revisions, current heads, sync metadata, dataset manifests/membership, and `dataset_hash`.
- The live database and `backtest-results.sqlite3` must resolve to different files and are rejected before DDL if their table domains are detected.
- Identical normalized content is a no-op. A provider correction appends a revision and never overwrites content referenced by an older dataset.
- A dataset references exact revisions. It never copies minute rows per run.
- Every frozen artifact is re-hashed before parsing or replay; valid-looking manifest text cannot authorize modified `content_json`.
- Exact Decimal canonicalization rejects binary float, normalizes equal scale variants, caps fixed-point expansion at 10,000 characters, and caps converted fen at `9,223,372,036,854,775,807`.

## Synchronization, Verification, and Cancellation

`DatasetScope` contains 1–10 unique symbols, spans at most five calendar years from `start` through `end`, and permits at most two calendar years from `warmup_start` through `start`. `end >= today`, invalid symbols/ranges, `.BJ`, and unverified profiles fail before provider or persistence access.

The approved profile remains `TUSHARE_STK_MINS_241_END_V1`: the 09:30 source row is retained as non-strategy `opening_special`, and a full normal trading day must expose exactly 240 canonical usable minutes. Calendar calls name `SSE` or `SZSE` explicitly. `stk_mins`, `trade_cal`, unadjusted `daily`, and `stk_limit` responses are untrusted complete surfaces; missing, extra, duplicate, malformed, cross-symbol, cross-exchange, or out-of-range identities fail before persistence.

Network calls stay outside transactions. One validated persistence batch contains at most 1,000 rows. Verification holds a stable WAL read snapshot, scans at most one symbol-day minute batch at a time, closes that snapshot, then publishes under a short `BEGIN IMMEDIATE` transaction after revalidating selected heads in batches of at most 1,000.

Cancellation is cooperative. Sync checks before each provider call, after each response, between symbol-days, and before the next surface; an already in-flight validated surface may commit, but no new provider request starts after cancellation is observed. Freeze checks between symbol-day batches and before publication; cancellation leaves either no manifest or one complete immutable manifest, never a partial manifest. Previously committed cache rows remain reusable on resubmission. There is no cross-database transaction with the job/result store.

## Security and Observability

Trust boundaries are the Web/CLI scope, environment secret reference, provider responses, and on-disk SQLite content. Assets are the Tushare credential, immutable historical facts, dataset identities, and local storage availability.

- Require explicit network authorization and an environment secret reference for every sync submission.
- Never persist or log tokens, authorization headers, raw provider bodies, rejected payloads, database paths from a Web request, or stack traces.
- Use parameterized SQL and stable sanitized error/blocker codes.
- Emit structured events for sync start, bounded progress, committed surface, cancellation, completion, and failure with `jobId`/request correlation supplied by the caller; label sets must remain bounded.
- Operational logs and callbacks must not change content hashes or dataset identities.

## Performance Budgets

- No operation loads a multi-year minute corpus into memory.
- Dataset list/detail responses contain summaries only and must remain below the shared 4 MiB JSON boundary; full membership is consumed incrementally inside the store/engine.
- Freeze and replay readers operate by symbol-day and use `(symbol, bar_end)` or manifest natural-key indexes.
- Persistence and head revalidation batches are at most 1,000 rows.
- Repeating an identical sync performs zero provider calls and adds zero revisions.
- Refreshing unchanged content adds zero revisions.
- Performance acceptance records database/WAL size, peak memory, provider-call count, and elapsed time for at least two symbols across multiple days before any optimization is retained.

## Project Structure

Historical provider interfaces and Tushare mapping stay under `src/trade_plan_monitor/market_data/`. Dataset identity, synchronization, storage, canonicalization, and storage guards stay under `src/trade_plan_monitor/backtest/`. CLI composition stays in `src/trade_plan_monitor/cli.py`. This logical module split does not require moving working files solely to mirror a documentation name.

## Code Style

Use frozen strict Pydantic values at external/application boundaries, `Protocol` for provider contracts, timezone-aware `Asia/Shanghai` values whose canonical RFC 3339 storage form is exactly `YYYY-MM-DDTHH:MM:SS.ffffff+08:00`, integer fen or exact `Decimal`, parameterized SQL, explicit stable blockers, and dependency injection. Provider mapping may accept 0–6 fractional-second digits with `+08:00` but must normalize before hashing/persistence; reject `Z`, offsetless datetime text, overprecision, and other offsets. Keep provider-specific mapping out of dataset logic and keep network construction out of import time.

## Testing Strategy

Default tests use fixtures and make zero network calls. Unit and integration coverage must include scope bounds, the 241-to-240 label profile, exact reference identities, malformed/duplicate facts, weekends/lunch/session boundaries, corrections, identical no-op sync, cancellation/resubmission, read-snapshot publication races, artifact tampering, Decimal limits, database path confusion, reopen, bounded summary serialization with no membership leakage, incremental full-manifest iteration, and two-symbol multi-day coverage. Authorized real Tushare evidence is a separate validation asset and is never committed with credentials.

## Boundaries

- Always: validate complete provider surfaces before persistence and keep provider calls outside transactions.
- Always: preserve immutable revisions, exact hashes, explicit SSE/SZSE calendars, and isolated storage.
- Ask first: change provider/profile, timestamp mapping, adjustment/corporate-action policy, BSE support, hash schema, scope limits, or market-data deletion/GC.
- Never: forward-fill, guess a calendar/price limit, silently drop malformed rows, overwrite referenced revisions, expose secrets, read live state, or count history as `T058` evidence.

## Success Criteria

- Unchanged facts reproduce the same 64-character `dataset_hash` byte-for-byte; a correction creates a different hash while the old dataset remains reproducible.
- A full normal day exposes exactly 240 usable canonical minutes under `TUSHARE_STK_MINS_241_END_V1`.
- Identical synchronization is provider- and storage-idempotent.
- Cancellation followed by resubmission completes without duplicate facts or a partial manifest.
- Every frozen read detects content tampering.
- Two symbols across multiple days pass exact calendar/minute/limit/daily coverage with bounded memory and batches.
- Live and result stores remain untouched, and `T058` remains independent.

## Open Questions

BSE history remains blocked pending a separately approved calendar contract. Corporate-action adjustment, user-defined dataset labels, dataset deletion, and unreferenced market-history GC are deferred beyond the first Web release.
