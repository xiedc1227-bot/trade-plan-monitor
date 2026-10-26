# Operations: market-linkage-p2

[Chinese review copy](market-linkage-p2.zh-CN.md) · [specification](../specifications/monitoring/SPEC-market-linkage-p2.md) · [acceptance evidence](../verification/2026-10-26-market-linkage-p2.md).

## MLP2-O01 — Prepare and review

Use `/plans` and `plan-extract-v11`. Copy only A from the trading prompt. A must explicitly define Schema 8 / condition-plan-v4, the complete P1 market policy, `pretrade-policy-v1`, sizing and economics. B is research explanation and grants no execution authority. The original-source inventory G01–G14 remains in the specification.

For `ATR_RATIO_TIERS`, supply `base_qty`, `metric=ATR14_OVER_CLOSE` and 1–10 contiguous `[lower, upper)` tiers covering zero to infinity (`upper=null` for the last tier). Multipliers must be nonincreasing, between 0 and 1. Decimal values are strings. `quantity_policy.mode=DERIVED_MARKET_FACTOR` has no `base_quantity`; `FIXED_Q0` uses the existing `MARKET_FACTOR` quantity policy. Mixing them blocks review.

Missing candidate values remain null and block executable review. The server never invents quantities, tiers, zero fees, validity dates, numeric profitability thresholds or BROKEN_STRONG quantities. Human supplements use the existing explicit source-bound review workflow. Changing source or policy requires a new exact-content review.

`NONE` has no fee fields. `PREVIEW_ONLY` displays estimates without vetoing a trade. `REQUIRED` adds at least one explicit non-null gate, combined with ALL and inclusive `>=` comparisons. Both estimation modes require exact covered securities, schedule ID/version, effective dates, source excerpt, commission/minimum commission, fee components/inclusion relationships and per-share slippage. `classification=ESTIMATE` never certifies current exchange or broker rates. No production fee schedule is supplied by P2.

The explicit target must fall inside the reviewed pressure range, respecting its inclusive/exclusive endpoints; the risk price must equal the reviewed risk line. Each PRESSURE/RISK level needs PRICE_STRUCTURE and another independent dimension; MA20 and BOLL_MIDDLE both count as TREND. This checks source completeness, not whether a discretionary price level is economically correct.

## MLP2-O02 — Quantity, estimates and execution

At the official daily confirmation, use admitted `daily-ta-v2` ATR14 and the same adjusted close. First derive Q0 by flooring `base_qty * multiplier` to the official grid intersected with the 100-share simulation grid, then apply the existing market factor. Base1000 ×0.5 gives Q0=500; ordinary WEAK authorizes200. Base100 ×0.5 produces no legal Q0 and cannot fall back to an exception. Base200 ×0.5 gives Q0=100; WEAK_MINIMUM may request exactly100 when its P1 conditions hold.

Confirmation freezes Q0 and policy evidence. Subsequent quotes recalculate economics for the same exact quantity; they do not resize it. REQUIRED failures block BUY; recovery can restore eligibility only within the original execution window. Changed reviewed assumptions invalidate the old authority. Risk exits bypass BUY economics. Actual fills/cash and research estimates remain separate.

Each fee component rounds upward to integer fen; commission takes its explicit minimum, included fees are not charged twice. With q shares, entry e, target t, risk z, slippage sb/ss: `B=q*(e+sb)+buy_fees`, `T=q*(t-ss)-target_fees`, `Z=q*(z-ss)-risk_fees`, reward=`T-B`, loss=`B-Z`. Gate ratios use exact fractions. Total round-trip cost includes entry/target fees and slippage; spread is cost/q. Invalid prices, expired schedules or unavailable required inputs yield UNKNOWN; only REQUIRED turns that into a veto.

WEAK_MINIMUM retains its exact compatible minimum. BROKEN_STRONG starts with an empty human quantity field; enter a legal whole Qe no greater than Q0 and current capacity. Read the estimate, explicitly approve this occurrence, then separately confirm the whole simulation. Approval and preview never change inventory. One consumption, revocation, original expiry and correction invalidation remain enforced; partial simulation is unsupported.

## MLP2-O03 — Read-only API and notifications

`POST /api/v1/plan-economics-previews` accepts `planVersionId`, `ruleId`, optional `occurrenceId` and `proposedQuantity`. `occurrenceId` is the server's exception `candidate_id`, not a signal ID or ordinal; required when previewing an exception. Only BROKEN_STRONG accepts a proposed quantity; other quantities come from server evidence. Client quotes, fees or approvals are rejected. The endpoint uses the existing local API admission and does not write a preview, candidate, approval or trade.

The response contains `computedAt`, `planVersionId`, `ruleId`, `quantity`, `evidence` (`p2-pretrade-evidence-v1`), `economics` (`p2-economics-v1`) and `authorityGranted=false`. Missing/currently stale or mismatched evidence returns409; invalid request fields return422. Refresh runtime after source, activation, position or market evidence changes. A successful estimate is not an approval token; simulation revalidates in its own guarded transaction.

The UI shows frozen sizing, current estimates, fee components and gate blockers. It discards late preview responses after the current context changes. Notifications identify the applicable rule's fee mode and the separate approval/execution requirement. Send-time checks suppress stale actionable messages.

## MLP2-O04 — Frozen research and compatibility

Schema 8 research uses `backtest-run-v9`, frozen plans/fee schedules and explicit exception events plus separate simulation operations. Source provenance distinguishes RECORDED_LOCAL from RESEARCH_SCENARIO. The same policies and runtime services run in private temporary state; current provider schedules or local approvals are never fetched. Receipt/availability boundaries prevent future evidence from authorizing earlier decisions. P2 signal reports retain sizing evidence and resolve shared linkage and pretrade references, then validate the complete signal before admission; the existing compact Schema 7 representation is unchanged.

Review content uses `plan-review-content-v5`; consumed continuity uses `p2-consumed-v1`. Schema 1–7 documents, hashes and authority retain their previous representation. Storage adds optional versioned JSON fields; no SQL schema migration or historical rewrite is needed. Back up before an operational downgrade: older readers must refuse Schema 8 execution, while the original records remain intact. Do not relabel Schema 8 as Schema 7 to force compatibility.

## MLP2-O05 — Limits and local verification

Monetary caps, automatic portfolio construction, broker orders/partial fills, non-100-share simulation, event-relative deadline discovery, automated fundamentals/announcements, unverified market/provider coverage and daily-linked five-minute confirmation remain outside P2. Mandatory unsupported source constraints block import; they cannot be dropped or replaced with a convenient default. Human technical facts remain limited to their existing scope.

Use the [task checks V01–V08](../../tasks/market-linkage-p2.md) and the actual acceptance report. Backend directories run in separate processes because existing unit/integration files share a module basename; only live tests are excluded. Local evidence uses synthetic prices and fees and disposable databases. It does not certify live data availability, current fee rates, real fills or deployment.
