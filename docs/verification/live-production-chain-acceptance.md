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
- Market-window fact: an authorized Tuesday open-market run at `09:52:53` certified the stock
  surface with `SourceTimeLabel=START`; a separate post-session index run at `15:16:52`
  selected `SourceTimeLabel=END` and certified four indexes while recording `899050.BJ` as
  `ERROR`.
- Network boundary: the two explicitly authorized certification runs and the explicitly authorized
  LPC006/LPC008 installed-production acceptance called Tushare. Offline tests and deterministic
  loopback browser fixtures still make no Tushare, DeepSeek, broker, webhook, or other supplier
  request.
- Credential boundary: the selected certification and application paths read credentials only
  from ignored local `config/app.yaml`; no secret value is written to a command line, report,
  log, database, profile, or candidate source file.
- Installed-production evidence: the ignored report
  `data/live-certification/production-a88bb95d5a054c46aa62847f894c8421.json` and its isolated
  SQLite database contain the 17:00 natural scheduler/restart proof. The final frozen-behavior
  rerun is `data/live-certification/production-e3f317ccb8784753a9914c7cfb08bb8c.json` with its
  isolated SQLite database. None of these artifacts contains a secret.

## Contract and Migration Evidence

- Migration 0009 is additive. Its focused suite passes `21 tests`; the combined migration
  and projection repository suite passes `29 tests`, persistent reads pass `18 tests`, and
  the existing SQLite repository suite passes `103 tests`.
- Final focused backend gates pass: `188 tests` for timing/runtime behavior, while
  `test_live_pipeline_acceptance.py`, `test_certified_production_runtime.py`, and
  `test_production_certification_gate.py` pass `22 tests` together in `38.27s`. They cover
  migration preservation, atomic projection writes/rollback, durable reconstruction,
  provider control, immutable deadline snapshots, pending-close ownership, supervisor
  recovery, production composition, typed Web APIs, and WebSocket generation fences.
- The frozen functional backend run passes `2307 tests` with `1 skipped` and `1 warning` in
  `181.42s`; its exact scope excludes the unchanged `tests/integration/test_backtest_acceptance.py`
  file because that file had already run twice, including the separately retained 120-second
  capacity failure. The log is
  `data/live-certification/frozen-production-functional-pytest.log`. This is a green functional
  scope, not a claim that the full repository gate is green.
- OpenAPI SHA-256 is
  `2b232e1a9237aa88a2de7c3d1ec3fcc692b198cfddeabc41fa88b7d67cdb3a53` and generated
  TypeScript is byte-current.
- English/Chinese structure and stable literal sets match for the specification, plan,
  task list, and this report; the only expected literal-set differences are the counterpart
  filenames.
- Historical independent review used the earlier requested model matrix. P2-A (`gpt-5.6-sol/ultra`) passed
  migration/persistence without findings. P2-B (`gpt-5.6-sol/max`) found four P1 and one P2
  runtime issues; all were fixed and regression-tested. P2-C (`gpt-5.6-terra/high`) found one
  P1 and two P2 Web/evidence gaps; all were fixed. Final P3 (`gpt-5.6-sol/ultra`) found one P1
  and five P2 boundary/test-harness issues; the same reviewer rechecked every fix and returned
  `PASS` with no remaining P0/P1/P2. For this acceptance update, pipeline/timing review used
  `gpt-5.6-sol/high`, documentation review used `gpt-5.6-sol/medium`, and the network review
  agent inherited its assigned model; these current allocations are not the historical matrix.

## Runtime and Provider Evidence

- The previously recorded provider/certification component suite passes `228 tests`. It accepts a missing
  `rt_min_daily.freq` echo only for the fixed `1MIN` request and continues to reject an explicitly
  wrong returned frequency. This is component evidence, separate from live certification and
  installed-production-chain acceptance.
- The 2026-09-08 `09:52:53` stock profile records `realtime_minutes`, `current_day_minutes`,
  `trading_calendar`, `daily_limits`, and `daily_bars` as `READY`, with
  `SourceTimeLabel=START`. It remains valid through 2026-09-15 09:52:53 Asia/Shanghai and
  closes LPC005.
- Tushare documents and live observations show that `idx_mins` is historical and updates after
  the session; it returned `49` prior-day five-minute rows and `0` current-day rows. The corrected
  index contract therefore combines `idx_mins`, `rt_idx_min_daily`, and `index_daily` rather than
  reusing the stock `rt_min` endpoint.
- The separate 2026-09-08 `15:16:52` index profile selects `SourceTimeLabel=END` and remains
  valid through 2026-09-15 15:16:52 Asia/Shanghai. `000001.SH`, `399001.SZ`, `399006.SZ`, and
  `000688.SH` are `READY`; `899050.BJ` is `ERROR`. This supersedes the earlier blanket
  `BLOCKED_PERMISSION` conclusion. It certifies neither `899050.BJ` nor the installed production
  chain, so LPC007 remains open pending complete acceptance evidence.
- Runtime tests cover one immutable at-most-ten-symbol batch per deadline, no evaluation
  refetch, separate complete admission/provider timeouts, queued `CLOSED` wake-up, immediate
  stop admission, final activation-revision fencing, durable official-close ownership, and
  bounded fresh-runtime supervision.
- The installed production acceptance started at `16:54:10.565727` and reported
  `waitingForScheduledClose` before the scheduler naturally started the `17:00:00` deadline at
  `17:00:00.011473`. It consumed the five-capability `READY` stock profile, kept
  `899050.BJ=ERROR`, exposed `LIVE` Shanghai/Shenzhen index snapshots, and committed two
  official-close evaluations. Replaying those committed identities returned zero results and
  made zero provider requests. Dashboard sequence `11` and the committed decisions survived a
  restart into `RUNNING`; the run finished at `17:00:18.114695`.
- Within each due-plan batch, dependent plans shared one revision-aware snapshot per required
  index endpoint. The 15:00 intraday and `OFFICIAL_CLOSE` phases are distinct evaluation kinds,
  so the two-stage acceptance correctly made one index-endpoint call per kind rather than one
  call across both kinds. Startup recovery likewise groups pending closes by pending trade date
  so same-board symbols share the batch snapshot.
- Frozen regressions cover provider revision sequence `r1` → `r2` → `r1`: canonically identical
  content for an existing revision reuses its exact persisted snapshot/hash, each plan result binds
  that persisted identity, and different canonical content for the same revision fails closed.
  The tests do not relax any snapshot field, hash formula, uniqueness constraint, or failed-index
  isolation rule. Index success and error paths also share the post-fetch whole-second boundary and
  future-time rejection.
- The production run recorded a minimum physical request-start interval of
  `1.2524307999992743` seconds and the following pre-restart instrumented call counts:
  `trade_cal=2`, `stk_limit=1`, `daily=4`, `rt_min_daily=2`, `idx_mins=4`,
  `rt_idx_min_daily=4`, `index_daily=4`, and `rt_min=1`. These installed-composition facts,
  together with component and live-certification evidence, close LPC006 and LPC008.
- The final frozen-behavior manual rerun started at `17:37:38.919297`, finished at
  `17:38:16.077702`, started and restarted `RUNNING`, committed both official closes, returned zero
  duplicate results with zero new requests, and preserved Dashboard sequence `11`. Its minimum
  physical request-start interval was `1.2519141000084346` seconds; its endpoint counts and
  Shanghai/Shenzhen `LIVE` snapshots matched the 17:00 run. It remained honestly intraday
  `GAPPED` with `freshIntradayCertifiedByThisRun=false`.
- The same run does not certify fresh intraday completeness: `freshIntradayCertifiedByThisRun=false`.
  The after-session intraday result was empty and `GAPPED`, with a 15:00 target and latest
  returned minute at 14:59. Read-only inspection of the production database found `239` minutes
  for each of the two stocks and the 13:01 minute absent from both. This limitation is recorded
  rather than upgraded to a pass.

## Web and Browser Evidence

- `scripts/generate_frontend_types.py --check` reports that the OpenAPI snapshot and
  generated frontend types are current.
- `vue-tsc --noEmit -p tsconfig.json` passes.
- Vitest passes `40 files / 599 tests` in `6.28s`.
- The Vite production build passes. `PriceChart` is a separate `95.39 kB` JavaScript
  chunk and the registered Canvas renderer is a separate `475.20 kB` asynchronous chunk;
  the Dashboard chunk contains neither resource and the non-chart browser case requests
  neither resource.
- Playwright passes `22 tests` in `34.3s` with one worker on project `chrome` using
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
.\.venv\Scripts\python.exe -m pytest tests/integration/test_live_pipeline_acceptance.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_certification_gate.py -q
.\.venv\Scripts\python.exe scripts\verify_live_production.py --authorize LPC006_LPC008_PRODUCTION_ACCEPTANCE --wait-for-scheduled-close
.\.venv\Scripts\python.exe scripts\verify_live_production.py --authorize LPC006_LPC008_PRODUCTION_ACCEPTANCE --config config/app.yaml
.\.venv\Scripts\python.exe -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_tushare_market_index.py tests/integration/test_runtime_lifecycle.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_monitor_production_composition.py tests/integration/test_plan_production_composition.py tests/integration/test_live_monitor_projection_migration.py tests/integration/test_live_projection_repository.py tests/integration/test_persistent_monitor_read_service.py tests/integration/test_sqlite_repositories.py tests/integration/test_web_api.py tests/integration/test_websocket.py -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe scripts\generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
git diff --check
```

The first repository-wide command below is not green:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q -m "not live"
```

It completed in `1614.22s` with `5 failed, 2286 passed, 1 skipped`. One failure was the existing
`test_ten_symbol_252_day_replays_meet_capacity_budgets` watchdog for `000001.SZ` at `120.066243s`. The other four
were current-change regressions: two legacy Web fixtures missing `runtimeGeneration`, one timing
test referencing an old snapshot name, and one replay assertion missing the new persisted
data-health events. Those four were corrected and focused regressions pass. The unchanged 252-day
capacity failure is retained and its threshold was not relaxed. The intermediate rerun excluded
that one measured case; the final frozen functional rerun excluded the entire unchanged
`test_backtest_acceptance.py` file after it had already run twice. LPC012 therefore remains open.

An intermediate filtered rerun used this explicit filter and completed in `1221.40s` with
`2306 passed, 1 failed, 1 skipped, 1 deselected`. The malicious-decimal helper failed because it
did not raise the expected exception; a subsequent focused run passed, but no cause is claimed
before the frozen-code sequential rerun. This intermediate run is not green and is not the final
frozen-code result:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q -m "not live" -k "not test_ten_symbol_252_day_replays_meet_capacity_budgets"
```

The final frozen functional run used the broader explicit file exclusion below because the whole
unchanged capacity suite had already run twice:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q --tb=short -m 'not live' --ignore=tests/integration/test_backtest_acceptance.py
```

Result: `2307 passed, 1 skipped, 1 warning in 181.42s`. The retained full-scope capacity failure
still keeps LPC012 open.

## Residual Risks and Deferred Live Evidence

- Stock realtime-minute timestamp semantics are certified as `START` until the current profile
  expires at 2026-09-15 09:52:53 Asia/Shanghai.
- Board-index timestamp semantics are certified as `END` until the current profile expires at
  2026-09-15 15:16:52 Asia/Shanghai. Only `000001.SH`, `399001.SZ`, `399006.SZ`, and `000688.SH`
  are `READY`; `899050.BJ` remains `ERROR` and must not be reported as certified.
- Direct `tushare.token` and `ai.api_key` configuration is implemented as the only credential
  source. Windows Credential Manager, environment/file references, and child-only certification
  were removed by the user's explicit personal-tool policy. The configured token was used only by
  the explicitly authorized certification and LPC006/LPC008 production-acceptance calls.
- Hash-protected stock and board-index profiles expire after seven days and fail
  closed on tampering, endpoint mismatch, schema mismatch, or cross-surface reuse. Real stock and
  per-index probes are implemented, including first-429 global stop behavior. The stock profile is
  fully ready; the index profile truthfully preserves the `899050.BJ` error alongside four ready
  indexes.
- CPython cannot forcibly terminate an arbitrary non-cooperative synchronous provider
  callable. The real Tushare transport is configured with its own 15-second timeout and
  shutdown is bounded and visible. On this host, WinINET uses `127.0.0.1:7897` and TUN fake DNS
  `198.18.0.2` resolved `api.quicksync.cn` to `198.18.0.42`; default Requests,
  `trust_env=False`, and `NO_PROXY=*` still produced `TLSV1_ALERT_INTERNAL_ERROR`. An authorized
  connection to `111.229.23.244` succeeded while preserving the original Host/SNI and CA checks;
  `101.35.23.219` failed, and the wrong-hostname certificate negative check was rejected. The
  ignored local setting `tushare.connect_ip=111.229.23.244` powered both production passes without
  per-run proxy environment changes. This public address is an operator setting, is not hard-coded
  in source, and remains bounded by the real endpoint certificate.
- The repository-wide offline gate remains blocked by the unrelated 252-day backtest
  performance budget described above; focused live-chain, frontend, and browser gates are green.

## Acceptance Status

`LIVE_CHAIN_PRODUCTION_ACCEPTED_INDEX_CERTIFICATION_PARTIAL` — LPC005, LPC006, and LPC008 pass
with separate live-certification and installed-production evidence. The independent index run
certifies four indexes and `SourceTimeLabel=END`, but `899050.BJ` remains `ERROR`; LPC007 therefore
remains open and does not certify the Beijing Stock Exchange 50 index. LPC012 also remains open on
the unchanged repository-wide 252-day capacity gate. No completion claim is based only on
component tests or profile generation.
