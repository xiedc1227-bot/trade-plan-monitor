# Specification: quantity-policy

Status: APPROVED — on 2026-10-24 the user approved all six decisions and specifications and explicitly authorized ordered implementation. Progress is governed by acceptance evidence; unfinished tasks are not shipped capability.
Implementation evidence is maintained in [the verification report](../../verification/2026-10-24-market-linkage-p0.md).

## QP01 — Objective and contract

Convert one eligible market route into one bounded, immutable simulation quantity. Depends on `confirmation-selection` and existing position/signal transaction rules. `quantity_policy` fields: `mode=MARKET_FACTOR`, `base_quantity=Q0`, `normal_factor="1"`, `weak_factor="0.5"`, `rounding=LEGAL_FLOOR`, `capacity_policy=BLOCK_FULL`, `signal_quantity_policy=FREEZE`. Decimal factors remain strings. These strategy values require source/review evidence; they are not invented product defaults.

Q0 is a positive integer multiple of 100 within the existing domain integer bound. It is chosen from research before market reduction and cannot be inferred, increased to compensate for rounding, or recomputed from live volatility. Position maximum remains mandatory. The linked rule cannot also provide fixed `quantity`; fixed ordinary rules remain unchanged.

## QP02 — Algorithm and constraints

1. Select factor 1 for NORMAL_TRANSITION or 0.5 for ordinary WEAK. Other routes authorize zero without constructing an executable zero-quantity action.
2. Compute `ceiling = factor * Q0` exactly. Candidate quantity is the greatest positive quantity <= ceiling allowed by both verified market rules and the current 100-share simulation contract. No common legal quantity means no ordinary order. Distinguish market-rule incompatibility from an ordinary reduction below minimum; neither can round upward.
3. Require complete selected S0/S1, no higher-priority risk, known simulation inventory and `position.max_qty - inventory.total_qty >= candidate_quantity`. Otherwise authorize zero and retain reasons. Never shrink to the remaining capacity.
4. On signal confirmation freeze candidate quantity as `planned_qty` together with the route, Q0, factor, rule/evidence hashes and inventory revision used. Execution revalidates all existing gates and current inventory transactionally; it either applies the whole quantity or none.

Unknown market rules or holdings block dependent buying. Actual account text does not initialize simulation holdings. SELL quantities, T+1, CORE protection and technical-risk quantities are not redefined by market factors. Use the existing verified market-rule data; adding non-100-share execution belongs to P1.

When Q0 itself is below the official minimum in NORMAL_TRANSITION (for example STAR Q0 100 versus minimum 200), use `MARKET_QUANTITY_BELOW_MINIMUM`. This is an ordinary quantity block, not the WEAK reduction exception. `P1_EXCEPTION_REQUIRED` applies to the specified WEAK/BROKEN exception routes only.

## QP03 — Worked acceptance fixtures

These are synthetic arithmetic fixtures, not trade recommendations. Assume the instrument allows positive 100-share multiples and all other gates pass.

| Q0 | State | Capacity | Candidate / result |
| --- | --- | --- | --- |
| 300 | NORMAL_TRANSITION | 500 | 300 authorized |
| 300 | WEAK | 500 | ceiling 150; candidate 100 authorized |
| 100 | WEAK | 500 | ceiling 50; no ordinary quantity; P1 exception stays blocked |
| 300 | NORMAL_TRANSITION | 200 | candidate 300; zero authorized, whole quantity blocked |
| 300 | WEAK | 0 | candidate 100; zero authorized |

At confirmation and execution, `authorized_quantity <= Q0` and authorized quantity never exceeds capacity. Conditions not met, incomplete evidence or P1 exception status cannot produce a positive authorization even if arithmetic is calculable.

## QP04 — Immutability and restart

Persist the calculation before exposing an actionable signal. Repeated polling or restart uses the same signal occurrence and frozen quantity. Improvement cannot enlarge it. A corrected consumed source fact invalidates pending authority as in CS04, without mutating completed executions. Concurrent inventory changes cause full-quantity revalidation; idempotent replay of a completed command returns the original receipt, never another fill. Insufficient capacity can block execution without erasing signal evidence; later capacity recovery within the unchanged window does not create a new signal.

Unchanged admitted stock values and basis retain continuity across refetch receipt IDs/times, adjustment-as-of dates and equivalent Decimal representations. These acquisition fields remain in immutable audit evidence; price/basis changes still invalidate the pending signal. Admission/cutoff checks are never bypassed by continuity normalization.

## QP05 — Acceptance and verification

| ID | Required evidence |
| --- | --- |
| QP-A01 | Strict exclusive fixed/policy contracts, string factors, source-bound Q0 and positive 100-share constraints reject invalid candidates. |
| QP-A02 | All fixture rows plus exact-boundary and incompatible-market-rule cases prove floor-only sizing and no capacity clipping. |
| QP-A03 | Unknown state, inventory or market rules; failed S0/S1; P1 blocks and higher risk all authorize zero. |
| QP-A04 | Restart, polling and state improvement cannot enlarge, duplicate or partially consume a signal. |
| QP-A05 | Real temporary SQLite concurrency and idempotency tests enforce full-quantity execution, limits, T+1 and inventory isolation. |

Implementation files: `domain/market_linkage_models.py`, `decision/quantity_policy.py`, shared lifecycle/transaction seams and focused tests. Verification command from `trade-plan-monitor/`: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_quantity_policy.py tests/integration/test_market_linkage_runtime.py tests/integration/test_unified_simulation_transactions.py -q`. Follow MLP07 exact arithmetic/style; no user database access.

## QP06 — Approved official-rule source amendment (2026-10-24)

The user directed implementation to use official exchange rules directly. P0 therefore embeds a dated, versioned minimum/increment registry; it does not introduce an additional per-security manual proof workflow. Version `cn-equity-buy-grid-2026-07-06` applies from 2026-07-06: SSE/SZSE ordinary A-shares and ChiNext use minimum 100 / increment 100; STAR uses 200 / 1; BSE uses 100 / 1. The existing simulation intersection remains 100-share multiples. Each calculation retains rule version, effective date, article, source URL and content hash. Unsupported security prefixes or earlier historical dates remain `MARKET_RULES_UNKNOWN`; this registry does not certify data-provider coverage or implement broker order limits.

Official sources: [SSE 2026 trading rules, articles 3.3.8 and 6.7](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml), [SSE STAR education](https://edu.sse.com.cn/tib/qa/), [SZSE 2026 trading rules, article 3.3.8](https://investor.szse.cn/lawrules/rule/trade/t20260424_620190.html), [BSE 2026 trading rules, article 3.3.8](https://www.bse.cn/jygl_list/200028217.html), [BSE official quantity examples](https://www.bse.cn/uploads/6/file/public/202509/20250916143055_4sxt0kkec4.pdf). Trading rules were published 2026-04-24 and take effect 2026-07-06.
