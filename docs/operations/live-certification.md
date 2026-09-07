# Tushare Live Certification

## Purpose

`LPC005` and `LPC007` are separately selected one-shot checks. They run directly in the current
process and read the Tushare token from the local application YAML. Stock and board-index runs
retain separate authorization phrases, capability sets, timestamp labels, and evidence profiles;
they do not require Windows Credential Manager or a child process.

Stock certification covers `trade_cal`, `stk_limit`, `daily`, one ten-symbol `rt_min` batch, and
two `rt_min_daily` observations. Board-index certification checks `idx_mins(freq="5min")` and
`index_daily` separately for every approved `MarketIndexCode`.

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

Direct `tushare.token` and `ai.api_key` values take precedence. The former `token_ref` and
`api_key_ref` shapes remain readable during migration, so an existing personal configuration does
not stop working immediately. `config/app.yaml` is excluded by the repository `.gitignore`.

## Authorized Runs

Run stock and index certification independently:

```powershell
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py stock --authorize LPC005_STOCK_LIVE_CERTIFICATION --config config/app.yaml
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py index --authorize LPC007_BOARD_INDEX_LIVE_CERTIFICATION --config config/app.yaml
```

Eligible `Asia/Shanghai` windows on a weekday are:

| Surface | Morning | Afternoon | Official-close follow-up |
|---|---:|---:|---:|
| Stock | `09:32`–`11:25` | `13:02`–`14:55` | `15:20`–`16:30` |
| Board index | `09:40`–`11:25` | `13:10`–`14:55` | `15:20`–`16:30` |

The runner additionally requires `trade_cal` to prove the observation date is open. An
ineligible local window returns `NOT_RUN_MARKET_WINDOW` before loading configuration or calling
the provider.

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
does not authorize or disable its peers.

## Authoritative References

- [Tushare `idx_mins`](https://tushare.pro/document/2?doc_id=419)
- [Tushare `index_daily`](https://tushare.pro/document/1?doc_id=95)
- [Tushare `trade_cal`](https://tushare.pro/document/2?doc_id=26)
