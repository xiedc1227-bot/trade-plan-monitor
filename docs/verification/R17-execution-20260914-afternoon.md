# R17 afternoon live execution — business acceptance not passed

Canonical English; the matching `.zh-CN.md` is the Chinese review copy. Execution baseline: branch `main`, commit `878f15e9180c75a7c882e3e739c56f184f829da0`, with the original 12 tracked user changes and four R00 untracked files retained. The user directly approved the afternoon proposal in the coordinating task. This was an actual new one-shot session, not replay, a scheduled attempt, or a reuse of R14 authorization.

## 1. Outcome and bounded session

**Real chain partially exercised; business acceptance FAILED.** The local browser and real provider boundary were exercised, but no valid reviewed plan reached activation, no market monitoring cycle completed, and no alert was delivered. R14-A/C7 remains not passed. Safety rejection of invalid drafts is distinct from successful plan support.

Run: `r17-20260914-a`; proposal: `R17-20260914-AFTERNOON-60`. Default preflight at 14:36:44 Shanghai was ready; the guarded command started before the approved 14:40 cutoff. Final audit records **2026-09-14 14:37:10.665445–14:52:10.867411 Asia/Shanghai**, **900.201966 seconds**. Application health startup was separately recorded at 14:37:10.706979. Physical attempts: **AI 3, market 1 (`trade_cal`)**, with zero pre-network denials and no retries. No stock/index endpoint was called. Cleanup returned `INACTIVE`; port 18765 was closed after exit; both the old R14 and new R17 one-shot claims remain. All 16 protected SHA-256 entries match. Launcher status `WALL_LIMIT_REACHED` and exit code **0** indicate that the bounded process ended normally, **not** that business acceptance passed. An open local Web service did not imply a functioning monitor.

Limits remained three physical DeepSeek attempts, one per original text, `deepseek-v4-pro`, zero retries, 30-second timeout, 19,000 prompt UTF-8 bytes, 4,096 output tokens; market total 60 with the approved 30-index/2-stock-history allocation; only loopback 18765, isolated SQLite and IN_APP. No source, threshold, position, production database or runtime business code was changed. No new automation or replacement session was created.

## 2. Three real AI results

| Case | Submitted / completed, Shanghai | Actual terminal result | Diagnostic evidence |
| --- | --- | --- | --- |
| `LITERAL` | 14:38:12 / 14:38:42 | `PROVIDER_ERROR` | `providerErrorCode=TIMEOUT`, one attempt, no usage or finish reason returned |
| `SEM-AMB-01` | 14:40:08 / 14:40:14 | `INVALID_OUTPUT` | mapping-stage `AI_FIELD_EVIDENCE_INVALID`, `finishReason=stop`, configured model matched; 4,930 prompt + 561 completion tokens |
| `SEM-UNS-01` | 14:40:31 / 14:40:39 | `INVALID_OUTPUT` | mapping-stage `AI_FIELD_EVIDENCE_INVALID`, `finishReason=stop`, configured model matched; 4,937 prompt + 904 completion tokens |

Each original text was submitted once through the real browser UI. Three persisted diagnostic source hashes match the approved source identities. Failed inputs were not resubmitted. All results were activation-blocking, with null draft and mapping in the public result. No manual substitute draft or synthetic K line was injected to make the live run pass.

The two mapping errors establish that output failed the source/current-draft evidence check; they do not identify the exact incorrect field and do not prove that rejecting these ambiguous plans was a defect. Diagnostic `path=unknown` remains a limitation. The literal timeout does not prove insufficient account balance, model unavailability or a parsing defect. Billing for the timed-out attempt is unknown; returned usage for the other two attempts does not establish the total charge. Historical R14 failures remain separate observations.

## 3. Actual monitoring and browser observations

At 14:41:55 the read-only health API returned `DEGRADED`, `readOnly=true`, `trading_calendar=ERROR`, `REFERENCE_REFRESH_FAILED`, with no `nextPollAt`, completed minute or evaluation. The browser's System page showed the same degraded/read-only state and calendar error. Other capability labels were READY from configured certification state, with zero reported latency; they are not proof that those endpoints succeeded in this session.

The dashboard showed `EMPTY_DATABASE`, no index snapshot and no active explicit plan. The Alerts page, with all filters at their defaults, showed zero records and no live updates. SQLite contained no calendar, price bars, plans, reviews, activations, explicit evaluations, alert events, delivery attempts or inventory rows. No ACK or fill was recorded. Empty alerts in this run are **not** evidence that the system correctly judged an active plan and found no signal: normal monitoring had not started.

The precise calendar failure cause is unconfirmed. `src/trade_plan_monitor/web/monitor_composition.py:514`, `refresh_references()`, collapses exceptions to the safe stage code at line 520. No provider response body or lower-level error category was captured, and no extra calendar call, retry or restart was used to investigate during this run. Do not attribute this to quota, token, network or schema without evidence.

## 4. Confirmed front/back contract regression

After each accepted submission, the real page displayed “无法确认 AI 提取状态；服务端任务可能仍会继续，请稍后重试查询或重新提交。” and lost the operation result. A local GET of each known operation ID returned HTTP 200 with the correct terminal status and `diagnosticStatus=RECORDED`.

`PlanExtractionView` adds `diagnostic_status` at `src/trade_plan_monitor/web/routers/plans.py:537`; `_run_extraction()` populates it in `src/trade_plan_monitor/web/ai_service.py:310`. The front-end `isPlanExtraction()` in `web/src/api/ai.ts:205` uses a strict allowed-key list at line 209 that omits `diagnosticStatus`. The composable's catch branch at `web/src/composables/usePlanDrafting.ts:85` then replaces the accepted operation with the generic status error.

**Executed offline causal check:** replay all three captured public API responses through the repository's actual TypeScript `createAIPlanApi()` using an injected local Response, with no network. All three fail as `INVALID_RESPONSE` despite HTTP 200. Remove only `diagnosticStatus` in an offline copy: all three are accepted with their original failure status. No production payload, server, browser validator or running code was altered. This confirms an interface defect independently of the real AI failures. Existing backend/offline wiring regressions did not exercise this browser response contract and therefore missed it.

Minimum repair: update the public generated/handwritten client contract together, validate allowed diagnostic enum/null states, and add a production-shaped queued/running/terminal response test through the client/composable. Preserve rejection of unrelated unknown fields and ensure a status-display failure never suggests an unbounded paid resubmission. Verify in the actual browser before another paid attempt.

## 5. Commands and evidence

Executed once from `trade-plan-monitor/` after the user's direct approval:

```powershell
.\.venv\Scripts\python.exe -m scripts.r17_bounded_acceptance
.\.venv\Scripts\python.exe -m scripts.r17_bounded_acceptance --execute --authorize R17_20260914_3_AI_60_MARKET_IN_APP_15MIN --run-id r17-20260914-a
node remediation/evidence/R17-execution-20260914/reproduce-client-contract.cjs
```

The final command is offline and passed with exit 0; it reproduces three failures and three counterfactual successes using the unchanged current TypeScript source. This is verification evidence, not a fix. Read-only local API and SQLite queries do not consume provider quota. The baseline 27-test coordinator and 56-test worker preparation runs remain offline preparation, not real acceptance.

Evidence under `remediation/evidence/R17-execution-20260914/`: `observed-health.json`, `observed-extractions.json` (public failure DTOs, no source text or raw model output), `extraction-diagnostics.jsonl`, `client-contract-replay.json`, its reproducible `.cjs` script, `browser-observations.json`, and `web-assets.json` identifying the installed bundle. Final `audit.json` and `summary.json` contain actual counts, duration, port/claim checks, protected hashes and final read-only SQLite table counts. Source hashes match the three approved identities, and final relevant business tables remain empty. The isolated database remains under `data/r17-acceptance/r17-20260914-a/` and is not committed. No secrets, raw provider errors or account configuration are included.

## 6. Smallest next steps

1. Fix and browser-verify the diagnostic-status API contract regression offline.
2. Preserve a bounded, secret-free calendar failure category and test startup failure/recovery without invoking a real supplier. Diagnose this session only to the level supported by retained evidence.
3. Improve the mapping diagnostic's field/stage precision and verify literal-plan timeout behavior without assuming that longer timeouts or larger paid budgets are authorized.
4. Only after those checks, propose a new bounded real session. This one-shot authorization and claim must not be reused. Successful real extraction/review/activation, fresh stock data and persisted rule evaluation remain necessary; visible IN_APP receipt still needs its own actual observation.
