# Specification: market-linkage-p1

Status: IMPLEMENTED AND ACCEPTED — on 2026-10-24 the user approved MLP1-D01–MLP1-D06 and authorized implementation. MLP1-T01–MLP1-T21 and MLP1-C01–MLP1-C07 are complete; executed tests, repairs and local-certification limits are recorded in the paired verification report.

Canonical English · [Chinese review copy](SPEC-market-linkage-p1.zh-CN.md) · [Implementation plan and tasks](../../../tasks/market-linkage-p1.md).

## MLP1-01 — Objective and baseline

Support the two human-reviewed BUY exceptions preserved in the [README source prompt](../../../README.md#reusable-trade-plan-generation-prompt), without turning relative strength or human approval into a bypass of trading conditions. Baseline: locally accepted P0 at `dbeff32`; [P0 specification](SPEC-market-linkage-p0.md), [confirmation definitions](SPEC-confirmation-selection.md), [quantity rules](SPEC-quantity-policy.md), [contracts](CONTRACT-market-linkage-p0.md), and [verification](../../verification/2026-10-24-market-linkage-p0.md).

The user should see why an exception is eligible, its exact quantity and remaining constraints, approve or reject that occurrence, and separately confirm a whole simulated trade. Success includes proving that missing approval always gives zero authority and that repeated actions cannot create extra trades.

This package is an approved extension of the existing `confirmation-selection`, `quantity-policy` and `market-linkage-workflow` modules. It does not replace their approved P0 behavior. The user reviewed the specification and task list together and has explicitly instructed implementation.

## MLP1-02 — Scope and module boundaries

| Module ID | P1 responsibility | Depends on |
| --- | --- | --- |
| `confirmation-selection` | Identify `WEAK_MINIMUM` and `BROKEN_STRONG` eligibility; require the exact S1/S2 and STRONG evidence | Existing `market-regime`, `relative-strength`, shared quantity preflight |
| `quantity-policy` | Validate the route-specific proposed quantity; freeze the approved quantity | Selected route, official quantity grid, existing inventory gates |
| `market-linkage-workflow` | Source review, occurrence-bound authorization, durable events, runtime, simulation, UI and replay | Both modules above and existing state/runtime infrastructure |

Build order: closed contracts → eligibility/quantity → source review → durable authorization → runtime/simulation → API/UI → frozen replay → full acceptance. These are extensions of existing modules, not new services. The selector does not depend on an authorization repository; it returns eligibility, while the application service combines eligibility with recorded authority.

In scope: DAILY BUY/TACTICAL, the existing official-close and next-exchange-session window, independent per-route opt-in, explicit human approval/rejection/revocation, atomic whole-quantity simulation, and honest frozen replay. Ordinary routes, SELL, technical risk, CORE protection and independent five-minute reminders retain their current meaning.

Out of scope: broker orders, batch or standing approval, automatic approval, intraday exception confirmation, arbitrary sizing formulas, non-100-share simulation, automatic Q0 changes, new providers/calendars, multi-user identity management, production deployment and user-database migration. Official minimum/increment data continue to use the existing versioned registry under QP06; no additional manual exchange-rule proof workflow is introduced. Existing provider/calendar coverage blocks remain, including BSE restrictions.

## MLP1-03 — Approved decisions

| ID | Recommended decision | Reason |
| --- | --- | --- |
| MLP1-D01 | Two authorization levels: reviewed plan permission for each route, followed by explicit approval of each eligible occurrence | Reviewing a strategy does not approve every future buy; AI, facts, acknowledgements and activation cannot grant an exception. |
| MLP1-D02 | `WEAK_MINIMUM` approves exactly the official minimum buy quantity, only if compatible with the 100-share simulation contract and no greater than Q0 or capacity | This implements the prompt's minimum-quantity exception; it is a separately authorized replacement quantity, not automatic upward rounding. |
| MLP1-D03 | `BROKEN_STRONG` requires an explicitly entered legal quantity greater than zero and no greater than Q0 or capacity; no default quantity or automatic half factor | The source leaves this quantity to human reassessment. Neither Q0 nor `0.5 * Q0` is an approved default for this route. |
| MLP1-D04 | At most one approval and one whole consumption per independent occurrence; quantity freezes on approval; the window remains the next exchange session only | Reapproval, corrections, new dates and repeated clicks must not bypass independent-signal restrictions or extend a missed window. |
| MLP1-D05 | Opt in through a newly reviewed Schema 7 plan; preserve Schema 5/6 bytes and behavior, including Schema 6 P1 blocks | Enabling human exceptions changes executable authority. Existing plans must not gain that authority silently. |
| MLP1-D06 | Replay uses explicit frozen authorization events only; absent events mean zero exception trades; hypothetical events are clearly labeled research assumptions | Avoid hindsight approval or a misleading claim that every eligible historical exception would have been approved. |

All six decisions are approved. D02 and D03 are the principal quantity choices. Approval of this document approves the stated boundaries, not authorize a particular security, occurrence, simulated trade or production operation.

## MLP1-04 — Common eligibility and authorization

Use P0 market classification, reference index, aligned relative-strength calculation, S0/S1/S2 definitions and timing unchanged. STRONG means all three known predicates pass: stock 5-session return > index return; stock 20-session return > index return; stock close at D >= its MA20 at D. Equality in either return comparison fails. Unknown evidence is not human-overridable.

S1 requires the complete S0 at D, adjacent scheduled sessions D-1/D both closing inside the low-buy region, D close >= D-1 close, D volume <= the prior 20-session mean excluding D, RSI14 at D > RSI14 at D-1, and no higher-priority risk. S2 adds each day's close >= its own day's MA20. The original warm-up, cutoff, source admission and reviewed-fact scopes remain mandatory.

Authorization requires ALL of:

1. An explicitly reviewed and active current plan enables this exact exception route and binds its full definition, Q0 and quantity constraints to source or a human-reviewed supplement.
2. Official completed session D evidence selects that route and proves its STRONG and S1/S2 eligibility. Missing market rules, input, alignment, required fact or higher-priority risk prevents approval.
3. A genuine independent occurrence exists under the rule's reviewed signal policy. Stock, plan/review version, activation, rule, route, D, execution window and consumed evidence are fixed in the candidate.
4. Known simulation inventory and remaining capacity support the full selected quantity. The current plan, review and candidate have not been superseded, rejected, expired, revoked or consumed.
5. The local user sees a server-generated preview and explicitly approves its exact quantity with a nonblank reason. Server time and the existing same-origin mutation guard establish the recorded local action; no authenticated human identity or signature is claimed by this single-user product.

Plan permission, occurrence eligibility, approval, and permission to execute are distinct. Approval has no inventory effect. `/api/v1/simulated-trades` remains a separate explicit action and rechecks all current execution gates. A reviewed technical fact can supply only its scoped technical predicate; it cannot stand in for exception approval. Basic source text saying “approved” is never an approval event.

## MLP1-05 — Route and quantity table

Let Q0 be the existing source-reviewed positive 100-share multiple, bounded by `9007199254740991`. Let `m` and `s` be the official minimum and increment for the security/session. Define `L = {m + n*s | n is an integer >= 0} ∩ {100*k | k is an integer >= 1}` and capacity `C = position.max_qty - inventory.total_qty`. Use exact arithmetic.

| Route | Entry conditions beyond common gates | Quantity rule | Authority before occurrence approval |
| --- | --- | --- | --- |
| NORMAL_TRANSITION | S0 | Existing P0 factor `1` and legal floor | Existing ordinary behavior |
| Ordinary WEAK | S1; `L` contains a quantity <= `0.5 * Q0` | Existing largest such quantity | Existing ordinary behavior; STRONG is unnecessary |
| `WEAK_MINIMUM` | WEAK; ordinary reduction is below the minimum; STRONG; S1; route enabled | `Qe = m`, require `m ∈ L`, `m <= Q0`, `m <= C` | Zero |
| BROKEN + NOT_STRONG | No exception eligibility | Zero | Zero |
| `BROKEN_STRONG` | BROKEN; STRONG; S2; route enabled | User enters `Qe ∈ L`, require `0 < Qe <= Q0` and `Qe <= C` | Zero |
| Necessary input UNKNOWN | Cannot establish selected route/conditions | No positive authorization | Zero |

For `WEAK_MINIMUM`, require `0.5 * Q0 < m <= Q0`. The existing preflight must identify a below-minimum reduction, not unknown rules or a grid incompatibility. If the official minimum itself is not a 100-share multiple, block this exception; do not replace it with a larger common-grid value. The approved current registry's minimums are compatible. Supporting other quantities would require a separate specification amendment.

For `BROKEN_STRONG`, Qe can be lower than, equal to or higher than `0.5 * Q0`, but never exceed Q0. This is a proposed human choice within the source ceiling, not a recommendation to use the maximum. The quantity entry starts empty. Invalid input is rejected without rounding, clipping, prefilling or silently substituting another quantity. Approval of one route never carries to the other.

For both routes, zero means no approval/trade, not an executable zero-share operation. Unknown capacity blocks approval; insufficient capacity blocks the whole selected quantity. Changing Q0 requires a new plan version and review. Normal-state under-minimum Q0, ordinary capacity shortage, incompatible grids or a failed ordinary confirmation cannot be diverted into either exception.

## MLP1-06 — Worked quantity acceptance fixtures

Synthetic fixtures below exercise the existing registry, not investment advice or new market-rule certification. Assume route permission, complete evidence and all other gates pass unless noted. All quantities are shares; the proposed authorization occurs only after explicit approval.

| ID | Route / grid | Q0 | C | Input / expected result |
| --- | --- | --- | --- | --- |
| MLP1-Q01 | WEAK; m=100, s=100 | 100 | 500 | Ordinary ceiling 50; STRONG + S1 permits approving exactly 100 |
| MLP1-Q02 | WEAK; m=100, s=100 | 300 | 500 | Ordinary 100; no minimum exception entry |
| MLP1-Q03 | WEAK; m=200, s=1 | 300 | 500 | Ordinary ceiling 150; STRONG + S1 permits approving exactly 200 |
| MLP1-Q04 | WEAK; m=200, s=1 | 100 | 500 | Minimum 200 exceeds Q0; blocked |
| MLP1-Q05 | WEAK; m=100, s=100 | 100 | 0 | Candidate minimum 100; approval blocked by capacity |
| MLP1-Q06 | WEAK; m=200, s=1 | 400 | 500 | Ordinary ceiling 200 equals minimum; ordinary 200, no exception |
| MLP1-Q07 | BROKEN; m=100, s=100 | 500 | 400 | STRONG + S2; entered 300 may be approved, 500 blocked by capacity |
| MLP1-Q08 | BROKEN; m=100, s=100 | 500 | 800 | Empty / 0 / 150 / 600 are rejected; legal 100 or 500 may be approved |
| MLP1-Q09 | BROKEN; m=200, s=1 | 300 | 500 | Entered 200 may be approved; 100 or 250 rejected |
| MLP1-Q10 | BROKEN; m=100, s=100 | 500 | 400 | NOT_STRONG, UNKNOWN or failed S2 prevents approval regardless of quantity |
| MLP1-Q11 | WEAK; synthetic m=150, s=1 | 200 | 500 | Minimum incompatible with simulation; do not substitute 200 |
| MLP1-Q12 | Either eligible exception | 300 | 500 | Missing approval, disabled route, foreign/stale approval or expired window gives zero authority |

## MLP1-07 — Occurrence lifecycle, cutoff and races

An eligible occurrence produces a non-executable `PENDING` candidate. It has no ordinary actionable signal and no authorized quantity. Weak-route quantity is already determined; broken-route quantity remains unset until preview input. User changes to an unapproved preview do not create additional occurrences.

Allowed transitions: `PENDING → APPROVED | REJECTED | EXPIRED | INVALIDATED`; `APPROVED → CONSUMED | REVOKED | EXPIRED | INVALIDATED`. All other transitions are rejected. Terminal states never reopen. Only `APPROVED` can produce a positive execution authorization, and only while its remaining gates pass. Execution writes `CONSUMED` in the same transaction as the original whole-trade receipt and inventory update.

One occurrence may have at most one successful approval and one consumption. Approval atomically freezes Qe, the evidence binding and its signal. Approved quantity cannot be edited; revoke it if the user changes their mind. Rejection or revocation does not permit another approval for that occurrence. A new opportunity needs the existing independently confirmed signal reset/new-event policy; a new date, route switch, plan clone, correction, notification or retry alone is insufficient. Preserve existing same-direction rule ordering and cross-version continuity; do not introduce a fresh exception counter that bypasses them.

Decision session D must be completed and its records available by the evaluated cutoff. Approval can occur after those records are admitted, including before the next session opens, but only until the next exchange session's close. Execution is limited to that next session and its existing tradability checks. Server receipt time is authoritative; the user cannot backdate approval. Delayed evidence or late approval never extends the window. Unknown next-session calendars block authority. Reopening the app does not renew it. All timestamps use timezone-aware `Asia/Shanghai`. Keep the original market-evidence cutoff distinct from the later authorization receipt time: append authority at its actual time; never rewrite the earlier decision as already approved.

Changes to consumed prices, basis, scoped facts, plan/review content, activation, route or required rule version invalidate pending or approved authority. Preserve P0 continuity for mere refetch IDs/times, adjustment-as-of metadata and equivalent Decimal formatting. New observations outside the consumed decision window do not by themselves rewrite D. A raised current risk blocks execution under existing risk rules. Executed history remains immutable.

Preview includes the current inventory and authority revisions. A changed revision before approval returns a conflict and requires a new preview. After approval, an inventory change rechecks full capacity without resizing or inventing another signal; unchanged authority may execute if capacity is sufficient within the original window. Approval/revocation/execution races use transactionally checked revisions. If consumption wins, revocation returns conflict and cannot undo the trade; if revocation wins, execution cannot fill.

## MLP1-08 — Contracts and compatibility

Schema 7 uses `execution_mode=CONDITION_PLAN`, `execution_version=condition-plan-v3`; linkage uses `market_policy.policy_version=market-linkage-v2`, `base_confirmation=S0`, `exception_policy=REVIEW_PER_OCCURRENCE`. Inside each linked rule's `market_policy`, add required `exception_routes.weak_minimum` and `exception_routes.broken_strong`, each `DISABLED` or `PER_OCCURRENCE`. Both may explicitly be disabled, including when a reviewed update withdraws permission; this does not silently downgrade the format. No absent field implies permission. Existing ordinary `quantity_policy`, BUY/TACTICAL restrictions, two-rule bound, depth 4 and 50 expanded leaves remain.

New plan permission binds the expanded exception meaning, not only these enum labels. A newly reviewed Schema 7 version is necessary to enable a formerly blocked route. Schema 6 remains `BLOCK_P1`; its exceptions keep `P1_EXCEPTION_REQUIRED`. Schema 5 fixed plans and Schema 1–4 frozen readers remain unchanged. No automatic upgrade, added legacy default, silent field drop or new UI schema selector.

Implemented version boundaries: extraction `plan-extract-v10`; review content `plan-review-content-v4`; decision `market-linkage-evidence-v2`; calculation `market-linkage-calculation-v2`; candidate `market-linkage-exception-candidate-v1`; authorization `market-linkage-exception-authorization-v1`; research input `backtest-run-v8`. Existing stock/index data and formula versions remain unchanged. MLP1-T01 verified collisions and froze the reader/writer inventory in the paired contract appendix; technical encoding details preserve the approved strategy meaning.

Candidate evidence binds `candidate_id`, stable `occurrence_id`, symbol, exact plan/review/activation/rule identity, route, D, decision cutoff, original execution window, consumed evidence/hash versions, Q0, official grid version/source hash, eligibility and quantity constraints. Full acquisition metadata remains auditable; continuity hashing retains P0 normalization. Authorization additionally binds `approval_id`, exact candidate digest, `quantity`, server `received_at`, `actor_kind=LOCAL_USER`, nonblank reason and command identity. Reject unrecognized fields and malformed or forged approval payloads at source/import boundaries.

Store append-only authorization/terminal events and a transactionally updated projection. Use durable unique occurrence/approval/consumption constraints and command receipts, not only process locks. Any additive storage migration is tested on temporary databases; old JSON/hashes are never rewritten. Rollback preserves new records and explicitly blocks unsupported operations; it must never reinterpret them as ordinary/fixed orders. Hashes use the existing canonical JSON and domain/NUL/SHA-256 convention; verify them on loading.

## MLP1-09 — API and diagnostics

Keep `/plans` and existing plan/review/activation/runtime/simulation families. Add the following local command families; all inputs are strict typed models, all mutations use the existing origin/context guards and durable idempotency. The names below are the implemented contracts; exact generated fields and event audit encoding are recorded in the contract appendix.

| Method and path | Required input / behavior | Output |
| --- | --- | --- |
| `POST /api/v1/plan-exception-previews` | `candidate_id`, `expected_revision`, `proposed_quantity` (null for `WEAK_MINIMUM`, explicit for `BROKEN_STRONG`); read-only recomputation, no approval | Immutable `preview_id`, `preview_hash`, exact quantity, capacity, evidence, expiry and all blockers |
| `POST /api/v1/plan-exception-decisions` | `command_id`, `candidate_id`, `expected_revision`, `decision=APPROVE\|REJECT`, reason; APPROVE requires `preview_id` and `preview_hash`, REJECT carries neither | Durable decision receipt, candidate state, approval identity/quantity if approved; no inventory change |
| `POST /api/v1/plan-exception-revocations` | `command_id`, `approval_id`, `expected_revision`, reason; only unconsumed current APPROVED authority | Durable revocation receipt; no inventory change |
| `GET /api/v1/plan-runtime/{symbol}` | Existing read extended for Schema 7 | Candidate, current authority, frozen quantity, execution eligibility and reasons |
| `POST /api/v1/simulated-trades` | Existing explicit signal command; server resolves the linked approval and verifies it atomically | Existing whole simulation receipt; never accepts a client assertion of approval |

A preview is evidence of what was displayed, not a reusable grant. The service must revalidate all authority and quantity gates when approving. The client cannot submit a different quantity with APPROVE. REJECT is allowed for a still-current PENDING candidate without a successful quantity preview.

Repeat the same command and body to receive its original receipt; a changed body with the same key is rejected. Different keys cannot approve or consume the same occurrence twice. In-flight or stale-revision conflicts return `409`; invalid/unsupported quantities or malformed input use existing `422` validation conventions; unknown resources use `404`. Keep the existing structured error envelope and unavailable-service semantics. Do not turn server/storage failure into an empty successful state. Persist idempotency evidence for at least the lifetime of the occurrence and its execution audit; do not allow key expiry to reopen an event.

Distinguish `EXCEPTION_DISABLED`, `EXCEPTION_APPROVAL_REQUIRED`, `EXCEPTION_QUANTITY_REQUIRED`, `EXCEPTION_QUANTITY_INVALID`, `EXCEPTION_APPROVAL_STALE`, `EXCEPTION_REJECTED`, `EXCEPTION_REVOKED`, `EXCEPTION_EXPIRED` and `EXCEPTION_CONSUMED`, alongside existing market/condition/capacity/risk reasons. Conditions that are false and evidence that is unknown remain distinguishable. `authorized_quantity=0` is not an executable action. Normal or ordinary WEAK routes do not acquire approval dependencies.

## MLP1-10 — Extraction and user workflow

1. Extraction preserves both source exception clauses, constraints and expanded definitions. It may draft per-route permission only from source or a reviewed supplement. It cannot create approval events, infer a broken-route quantity, or convert an exception into an ordinary buy/reviewed fact. Update, preparation and plan inheritance paths preserve this boundary too.
2. Plan review shows each route's enabled/disabled intent and quantity semantics. Explicitly disabled routes may coexist with enabled ordinary routes without deleting source meaning. Missing definitions/Q0, unsupported timing, fabricated approval or dropped constraints block complete review. A source clause allowing future reassessment does not supply occurrence approval; an empty broken-route Qe is expected until that occurrence is reviewed.
3. Runtime shows “eligible, awaiting your approval” only after technical eligibility is established. It also shows route, D/expiry, reference index, market and STRONG operands, S1/S2 evidence, Q0, proposed quantity, capacity, risks and blockers. Technical unknowns cannot be resolved with an approval button. Surface server unavailability distinctly.
4. Weak exception quantity is read-only. Broken exception quantity starts empty and has inline legal-grid/ceiling feedback. The human enters a reason, previews, then confirms the exact displayed quantity. The confirmation states that approval alone makes no simulated trade. Rejection and revocation are explicit separate actions.
5. The approved view shows frozen quantity, original window and current execution blockers. Actual simulation still requires its existing explicit action. Notification receipt, acknowledgement, refresh, review and activation never approve or trade. Retries/restart restore the same candidate and state. One occurrence uses stable reminder identity; send-time checks suppress obsolete approval/execution prompts. Independent five-minute reminders remain unaffected.

## MLP1-11 — Frozen replay and evidence

Live evaluation and replay share the same eligibility, quantity and authority policies. A replay run freezes plan/review identities, stock/index/fact data, official grid version, calendars, and an ordered `exception_authorization_events` stream. Each event binds the exact occurrence and quantity and has a usable timestamp no earlier than its admissible evidence. Approval, rejection, revocation and consumption order is deterministic. Never query the current local approval database during frozen replay.

Without matching events, report eligible-but-unapproved and zero exception trades. Imported recorded events use provenance `RECORDED_LOCAL`. Explicit hypothetical events use `RESEARCH_SCENARIO`, are saved before the run, and are labeled as assumptions in setup and results; they cannot be exported as live authority or represented as historical human actions. P1 adds no automatic policy that approves every eligible event. Neither recorded nor research approval executes a trade by itself: the existing explicit replay operation script must also request execution within the original window.

Only events and evidence available by the replay cutoff may affect a decision. A later approval cannot authorize an earlier fill. Reject mismatched plan/route/quantity/evidence bindings and report unavailable historical rule/calendar scope rather than guessing. Identical frozen inputs, operation scripts and authorization events must produce the same decisions in runtime adapters and replay. Future data/event mutations cannot change earlier outputs. Existing job exclusion, cancellation, storage limits and atomic result publication remain in force.

## MLP1-12 — Acceptance criteria

| ID | Required evidence |
| --- | --- |
| MLP1-A01 | Schema 7 strict opt-in and source bindings; Schema 1–6 exact byte/hash fixtures and Schema 6 exception blocks remain unchanged; unsupported readers fail explicitly. |
| MLP1-A02 | Every market row, STRONG equality/unknown case, S1/S2 predicate and ordinary-route independence has deterministic expected outcomes. |
| MLP1-A03 | MLP1-Q01–MLP1-Q12 pass with independent arithmetic assertions; no upward ordinary rounding, over-Q0 sizing, non-100 quantity, capacity clipping or automatic broken-route quantity. |
| MLP1-A04 | Both source languages, negated permission, forged approvals, missing definitions, updates/preparation and inheritance preserve the exact review boundary. |
| MLP1-A05 | No approval through save/review/activation/facts/AI/acknowledgement; preview and approval bind exact evidence, quantity and revisions. |
| MLP1-A06 | Every lifecycle transition, independent-event restriction, expiry/holiday/window edge, delayed evidence and server-time/backdating case is verified. |
| MLP1-A07 | Real temporary SQLite proves atomic approval/revoke/execute races, same/different-key duplication, crash recovery and restart with at most one approval/consumption. |
| MLP1-A08 | Consumed-value/basis corrections invalidate authority; harmless receipt/Decimal changes do not; stale queued notifications and stale reads cannot expose authority. |
| MLP1-A09 | Execution rechecks full quantity, current quote/calendar/tradability, risk, T+1, CORE, inventory and plan authority; local/actual/backtest inventories remain isolated. |
| MLP1-A10 | Generated API/types and both UI contract profiles preserve existing projections; invalid/stale commands have precise errors, service faults are not disguised. |
| MLP1-A11 | Real-browser journeys cover both exception approvals and separate simulation, rejection/revocation, errors/retry/restart, disabled routes and unaffected ordinary/five-minute paths. |
| MLP1-A12 | Frozen replay proves missing/late/revoked/mismatched approval gives no fill, research assumptions are labeled, and future mutations do not alter earlier decisions. |
| MLP1-A13 | Backend non-live regressions, frontend tests/type-check/build, generated-artifact checks and browser acceptance pass without weakening existing tests or thresholds. |
| MLP1-A14 | Paired specs/tasks/operations/prompt capability text and final verification match actual implementation; results distinguish local acceptance from live certification. |

## MLP1-13 — Engineering conventions and verification

Retain Python 3.14, strict immutable Pydantic models, Decimal/integer arithmetic, FastAPI/SQLite, Vue 3/TypeScript, pytest/Vitest/Playwright and current dependency pins. Domain policy stays under `src/trade_plan_monitor/domain` and `decision`; authority and atomic persistence under `state`; runtime/adapters under `runtime`, `web` and `backtest`; UI under `web/src`; deterministic tests under `tests/unit`, `tests/integration` and `web/tests`. No new dependency is proposed.

Use snake_case and narrow pure policies, for example `validate_exception_quantity(route, base_quantity, proposed_quantity, market_grid)` with explicitly supplied typed inputs and no clock, database or provider reads. Keep network I/O outside transactions. Extend server models first and generate frontend types rather than duplicating authority in Vue. Testing commands and implemented test ownership are specified in [MLP1-P02](../../../tasks/market-linkage-p1.md#mlp1-p02--verification-command-catalog); executed results and final repair evidence are recorded in the verification report.

Always: preserve source meaning, independent-signal limits, exact frozen quantities and bilingual parity; verify before marking tasks complete. Seek a specification amendment for changed quantities/expiry, automatic approval, broader execution/provider scope, dependencies or destructive storage changes. Never: fabricate approval, weaken tests, rewrite old authority or use user databases for acceptance. Implementation is authorized. Live-provider calls, push and deployment are not authorized.

## MLP1-14 — Review and completion gate

MLP1-D01–MLP1-D06 are approved, including exact-minimum weak sizing, manually chosen broken sizing up to Q0, the terminal lifecycle and explicit-event replay. Amendments must update both languages before dependent implementation.

Under the user approval and implementation instruction, MLP1-T01–MLP1-T21 and MLP1-C01–MLP1-C07 are complete. The six approved decisions are unchanged. See the [contract inventory](CONTRACT-market-linkage-p1.md) and [executed verification](../../verification/2026-10-24-market-linkage-p1.md), including full-regression failure reconciliation, all fourteen acceptance criteria and the distinction between local acceptance and live certification.
