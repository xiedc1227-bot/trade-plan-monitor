# Risk exits by holding cohort

## CR-01 — Policy and evidence

An explicit exclusion of newly opened positions narrows the inherited risk rule to lots acquired before the confirmed effective trading day. Keep its price, targets, suspension policy, confirmation evidence and original source. Future entries follow the new plan's explicit risk rules; absent new-position stop authority remains absent. Initial holdings belong to the opening cohort even when their original acquisition date is unknown. Later stated holdings never reset the ledger. Scope is determined from reviewed source meaning and the confirmed effective day, not exact phrase matching or a new manual confirmation.

Add optional `holding_scope` (`BEFORE_TRADE_DATE` / `FROM_TRADE_DATE`, `trade_date`) to unified risk branches, with optional stable `rule_id` and per-branch price override for distinct old/new rules of the same kind. Omitted fields preserve historical serialization and hashes. Existing unscoped rules keep their behavior. Non-overlapping variants may retain different risk parameters; risk identity and latched confirmation remain separate. At most 64 unified risk variants retain the existing 64-operation and 500-lot bounds. Schema 4 plan contracts remain unchanged.

## CR-02 — Execution

Risk evaluation and fulfillment use only matching lot quantities. New lots record the originating plan version. T+1, calendar, tradability and known sellability remain authoritative. A blocked old lot cannot be replaced with a sale of an excluded new lot. The authorized action records exact lot allocations; execution recomputes and checks them atomically. Overlapping confirmed obligations cannot double-sell a lot. Closing eligible old holdings fulfills that obligation even if excluded new holdings remain. Preserve pending/confirmed evidence across plan switches without widening a narrowed scope.

## CR-03 — Verification and presentation

Verify old/new mixed lots, unknown opening acquisition dates, settlement restrictions, explicit new stop rules, persisted pending obligations, exact debit/cost accounting and historical compatibility. Replay the four actual originals using neutral extraction and the previously confirmed dates and suspension policy, review the resulting chain and execute a new continuous run. No source or model response may be edited into acceptance. Report actual fills and blockers, including genuine unquantified conditions; a zero-fill actual run needs deterministic mixed-lot execution evidence as well.

Result pages show risk applicability, inherited protection and lot-specific exits, alongside existing rule comparisons and price diagnostics. Keep old frozen runs historical and publish a separately identified new run. Update matching English/Chinese specifications, operations and verification records. Restart and inspect the updated local result page.

## CR-04 — Completion record

CR-01–CR-03 are complete. The actual fourth source retains the 25.99 old-holding exit before 2026-10-09 and excludes newer buys. Its unchanged live AI correction, reviewed four-plan chain and new continuous run are verified: 1468 evaluations, 0 fills, no scope-processing blocker. Production mixed-lot tests prove old-only debits, T+1, pending confirmation, separate new risk parameters, cost accounting and fulfillment with new holdings remaining. The restarted result page and actual library have been checked; the old fourth cancellation remains historical, not reusable authority. No new manual source confirmation was needed. See [CR-V01–CR-V05](../docs/verification/2026-10-18-cohort-risk-execution.md) for run identities, all checks and bounded capacity exclusions.
