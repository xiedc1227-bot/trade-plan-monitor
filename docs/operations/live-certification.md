# Tushare Live Certification

## Purpose

`LPC005` and `LPC007` are separately authorized, one-shot checks. The parent process is
secret-blind: it receives only a Windows Credential Manager target name and launches a child
with an allowlisted environment. Only that child reads the credential, temporarily exposes it
as `TUSHARE_TOKEN`, runs exactly one selected surface, restores its environment, and zeroes the
mutable credential buffers.

The stock and board-index runs never share timestamp evidence. Stock certification covers
`trade_cal`, `stk_limit`, `daily`, one ten-symbol `rt_min` batch, and two `rt_min_daily`
observations. Board-index certification checks `idx_mins(freq="5min")` and `index_daily`
separately for every approved `MarketIndexCode`.

## One-Time Credential Setup

Run this command in a private local terminal. The prompt does not echo the token. Never place
the token in the command line, chat, source tree, `.env`, report, or screenshot.

```powershell
.\.venv\Scripts\python.exe scripts\set_tushare_live_credential.py
```

The default Windows Credential Manager target is `trade-plan-monitor/tushare-live`. The setup
script validates printable ASCII, stores the credential through `CredWriteW`, and zeroes its
mutable copy. The live child reads it through `CredReadW` and always releases the native buffer
with `CredFree`.

## Authorized Runs

Run stock and index certification independently:

```powershell
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py stock --authorize LPC005_STOCK_LIVE_CERTIFICATION
.\.venv\Scripts\python.exe scripts\run_tushare_live_contract.py index --authorize LPC007_BOARD_INDEX_LIVE_CERTIFICATION
```

Eligible `Asia/Shanghai` windows on a weekday are:

| Surface | Morning | Afternoon | Official-close follow-up |
|---|---:|---:|---:|
| Stock | `09:32`–`11:25` | `13:02`–`14:55` | `15:20`–`16:30` |
| Board index | `09:40`–`11:25` | `13:10`–`14:55` | `15:20`–`16:30` |

The child additionally requires `trade_cal` to prove the observation date is open. An
ineligible local window returns `NOT_RUN_MARKET_WINDOW` before any child or provider call.

## Evidence and Failure Semantics

Sanitized, hash-protected profiles are written under the ignored directory
`data/live-certification/`:

- `tushare-stock-live.json`
- `tushare-board-index-live.json`

Profiles contain endpoint identity, SDK version, timestamps, capability status, timestamp-label
semantics, and a SHA-256 integrity value. They contain no token, authorization response, raw
provider frame, request header, or provider exception text. A profile is accepted only for its
exact HTTPS endpoint, within seven days, with an intact hash and the correct surface schema.

Calls are serial with one worker, start at least `1.25` seconds apart, time out after `15`
seconds, and are never retried during certification. The first `RATE_LIMITED` result stops every
later provider call. Permission failures remain `BLOCKED_PERMISSION`; other failures are reduced
to stable, secret-free states. A stock profile is actionable only when all five capabilities are
`READY` and its `SourceTimeLabel` is verified. Index readiness is kept per index, and one blocked
index does not authorize or disable its peers.

## Authoritative References

- [Microsoft `CredReadW`](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credreadw)
- [Microsoft `CredWriteW`](https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credwritew)
- [Microsoft password-handling guidance](https://learn.microsoft.com/windows/win32/secbp/handling-passwords)
- [Tushare `idx_mins`](https://tushare.pro/document/2?doc_id=419)
- [Tushare `index_daily`](https://tushare.pro/document/1?doc_id=95)
- [Tushare `trade_cal`](https://tushare.pro/document/2?doc_id=26)
