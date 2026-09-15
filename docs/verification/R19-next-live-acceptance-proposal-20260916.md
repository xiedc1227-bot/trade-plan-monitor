# R19 next bounded live-acceptance proposal — not authorized

Canonical English; `R19-next-live-acceptance-proposal-20260916.zh-CN.md` is the equivalent Chinese review copy. Proposal ID `R19-20260916-A-105`; proposed run ID `r19-20260916-a`. Status **PROPOSED / NOT_AUTHORIZED / NOT_RUN / ZERO_EXTERNAL_CALLS**.

## Candidate and admission

- Candidate date: **2026-09-16**. Admission gate: **09:30:00–09:45:00 Asia/Shanghai inclusive**. This wider early-morning gate avoids another one-minute miss. A start at the upper bound stops new calls by 10:23, within the morning session if the exchange is open.
- Before claiming the run, require current AI balance/price/route acknowledgement, exact configuration/model/source hashes, loopback port availability and local certificate validation. After the claim but before paid AI or any other market endpoint, perform one budgeted `trade_cal` open-day check. Any failed or uncertain prerequisite consumes and ends this candidate with no replacement or retry.
- Current local metadata, inspected offline on 2026-09-15 10:14, records stock validity through `2026-09-16T14:48:40.405317+08:00` and five-index validity through `2026-09-18T10:20:44.522358+08:00`. This is not entitlement, quota or open-day proof; both files must still pass validation at admission.
- Use a new isolated root `data/r19-acceptance/r19-20260916-a/`, new SQLite databases and loopback port `18766`. Never read, delete, rename or reuse R14/R17/R18 claims, run folders, authorization strings or databases.

## Exact bounded work

- AI: at most **3 physical POST starts**, zero provider retries, one exact attempt each in order: `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01`. Use configured alias `deepseek-v4-pro`, `plan-extract-v5`, `thinking=disabled`, `response_format=json_object`, `temperature=0`, explicit `max_tokens=8192`, and the three already frozen source hashes. A literal failure stops immediately; no semantic request is sent and no source is resubmitted.
- Official DeepSeek notice says `deepseek-v4-pro` routes to V4.1-Flash starting 2026-09-14 04:00 UTC until V4.1-Pro launches. The candidate must record both requested and returned model identities and cannot claim the same underlying model as R18: https://api-docs.deepseek.com/news/news260910/
- Market data: at most **105 physical starts** across `trade_cal=3`, `rt_min_daily=2`, `rt_min=40`, `idx_mins=5`, `rt_idx_min_daily=50`, `index_daily=5`; all other endpoints have cap zero. Failed requests consume budget. One shared pre-call lock enforces total/per-endpoint/deadline limits and stops the service before any denied network call.
- Wall boundary: **2,280 seconds for new calls plus 20 seconds cooperative cleanup**. No automation or unattended scheduling. The user must explicitly authorize and manually start this exact candidate inside its gate.

## Business oracle and stops

1. `LITERAL` must return `SUCCEEDED` with all 15 source clauses and a reviewable mapping, then pass current-content human review, immutable save and explicit activation. Any truncation, invalid output, provider error, mapping mismatch, missing clause/value/boundary/logical relationship/timeframe/quantity, unresolved blocker, save/review/activation failure, or model mismatch stops the run.
2. `SEM-AMB-01` and `SEM-UNS-01` must preserve the specified ambiguity/unsupported material as activation blockers and must not activate. Any invented executable meaning stops the run.
3. Only the literal plan may monitor one isolated symbol. Require six completed five-minute bars before evaluating the five-bar mean rule. Natural market prices may produce no trigger; then BUY/SELL/RISK remain **NOT_OBSERVED**, never fabricated or waived.
4. Accept only IN_APP delivery. No webhook or broker/trade call is configured or allowed. Query recovery may issue additional GETs only; it may never submit another AI POST. On any uncertain receipt, stop local waiting, preserve the operation ID and recover by GET.
5. On every failure, deactivate the isolated plan if necessary, stop the service, close clients and write a redacted audit. Do not expose source text, raw provider content, exception text, credentials or authorization headers.

## Cost uncertainty and authority

This proposal grants no spending authority. Current official pricing is token-based and changeable; the configured alias is presently documented as routing at V4.1-Flash rates. Using the higher currently listed V4-Pro input/output rates as a conservative arithmetic ceiling, three requests of approximately 5,100 input tokens and the full 8,192 output-token cap would be under USD 0.03 before taxes or account-specific adjustments. Actual prompt sizes, cache status, output length, routing, peak/off-peak period, currency conversion, market-data charging and account balance are unknown until preflight. Recheck official pricing immediately before asking for approval: https://api-docs.deepseek.com/quick_start/pricing

Execution requires a new explicit user approval covering proposal ID, date/window, up to 3 paid AI starts, up to 105 market-data starts, possible charges and the 38-minute boundary. Nothing in R14, R17, R18 or this R19 offline remediation supplies that approval.
