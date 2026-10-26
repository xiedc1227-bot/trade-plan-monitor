# Verification: market-linkage-p3

Status: IMPLEMENTING. MLP3-T01–T10 and C01–C03 complete; T11–T24/C04–C08 remain unexecuted. User approved MLP3-D01–D06 and implementation. Baseline `c9ad16aa352d9bdb5ec49f16cd9fcd90151f9c46`. [Chinese copy](2026-10-26-market-linkage-p3.zh-CN.md) · [tasks](../../tasks/market-linkage-p3.md).

## MLP3-V01 — Contracts and historical boundary

T01 V01:98 passed,1 existing Starlette warning,3.00s. Retained the exact normalized original source and five critical excerpts in tests/fixtures/p3_original_prompt.json; independent snapshot/hash test passed. T02 source-defined OPEN_COST_CAP/MARKET_VALUE_CAP and CAPITAL_ONLY/QUANTITY_AND_CAPITAL variants, strict integer bounds, fee applicability/consistency, scoped BUY and nullable-draft collection tests passed with baseline:121 passed,1 warning,3.64s. Initial implementation tests failed on missing new modules. The initial positive fee fixture named a different synthetic security; its explicit applicability was corrected, with the separate mismatch rejection preserved.

T03/C01:223 passed,1.97s, including private Schema9 round trips, exact plan-review-content-v6 independent hash, missing-cap review blocking, explicit public9 rejection and historical model/codec tests. Public current/frozen admission is still closed; pure models and review/hash preparation are not shipped executable support. P0/P1/P2 bytes/authority remain the regression baseline.

A restricted Windows local-communication regression process stopped progressing after69%; only its exact owned test processes were terminated. The expanded group completed in an environment allowing local communication. Interrupted runs are not passes. No test was skipped or weakened. Ruff passed for the new contract/source files. Exact later commands and logs will be archived at final acceptance; downstream tests are not yet created or claimed.

## MLP3-V02 — Remaining acceptance

MLP3-A01/A02 have stage-specific source/contract evidence; full current authority, budget book, exact capital predicates, transaction gates, APIs/UI, frozen replay and complete regression remain pending. Do not infer implementation completion from the approved specification or stage-only tests. No user database, live provider, deployment or push is involved. Preserve tasks/plan.md and tasks/todo.md.

## MLP3-V03 — Pure capital and basis policies

T04 exact buy-debit helper/P2 fee goldens:23 passed,0.47s. T05 capital predicates with P2 regression:38 passed,0.58s. A negative-basis test caught an incorrect chained comparison; corrected explicit integer/sign/bound checks reject negative costs. T06/C02 combined core/historical policies:157 passed,1 warning,3.15s. Exact cost/value equality and rejection, whole quantities, unknown versus unbounded share capacity, cost-release lot selection, unknown lots and ten whole sales conserving987654321fen are covered. The deliberate > to >= cap mutation failed the independent equality tests; exact original code was restored. Public9 remains closed; storage/runtime/API/replay still pending.

## MLP3-V04 — Durable budget and inventory continuity

T07 temporary-storage migration/reopen/hash/backup/downgrade group:5 passed,2.24s. T07/T08 expanded storage and opening service:14 passed,2 metadata-reflection warnings,3.03s. T09/C03 with original whole-simulation/cohort-risk regressions:45 passed,3 existing warnings,14.50s. Opening/reconciliation is explicitly confirmed and server-timed; retry returns the original receipt without inventory/approval effects. Exact actual allocations release historical basis, old-version buys/mismatches retain unknown cost, known empty inventory creates the budget only inside the first explicit buy, and a post-write fault rolls back both stores. Positive test fixtures were corrected to use the actual calendar fields and unique audit IDs; no production constraint was relaxed. Public9 remains closed. All migrations used disposable SQLite, never user data.

## MLP3-V05 — Source extraction and review

T10 draft/source compatibility:46 passed,1 warning,2.68s. Current extraction, P3/P2 source review and untrusted-source isolation:58 passed,1 warning,3.31s. Explicit cap meanings and exact fee percentages are required; ambiguous total investment, negated modes and mismatched source rates are rejected. The existing 50,000-character input budget remains unchanged: redundant instructions were shortened after the original budget test caught an overrun. Both original prompt sizes and current extraction security pass. Ruff and diff whitespace checks passed. Public executable9 remains closed pending the complete current authority chain.
