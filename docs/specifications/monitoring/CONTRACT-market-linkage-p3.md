# Contract: market-linkage-p3

Status: implementation contract — 2026-10-26. [Approved specification](SPEC-market-linkage-p3.md) · [Chinese copy](CONTRACT-market-linkage-p3.zh-CN.md). No new strategy threshold is introduced.

## MLP3-K01 — Version and position ownership

Schema9 / condition-plan-v5; review domain plan-review-content-v6; extraction plan-extract-v12. P3TradePlan extends the Schema8 contract with a replacement position model, not an inferred max_qty. `position.limit.mode=CAPITAL_ONLY` requires capital_policy and forbids max_qty; QUANTITY_AND_CAPITAL requires both max_qty and capital_policy. Existing optional allocation fields retain their source semantics. Every BUY must use the existing daily linked TACTICAL P2Rule; ordinary SELL and technical-risk branches retain their scope. Share-only plans stay in their existing schema. Public and frozen9 admission remain gated separately until their complete chains are ready.

## MLP3-K02 — Policy and exact predicates

Capital policy common required fields: policy_version=capital-policy-v1, currency=CNY, scope=SYMBOL_CORE_AND_TACTICAL, account_scope=SIMULATION, positive cap_fen. OPEN_COST_CAP additionally requires buy_cost_schedule: the exact P2 FeeSchedule; MARKET_VALUE_CAP instead requires valuation=CURRENT_ADMITTED_QUOTE and forbids a cost schedule. Matching P2 economics schedules must have equal canonical content, not only the same ID. Money-only permits no synthetic max_qty. Decimal inputs remain strings. Strict integer quantities/fen retain 9007199254740991; lot bound500, event/operation bound10000. Unknown is explicit, never zero or unbounded.

Calculate source-selected q first. Cost: after=K+q*(p+buy_slippage)+buy_fees; value: after=(N+q)*p. Both use <=cap_fen. Explicit share maximum adds N+q<=max_qty. No clipping, resizing or cap-derived Q0. Capacity is BOUNDED(remaining_qty), UNBOUNDED(no share ceiling and known inventory), UNKNOWN; only the new capital-market-calculation-v1 carries this union. Historical quantity calculations retain capacity=int|null and their meaning. Capital assessment version capital-limit-evidence-v1 records policy hash, phase, exact q, quote, inventory/book revisions, occupancy, remaining amount and blockers, not BUY authority. capital-consumed-v1 binds semantic strategy inputs, never transient acquisition identities or a new independent signal.

## MLP3-K03 — Book and opening evidence

capital-book-v1 is per symbol and inventory stream, with own positive revision, inventory revision, initialized/reconciled times, complete lots and evidence hash. A lot has lot_id, bucket CORE/TACTICAL, positive whole quantity, retained_basis_fen (nonnegative safe integer or null), provenance receipt reference. Identities are unique by lot_id/bucket; complete quantities must equal the current inventory. Book aggregate overflow is invalid. No actual account or research cash inference.

Separate simulation_capital_book/current and simulation_capital_event/append-only storage share the inventory transaction. The event owns command ID, request hash, expected/resulting revisions, kind OPENING/RECONCILIATION/BUY/SELL/UNKNOWN_CHANGE, authoritative times, before/after hashes and source/assumption evidence. Unique command identity guarantees replay or conflict, never a second effect. Keep old daily-simulation-v1 payloads intact.

Opening input binds reviewed plan/version, expectedInventoryRevision, expectedBookRevision (0 only for absence), observedAt, provenance and complete sourced lot bases. Current server supplies received/reviewed/available time; no future observation or backdating. Nonzero unknown costs require explicit human reconciliation. Known initialized empty inventory derives K=0/bookRevision0 read-only; the first explicit BUY creates/debits in one transaction. This never initializes unknown holdings. Correction appends evidence and preserves completed effects.

## MLP3-K04 — Allocations, unknown history and atomicity

BUY records the exact budget debit under the frozen applicable schedule. SELL uses the inventory's actual selected allocations: released=floor(basis*sold/old_qty), residual stays with the residual lot, final sale releases all. Do not change newest-first/holding-scoped allocation, T+1 or CORE protection. Sale proceeds/profit do not increase the cap. Plan switches never reset basis; new fee schedules affect future buys. Older-plan buys with no P3 budget debit record unknown basis; old binary/revision mismatches are unknown until reconciled. Missing cost never becomes a value-cap or SELL prerequisite.

One transaction revalidates current inventory/book/policy/quote, updates both ledgers, consumes exactly one whole signal and commits receipt/outbox. Same key/body replays original; changed body/in-flight/version conflict409. Failure leaves no partial inventory, budget, event or consumption. Preview/review/approval reserve nothing. Ordinary and P1 exception quantities remain frozen; only an eligible current full quantity can execute. Risk SELL bypasses BUY money predicates; actual storage failures remain atomic errors.

## MLP3-K05 — Interfaces and errors

GET /api/v1/simulation-capital-books/{symbol} reads a bounded current simulated resource. Missing book with known positive inventory is UNKNOWN; it is not an invented zero book. POST /api/v1/simulation-capital-openings is an explicit idempotent human command, never plan activation. Its receipt contains inventoryChanged=false and authorityGranted=false.

POST /api/v1/plan-capital-previews accepts planVersionId, ruleId, optional occurrenceId (exception candidate_id), proposedQuantity only for BROKEN_STRONG. Reject client prices/bases/capacity/approvals. It returns computedAt, planVersionId, ruleId, quantity, evidence, assessment and literal authorityGranted=false, writes nothing and grants no receipt usable for execution. Missing/stale current authority409, malformed body422; existing structured admission errors and byte limits remain. Exact types are generated only after guarded endpoints exist. Current context changes discard late UI responses.

## MLP3-K06 — Frozen research and evidence bounds

backtest-run-v10 carries Schema9, frozen opening facts, explicit capital reconciliation events and separate simulations/exception authorizations. capital-exception-event-v1 owns the new calculation proof; old frozen-exception-event-v1 remains strict. Reconciliation events have provenance RECORDED_LOCAL/RESEARCH_SCENARIO and ordered available/received times; future facts cannot fill past gaps. No mutable current book/fee source lookup. Keep actual research settlement/cash/P&L distinct from estimated budget basis, including position-limit-only funding without fake max_qty/cash.

Retain 32KiB result items and existing overall source/input/report limits. Size-admit before enqueue/authority changes. Shared proofs must resolve and revalidate full evidence; no truncation or dropped proof. Unsupported old readers reject9. Additive migration tests use temporary databases; downgrade preserves new evidence and blocks9. User database migration, live providers, deployment and push are not authorized.

## MLP3-K07 — Execution seams and stage evidence

T01 baseline V01:98 passed,1 existing Starlette warning,3.00s. Freeze source hash/excerpts in tests/fixtures/p3_original_prompt.json and verify independently. Follow sequential model/hash → pure fee/capital/basis → storage/opening/atomic accounting → extraction/runtime/exception guards → guarded HTTP/generation → UI/browser → frozen readers/workers → full regression/documentation. Do not enable9 by changing every schema set before its guard chain exists. Preserve tasks/plan.md and tasks/todo.md.

## MLP3-K08 — Implemented current API ownership

The current API owns CapitalBookView, CapitalOpeningApiCommand, CapitalOpeningReceipt, CapitalPreviewCommand and CapitalPreviewView in web/p3_schemas.py; the domain continues to own immutable capital books, events, assessments and strict opening commands. Only the three K05 routes are added. Both OpenAPI profiles and generated TypeScript files expose the same P3 operations. Capability supportedSchemaVersions adds9 and capitalExecutionVersion=condition-plan-v5; the editor adds capitalCandidateSchema. Existing fields/routes remain. Public current9 admission follows complete ordinary, exception and HTTP guards; old frozen-input unions still reject9 until T19/T20. JSON times/lists are converted at the API edge, with strict domain numbers and complete500-lot bounds retained. Economics previews also accept current9 and continue to grant no authority.
