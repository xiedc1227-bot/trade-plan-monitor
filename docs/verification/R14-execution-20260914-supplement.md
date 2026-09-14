# R14 execution supplement — 2026-09-14

Canonical English; the matching `.zh-CN.md` is the equivalent Chinese review copy. This supplements, and does not rewrite, the earlier NOT_RUN attempt. Actual code baseline: `main/70e2a92d5375207d33da69bf727d50342a63e866`; prepared harness: `b557c4f9a277632a678c5a7f8f77f1124f473fd1`.

## 1. Authorization and actual execution

The user directly authorized an immediate single replacement attempt starting by 10:30 Asia/Shanghai, up to 15 minutes, the same three DeepSeek inputs/three physical AI attempts and 60 market attempts, disclosed billing uncertainty, isolated database and IN_APP only. No new automation was created. The exact prepared command ran from the project directory:

```powershell
.\.venv\Scripts\python.exe scripts\r14_bounded_acceptance.py --execute --authorize R14_3_AI_60_MARKET_IN_APP_15MIN --run-id r14-20260914-a
```

The initial read-only preflight was ready at 10:21:42. Actual start **2026-09-14T10:22:09.654195+08:00**, finish **2026-09-14T10:36:18.079591+08:00**, elapsed **848.425 seconds**. The process exited **1 / BUDGET_DENIED**: the `rt_idx_min_daily=25` endpoint allowance was exhausted before the global 60-query or 900-second limit. Five further admissions were denied before network execution. This is an observed controlled stop, not proof of full acceptance or an uncontrolled overspend. No retries beyond the prepared request policy, model changes, extra source texts, or new session were attempted.

## 2. Business acceptance results

**Real execution partially completed; core acceptance failed at the complete literal AI extraction. R14-A/C7 is not passed.**

| Step | Actual result | Evidence boundary |
| --- | --- | --- |
| LITERAL | One physical DeepSeek attempt; UI `INVALID_OUTPUT`, not saved as executable rules. | The complete original source failed to produce a reviewable plan in this run. No retry or JSON replacement. |
| SEM-AMB-01 | One physical attempt; UI `INVALID_OUTPUT`. | Unsafe activation was prevented; useful ambiguity clarification was not demonstrated. |
| SEM-UNS-01 | One physical attempt; UI `INVALID_OUTPUT`. | Unsafe activation was prevented; faithful handling of the unsupported phrase was not demonstrated. |
| Review and activation | No saved/reviewed/active plan. | Downstream stock monitoring cannot be declared verified. |
| Calendar and indexes | Real SSE calendar says 2026-09-14 is open; browser showed index data advancing from 10:25 to 10:30. | Partial provider/UI evidence only. Readiness flags are not fresh stock-data proof. Some index heads are BLOCKED; 10:35 heads after denial report `PROVIDER_UNAVAILABLE`, not successful fresh data. |
| Stock bars, deterministic conditions and alerts | Zero stock minute/five-minute rows, explicit evaluation rows, alerts and deliveries. | **NOT_RUN because extraction blocked activation**, not a case where a monitored plan simply did not trigger. |
| Holdings and cleanup | Zero isolated inventory/opening-balance/lot rows; cleanup `INACTIVE`; port 18765 closed. | No holding registration, fill, alert ACK or production holding change was performed. |

The three exact approved texts were submitted using the real Chrome source editor at `http://127.0.0.1:18765/plans`; each final failure was observed separately. The alerts page showed zero records. No synthetic stock market data or substitute plan was injected. The observed browser evidence is recorded in `browser-observations.json`; it is an observer record, not a provider-response export.

## 3. Calls, scope and limitations

AI: **3/3**, one each `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01`; zero guard denials. Market: **36/60** physical attempts: `trade_cal=1`, `idx_mins=5`, `index_daily=5`, `rt_idx_min_daily=25`; **5** additional calls denied before network. `rt_min=0`, `rt_min_daily=0`. Zero physical stock calls is explained by no activated stock plan. Physical attempt counts do not prove every response succeeded or establish actual billing. Usage/token totals and actual charges were not captured; no monetary conclusion is claimed.

The harness retained neither raw model output nor a sufficient per-request finish-reason/validation-path diagnostic. Static code permits multiple reasons for `INVALID_OUTPUT` (`ai/extraction.py:104–148`); the UI exposes a generic failure, and `web/ai_service.py:294–298` persists only successful review results. Therefore malformed JSON, truncation, schema errors and mapping errors remain **unconfirmed alternatives**, not established causes. All three failures do not prove a general model incapability. Separately, the index endpoint budget ran out even without an active stock plan; the offline two-evaluation/39-call example was not a guarantee under real provider timing. The present evidence does not fully identify why the additional index attempts were needed.

All **16** protected files match their preparation hashes. Existing user changes remain intact. No business code, real configuration, original 8765 service or production database was modified. The ignored isolated database and session claim remain as evidence; the claim must not be removed to repeat this authorization.

## 4. Evidence and next minimum step

See `remediation/evidence/R14-execution-20260914-supplement/`: `audit.json` is copied from the actual launcher; `summary.json` contains read-only final database/calendar/index-head and cleanup checks; `browser-observations.json` records actual UI observations and source hashes. The ignored original database is `data/r14-acceptance/r14-20260914-a/monitor.sqlite3`.

No new unit/full regression suite was run during this live acceptance; the preceding 14-pass morning offline suite remains separate evidence. The next remediation should first add bounded sanitized AI failure diagnostics, then reproduce the concrete failure offline and fix the provider/prompt/parser mismatch only when identified. Also measure the real index refresh/publication-delay request pattern before proposing a revised budget or decoupling. Keep fail-closed validation. Only after that should another separately scoped real run verify the original literal through activation, real stock conditions and user-visible alerts. This task did not implement those future changes or authorize another paid run.
