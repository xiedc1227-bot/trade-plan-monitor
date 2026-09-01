# Spec: backtest (Historical Data and Deterministic Trade Backtesting)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-backtest.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Provide a deterministic A-share backtest that can be prepared and run outside market hours. An explicitly authorized `backtest sync` operation incrementally downloads Tushare/QuickSync historical data into an isolated market-data SQLite database. `backtest verify` freezes an exact content-addressed `dataset_hash`, and `backtest run` consumes only that frozen local dataset, the reviewed plan, and explicit execution assumptions without network access or wall-clock sleeps.

The backtest reuses the production plan, market normalization, indicator, and pure decision contracts. It adds an isolated, versioned simulated-execution model for research only. It never sends an order, changes live monitoring state, or claims that historical `stk_mins` proves the live `rt_min` or `rt_min_daily` contracts.

## Approved Scope Change

The user approved this module on 2026-08-25 so historical-data validation and trade-plan research are not blocked by market hours. This is a narrow exception to the original “no order simulation” boundary:

- the live monitor remains reminder-only and never infers a fill;
- simulated fills exist only under the explicit `BACKTEST` mode and isolated databases;
- broker connectivity, paper trading against a live feed, automatic orders, leverage, and short selling remain out of scope;
- task `T058` remains the independent live-market contract gate and is not completed by any historical backtest result.

## Module Decomposition

`backtest` remains the stable umbrella identity and the compatibility home of the existing CLI MVP. The approved 2026-08-26 capability map decomposes the next release into six independently reviewable modules, implemented in dependency order:

1. [`backtest-data`](SPEC-backtest-data.md) — authorized historical acquisition, immutable revisions, coverage, verification, and frozen `dataset_hash`;
2. [`backtest-engine`](SPEC-backtest-engine.md) — deterministic event-time replay and `execution-model-v1` for one reviewed plan version and one symbol;
3. [`backtest-results`](SPEC-backtest-results.md) — immutable completed-result publication, bounded queries/exports, retention, and pinning;
4. [`backtest-jobs`](SPEC-backtest-jobs.md) — durable asynchronous submission, progress, cancellation, and crash recovery;
5. [`backtest-api`](SPEC-backtest-api.md) — typed REST resources, idempotency, pagination, and production composition;
6. [`backtest-web`](SPEC-backtest-web.md) — accessible Vue workflows for data preparation, submission, progress, and result review.

The capability map and module direction are approved, and the user confirmed the linked detailed specification set on 2026-08-26. A bilingual cross-module consistency pass corrected UUID/CLI lookup identity, exact money/time projections, legacy-result reuse, incremental export, publication-size, and mutation-idempotency clauses without changing the approved boundaries. The user confirmed those corrected contracts on 2026-08-26, so the aggregate detailed specification is approved as corrected. Section 15 of the bilingual implementation plan was approved on 2026-08-26. That approval authorizes only generating the bilingual `BT009`–`BT050` task list. The generated task list still requires separate explicit approval; implementation, OpenAPI changes, the Web surface, commit, push, dependency installation, and any network access remain unauthorized. Existing `BT001`–`BT008` work remains the local MVP baseline and is not relabeled as completion of these six modules.

## Commands

The implemented CLI surface is explicit and non-overlapping with the existing `replay` command:

```powershell
python -m trade_plan_monitor backtest sync --symbols 003043.SZ --start 2025-01-02 --end 2025-12-31 --allow-network
python -m trade_plan_monitor backtest verify --symbols 003043.SZ --start 2025-01-02 --end 2025-12-31
python -m trade_plan_monitor backtest run --dataset <dataset_hash> --plan config/plans/003043.SZ.sample.yaml --initial-cash-yuan 100000 --commission-rate 0.0003 --minimum-commission-yuan 5 --stamp-duty-rate 0.0005 --transfer-fee-rate 0.00001 --buy-slippage-bps 2 --sell-slippage-bps 2 --no-event-risk
python -m trade_plan_monitor backtest list --limit 20 --offset 0
python -m trade_plan_monitor backtest prune --batch-size 1000
```

`sync` is the only command allowed to use the network and `TUSHARE_TOKEN`; it requires both user authorization and the literal `--allow-network` flag. `verify`, `run`, `list`, and `prune` are local-only. `sync` and `verify` default `warmup_start` to 400 calendar days before `start`; an explicit override must match across both commands. `run` fails unless its dataset is frozen and verified, all six fee/slippage inputs are present, and exactly one of `--no-event-risk` or `--manual-event-risk` is selected. The numeric values above are illustrative assumptions, not defaults. The current `replay` command keeps its existing monitor-event semantics.

`OfflineBacktestRunner` includes immutable `initial_lots` in `run_id`, but the current CLI exposes only `--initial-cash-yuan` and therefore supplies an empty initial-lot tuple. A validated public initial-lot input/import remains open acceptance work.

## Architecture and Isolation

```text
Tushare/QuickSync
       │ explicit backtest sync; network outside transactions
       ▼
backtest-market.sqlite3
  normalized immutable row revisions + manifests
       │ backtest verify → frozen dataset_hash
       ▼
offline event-time replay ──→ existing pure decision engine
       │                       + BACKTEST execution-model-v1
       ▼
backtest-results.sqlite3
  run summary + decisions + signals + fills + daily equity
```

The three storage domains are separate:

| Store | Owns | Must not own |
|---|---|---|
| live monitor SQLite | active plans, manual lots, live bars, evaluations, episodes, risk, alerts, outbox, monitor events, audit | backtest datasets, simulated fills, backtest equity |
| `backtest-market.sqlite3` | normalized historical artifacts, immutable revisions, current heads, dataset manifests/membership, `dataset_hash` | live state, simulated fills, result details |
| `backtest-results.sqlite3` | immutable run inputs, summaries, decisions, signals, fills/unfilled reasons, daily equity, retention metadata | copied market bars, live state, secrets |

Market and result paths must resolve to different files. Before schema creation, each store rejects an existing SQLite database containing live tables or the other backtest domain's table prefixes. Backtest databases are not included in live-monitor online backups. A Web `BACKTEST_RUN` submission may open one read-only live-store transaction to read exactly one immutable plan version. It validates that version and durably persists the canonical plan snapshot with the accepted request before responding; submission performs zero live-store writes. Once that durable boundary commits, the worker and deterministic replay perform zero live-store reads and zero live-store writes. Direct CLI `backtest run` receives the plan through the explicit `--plan` file, validates the same snapshot contract locally, and never opens the live store. Final `BC01` evidence must compare exact logical live state immediately before and after Web submission, then immediately before and after worker/replay, and assert zero notification calls; those explicit zero-difference acceptance tests remain open in the current MVP.

## Historical Provider Contract

Historical acquisition uses a separate interface; it must not pretend to implement realtime operations:

```python
class HistoricalMinuteProvider(Protocol):
    def historical_minute_batch(self, symbol: str, trade_date: date) -> HistoricalMinuteBatch: ...
    def historical_minutes(self, symbol: str, trade_date: date) -> tuple[MinuteBar, ...]: ...
    def trading_calendar(self, exchange: str, start: date, end: date) -> tuple[TradingDay, ...]: ...
    def daily_limits(self, trade_date: date) -> tuple[DailyLimit, ...]: ...
    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[DailyBar, ...]: ...
```

Tushare mapping is `stk_mins`, `trade_cal`, `stk_limit`, and unadjusted `daily`. Historical capability status and timestamp-label semantics are independent of the realtime capability matrix. A ready historical capability never changes `rt_min` or `rt_min_daily` to `READY`; a denied historical capability never blocks the live monitor.

Historical synchronization requests `trade_cal(exchange="SSE", ...)` and `trade_cal(exchange="SZSE", ...)` explicitly for the exchanges present in the scope; it never relies on an omitted or empty exchange argument. The official Tushare `trade_cal` contract does not list BSE as a supported exchange. Therefore any `.BJ` scope is rejected before network or persistence with stable blocker `UNSUPPORTED_HISTORICAL_CALENDAR:BSE`. BSE history remains unavailable until a separately verified calendar contract is approved; this does not remove `.BJ` from the live plan domain.

The authorized 2026-08-25 observation for `600000.SH` on 2026-08-24 returned 241 `stk_mins` rows from 09:30 through 15:00. The provider constructor remains fail-closed at `UNVERIFIED`. The implemented versioned contract `TUSHARE_STK_MINS_241_END_V1`, selected explicitly by the CLI composition, preserves the 09:30 source row as non-strategy `opening_special` and requires the other end-labeled rows to match the existing 240 canonical trading-minute ends exactly. Unknown profiles cannot call the SDK or freeze a dataset; no implementation silently deletes, shifts, or accepts all 241 rows.

## Incremental Synchronization

`backtest sync` follows these invariants:

1. Validate symbols, closed date range, provider capability, exchange calendar, and configured unadjusted-price policy before retrieval. One `DatasetScope` contains 1–10 unique symbols, spans at most 5 calendar years from `start` through `end`, and permits at most 2 calendar years from `warmup_start` through `start`; broader requests fail before network or persistence.
2. Compute missing symbol/trading-day/interface surfaces from local current heads and request only missing or explicitly refreshed surfaces. Every fetched reference response must contain exactly the requested identities: `trade_cal` covers every calendar date for its explicit exchange, `daily` covers every expected open-day `(symbol, trade_date)` in its requested span, and `stk_limit` covers every requested open-day `(symbol, trade_date)`. A missing, extra, or duplicate identity fails before persistence as `INVALID_RESPONSE:trade_cal`, `INVALID_RESPONSE:daily`, or `INVALID_RESPONSE:stk_limit`; `--refresh` cannot replace a complete head with a partial response.
3. Keep every network call outside SQLite transactions. Validate a bounded provider response before a short insert transaction; one persistence batch contains at most 1,000 rows.
4. Use stable content hashes. Identical normalized facts are stored once; an upstream correction creates a new immutable revision instead of overwriting a row used by an older dataset.
5. Persist each validated provider result before requesting the next surface, so a later retry skips already committed heads. Repeating an identical sync creates neither duplicate artifacts nor head revisions.
6. Store sanitized operation/error metadata only. Tokens and raw authorization/provider response bodies are never persisted or printed.

The real Tushare historical-reference adapter is stricter than the realtime partial-health path. Any unparsable row or duplicate identity, even with equal content, fails the complete raw surface as sanitized `INVALID_RESPONSE`. Surface identity rules are explicit: `trade_cal` rejects another exchange or a date outside its requested range; `daily` rejects another symbol or a date outside its requested range; and market-wide `stk_limit(trade_date)` rejects another date but legitimately permits other valid symbols for that date. Sync then selects its requested `missing_symbols` from the market-wide limit response and independently requires that selected set, and every calendar/daily request set, to be exact. No malformed raw row may be silently dropped before historical persistence.

Historical market data is retained as a shared deduplicated cache. A dataset references exact immutable revisions; it never copies the same minute rows per run. Automatic result pruning cannot delete a market revision referenced by a dataset or retained run. Deleting unreferenced market history requires an explicit offline maintenance operation.

## Dataset Verification and Identity

`backtest verify` is fully offline and fail-closed. It validates:

- exact symbol/date coverage against `trade_cal`, including weekends, holidays, lunch, and the canonical 09:30/15:00 boundaries;
- the versioned historical-label mapping and exactly 240 usable one-minute bars per full normal trading day unless an explicit exchange-session exception is represented;
- strictly ordered, unique `(symbol, bar_end)` identities and rejection of conflicting duplicate payloads;
- timezone-aware `Asia/Shanghai` timestamps, valid integer-fen OHLC, non-negative integer shares, exact Decimal yuan amounts, and allowed provenance;
- actual `stk_limit`, official unadjusted `daily`, and complete reference-data coverage from the explicit `warmup_start` through the requested end.

The cross-cutting time contract is singular: every active backtest timestamp, including market facts, replay events, job lifecycle, audit/idempotency records, result publication, persistence, API values, and Web display, is timezone-aware `Asia/Shanghai`. Inputs accept only `+08:00` with 0–6 fractional-second digits and normalize before identity work; canonical persistence, hashing, cursor encoding, output, and export text is exactly `YYYY-MM-DDTHH:MM:SS.ffffff+08:00`. `Z`, offsetless values, more than 6 fractional digits, and other offsets fail validation. Date-only fields are interpreted in the China-market calendar, and no layer converts an accepted value through the host or browser timezone.

The local uncommitted MVP currently contains some UTC-normalized market metadata and result/export projections. Migration may convert metadata that is excluded from `dataset_hash` only after a verified backup and proof that dataset identities are unchanged. Identity-bearing UTC v1 result/export bytes remain immutable compatibility artifacts; the active path uses versioned v2 China-time result/content/export projections and does not expose or reuse v1 through the new API until separately approved adoption.

Missing, invalid, conflicting, or unverified facts produce stable blockers. Corrupt content uses `INVALID_<KIND>:<identity>:<date>`; broken exchange predecessor facts use `INVALID_CALENDAR_CHAIN:<exchange>:<date>`; OHLC outside the day's actual limit uses `PRICE_OUTSIDE_DAILY_LIMIT:<symbol>:<date>`. The verifier never forward-fills a minute, guesses a trading day, substitutes a hard-coded 10% limit, or treats a provisional bar as an official close.

Because `verify` receives no plan, plan-specific indicator sufficiency is checked later by `run`; the runner blocks insufficient daily history for every used indicator, including MA200 when applicable. `run` also requires explicit manual event-risk input or an explicit recorded no-event assumption. Absence is never silently interpreted as safe.

`dataset_hash` is the canonical hash of the dataset-schema version, historical-label profile, symbol/date scope, adjustment policy, ordered immutable row-revision hashes, calendar/limit/daily facts, and warm-up boundary. Provider receipt time and local database row IDs are excluded unless they select a different content revision. Reverification of unchanged facts returns the same hash byte-for-byte. A provider correction creates a new hash while old datasets remain reproducible.

Every backtest content and identity hash uses the same exact Decimal canonicalization. Finite numerically equal values with different scale, such as `0.0003` and `0.00030`, serialize to the same non-exponent fixed-point text and therefore the same hash; zero is always `0`, binary floating point is rejected, and no result depends on the process-global Decimal context. A value whose exact fixed-point expansion would exceed 10,000 characters fails closed before hashing rather than exhausting memory or creating a context-dependent identity. CLI yuan-to-fen conversion is equally context-independent: it accepts at most two fractional digits plus any additional trailing fractional zeroes, rejects an oversized exponent before expansion, and requires the converted amount to fit signed 64-bit fen, at most `9,223,372,036,854,775,807`.

Content addressing is verified on every frozen-artifact read, not only at insertion. Before parsing or replaying a referenced artifact, the store recomputes its canonical content hash and compares it with the frozen `artifact_hash`; any mismatch is a stable tamper/corruption blocker. A syntactically valid manifest or hash string never authorizes changed `content_json`.

Freeze validation holds a stable WAL read snapshot and walks required dates in order, validating each daily minute batch independently rather than loading a multi-year minute corpus into memory or reserving the writer during the scan. After the read snapshot closes, publication alone acquires a short `BEGIN IMMEDIATE` transaction and revalidates every selected `natural_key -> artifact_hash` head in bounded batches; any head correction between validation and publication aborts the freeze rather than publishing a mixed revision. A validated manifest also builds a bounded cached `natural_key` dictionary, so later single-key membership lookup is O(1) before the referenced artifact is re-read and re-hashed.

## Event-Time Replay and No-Lookahead Rules

The replay advances only through timestamps stored in the frozen facts and never sleeps or reads the wall clock for a decision. It never invokes `MarketSessionScheduler`, `SymbolService`, `RecoveryService`, `RuntimeLifecycleService`, realtime alerts, Webhooks, WebSockets, or the notification outbox.

It must reuse the approved production contracts rather than duplicate strategy rules:

- `TradePlan`, plan validation, immutable version, and `plan_sha256`;
- `MinuteBar`, `TradingDay`, `DailyLimit`, and `DailyBar`;
- `expected_minute_ends`, `normalize_source_minute`, `aggregate_five_minute_bar`, and `aggregate_provisional_daily_bar`;
- `calculate_ta_v1`, `reconcile_daily_close`, `EvaluationContext`, and `evaluate(EvaluationContext)`;
- `EvaluationResult`, `result_hash`, episode/risk intents, and `SignalIntent`.

At every deadline the engine receives only facts available at or before that event time. A five-minute evaluation sees only completed component minutes. Its provisional daily bar contains only minutes observed so far. The current official `daily` row becomes visible only at the official-close stage. Warm-up facts initialize indicators but never contribute return or fills. Changing any fact after a deadline cannot change an earlier decision, `result_hash`, signal, or fill.

The MVP uses one explicit bounded rolling context: the newest 512 complete five-minute bars, 499 official daily bars before the current day, and 512 calendar-day facts. The report limitation `BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR` makes this research boundary visible. It bounds each evaluation context but is not evidence that the broader `BC01` memory/database resource ceilings have passed.

Every actionable signal has one exact event-time identity: `signalAt == EvaluationResult.snapshot.evaluatedAt`. For an intraday decision, that value is the latest input minute's `receivedAt`; for an official-close decision, it is the official daily fact's `receivedAt`. The runner must not substitute the source minute's `barEnd`, a five-minute bucket end, a hard-coded 15:00, or the local wall clock. An order may be considered only on a subsequent canonical candidate bar whose `openAt >= signalAt`. The discrete replay order may finish the producing event at a boundary before processing the next minute-bar event with that same boundary `openAt`, so equality is valid without permitting a fill inside the producing bar or bucket. Production historical minute facts normally set `receivedAt == barEnd + 12s`; ordinary minute-derived signals therefore still begin consideration in a later minute and gain no lookahead. A fill records `filledAt == openAt` of that execution minute.

## Simulated Execution Model

Formula version `execution-model-v1` is deterministic and belongs only to `BACKTEST`:

- a signal cannot fill in its producing minute or five-minute bucket; the earliest candidate is a subsequent tradable one-minute bar in discrete replay order whose `openAt` is not earlier than the signal's `receivedAt`-based event time, with same-boundary equality allowed only after the producing event has completed;
- a zero-volume candidate is the MVP non-tradable proxy and leaves the order pending; the engine advances through each contiguous canonical candidate to the first later positive-volume minute, fails an omitted required candidate as `MISSING_NEXT_MINUTE`, and emits `SUSPENDED` only if the finite replay closes after encountering zero-volume minutes without a later tradable bar;
- the default fill price derives from that execution bar's open plus configured directional slippage in basis points, and `filledAt` is exactly that bar's `openAt`, never its `barEnd`;
- buy quantities use 100-share board lots; holdings cannot become negative, and no leverage or naked shorting is allowed;
- A-share T+1 is enforced by trading date, and cash, plan maximum position, target position, and sellable quantity cap every fill;
- actual daily `stk_limit` determines limit-up/limit-down unavailability; suspension, missing next minute, end of range, insufficient cash, invalid lot, and T+1 each produce an explicit unfilled reason;
- commission rate, minimum commission, stamp-duty rate, transfer-fee rate, and slippage are required versioned configuration. Money, fees, cash, and profit/loss use integer fen or exact `Decimal`, never binary floating point. Rates and slippage convert to exact integer numerator/denominator pairs: fee rates round upward to fen, buy slippage rounds upward, sell slippage rounds downward, and partial-lot cost-basis allocation rounds to the nearest fen with positive half ties upward. None of these calculations reads the ambient Decimal precision or rounding mode;
- `RISK_BREACH` is a risk event and never implies a fill by itself.

The report exposes three execution simplifications verbatim: `ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY` because volume zero is the MVP suspension/non-tradable proxy; `FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME` because the simulator does not model participation or market impact; and `CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE` because either the raw open or slipped price reaching the actual daily limit blocks the fill. These are research limitations, not hidden broker behavior.

Every `ExecutionOutcome` carries immutable `resolvedAt` and `sourceBarId` evidence in its identity, report payload, and retained detail hash; persisted outcome-detail `eventAt` equals `resolvedAt`, not the original signal time. A filled or bar-rejected outcome resolves at that bar's `openAt` and names its `sourceBarId`; an ignored non-executable signal resolves at `signalAt` with no source bar. If the first required canonical session minute is absent and a later bar exposes the gap, the order fails closed as `MISSING_NEXT_MINUTE`, resolves at the later observed bar's `openAt`, and records that bar's `sourceBarId` instead of skipping ahead. `NO_NEXT_MINUTE` is reserved for replay finalization with no observed candidate and therefore has no source bar; `SUSPENDED` retains the observed zero-volume source evidence and resolves at the replay boundary. Lunch and the next valid session open are canonical boundaries, not fabricated minute gaps.

Every fill traces to `run_id`, `plan_sha256`, `dataset_hash`, `result_hash`, signal identity, source bar identity, execution-model version, and fee-model inputs.

## Run Identity, Idempotency, and Recovery

The exact versioned `run_id` preimage is owned by [`backtest-engine`](SPEC-backtest-engine.md); this umbrella specification neither redefines nor silently extends it. An empty normalized initial-lot list preserves the existing byte-identical `backtest-run-v1` preimage and remains readable and reusable. A non-empty public initial-lot list selects `backtest-run-v2` and represents every lot with normalized `BacktestInitialLotInput` containing a stable `lotKey`. `planVersionId` is only a lookup/audit reference: Web submission uses it to acquire exactly one immutable plan snapshot, but it does not participate in either identity preimage. Changing either exact preimage requires a new formula version and migration decision.

The same inputs and code-compatible formula versions produce the same ordered decisions, hashes, fills, daily equity, report bytes, and `run_id`. A repeated completed run is a no-op/read of the existing result. The current MVP has no strategy event cursor: decision/execution replay runs in memory from the beginning of the frozen dataset. If interruption occurs during result persistence, a retry deterministically replays the frozen input and idempotently completes staged rows under unique identities, without duplicate decisions, signals, fills, or equity rows. Conflicting content under an existing identity fails closed. Event-cursor resume during strategy replay remains open `BC01` acceptance work.

Result publication uses a staged/materialized recovery protocol. It first stages the canonical summary, then writes fills and bounded detail batches idempotently. One verification transaction sets the internal `materialized` visibility flag only when the summary's complete `reportHash`, the expected fill/detail counts, and canonical `(identity, contentHash)` set hashes for the exact fill and detail sets all agree with stored rows. The first successful publication persists those fill/detail counts and identity-content set hashes as materialization metadata; every retry of an already published run must match that metadata exactly. Before the transaction commits, the staged summary, fills, and details are hidden from ordinary summary/list/fill/detail reads and statistics; only explicit recovery and maintenance paths may inspect them. Ordinary summary/fill/detail reads cross-check each SQL identity against its hashed canonical payload before returning it, and a requested detail-kind filter is applied only after that validation so it cannot conceal a corrupt row. `materialized` is the only publication gate and is not a public run status. The existing result status enum remains `COMPLETED`, `FAILED`, or `CANCELLED` for compatibility reads, but the new job-based publication path writes only materialized `COMPLETED` results and keeps attempt failure/cancellation in `backtest-jobs`. The summary JSON and fill CSV are then atomically written as reconstructable projections of the materialized long-lived summary/fill ledger. On a repeated `run` or recovery request, missing or corrupt summary/ledger files are rebuilt without provider access, strategy replay, or duplicate fills. Conflicting staged identities, content-set hashes, incomplete row counts, or published metadata mismatches fail closed.

`reportHash` identifies the original complete canonical `BacktestRunReport`, including the decision/signal/outcome/equity detail present when the run was first materialized. It remains a long-lived audit identity after detail retention runs, but it is not the byte hash of either emitted file and does not promise that expired detail can be reconstructed. Rebuilt assets use `backtest-report-summary-v1` plus the durable fill ledger only; retention-deleted detail stays deleted.

## Results and Reports

The compatibility result schema can read bounded `COMPLETED`, `FAILED`, and `CANCELLED` summaries. The new job-based path materializes only complete `COMPLETED` research results with input identities, coverage, data-quality blockers, assumptions, start/end event time, and formula versions; failed/cancelled attempt diagnostics remain bounded job records so the same deterministic `run_id` can later complete. The current CLI materializes completed runs, while migration to atomic result/job publication remains open. Successful in-memory reports and retained detail rows include:

- data coverage and gap summary;
- ordered decisions and `result_hash` values;
- signals and explicit filled/unfilled outcomes;
- cash, positions, realized/unrealized profit and loss, and daily equity;
- total return, maximum drawdown, trade count, win rate, turnover, and total costs;
- `BLOCKED`/`SKIPPED` counts and every model limitation.

Every persisted detail identity is scoped by `run_id` as well as its decision/signal/outcome/equity identity. Two runs may legitimately share a production `result_hash` while differing in execution assumptions; they must persist separate detail rows rather than collide or suppress one another.

Metric semantics are also explicit limitations: `DAILY_EQUITY_DRAWDOWN_SAMPLING` means maximum drawdown uses daily equity points and does not claim an intraday trough; `WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP` means win rate classifies sell fills rather than reconstructed round trips; and `METRIC_DECIMAL_PRECISION_28_HALF_EVEN` means return, drawdown, and win-rate division uses an isolated Decimal context with precision 28 and `ROUND_HALF_EVEN`. All three tokens remain in the report assumptions/limitations, and ambient process precision cannot change metric bytes or identities.

The MVP emits stable `backtest-report-summary-v1` JSON and a simulated-fill CSV through the CLI. Both can be deterministically reconstructed from the long-lived summary/fill rows when absent. Decisions, signals, unfilled outcomes, and daily equity remain separate bounded detail rows subject to the same 100-run/90-day or 14-day retention rules; they are never embedded in a permanent canonical blob, and pruning them makes them unavailable. The system persists daily rather than minute account equity. Raw provider responses and duplicated historical bars are not result artifacts. The FastAPI/Vue direction and the corrected `backtest-api` and `backtest-web` specifications are approved, while OpenAPI/generated-type changes and frontend implementation remain unauthorized and unimplemented. A router-only placeholder is not sufficient.

## Retention and Performance

Retention is explicit for published details and abandoned unpublished stages:

| Record class | Default retention |
|---|---|
| run summary, hashes, assumptions, final metrics, and fill ledger | long-term |
| successful decision/signal/daily-equity detail | newest 100 runs and no more than 90 days; whichever bound is reached first |
| failed/cancelled job diagnostics and any compatibility diagnostic detail | 14 days |
| minute-level debug trace, when explicitly enabled | 14 days |
| abandoned unmaterialized, unpinned staged summary/fill/detail | 14 days; all three record classes become eligible under the same bounded cleanup budget |
| pinned run and its detail | exempt until manually unpinned/deleted |
| deduplicated market revisions referenced by a dataset/run | retained |

Cleanup uses indexed `run_id`, status, completion/creation time, materialization, and pin state, deletes in bounded batches of at most 1,000 rows, and never runs a large `VACUUM` while monitoring or backtesting is active. `prune` first removes eligible abandoned staged detail/fill/summary rows within the same total batch budget, then published expired detail; recent or pinned stages remain available for recovery. WAL checkpoint occurs at safe phase/shutdown boundaries; `VACUUM` is an explicit offline maintenance operation.

Pin state and prune exemption are implemented in the result store. The current MVP CLI exposes `list` and `prune` but not pin/unpin; public pin and initial-lot management remain part of the open operational acceptance work.

At the approved maximum of 10 symbols, one normal year is approximately 600,000 minute rows and 5 years approximately 3,000,000. Queries must use `(symbol, bar_end)` or dataset/run/date indexes and replay in day-sized bounded chunks rather than loading a multi-year dataset into memory. Final `BC01` performance tests must define explicit database, WAL, memory, task, and thread ceilings and prove repeated runs do not grow market or result tables; those resource ceilings are not yet verified by the current MVP.

## Security and Operational Boundaries

- Always require an environment secret reference and explicit network authorization for `backtest sync`.
- Always validate downloaded facts before persistence and preserve stable sanitized provider errors.
- Always keep network calls outside database transactions and keep the three storage domains isolated.
- Always resolve exactly one immutable plan version for an accepted Web run in a read-only live-store transaction, persist its validated snapshot before responding, and perform zero live-store writes during submission.
- Always use the explicit CLI `--plan` file for direct CLI runs and enforce zero live-store reads and writes by workers and replay after the durable submission boundary.
- Always request historical calendars for explicit `SSE`/`SZSE` exchange identities and block `.BJ` until a separately verified BSE calendar contract exists.
- Always recompute frozen artifact hashes on read and recover report files only from verified staged canonical content.
- Always state unadjusted-price/corporate-action limitations prominently in configuration and reports. The MVP does not silently apply `qfq` or `hfq` and does not model dividends, splits, rights issues, or other corporate actions.
- Ask first before changing timestamp mapping, adjustment policy, formula/execution version, retention defaults, approved API paths/transports, or Web trust boundaries.
- Never count a backtest as T058 evidence, publish its signals, mutate live state, or connect it to a broker.

## Testing Strategy

Final RED-to-GREEN acceptance must include at least two symbols across multiple trading days and verify:

- weekends, lunch, 09:30/15:00 boundaries, and explicit handling of the observed 241-row response;
- missing, duplicate, conflicting, unordered, null, and illegal minute facts;
- one valid buy and one reduction/exit signal, next-minute rather than same-bucket execution, final-minute no-fill, actual limit locks, T+1, board lots, insufficient cash, fees, and slippage;
- failure-closed gaps (`MISSING_NEXT_MINUTE`) with exact `resolvedAt`/`sourceBarId`, and insufficient warm-up/reference data;
- no lookahead by mutating later facts and comparing every earlier identity/hash;
- byte-stable repeated reports, staged-result interruption/retry recovery, no duplicate fills, and the still-open strategy event-cursor recovery boundary;
- exact `signalAt == snapshot.evaluatedAt == receivedAt` provenance, next-tradable-minute `filledAt == openAt`, and rejection of same-minute or `barEnd` substitution;
- explicit SSE/SZSE `trade_cal` calls, strict raw reference-row rejection, pre-network `.BJ` rejection, read-snapshot/short-publication freeze races, O(1) manifest-key lookup, frozen-artifact tamper detection, and materialized summary-JSON/fill-CSV reconstruction;
- `BC01` exact logical equality of live state before/after Web submission and before/after worker/replay, zero live-store writes during submission, zero live-store reads/writes after the durable boundary, zero notification/network calls during replay, and isolated database paths;
- bounded memory, SQLite/WAL, task, and thread growth plus retention/pin behavior.

Default tests use fixtures and no credentials or network. Real historical acquisition probes are separately authorized validation assets and do not replace deterministic committed tests.

## Success Criteria

- Historical data is incrementally synchronized once, content-deduplicated, verified, and reusable by many offline runs.
- A frozen dataset and identical configuration reproduce the same `run_id`, decisions, fills, equity, and report bytes.
- Missing or semantically unverified data blocks execution with an explicit reason; no future fact affects an earlier result.
- Simulated execution obeys next-minute, actual-limit, T+1, board-lot, cash, position, fee, and slippage contracts.
- Web submission leaves live database state unchanged after its one read-only immutable-plan lookup, and worker/replay leaves live database state and notification counts unchanged without reading that database.
- Long-term summaries/fills remain queryable while bounded detail retention and indexes prevent unbounded performance degradation.
- Active persisted and exposed backtest times remain canonical `Asia/Shanghai`/`+08:00` end to end, with no host/browser timezone conversion; isolated UTC v1 compatibility bytes are never silently reinterpreted.
- T058 remains independently blocked until its live-network, entitlement, timestamp, and market-window evidence passes.

## Review Status

The user approved the hybrid local-data and offline-backtest direction, isolated storage, and bounded retention policy on 2026-08-25, then approved the six-module capability map and direction on 2026-08-26. On 2026-08-26, the user also confirmed the six detailed module specifications and approved the `local-web` Backtest Extension Boundary. The user then explicitly confirmed that every backtest time uses `Asia/Shanghai`/`+08:00`, with no separate active UTC contract, and confirmed the remaining corrected cross-module clauses. The aggregate detailed specification is therefore approved as corrected. The local MVP command surface and review-driven integrity regressions exist under `BT001`–`BT008`; the latest focused backtest gate is 97 passing tests, but that local work is uncommitted and does not renumber or weaken `T058`/`T059`. Section 15 of the bilingual implementation plan was approved on 2026-08-26. That approval authorizes only generating the bilingual `BT009`–`BT050` task list. The generated task list still requires separate explicit approval; API/Web implementation, commit, push, dependency installation, and any network access remain unauthorized. Broader multi-symbol/multi-day actionable journeys, cancellation/crash recovery evidence, explicit resource ceilings, public pin/initial-lot management, and authorized real historical synchronization remain open acceptance work.
