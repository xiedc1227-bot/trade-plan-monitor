# Spec: backtest-api

> `SPEC-backtest-api.md` is the canonical agent-facing English version; `SPEC-backtest-api.zh-CN.md` is the human-review Chinese version; both documents must remain semantically equivalent.

## Objective

Expose additive, typed, loopback-only FastAPI resources for backtest datasets, persistent jobs, completed runs, paginated results, cancellation, pinning, and safe export without executing provider or replay work inside HTTP request handlers.

## Relationship and Scope

`backtest-api` is the contract-first adapter over `backtest-data`, `backtest-jobs`, `backtest-results`, immutable `plan-domain` versions, and the shared `local-web` error/origin/OpenAPI boundary. It does not implement strategy rules, SQL repositories, worker loops, provider mapping, result formatting in Vue, a new authentication system, or a new WebSocket.

The current committed OpenAPI has exactly 24 live-monitor paths. This specification adds 13 resource paths; after implementation and regeneration the canonical document must have exactly 37 paths. Until implementation is accepted, `openapi.json` remains the 24-path baseline and no placeholder router counts as completion.

## Commands

Contract generation remains:

```powershell
python scripts/generate_frontend_types.py
python scripts/generate_frontend_types.py --check
```

`create_app(...)` remains the sole side-effect-free OpenAPI source. Generation updates `openapi.json` and `web/src/api/generated.ts` byte-for-byte together. This specification does not authorize a network sync; only an accepted `POST /api/v1/backtest-data-syncs` command with explicit `allowNetwork: true` may enqueue one after implementation.

## REST Resources

All paths are under `/api/v1`:

| Method | Path | Success contract |
|---|---|---|
| `GET` | `/backtest-jobs` | `200 BacktestJobPage` |
| `GET` | `/backtest-jobs/{job_id}` | `200 BacktestJobView` |
| `POST` | `/backtest-job-cancellations` | `200 BacktestJobView` or `202 BacktestJobView`, according to the cancellation matrix |
| `POST` | `/backtest-data-syncs` | `202 BacktestJobReceipt` |
| `POST` | `/backtest-dataset-verifications` | `202 BacktestJobReceipt` |
| `GET` | `/backtest-datasets` | `200 BacktestDatasetPage` |
| `GET` | `/backtest-datasets/{dataset_hash}` | `200 BacktestDatasetView` |
| `GET`, `POST` | `/backtest-runs` | `200 BacktestRunPage`, `202 BacktestJobReceipt` |
| `GET`, `PATCH` | `/backtest-runs/{run_id}` | `200 BacktestRunView` |
| `GET` | `/backtest-runs/{run_id}/fills` | `200 BacktestFillPage` |
| `GET` | `/backtest-runs/{run_id}/details` | `200 BacktestDetailPage` selected by required `kind` |
| `GET` | `/backtest-runs/{run_id}/equity-series` | `200 BacktestEquitySeries` |
| `GET` | `/backtest-runs/{run_id}/exports/{export_kind}` | streamed `200 SUMMARY_JSON` or `200 FILLS_CSV` |

`GET /plan-versions` gains additive optional `symbol`, `status`, and `canActivate` filters so the browser never loads one incomplete page and filters it as if complete.

## Input Contracts

All request objects are strict and closed. `JavaScriptSafeInteger` is a JSON integer in `0..9007199254740991`; positive integer fields additionally exclude `0`. Public fen input fields use `JavaScriptSafeInteger`. Public fen output fields use `FenText`, a canonical signed base-ten string with no `+`, exponent, whitespace, or leading zero except the literal `0`. `DecimalText` is a finite canonical non-exponent decimal string. A rate is `DecimalText` in `0..1`; slippage basis points are `DecimalText` in `0..<10000`. Binary JSON floats are rejected for every exact decimal field.

`BacktestDatasetScopeInput` has exactly `symbols`, `start`, `end`, `warmupStart`, `historicalProfile`, and `adjustmentPolicy`. It contains 1–10 unique canonical `.SH`/`.SZ` symbols, ISO dates, at most five calendar years from `start` through `end`, at most two calendar years from `warmupStart` through `start`, literal `historicalProfile=TUSHARE_STK_MINS_241_END_V1`, and literal `adjustmentPolicy=NONE`. The bounds and the historical-data rule that rejects `end >= today` are server-authoritative.

`BacktestDataSyncCommand` has exactly `scope`, `refresh`, and required literal `allowNetwork: true`. It accepts no token, provider URL, database path, plan path, report path, or arbitrary file path. `BacktestDatasetVerificationCommand` has exactly `scope` and is fully local.

`BacktestExecutionConfigInput` has exactly the following six required fields and no default: `commissionRate`, `minimumCommissionFen`, `stampDutyRate`, `transferFeeRate`, `buySlippageBps`, and `sellSlippageBps`. The three rate fields use `0..1`; the two slippage fields use `0..<10000`; `minimumCommissionFen` is a `JavaScriptSafeInteger`.

`BacktestInitialLotInput` has exactly `lotKey`, `bucket`, `acquiredTradeDate`, `quantity`, and `costBasisFen`. `lotKey` is caller-stable, unique within the command, 1–64 characters, and matches `[A-Za-z0-9][A-Za-z0-9._-]*`. `bucket` is `CORE|TACTICAL`; `quantity` is a positive `JavaScriptSafeInteger` divisible by 100; `costBasisFen` is a positive `JavaScriptSafeInteger` representing the remaining total cost of the whole lot. Multiple lots may share `(bucket, acquiredTradeDate)` when `lotKey` differs. Normalization sorts by `(bucket, acquiredTradeDate, lotKey)` and never exposes or accepts an internal `PositionLot` identity.

`BacktestRunCommand` has exactly `planVersionId`, `datasetHash`, `initialCashFen`, `initialLots`, `executionConfig`, and `eventRiskAssumption`. `planVersionId` is an RFC 4122 UUID that serializes as canonical lowercase hyphenated text and remains lookup/audit metadata only; `datasetHash` is a lowercase 64-character SHA-256; `initialCashFen` is positive; `initialLots` contains at most 200 `BacktestInitialLotInput` values; and `eventRiskAssumption` is `NO_EVENT_RISK|MANUAL_EVENT_RISK`. The dataset must be frozen and verified, contain the plan symbol, and cover the plan event range plus required warm-up. Every `acquiredTradeDate <= dataset.start`; each bucket quantity and total quantity must not exceed the validated plan caps; and `initialCashFen + sum(costBasisFen) <= 9007199254740991`. Canonicalization occurs before `requestHash` and deterministic run identity are calculated. Empty `initialLots` selects `backtest-run-v1`; non-empty `initialLots` selects `backtest-run-v2` and includes each `lotKey` in its identity preimage.

`BacktestJobCancellationCommand` has exactly `jobId`. `BacktestRunPinCommand` has exactly `pinned` and non-negative `expectedRevision`. Every `POST` and `PATCH` also requires the `Idempotency-Key` header described below; the header is not copied into a JSON body.

For a new run submission, the application service performs one read-only lookup of the immutable live plan version, revalidates its canonical `planJson`, recomputed `planHash`, symbol, deterministic validation, and `canActivate=true`, and durably stores a bounded canonical plan snapshot with the job request. The plan need not be active. Same-key receipt replay is resolved from the job store without repeating this lookup. Workers, recovery, strategy replay, result reuse, polling, and export perform zero live-database reads or writes.

## Output Contracts

All JSON schemas are strict, closed, camelCase, and use `UPPER_SNAKE` enum values. Arbitrary mappings, stored request JSON, raw provider payloads, and unbounded evidence are forbidden public contracts. Every backtest datetime input and output, including job/audit/publication metadata and embedded decision/result times, uses timezone-aware `Asia/Shanghai`. Input accepts only RFC 3339 `+08:00` with 0–6 fractional-second digits and canonicalizes before request hashing, cursor encoding, comparison, or persistence; output is exactly `YYYY-MM-DDTHH:MM:SS.ffffff+08:00`. `Z`, offsetless values, more than 6 fractional digits, and other offsets fail validation; date-only fields remain China-market calendar dates. Counts/revisions use non-negative `JavaScriptSafeInteger`; SHA-256 values are lowercase 64-character hex.

### Job schemas

`BacktestJobKind` is `DATA_SYNC|DATASET_VERIFY|BACKTEST_RUN`. `BacktestJobStatus` is `QUEUED|RUNNING|CANCEL_REQUESTED|COMPLETED|FAILED|CANCELLED`. `BacktestJobPhase` is `QUEUED|VALIDATING_INPUT|SYNCING_DATA|VERIFYING_DATASET|REPLAYING|MATERIALIZING_RESULTS|FINALIZING|TERMINAL`. `BacktestProgressUnit` is `ITEMS|SYMBOL_DAYS|EVENTS|ROWS`.

| Schema | Exact fields and invariants |
|---|---|
| `BacktestJobReceipt` | `jobId`, `kind`, `status`, nullable `runId`, nullable `datasetHash`, `attempt`, `revision`, `reused`, `submittedAt`. Every submission response is `202`, including immediate deterministic reuse with `status=COMPLETED`, `attempt=0`, `revision=0`, and `reused=true`. |
| `BacktestJobProgressView` | `phase`, `completedUnits`, nullable `totalUnits`, `unit`, `updatedAt`. If `totalUnits` is present, `completedUnits <= totalUnits`; progress is monotonic for one claim generation. |
| `BacktestJobView` | `jobId`, `kind`, `status`, `requestHash`, nullable `runId`, nullable `datasetHash`, `progress`, nullable `result`, `attempt`, `revision`, `createdAt`, nullable `startedAt`, `updatedAt`, nullable `finishedAt`, nullable `cancelRequestedAt`, `reused`, nullable `errorCode`, nullable `errorMessage`. `attempt` is `0..3`; error text is sanitized and at most 512 characters. |

`BacktestJobResultView` is a discriminator union on `kind` and exists only when `status=COMPLETED`:

| Variant | Exact fields |
|---|---|
| `BacktestDataSyncJobResultView` | `kind=DATA_SYNC`, `calendarRows`, `minuteDays`, `dailyLimitRows`, `dailyBarRows`, `networkCalls` |
| `BacktestDatasetVerificationJobResultView` | `kind=DATASET_VERIFY`, `ready`, nullable `datasetHash`, `coverage`, `blockers` |
| `BacktestRunJobResultView` | `kind=BACKTEST_RUN`, `runId`, `reportHash`, `reused` |

`errorCode` and `errorMessage` are both present only for `FAILED|CANCELLED` and both null otherwise. They are the only public failure/cancellation diagnostic and remain on the job resource; they never appear in a completed run, run-detail page, equity series, or export. `result` is non-null only for `COMPLETED`. A terminal job has `phase=TERMINAL` and non-null `finishedAt`.

`BACKTEST_RUN` receipts/jobs always have non-null matching `runId` and `datasetHash`; their completed result has the same `runId`. `DATA_SYNC|DATASET_VERIFY` always have `runId=null`. `DATA_SYNC` has `datasetHash=null`; `DATASET_VERIFY` may keep it null until successful readiness, after which the job and result values match. Outer `kind`, result discriminator, progress phase, status, timestamps, error pair, and result presence are validated as one closed union rather than as independent fields.

### Dataset schemas

| Schema | Exact fields |
|---|---|
| `BacktestDatasetScopeView` | `symbols`, `start`, `end`, `warmupStart`, `historicalProfile`, `adjustmentPolicy` |
| `BacktestDatasetCoverageView` | `symbolCount`, `tradingDayCount`, `calendarRowCount`, `minuteDayCount`, `minuteBarCount`, `dailyLimitRowCount`, `dailyBarRowCount`, `blockers` |
| `BacktestDatasetView` | `datasetHash`, `schemaVersion=backtest-dataset-v1`, `scope`, `coverage`, `createdAt`, `verifiedAt` |

`blockers` is an ordered, unique list of at most 100 stable `UPPER_SNAKE` codes. Full dataset membership, artifact rows, provider bodies, and local paths are never serialized.

### Completed-run schemas

`BacktestArtifactAvailability` is `AVAILABLE|EXPIRED|NOT_RECORDED`. `BacktestResultAvailabilityView` has exactly `decisionDetails`, `signalDetails`, `executionOutcomeDetails`, and `equitySeries`, each a `BacktestArtifactAvailability` value.

| Schema | Exact fields |
|---|---|
| `BacktestRunSummaryView` | `runId`, `reportHash`, nullable `planVersionId`, `planHash`, `datasetHash`, `symbol`, `status=COMPLETED`, `eventStart`, `eventEnd`, `completedAt`, `pinned`, `revision`, `fillCount`, `metrics`, `availability` |
| `BacktestRunView` | every `BacktestRunSummaryView` field plus `initialCashFen`, `coverage`, `assumptions`, `formulaVersions`, and `limitations` |
| `BacktestRunCoverageView` | `eventStart`, `eventEnd`, `tradingDayCount`, `decisionCount`, `signalCount`, `orderCount`, `fillCount`, `outcomeCount`, `equityPointCount` |
| `BacktestMetricsView` | `initialCashFen`, `initialEquityFen`, `finalCashFen`, `finalEquityFen`, `totalReturn`, `maximumDrawdown`, `tradeCount`, `winningSellCount`, `winRate`, `turnoverFen`, `totalCostFen`, `realizedPnlFen`, `unrealizedPnlFen`, `blockedCount`, `skippedCount` |
| `BacktestExecutionConfigView` | `commissionRate`, `minimumCommissionFen`, `stampDutyRate`, `transferFeeRate`, `buySlippageBps`, `sellSlippageBps` |
| `BacktestAssumptionsView` | `eventRiskAssumption`, `executionConfig`, `executionConfigHash`, `priceAdjustmentPolicy`, `historicalProfile` |
| `BacktestFormulaVersionsView` | `runFormulaVersion`, `reportSchemaVersion`, `executionFormulaVersion`, `metricFormulaVersion` |

`BacktestRunView.coverage` is `BacktestRunCoverageView`, while dataset/job-verification coverage is `BacktestDatasetCoverageView`. `BacktestAssumptionsView.executionConfig` is `BacktestExecutionConfigView`. Every `*Fen` output above is `FenText`; `totalReturn`, `maximumDrawdown`, `winRate`, rates, and slippage are canonical `DecimalText` values in their domain ranges and are never JSON numbers. `limitations` is an ordered, unique list of at most 32 stable Tokens, each at most 128 characters. `planVersionId` is nullable because a completed CLI-originated result may have no live-plan row; a `planVersionId` filter matches only the same non-null audit reference and excludes null rows. A run resource exists only after atomic completed-result publication; there is no partial or failed `BacktestRunView`.

### Result schemas

| Schema | Exact fields |
|---|---|
| `BacktestFeeBreakdownView` | `commissionFen`, `stampDutyFen`, `transferFeeFen`, `totalFen` |
| `BacktestFillView` | `fillId`, `orderId`, `signalId`, `runId`, `planHash`, `datasetHash`, `resultHash`, `configHash`, `sourceBarId`, `side`, `symbol`, `bucket`, nullable `targetLotId`, `filledAt`, `requestedQuantity`, `quantity`, `priceFen`, `notionalFen`, `fees`, `cashDeltaFen`, `costBasisReleasedFen`, nullable `realizedPnlFen` |
| `BacktestDecisionView` | `kind=DECISION`, `detailId`, `runId`, `eventAt`, `resultHash`, `decision` where `decision` is the closed backtest-only `BacktestAuthoritativeDecisionView` projection |
| `BacktestSignalView` | `kind=SIGNAL`, `detailId`, `runId`, `eventAt`, `signalId`, `resultHash`, `signalType`, `symbol`, nullable `quantity`, nullable `bucket`, nullable `targetLotId`, `causeId` |
| `BacktestExecutionOutcomeView` | `kind=EXECUTION_OUTCOME`, `detailId`, `runId`, `eventAt`, `outcomeId`, `signalId`, nullable `orderId`, nullable `sourceBarId`, `status`, nullable `reason`, nullable `fillId` |
| `BacktestEquityPointView` | `snapshotId`, `runId`, `symbol`, `markedAt`, `markPriceFen`, `cashFen`, `positionQuantity`, `marketValueFen`, `costBasisFen`, `realizedPnlFen`, `unrealizedPnlFen`, `totalCostFen`, `equityFen` |

All result `*Fen` fields are `FenText`. `BacktestAuthoritativeDecisionView` is field-for-field and semantically equivalent to the existing closed live `AuthoritativeDecisionView`, including enums, evidence identities, ordering, and bounds, except that every nested field whose name ends in `Fen` is serialized as `FenText`. It neither changes nor replaces the live projection used by the existing 24 paths. A fully encoded `BacktestDecisionView` must satisfy the 32 KiB item limit at result-publication time; oversized evidence fails publication and is never truncated. `BacktestDetailPage.kind` is required and limited to `DECISION|SIGNAL|EXECUTION_OUTCOME`; its item variant carries the same literal discriminator. Failed/cancelled `DIAGNOSTIC` and internal `DEBUG_TRACE` are not run details. `BacktestDetailPage` has `kind`, `availability`, `filters`, `items`, `limit`, `nextCursor`, `hasMore`, and `highWatermark`; `filters` echoes the normalized object containing the same required `kind`. When availability is not `AVAILABLE`, `items` is empty, `nextCursor` is null, and `hasMore=false`; `EXPIRED` is never represented as `NOT_RECORDED`.

`BacktestEquitySeries` has exactly `availability` and `items`. It contains at most 2,000 daily points in `(markedAt, snapshotId)` order. When availability is not `AVAILABLE`, `items` is empty. `BacktestJobPage.items` is `BacktestJobView[]`; `BacktestDatasetPage.items` is `BacktestDatasetView[]`; `BacktestRunPage.items` is `BacktestRunSummaryView[]`; `BacktestFillPage.items` is `BacktestFillView[]`; and `BacktestDetailPage.items` is the discriminator-matching detail variant. Fill rows are long-lived and therefore do not use a detail-availability state.

## Pagination and Ordering

`limit` defaults to 20 and is in `1..100`. `cursor` is optional on the first request and is a `CursorToken`: an ASCII token of at most 512 characters. Its exact wire form is `<payload_b64url>.<mac_b64url>` using unpadded base64url segments. The canonical payload has `v=cursor-v1`, route identity, normalized-filter SHA-256, exact order identity, first-page high-water tuple, and last-seen tuple. Dataset and run cursors also carry a signed `s` tuple of safe non-negative insertion-fence integers; `s` never replaces or changes the exact public ordering tuple. The MAC is HMAC-SHA-256 over the payload segment using an installation-local 256-bit secret created owner-only before any secret bytes are written and thereafter owner/permission-validated before reading through one non-replaceable file handle; an existing nonconforming key is rejected without silent permission repair or reuse, and concurrent Windows creation is handled by a short bounded sharing-violation retry. A rotated/missing key, invalid encoding/MAC/version, route/filter/order mismatch, or malformed tuple returns the same `422 VALIDATION_ERROR` without an oracle-specific reason.

First-page membership is frozen by the signed high-water tuple plus its signed insertion fence where required; rows inserted later, including rows with the same public timestamp, cannot enter the traversal. Every cursor page returns exactly `filters`, `items`, `limit`, `nextCursor`, `hasMore`, and `highWatermark`; `filters` is the server-normalized closed filter object, nullable `nextCursor` is a `CursorToken`, and non-null `highWatermark` is the constant signed `CursorToken` anchor for that traversal. The exact order tuples are:

| Resource | Ordering |
|---|---|
| jobs | `(createdAt DESC, jobId DESC)` |
| datasets | `(createdAt DESC, datasetHash DESC)` |
| runs | `(completedAt DESC, runId DESC)` |
| fills | `(filledAt ASC, fillId ASC)` |
| decisions/signals/outcomes | `(eventAt ASC, detailId ASC)` |

Job filters are `kind`, `status`, `runId`, `datasetHash`, `createdFrom`, and `createdTo`. Dataset filters are `symbol`, `startOnOrAfter`, `endOnOrBefore`, `historicalProfile`, and `adjustmentPolicy`. Run filters are `symbol`, `planVersionId`, `datasetHash`, `completedFrom`, `completedTo`, and `pinned`. Fill filters are the closed empty object; detail filters contain only required `kind`. Filters use AND semantics, repeated enum values are normalized as sorted unique sets, and cursor binding uses the fully normalized filter object.

A job cursor also binds an independent job-list `membershipRevision` when either mutable `status` or `datasetHash` membership is filtered. A transition increments it when status changes or a verification job acquires its completed `datasetHash`; ordinary progress/heartbeat updates do not increment it. If the bound revision changes before a later page, that page returns `409 CONFLICT` and the client restarts from page one. Traversals without either mutable filter remain anchored to immutable `(createdAt, jobId)` and do not fail because progress or status display values changed. A run traversal with a non-null `pinned` filter similarly binds the global monotone pin-membership revision in `s` and returns `409 CONFLICT` after membership drift; unfiltered run display metadata may change without invalidating immutable catalog membership.

Each encoded item is at most 32 KiB, each page has at most 100 items, and the complete UTF-8 JSON response including envelope overhead is strictly below `4 * 1024 * 1024` bytes. Projection and response-size invariants are checked before headers are committed; the server never silently truncates an item or page. Exports do not use JSON pagination.

## Idempotency, Revisions, and Errors

Every `POST` and `PATCH` requires `Idempotency-Key` of 1–128 characters matching `[A-Za-z0-9][A-Za-z0-9._:-]*`. The application service atomically claims the key with its canonical request hash; check-then-insert is forbidden.

- Same key and same hash returns the same canonical response and resource identity. Submission endpoints always return `202 BacktestJobReceipt`, whether the job is active, terminal, or an immediately reused completed run.
- Same key and different hash returns `409 CONFLICT` and creates no resource or side effect.
- Submission and cancellation replay guarantees last while the referenced job is nonterminal and for 14 days after `finishedAt`. Pin-operation idempotency records last 14 days after their internal audited `recordedAt`; this timestamp is not a public run field. After expiry a key may represent a new intent, but current revision checks and deterministic completed-run reuse still prevent stale mutation or duplicate results.
- Different keys with identical active operation identity share one active job. Identical completed run input creates an immediately completed `reused=true` job linked to the existing `runId` and performs no replay.

Cancellation and pinning are application/Unit-of-Work mutations that atomically claim their idempotency key, canonical request hash, state transition, audit record, and canonical response; route adapters never implement replay themselves. `PATCH /backtest-runs/{run_id}` changes only `pinned` and requires `expectedRevision`; a stale revision returns `409 CONFLICT`. Successful no-op and state-changing replays return the same `200 BacktestRunView`.

Cancellation has this exact matrix:

| Current state | Response | Result |
|---|---|---|
| `QUEUED` | `200 BacktestJobView` | atomically becomes `CANCELLED` |
| `RUNNING` | `202 BacktestJobView` | atomically becomes `CANCEL_REQUESTED` |
| `CANCEL_REQUESTED` | `202 BacktestJobView` | idempotent current-state replay |
| `CANCELLED` | `200 BacktestJobView` | idempotent terminal replay |
| `COMPLETED` | `409 CONFLICT` | no mutation |
| `FAILED` | `409 CONFLICT` | no mutation |

Queue exhaustion returns `429 RATE_LIMITED` with `Retry-After`; missing service/worker/configuration returns `503 SERVICE_UNAVAILABLE`. Missing resources return `404 NOT_FOUND`. Every error uses the existing closed `ErrorResponse` envelope and fixed `ApiErrorCode`; public messages are fixed and sanitized. Each request receives a server-generated 32-character lowercase-hex request ID in `X-Request-ID`; client-supplied IDs are ignored. Every submission `202` includes `Location: /api/v1/backtest-jobs/{job_id}`. A nonterminal `202` also includes `Retry-After: 2`; an immediately reused `COMPLETED` receipt omits `Retry-After`. A running/cancel-requested cancellation `202` includes both headers.

## Application and Security Boundary

`create_app(backtest_read_service=..., backtest_operation_service=...)` injects Protocol adapters without constructing a database, SDK, thread, timer, worker, or task. Import/OpenAPI generation remains I/O-free. `create_production_app(...)` must explicitly compose real backtest services and coordinator lifecycle; a router with missing services returns `SERVICE_UNAVAILABLE` and is not product completion.

The existing exact loopback listener, same-origin guard, absent production CORS, CSP/security headers, and 4 MiB request-body limit remain unchanged. All inputs are server-validated; SQL is parameterized; Vue validation is never a security boundary. No API returns credentials, provider text, local paths, full exceptions, staged data, raw persisted payloads, or live-state mutations. Backtest signals remain research results and are never published to the live WebSocket/outbox.

Export accepts only the path `run_id` and `export_kind=SUMMARY_JSON|FILLS_CSV` and reconstructs from verified long-lived active v2 completed-result rows. `SUMMARY_JSON` emits `backtest-report-summary-v2` with `application/json` and filename `backtest-<runId>-summary.json`; `FILLS_CSV` emits `backtest-simulated-fills-v2` with `text/csv; charset=utf-8` and filename `backtest-<runId>-fills.csv`. Both contain only canonical `Asia/Shanghai` timestamps, use `Content-Disposition: attachment` with that allowlisted ASCII filename, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`. Immutable UTC v1 artifacts are excluded from this public route until separately approved adoption. Export buffers no complete file, yields chunks no larger than 64 KiB, checks client disconnect between chunks, and aborts reconstruction/iteration immediately after disconnect. It never creates a report file or exposes a file path.

## Observability and Performance

HTTP RED evidence records route-template rate, error class, and latency with bounded labels. Structured logs carry `requestId`, optional `jobId`/`runId`, route template, status class, and sanitized error code; they never log full bodies or secrets. Approved health projections expose bounded queue/worker facts without adding an unreviewed telemetry dependency.

This specification sets structural gates only: handlers perform no provider/replay work; lists obey the 100-item, 32 KiB-item, and sub-4 MiB response limits; export chunks are at most 64 KiB and stop on disconnect; and application adapters use bounded incremental reads. The implementation plan must define the fixed database fixture, environment, repetitions, percentile latency, peak-memory/WAL, and export-throughput acceptance numbers before performance implementation begins. No empirical threshold is approved by this specification.

## Project Structure

Strict schemas belong in `src/trade_plan_monitor/web/schemas.py` or a focused backtest schema module; route adapters belong in `src/trade_plan_monitor/web/routers/`; service Protocols remain application boundaries. Cursor signing/verification and bounded export helpers are shared backend infrastructure, not copied per route. `openapi.json` and `web/src/api/generated.ts` are generated together. Frontend request orchestration belongs in `web/src/api/backtests.ts`, not an unbounded expansion of a generic client.

## Code Style

Use typed FastAPI dependencies, strict frozen Pydantic input/output models, explicit response/status declarations, plural noun resources, camelCase JSON aliases, exhaustive enums, bounded arrays/text, parameterized application services, and one shared error envelope. Validate service output before serialization and keep transport adapters free of domain decisions.

## Testing Strategy

Contract tests cover every method/path/status/schema; all field and cross-field constraints; JavaScript-safe fen input and `FenText` output; uniform `Asia/Shanghai`/`+08:00` datetime round trips, 0–6-digit input to fixed-six-digit canonicalization, and rejection of `Z`, offsetless, overprecision, and other-offset values; rate/slippage bounds; 200 initial lots and `lotKey` normalization; plan snapshot validation and zero worker/replay live-database access; job progress/result unions; dataset/run views; filters; exact cursor format, signature, high-water traversal, key rotation, tampering, and filter mismatch; 100-item, 32 KiB-item, and sub-4 MiB response gates; all availability states; 14-day idempotency and races; immediate completed reuse under `202`; pin revisions; the full cancellation matrix; queue-full retry; missing services; origin/body/security headers; redaction; v1 exclusion, v2 64 KiB streamed export, and disconnect abort; request IDs; and zero request-handler work.

OpenAPI tests fix exactly 37 paths, regenerate TypeScript, and reject schema/status drift. Production-composition tests prove real services and lifecycle are reachable rather than defaulting to `DEGRADED`/`SERVICE_UNAVAILABLE`. Performance tests and their measured thresholds are defined in the approved implementation plan, not invented during specification implementation.

## Boundaries

- Always: contract first, strict typed schemas, boundary validation, atomic idempotency, bounded signed-cursor pagination, same-origin loopback security, generated TypeScript, and service output revalidation.
- Always: return `202` for every long-operation submission, persist the plan snapshot at submission, and make the persistent job/result store authoritative thereafter.
- Ask first: change an API path/field/status, error semantics, pagination/response limits, Origin/CORS/authentication, expose a new detail/export, or add WebSocket transport.
- Never: accept paths/tokens/provider URLs, execute work in a route, expose staged/raw/arbitrary payloads, copy strategy logic into transport, let a worker/replay read live state, mutate live state, or publish backtest signals as live alerts.

## Success Criteria

- The canonical OpenAPI expands from exactly 24 to exactly 37 declared paths with byte-matching generated TypeScript.
- Every long operation returns a durable `202` receipt, including deterministic completed reuse, without provider/replay work in the handler.
- Same-key receipt replay is guaranteed through the 14-day window; conflicting reuse fails; identical run inputs execute once.
- Lists/details remain stable, bounded, signed, filter-bound, at most 100 items, at most 32 KiB per item, and below 4 MiB per JSON page.
- Public fen input is JavaScript-safe and every fen output is `FenText`; all rates/slippage and initial-lot identities are exact.
- All datetime inputs, outputs, filters, cursor keys, and exports use canonical `Asia/Shanghai`/`+08:00`; no host/browser conversion or alternate offset is accepted.
- Plan snapshots are persisted on submission; workers, recovery, idempotent replay, and strategy replay have zero live-database access.
- Cancellation, pinning, equity/detail availability, export, and job-only failure/cancellation diagnostics are represented by closed typed contracts.
- Real production composition serves the resources under the existing loopback security boundary.

## Open Questions

No blocking question remains for the first contract proposal. WebSocket job events, remote authentication, destructive run deletion, debug-trace exposure, portfolio runs, server-side comparison, and empirical performance budgets are deferred and require separate approval or an approved implementation plan as applicable.

## Review Status

The user confirmed the six-module map, additive local REST direction, and this detailed specification set on 2026-08-26. A bilingual consistency pass then corrected `BacktestRunCommand.planVersionId` to the existing RFC 4122 UUID/string identity, added the backtest-only `FenText` decision projection without changing the live 24-path contract, closed job discriminator invariants, and clarified application-owned cancellation/pin idempotency. On 2026-08-26, the user explicitly rejected the temporary UTC proposal, confirmed one `Asia/Shanghai`/`+08:00` contract for every backtest time, and confirmed all remaining corrected clauses. Section 15 of the bilingual implementation plan was approved on 2026-08-26. That approval authorizes only generating the bilingual `BT009`–`BT050` task list. The generated task list still requires separate explicit approval; implementation, regeneration of the committed 24-path snapshot, commit, push, dependency installation, and any network access remain unauthorized.
