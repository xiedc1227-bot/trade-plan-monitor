# R18 same-morning restart execution record — business failure

Canonical English; `R18-execution-20260915-restart.zh-CN.md` is the equivalent Chinese review copy. Proposal ID `R18-20260915-RESTART-105`; run ID `r18-20260915-b`. Final status **AI_INVALID_OUTPUT / BUSINESS_FAILED / SESSION_CONSUMED**.

## Execution and bounded calls

The authorized replacement candidate started at `2026-09-15T09:40:26.803818+08:00` inside its 09:40–09:45 admission gate. The browser showed the isolated service running and monitorable, with `trading_calendar` and the other certified market capabilities ready. The fixed `LITERAL` source was submitted once through the normal browser page to configured `deepseek-v4-pro`.

The terminal result was `INVALID_OUTPUT`. The bounded diagnostic recorded stage `response`, reason `FINISH_REASON`, `finishReason=length`, `modelMatchesConfigured=true`, and one attempt. Reported usage was 5,077 prompt tokens plus 4,096 completion tokens, 9,173 total. The output reached the fixed completion ceiling and was not accepted by the closed contract. No draft was returned or saved.

Following the approved stop rule, the literal source was not resubmitted and `SEM-AMB-01` / `SEM-UNS-01` were not sent. The service was stopped immediately. Its audit therefore records controlled cancellation as `FAILED` / `CancelledError`; isolated-plan cleanup returned `INACTIVE`.

Physical starts remained within the hard bounds:

- DeepSeek: **1 of 3**, only `LITERAL`.
- Market data: **1 of 105**, only `trade_cal`.
- Denied-before-network calls: **0** on both guards.

## Business evidence

The isolated database contains 399 trading-calendar rows and zero plan versions, active plans, activation states, extraction reviews, positions, minute bars, five-minute bars, evaluations, alerts or delivery attempts. No plan was reviewed or activated, no market rule was evaluated, and no in-app alert was emitted. AI and market-data charges may apply to the two physical starts above; no monetary amount is asserted.

The R18 restart did not pass business acceptance. This candidate and its authorization are consumed and cannot be retried. The earlier candidate `r18-20260915-a` remains separately recorded as `NOT_RUN_TIME_GATE / ZERO_EXTERNAL_CALLS`.
