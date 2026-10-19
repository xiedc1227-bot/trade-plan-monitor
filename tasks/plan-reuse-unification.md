# Plan reuse implementation

## PRI01. Authority and scope

The user approved PRU01–PRU11 on 2026-10-19 and explicitly requested removal of `POST /api/v1/plan-imports`. Execute the bounded work without another stage approval. Existing incomplete/unrelated plans and working changes are preserved. Canonical design: `../docs/specifications/backtesting/SPEC-plan-reuse-unification.md`.

## PRI02. Ordered slices and verification

- [x] S1: Add validated workbench selection/context, immutable storage and old-store upgrade tests.
- [x] S2: Expose freeze/read and adapt data/run commands; copy selections into result input and preserve old artifact bytes.
- [x] S3: Connect a structured workbench form to automatic data/run; preserve prepared single/continuous workflows and recovery.
- [x] S4: Remove the JSON/YAML import API and its direct clients; regenerate contracts and update affected expectations.
- [x] S5: Run focused/full offline tests, type/build/contract checks and browser acceptance; record bilingual evidence.

## PRI03. Boundaries

No rule, account transition, prompt, task-limit or legacy-report changes. Workbench runs remain single-version. Original multi-plan chains and source stores retain their existing review/lineage semantics. Add at most one selection table to the preparation database. Use focused failing tests before behavioral edits. Do not commit unrelated pre-existing changes.

## PRI04. Completion evidence and limits

S1–S4 are implemented. S5 checks were executed and findings recorded in [verification](../docs/verification/2026-10-19-plan-reuse-unification.md); this checkbox records execution, not a claim that all broad gates are green. The final frontend suite, API/selection/contract checks and original continuous Chrome journeys pass. Wider Chrome cancellation audits and the uncompleted capacity benchmark remain explicitly documented. No unrelated implementation was added to clear those gates.

## PRI05. Cancellation audit follow-up

- [x] CA01: Reproduce a fully consumed response reported as aborted; identify Chromium issue `568852319` and official fix `8508456`.
- [x] CA02: Pin isolated Chrome for Testing `157.0.8103.6`, provide explicit local setup, preserve system Chrome and all application/original browser-test bytes.
- [x] CA03: Keep zero-failure audit assertions, 5-second expectations and zero retries; pass three rounds of 1000 complete reads, separated EOF and real-cancellation negative controls.
- [x] CA04: Re-run original multi-plan continuous and historical-result browser journeys; record exact results in verification PR-V05.

The distinct 320px/200%-text layout failure and uncompleted capacity certification are outside this cancellation follow-up; retain their original gates and evidence.

CA04 result: 15 passed / 1 retained layout failure; no cancellation-audit failures. All 5 real journeys, including four-plan account/cash/equity continuity, passed. PR-V05 records the exact evidence.


## PRI06. Narrow-layout follow-up

- [x] LA01: Reproduce the unchanged 320px/200%-text gate and use R13 measurements/screenshots to isolate dataset-filter input overflow.
- [x] LA02: Add only scoped input shrink/width styles; preserve scripts, templates, filter semantics, AppShell and all original test gates.
- [x] LA03: Pass the original 16-combination layout gate, review before/after screenshots, and pass frontend unit/type/build checks.
- [x] LA04: Re-run original multi-plan continuous, historical-result and cancellation-audit browser checks; record exact results in verification PR-V06.

LA04 result: all 19 browser checks passed (7.1m), including all 5 real journeys and original history/cash/equity assertions. PR-V06 records the evidence.


## PRI07. Final review before scoped commit

- [x] FR01: Exclude pre-existing retention wording, temporary files and browser/build caches; retain only the approved plan-reuse and follow-up changes.
- [x] FR02: Independently review legacy hashes/codecs, copied historical inputs and prepared multi-plan boundaries; fix the first-reader BUSY/LOCKED mapping and verify six fault/retry cases.
- [x] FR03: Finish exact-candidate offline compatibility/browser checks and record final evidence in PR-V07 without weakening gates.
