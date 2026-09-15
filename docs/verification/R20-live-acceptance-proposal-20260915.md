# R20 same-morning bounded live-acceptance plan

Canonical English; `R20-live-acceptance-proposal-20260915.zh-CN.md` is the equivalent Chinese review copy. Proposal ID `R20-20260915-A-105`; run ID `r20-20260915-a`. Final status **AUTHORIZED / CONSUMED / STOPPED_AT_OPEN-DAY_GATE**.

## Admission and isolation

- Candidate date: **2026-09-15**. Admission gate: **10:35:00–10:50:00 Asia/Shanghai inclusive**. New calls were limited to 2,280 seconds plus 20 seconds cooperative cleanup and therefore could not extend past 11:30.
- The one-shot root was `data/r20-acceptance/`, with a new claim, isolated SQLite database and loopback port `18766`. R14/R17/R18 claims, authorization strings and databases were not reused or modified.
- The session defaulted to no-network dry-run. Execution required the exact R20 authorization and run ID. The stock and five-index certificates, selected model, endpoint hosts, source hashes, port and time gate were validated without exposing credentials. AI balance remained `UNKNOWN_NOT_PROBED`; no recharge or auxiliary paid probe was allowed.

## Bounded work and stop rules

- AI allowed at most three zero-retry POST starts, in order `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01`, with one attempt per frozen source. The physical request contract was `deepseek-v4-pro`, `plan-extract-v5`, `temperature=0`, `thinking={"type":"disabled"}`, JSON object output and explicit `max_tokens=8192`. A literal failure or returned-model mismatch stopped all later calls.
- Market data allowed at most 105 physical starts: `trade_cal=3`, `rt_min_daily=2`, `rt_min=40`, `idx_mins=5`, `rt_idx_min_daily=50`, `index_daily=5`; every other endpoint had cap zero. Failed starts consumed budget.
- One budgeted `trade_cal` check had to establish the current open day and reference-data health before any AI POST or other market request. Failure or uncertainty ended the run with no retry or replacement.
- Only a source-faithful literal result could proceed through the normal browser review, immutable save, explicit activation, production recovery and isolated monitoring path. Semantic ambiguity/unsupported cases could never activate. Only IN_APP delivery was allowed; webhook, broker, order and real holding changes were prohibited.

## Cost correction

At the official peak V4-Pro rates checked immediately before authorization—USD 1.32 per million cache-miss input tokens and USD 3.96 per million output tokens—three requests of about 5,100 input tokens plus the full 8,192 output-token cap estimate to **USD 0.117523 (about USD 0.12)**. This is an estimate, not a guaranteed monetary cap, and excludes tax, market-data charging, actual token size and account-specific adjustments. The older USD 0.03 arithmetic must not be reused. The pricing page and the earlier routing notice conflict about post-September-14 Pro service; R20 therefore required both requested and returned model metadata and would stop on mismatch without changing models.

## Outcome

The session was claimed at `2026-09-15T10:40:25.420+08:00`. Its first and only external start was the budgeted `trade_cal` request, which failed with sanitized code `REFERENCE_TRANSIENT`. The mandatory stop rule ended the candidate before AI or any other market call. Exact results are in `R20-live-acceptance-execution-20260915.md`.
