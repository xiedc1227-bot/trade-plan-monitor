# Specification: market-linkage-p2

Status: IMPLEMENTED AND ACCEPTED — 2026-10-26. The user approved MLP2-D01–MLP2-D06 and ordered all implementation tasks and stage acceptance. Baseline: `8db00c425706945d69a39ae0d3ffe1d85348d626`.
Canonical English · [Chinese review copy](SPEC-market-linkage-p2.zh-CN.md) · [Tasks](../../../tasks/market-linkage-p2.md).

## MLP2-S01 — Sources, objective and interpretation

Compare the original [新提示词.txt](../../../../docs/TradingAgents/reports/新提示词.txt), especially sections II–V and its final “工具衔接”, with the [current reusable prompt](../../../README.zh-CN.md#generic-trade-plan-prompt), approved [P0](SPEC-market-linkage-p0.md) and [P1](SPEC-market-linkage-p1.md). The original is a local workspace input outside this Git repository; retain its exact relevant source excerpts in implementation fixtures. Do not silently replace it with the amended README. The original has four output sections; the current integration format is A/B. This is a deliberate format change, not a missing monitoring capability.

P0/P1 deliver daily market linkage, relative strength, legal market reductions and separately approved exceptions. Proposed P2 adds **explicitly source-defined volatility sizing and pre-buy net-return constraints**, with reviewable evidence and reproducible cost estimates. It does not promise to automate discretionary research. This prioritization is a proposal derived from remaining gaps, not a previously approved P2 scope.

Evidence inspected: `domain/unified_plan_models.py` (registered leaves, fixed quantities, position max_qty, rule validity), `domain/daily_plan_models.py` (ATR14 and dated validity), `domain/market_quantity_rules.py` (official grid), `decision/quantity_policy.py`, `decision/market_exception_policy.py`, `backtest/loop_account.py` and `backtest/execution.py` (existing fee engines), and P0/P1 specifications and verification reports. Paths are relative to `src/trade_plan_monitor/`. Existing calculators are not proof that equivalent constraints can be extracted, reviewed, monitored and enforced in current plans.

## MLP2-S02 — Remaining-capability inventory

“Blocked” means a required unsupported condition must prevent importing/activating that affected trading rule; it must not be removed or replaced with an unauthorized reminder. If A cannot faithfully carry the requested plan, retain the current exact blocked-A behavior.

| ID | Prompt requirement and current coverage | P2 disposition / remaining boundary |
| --- | --- | --- |
| G01 | Current prompt market table: daily regime, 5/20-session strength, S0/S1/S2, normal/weak sizing and both human exceptions are delivered by P0/P1 | Regression baseline, not new scope. Provider/calendar coverage is still conditional. |
| G02 | Original III/V: volatility affects quantity/confirmation. ATR14 is calculable; arbitrary volatility-to-Q0 rules are not executable policies | P2: explicit bounded ATR-ratio sizing table. No automatic formula discovery or arbitrary expressions; unsupported confirmation changes remain blocked. |
| G03 | Original IV/V: round-trip cost, break-even spread, net potential reward and risk. Backtest fee accounting exists; current condition union has no equivalent pre-buy policy | P2: deterministic preview and optional explicitly defined BUY gate. Discretionary “worth trading” without thresholds remains human research. |
| G04 | Original III: two independent dimensions per newly researched level, one structural; MA20/Bollinger middle cannot count twice | P2: structured source/evidence review for new P2 constraints. Record references and manual verification; do not claim automated discovery or proof of price structure. |
| G05 | Original I/V permits monetary caps; current reusable prompt and position model require max_qty | Deferred: invested-budget versus market-value accounting needs a separate contract. Do not divide money by a convenient quote or ignore the monetary cap to import. |
| G06 | Original IV/V actual fills, partial fills, outstanding-order reservations, sellable holdings and account continuity | Explicitly excluded by original “工具衔接”; existing real-holding records do not form a broker ledger. No automatic chat-to-ledger synchronization. |
| G07 | Original V nonuniform lots/odd lots; final tool clause requires whole positive 100-share simulation | Intentional intersection with official grid stays. Non-100 simulation, odd-lot liquidation and ordinary CORE creation require separate approval; incompatible quantities remain blocked. |
| G08 | Original I/III explicit expiry/reassessment after events; dated ordinary validity and reviewed invalidation exist | Calendar-date validity is supported. Automatic announcement/event-relative deadline resolution and automatic equivalent corporate-action risk-line conversion remain deferred/manual. Never extend or drop source deadlines. |
| G09 | Original II/IV fundamental invalidation and announcements | Generation-time human verification is intentional. No automatic “no bad news” conclusion, fundamental trigger or simulation gate; risk decisions remain human. |
| G10 | Original II data provenance, adjustment, latest dates and exchange restrictions | Existing admission checks remain; no blanket certification of BSE, provider fallback, all historical calendars or special statuses. Missing required coverage blocks the affected path. New adapters are deferred. |
| G11 | Original tool clause permits minutes as condition periods; current tool has independent completed-five-minute rules | Daily market-linked five-minute confirmation is still unsupported, but the original ordinary strategy explicitly uses daily closes. Defer a separate temporal contract; do not convert daily signals to intraday signals. |
| G12 | Original III/V price discovery, automatic portfolio split, research Q0 selection, dynamic technical conditions beyond registered leaves | Human research remains. P2 evaluates a reviewed table, not autonomous portfolio construction. Fixed/scoped human technical facts remain supported; unsupported mandatory leaves still block. |
| G13 | Original output, cost input and source consistency; current A/B extraction deliberately excludes B from executable input | P2 places executable policies in A with source bindings; B remains explanation. Original account cost, general prose and exception “approval” in B cannot acquire authority. |
| G14 | Original IV same-signal accounting and re-evaluation | Existing whole-simulation independent-signal lifecycle is retained. Partial actual execution is outside the tool; P2 neither restores consumed quantities nor resets signals after a tier change. |

Existing scoped reviewed facts include TRADE_VIABILITY: a human viability judgment is already representable within its accepted scope. G03 concerns native numerical calculation and enforcement, not the absence of all human viability support.

These are different classes: missing executable policy (G02/G03), partially supported research/evidence (G04/G08/G10/G12/G13), intentional human/product boundaries (G06/G07/G09), and separately scoped extensions (G05/G11). P2 completion does not mean every original research request is automated.

## MLP2-S03 — Six approved decisions

| ID | Approved decision | Reason |
| --- | --- | --- |
| MLP2-D01 | Scope P2 to daily TACTICAL BUY, source-defined ATR-ratio sizing, cost/reward preview and opt-in numeric net-return gates; retain all G05–G12 boundaries | Deliver a finite, testable next step without inventing broker or discretionary authority. |
| MLP2-D02 | First derive Q0 from a source-reviewed base and volatility tier; then apply the unchanged P0/P1 market policy. No upward sizing or automatic threshold selection | Volatility and market reductions must not be confused, doubled or reversed. |
| MLP2-D03 | Cost assumptions are explicit, versioned and time-bounded. No default net-profit/risk-reward veto; numeric gates require explicit source authorization | The original forbids universal invented profitability thresholds; estimates are not actual fills. |
| MLP2-D04 | Freeze sizing evidence/Q0 at confirmation; recheck cost gate at execution against current admissible quote using the same reviewed policy. Risk exits bypass cost gates | Avoid automatic resizing and prevent a stale favorable entry price from authorizing a bad entry. |
| MLP2-D05 | Opt-in Schema 8 / condition-plan-v4, with pretrade-policy-v1; preserve Schema 1–7 serialization and authority. Carry source bindings and evidence in existing /plans flow | New executable semantics need explicit versioning. Schema 8 is explicitly opt-in; earlier readers must reject it. |
| MLP2-D06 | Share pure policies across runtime and frozen replay; retain explicit per-occurrence P1 approval and separate whole simulation. Missing mandatory evidence fails closed | Prevent approval shortcuts and hindsight; research attachments cannot authorize trades. |

These six decisions and implementation are approved. No source-defined thresholds can be supplied merely by approving this generic specification.

## MLP2-S04 — Modules and contracts

| Module ID | Responsibility | Dependencies |
| --- | --- | --- |
| p2-source-policy | Strict policy contract, source bindings and evidence review | Existing extraction, codec and review |
| p2-volatility-sizing | Exact ATR14/close ratio and legal Q0 selection | p2-source-policy, existing daily indicators and grid |
| p2-trade-economics | Versioned fee assumptions, preview and source-defined numeric gates | p2-source-policy, existing arithmetic semantics |
| p2-pretrade-workflow | Freeze/revalidate, transaction guards, UI and frozen replay | All three modules, P0/P1 lifecycle |

Schema 8 extends the Schema 7 daily plan contract, retaining market-linkage-v2 and explicit exception route flags. P2 BUY policies require daily confirmation and existing market_policy. Ordinary SELL, risk and alerts keep existing behavior. Policies without P2 fields continue to use their existing schema; no automatic migration or new default fields in historical hashes.

Each eligible BUY has `pretrade_policy`: `policy_version=pretrade-policy-v1`, `sizing` (FIXED_Q0 or ATR_RATIO_TIERS), and `economics` (NONE, PREVIEW_ONLY or REQUIRED). Fixed sizing references the existing Q0; tier sizing supplies `base_qty` plus `tiers`. Mixed fixed Q0 and tier-derived Q0 input is rejected. A version-specific adapter supplies derived Q0 to the shared market policy, never mutates a persisted old plan. Source bindings cover every tier, threshold, quantity, price assumption, cost component and gate. A preset name alone is insufficient.

For ATR_RATIO_TIERS: `metric=ATR14_OVER_CLOSE`; 1–10 ordered bands with Decimal-string lower-inclusive/upper-exclusive bounds; coverage starts at 0, ends with upper=null, without gaps/overlaps. Each band carries `multiplier` in [0,1]. Multipliers are nonincreasing. Only one band matches. No script/eval, alternate indicator, automatic ATR stops or automatic confirmation tightening. Quantities remain positive 100-share multiples bounded by 9007199254740991; a computed no-buy result is not a zero-quantity order.

Economics carries `entry_price_mode=CONFIRMED_CLOSE_THEN_EXECUTION_QUOTE`, fixed source-reviewed `target_price_fen`, `risk_price_fen`, a frozen `fee_schedule` and `gates`. Target and risk must bind to the reviewed pressure/risk references; require 0 < risk < entry < target for a computable preview. No cost-basis-derived target. Dynamic targets/risk references are outside this first policy version. REQUIRED must have at least one explicit gate: `min_net_reward_fen` (integer >=0) and/or `min_reward_risk_ratio` (positive Decimal). Both supplied gates use ALL with >=. PREVIEW_ONLY has no veto or gates; NONE has no estimate. Missing a necessary source threshold blocks REQUIRED import, not an unrelated reminder.

A fee_schedule records schedule_id/version, currency=CNY, market/security applicability, effective_from/through, provenance, commission rate/minimum, buy/sell tax/transfer/handling components and per-share buy/sell slippage in integer fen. Each rate component declares whether separately charged or included in another component; duplicate or cyclic inclusion is invalid. No negative values, unknown silently zero, or assumed universal tax rate. Validate applicability at decision/execution dates. Source-linked, reviewed estimates may be used but are visibly ESTIMATE. Do not introduce a new manual exchange-lot proof workflow.

Keep new exact DTOs in a paired contract appendix during T01 before implementation. Use existing strict immutable Pydantic/Decimal patterns, Python 3.14, FastAPI/SQLite and Vue/TypeScript; no new dependency is proposed.

## MLP2-S05 — Quantity, economics and timing

For official completed session D, r=ATR14(D)/close(D) on the same admitted QFQ basis. Use the existing Wilder formula/warm-up contract, not an independently seeded ATR. Missing/incomparable data produces UNKNOWN, not r=0. No floating-point comparisons.

Let L be the existing official-buy grid intersected with positive 100-share simulation quantities. For matching multiplier v, Q0=max{q in L | q <= base_qty*v}. An empty set blocks as VOLATILITY_BELOW_MINIMUM. In particular, this is **not** the weak-market minimum exception. Base_qty is source-defined before any market calculation and cannot be raised to compensate for reductions.

Pass this Q0 through unchanged P0/P1 selection. NORMAL uses Q0; WEAK chooses max{q in L | q<=0.5*Q0}; its below-minimum result may enter WEAK_MINIMUM only under the existing STRONG/S1/explicit-approval rules and 0.5*Q0 < m <= Q0. BROKEN_STRONG still requires STRONG/S2 and manually entered legal Qe<=Q0. Capacity checks block whole quantities. P2 never auto-fills Qe.

Compute economics at the selected full candidate quantity; eligibility preview is not execution authority. For an exception, recompute at the exact entered quantity before approval and again at execution; minimum commissions make per-share scaling invalid. Do not shrink quantities until a gate passes.

For quantity q, quote entry e, target t, risk z and per-share slippage sb/ss:
- entry debit B=q*(e+sb)+buy_fees(q*(e+sb)).
- target proceeds T=q*(t-ss)-sell_fees(q*(t-ss)).
- risk proceeds Z=q*(z-ss)-sell_fees(q*(z-ss)).
- net reward=T-B; planned loss=B-Z; reward/risk=(T-B)/(B-Z), only if planned loss>0.
- estimated round-trip cost=buy_fees+target_sell_fees+q*(sb+ss); break-even spread=that cost/q. This is a scenario estimate, not an exact solved future sale price.

Reject nonpositive slippage-adjusted prices and overflow; use integer fen totals and exact Decimal/rational comparisons. Each separately charged proportional fee rounds upward to whole fen, then commission takes its declared minimum, consistently with existing engines. Included handling fees are not added again. Do not silently change old backtest accounting. REQUIRED unknown inputs or failed gates block ordinary buying; PREVIEW_ONLY displays UNKNOWN without becoming a hidden gate. No account cash query or actual P&L inference.

Freeze session, source bindings, metric/tier/base_qty/Q0, route, grid and authority with the signal. Evidence/policy corrections invalidate affected pending authority under P0/P1 rules; equivalent decimal formatting and refetch timestamps do not. A later volatility tier does not resize an existing signal or create a new one. Next-session expiry and independent-reset rules remain unchanged.

At execution revalidate admission, risk, capacity, P1 approval where applicable, original window and current economics. A changed quote may make a gate fail and later recover within the original window, but never enlarges authority. A changed fee schedule or reviewed target/risk invalidates pending authority rather than silently switching assumptions. Approval-time preview and execution-time preview are separately retained. Every technical risk exit bypasses economics; no cost-based delay or new fundamental gate.

## MLP2-S06 — Review, persistence, API and replay

Review presents original clauses, derived fields and verification status separately. For price levels used by P2, record at least two distinct evidence dimensions, including one price-structure dimension; MA20 and Bollinger middle share one dimension. Record source identifier, excerpt, source date/time or explicit unknown, observation cutoff and human reviewer decision. Human review attests judgment; no automated claim that two references prove a price is correct. Missing required evidence prevents P2 review approval. Previously reviewed plans do not acquire this new requirement retroactively.

A contains executable policy definitions; B contains explanations and optional account facts. Extraction never treats B as policy, a fee default as broker fact, or a source sentence as P1 approval. Missing required definitions produces scoped errors and preserves the existing blocked-A contract. No lowering to Schema 7 to strip P2 constraints.

Proposed POST `/api/v1/plan-economics-previews` is read-only: request identifies reviewed plan/version, rule, occurrence when available and optional proposed P1 quantity. Server loads authority and admitted prices; caller-supplied quotes cannot authorize execution. Response includes plan/evidence hashes, computed_at, candidate quantity, metric/tier/Q0, estimate components, gate outcomes and reasons. It neither approves, activates, simulates nor creates candidates. Existing runtime and exception-preview responses expose the same policy result; simulation recomputes under its current transaction/concurrency guard and never trusts a preview token alone.

Persist versioned frozen policy/evidence with existing signal/exception authority, using an additive migration if needed. Migration acceptance uses temporary databases only; readers that cannot understand Schema 8 fail closed. Rollback preserves new records and blocks Schema 8 activation rather than rewriting as Schema 7. Technical hashes include consumed inputs, not receipt timestamps.

Replay receives frozen fee schedules, source evidence, prices and exception events with availability times. No current network schedule or local approval lookup. Missing history blocks the relevant decision; future corrections/events cannot change earlier outputs. Actual holdings, simulation and replay accounts remain isolated. Notification payloads disclose estimate versus gate and never imply an approval or trade; send-time revalidation suppresses stale actionable messages.

## MLP2-S07 — Acceptance criteria

| ID | Required evidence |
| --- | --- |
| MLP2-A01 | G01–G14 trace to prompt/source and supported/manual/blocked/deferred outcomes; paired docs agree. |
| MLP2-A02 | Schema 8 strict round trips and source review; historical 1–7 bytes/hashes unchanged; unsupported readers fail closed. |
| MLP2-A03 | Tier boundaries, missing ATR, source corrections, grid floor and empty-set cases use independent expected values. |
| MLP2-A04 | Base 1000, v=0.5, main-board L: Q0=500, WEAK=200. Base 100,v=0.5: blocked before exceptions. Base 200,v=0.5: Q0=100, WEAK_MINIMUM may request exactly100, subject to P1. |
| MLP2-A05 | Synthetic fees: q=100,e=1000,t=1100,z=950,sb=ss=0, commission rate=0/minimum=500fen each side, all other components explicitly0: B=100500,T=109500,Z=94500,reward=9000,loss=6000,ratio=1.5,cost=1000,spread=10fen. These are test assumptions, not market rates. |
| MLP2-A06 | Minimum fees, included handling, per-side fees, fractional rates, rounding, expiry, overflow and invalid prices tested; gate equality passes; absent gates never invent thresholds. |
| MLP2-A07 | Both P1 routes preserve separate approval, exact quantities, one consumption, original expiry and revoked/invalidated behavior; economics never approves or resizes. |
| MLP2-A08 | Execution quote can fail then recover a gate only within original window; changed reviewed assumptions invalidate; risk exits bypass economics. |
| MLP2-A09 | API authorization/admission, stale preview, concurrent requests, restart and atomic failure leave no extra fill or inventory mutation. |
| MLP2-A10 | Frozen runtime/replay parity and future-data mutations; old backtest fee results unchanged. |
| MLP2-A11 | Browser journeys cover evidence review, missing source, tier explanation, PREVIEW_ONLY, REQUIRED failure, P1 exact-quantity preview and separate simulation. |
| MLP2-A12 | Full non-live backend, frontend, type/build/generated contracts, lint and bilingual verification pass; record failures and reruns honestly. |

## MLP2-S08 — Delivery and approval boundary

Follow [MLP2-T01–MLP2-T18](../../../tasks/market-linkage-p2.md) and six checkpoints. Implementation and local verification are authorized; user-database mutation, live provider calls, deployment and push remain outside scope. Use official sources to validate any production fee data added; this spec intentionally does not certify current fee rates. Tasks may not weaken existing quality gates.

The six decisions above, especially dynamic Q0 before market reduction, opt-in numeric BUY gates and the proposed scope deferrals, are approved. A requirement beyond this bounded policy language remains blocked until a separately reviewed extension.


Implementation acceptance: [2026-10-26 report](../../verification/2026-10-26-market-linkage-p2.md), MLP2-A01–MLP2-A12 PASS.
