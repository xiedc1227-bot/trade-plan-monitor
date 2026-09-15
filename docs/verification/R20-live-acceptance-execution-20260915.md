# R20 live-acceptance execution record — stopped at calendar gate

Canonical English; `R20-live-acceptance-execution-20260915.zh-CN.md` is the equivalent Chinese review copy. Proposal ID `R20-20260915-A-105`; run ID `r20-20260915-a`. Final status **REFERENCE_TRANSIENT / BUSINESS_NOT_RUN / SESSION_CONSUMED**.

## Execution and physical starts

The authorized session atomically claimed its new root at `2026-09-15T10:40:25.420+08:00`, inside the 10:35–10:50 admission gate. Offline preflight at `10:40:11.823917+08:00` had reported the stock and all-five-index certificates ready, port 18766 available, `deepseek-v4-pro` configured, v5/8,192 session overrides selected, and AI balance explicitly unknown.

Startup made one budgeted real `trade_cal` attempt. It returned sanitized reference-stage code `REFERENCE_TRANSIENT`; the open-day and reference-health prerequisite was therefore not established. The service was externally stopped to enforce the no-retry rule. Port 18766 was confirmed released no later than `10:43:05.864+08:00`. Because that safety stop terminated the process before its normal `finally` completed, no normal `audit.json` exists; `termination.json` explicitly records this incomplete-normal-cleanup fact instead of claiming graceful shutdown.

Physical starts:

- DeepSeek: **0 of 3**. No source was submitted; prompt/completion/total tokens, finish reason, returned model and charges are **NOT_APPLICABLE / NOT_OBSERVED**.
- Market data: **1 of 105**, exactly `trade_cal=1`; every other market endpoint was **0**.
- Denied-before-network calls: **0 observed**.

No retry, second candidate, alternate model, extra balance/model-list probe or delayed/afternoon extension was performed.

## Business and isolation evidence

The isolated database has zero trading-calendar rows, plan sources, plan versions, extraction reviews, active/activation states, positions, minute bars, five-minute bars, evaluations, alerts and delivery attempts. Consequently:

- `LITERAL`, `SEM-AMB-01` and `SEM-UNS-01`: **NOT_RUN**.
- Human review, immutable save and activation: **NOT_RUN**.
- Six completed five-minute bars and five-bar mean evaluation: **NOT_RUN**.
- BUY/SELL/RISK natural trigger and IN_APP visibility: **NOT_OBSERVED**.
- Real holdings remained independent because the run used only its new isolated SQLite database and created no position state.
- No webhook, broker, order, trade or real-plan mutation occurred.

The one-shot R20 claim is consumed and must not be reused. Business acceptance remains unproved, but the fail-closed prerequisite and isolation boundaries behaved as required.

## Verification and implementation evidence

Focused R20 plus historical launcher wiring tests passed: **11 passed**, with one pre-existing Starlette/httpx deprecation warning. They prove v5/8,192/temperature-zero physical request filtering, the new date/run/port boundary and unchanged historical defaults. The dry-run preflight emitted no network call and reported the real configuration's explicit output cap as 4,096 while the isolated R20 lifecycle override was 8,192.
