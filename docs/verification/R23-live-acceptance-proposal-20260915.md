# R23 afternoon bounded live-acceptance plan

Canonical English; `R23-live-acceptance-proposal-20260915.zh-CN.md` is the equivalent Chinese review copy. Proposal ID `R23-20260915-PM-105`; run ID `r23-20260915-a`. Status **REFERENCE_FAILED / AUTHORIZATION_CONSUMED / CLOSED / FULL_WORKFLOW_NOT_PROVEN**.

## Execution disposition

R23 executed on 2026-09-15 from `12:51:26.061589+08:00` to `12:51:26.553170+08:00`. The first `trade_cal` failed with `REFERENCE_TIMEOUT / TRANSPORT_TIMEOUT`; market starts were 1/105 and AI starts 0/3. Normal audit completed, isolated-plan cleanup was `INACTIVE`, and the one-shot claim remains present. The remaining sections preserve the historical candidate contract; they do not authorize another start. See [execution record](R23-live-acceptance-execution-20260915.md) and [handoff](../../remediation/handoffs/R23.md).

## Admission and isolation

- Candidate date: **2026-09-15**. Admission gate: **12:50:00–13:05:00 Asia/Shanghai inclusive**. A start at the upper bound stops new calls by 13:43, within the afternoon continuous auction.
- The one-shot root is `data/r23-acceptance/`, with a fresh claim, isolated SQLite database and loopback port 18768. No earlier claim, authorization, database, or evidence may be reused or changed.
- Default invocation is no-network dry-run. Execution requires the exact R23 authorization and run ID. Preflight must validate stock and all-five-index certificates, selected model, endpoint hosts, frozen source hashes, port, configuration, and time gate without exposing credentials. AI balance remains `UNKNOWN_NOT_PROBED`; no balance/model-list probe or recharge is authorized.
- The user's instruction `继续下一步`, following the R22 handoff, authorizes this candidate's bounded external calls and possible charges. It does not authorize webhook, broker, order, trade, or real plan/holding mutation.

## Bounded work and stop rules

- AI allows at most three zero-retry POST starts in order `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01`, one attempt per frozen source. The request contract is configured alias `deepseek-v4-pro`, `plan-extract-v5`, `temperature=0`, `thinking={"type":"disabled"}`, JSON object output, and explicit `max_tokens=8192`. A literal failure, returned-model mismatch, or uncertain receipt stops all later calls.
- Market data allows at most 105 physical starts: `trade_cal=3`, `rt_min_daily=2`, `rt_min=40`, `idx_mins=5`, `rt_idx_min_daily=50`, `index_daily=5`; every other endpoint has cap zero. Failed starts consume budget.
- One budgeted `trade_cal` request must establish current open-day and reference health before any AI POST or other market request. Failure or uncertainty ends the candidate without retry or replacement.
- The service has 2,280 seconds for new calls plus at most 20 seconds cooperative cleanup. First calendar/reference failure stops shared AI/market admission and writes the pre-call journal and final audit.

## Business oracle

1. `LITERAL` must return `SUCCEEDED` with all 15 source clauses and a reviewable mapping. Current-content human review, immutable save, and explicit activation are mandatory. Automation cannot replace the review decision.
2. `SEM-AMB-01` and `SEM-UNS-01` must preserve ambiguity/unsupported content as activation blockers and must never activate. Invented executable meaning stops the run.
3. Only the literal plan may monitor isolated symbol `003043.SZ`. Evaluation requires six completed five-minute bars for the five-bar mean rule. Natural prices may produce no BUY/SELL/RISK trigger; such outcomes remain `NOT_OBSERVED` and are never fabricated.
4. Delivery is IN_APP only. Query recovery may use GET only and may not resubmit an AI POST. Webhook, broker, order, trade, and real holdings are prohibited.
5. Every failure stops new work, deactivates any isolated plan, closes the listener, and records redacted evidence. Source text, raw provider content, exception text, credentials, and authorization headers are not retained in the audit.

## Route and cost acknowledgement

The original proposal assumed that `deepseek-v4-pro` would route to V4.1 Flash at off-peak rates and recorded a three-request estimate of **USD 0.017041**, alongside V4-Pro peak-rate arithmetic of **USD 0.117523**. The handoff reports conflicting official pricing and announcement information; these historical assumptions are not a verified current route, price, or spending ceiling. This closeout does not recheck external pricing. Before any new live proposal, verify the current official route and prices, disclose assumptions and unknown market-data fees/taxes, and obtain authorization for that specific candidate. R23 made zero AI starts, so it produced no returned-model or AI-billing evidence; market charges remain unknown.

Official pages referenced by the historical proposal, to recheck for a future candidate:

- https://api-docs.deepseek.com/quick_start/pricing/
- https://api-docs.deepseek.com/news/news260910/

## Start condition

The candidate contract must pass focused offline tests and be committed before the gate. Immediately before execution, rerun dry preflight and verify a clean worktree, valid certificates, free port, absent R23 claim, and user availability for the mandatory review. No automation or unattended scheduling is authorized. Missing the gate consumes no external calls and requires a new proposal; entering the gate and creating the claim consumes this authorization.
