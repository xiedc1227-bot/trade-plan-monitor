# Fourth-source risk withdrawal audit — 2026-10-17

Historical record: the execution boundary in RW-V04 was completed on 2026-10-18. A newly reviewed scoped chain and continuous replay are recorded in [CR-V01–CR-V05](2026-10-18-cohort-risk-execution.md); the original evidence below is retained unchanged.

## RW-V01 — Source conclusion and correction of earlier acceptance

The fourth source does **not** authorize cancelling the entire inherited ordinary exit. It describes 25.99 as an already-broken former core risk line, now a structural-recovery reference, and explicitly says it is not a direct stop for **new positions**. The third reviewed policy retains the earlier 25.99 ordinary exit: two official closes, core/tactical targets both zero, and `RESUME_FIRST_CLOSE` after suspension. The third source also warns against cancelling risk protection merely because of a rebound. The fourth source's 24.20 instruction is to remain out of the market; it is not a replacement stop.

Neither global cancellation nor unrestricted inheritance is a faithful executable interpretation. Preserve the prior evidence, but do not apply its whole-position exit to newly opened holdings. Zero source holdings do not authorize removing a rule, and later source holdings must not reset the replay ledger. No further manual source facts are needed to identify this scope restriction.

Earlier GI-V04/GI-V05 acceptance and RC-V02's cancellation row described a frozen policy that passed then-current checks. They do **not** prove that the cancellation was source-correct. Their report remains historical evidence; it is not a corrected replay.

## RW-V02 — Causes and generic repair

Three causes were reproduced:

1. A legacy exact-sentence exception treated demotion of a price reference as permission to revoke its entire risk branch. The exception is removed.
2. The previous local verification helper explicitly instructed the model to revoke the old exit and clear its risk-line fields. This was an incorrect reviewer diagnosis. The helper is retired with an execution guard; its original prompt remains available as audit evidence. The new verification uses neutral instructions.
3. A fresh real response correctly supplied `RETAIN`, `scope_assessment: PARTIAL_RULE` and `intent: CONTEXT`, but normalization discarded context-only retention operations together with the scope restriction. Scope-bearing operations now survive normalization.

The private `monitor-loop-delta-wire-v4` requests an applicability assessment for every predecessor risk branch. `ENTIRE_RULE`, `PARTIAL_RULE`, `CONTEXT_ONLY` and `UNCLEAR` distinguish entire-rule authority, partial applicability, background context and genuine ambiguity. Missing assessment is an AI processing error eligible for bounded correction. Only an entire-rule assessment can authorize whole-rule withdrawal. Partial scope preserves the prior branch and price evidence in an **unapproved candidate**, with `UPDATE_PARTIAL_SCOPE_UNSUPPORTED`; it is not retried into a guessed full-rule answer or presented as missing source facts. Unclear applicability remains unresolved even when the proposed action is retention.

Previously frozen history remains readable with its original hash. Reusing an old library entry as a predecessor or in a newly composed selection is rechecked under current validation and returns `REVIEWED_RISK_SCOPE_RECHECK_REQUIRED` when it fails. Historical validation is unavailable for unreviewed records. No historical policy, source, report or account was rewritten.

## RW-V03 — Actual and regression evidence

The existing authorization covered the exact fourth original and the reviewed third-source context sent to official `api.deepseek.com`, model `deepseek-flash`. Two fresh calls returned HTTP 200. The first exposed a missing applicability audit. The second returned the partial-scope retention described above; its unedited response was replayed offline after the normalizer repair. Local request/response evidence is under `data/verification/2026-10-17-risk-scope-audit/`; no credential headers are retained. `tests/fixtures/ai/risk-scope-fourth-live.json` contains the unchanged second response and its source/base inputs.

The corrected real-response candidate has exactly one review issue: `UPDATE_PARTIAL_SCOPE_UNSUPPORTED: risk_branches.ORDINARY_TECHNICAL`. It preserves 25.99 and the predecessor exit evidence, retains the two 100-share entries and their `AFTER_RULE_COMPLETED` order, and does not ask for exit policy, exit scope or suspension facts. Its normal stored candidate codec remains bounded and marks it non-executable.

All four saved original-source responses were replayed: the first three retain their validated outcome; the old fourth withdrawal now fails the missing-scope check. Differently worded Chinese and English cases cover partial scope with both `REVOKE`/`RETAIN` and `ASSERTED`/`CONTEXT`, explicit whole-rule cancellation, missing assessment and unclear scope. Focused scope/decoder/four-source tests: **62 passed**. Preparation review/library/source-confirmation regressions: **109 passed** before the additional history-boundary tests. The shared Windows temporary directory denied access; rerunning with a new project-local test directory resolved that environment error.

The actual old fourth frozen manifest remains `4f123bba726a4bf7acf2a0254e313044bb2e5ab3ba1497a980529aab0fc13efa`, all four library records remain readable, and attempting to reuse that fourth entry now returns the scope recheck error.

Final compatibility/history/automatic-correction/contract tests: **76 passed**. Frontend preparation/library/confirmation tests: **108 passed**. Targeted Ruff checks, both generated-contract checks, frontend type checking and production build passed. The local service was restarted after confirming its job list was empty; monitor-contract-2 health and the historical result endpoint both returned HTTP 200. The new server process is `90016`. This is deployment of the validation/presentation repair, not execution of a corrected strategy.

## RW-V04 — Remaining execution boundary

The execution model currently targets whole core/tactical buckets, without entry-cohort or plan-version applicability. This change repairs erroneous cancellation and lost scope metadata; it does **not** implement scoped exit execution. The candidate clearly explains this system limitation without asking the user to invent a stop or repeat known facts. No newly corrected four-plan continuous replay has been published. The earlier 0-fill report cannot be used as proof that this scope repair has been executed successfully.
