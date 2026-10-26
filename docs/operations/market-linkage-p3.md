# Operations: market-linkage-p3

[Chinese review copy](market-linkage-p3.zh-CN.md) · [approved specification](../specifications/monitoring/SPEC-market-linkage-p3.md) · [tasks and acceptance status](../../tasks/market-linkage-p3.md) · [verification](../verification/2026-10-26-market-linkage-p3.md).

## MLP3-O01 — Source and policy review

Use `/plans` and `plan-extract-v12`. For a source-defined monetary limit, A must explicitly select Schema9 / condition-plan-v5 and preserve the complete P0/P1/P2 daily linked TACTICAL BUY policy. The cap covers this symbol's CORE+TACTICAL simulation holdings. Amounts are integer fen, quantities remain positive whole100-share units intersected with the applicable official buy grid. Source/review changes require a new exact-content review.

`position.limit.mode=CAPITAL_ONLY` requires `capital_policy` and forbids `max_qty`. `QUANTITY_AND_CAPITAL` additionally requires positive100-share-multiple `max_qty` inside `position.limit`; Schema9 has no root `position.max_qty`. Both constraints apply to the complete chosen quantity. The source must choose exactly one meaning:

| Policy | Whole proposed buy q at current admitted price p |
| --- | --- |
| `OPEN_COST_CAP` | K+B(q,p)<=C, where K is retained historical simulation budget basis and B includes the explicit estimated buy fees/slippage |
| `MARKET_VALUE_CAP` | (N+q)*p<=C, where N is all current CORE+TACTICAL shares; valuation is `CURRENT_ADMITTED_QUOTE` |

Both policies use `policy_version=capital-policy-v1`, `currency=CNY`, `scope=SYMBOL_CORE_AND_TACTICAL`, `account_scope=SIMULATION`, positive `cap_fen`. Cost caps require the complete dated, security-scoped P2 `buy_cost_schedule`, even when economics mode is NONE. If P2 also supplies a fee schedule it must be exactly the same. Market-value caps forbid this cost schedule and do not require opening costs. “Total investment budget” without an explicit accounting meaning stays unresolved; B cannot fill it, initialize costs or grant approval. Cumulative lifetime purchases, net invested cash, portfolio or separate bucket caps require another specification.

## MLP3-O02 — Initialize quantities and explicitly confirm costs

Simulation inventory, the simulation budget book, historical actual positions and research P&L are separate records. First explicitly confirm the actual intended simulation CORE/TACTICAL quantities. The capital panel lists complete current lot identities and quantities; opening cost fields start empty. For nonzero holdings under OPEN_COST_CAP, provide every current lot's retained basis, observation time, source, excerpt and reason, then explicitly confirm the opening/reconciliation. Do not use B, a current quote, a research cost or a real-account balance as an automatic substitute.

The server checks the active reviewed plan, exact complete lots, inventory/book revisions and nonfuture observation. It stamps receipt time and writes a versioned book/event in one transaction. Retry the same command to retrieve the same receipt. The receipt has `inventoryChanged=false` and `authorityGranted=false`: it creates no inventory, signal, approval or simulation. Unknown cost stays UNKNOWN. Explicitly initialized zero holdings may use known K=0 without a cost declaration; the first separately confirmed buy creates/debits the book atomically.

Selling releases the historical basis of the actual selected lots. For400shares with basis450001fen, selling100 releases112500fen; the remaining300retain337501fen, which the final full sale releases exactly. Sale proceeds or profits do not increase C. An older-plan buy without compatible cost evidence makes that lot's basis unknown; selling precisely that unknown lot can restore known aggregate basis. A changed quantity/book mismatch never reconstructs cost automatically. Plan replacement preserves the shared symbol inventory/book rather than resetting its budget.

## MLP3-O03 — Quantity, authorization and current execution

P2 derives Q0 first; P0 selects the ordinary market quantity; P1 retains only its two source-permitted exception routes. The capital predicate checks that exact whole quantity. It never chooses Q0, clips to remaining money, rounds upward or creates another exception. Equality passes. For K450000fen, q100, p1000fen, minimum commission500fen and other costs/slippage0, B=100500fen and K+B=550500fen passes C550500fen. p1001 produces550600fen and rejects the whole buy. For N400, q100, C500000fen, p1000 passes, p1001 fails500500fen, p990 passes495000fen; no quantity changes.

`WEAK_MINIMUM` still needs explicit plan permission, STRONG, S1 and `0.5*Q0 < minimum <= Q0`; approved quantity is exactly the compatible official minimum. `BROKEN_STRONG` still needs permission, STRONG, S2 and a separately entered legal Qe within Q0 and any share ceiling; its input starts empty. Preview grants no authority and reserves no budget. Each occurrence needs explicit approval, then a separate whole simulation in its original next-session window. Approval and execution independently recheck current budget/quote. No automatic approval, amount-based reduction, partial execution or new window is introduced.

The UI separates frozen quantity from current capital eligibility and discards stale responses after context changes. Execution serializes inventory/book writes, checks current quote, exact policy, book, inventory and authority, then commits inventory, lot costs, signal/approval consumption and receipt together. A correction can block or restore eligibility only inside the original window; it cannot resize, rearm or extend a consumed signal. Send-time checks suppress stale actionable BUY reminders. Over-cap holdings alone create no SELL, and BUY-only money/fee failures never veto an actual source-authorized technical-risk SELL.

## MLP3-O04 — Current API

| Route | Purpose and boundary |
| --- | --- |
| `GET /api/v1/simulation-capital-books/{symbol}` | Bounded book/current inventory read; complete `inventoryLots` up to500 even before cost exists; no inferred zero |
| `POST /api/v1/simulation-capital-openings` | Explicit reviewed complete-lot opening/reconciliation; same-origin, idempotent, server-timed receipt; no inventory/approval effect |
| `POST /api/v1/plan-capital-previews` | Read-only current whole-quantity assessment from server quote/book/inventory; literal `authorityGranted=false`, no writes |

Preview accepts `planVersionId`, `ruleId`, optional `occurrenceId` and `proposedQuantity`. Exception `occurrenceId` is the server candidate_id; only BROKEN_STRONG accepts manual proposedQuantity. Caller quotes, totals, revisions or approval claims cannot replace server authority. Opening accepts the actual expected inventory/book revisions and full explicit lot costs/source; review and inventory are reloaded in the write transaction. Invalid bodies return422; unavailable/stale exact authority returns409, missing resources404, under the existing structured local API contract. A preview or opening receipt is never a simulation token.

## MLP3-O05 — Frozen research, recovery and compatibility

Schema9 uses `backtest-run-v10`, `unified-research-input-v3`, explicit `capital-replay-program-v1` and `capital-exception-program-v1`. Opening/reconciliation events distinguish RECORDED_LOCAL original receipts from RESEARCH_SCENARIO declarations, bind exact OPENING(lot_key) or BUY_SIGNAL(signal_id) references and retain observed<=received<=available times. Future declarations cannot fill earlier gaps; missing/incorrect complete lots block the declaration. Available pre-start declarations may seed only matching explicitly known opening holdings. No current user book, fee provider or live approval is fetched.

The prepared backtest form provides the optional advanced ‘预算与复评研究记录（可选）’ entry. It starts blank and accepts only a JSON object containing capitalProgram and/or exceptionProgram; these are complete frozen records, not client prices or totals. Changing the reviewed preparation/selection requires explicit reentry. Omitting capitalProgram in a public prepared command freezes an explicit empty program in the required v10 field; it never supplies zero costs, reads the current book or borrows research costs. Nonzero unknown basis still blocks dependent cost-cap buys. A populated declaration must pass exact source, lot, time, order and provenance checks; authorization and operations remain separate.

Budget declarations, exception authorizations and independent operations have unique time/order. Both private workers call shared current services; research cash/fees/P&L stay independent of estimated budget basis. Reports retain source/provenance/private receipt hashes and resolve/revalidate shared full evidence. Tampered or missing references fail publication/read-back. Existing32KiB items,8MiB source/input and all other bounds remain. The legacy `POSITION_LIMIT_ONLY` funding value removes a spendable-cash constraint, while Schema9 plan capital predicates still apply; it does not fabricate an available-cash balance.

Storage migration0027 adds separate versioned sidecar tables. Implementation/tests use disposable databases. Operational user-database migration remains a separate authorized action; back up before any approved upgrade or downgrade. Older readers reject9 rather than relabeling it. Downgrade refuses to discard nonempty new evidence. Restart reads the same exact book/inventory revisions; an older binary or external quantity mismatch produces unknown cost. Schema1–8 bytes, hashes, frozen inputs and authority remain unchanged.

## MLP3-O06 — Remaining original-prompt boundaries and verification

G05 is supported for isolated per-symbol simulation only. Actual account/partial fills/order reservations/chat-derived holdings (G06), non100-share execution/odd-lot liquidation/ordinary CORE creation (G07), automatic fundamentals/news judgment (G09), autonomous portfolio/Q0 selection and arbitrary expressions (G12) remain excluded or human. Automatic level/evidence discovery (G04), arbitrary volatility-dependent confirmation changes (G02), event-relative deadlines/corporate-action conversions (G08), daily-linked five-minute confirmation (G11), unverified provider/BSE coverage and automatic rule maintenance (G10) require separately reviewed capabilities. Fee discovery/catalog updates and discretionary viability under G03 remain manual. A/B format adaptation and complete-source checks remain under G13/G14. Required unsupported constraints block the affected executable rule; never drop them or substitute a reminder.

Use the actual [V01–V08 task checks](../../tasks/market-linkage-p3.md) and [verification status](../verification/2026-10-26-market-linkage-p3.md). Separate backend unit/integration/contract processes avoid existing duplicate basenames; live tests are excluded, not simulated as certified. Capacity checks run alone with unchanged120s/symbol,768MiB working-set delta,512MiB market and192MiB result limits. Local acceptance uses synthetic prices/fees and temporary databases; it does not certify live data/rates, actual fills or deployment.
