# Live Production Chain Acceptance

> Canonical English evidence record. The Chinese review copy is
> `live-production-chain-acceptance.zh-CN.md`; task IDs, commands, counts, paths, enums,
> and outcomes must remain aligned.

## Scope and Evidence Boundary

This report covers `LPC001` through `LPC012` from `tasks/live-production-todo.md`. It
supersedes only the temporary WEBF13 Health-fallback approach; it does not rewrite the
historical WEBF13 result, reuse T058 stock evidence for board-index certification, or reuse
T059 release acceptance. The implementation preserves Schema v1 data, established hashes,
backtest stores, DeepSeek behavior, and all existing local Web routes.

## Environment

- Date/time zone: 2026-09-08, Asia/Shanghai.
- Market-window fact: an authorized Tuesday open-market run at `09:52` certified the stock
  surface; a corrected index run at `10:04` recorded the realtime-index permission block.
- Network boundary: the two explicitly authorized certification runs called Tushare. Offline
  tests and deterministic loopback browser fixtures still make no Tushare, DeepSeek, broker,
  webhook, or other supplier request.
- Credential boundary: the selected certification and application paths read credentials only
  from ignored local `config/app.yaml`; no secret value is written to a command line, report,
  log, database, profile, or candidate source file.

## Contract and Migration Evidence

- Migration 0009 is additive. Its focused suite passes `21 tests`; the combined migration
  and projection repository suite passes `29 tests`, persistent reads pass `18 tests`, and
  the existing SQLite repository suite passes `103 tests`.
- The consolidated current-code live-chain backend command passes `558 tests`, covering
  migration preservation, atomic projection writes/rollback, durable reconstruction,
  provider control, immutable deadline snapshots, pending-close ownership, supervisor
  recovery, production composition, typed Web APIs, and WebSocket generation fences.
- OpenAPI SHA-256 is
  `2b232e1a9237aa88a2de7c3d1ec3fcc692b198cfddeabc41fa88b7d67cdb3a53` and generated
  TypeScript is byte-current.
- English/Chinese structure and stable literal sets match for the specification, plan,
  task list, and this report; the only expected literal-set differences are the counterpart
  filenames.
- Independent review used the requested model matrix. P2-A (`gpt-5.6-sol/ultra`) passed
  migration/persistence without findings. P2-B (`gpt-5.6-sol/max`) found four P1 and one P2
  runtime issues; all were fixed and regression-tested. P2-C (`gpt-5.6-terra/high`) found one
  P1 and two P2 Web/evidence gaps; all were fixed. Final P3 (`gpt-5.6-sol/ultra`) found one P1
  and five P2 boundary/test-harness issues; the same reviewer rechecked every fix and returned
  `PASS` with no remaining P0/P1/P2.

## Runtime and Provider Evidence

- The corrected provider/certification focus passes `228 tests`. It accepts a missing
  `rt_min_daily.freq` echo only for the fixed `1MIN` request and continues to reject an explicitly
  wrong returned frequency.
- The 2026-09-08 `09:52` stock profile records `realtime_minutes`, `current_day_minutes`,
  `trading_calendar`, `daily_limits`, and `daily_bars` as `READY`, with
  `SourceTimeLabel=START`. This closes LPC005.
- Tushare documents and live observations show that `idx_mins` is historical and updates after
  the session; it returned `49` prior-day five-minute rows and `0` current-day rows. The corrected
  index contract therefore combines `idx_mins`, `rt_idx_min_daily`, and `index_daily` rather than
  reusing the stock `rt_min` endpoint.
- The 2026-09-08 `10:04` index profile records all five approved indexes as
  `BLOCKED_PERMISSION` on `rt_idx_min_daily`, with `SourceTimeLabel=UNVERIFIED`. The separate
  Tushare permission named “Index realtime minutes” remains required for LPC007.
- Runtime tests cover one immutable at-most-ten-symbol batch per deadline, no evaluation
  refetch, separate complete admission/provider timeouts, queued `CLOSED` wake-up, immediate
  stop admission, final activation-revision fencing, durable official-close ownership, and
  bounded fresh-runtime supervision.
- Production remains `DEGRADED` and non-actionable because the installed composition still uses
  its hard-coded `UNVERIFIED` provider state and has not yet consumed the now-ready stock profile.
  Board-index capability remains a separate unmet gate.

## Web and Browser Evidence

- `scripts/generate_frontend_types.py --check` reports that the OpenAPI snapshot and
  generated frontend types are current.
- `vue-tsc --noEmit -p tsconfig.json` passes.
- Vitest passes `40 files / 592 tests`.
- The Vite production build passes. `PriceChart` is a separate `95.39 kB` JavaScript
  chunk and the registered Canvas renderer is a separate `475.20 kB` asynchronous chunk;
  the Dashboard chunk contains neither resource and the non-chart browser case requests
  neither resource.
- Playwright passes `22 tests` with one worker on project `chrome` using
  `channel: "chrome"`. The relevant fixtures assert zero browser console errors, zero
  browser console warnings, and zero `requestfailed`; typed `UNAVAILABLE` opens no
  WebSocket. The installed-production case starts the exact `.venv` console executable,
  validates the packaged SPA and typed empty-database response, stops it, restarts it over
  the same temporary database, and validates the same honest state again. A Node runner
  warning about `NO_COLOR`/`FORCE_COLOR` is not browser-console output.
- The installed journey uses a dynamically reserved loopback port, ties readiness to the
  child launcher and parsed Uvicorn PID, retains its handle until both identities have exited,
  and bounds `taskkill.exe`/`icacls.exe` calls to three seconds. Contract-error browser fakes
  deliver application-visible HTTP `503`/`409` responses without masking them as
  `INVALID_RESPONSE`.

## Verification Commands and Results

Completed live-chain and Web commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/contract/test_tushare_live.py -q -m "not live"
.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_tushare_market_index.py tests/integration/test_runtime_lifecycle.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_monitor_production_composition.py tests/integration/test_plan_production_composition.py tests/integration/test_live_monitor_projection_migration.py tests/integration/test_live_projection_repository.py tests/integration/test_persistent_monitor_read_service.py tests/integration/test_sqlite_repositories.py tests/integration/test_web_api.py tests/integration/test_websocket.py -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe scripts\generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

The repository-wide command below is not green:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q -m "not live" -x
```

It passed `1213 tests` before the existing
`test_ten_symbol_252_day_replays_meet_capacity_budgets` watchdog cancelled
`688981.SH` at `120.076626s`. A resource-isolated rerun, without any concurrent checks,
again failed the same unchanged backtest performance gate when `003043.SZ` reached
`120.074936s`. No backtest source or threshold was changed by this work, so the failure is
reported rather than hidden, skipped, or relaxed.

## Residual Risks and Deferred Live Evidence

- Stock realtime-minute timestamp semantics are certified as `START` until the current profile
  expires at 2026-09-15 09:52 Asia/Shanghai.
- Board-index live capability and timestamp evidence require the separate Tushare “Index realtime
  minutes” permission; A-share realtime minutes and index historical minutes cannot satisfy it.
- Direct `tushare.token` and `ai.api_key` configuration is implemented as the only credential
  source. Windows Credential Manager, environment/file references, and child-only certification
  were removed by the user's explicit personal-tool policy. The configured token was used only by
  the explicitly authorized certification calls.
- Hash-protected stock and board-index profiles expire after seven days and fail
  closed on tampering, endpoint mismatch, schema mismatch, or cross-surface reuse. Real stock and
  per-index probes are implemented, including first-429 global stop behavior. The stock profile is
  ready; the index profile truthfully preserves its permission block.
- CPython cannot forcibly terminate an arbitrary non-cooperative synchronous provider
  callable. The real Tushare transport is configured with its own 15-second timeout and
  shutdown is bounded and visible. The host proxy currently maps `api.quicksync.cn` to an
  interception address, so the authorized evidence run required a process-local direct route; this
  host networking issue must be resolved before unattended production use.
- The repository-wide offline gate remains blocked by the unrelated 252-day backtest
  performance budget described above; the live-chain-focused `558` tests are green.

## Acceptance Status

`LIVE_CHAIN_STOCK_CERTIFIED_INDEX_PERMISSION_BLOCKED` — LPC005 passes with real open-market
evidence. LPC006 remains unbound in production, LPC007 is blocked by the separate realtime-index
permission, and LPC008 remains dependent on LPC007 and production binding. LPC006–LPC008 and
LPC012 remain open; production safely remains non-actionable and `DEGRADED`.
