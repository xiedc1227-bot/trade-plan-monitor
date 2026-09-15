# R22 one-shot calendar diagnostic proposal and gate record

Canonical English; `R22-calendar-diagnostic-proposal-20260915.zh-CN.md` is the equivalent Chinese review copy. Status **AUTHORIZED_ONCE / EXECUTED / AUTHORIZATION_CONSUMED**.

## 1. Purpose and authorization

R21 recommended isolating calendar health before reopening the larger R19 acceptance budget. The user's instruction `继续下一阶段` supplied fresh authorization for that recommended next stage only. It did not authorize the full AI, plan-review, activation, monitoring, alert, webhook, broker, order, or trade workflow.

The fixed candidate identity was:

- proposal: `R22-20260915-A-CALENDAR-1`;
- run: `r22-20260915-a`;
- eligible Shanghai window: `2026-09-15 11:20:00` through `11:55:00` inclusive;
- fresh loopback port: 18767;
- fresh session root: `data/r22-calendar-diagnostic`;
- cooperative wall bound: 15 seconds plus at most 20 seconds cleanup.

## 2. Hard boundaries

| Boundary | Fixed value |
| --- | --- |
| AI physical starts | 0 |
| `trade_cal` physical starts | 1 |
| All other market endpoint starts | 0 |
| In-cycle retries | 0 |
| Delivery channel | IN_APP only |
| Plan/holding mutation | prohibited |
| Webhook, broker, order, trade | prohibited |

One shared fail-stop gate denies later AI or market admission. The attempt journal must be written before any physical start. A calendar or higher reference failure must stop the listener and retain only fixed safe failure enums, counts, and status family without provider content.

## 3. Start gate

The offline preflight at `2026-09-15T11:30:10.312455+08:00` returned `ready=true`. It confirmed the eligible window, free port 18767, ready stock certificate, HTTPS market host, configured direct connection address, present market credential, AI physical cap 0, market total cap 1, and only `trade_cal=1`. It made no network call.

The candidate contract and inherited R14/R20 wiring passed 17 focused offline tests before execution. The one-shot claim did not yet exist at preflight. The live authorization was consumed when the session claim and pre-call journal were created; it cannot be reused.

## 4. Acceptance criteria

A pass requires exactly one `trade_cal` attempt, zero AI and other market attempts, no bounded failure, a usable current-date calendar row persisted in the fresh database, empty isolated business state, normal journal/audit completion, and port release. The pass proves only this invocation's calendar path. It does not prove the larger R19 business loop.
