# Tushare live contract acceptance

Status: PASS — the visible-block branch is accepted; all five capabilities are `ERROR` from sanitized provider code `TRANSIENT`

- Evidence date: 2026-08-31, 11:24:21–11:24:26 `+08:00` (`Asia/Shanghai`).
- Evidence baseline: `main` at `eee65fd9ede37cee229c0147ba2ddb55a5f311d5`; this report describes the uncommitted T058 candidate derived from that baseline.
- Boundary: one explicitly authorized T058/P18 live probe of `rt_min`, `rt_min_daily`, `trade_cal`, `stk_limit`, and `daily` through `api.quicksync.cn`. No broker, notification, AI-provider, historical-sync, or unapproved provider interface was called.
- Decision: no capability can be labelled `READY` from this run. Production classification reduces each provider failure to safe code `TRANSIENT`, which maps to capability status `ERROR`. The application demonstrably remains degraded, read-only, and visibly blocked; the timestamp state remains `SourceTimeLabel.UNVERIFIED`, and neither `SourceTimeLabel.START` nor `SourceTimeLabel.END` is asserted.

## Reference environment and credential handling

| Item | Observed fact |
|---|---|
| Host | Windows 11 `10.0.26200`, local single-user process |
| Python / pandas / Tushare SDK | CPython 3.14.7 / pandas 3.0.5 / tushare 1.4.29 |
| Business clock | `Asia/Shanghai`; all observation times carry explicit `+08:00` |
| Endpoint | HTTPS host `api.quicksync.cn`; no credential in the URL |
| Credential reference | `TUSHARE_TOKEN` supplied only to the authorized child process |
| Live authorization | Process-local `TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE=1`; ordinary suites skip network tests, while an explicit `-m live` selector fails closed when authorization or the token reference is absent |

The credential page was opened only after action-time confirmation, read in the controlled browser, and closed. The token was kept in memory, passed through standard input to the one authorized child process, installed only in that child's environment, never added to the parent process environment, and cleared with the browser execution context after use. It was never written to a file, command line, report, Git object, or test output. Raw SDK exceptions, HTTP bodies, headers, request arguments, and authorization responses are not evidence artifacts.

## Capability and pacing evidence

The sanitized RED independently attempted all five approved operations so one failure could not hide the remaining capability states.

| Operation | Result | Latency ms | Safe observation |
|---|---|---:|---|
| `trade_cal` | `ERROR` (`TRANSIENT`) | 7 | zero rows; no schema or body retained |
| `stk_limit` | `ERROR` (`TRANSIENT`) | 24 | zero rows; no schema or body retained |
| `daily` | `ERROR` (`TRANSIENT`) | 2 | zero rows; no schema or body retained |
| `rt_min` | `ERROR` (`TRANSIENT`) | 13 | one exact 10-symbol request; zero returned symbols |
| `rt_min_daily` sample 1 | `ERROR` (`TRANSIENT`) | 26 | zero rows |
| `rt_min_daily` sample 2 | `ERROR` (`TRANSIENT`) | 18 | zero rows |

Calls started at least one second apart. The six starts were recorded at consecutive seconds from `11:24:21+08:00` through `11:24:26+08:00`. No `RATE_LIMITED` classification was observed under this pacing. The test did not intentionally generate rate-limit traffic and does not infer this account's per-minute allowance from documentation or another account.

The following machine-readable object is the canonical sanitized evidence shared byte-for-byte with the Chinese report. It intentionally contains no credential value, raw request, response body, or provider exception text.

<!-- T058-CANONICAL-EVIDENCE-START -->
```json
{
  "acceptanceBranch": "VISIBLE_BLOCK",
  "baseline": "eee65fd9ede37cee229c0147ba2ddb55a5f311d5",
  "capabilities": {
    "daily": "ERROR",
    "rt_min": "ERROR",
    "rt_min_daily": "ERROR",
    "stk_limit": "ERROR",
    "trade_cal": "ERROR"
  },
  "calls": [
    {
      "latencyMs": 7,
      "operation": "trade_cal",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:21+08:00"
    },
    {
      "latencyMs": 24,
      "operation": "stk_limit",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:22+08:00"
    },
    {
      "latencyMs": 2,
      "operation": "daily",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:23+08:00"
    },
    {
      "latencyMs": 13,
      "operation": "rt_min",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:24+08:00"
    },
    {
      "latencyMs": 26,
      "operation": "rt_min_daily",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 1,
      "startedAt": "2026-08-31T11:24:25+08:00"
    },
    {
      "latencyMs": 18,
      "operation": "rt_min_daily",
      "providerErrorCode": "TRANSIENT",
      "result": "ERROR",
      "rows": 0,
      "sample": 2,
      "startedAt": "2026-08-31T11:24:26+08:00"
    }
  ],
  "endpointHost": "api.quicksync.cn",
  "finalMinute": null,
  "officialCloseRows": null,
  "pacingSeconds": 1.0,
  "rateLimitObservation": "NO_429_UNDER_PACING",
  "requestedSymbols": 10,
  "returnedSymbols": 0,
  "sourceTimeLabel": "SourceTimeLabel.UNVERIFIED",
  "timezone": "Asia/Shanghai"
}
```
<!-- T058-CANONICAL-EVIDENCE-END -->

## Batch, partial rows, and units

`rt_min` received one comma-separated 10-symbol request. The call was classified `TRANSIENT` before any provider row became available, so the live result is 10 requested, zero returned, and no unexpected symbol. This is not evidence that the batch is `READY`, nor evidence of provider partial-row behavior.

No raw market row was available for live unit reconciliation. Therefore realtime price-to-fen, volume-in-shares, amount-in-yuan, daily volume-times-100, and daily amount-times-1000 remain live-unverified. Existing deterministic offline contract tests remain valid, but they are not presented as T058 live evidence.

## Timestamp mapping, final minute, and official close

Both `rt_min_daily` samples ended with safe provider code `TRANSIENT` before rows were returned. The timestamp mapping consequently remains `SourceTimeLabel.UNVERIFIED`; the report does not select `SourceTimeLabel.START` or `SourceTimeLabel.END`.

The 15:00 final minute, 240-minute complete day, and official `daily` close could not be observed. Both required surfaces are `ERROR`, so the corrected close branch performs no additional call and keeps the application visibly read-only. The evidence records `finalMinute=null` and `officialCloseRows=null`; `OFFICIAL_READY` is not claimed.

## Fail-closed application proof

The candidate maps production provider codes to the same `ProviderCapabilityStatus` contract as `TushareMarketDataProvider.probe_capabilities`, then starts the real `RuntimeLifecycleService`. Any complete mixture containing `BLOCKED_PERMISSION`, `RATE_LIMITED`, or `ERROR` must produce `DEGRADED`, `read_only=true`, `next_poll_at=null`, and zero owned actionable tasks. Its health API model must preserve every individual status, and the tracked health matrix must render the current `ERROR` state as `错误`. A supplemental provider guard still proves that an unverified timestamp mapping reaches no SDK call. This is application-level visible blocking rather than a provider-only inference.

## Commands and result

The prescribed authorized selector is:

```text
python -m pytest tests/contract/test_tushare_live.py -q -m live
```

The first diagnostic RED was discarded because pytest's normal traceback included non-secret request arguments. No token or raw provider response appeared. The failure surface was immediately changed to fixed codes with `pytrace=False`. A later 10:15 run that labelled all failures `BLOCKED_PERMISSION` was also discarded because it used a duplicated permissive classifier rather than the production classifier.

An intermediate `3 passed` run was also discarded: review found that its close test made two additional calls before 15:20 while the report recorded only the original six. After the production classifier was wired, the authorized exact selector produced the expected RED at 11:24: all five provider errors were safely classified `TRANSIENT`, while the test still treated adapter error codes as capability states. The selector reported `3 failed`, made only the six recorded calls, and confirmed that the configured Token value was absent from output. The corrected candidate now maps those codes to `ProviderCapabilityStatus.ERROR`, reuses the stable five-capability observation, and makes zero close-test calls. The affected offline market/runtime suite reports `399 passed, 2 skipped` after this correction.

The corrected authorized selector completed with `3 passed in 6.09s`. The final affected offline market/runtime rerun completed with `399 passed, 2 skipped in 5.77s`. Ruff check, Ruff format for 158 tracked-or-candidate Python files, `compileall`, `pip check`, whitespace checks, report equivalence, configured-Token absence, and the ordinary zero-network selector all pass.

One additional non-required whole-backend diagnostic was stopped after the existing `test_ten_symbol_252_day_replays_meet_capacity_budgets` exceeded its 120-second deadline by 0.087856 seconds on the first symbol. Its focused rerun reproduced the same host-performance failure in 284.90 seconds. No threshold or backtest code was changed; this diagnostic is outside T058's required live plus complete offline market/runtime gate and is not presented as passing evidence.

T058 acceptance is satisfied by its explicit alternative: every required capability is either `READY`, or the application remains honestly and visibly blocked. Here none is `READY`; all five are `ERROR`, and the report claims only the proven visible-block branch. A later attempt to obtain `READY` evidence requires fresh operation-specific authorization and the appropriate market window; it must replace, not reinterpret, these facts.

## Redaction and artifact policy

The tracked report contains only the environment-variable name `TUSHARE_TOKEN`, stable capability codes, counts, timestamps, endpoint host, and bounded latency. It contains no credential URL, token value, `Authorization`/`Bearer` material, raw response, provider exception text, downloaded code, screenshot, browser profile, or temporary observation file. All five protected validation-only files remain untracked and unmodified, and none was executed or used as evidence. One accidental `rg` diagnostic search read six matching lines from the protected soak file; it was disclosed to the user, its output is excluded from evidence, and every subsequent formal input used an explicit tracked-or-candidate allowlist.
