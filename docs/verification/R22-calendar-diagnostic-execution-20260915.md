# R22 one-shot calendar diagnostic execution

Canonical English; `R22-calendar-diagnostic-execution-20260915.zh-CN.md` is the equivalent Chinese review copy. Status **LIVE_CALENDAR_DIAGNOSTIC_PASS / AUTHORIZATION_CONSUMED / FULL_WORKFLOW_NOT_PROVEN**.

## 1. Outcome

The fresh session started at `2026-09-15T11:30:39.502308+08:00` and finished at `11:30:54.767276+08:00`. Exactly one `trade_cal` physical start completed without a bounded market or reference failure. The production reference path persisted 399 SSE calendar rows from `2025-09-14` through `2026-10-17`; `2026-09-15` was present once and marked open.

The audit status is `WALL_LIMIT_REACHED` because a successful reference refresh does not itself terminate the loopback application; the deliberately short 15-second diagnostic wall timer initiated normal shutdown. In this candidate, that status is a controlled completion rather than a timeout of the provider request. Evidence for the distinction is: calendar rows were persisted, `firstMarketFailure=null`, `referenceFailureCode=null`, the process exit code was 0, and normal cleanup completed.

## 2. Physical counts and isolation

| Item | Observed |
| --- | --- |
| AI | 0 of 0 |
| `trade_cal` | 1 of 1 |
| Other market endpoints | 0 of 0 each |
| Retries | 0 |
| Denied before network | 0 |
| Isolated plan cleanup | `INACTIVE` |
| Port 18767 after exit | closed |
| Normal audit present | true |

The isolated database has zero plan sources/versions/reviews/activation rows, positions, daily/minute/five-minute bars, evaluations, alerts, delivery attempts, market-index data, health projections, and risk state. It contains one schema revision row, one internal monitor sequence row, and the 399 calendar rows. No webhook, broker, order, trade, AI, model-list, or balance endpoint was called. The real plan, holdings, configuration, and earlier R18/R20 evidence were not changed.

## 3. Evidence integrity

The one-shot claim remains present under `data/r22-calendar-diagnostic/_session_claimed`, so the authorization cannot be reused. Preserved artifact SHA-256 values are:

- `physical-attempts.json`: `CD6EDC4EE88891AFDFECA2814B64BEC781CAF6C428429756C35B35102469D254`;
- `audit.json`: `573038C2BFABA2BAED06AE5BD8CD052375FFCB09132010F1C4A7A4B327275129`;
- `monitor.sqlite3`: `0243BB41E401CE39A69E8E3AF6828E58F5851D3C95F76BFCE7236C562B4E5A7F`.

The ignored real `config/app.yaml` SHA-256 remained `89923EA019712573B0F8118164EDA1EE2A8371C4EE57FAF2A2AD48FD6B8AB428`. Execution occurred from the R21 base commit `8741b5d13046e5db327ef750897e1a55c4ff3021` plus the reviewed candidate worktree. A formatting-only import reorder followed the live run; the captured candidate behavior is committed as `f88fc4a58709d0041e9822df13070c15ff722c92`.

## 4. Offline verification

Before execution, 17 focused R14/R20/R22 tests passed. After execution and the formatting-only change, 254 selected non-live production, lifecycle, Tushare contract, bounded-wiring, and R22 tests passed with one pre-existing Starlette/httpx deprecation warning. Targeted Ruff and `git diff --check` passed.

## 5. Evidence boundary and next decision

This pass shows that one direct-IP Tushare calendar request, response validation, current-date check, and SQLite persistence succeeded at the recorded time. It does not identify the exact historical R20 transient cause and does not prove future availability.

It also does not prove R19's real v5/8,192 extraction, semantic correctness, review/save/activation, minute/index data, natural BUY/SELL/RISK evaluation, or visible IN_APP alert delivery. Reopening that larger loop requires a new candidate, fresh claim/database/port, current certificate checks, bounded AI/market costs, and separate explicit authorization. No such candidate or automation was created by R22.
