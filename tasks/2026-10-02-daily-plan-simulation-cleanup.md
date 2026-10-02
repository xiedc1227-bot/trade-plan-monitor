# Daily simulation cleanup — 2026-10-02

Canonical English; paired copy: `2026-10-02-daily-plan-simulation-cleanup.zh-CN.md`. Status: COMPLETE. The user explicitly corrected the product scope and authorized cleanup. No further approval is required. Authority: [SPEC-daily-plan](../docs/specifications/monitoring/SPEC-daily-plan.md) D01/D02/D06/D08–D10 and DP-A01–DP-A20; existing module/task IDs remain stable.

## C01. Product contract

This is monitoring plus simulation. A reminder never changes holdings. A separate user command validates current plan/review, ordinary signal or technical risk cause, inventory revision, quote, trading session, T+1, CORE scope and max quantity. The offered positive100-share-multiple quantity succeeds completely in one transaction or fails with zero mutation. Ordinary simulation consumes the whole original signal once. Risk simulation consumes the full currently offered whole-lot reduction across server-derived affected buckets; unavailable holdings remain a risk obligation. There is no broker submission, partial result, uncertain order or asynchronous order status.

`POST /api/v1/daily-simulated-trades` accepts exactly `planVersionId`, `causeId`, `expectedCauseRevision`, `expectedInventoryRevision`, `quantity`, with `Idempotency-Key`. Side, scopes, internal batch debits, current verified price and server time are derived. Response includes `simulationId`, side, quantity, `priceFen`, `simulatedAt`, inventory revision/current result and ordinary consumption where applicable. Same-key retry returns the same receipt; a different key cannot reuse consumed ordinary authority. Body/quantity invalidity is422, current-authority/revision conflict409, missing resource404. No new manual/unlinked trade API or cash ledger is added.

`POST /api/v1/daily-position-confirmations` becomes minimal simulation initialization: `symbol`, `coreQty`, `tacticalQty`, `expectedRevision`. Quantities are nonnegative100-share multiples; the baseline is pre-settled simulation stock, available at the first certified open session at/after setup. Subsequent buys use their real simulation date for T+1. Do not accept `outstandingComplete`, `includedLotIds`, `openingAllocations`, manual sellable values or broker proof. Exact retries do not add stock; conflicting setup cannot overwrite existing simulated trades or consumed signals.

Field-specific whole-lot checks also cover initialization CORE/TACTICAL, `max_qty`, position/ordinary/risk targets, sellable and displayed executable quantity:0 or a multiple of100, with trades strictly positive. Do not globally change `Qty` because revisions/counters share it. Technical-risk `PENDING` is retained for official-close timing; only broker-order statuses are deleted.

Delete configurable `buy_min_qty`, `buy_increment`, `sell_increment`, `odd_lot_liquidation` and broker-rule `evidence`/`as_of`. The software fixes100-share units, `settlement=NEXT_EXCHANGE_SESSION`, `tick_size_fen=1` and `special_state_restrictions=BLOCK_UNVERIFIED`; source review binds these as product constants. Neither AI nor UI asks the user to configure broker rules or attest them for each plan. Do not introduce a new global policy/evidence confirmation layer.

## C02. Storage and compatibility

Use existing generic daily storage for simulation-tagged `POSITION` plus `SIMULATION` receipts, with a daily-only revision and only acquisition-date batches needed by T+1/newest-first risk. No writes to legacy/shared `PositionLot`, `PositionInventoryConfirmation`, opening balance, real inventory revision or legacy sync. No implicit copy of real holdings into simulation. Old Schema1/2/3 readers and commands retain their behavior.

The unpublished0024 CHECK/model may recognize `SIMULATION` in place for fresh development databases. No new migration sequence, destructive rewrite or production database inspection. Existing incompatible development layout must fail explicitly before mutation. Old `REPORT`, broker `POSITION`, partial/unknown/filled signals and old evaluation heads remain evidence, never simulated receipts or500 errors. For affected symbols, return `409 DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED` on setup/simulation and a bounded obsolete-data read result; keep technical risk/source history visible. Do not erase old consumption, create a reset wizard, replay old fills or auto-convert a database. Fresh fixtures may be recreated.

## C03. Delete and retain boundaries

Delete daily-specific broker execution-report route/service/contracts, external/report order identity, PENDING/CANCELLED/UNKNOWN order transitions, partial40+60/new-order remainder math, BUY/SELL reservations, unknown-order capacity, outstanding-order assertions, client lot allocation/debit fields/forms, broker execution price/time/evidence inputs and fixtures/tests whose only purpose is that removed model. Removing these now-authorized tests is scope cleanup, not weakening retained strategy requirements. Remove obsolete generated client fields and hidden handlers too. Do not keep a compatibility alias from reports to simulated trades.

Retain technical facts and official tradability/suspension evidence (not broker proof), source review/activation, official complete close, next exchange-session expiry, independent-event/reset lineage, durable consumption, max300 example, CORE-only protection, T+1, ordinary first-breach/next-close risk timing, severe two-evidence timing, target fulfillment/reassessment, distinct risk cause/outbox authority and the repaired500-observation/3033-date recovery boundaries. Fundamentals remain excluded; index behavior and frozen schemas/prompts/formulas remain unchanged. Internal minimal simulation batches are implementation data, not user-facing execution-tracking controls.

## C04. Ordered work and verification

| State / ID | Slice and required proof |
|---|---|
| [x] DSC01 | Tighten unpublished daily simulation model/API contract and remove old report/order fields; DP-A11/12 shape/quantity rejection, old-schema fixtures unchanged. |
| [x] DSC02 | Replace daily accounting with isolated position/receipt transactions; prove full100 once, rollback, conflicting revisions, max300, T+1 and no legacy table writes. |
| [x] DSC03 | Rewire lifecycle/risk/runtime/delivery to simulated consumption without reservations; preserve risk invalidation/cause/recovery and new independent signals; obsolete development data controlled. |
| [x] DSC04 | Replace API/UI broker forms with aggregate setup and explicit full simulation; server chooses internal batches; regenerate both OpenAPI/TypeScript contracts. |
| [x] DSC05 | Replace removed-model tests with DP-A11/12/18/20 whole-lot simulation oracles, real temporary-DB production integration and real browser journey; keep source/technical/legacy/index tests. |
| [x] DSC06 | Independent Astra high review → Sol fixes → Astra re-review; fresh relevant/full gates chosen by coordinator; paired2026-10-02 verification records actual commands/counts and historical-scope separation. |

Keep each implementation slice small; split mechanical generated files from behavior. Existing files may be simplified or deleted when daily-only; shared legacy APIs and their tests are not cleanup targets. Run focused unit/API/transaction tests as each slice stabilizes, then frontend unit/type/build, both contract checks and Chrome. Full-command baseline remains `.venv/Scripts/python.exe -m pytest -q -m "not live"`; the coordinator schedules it after source/review stabilizes rather than repeatedly rerunning the unchanged53-minute capacity group after every doc/test addition.

## C05. Acceptance and handoff

DP-A01–DP-A20 are retained. DP-A11 now proves atomic BUY100/whole-unit rejection/nonmutating reminders; DP-A12 proves current simulated capacity, T+1/CORE and absence of order contracts; DP-A18 proves transaction/race/restart/dedup plus preserved obsolete development evidence; DP-A20 proves the real user-triggered simulation UI and absence of broker tracking. Other criteria remain required under current simulated-position vocabulary. No former40+60/UNKNOWN test result establishes these new criteria.

The2026-10-01 feature/independent-review reports and6065-pass backend result remain historical achievements for the superseded scope, not approval of this cleanup. Keep their content with a scope-change notice. Start Sol/high implementation after both language copies of this design, specification, capability map, plan and task list are saved. No live calls, production data access, commit, push or deployment is authorized.
