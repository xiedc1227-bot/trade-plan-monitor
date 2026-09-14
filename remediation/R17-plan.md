# R17 bounded afternoon retest preparation

Canonical English; `R17-plan.zh-CN.md` is the equivalent Chinese review copy. This replaces the **unexecuted** 2026-09-15 morning candidate with one proposed 2026-09-14 afternoon session. Preparation is **NOT_AUTHORIZED / NOT_RUN**. R14-A/C7 remains failed with three real `INVALID_OUTPUT` results of unknown precise cause.

## Scope and decision boundary

- Proposal `R17-20260914-AFTERNOON-60`, run `r17-20260914-a`, proposed 14:35 start, 14:30:00–14:40:00 inclusive admission. Actual start starts 900 seconds of new-call time; latest allowed start stops new calls at 14:55, before 14:57 closing auction. Shutdown and isolated deactivation share 20 further seconds of cooperative asynchronous cleanup; blocked OS/local I/O may exceed 920 seconds. Direct user approval and exchange-open, certificate, entitlement, balance/quota, price and port checks are prerequisites. No auto-schedule, renewal, retry or date rollover.
- Keep exact `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01` texts, one `deepseek-v4-pro` attempt each, zero retry, 19,000 UTF-8 prompt bytes, `max_tokens=4096`, 30-second AI timeout. Market remains 15-second TLS route and a total 60 physical starts with `trade_cal=3`, `stk_limit=0`, `daily=0`, `rt_min_daily=2`, `rt_min=15`, `idx_mins=5`, `rt_idx_min_daily=30`, `index_daily=5`. A fourth fully lagged five-index boundary, missing cache or extra demand stops at the guard. No thresholds, freshness, history or policies change.
- Only loopback `127.0.0.1:18765`, `InAppChannel`, isolated `data/r17-acceptance/` SQLite, synthetic labelled test inventory. No `config/app.yaml`, production 8765, real holding, broker or external notification changes. R14 claim/token remain historical; the R17 root has its own one-shot claim. The human separately supplies and reviews `TRADING_DAY=2026-09-14`; it is not AI extraction.
- [DeepSeek's official prices](https://api-docs.deepseek.com/quick_start/pricing/) checked 2026-09-14 and [usage accounting](https://api-docs.deepseek.com/quick_start/token_usage/) do not yield an exact currency hard cap from client limits. Market prices remain unknown. Approval must include account-side limits or informed acceptance of possible charges.

## Acceptance checklist

- [x] Default dry-run and date/token/run/claim/shared-stop boundary tests reject R14 and the obsolete morning candidate without network.
- [x] Real FastAPI lifespan, extraction/review/activation API, production scheduler, Tushare adapter and controlled SDK/HTTP verify the virtual **14:35:12–14:49:12** schedule. Mock index rows exclude lunch; stock recovery excludes 11:30–13:00. The 14:38:30 synthetic human activation is an explicit assumption; the complete source-faithful literal draft is separate from the three mock AI outputs.
- [x] Three all-five-lag boundaries at 14:35/14:40/14:45 recover next minute; 14:40 and 14:45 completed evaluations persist with previous-five-bar capacity. Count **55** physical market starts (3 calendar, 1 stock history, 11 stock minute, 5 index history, 30 realtime index, 5 index daily), zero denials. Late activation is `NOT_OBSERVED`, never an extension.
- [x] Simulated no-activation/AI-failure, persistent lag and missing-cache paths retain guard refusal and non-`LIVE` health; evidence is bounded, redacted and marked `SIMULATED`. No real AI/market call or browser receipt is claimed.
- [x] Focused R14–R17 tests, lint, default dry-run and 16 protected hashes are the final preparation checks. Only R17-owned changes are committed; no live execution or recurring task.
