# Trade Plan Monitor

Trade Plan Monitor is a local-first, AI-assisted monitor for deterministic A-share trade
plans. It turns reviewed plans and normalized market data into explainable reminders; it does
not place orders.

[简体中文](README.zh-CN.md)

## Product Status

Tasks `T001` through `T059` and `BT001` through `BT050` are implemented and accepted. The packaged
command can serve the built Vue SPA, REST API, and WebSocket routes on exact loopback. WEBF05 now
uses a lazy real monitoring composition: it opens and migrates the shared monitor SQLite, exposes
backend `RuntimeHealthSnapshot`, and owns the committed event stream. Because live minute
`SourceTimeLabel` semantics and the live board-index provider remain unverified, startup honestly
reports read-only `DEGRADED` with `nextPollAt=null` before any token or provider request and creates
no scheduler run task. Dashboard, symbol, and live-index reads without an
authoritative persisted projection remain `SERVICE_UNAVAILABLE`; no generic lifecycle placeholder
or fabricated empty decision state is used. Its `/plans` workflow is usable: startup loads the
project AI configuration once and injects one backend-authoritative persistent plan service over
`data/monitor.sqlite3`. Plan save, query, JSON/YAML import, activation, and deactivation therefore
survive Web process restarts; extraction runs only after the user submits plan text. A successful AI
result enters the shared structured editor only through an explicit review action; saving creates an
inactive draft, and activation still requires a separate user confirmation plus backend approval.
WEBF06 connects `/` to the existing backend-authoritative dashboard snapshot: it renders stock
decisions and shared board-index facts separately from plan-specific index progress, and retains an
honest loading state until a snapshot exists. It adds no browser-side trading rules or provider call.
WEBF09 connects the stock-detail position panel to the existing position REST contract and a
persistent service over the shared monitor database. The backend alone applies active-plan maximums,
stored-calendar T+1, remaining quantity, board-lot, and revision rules; the browser performs input
shape checks and explicit confirmation but never predicts whether a position command is eligible.
WEBF10 connects `/alerts` to the existing alert REST contract and the shared persistent outbox.
Filtering, canonical evidence, and acknowledgement revisions stay backend-authoritative;
acknowledgement is idempotent and audited but never records a fill or changes a position.
WEBF11 hardens the existing T039/T043/T044 monitor stream: reconnects resume from the SQLite
global cursor, and any event gap or `snapshot.required` frame causes a fresh
backend-authoritative dashboard snapshot before reconnecting with that snapshot's `sequence`.
Only a strictly matching heartbeat can reset liveness and permit `LIVE`; duplicate or stale frames
cannot conceal a timeout. The additive `0008_market_index_monitor_event` migration only permits the
already approved `market.index.updated` event in the existing ledger CHECK constraint; it preserves
all existing rows, sequences, and identities and never rewrites frozen `0006_monitor_event`.
The default production composition still returns `SERVICE_UNAVAILABLE` when no authoritative
dashboard projection exists; WEBF11 never fabricates recovery data. This does not add an OpenAPI
path or generated TypeScript field, change Schema v1 data, historical backtest results, established
hashes, or claim strategy-event-cursor resume for backtesting.

The deterministic test suite does not use live Tushare, AI, Webhook, or other external services.
Live provider checks remain separately authorized operations.

The local backtest implementation provides isolated `sync`, `verify`, `run`, `list`, and `prune`
commands, and its BT050 production-fake acceptance is complete. The separately authorized T059
performance remediation now passes the unchanged 100k-export, ten-symbol/252-day, memory, storage,
and complete offline gates. T059 completed final user acceptance on 2026-09-01, and C24 is complete
at 4 of 4. The optional AI live probe remains `NOT_RUN_UNAUTHORIZED`. See
[the bilingual T059 evidence](docs/verification/release-acceptance.md). Historical sync
availability and the accepted visible-block T058 result do not imply current live Tushare
readiness.

The approved board-index extension is implemented for monitoring and backtesting. Version
`board-index-map-v1` derives one fixed board reference from each validated A-share symbol;
immutable data snapshots are shared by index and cutoff, while each Schema v2 plan independently
evaluates only its own index conditions. The UI separates shared index facts from plan-specific
condition outcomes, and historical Schema v1 plans/results remain unchanged.

## Safety Boundaries

- The live system is monitoring and reminder software, not a broker, order router, or investment
  adviser. Every actionable reminder carries the literal `仅提醒，不会自动下单。`; only the isolated offline `BACKTEST` mode may create clearly labeled simulated research fills.
- Plans are typed, reviewed, versioned, and immutable after activation. AI output remains an
  untrusted draft until deterministic validation and user review succeed; extraction and draft
  save never activate it automatically.
- Prices are stored as integer fen, quantities as integer shares, and A-share timestamps as
  timezone-aware `Asia/Shanghai` values.
- Missing, stale, unauthorized, or semantically unverified market data fails closed.
- Board-index data never creates a global market-strength opinion or hidden trading rule. A plan
  with no index condition keeps its original decision when reference-index data is absent.
- AI secrets stay in ignored project secret files selected by a non-secret YAML file/key
  reference; secrets never enter tracked YAML, database columns, API responses, logs, or exports.
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

### 3. Configure local references

```powershell
Copy-Item config\app.example.yaml config\app.yaml
```

The YAML file contains non-secret provider settings, the Tushare environment-variable name, and an
AI project-secret file/key reference. The versioned example selects the verified
`https://api.quicksync.cn` Tushare-compatible endpoint and the DeepSeek OpenAI-format endpoint
`https://api.deepseek.com` with model `deepseek-v4-flash`. The AI profile, display name, base URL,
model, timeout, retry budget, input limit, output limit, temperature, secret-file path, and key name
are configurable. The local `config/app.yaml` copy is ignored by Git. For Tushare, set its process
variable only when that service is used:

```powershell
$env:TUSHARE_TOKEN = "replace-with-your-tushare-token"
```

[.env.example](.env.example) is the versioned project-secret template. Copy it to the ignored
project-root `.env` when using the example `api_key_ref`, then replace only the selected key's
placeholder. This workspace's local configuration uses its own ignored project-root `.env`; its
`DEEPSEEK_API_KEY` was copied from `TradingAgents/.env` without printing the value. Never put a
token or API key directly in `config/app.yaml`, and never commit `config/app.yaml`, `.env`,
databases, backups, keys, or build output.

Web startup validates the strict YAML, resolves the AI project-secret file relative to that YAML,
and creates one immutable AI client binding for the server lifetime. It never reads the AI key from
the process environment. The general monitoring `DEGRADED` state remains independent and does not
prove Tushare readiness.

### 4. Start the packaged local Web UI

```powershell
trade-plan-monitor web --config config/app.yaml --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` on the same computer. Stop the foreground process with `Ctrl+C`.
The monitoring header honestly reports `DEGRADED` while live minute `SourceTimeLabel` semantics or
the live board-index provider remain unverified; it also shows read-only state and no next poll.
Open `/plans` to use AI drafting and persistent plan management. The first lifespan startup creates
or upgrades `data/monitor.sqlite3`; saving, querying, importing, activating, and deactivating plans
uses that same SQLite file on later starts. Keep the database and its WAL/SHM companions private
and do not copy an in-use WAL database as a backup.
Edit `config/app.yaml` or the selected project `.env` and restart Web to change AI settings.

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
hidden/unmounted, at most 100 rows per result table page and 2,000 equity points, and zero ECharts
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

The production backtest workflow remains `sync` → `verify` → offline `run`. `sync` is the only
network-capable backtest command and still requires both separate human authorization and the
literal `--allow-network` flag. Passing the fake browser gate never authorizes live synchronization
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

The non-secret example configuration selects `https://api.quicksync.cn`. The
`create_tushare_client` factory resolves `TUSHARE_TOKEN` only at runtime and sets the endpoint on
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

Set `TUSHARE_TOKEN` only for a separately authorized live capability probe. Capability, account
permission, rate limit, and minute-label semantics are discovered independently; configuration
never implies availability. A denied or unverified required capability blocks actionable output.
The default contract suite uses deterministic fake DataFrames:

```powershell
python -m pytest tests/integration/test_tushare_contract.py -q -m "not live"
```

## Historical Backtesting

The approved backtest design uses a hybrid workflow: an explicitly authorized `backtest sync` incrementally downloads `stk_mins`, `trade_cal`, `stk_limit`, and unadjusted `daily` facts into `backtest-market.sqlite3`; local verification freezes an exact `dataset_hash`; every formal run then reads that frozen dataset fully offline and writes only result artifacts to `backtest-results.sqlite3`.

The `/backtests/new` page lists real immutable plan versions that the backend currently marks `canActivate=true`, including eligible inactive drafts. The user selects one exact version; submission revalidates it and persists its canonical plan snapshot before the accepted receipt is returned. Saving a newer version later cannot change the queued job, an older result, or its established hashes.

Market and result paths must resolve to different files. Before creating tables, each store rejects an existing live-monitor database or the other backtest storage domain, preventing a misconfigured path from mutating unrelated state.

Historical rows are content-deduplicated and reused across runs. Provider corrections create immutable revisions and a new dataset hash instead of changing an old result. The historical adapter defaults to `UNVERIFIED`; the CLI composition explicitly selects versioned profile `TUSHARE_STK_MINS_241_END_V1`, preserves the 09:30 source row as non-strategy `opening_special`, and maps the remaining end-labeled rows to exactly 240 canonical trading minutes. This evidence never completes live task `T058`.

One dataset accepts 1–10 unique symbols, at most 5 calendar years of backtest dates, and at most 2 calendar years of warm-up. Historical calendar sync explicitly calls `trade_cal` once per needed `SSE`/`SZSE` exchange. Tushare's official calendar contract does not list BSE, so `.BJ` historical scopes are currently rejected before network access with `UNSUPPORTED_HISTORICAL_CALENDAR:BSE`; live `.BJ` plan support is unaffected. The real historical adapter rejects unparsable/duplicate raw rows plus wrong calendar exchange/range, daily symbol/range, or limit date. Because `stk_limit(trade_date)` is market-wide, other valid symbols on that date remain legal; sync selects the requested symbols and then requires every normalized reference set—even during `--refresh`—to match exactly or fail before persistence as `INVALID_RESPONSE:<surface>`. Every frozen artifact is content-hashed again when read, so a modified local payload cannot be replayed under an old `artifact_hash`.

Frozen verification also reports stable `INVALID_<KIND>:<identity>:<date>`, `INVALID_CALENDAR_CHAIN:<exchange>:<date>`, and `PRICE_OUTSIDE_DAILY_LIMIT:<symbol>:<date>` blockers instead of guessing or repairing corrupt facts. It validates daily minute batches under one WAL read snapshot, then holds a short `BEGIN IMMEDIATE` only to recheck every selected head and publish; a concurrent correction aborts the freeze. Validated manifests use an O(1) cached `natural_key` index for later membership lookup, followed by the normal artifact re-hash.

All backtest hashes share exact Decimal canonicalization: numerically equal scale variants such as `0.0003` and `0.00030` have the same canonical text and identity, while binary floats and fixed-point expansions over 10,000 characters fail closed. CLI yuan-to-fen parsing is also context-independent: at most two fractional digits plus trailing zeroes are accepted, oversized exponents fail before expansion, and the result cannot exceed signed 64-bit `9,223,372,036,854,775,807` fen. The backtest reuses reviewed plan hashes, normalized bars, indicators, close reconciliation, and the pure decision engine. `execution-model-v1` is backtest-only: `signalAt` equals the producing decision's `snapshot.evaluatedAt` and the source fact's `receivedAt`; only a subsequent candidate bar with `openAt >= signalAt` may fill. Discrete replay may complete the producing event before processing a next-minute bar at the same boundary, so equality is valid without filling the producing bar/bucket; production historical minute facts normally use `receivedAt == barEnd + 12s`, which keeps the ordinary path in a later minute without lookahead. A fill records `filledAt` as that execution minute's `openAt`. A zero-volume minute leaves the order pending through contiguous canonical candidates until the first later positive-volume minute; it becomes `SUSPENDED` only if replay ends without one. A missing required session minute fails as `MISSING_NEXT_MINUTE` when a later bar exposes the gap. Every `ExecutionOutcome` includes immutable `resolvedAt` plus the resolving `sourceBarId` when a bar exists; `NO_NEXT_MINUTE` alone resolves at finalization without a source bar. Fees, slippage, and partial-lot cost allocation use exact integer-rational arithmetic with explicit fen rounding, independent of the process-global Decimal context. Actual daily limits, T+1, 100-share lots, cash/position bounds, fees, and slippage are applied deterministically. It never invokes the live scheduler, notification outbox, Webhook, WebSocket, or a broker.

Each evaluation uses at most 512 complete five-minute bars, 499 official daily bars before the current day, and 512 calendar-day facts. These bounds enter `run_id` and appear as `BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR`; they are a disclosed research limitation and do not themselves prove multi-year resource acceptance. That independent gate is complete through the BT050/BT008 evidence.

Reports also disclose that zero-volume minutes are treated as a non-tradable proxy (`ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY`), fill quantity is not capped by minute volume (`FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME`), limit locks conservatively use the open or slipped price (`CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE`), drawdown samples daily equity (`DAILY_EQUITY_DRAWDOWN_SAMPLING`), win rate is per sell fill rather than round trip (`WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP`), and metric division is fixed to Decimal precision 28 with `ROUND_HALF_EVEN` (`METRIC_DECIMAL_PRECISION_28_HALF_EVEN`).

The following complete example uses the default isolated paths `data/backtest-market.sqlite3`, `data/backtest-results.sqlite3`, and `backtest-reports/`. `sync` is the only network-capable command and refuses to run without `--allow-network`. Its default warm-up boundary is 400 calendar days before `--start`; when overriding it, pass the same `--warmup-start` to both `sync` and `verify`.

The fee/slippage numbers below are explicit illustrative assumptions, not product defaults. Choose values appropriate to the intended research. `--no-event-risk` records an explicit assumption; use the mutually exclusive `--manual-event-risk` when a material event-risk blocker applies.

```powershell
# 1. Incrementally synchronize missing historical facts with explicit authorization.
$env:TUSHARE_TOKEN = "<set-in-this-shell-only>"
python -m trade_plan_monitor backtest sync `
  --symbols 003043.SZ `
  --start 2025-01-02 `
  --end 2025-12-31 `
  --allow-network
Remove-Item Env:TUSHARE_TOKEN

# 2. Freeze the same scope locally and copy dataset_hash from the JSON result.
python -m trade_plan_monitor backtest verify `
  --symbols 003043.SZ `
  --start 2025-01-02 `
  --end 2025-12-31

# 3. Run fully offline with every execution and event-risk assumption explicit.
python -m trade_plan_monitor backtest run `
  --dataset <dataset_hash_from_verify> `
  --plan config/plans/003043.SZ.sample.yaml `
  --initial-cash-yuan 100000 `
  --commission-rate 0.0003 `
  --minimum-commission-yuan 5 `
  --stamp-duty-rate 0.0005 `
  --transfer-fee-rate 0.00001 `
  --buy-slippage-bps 2 `
  --sell-slippage-bps 2 `
  --no-event-risk

# 4. Inspect summaries and delete at most one bounded batch of expired detail.
python -m trade_plan_monitor backtest list --limit 20 --offset 0
python -m trade_plan_monitor backtest prune --batch-size 1000
```

Run summaries, assumptions, final metrics, and fill ledgers are retained long-term. Successful decision/signal/daily-equity detail is limited to the newest 100 runs and at most 90 days; failed, cancelled, and opt-in debug detail is retained for 14 days; pinned runs are exempt. Result publication first stages canonical rows in `backtest-results.sqlite3`; ordinary reads and statistics hide all staged rows. One transaction sets the internal `materialized` visibility flag only after the complete `reportHash`, expected fill/detail counts, and canonical identity/content set hashes all match. First publication persists those counts and set hashes, and every published retry must match them exactly; ordinary summary/fill/detail reads also validate each SQL identity against its hashed payload before applying any detail-kind filter. The CLI then atomically writes `backtest-report-summary-v1` JSON plus fill CSV. `materialized` is the only publication gate, not a public run status; public statuses remain `COMPLETED`, `FAILED`, or `CANCELLED`. Bounded `prune` maintenance removes unpinned abandoned staged summary/fill/detail after 14 days, while recent stages remain recoverable. Missing or corrupt files can be rebuilt from the long-lived summary/fill rows without network access, replay, or duplicate fills; pruned decision/signal/outcome/equity detail is intentionally not reconstructable. `reportHash` remains the audit identity of the original complete run and is not a file-byte hash. Pin metadata and initial lots are supported by lower-level backtest contracts, but the current CLI exposes neither pin/unpin nor initial-lot input and therefore starts each CLI run with cash only. Full minute-by-minute account snapshots and duplicate market rows are not stored. See [SPEC-backtest.md](docs/specifications/backtesting/SPEC-backtest.md) for the isolation, no-lookahead, report, and retention contracts.

## AI Configuration and Secrets

`DEEPSEEK_API_KEY` is optional unless AI-assisted drafting is enabled. YAML stores only
`api_key_ref.file` and `api_key_ref.key`; the real value remains in the ignored project secret file.
Relative file paths are resolved from the directory containing `app.yaml`. The default `DEEPSEEK`
profile sends DeepSeek's current `max_tokens`, `thinking={"type":"disabled"}`, and JSON-output
request fields. Change `profile` to `OPENAI_COMPATIBLE` and configure another reviewed base URL,
model, file, and key to use a different compatible service. Runtime provider configuration stores
a non-secret reference, model, bounded timeout/retry/token limits, and an HTTPS base URL (plain HTTP
is accepted only for an explicit loopback host).

API-key material is loaded only by the backend and cannot be returned through the public contract.
The Web page displays only the provider name, model, safe base URL, limits, enabled state, and
whether a key was loaded. It has no provider edit, Token input, secret replacement, or connection
test control. Redirects, embedded URL credentials, query-bearing base URLs, raw model execution,
and secret-bearing validation errors are rejected. AI output is never activated directly.

Web is the primary AI workflow: open `/plans`, paste the source text, submit it, and review the
validated result. The backend holds at most one concurrent extraction and the page polls its exact
operation ID. Changing `config/app.yaml` or `.env` requires a Web restart. The CLI remains as a
maintenance tool; both commands below make a real provider request and can consume paid tokens:

```powershell
# Send one minimal connectivity request using config/app.yaml.
python -m trade_plan_monitor ai test

# Read one UTF-8 text file and return a review-only structured draft.
python -m trade_plan_monitor ai extract --source .\plan-source.txt
```

Pass `--config <path>` after `test` or `extract` to select another configuration file. The command
rejects a missing/non-file source, invalid UTF-8, source text above the configured character limit,
and a missing, oversized, invalid, duplicate-key, or empty project secret file before accepting a
result. The secret file is capped at 65,536 bytes, decoded as strict UTF-8, and never consulted
through the process environment. Web and CLI use the same file-based configuration and secret
loader; neither offers a Web settings editor and neither uses an AI environment-variable fallback.

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
| UI shows `DEGRADED` or a general monitoring API returns `SERVICE_UNAVAILABLE` | Expected while live minute `SourceTimeLabel` semantics or the live board-index provider is unverified, or when an authoritative projection is unavailable. The backend keeps health read-only and does not schedule actionable monitoring; the separately composed plan and persistent position workflows remain available when their stored plan/calendar prerequisites exist. |
| `runtime service factory is not configured` | `validate`, `monitor`, `replay`, or `backup` was invoked before application service composition is wired. |
| Host validation rejects the listener | Use the exact literal `127.0.0.1`; `localhost`, `::1`, `0.0.0.0`, hostnames, and LAN addresses are intentionally rejected. |
| Port 8765 is busy | Stop the other local process or choose another unused port from 1–65535, keeping host `127.0.0.1`. |
| YAML reports an unknown field | Start again from `config/app.example.yaml`; the schema deliberately rejects unsupported sections and literal secrets. |
| Tushare capability is `DENIED`/`UNVERIFIED` | Check the process environment and account permission, then run only an authorized live probe. Never bypass the blocker. |
| AI returns configuration/authentication errors | Verify `api_key_ref.file`, `api_key_ref.key`, profile, base URL, and model; keep the real key only in the ignored project secret file, not in a URL or YAML. |
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

Unsuffixed documents are canonical English inputs for agents and implementation workflows. The
matching `.zh-CN.md` files are Chinese review copies and must remain semantically equivalent in
the same change. The complete categorized inventory is in [docs/README.md](docs/README.md), with
the [Chinese index](docs/README.zh-CN.md) alongside it.

| Contract | English | Chinese |
|---|---|---|
| Capability map | [CAPABILITY-MAP.md](docs/architecture/CAPABILITY-MAP.md) | [CAPABILITY-MAP.zh-CN.md](docs/architecture/CAPABILITY-MAP.zh-CN.md) |
| Plan domain | [SPEC-plan-domain.md](docs/specifications/monitoring/SPEC-plan-domain.md) | [SPEC-plan-domain.zh-CN.md](docs/specifications/monitoring/SPEC-plan-domain.zh-CN.md) |
| AI drafting | [SPEC-ai-plan-drafting.md](docs/specifications/monitoring/SPEC-ai-plan-drafting.md) | [SPEC-ai-plan-drafting.zh-CN.md](docs/specifications/monitoring/SPEC-ai-plan-drafting.zh-CN.md) |
| Market data | [SPEC-market-data.md](docs/specifications/monitoring/SPEC-market-data.md) | [SPEC-market-data.zh-CN.md](docs/specifications/monitoring/SPEC-market-data.zh-CN.md) |
| Historical backtest | [SPEC-backtest.md](docs/specifications/backtesting/SPEC-backtest.md) | [SPEC-backtest.zh-CN.md](docs/specifications/backtesting/SPEC-backtest.zh-CN.md) |
| Strategy state | [SPEC-strategy-state.md](docs/specifications/monitoring/SPEC-strategy-state.md) | [SPEC-strategy-state.zh-CN.md](docs/specifications/monitoring/SPEC-strategy-state.zh-CN.md) |
| Decision engine | [SPEC-decision-engine.md](docs/specifications/monitoring/SPEC-decision-engine.md) | [SPEC-decision-engine.zh-CN.md](docs/specifications/monitoring/SPEC-decision-engine.zh-CN.md) |
| Notification outbox | [SPEC-notification-outbox.md](docs/specifications/monitoring/SPEC-notification-outbox.md) | [SPEC-notification-outbox.zh-CN.md](docs/specifications/monitoring/SPEC-notification-outbox.zh-CN.md) |
| Monitor runtime | [SPEC-monitor-runtime.md](docs/specifications/monitoring/SPEC-monitor-runtime.md) | [SPEC-monitor-runtime.zh-CN.md](docs/specifications/monitoring/SPEC-monitor-runtime.zh-CN.md) |
| Local Web | [SPEC-local-web.md](docs/specifications/monitoring/SPEC-local-web.md) | [SPEC-local-web.zh-CN.md](docs/specifications/monitoring/SPEC-local-web.zh-CN.md) |

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
