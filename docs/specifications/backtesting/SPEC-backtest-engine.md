# Spec: backtest-engine

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-backtest-engine.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Replay one immutable reviewed plan version for one symbol over a frozen dataset using event time and `execution-model-v1`, producing a deterministic completed report without network, wall-clock, live-state, notification, WebSocket, or broker access.

## Relationship and Scope

`backtest-engine` consumes `backtest-data` and reuses the approved `plan-domain`, `market-data`, `strategy-state`, and pure `decision-engine` contracts. It owns run input identity, event-time replay, simulated execution, metrics, and the canonical report. It does not own provider calls, mutable jobs, HTTP, Vue, result retention, or live monitoring.

One run means one immutable validated plan snapshot and its one symbol. A Web submission must bind that snapshot to one RFC 4122 `planVersionId`. The selected plan need not be live-active, because backtesting supports review before activation, but it must pass the same deterministic validation required for `canActivate=true`. Multi-symbol shared cash, portfolio execution, optimization, and batch comparison are outside the first release.

## Operation entry points

Web/API submits `BACKTEST_RUN` through `backtest-jobs` with explicit execution costs, slippage, and research assumptions. Background workers execute frozen inputs; replay never runs inside an HTTP request handler. No backtest CLI or plan-file compatibility adapter remains.

## Public Contracts

Add immutable `BacktestRunInput` and `BacktestInitialLotInput` values. `BacktestRunInput` contains `runFormulaVersion`, the canonical plan snapshot and recomputed `plan_sha256`, optional `plan_version_id: UUID | None` lookup identity, `dataset_hash`, initial cash, normalized initial lots, `ExecutionConfig`, explicit event-risk assumption, context bounds, and schema/formula versions. A Web submission requires the UUID; `None` remains supported only by domain inputs and existing historical results. `planVersionId` is audit/lookup metadata only and is excluded from the run-hash preimage; the snapshot contributes through exact `plan_sha256` and `plan.version` only.

`BacktestInitialLotInput` is separate from live `PositionLot` and contains `lotKey`, `bucket`, `acquiredTradeDate`, `quantity`, and `costBasisFen`. `lotKey` is a caller-stable 1–64 character identifier matching `[A-Za-z0-9][A-Za-z0-9._-]*` and is unique within the command. Multiple lots may share `(bucket, acquiredTradeDate)` when their `lotKey` values differ. Inputs are normalized by `(bucket, acquiredTradeDate, lotKey)`; quantities are positive 100-share board lots, and `costBasisFen` is the positive remaining total cost of the entire lot, not a per-share price. Run-specific `PositionLot` IDs are derived only after the v2 run hash exists, using `lotKey` as the stable source key. This preserves same-day lot identity/tie-breaking and removes the cycle caused by using a `PositionLot` that already requires `run_id` to calculate that same `run_id`.

Every initial lot uses the selected plan symbol, has `acquiredTradeDate <= dataset.start`, and starts fully open with original quantity equal to remaining quantity. Aggregated initial quantity per bucket and in total must satisfy the reviewed plan's bucket/maximum-position limits before hashing or replay.

Retain `backtest_run_id(...)`, `OfflineBacktestRunner.run(...)`, `BacktestRunReport`, `BacktestBlockedError`, `ExecutionConfig`, and the signal/order/fill/outcome/equity contracts. Add a typed internal cancellation result carrying only phase and last safe event identity; cancellation never creates a partial `BacktestRunReport`.

Progress and cancellation are operational side channels. They are excluded from `run_id`, `report_hash`, decision input, ordered output, and report bytes.

## Run Identity and Determinism

Run identity is explicitly versioned. Existing empty-initial-lot work keeps `backtest-run-v1` with its current preimage unchanged: `plan_sha256`, `plan.version`, `dataset_hash` and range, positive initial cash, the empty `initial_lots` list, indicator formula, exact 512/499/512 context, execution config/hash, and explicit event-risk boolean. Existing v1 results remain readable and reusable byte-for-byte.

Public non-empty initial-lot support uses `backtest-run-v2`. Its canonical preimage contains the same v1 semantic values but replaces run-bound `PositionLot` values with the normalized `BacktestInitialLotInput` list, including `lotKey`, and names `backtest-run-v2` as formula/domain version. `planVersionId`, database row IDs, full snapshot bytes beyond the recomputed plan hash/version, `job_id`, `attempt`, progress, timestamps, and cancellation are excluded. Formula selection is deterministic: an empty input list uses v1; a non-empty list uses v2. Changing either preimage requires a new formula version and migration decision.

The fixed context remains 512 complete five-minute bars, 499 prior official daily bars, and 512 calendar-day facts. Exact Decimal canonicalization, rate-to-rational conversion, integer-fen money, rounding directions, precision-28 half-even metrics, and all existing limitation Tokens remain unchanged.

`run_id` identifies deterministic research output, while `job_id` identifies one durable submission/operation. A single job may have multiple worker-claim generations recorded by `attempt`; terminal retry creates a new `job_id`. A failed or cancelled job never occupies the completed result identity, so a new job may replay the same `run_id` to completion.

## Event-Time and No-Lookahead Contract

Replay advances only through frozen fact timestamps. Every evaluation sees only facts available at or before its event time. Five-minute buckets contain only completed minutes, provisional daily bars contain only observed minutes, official daily facts become visible only at official close, and warm-up facts never contribute returns or fills.

For every actionable signal, `signalAt == EvaluationResult.snapshot.evaluatedAt` and the event is owned by the source fact's `receivedAt`. A candidate execution minute must occur after the producing event in discrete replay order and satisfy `openAt >= signalAt`; a fill records `filledAt == openAt`. The engine never substitutes `barEnd`, bucket end, hard-coded 15:00, or wall-clock time.

Changing a fact after an evaluation cannot change an earlier decision, `result_hash`, signal, outcome, or fill. Missing required canonical candidates fail closed rather than being skipped.

## Simulated Execution Contract

`execution-model-v1` preserves actual daily limits, T+1 by trading date, 100-share board lots, cash and position caps, target caps, no leverage, no short selling, explicit fees, directional slippage, and exact unfilled reasons. A zero-volume minute remains the non-tradable proxy; candidates continue until a later positive-volume minute or finite replay finalization.

`RISK_BREACH` is a risk event and never implies a fill. Required report limitations remain verbatim, including `ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY`, `FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME`, `CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE`, `DAILY_EQUITY_DRAWDOWN_SAMPLING`, `WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP`, `METRIC_DECIMAL_PRECISION_28_HALF_EVEN`, and `BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR`.

## Cancellation and Recovery

The engine checks cancellation before every source-minute step, evaluation, trading-day transition, finalization, and publication hand-off. It observes cancellation within one logical minute iteration, stops at a deterministic safe boundary, and returns no completed report.

Restart recovery deterministically replays from the frozen beginning and relies on idempotent staged result writes. Strategy event-cursor resume is explicitly deferred and cannot be marked complete. Cancellation, retries, attempts, leases, and progress are owned by `backtest-jobs`.

## Security and Observability

The engine accepts only validated in-memory contracts and a frozen dataset reader. It must not construct a provider, open the live database, read arbitrary paths from HTTP, call a scheduler or recovery service, emit a live event, enqueue a notification, or connect to a broker.

Structured run events use stable names and bounded fields such as `jobId`, `runId`, phase, symbol, dataset hash prefix, decision/fill counts, duration, and sanitized blocker code. Plan source text, full plan JSON, initial-lot payloads, database paths, secrets, and raw exception text are not logged. Telemetry cannot affect deterministic output.

## Performance Budgets

- Each evaluation context is bounded by the declared 512/499/512 contexts, and each market-data read is bounded to one symbol-day input batch.
- The runner never materializes a five-year multi-symbol dataset in memory.
- The current compatibility runner retains the complete ordered `BacktestRunReport` in memory, so this specification does not claim an end-to-end heap ceiling from the rolling-context bound. Streaming/staged output or an empirically accepted whole-run memory ceiling remains open `BC01` work.
- Progress callbacks are coalesced by `backtest-jobs`; the engine does not perform database progress writes per minute.
- Before optimization, acceptance records wall time, peak memory, decision count, fill count, and database growth for the same fixed fixture; changes within measurement noise are not retained as optimizations.

## Project Structure

Replay, execution models, canonical run/report identity, and application-neutral value objects stay under `src/trade_plan_monitor/backtest/`. Production decision contracts remain under their existing domain/decision/market-data packages. HTTP adapters may compose the engine but never own or duplicate execution rules.

## Code Style

Use frozen strict values, pure functions for formulas, explicit version constants, exact Decimal/integer arithmetic, timezone-aware `Asia/Shanghai` event values with canonical `YYYY-MM-DDTHH:MM:SS.ffffff+08:00` representation, exhaustive enum handling, deterministic ordering, and dependency injection for the evaluator/dataset reader. Reject `Z`, offsetless values, overprecision, and other offsets. No ambient Decimal context, process clock, or host timezone may influence output.

## Testing Strategy

Retain the exact one-symbol/one-day regression of 49 decisions and one daily-equity point plus byte-identical `backtest-run-v1` IDs for existing empty-lot fixtures. Expand deterministic fixtures to separate single-symbol runs for at least two symbols across multiple days with at least one valid buy and one reduction/exit fill. Cover v2 same-day multi-lot keys/tie-breaking, positive total cost basis, actual limits, T+1, board lots, cash/position caps, fees/slippage, missing minutes, zero volume, final-minute no-fill, no-lookahead mutation, cancellation, restart replay, stable bytes, and zero provider/live/notification calls.

## Boundaries

- Always: use one validated immutable plan version, one symbol, a frozen dataset, explicit initial state, and explicit execution/event-risk assumptions.
- Always: preserve event-time provenance, deterministic identities, exact arithmetic, and all declared research limitations.
- Ask first: change formula/schema versions, rolling bounds, rounding, metric semantics, event-risk shape, corporate actions, participation/impact, or portfolio/shared-cash execution.
- Never: use future facts or wall-clock time, fill in the producing bar/bucket, access live state/network/notifications, treat a risk event as a broker fill, or publish a partial cancelled report.

## Success Criteria

- Identical inputs reproduce identical `run_id`, ordered decisions, fills, equity, `report_hash`, JSON bytes, and CSV bytes.
- Later-fact mutation changes no earlier identity or output.
- Every semantic event time is `Asia/Shanghai`/`+08:00`; changing only an operational job/audit time never changes `run_id`.
- Initial lots affect identity, equity, cost basis, sellable quantity, and T+1 exactly as specified.
- Cancellation produces no completed result and the same inputs can complete under a later `job_id`.
- Two symbols over multiple days exercise actionable buy and reduction/exit paths.
- Network, live-database reads/writes, and notification calls during replay are all exactly zero.
- Evaluation contexts and market reads stay within the declared rolling and symbol-day boundaries; whole-run heap/resource acceptance remains explicitly open under `BC01` until measured or redesigned.

## Open Questions

Structured event-risk records, corporate actions, volume participation, market impact, portfolio/shared-cash execution, optimizer/batch comparison, and strategy event cursors remain deferred. The current explicit event-risk boolean and deterministic replay-from-start recovery remain the first-release contract.
