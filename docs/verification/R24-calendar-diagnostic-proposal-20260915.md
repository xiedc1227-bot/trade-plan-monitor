# R24 bounded calendar diagnostic plan

Canonical English; `R24-calendar-diagnostic-proposal-20260915.zh-CN.md` is the equivalent Chinese review copy. Proposal ID `R24-20260915-PM-CALENDAR-1`; run ID `r24-20260915-a`. Status **CALENDAR_DIAGNOSTIC_PASS / ALLOWANCE_CONSUMED / CLOSED / FULL_WORKFLOW_NOT_PROVEN**.

## Attempt disposition

At `2026-09-15T14:18:20+08:00`, offline preflight passed on clean candidate commit `1a2d89d079920aad2a4896470425dc84749df3ff`, but the host rejected execution before process creation pending exact user approval. After that approval, final preflight passed on clean documentation-closeout HEAD `05181319e84b011086440a6ff581603059f470fb` at `14:27:20+08:00`. R24 then ran from `14:27:35.883636+08:00` through `14:27:56.083854+08:00`. Its only `trade_cal` physical start succeeded and persisted 399 calendar rows; the lifecycle reached the 20-second wall limit and completed normal cleanup. See [execution record](R24-calendar-diagnostic-execution-20260915.md). The claim and allowance are consumed and must not be reused.

## Purpose and evidence boundary

R23 ended after its first `trade_cal` physical start returned `REFERENCE_TIMEOUT / TRANSPORT_TIMEOUT`. The whole R23 session lasted about 492 milliseconds, so the preserved result was not the request controller's 15-second logical timeout. The sanitized evidence cannot distinguish an early connect, TLS, read, remote, or local transport cause. R22's earlier success proves only that invocation. R24 therefore performs only one new calendar invocation to test whether the prerequisite path is currently reproducible; it does not reopen the AI or full market workflow and cannot prove business acceptance.

The local journal closeout defect observed in R23 is fixed before this candidate: normal closeout writes both final budget snapshots into `physical-attempts.json`. This changes evidence consistency only; it does not alter transport timeout, retry, routing, or production behavior.

## Admission and isolation

- Candidate date: **2026-09-15**. Admission gate: **14:18:00–14:35:00 Asia/Shanghai inclusive**. The 20-second wall limit ends new calls well before market close.
- Fresh one-shot root: `data/r24-calendar-diagnostic/`; fresh claim: `_session_claimed`; isolated database: `r24-20260915-a/monitor.sqlite3`; loopback port: `18769`.
- The default invocation is `DRY_RUN_NO_NETWORK`. Execution requires the exact R24 authorization and run ID. It validates the current configuration, endpoint identity, direct-route presence, stock certificate, port, and time gate without exposing credentials or the direct address.
- The locally recorded stock certificate expires at `2026-09-16T14:48:40.405317+08:00`; the five-index certificate expires at `2026-09-18T10:20:44.522358+08:00`. R24 needs only the stock certificate and does not recertify either file.
- The real `config/app.yaml` SHA-256 before preparation is `89923EA019712573B0F8118164EDA1EE2A8371C4EE57FAF2A2AD48FD6B8AB428`. R24 does not modify it.

## Bounded work, cost, and stop rules

- AI physical starts: **0**. No balance, model-list, or other account probe; no AI cost.
- Market physical starts: at most **1**, solely `trade_cal=1`; all other endpoints have cap zero. Failed starts consume the allowance. Market-data fee and taxes, if any, are unknown.
- Retries: **0**. The live request controller and direct HTTPS transport retain their existing 15-second bounds. R24 does not increase timeouts, add fallback routing, change the configured provider, or use an environment proxy.
- The first market or reference failure stops all admission immediately. Normal cleanup has at most 20 seconds to close the listener, restore the provider factory, confirm the isolated plan is inactive, and atomically write `audit.json` plus a final-snapshot `physical-attempts.json`.
- A successful calendar refresh may run until the 20-second wall limit so the ordinary lifecycle can close with a normal audit. Success proves only that invocation's calendar acquisition, validation, and persistence path.

## Current official AI route and pricing check

DeepSeek's official pricing page checked on 2026-09-15 identifies `deepseek-v4-pro` as `DeepSeek-V4-Pro-0813`, not Flash. It lists weekday peak hours as 01:00–04:00 and 06:00–10:00 UTC; this Shanghai-afternoon candidate falls in the latter peak interval. Those facts invalidate R23's historical Flash-route assumption. They do not create an R24 charge because AI starts are capped at zero. Source: https://api-docs.deepseek.com/quick_start/pricing/

## Prohibitions and disposition

R24 is IN_APP-only and diagnostic-only. It does not create, review, save, or activate a plan; change holdings; send a webhook; connect to a broker; place an order; execute a trade; recharge an account; create automation; or wait in the background. Its one-shot claim is consumed when execution enters the gate. Success or failure does not authorize a replacement candidate or R25.
