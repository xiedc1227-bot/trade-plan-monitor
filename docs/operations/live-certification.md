# Tushare Live Certification

## Purpose

`LPC005` and `LPC007` are separately selected one-shot checks. They run directly in the current
process and read the Tushare token from the local application YAML. Stock and board-index runs
retain separate authorization phrases, capability sets, timestamp labels, and evidence profiles;
they do not require Windows Credential Manager or a child process.

Stock certification covers `trade_cal`, `stk_limit`, `daily`, one ten-symbol `rt_min` batch, and
two `rt_min_daily` observations. Board-index certification checks historical
`idx_mins(freq="5min")`, current-day `rt_idx_min_daily(freq="5MIN")`, and `index_daily`
separately for the four visible indexes `000001.SH`, `399001.SZ`, `399006.SZ`, and `000688.SH`,
plus the hidden whole-Shenzhen turnover benchmark `399107.SZ`. The known BSE 50 identity `899050.BJ` is `DEFERRED` and receives
no certification request until BSE stocks enter scope. The stock “A-share realtime minutes”
permission does not replace the separately named “Index realtime minutes” permission.

## Required Data Permissions

The implementation calls exactly the following nine Tushare endpoints. The account audit on
2026-09-08 used the configured token and the configured `https://api.quicksync.cn` endpoint; no
credential value was printed or recorded.

| Official data/permission name | Endpoints used | Function dependency | Account status |
|---|---|---|---|
| Trading calendar | `trade_cal` | Open-day validation for live monitoring and backtest synchronization | `READY` |
| Daily price limits | `stk_limit` | Stock limit-up/limit-down state and backtest synchronization | `READY` |
| A-share daily bars | `daily` | Official stock daily reference and backtest synchronization | `READY` |
| Historical stock minutes | `stk_mins` | Historical stock-minute synchronization for backtests | `READY` (241 rows observed) |
| A-share realtime minutes | `rt_min`, `rt_min_daily` | Live stock monitoring and current-day cumulative recovery | `READY` |
| Index daily bars | `index_daily` | Official board-index daily reference | `READY` |
| Historical index minutes | `idx_mins` | Historical warm-up for board-index monitoring | `READY` (49 five-minute rows observed) |
| Index realtime minutes | `rt_idx_min_daily` | Current-day board-index monitoring and turnover | `READY` for SSE Composite, Shenzhen Component, Shenzhen A-share, ChiNext, and STAR 50; BSE 50 is `DEFERRED` |

No previously certified permission remains blocked after Index realtime minutes was activated and probed on
2026-09-08. The separately authorized 2026-09-11 renewal also certified the `399107.SZ`
turnover benchmark. Enabling A-share realtime minutes alone would not have granted it. `rt_min_daily` is
included with A-share realtime-minute access; the implementation does not need a separate
permission for that endpoint. The 2026-09-08 probe historically observed no BSE 50 realtime rows;
the current product scope now defers BSE 50 entirely. Future certification profiles retain its
known identity as `DEFERRED` and call none of `idx_mins`, `rt_idx_min_daily`, or `index_daily` for
`899050.BJ`.

The current code does not call auction, realtime daily-bar, ETF, industry-classification realtime,
Level-2, or tick-by-tick endpoints. Those permissions are not required for the current feature set.

### Test and runtime boundary

- The default automated suite uses deterministic fakes; explicitly authorized live contract cases
  are skipped. Normal test runs therefore do not depend on provider permissions or network access.
- A completed live probe with unavailable permission writes the capability as
  `BLOCKED_PERMISSION`, prints `CERTIFIED_VISIBLE_BLOCK`, and exits with code `0`.
- Only the production function that consumes the unavailable data remains non-actionable. Missing
  Index realtime minutes therefore blocks live board-index conditions, not the test suite and not
  unrelated stock or backtest behavior.

## Configuration

Copy the versioned template once and place credentials directly in the ignored local file:

```powershell
Copy-Item config\app.example.yaml config\app.yaml
```

```yaml
tushare:
  api_url: https://api.quicksync.cn
  timeout_seconds: 30
  token: replace-with-your-tushare-token

ai:
  api_key: replace-with-your-deepseek-api-key
```

`tushare.token` and `ai.api_key` in `config/app.yaml` are the only credential source. That file is
excluded by the repository `.gitignore`; environment variables and separate credential files are
not read.

## Authorized Runs

Run stock and index certification independently:

```powershell
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py stock --authorize LPC005_STOCK_LIVE_CERTIFICATION --config config/app.yaml
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py index --authorize LPC007_BOARD_INDEX_LIVE_CERTIFICATION --config config/app.yaml
```

Eligible `Asia/Shanghai` windows on a weekday are:

| Surface | Morning | Afternoon | Official-close follow-up |
|---|---:|---:|---:|
| Stock | not eligible | `13:02`–`14:55` | `15:20`–`16:30` |
| Board index | `09:40`–`11:25` | `13:10`–`14:55` | `15:20`–`16:30` |

The runner additionally requires `trade_cal` to prove the observation date is open. An
ineligible local window returns `NOT_RUN_MARKET_WINDOW` before loading configuration or calling
the provider.

Stock certification is intentionally unavailable in the morning. A continuous early-session
sequence beginning at `09:30` cannot distinguish start-labelled minutes from an independent
`09:30` opening snapshot followed by end-labelled minutes. The afternoon window can prove the
`11:30` and `13:01` boundaries; without both boundaries the stock label remains `UNVERIFIED`.

## Current Renewal Evidence

The 2026-09-11 board-index renewal observed at `10:20:44.522358+08` certified
`000001.SH`, `399001.SZ`, `399107.SZ`, `399006.SZ`, and `000688.SH` as `READY` with
`SourceTimeLabel=END`, valid through `2026-09-18 10:20:44.522358+08`. `899050.BJ` remains
`DEFERRED` and made no provider request.

The earlier 2026-09-08 stock `START` conclusion was an insufficient early-market inference. On
2026-09-09, two 13:10 attempts and bounded retries correctly reported
`current_day_minutes=ERROR/UNVERIFIED` under the old label logic. Each redacted diagnostic had
139 rows from `09:30` through `13:18`, included `11:30`, and excluded `13:00`. The strict corrected
stock run observed at `14:48:40.405317+08` certified all five capabilities `READY` with
`SourceTimeLabel=END`, valid through `2026-09-16 14:48:40.405317+08`; it proves a standalone
`09:30` snapshot followed by end-labeled minutes.

Both renewals used `config/app.yaml`. The configured `connect_ip` continued to work without a
temporary per-run proxy change. A 2026-09-09 13:27 installed-production attempt was rejected
before network because its scheduled-close window was ineligible; it is not production-chain
acceptance evidence.

## Evidence and Failure Semantics

Certification profiles are written under the ignored directory `data/live-certification/`:

- `tushare-stock-live.json`
- `tushare-board-index-live.json`

Profiles contain endpoint identity, SDK version, timestamps, capability status, timestamp-label
semantics, and a SHA-256 integrity value. A profile is accepted only for its exact HTTPS endpoint,
within seven days, with an intact hash and the correct surface schema.

Calls are serial with one worker, start at least `1.25` seconds apart, time out after `15`
seconds, and are never retried during certification. The first `RATE_LIMITED` result stops every
later provider call. A stock profile is actionable only when all five capabilities are `READY`
and its `SourceTimeLabel` is verified. Index readiness is kept per index, and one blocked index
does not authorize or disable its peers. The `DEFERRED` BSE 50 identity is non-actionable and
fails before request control if selected.

The observed `rt_idx_min_daily(freq="5MIN")` shape contains a standalone `09:30` opening snapshot
followed by end-labeled five-minute bars. Certification excludes that opening snapshot only while
determining timestamp-label semantics; runtime normalization already drops it because it is not a
completed five-minute interval.

## Runtime recovery and normal restart

The installed `trade-plan-monitor web` entry uses monitor contract `2` and the matching packaged frontend. `npm --prefix web run build` builds that frontend and copies its manifest and assets into the Python package; `npm --prefix web run build:runtime-status-preview` remains an isolated preview. `python scripts/generate_frontend_types.py --check` checks both the installed v2 artifacts (`openapi.runtime-status.json`, `web/src/api/generated-runtime-status.ts`) and explicit v1 compatibility fixtures (`openapi.json`, `web/src/api/generated.ts`). Compatibility fixtures are not a selectable CLI protocol.

Compatible validated provider semantics do not expire merely because seven days pass. The original evidence timestamp is retained; old `READY` evidence does not prove current permission or fresh data. First-time or incompatible provider semantics still need explicit verification. A missing credential, rejected permission or incomplete input remains visible and prevents the affected work; recovery retries use the existing bounded scheduler and shared request controller.

To change configuration, safely stop the program, edit the configuration, then start a new process with `trade-plan-monitor web --config config/app.yaml`. Do not change provider configuration while monitoring is running. On restart, the owned runtime reads durable state and resumes missing work; it does not recompute completed decisions or assume a reminder was executed. The dashboard distinguishes transport, runtime progress and data eligibility. An old cached page must reload; version mismatch rejects protected commands before execution.

The five-day rule measures software downtime from the last persisted owner liveness observation. Exactly `120` hours may resume; more than `120` hours invalidates active plans before provider or notification work while preserving inventory and audit. Missing old liveness uses the existing system-page preview and explicit invalidation, then a fresh plan. Corrupt or future liveness remains blocked for investigation; never enter a fabricated last-run time. A running but degraded provider is not software downtime.

Before changing an actual installation, preserve an approved database backup and deploy matching backend/frontend versions together. A rollback must stop the runtime, restore a compatible package and its matching assets, and verify database-schema compatibility; use the verified backup when compatibility cannot be proved. Never overwrite a live database or infer that every schema downgrade is lossless. This refactor's acceptance uses temporary SQLite, fake provider/channel boundaries and controlled clocks; actual provider acceptance, user-database migration and deployment are separate.

The historical bounded R14 diagnostic retains its approved v1 test path and requires `npm --prefix web run build:legacy-test` before execution. These isolated assets do not affect the normal CLI build. This prerequisite does not authorize a paid diagnostic or extend its existing time/budget limits.

## Authoritative References

- [Tushare `trade_cal`](https://tushare.pro/document/2?doc_id=26)
- [Tushare `stk_limit`](https://tushare.pro/document/2?doc_id=183)
- [Tushare `daily`](https://tushare.pro/document/1?doc_id=27)
- [Tushare `stk_mins`](https://tushare.pro/document/2?doc_id=370)
- [Tushare `rt_min`](https://tushare.pro/document/2?doc_id=374)
- [Tushare `rt_min_daily`](https://tushare.pro/document/2?doc_id=457)
- [Tushare `idx_mins`](https://tushare.pro/document/2?doc_id=419)
- [Tushare `rt_idx_min_daily`](https://tushare.pro/document/2?doc_id=420)
- [Tushare `index_daily`](https://tushare.pro/document/1?doc_id=95)
