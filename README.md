# Trade Plan Monitor

Current local verification: [One Plan Workflow acceptance](docs/verification/2026-10-03-unified-plan.md). Live-provider readiness and deployment are separate verification work.

> Current plan workflow: [One Trade Plan Workflow](docs/specifications/monitoring/SPEC-unified-plan.md). Use /plans to paste source, extract one draft, edit/review, explicitly activate, monitor condition periods and explicitly simulate whole trades. There is no separate daily-plan product. Fundamentals are reviewed only when generating the plan; reminders and acknowledgement never change holdings. See the current verification report for executed evidence and scope limits.

Trade Plan Monitor is a local-first, AI-assisted monitor for deterministic A-share trade
plans. It turns reviewed plans and normalized market data into explainable reminders; it does
not place orders.

[简体中文](README.zh-CN.md)

## Trade plans

Current Schema 5 plans also use the existing isolated backtest path with explicit frozen research input. Live activation is unnecessary; server review remains authoritative. Empty operation scripts produce evidence without changing holdings. See the [replay guide and synthetic minute/daily example](docs/operations/unified-replay.md) and [replay verification](docs/verification/2026-10-03-unified-replay.md).

Open `/plans` in the local Web interface to extract one `plan-extract-v8` candidate, edit its source-defined conditions and parameters, register explicit human supplements, save, review and activate. Missing strategy definitions remain visible and prevent activation. Source or parameter edits require a fresh review bound to the exact saved version. There is no plan-family selector or separate daily-plan workspace.

Each condition declares its required evidence period. A rule confirmed by an official daily close uses the next exchange session; a completed five-minute confirmation uses the current session. A condition tree can combine both periods with one evidence cutoff. Optional price zones, allocation metadata and technical risk branches follow the source rather than being required template fields. Initialize separate CORE/TACTICAL simulation holdings, then explicitly confirm the entire currently offered trade in fixed 100-share units. The server rechecks the current quote, calendar, T+1, CORE protection, maximum holdings, review, cause and revisions in one transaction. Reminders and acknowledgements never trade. Confirmed technical risk obligations retain their source-defined timing and reviewed removal. Simulation inventory is isolated from registered historical real holdings and from backtest portfolios; broker reports and partial or unknown orders are outside this workflow.

Fundamentals are reviewed by the user when generating the plan and are excluded from runtime and simulation gates. Original fundamental/announcement text stays visible as review-bound background; mixed sentences retain their technical remainder and parameter bindings. This finite source treatment does not prove arbitrary natural-language classification. Schema 1–4 bytes, hashes and historical evidence remain readable without conversion; old active plans require a newly reviewed current version. Existing historical index research and backtests remain isolated.

See the [current specification](docs/specifications/monitoring/SPEC-unified-plan.md) and [latest local acceptance](docs/verification/2026-10-03-unified-plan.md). Deterministic offline checks do not certify current live providers or approve a user’s source plan.

## Runtime recovery revision

The normal installed Web entry and packaged frontend now use monitor contract `2`. Compatible provider semantics remain valid across time; current dependency availability, recovery progress and per-plan data eligibility are checked separately. After a safe stop, restart resumes durable work without replaying completed decisions or interpreting reminders as trades. Configuration changes use safe stop → edit → new process. See the [operating guide](docs/operations/live-certification.md#runtime-recovery-and-normal-restart) and [final acceptance record](docs/verification/2026-10-03-unified-plan.md) for exact evidence and limits. Current plan operations use explicit whole-trade simulation with an isolated inventory; real-fill registration is absent from the current API and interface.

The product-status entries below retain the earlier T/WEBF implementation history. Their old startup age gate and v1 status descriptions are superseded by this revision.

## Product Status

The installed command serves the Vue SPA, REST and WebSocket on loopback. The backend owns persisted plan/review state, monitored evidence, recovery progress and atomic isolated simulation; the browser renders its projections. `/plans` provides the current source-to-activation workflow, `/alerts` provides audited idempotent acknowledgement, and `/system` explains runtime progress and unavailable dependencies. Missing projections are typed unavailable responses; genuine storage/service faults remain errors.

The dashboard retains shared index charts and turnover facts separately from plan decisions. Frozen index-condition plans and isolated backtesting retain their original research interpretation; current plan unification introduces no new index judgment. Historical provider observations are not current readiness. `899050.BJ` remains a known `DEFERRED` identity outside current trading scope.

Backtest `sync`, `verify`, `run`, `list` and `prune` use isolated market/result databases. The [backtest acceptance contract](docs/verification/backtest-acceptance.md) preserves fixed regression budgets. Default automated tests use deterministic providers; live Tushare, AI and Webhook operations require their own authorization. Configuration, certification and safe restart are described in the [operations guide](docs/operations/live-certification.md).

## Safety Boundaries

- The live system is monitoring and reminder software, not a broker, order router, or investment
  adviser. Every actionable reminder carries the literal `仅提醒，不会自动下单。`; isolated offline `BACKTEST` creates clearly labeled research fills, and the current plan workflow records only explicit user-confirmed whole simulated trades in isolated simulation inventory (retaining the established `daily-simulation-v1` receipt format).
- Plans are typed, reviewed, versioned, and immutable after activation. AI output remains an
  untrusted draft until deterministic validation and user review succeed; extraction and draft
  save never activate it automatically.
- Prices are stored as integer fen, quantities as integer shares, and A-share timestamps as
  timezone-aware `Asia/Shanghai` values.
- Missing, stale, unauthorized, or semantically unverified market data fails closed.
- Board-index data never creates a global market-strength opinion or hidden trading rule. A plan
  with no index condition keeps its original decision when reference-index data is absent.
- All provider credentials are stored directly in the ignored `config/app.yaml` for this personal
  tool; environment variables and separate credential files are not read.
- The Web listener accepts only the literal `127.0.0.1`; authentication is not implemented.

## Quick Start

The following PowerShell workflow starts the packaged local UI from a clean source checkout.
Dependency installation needs package-registry access once; the verification and startup steps
make no live Tushare, AI, or Webhook call.

### 1. Requirements

- CPython 3.14.x (`>=3.14,<3.15`); development is verified with Python 3.14.7.
- Node.js `^20.19.0`, `^22.13.0`, or `>=24.0.0` and npm 11.8.0.
- Windows PowerShell, with the current directory set to `trade-plan-monitor/`.

### 2. Install from a clean checkout

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Push-Location web
npm install --include=optional --no-package-lock
npm run build
Pop-Location
```

`npm run build` keeps the ordinary `web/dist/index.html` output and copies the same complete
build into the ignored Python package staging directory. The installed Web command does not fall
back to the current working directory or the frontend source tree when those assets are absent.

### 3. Configure local credentials

```powershell
Copy-Item config\app.example.yaml config\app.yaml
```

The YAML file contains provider settings and direct Tushare/AI credentials. The versioned example
uses replaceable placeholders and selects the verified
`https://api.quicksync.cn` Tushare-compatible endpoint and the DeepSeek OpenAI-format endpoint
`https://api.deepseek.com` with primary model `deepseek-v4-flash` and additional model
`deepseek-v4-pro`. The AI profile, display name, base URL, primary and additional models, timeout,
retry budget, input limit, output limit, temperature, and credentials are configurable. All models
under one `ai` section share that section's transport settings and credential. The local
`config/app.yaml` copy is ignored by Git. Replace these fields directly:

```yaml
tushare:
  token: replace-with-your-tushare-token
ai:
  api_key: replace-with-your-deepseek-api-key
```

`config/app.yaml` is the only credential source. Do not commit it, databases, backups, or build
output.

Web startup validates the strict YAML and creates immutable AI model bindings for the server
lifetime. The plan workbench lists every configured model in the provider selector. The general
monitoring `DEGRADED` state remains independent and does not prove Tushare readiness.

### 4. Start the packaged local Web UI

```powershell
trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` on the same computer. Stop the foreground process with `Ctrl+C`.
The monitoring header honestly reports `DEGRADED` with read-only state and no next poll when a
required certified profile is missing, expired, tampered, endpoint/schema/scope mismatched, or not ready.
Open `/plans` to use AI drafting and persistent plan management. The first lifespan startup creates
or upgrades `data/monitor.sqlite3`; saving, querying, importing, activating, and deactivating plans
uses that same SQLite file on later starts. Keep the database and its WAL/SHM companions private
and do not copy an in-use WAL database as a backup.
To change `config/app.yaml`, stop the foreground Web/monitor process and wait for it to exit, edit the file, then start a new process. Do not edit provider settings while it runs. If startup rejects invalid configuration, correct the file while stopped and start again. A failed stop must be resolved before another instance uses the same database. Semantic-file metadata refresh alone does not require a restart.

### 5. Offline verification

```powershell
python -m trade_plan_monitor --help
python -m pytest tests/unit/test_package.py tests/integration/test_packaging.py -q
Push-Location web
npm test -- --run
npm run type-check
npm run build
Pop-Location
```

These checks validate the installed entry, package assets, frontend tests, types, and production
build without contacting a live provider.

### Browser, NVDA, and performance gates

The real-browser gate uses deterministic fake REST contracts and must not receive a provider
token. It covers `/backtests`, `/backtests/new`, `/backtests/data`, and
`/backtests/:runId` in Chromium without contacting Tushare, AI, Webhook, or any other
external service. The result journey includes server-resolved reference-market coverage, the
frozen index resource, exact plan paths, and navigation to persisted decision evidence:

```powershell
Push-Location web
npm run build
npm run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/accessibility.spec.ts
Pop-Location
```

Run the browser gate at 320, 768, 1024, and 1440 CSS pixels with keyboard-only navigation,
200-percent text, and reduced motion. It passes only with no console or API failure, no serious or
critical axe violation, at most one in-flight request per resource, one polling timer per active
job at an interval of at least two seconds, no polling after a job becomes terminal or its view is
hidden/unmounted, at most 100 rows per result table page and 2, 000 equity points, and zero ECharts
bytes before the equity tab is selected. The approved acceptance profile is Chromium-only and
does not claim Gecko/Firefox compatibility evidence.

On Windows, complete one NVDA keyboard pass across the same four routes. Confirm the page title
and heading, landmark and navigation names, field labels and focused error summary links, labelled
table scrolling, modal focus containment and restoration, tab and pagination state, export
controls, and the exact equity table alternative to the chart. Polling must announce a changed
state once without stealing focus or repeating an unchanged state. Record the date, browser/NVDA
versions, route/checklist result, and reviewer outside Git; keep screenshots, traces, downloads,
profiles, and other raw evidence outside the repository.

Measure performance from the production build served on exact loopback with a clean Chromium
profile at 1440×900, 4× CPU slowdown, and 20 ms loopback latency. Use five warm-up navigations and
20 measured navigations for each of the four routes. The fixed p75 limits are LCP ≤ 2.5 seconds,
INP ≤ 200 milliseconds, and CLS ≤ 0.10; interaction latency must also be ≤ 200 milliseconds p95.
The entry/shared bundle excluding ECharts must be ≤ 150 KiB gzip, every non-chart route must be
≤ 100 KiB gzip, and the asynchronous ECharts chunk must be ≤ 450 KiB gzip. Store profiles and
measurement output outside Git; an unavailable or flaky measurement environment blocks the gate
instead of weakening a threshold.

The production backtest workflow remains `DATA_SYNC` → `DATASET_VERIFY` → offline
`BACKTEST_RUN`. Only data synchronization may access the network, with explicit human
authorization and the API request field `allowNetwork: true`. Passing the fake browser gate never authorizes live synchronization
and never proves Tushare availability or semantics.

## Commands

Run backend commands from `trade-plan-monitor/` and frontend commands from `web/` unless the
command changes directories itself.

| Command | Purpose | Current availability |
|---|---|---|
| `trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765` | Serve packaged SPA, API, WebSocket, file-configured AI drafting, and persistent plan management | Available; WEBF05 composes the monitor lazily and reports honest read-only `DEGRADED` until live prerequisites are verified; missing projections remain unavailable |
| `python -m trade_plan_monitor --help` | Show the stable installed command surface | Available |
| `python -m pytest -q` | Run the complete backend suite | Available; offline |
| `python -m ruff check --no-cache src tests` | Run backend lint | Available; offline |
| `python -m compileall -q src/trade_plan_monitor` | Compile-check backend modules | Available; offline |
| `python scripts/generate_frontend_types.py --check` | Detect OpenAPI/generated TypeScript drift | Available; offline |
| `npm test -- --run` | Run frontend unit tests | Available in `web/`; offline |
| `npm run type-check` | Check Vue and TypeScript | Available in `web/`; offline |
| `npm run build` | Build and stage production SPA assets | Available in `web/`; offline after dependencies are installed |
| `python -m trade_plan_monitor validate` | Dispatch configuration/plan validation | Injection boundary; standalone console requires an explicit service factory |
| `python -m trade_plan_monitor monitor --once` | Dispatch one headless monitor cycle | Injection boundary; standalone console requires an explicit service factory |
| `python -m trade_plan_monitor replay` | Dispatch deterministic replay | Injection boundary; standalone console requires an explicit service factory |
| `python -m trade_plan_monitor backup` | Dispatch verified online backup | Injection boundary; standalone console requires an explicit service factory |

An injection-boundary command raises `runtime service factory is not configured` when invoked
through the current standalone console entry. This is an explicit incomplete-composition signal,
not a successful no-op.

## Architecture

```text
reviewed text ─→ AI drafting ─→ typed plan validation ─→ immutable active plan
                                      │                         │
Tushare ─→ normalized complete bars ──┴──→ deterministic decision engine
                                                    │
                                                    ▼
                                         transactional outbox
                                                    │
                                                    ▼
                                            monitor runtime
                                                    │
                                                    ▼
                           FastAPI REST/WebSocket + packaged Vue SPA
                                                    │
                                                    ▼
                                      127.0.0.1:8765 only
```

The target runtime is one Python process owning FastAPI lifecycle, the monitor runtime,
deterministic decision engine, SQLite WAL state, and local Vue SPA. Synchronous Tushare work and
asynchronous AI work use separate bounded execution paths so AI latency cannot stall market-data
monitoring. Repositories never perform network I/O.

## Tushare Capabilities

The adapter exposes one independent capability probe and five normalized operations:

| Normalized operation | Tushare interface | Use |
|---|---|---|
| `realtime_minutes` | `rt_min` | Requested-symbol real-time minute rows |
| `current_day_minutes` | `rt_min_daily` | Current trading-day one-minute rows |
| `trading_calendar` | `trade_cal` | Trading-day/session decisions |
| `daily_limits` | `stk_limit` | Official daily up/down limits |
| `daily_bars` | `daily` | Official unadjusted daily bars |

The example configuration selects `https://api.quicksync.cn`. The `create_tushare_client` factory
reads `tushare.token` from `config/app.yaml` and sets the endpoint on
one official `tushare==1.4.29` `DataApi` instance instead of mutating the SDK's process-global
endpoint. Plain HTTP, embedded credentials, query strings, and fragments are rejected.

An explicitly authorized check on 2026-08-25 verified `stk_mins` through both HTTPS and the
official SDK: one `600000.SH` trading day returned 241 one-minute rows for 2026-08-24, covering
09:30:00 through 15:00:00 with the expected eight fields and no duplicate, null-required,
invalid-OHLC, negative-flow, or wrong-symbol row. That observation alone does not prove upstream
label semantics, so the adapter still defaults to `UNVERIFIED`. The reviewed backtest composition
must explicitly opt into the project policy `TUSHARE_STK_MINS_241_END_V1`, described below. Neither
the observation nor that historical policy replaces the separately required live `rt_min` and
`rt_min_daily` capabilities.

Set `tushare.token` in `config/app.yaml` before a separately authorized live capability probe.
Capability, account permission, rate limit, and minute-label semantics are discovered independently;
configuration never implies availability. A denied or unverified required capability blocks actionable output.
The default contract suite uses deterministic fake DataFrames:

```powershell
python -m pytest tests/integration/test_tushare_contract.py -q -m "not live"
```

## Historical Backtesting

The approved backtest design uses a hybrid workflow: an explicitly authorized `DATA_SYNC` incrementally downloads `stk_mins`, `trade_cal`, `stk_limit`, and unadjusted `daily` facts into `backtest-market.sqlite3`; local verification freezes an exact `dataset_hash`; every formal run then reads that frozen dataset fully offline and writes only result artifacts to `backtest-results.sqlite3`.

The `/backtests/new` page lists real immutable plan versions that the backend currently marks `canActivate=true`, including eligible inactive drafts. The user selects one exact version; submission revalidates it and persists its canonical plan snapshot before the accepted receipt is returned. Saving a newer version later cannot change the queued job, an older result, or its established hashes.

Market and result paths must resolve to different files. Before creating tables, each store rejects an existing live-monitor database or the other backtest storage domain, preventing a misconfigured path from mutating unrelated state.

Historical rows are content-deduplicated and reused across runs. Provider corrections create immutable revisions and a new dataset hash instead of changing an old result. The historical adapter defaults to `UNVERIFIED`; the worker composition explicitly selects versioned profile `TUSHARE_STK_MINS_241_END_V1`, preserves the 09:30 source row as non-strategy `opening_special`, and maps the remaining end-labeled rows to exactly 240 canonical trading minutes. This evidence never completes live task `T058`.

One dataset accepts 1–10 unique symbols, at most 5 calendar years of backtest dates, and at most 2 calendar years of warm-up. Historical calendar sync explicitly calls `trade_cal` once per needed `SSE`/`SZSE` exchange. Tushare's official calendar contract does not list BSE, so `.BJ` historical scopes are currently rejected before network access with `UNSUPPORTED_HISTORICAL_CALENDAR:BSE`; live `.BJ` plan support is unaffected. The real historical adapter rejects unparsable/duplicate raw rows plus wrong calendar exchange/range, daily symbol/range, or limit date. Because `stk_limit(trade_date)` is market-wide, other valid symbols on that date remain legal; sync selects the requested symbols and then requires every normalized reference set—even during `refresh`—to match exactly or fail before persistence as `INVALID_RESPONSE:<surface>`. Every frozen artifact is content-hashed again when read, so a modified local payload cannot be replayed under an old `artifact_hash`.

Frozen verification also reports stable `INVALID_<KIND>:<identity>:<date>`, `INVALID_CALENDAR_CHAIN:<exchange>:<date>`, and `PRICE_OUTSIDE_DAILY_LIMIT:<symbol>:<date>` blockers instead of guessing or repairing corrupt facts. It validates daily minute batches under one WAL read snapshot, then holds a short `BEGIN IMMEDIATE` only to recheck every selected head and publish; a concurrent correction aborts the freeze. Validated manifests use an O(1) cached `natural_key` index for later membership lookup, followed by the normal artifact re-hash.

All backtest hashes share exact Decimal canonicalization: numerically equal scale variants such as `0.0003` and `0.00030` have the same canonical text and identity, while binary floats and fixed-point expansions over 10, 000 characters fail closed. The backtest reuses reviewed plan hashes, normalized bars, indicators, close reconciliation, and the pure decision engine. `execution-model-v1` is backtest-only: `signalAt` equals the producing decision's `snapshot.evaluatedAt` and the source fact's `receivedAt`; only a subsequent candidate bar with `openAt >= signalAt` may fill. Discrete replay may complete the producing event before processing a next-minute bar at the same boundary, so equality is valid without filling the producing bar/bucket; production historical minute facts normally use `receivedAt == barEnd + 12s`, which keeps the ordinary path in a later minute without lookahead. A fill records `filledAt` as that execution minute's `openAt`. A zero-volume minute leaves the order pending through contiguous canonical candidates until the first later positive-volume minute; it becomes `SUSPENDED` only if replay ends without one. A missing required session minute fails as `MISSING_NEXT_MINUTE` when a later bar exposes the gap. Every `ExecutionOutcome` includes immutable `resolvedAt` plus the resolving `sourceBarId` when a bar exists; `NO_NEXT_MINUTE` alone resolves at finalization without a source bar. Fees, slippage, and partial-lot cost allocation use exact integer-rational arithmetic with explicit fen rounding, independent of the process-global Decimal context. Actual daily limits, T+1, 100-share lots, cash/position bounds, fees, and slippage are applied deterministically. It never invokes the live scheduler, notification outbox, Webhook, WebSocket, or a broker.

Each evaluation uses at most 512 complete five-minute bars, 499 official daily bars before the current day, and 512 calendar-day facts. These bounds enter `run_id` and appear as `BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR`; they are a disclosed research limitation and do not themselves prove multi-year resource acceptance. That independent gate is complete through the BT050/BT008 evidence.

Reports also disclose that zero-volume minutes are treated as a non-tradable proxy (`ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY`), fill quantity is not capped by minute volume (`FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME`), limit locks conservatively use the open or slipped price (`CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE`), drawdown samples daily equity (`DAILY_EQUITY_DRAWDOWN_SAMPLING`), win rate is per sell fill rather than round trip (`WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP`), and metric division is fixed to Decimal precision 28 with `ROUND_HALF_EVEN` (`METRIC_DECIMAL_PRECISION_28_HALF_EVEN`).

Use the backtest data page to submit historical synchronization and local verification, then select the reviewed plan, frozen dataset, initial account, and execution assumptions on `/backtests/new`. Background jobs execute asynchronously with progress and cancellation; the result page provides inspection and report downloads. Only explicitly authorized data synchronization may access the network. Backtest CLI commands and compatibility adapters have been removed; application launch commands still start the Web service.

“从原文准备新计划” prepares one original at a time. Successors link an exact reviewed predecessor; explicitly review and save each entry, then select 1–256 reviewed plans for a single continuous backtest. Composition makes no AI call. Saving extracts unambiguous effective trading dates from their text; only missing/ambiguous dates need confirmation. Authoring and historical-availability timestamps are optional. Preloaded plans without declared availability execute from the effective day's 09:30 Shanghai opening, with the existing plan/account review and market-data checks. See [source preparation](docs/operations/monitor-loop-backtest.md#ml-o02-prepare-and-review-ordered-sources).

New successor extraction keeps unmentioned reviewed rules and fields by default and proposes only source-backed changes. Review shows retained, modified, added and cancelled rules; extraction/validation errors are separate from genuine source ambiguity. Bounded automatic corrections cannot approve a candidate. The generic mechanism passed regression checks and review-assisted live verification with four originals and eight differently worded cases; the new continuous replay completed with 1468 evaluations and zero fills. Semantic review remains mandatory; see the [current verification record](docs/verification/2026-10-17-generic-inheritance.md).

Risk exits now execute by holding cohort. Explicitly excluding new entries keeps the inherited exit for old lots; new lots follow the new plan, with exact batch debits, T+1 and cost accounting. Results show the scope and lot allocations beside rule changes and price diagnostics. The corrected four-original chain completed a separate 1468-evaluation continuous run with zero fills; actual prices failed entry prerequisites, while unquantified conditions remain visible. See [cohort verification](docs/verification/2026-10-18-cohort-risk-execution.md), which supersedes the earlier execution limitation and erroneous fourth-plan cancellation.


Run summaries, assumptions, final metrics, and fill ledgers are retained long-term. Successful decision/signal/daily-equity detail is limited to the newest 100 runs and at most 90 days; failed, cancelled, and opt-in debug detail is retained for 14 days; pinned runs are exempt. Result publication first stages canonical rows in `backtest-results.sqlite3`; ordinary reads and statistics hide all staged rows. One transaction sets the internal `materialized` visibility flag only after the complete `reportHash`, expected fill/detail counts, and canonical identity/content set hashes all match. First publication persists those counts and set hashes, and every published retry must match them exactly; ordinary summary/fill/detail reads also validate each SQL identity against its hashed payload before applying any detail-kind filter. Web/API exports verified JSON and CSV from persisted results. `materialized` is the only publication gate, not a public run status; public statuses remain `COMPLETED`, `FAILED`, or `CANCELLED`. Bounded `prune` maintenance removes unpinned abandoned staged summary/fill/detail after 14 days, while recent stages remain recoverable. Missing or corrupt files can be rebuilt from the long-lived summary/fill rows without network access, replay, or duplicate fills; pruned decision/signal/outcome/equity detail is intentionally not reconstructable. `reportHash` remains the audit identity of the original complete run and is not a file-byte hash. Web/API supports pinning and initial lots. Full minute-by-minute account snapshots and duplicate market rows are not stored. See [SPEC-backtest.md](docs/specifications/backtesting/SPEC-backtest.md) for the isolation, no-lookahead, report, and retention contracts.

## AI Configuration and Credentials

`ai.api_key` is optional unless AI-assisted drafting is enabled and may be stored directly in the
ignored `config/app.yaml`. The default `DEEPSEEK`
profile sends DeepSeek's current `max_tokens`, `thinking={"type":"disabled"}`, and JSON-output
request fields. Change `profile` to `OPENAI_COMPATIBLE` and configure another reviewed base URL,
model, and API key to use a different compatible service. Runtime provider configuration stores
an internal reference, model, bounded timeout/retry/token limits, and an HTTPS base URL (plain HTTP
is accepted only for an explicit loopback host).

API-key material is loaded only by the backend and cannot be returned through the public contract.
The Web page displays only the provider name, model, safe base URL, limits, enabled state, and
whether a key was loaded. It has no provider edit, Token input, secret replacement, or connection
test control. Redirects, embedded URL credentials, query-bearing base URLs, raw model execution,
and secret-bearing validation errors are rejected. AI output is never activated directly.

Web is the primary AI workflow: open `/plans`, paste the source text, submit it, and review the
validated result. The backend holds at most one concurrent extraction and the page polls its exact
operation ID. Changing `config/app.yaml` requires a Web restart. The CLI remains as a
maintenance tool; both commands below make a real provider request and can consume paid tokens:

```powershell
# Send one minimal connectivity request using config/app.yaml.
python -m trade_plan_monitor ai test

# Read one UTF-8 text file and return a review-only structured draft.
python -m trade_plan_monitor ai extract --source .\plan-source.txt
```

Pass `--config <path>` after `test` or `extract` to select another configuration file. The command
rejects a missing/non-file source, invalid UTF-8, source text above the configured character limit,
and a missing or empty configured API key before accepting a result. Web and CLI use the same
application configuration; no environment-variable or separate-file credential fallback exists.

T059 adds an optional, fail-closed connectivity probe. It is not part of ordinary tests and must
not be run without a separately approved real-provider network operation. Review a canonical
lowercase HTTPS base URL and exact model first, then bind authorization to the operation, normalized
target, and model. The digest context is
`trade-plan-monitor:t059:ai-live:test-connection:v1` and includes the three newline separators shown
below, including the final newline:

```powershell
$env:TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL = "https://api.deepseek.com"
$env:TRADE_PLAN_MONITOR_AI_LIVE_MODEL = "deepseek-v4-flash"
$target = "trade-plan-monitor:t059:ai-live:test-connection:v1`n$($env:TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL.TrimEnd('/'))`n$($env:TRADE_PLAN_MONITOR_AI_LIVE_MODEL)`n"
$targetBytes = [Text.Encoding]::UTF8.GetBytes($target)
$env:TRADE_PLAN_MONITOR_AI_LIVE_AUTHORIZATION_SHA256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($targetBytes)).ToLowerInvariant()
python -m pytest tests/contract/test_ai_live.py -q -m live
Remove-Item Env:TRADE_PLAN_MONITOR_AI_LIVE_AUTHORIZATION_SHA256, Env:TRADE_PLAN_MONITOR_AI_LIVE_MODEL, Env:TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL
```

The exact selector is `python -m pytest tests/contract/test_ai_live.py -q -m live`. It uses default
TLS verification, ignores proxy environment variables, disables redirects and retries, and emits
only stable error codes. A pass proves bounded Chat Completions envelope connectivity only; it does
not prove model identity, plan quality, activation safety, or trading correctness.

## Backup and Restore

### Create and verify

The backup service uses SQLite's online backup API while WAL writes may continue. It writes a
temporary candidate, runs `PRAGMA integrity_check`, atomically publishes only a verified
`monitor-backup-*.sqlite3` file, and then applies retention. Never copy an in-use `.sqlite3`,
`-wal`, or `-shm` file as a backup.

The current standalone `backup` command is not yet composed, so do not assume it created a file.
When a runtime integration supplies the database and backup-directory paths, verify every result
before restore. This read-only command is the supported verification boundary; replace the
placeholder with one candidate path:

```powershell
$env:TPM_BACKUP_PATH = "backups\<verified-backup>.sqlite3"
python -c "import os; from trade_plan_monitor.state.backup import verify_sqlite_backup; result = verify_sqlite_backup(os.environ['TPM_BACKUP_PATH']); print(result.integrity_check, result.schema_object_count)"
```

Proceed only when the first value is exactly `ok`.

### Restore

1. Stop the foreground Web/monitor process; never restore into an open database.
2. Resolve the intended database and backup to exact local paths. Do not use a glob.
3. Run `verify_sqlite_backup` as above.
4. Move the existing database **and any same-name `-wal`/`-shm` sidecars** to one dated recovery
   location rather than deleting or leaving them beside the restore target.
5. Copy the single verified backup to the now-empty configured database path, start the
   application, and
   confirm health before removing the recovery copy.

The application configuration schema does not yet expose database or backup paths; those are
runtime-composition inputs. Unknown YAML fields are rejected, so do not invent `database` or
`backup` sections in `config/app.yaml`.

## Retention

- Verified online backups retain the newest **30 successful backups**. Cleanup considers only
  owned `monitor-backup-*.sqlite3` files inside the configured backup directory, verifies each
  candidate again, and ignores unrelated, invalid, or symlinked files.
- Alert replay and durable monitor-event replay use a default **7-day** replay window. A cursor
  older than retained history fails explicitly instead of silently skipping events.
- No general-purpose automatic deletion policy exists for plans, audits, positions, market bars,
  or the primary SQLite database. Manage those only through a future approved operation, not a
  filesystem wildcard.

## Webhook Defaults

The generic Webhook channel defaults to:

| Setting | Default |
|---|---|
| `enabled` | `false` |
| `endpoint` | `null` |
| `allowlisted_hosts` | empty |
| `timeout_seconds` | `5` |
| `allow_redirects` | `false` and cannot be enabled |

`config/app.example.yaml` intentionally has no `webhook` section; the strict application schema
would reject one. Enabling Webhook delivery requires explicit runtime composition with one HTTPS
endpoint whose exact host is allowlisted. Wildcards, embedded credentials, query strings,
fragments, redirects, and response-body persistence are rejected. Keep it disabled unless an
approved receiver and secret-handling procedure exist.

## Troubleshooting

| Symptom | Meaning and action |
|---|---|
| `WEB_ASSETS_UNAVAILABLE` | The installed distribution lacks a complete Vite build. Run `npm install --include=optional --no-package-lock` and `npm run build` before building/reinstalling the Python package; do not add a cwd fallback. |
| `Cannot find native binding` from Rolldown | npm omitted Vite's platform-specific optional package. Run `npm install --include=optional --no-package-lock`, then retry `npm run build`. |
| UI shows `DEGRADED` or typed `UNAVAILABLE` | Expected while live minute `SourceTimeLabel` semantics or the live board-index provider is unverified, or when an authoritative projection has not completed. The backend keeps health read-only and does not schedule actionable monitoring; actual service/storage/composition faults still return `SERVICE_UNAVAILABLE`. The separately composed plan and persistent position workflows remain available when their stored plan/calendar prerequisites exist. |
| `runtime service factory is not configured` | `validate`, `monitor`, `replay`, or `backup` was invoked before application service composition is wired. |
| Host validation rejects the listener | Use the exact literal `127.0.0.1`; `localhost`, `::1`, `0.0.0.0`, hostnames, and LAN addresses are intentionally rejected. |
| Port 8765 is busy | Stop the other local process or choose another unused port from 1–65535, keeping host `127.0.0.1`. |
| `SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT` / `SQLITE_EMPTY_WAL_RECOVERY_BUSY` / `SQLITE_EMPTY_WAL_RECOVERY_FAILED` | Backtest store startup can recover an empty `-wal` (optionally with `-shm`) only after immutable inspection confirms the complete current schema and no pending migration or metadata correction. SQLite checkpoints and closes the recovery connection; startup then repeats strict inventory and requires all sidecars to be gone. Close other application/IDE database connections if recovery is busy or sidecars remain. Non-empty WAL, rollback journals, orphaned files, unknown/legacy schemas and pending extensions still require stopped, verified maintenance; never delete sidecars manually. Migration inventory itself remains read-only and rejects every sidecar. |
| `SQLITE_SOURCE_BUSY_OR_UNREADABLE` | SQLite byte-range locks on Windows or filesystem permissions prevented reading a source file during preflight. Close other database connections and check file permissions before retrying. Preflight preserves the source. |
| YAML reports an unknown field | Start again from `config/app.example.yaml`; the schema deliberately rejects unsupported sections. |
| Tushare capability is `DENIED`/`UNVERIFIED` | Check `tushare.token` and account permission, then run an authorized live probe. |
| AI returns configuration/authentication errors | Verify `ai.api_key`, profile, base URL, and model in `config/app.yaml`. |
| Frontend generated types drift | Run `python scripts/generate_frontend_types.py --check`; regenerate only as part of an approved API-contract change. |

## No Port Forwarding

Use the application only from the same desktop that owns the process. Do **not** bind to
`0.0.0.0`, a LAN address, `localhost`, or `::1`; do not use SSH/IDE port forwarding, reverse
proxies, tunnels, container port publishing, host aliases, or router exposure. The exact Origin
guard and loopback listener are security boundaries, not deployment inconveniences.

Because there is no login or remote-user authorization, forwarding `127.0.0.1:8765` would expose
sensitive plans, positions, health data, and mutation endpoints outside the supported threat
model. Remote access requires a separately designed and reviewed authentication/deployment model.

## Project Structure

```text
trade-plan-monitor/
├── config/                   # Non-secret app references and sample plan
├── docs/                     # Architecture, specifications, decisions, guides, evidence
├── src/trade_plan_monitor/
│   ├── ai/                   # AI configuration, secrets, adapter, extraction
│   ├── decision/             # Deterministic conditions, risk, priority, hashes
│   ├── domain/               # Typed plans, validation, codecs, stable hashes
│   ├── market_data/          # Tushare normalization, sessions, bars, indicators
│   ├── notifications/        # Alert models, outbox, channels, dispatch
│   ├── runtime/              # Monitoring, recovery, lifecycle, health
│   ├── state/                # SQLite WAL, migrations, repositories, backup
│   └── web/                  # FastAPI routes, security, packaged SPA assets
├── tests/                    # Unit, integration, replay, fixtures
├── web/                      # Vue 3 / TypeScript source and tooling
├── pyproject.toml
├── README.md
└── README.zh-CN.md
```

The project is standalone and must not import from or modify the workspace's `TradingAgents/`
upstream checkout.

## Domain Conventions

- Symbols use standard Tushare form, for example `003043.SZ`.
- Buy quantities follow 100-share board lots; sellable lots follow A-share T+1 by trading date.
- Price-zone boundaries have one owner, so an exact boundary cannot trigger conflicting actions.
- A 15:00 intraday result remains provisional until reconciled with the official daily bar.
- Active plan versions are immutable; changes create a new reviewed version.

The [Huaya Intelligent sample plan](config/plans/003043.SZ.sample.yaml) is the repository's golden
example.

## Documentation

English documents are canonical implementation inputs and matching `.zh-CN.md` files are Chinese review copies. Keep both semantically equivalent in the same change.

Start with the [documentation index](docs/README.md) ([中文](docs/README.zh-CN.md)), [current plan specification](docs/specifications/monitoring/SPEC-unified-plan.md), [capability map](docs/architecture/CAPABILITY-MAP.md), and [operating guide](docs/operations/live-certification.md). Frozen plan/replay contracts are explicitly scoped to compatibility; completed process reports and obsolete attachments are not retained as development entry points.

## Development Workflow

1. Implement one approved workspace task at a time.
2. Read the task, module contracts, and current code before editing.
3. Add a failing test or contract check before behavior/documentation changes.
4. Run affected tests, full regression, Ruff, formatting, compile, dependency, security, and
   bilingual parity gates.
5. Update English and Chinese documents together whenever behavior, commands, architecture, or a
   public contract changes.

## Financial Disclaimer

This project is a personal monitoring and reminder tool. It is not investment advice, a broker,
or an order-execution system. Market data, AI output, indicators, and reminders may be delayed,
incomplete, or incorrect. Users must review every plan and remain solely responsible for every
trading decision.

Preparation now consolidates genuine confirmations and automatically handles explicit source facts, inactive zones and ordered tranches. See [source confirmation verification](docs/verification/2026-10-16-source-confirmations.md).

Backtests now use one “准备计划” entry: default to the previous reviewed plan and review retained, modified, added and cancelled rules. No complete/update document-type choice is required. See [unified preparation verification](docs/verification/2026-10-16-unified-preparation.md).

New source-prepared monitoring-loop backtests use `POSITION_LIMIT_ONLY`: no initial cash is required; authorized order quantities and the current maximum holdings still apply. Daily replay uses frozen, time-scoped adjustment-factor evidence. Trade PnL/fees remain available when their inputs are known; capital returns and equity drawdown are not modeled. Use the [plan-generation template](docs/templates/trading-plan.md) to specify qualitative conditions before review. See [validation](docs/verification/2026-10-17-daily-basis.md).

Completed result summaries include per-plan execution diagnostics: actual versus required prices, unmet market conditions, unresolved qualitative criteria, processing problems and separate execution/data limitations. Known conditions are explained automatically without new confirmation fields. Existing retained results gain the projection on refresh after upgrading; expired audit details remain explicitly unavailable. See [result diagnosis](docs/operations/monitor-loop-backtest.md#ml-o16-per-plan-diagnosis-on-the-result-page).
