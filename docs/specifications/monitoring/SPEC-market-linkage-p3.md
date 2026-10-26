# Specification: market-linkage-p3

Status: IMPLEMENTED AND ACCEPTED — 2026-10-26. The user approved MLP3-D01–MLP3-D06 and ordered all tasks and stage acceptance. Baseline: `c9ad16aa352d9bdb5ec49f16cd9fcd90151f9c46` (P0/P1/P2 completed). MLP3-T01–T24 and C01–C08 are complete; actual tests and boundaries are recorded in the task pair and verification report.

Canonical English · [Chinese review copy](SPEC-market-linkage-p3.zh-CN.md) · [Implementation plan and tasks](../../../tasks/market-linkage-p3.md).

## MLP3-S01 — Sources, baseline findings and delivered objective

Compare the original [新提示词.txt](../../../../docs/TradingAgents/reports/新提示词.txt), the maintained [integration prompt](../../../README.zh-CN.md#generic-trade-plan-prompt), accepted [P0](SPEC-market-linkage-p0.md), [P1](SPEC-market-linkage-p1.md), [P2](SPEC-market-linkage-p2.md) and [P2 verification](../../verification/2026-10-26-market-linkage-p2.md). The original is outside this Git repository; normalized UTF-8 SHA-256 is `f17e12b88f4c12d7af7b67caabede2e9d7c2712142a64e67a212c7621865f731`. Do not replace it with the amended README when assessing gaps.

Critical original clauses (line numbers are navigation aids; excerpts and hash are authoritative):

- Line 8: “最大计划持仓：【优先填写股数；填写金额须注明是总投入预算还是持仓市值上限】”.
- Line 13: “以金额给出的计划上限仍须遵守，含义或核算所需记录不清时，不推算确定额度。” It also explicitly excludes an available-cash prerequisite.
- Line 104: “最大计划持仓是上限，不是必须买满的目标。”
- Line 154: “真实成交、委托占额及部分成交仍在本会话/实际交易管理中按原文处理，工具不跟踪。”
- Line 155: “每次工具模拟须由我显式确认，一次完整应用正数100股整数倍数量，与真实持仓分开”.

Inspected P0/P1/P2 baseline: `domain/unified_plan_models.py::UnifiedPositionPolicy` requires `max_qty`; `decision/quantity_policy.py` and `decision/unified_lifecycle.py` enforce whole-quantity share capacity. `state/daily_accounting.py` persists isolated simulation batches, acquisition dates and quantities, but no purchase cost. `backtest/loop_account.py` has a separate research cost/cash ledger; it is not a current-runtime capital-limit policy. P2 fee estimates are not a persistent holdings-cost book. Paths are relative to `src/trade_plan_monitor/`.

Delivered P3 objective: enforce a source-defined **per-symbol monetary position limit** for the existing daily linked TACTICAL BUY workflow, including both P1 exception routes and P2 sizing/economics. Support an amount-only limit as well as simultaneous share/amount limits without inventing a maximum share count. Provide an explicitly reviewed simulation budget basis where needed. Actual account management remains outside the tool.

## MLP3-S02 — Remaining capabilities after P0/P1/P2

Preserve G01–G14 from P2 as trace IDs; this table supersedes their *remaining-work assessment*, not accepted behavior. Unsupported mandatory constraints block the affected executable rule; if A cannot faithfully express the plan, preserve the existing exact blocked-A response. Do not drop constraints or create an unauthorized reminder.

| ID | Delivered / still missing | Proposed disposition and priority |
| --- | --- | --- |
| G01 | P0 daily regime, aligned 5/20-session strength, S0/S1/S2 and legal reductions; P1 both explicit exceptions | Regression baseline. Data admission and calendar limits still apply. |
| G02 | P2 source-defined ATR14/close tiers derive Q0; arbitrary volatility-driven confirmation changes and formulas remain unsupported | Follow-up candidate: a separately reviewed confirmation policy. Keep unsupported mandatory changes blocked; do not claim P3 adds them. |
| G03 | P2 exact fee/net-reward/risk estimates and optional explicit BUY gates | Discretionary viability, automatic official-fee updates, broker-tariff discovery and reusable fee-catalog management remain manual/deferred. P3 reuses explicit fee arithmetic, not a fee-data service. |
| G04 | P2 source/evidence checks for its pressure/risk references; existing scoped human technical facts | Automatic discovery of all three levels, proof of independent evidence and automatic validation of every ordinary structure/volume/indicator combination remain research/review responsibilities. MA20/BOLL_MIDDLE are one dimension. |
| G05 | P3 delivered amount-only/combined limits and an isolated simulation budget book | **P3 delivered, tool-simulation scope:** explicit open-cost or market-value cap, amount-only or share-and-amount policy, continuous isolated budget basis, atomic revalidation. Actual-account compliance remains manual under G06. |
| G06 | Actual trades, partial fills, outstanding-order reservations and chat-derived real-account continuity | Intentional original tool exclusion, not a P3 defect. No broker ledger, reservation or automatic actual-position update. |
| G07 | Official buy grid intersected with whole positive 100-share simulation | Intentional tool boundary. Non-100 execution, odd-lot liquidation and ordinary CORE creation need a separate product decision. Never alter actual trade quantities to make them fit. |
| G08 | Explicit date validity, reviewed replacement and technical-risk continuity exist | Follow-up candidate: sourced event-relative deadlines and equivalent corporate-action conversions. Event-time discovery, automatic reevaluation and automatic risk-line conversion remain manual/blocked where mandatory. |
| G09 | Generation-time review of fundamentals/announcements and human risk decisions | Intentional boundary. No continuous news/fundamental trigger, “no bad news” inference or new simulation gate. |
| G10 | Admitted normalized prices/indicators, provenance and board-index mapping | New provider fallback, blanket BSE/history/special-status certification and automatic public-rule maintenance remain separate data work. Missing required coverage blocks only dependent actions. |
| G11 | Independent registered five-minute conditions; linked BUY confirms on official daily bars | Daily-linked five-minute confirmation needs a separate timing contract. Ordinary daily signals must not be silently converted to intraday signals. |
| G12 | Reviewed quantities, bounded native leaves, manual scoped facts and independent-signal state | Autonomous research, portfolio construction, Q0 selection, arbitrary expressions and qualitative confirmation discovery remain human or unsupported. P3 validates a complete quantity; it does not allocate capital automatically. |
| G13 | A-only executable extraction and B explanation; source/review hashes | Four original output sections versus A/B is an intentional format adaptation. B cost/holding text never initializes a simulation cost book or grants approval. |
| G14 | One whole simulation per signal, original execution window, consumption and correction fencing | Preserve. Actual partial-fill continuity stays with G06; a new price, budget tier or date must not reset a consumed signal. |

Suggested order after P3: explicitly defined volatility/confirmation extensions (G02), sourced time/event contracts (G08/G11), then individually certified data adapters (G10). This is a review proposal, not authorization for a later phase. G04/G06/G07/G09/G12 contain deliberate human/product boundaries and are not promises to automate everything eventually. Portfolio-wide or per-bucket money caps, cumulative lifetime spending and net cash invested are outside this first P3 policy.

## MLP3-S03 — Six approved decisions

| ID | Recommended decision | Reason |
| --- | --- | --- |
| MLP3-D01 | Scope P3 to daily linked TACTICAL BUY with a per-symbol cap over CORE + TACTICAL; support amount-only and share-and-amount forms | Closes G05 without a fabricated max_qty or a new portfolio allocator. Existing SELL/risk semantics continue. |
| MLP3-D02 | Offer exactly OPEN_COST_CAP and MARKET_VALUE_CAP. OPEN_COST_CAP limits current holdings' retained budget basis, including explicitly estimated buy fees/slippage; selling releases the corresponding historical basis. MARKET_VALUE_CAP uses all held shares plus the proposed buy at one current admitted quote | These are different accounting promises. “Total investment budget” alone is insufficient if release/fee meaning is unclear. Cumulative gross purchases and sale-proceeds/net-investment accounting require another contract. |
| MLP3-D03 | Derive/freeze quantities through P0/P1/P2 first, then apply all applicable limits as whole-quantity predicates. No automatic clipping, upward rounding, cap-derived Q0 or alternate exception route | A remaining amount is not authority to change a reviewed trade. Equality with a cap passes. |
| MLP3-D04 | Maintain a versioned simulation budget book bound to exact inventory batches/revisions. Existing nonzero lots require explicit reviewed opening/reconciliation evidence for OPEN_COST_CAP; zero holdings may have a known zero basis | Current quantity records cannot prove cost. No inference from B, real holdings, convenient quotes or backtest balances. No available-cash request. |
| MLP3-D05 | Opt in via Schema 9 / condition-plan-v5; retain Schema 1–8 bytes, hashes and authority, with additive separate storage and exact source review | Money-only capacity cannot be represented by treating None as both “unknown” and “unbounded”, or by supplying a fake large share limit. |
| MLP3-D06 | Share exact capital policies and event ordering across current runtime and frozen research; retain separate preview, P1 approval and whole simulation. BUY-only money failures do not veto technical risk SELL | Prevent stale-budget races, hindsight facts and approval shortcuts while preserving the original risk priority. |

All six decisions and implementation are approved. This approval does not supply missing per-plan amounts, quantities, accounting meanings, fee schedules or opening costs.

## MLP3-S04 — Capability map and dependency order

| Module ID | Owns | Depends on |
| --- | --- | --- |
| p3-capital-policy | Strict position-limit/source contracts and review identities | Existing plan-domain and AI source review |
| p3-capital-ledger | Reviewed opening basis, per-batch continuity and atomic inventory/book binding | p3-capital-policy, strategy-state |
| p3-capital-gate | Pure exact candidate-cost/value comparison and explicit share-capacity states | p3-capital-policy, p3-capital-ledger snapshot contract, P2 buy-fee arithmetic |
| p3-capital-workflow | Runtime, exceptions, API/UI, notifications and frozen replay | All three P3 modules and existing P0/P1/P2 workflow |

Build in that order, with verifiable slices in the task list. This map, the contracts and tasks are one approved implementation package. Existing production capability-map rows must not describe P3 as delivered before implementation acceptance.

## MLP3-S05 — Version and source contract

Schema 9 adds `position.limit`, a discriminated union:

- `mode=CAPITAL_ONLY`: required `capital_policy`; no `max_qty` field.
- `mode=QUANTITY_AND_CAPITAL`: required positive 100-share-multiple `max_qty` and `capital_policy`.

Each capital policy has `policy_version=capital-policy-v1`, `currency=CNY`, `scope=SYMBOL_CORE_AND_TACTICAL`, `account_scope=SIMULATION`, a positive integer `cap_fen`, and either `mode=OPEN_COST_CAP` with a complete explicit `buy_cost_schedule`, or `mode=MARKET_VALUE_CAP` with `valuation=CURRENT_ADMITTED_QUOTE`. One monetary policy applies per plan. No NONE branch: share-only sources keep their existing schema. Required simultaneous unsupported caps cannot be discarded. Allocation proposals remain optional and do not initialize holdings or money.

The fee schedule reuses P2's typed dated/security-scoped ESTIMATE contract and exact buy-component rounding. OPEN_COST_CAP needs this schedule even if P2 economics is NONE; it must not invent target/risk prices merely to calculate buy cost. When P2 economics also supplies a schedule, require identical schedule content/hash for this first version. MARKET_VALUE_CAP needs no fee schedule for valuation; P2 REQUIRED economics still applies independently if configured. No schedule or cap is an account cash balance.

All quantities/fen are strict integers within 9007199254740991; execution quantities retain legal positive 100-share multiples. Decimal fee values remain strings with P2 bounds/canonicalization. Reuse the 500-lot bound; frozen opening/reconciliation events and operations each retain the existing 10000-event envelope, with duplicate/order/cutoff validation and existing byte budgets. No new dependency or arbitrary expression evaluator.

Delivered owned domains: `plan-review-content-v6`, `plan-extract-v12`, `capital-book-v1`, `capital-limit-evidence-v1`, `capital-market-calculation-v1`, `capital-consumed-v1`, `capital-exception-event-v1`, `backtest-run-v10`. MLP3-T01 froze exact DTOs in the paired CONTRACT appendix. New Schema 9 calculation evidence uses `share_capacity` states BOUNDED (remaining_qty), UNBOUNDED (no share cap, known inventory) or UNKNOWN; do not feed fake numbers/unknown sentinels into the old authorized-quantity models. Reuse P0/P1 route and legal-floor algorithms with a new versioned composition. Earlier schemas retain their existing calculation representation and frozen-exception-event-v1 validation. Schema 9 frozen exception envelopes carry the new calculation proof under their distinct owned version; do not weaken the old envelope to accept invented capacities.

Source A must define the cap meaning/scope, amount, applicable quantity form, any buy-cost assumptions and all P0/P1/P2 strategy parameters. A standalone “总投入预算” with unresolved accounting meaning remains a scoped review blocker. Preserve missing candidate fields as null; never turn them into zero, UNBOUNDED or another schema. Every new executable leaf needs source binding or an existing explicit human supplement. Opening-budget evidence is a separate human action; source extraction, plan review and activation cannot create it.

P3 enforces the explicitly authorized simulation policy. It does not certify the actual account's monetary exposure or outstanding orders. If a source requires actual-account enforcement and provides no compatible simulation scope, retain that blocker instead of substituting a simulation book. Consumed continuity binds canonical strategy/cap content; current book/quote observations are eligibility evidence, not a new independent signal. Acquisition IDs/times and equivalent decimal spelling do not reset consumption, while admission and source-correction checks remain mandatory.

## MLP3-S06 — Exact calculations and quantity rules

Let N be known current total CORE + TACTICAL shares; q the already selected full BUY quantity; p one current admissible quote in integer fen; C the source-defined cap; K the sum of known retained budget bases. All comparisons are exact and inclusive.

OPEN_COST_CAP: `buy_notional=q*(p+buy_slippage_fen)`; `B=buy_notional+buy_fees(buy_notional)`; allow only `K+B<=C`. Commission minimum, inclusion and ceiling per component reuse P2 semantics. Invalid/expired/inapplicable schedules, unknown K/quantity/price, inconsistent book or overflow yield UNKNOWN and block dependent buying. This is simulated planned budget occupancy under reviewed estimates, not actual broker cash or realized P&L.

MARKET_VALUE_CAP: `after_value=(N+q)*p`; allow only `after_value<=C`. Value all held shares at the same stock quote; do not add historic principal, fees or the current value of only TACTICAL. Missing holding costs do not affect this branch. Price growth may place existing holdings over C: block further BUY; cap breach alone never creates a SELL, a risk exit or an instruction to liquidate the excess.

If max_qty is explicitly supplied, require `N+q<=max_qty` as well. With CAPITAL_ONLY, skip only that share-ceiling predicate; inventory and money evidence are still required. Q0/base_qty and an exact per-trade quantity remain source requirements. Never compute a permanent share maximum by dividing C by p.

WEAK_MINIMUM retains the exact compatible official minimum under P1, now also subject to the money predicate. BROKEN_STRONG keeps an empty quantity field until a human enters legal Qe<=Q0 and every applicable share/money bound; approval freezes that exact quantity. Failed money gates do not suggest or silently try a smaller quantity. P3 adds no third exception. Ordinary buys and both exceptions revalidate the same full quantity at execution; cap failures/recovery use the unchanged original window and consumption rules.

Synthetic acceptance oracles, not market rates:

- OPEN_COST_CAP: K=450000, q=100, p=1000, buy commission rate="0", minimum=500fen, other fees/slippage explicitly0. B=100500; C=550500 passes equality. At p=1001, K+B=550600 fails; no 99-share or smaller trade is produced.
- MARKET_VALUE_CAP: N=400, q=100, C=500000. p=1000 passes; p=1001 fails at 500500; p=990 recovers at 495000 within the existing window. No cost basis is needed. N=600,p=1000 alone cannot create a SELL.
- Both limits: N=400,q=100,max_qty=500 and the first monetary equality pass; either limit failing blocks the full buy. Unknown inventory is different from UNBOUNDED share capacity.

## MLP3-S07 — Budget-book continuity and atomicity

Add separate versioned storage, proposed `simulation_capital_book` and append-only `simulation_capital_event`, in the same SQLite transaction/session as simulation inventory. Keep existing daily-simulation-v1 records/bytes and actual-position tables intact. A book is per symbol/inventory stream, not per plan: bind inventory revision and the complete lot-key/bucket/quantity set, own book revision, retained basis per lot (known nonnegative fen or explicit unknown), source/availability and idempotent audit receipts.

For existing nonzero simulated holdings, require an explicit opening/reconciliation command with source/provenance, observation time, exact current lot identities and quantities, per-lot retained budget basis and expected inventory/book revisions. Unknown cost is never zero. The command changes budget evidence only: no holdings, trade, P1 approval or cash. Zero holdings can have an explicitly bound zero book. No auto-copy from real inventory, B cost, average market price or a research account. Reconciliation creates a new reviewed receipt, preserves old evidence and never rewrites completed simulations.

The current server owns received/reviewed/available times for an opening command; a supplied observation time cannot backdate its execution effect or lie in the future. Historical scenario availability is a separately labeled frozen-research assumption, never a forged RECORDED_LOCAL receipt.

Known, explicitly initialized empty simulated inventory has an exact zero retained basis. A read-only preview may derive this empty state with book revision 0 without creating a record; the first explicitly confirmed BUY can create the empty book and debit it in one guarded transaction. This does not initialize unknown inventory or infer a zero cost for nonzero lots.

BUY appends the exact simulated budget debit B with its frozen fee/price assumptions. SELL releases basis only from the exact lots actually debited by existing inventory allocation: `released=floor(old_basis*sold_qty/old_qty)`; retain every residual fen with the remaining lot, releasing all on its final sale. Preserve existing newest-first or explicit holding-scoped risk allocations; do not introduce FIFO or change sellability. Example: 400 shares with 450001fen basis; selling100 releases112500 and leaves300/337501; final sale releases all 337501. Sale proceeds/profits do not inflate C. This is an indivisible signal execution that can reduce a larger lot, not partial signal fills.

Once a book exists, all subsequent simulation inventory changes must advance its lot/revision binding atomically. A buy under an older/no-cost-schedule plan records unknown budget basis rather than changing old authority or guessing fees. Missing/mismatched/older-binary book history makes OPEN_COST_CAP unknown until reconciled. Selling all unknown lots can restore a known zero/known remaining basis. MARKET_VALUE_CAP and existing versions do not acquire a historical-cost prerequisite.

Plan switches, restart, cap changes and schedule changes cannot reset historical basis. New reviewed schedules apply to future debits only. Book/quote revisions invalidate stale previews and require current revalidation; ordinary capacity changes do not manufacture new signals. Policy/content corrections retain P0/P1/P2 invalidation semantics. Existing consumed fills remain immutable.

Preview/review/approval reserves no budget and changes no inventory. Concurrent buys may both appear eligible before execution; serialize the guarded simulation transaction, compare current inventory/book revisions, and permit only those whose post-state satisfies every limit. One idempotent command has one original receipt; a different command cannot consume the same signal twice. Failures roll back inventory, book, consumption and receipt/outbox together. Missing money evidence does not add a policy veto to SELL/risk; a genuine storage failure still fails the whole transaction without a partial effect.

## MLP3-S08 — Runtime, API, UI and notifications

At daily confirmation calculate/freeze the chosen quantity and policy identity; keep the confirmation budget assessment as evidence. At exception preview/approval and each simulation use the current admitted price, current inventory and current budget book. Do not reuse a favorable prior quote or approval-time balance. No extra day of waiting, expiry extension, price chase, rearming or cap-driven quantity resizing.

Proposed interfaces (new authority is not admitted until its full guard chain is ready):

- `GET /api/v1/simulation-capital-books/{symbol}`: read only, current simulated lot/book provenance, revisions and known/unknown status; no actual-account lookup.
- `POST /api/v1/simulation-capital-openings`: explicit human-reviewed opening/reconciliation, existing same-origin/admission/idempotency safeguards; `planVersionId`, expected inventory/book revisions, sourced observation time, server-owned receipt/availability and complete lot bases. Receipt states `inventoryChanged=false`, `authorityGranted=false`.
- `POST /api/v1/plan-capital-previews`: read only; `planVersionId`, `ruleId`, optional `occurrenceId` (server exception candidate_id) and proposed quantity only for BROKEN_STRONG. Server loads price, inventory, policy and book. Reject supplied quotes, cost totals, approvals and arbitrary share capacity. Response has `authorityGranted=false`, computed/cutoff time, policy/hash, revisions, q, before/after occupancy, remaining amount, known/blocked reasons and estimate label. Existing admission/error contracts apply: malformed422, stale/conflicting409.

Opening/reconciliation uses the existing `Idempotency-Key` convention: one stable key per human intent, atomically claimed with a unique key/request-hash binding. Same key/body returns its original receipt; changed body or an in-flight conflict returns the existing structured409 error, never another write. Version comparison, book/event update and receipt commit together. Retain deduplication evidence through all supported retry/replay paths; cleanup cannot reopen a completed command. Old endpoints retain their original error shapes and status meanings.

Use one `/plans` workflow. Explain amount-only versus combined constraints, the two monetary meanings, all-holdings scope, explicit fees and opening-cost requirements. BROKEN_STRONG starts blank; a remaining monetary amount is not a suggested quantity. Show frozen q and current assessments separately. An unavailable opening basis blocks only dependent cost-budget buying, without requesting available cash or implying holdings are safe. Explicit opening/reconciliation and simulation remain distinct actions. Discard late responses after any plan/rule/occurrence/quantity/inventory/book context change.

Runtime/exception/notification projections expose capital state through new optional/versioned fields; old records omit them. Send-time checks revalidate the applicable rule and current budget, suppress stale actionable messages, and never make an estimate sound like an approval. Existing 32 KiB result-item and other API/report byte budgets remain; use shared references with full resolution validation rather than duplicating large books/schedules or dropping proofs.

Size-admit new opening/input/proof resources before work is queued or authority changes. Oversized complete evidence must receive an explicit bounded admission failure, not be truncated or discovered only during publication. Test large500-lot inputs and shared-proof resolution/corruption within the existing byte limits. The current-book endpoint reads one bounded resource, not an unpaginated event-history list.

## MLP3-S09 — Frozen replay, compatibility and rollback

Schema 9 research uses backtest-run-v10 with copied policies, opening inventory/budget facts and explicitly ordered budget reconciliation events. Include source provenance RECORDED_LOCAL or RESEARCH_SCENARIO and observation/receipt/availability cutoffs. Same private runtime/policies, separate P1 authorization events and separate simulation operations. No source sentence or budget event grants a BUY; absent exception authorization means no exception trade.

No current book, real account, live fee schedule or future opening/correction lookup. An event available later cannot fill earlier missing basis. Preserve exact prefix decisions under future-data/event mutations. Persist complete compact evidence with integrity-checked references through real dataset readers, workers, publication and reopening, including mixed Schema 8/9 version schedules and book continuity.

Keep research cash/actual settlement accounting separate from the simulated budget basis; different reviewed estimate versus research settlement assumptions must be labeled and never silently mixed. Capital-only source limits must work with existing position-limit funding semantics without fabricating available cash or max_qty. Historical cash-constrained research and fee/P&L golden results retain their current behavior.

Schema 1–8 content hashes, serialization, prior approval receipts and historical backtest identities stay unchanged. Older readers reject 9. New additive table migrations are tested on disposable databases with backup/restore and rollback; do not infer old cost. Downgrade preserves book/event evidence and refuses Schema 9 execution. An older binary's quantity changes are detected by revision/lot mismatch after re-upgrade; no silent resumption with a stale book. User-database migration, live providers, deployment and push require separate authorization.

## MLP3-S10 — Acceptance criteria

| ID | Required independent evidence |
| --- | --- |
| MLP3-A01 | Original hash/excerpts and G01–G14 trace to delivered/manual/blocked/deferred outcomes; bilingual IDs, boundaries and six decisions agree. |
| MLP3-A02 | Strict Schema 9 variants, scalar/collection bounds, source binding, nullable draft blockers and exact review hash; no inferred cap meaning, max_qty, fee or opening cost; old 1–8 bytes/hashes pinned. |
| MLP3-A03 | Both monetary equality/failure oracles, unknown/missing/stale data, expiry/inclusion/rounding/overflow, all-holdings valuation and BOUNDED/UNBOUNDED/UNKNOWN distinction. |
| MLP3-A04 | Source-defined P2 Q0 then P0/P1 quantity selection; every applicable money/share predicate; no clipping, capital-derived sizing or new exception; both routes preserve exact quantities. |
| MLP3-A05 | Opening/reconciliation binds exact simulated lots/revisions, never actual holdings/B/cash; zero versus unknown; safe-integer, tamper/restart/migration/rollback checks. |
| MLP3-A06 | BUY debit and exact selected-lot cost release conserve fen, survive plan/schedule changes, retain unknown history and never credit sale profit to the cap. |
| MLP3-A07 | Two concurrent buys cannot overspend; approval does not reserve funds; retry/duplicate/revocation/correction/window and post-write rollback preserve one atomic consumption. |
| MLP3-A08 | Current quote can fail/recover the same q within its original window; existing over-cap holdings do not force SELL; missing budget/fees never add a veto to actual technical-risk simulation. |
| MLP3-A09 | Real API admission/source-review errors, literal false authority, read-only preview, explicit opening receipt, rejected client prices and stale-context/version fences. |
| MLP3-A10 | Real frozen workers and published/read-back reports retain current/replay parity, no future-data effects, explicit budget/approval events, isolated accounts and unchanged legacy fee/P&L fixtures and byte budgets. |
| MLP3-A11 | Browser journeys for both cap meanings, amount-only/combined forms, opening unknown/reconciliation, both exceptions, stale preview, whole execution and readable 320/768/1024/1440 layouts. |
| MLP3-A12 | Complete non-live backend, frontend, type/build, both generated API profiles, lint, whitespace and bilingual audit; record failures/reruns and retained platform/live exclusions honestly. |

## MLP3-S11 — Implementation and verification contract

Use current Python 3.14/Pydantic/FastAPI/SQLAlchemy/SQLite and Vue/TypeScript patterns. Put pure calculations under `decision/`, strict contracts under `domain/`, book/transaction logic under `state/`, owned orchestration under `runtime/`, HTTP under `web/` and frozen adapters under `backtest/`. Use the existing strict immutable models, integer fen, exact Decimal/Fraction arithmetic and Composition API `<script setup lang="ts">`; no new dependency is proposed. Expected pure predicate shape: `after_fen = before_fen + buy_debit_fen; allowed = after_fen <= cap_fen`, with all input/overflow checks preceding authorization.

The [task list](../../../tasks/market-linkage-p3.md) owns full executable V01–V08 commands, proposed test files, 24 ordered tasks and eight checkpoints. New tests must first exist and fail for independent expected outcomes; an empty selection is not a pass. The paired verification report records actual stages and final acceptance; approval never substitutes for test evidence. Target 3–5 files per slice; explicitly split broad reader/generator/UI/replay seams before editing. Preserve `tasks/plan.md` and `tasks/todo.md`; no delegated/parallel-agent work was used in this phase.

Always preserve source constraints, risk priority, historical golden fixtures, exact arithmetic, existing capacity/time/byte gates and bilingual parity. A later implementation instruction may authorize code, additive migration development and disposable-database verification; it does not authorize applying migrations to user databases. New strategy semantics, ambiguous amount meanings beyond these modes, historical-authority incompatibility or a scope extension require review. Never infer cash, weaken tests, migrate historical documents silently, auto-approve an exception or execute a broker order.

## MLP3-S12 — Review and delivery boundary

Review MLP3-D01–MLP3-D06 together with the module map, money-only contract and acceptance criteria. The main decisions are the OPEN_COST_CAP meaning/release rule and the explicit isolated opening-budget workflow. If another meaning of “总投入预算” is intended, revise D02 and its tests before implementation rather than disguising it as retained cost.

The user has approved this bounded P3 package and authorized implementation and local tests. P0/P1/P2 compatibility and scope boundaries remain binding. User-database mutation, live provider calls, deployment and push are outside this implementation authorization. Task/checkpoint marks and the verification report record actual completion; approval alone is not test acceptance.

Acceptance: [final criterion evidence](../../verification/2026-10-26-market-linkage-p3.md). G05 is delivered only within this per-symbol simulation capital scope; other excluded/manual/follow-up capabilities retain their approved boundaries.
