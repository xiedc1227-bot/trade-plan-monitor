# Verification: market-linkage-p1

Status: PASS — MLP1-T01–MLP1-T21, MLP1-C01–MLP1-C07 and MLP1-A01–MLP1-A14 are complete. MLV1-23 is the final result; earlier entries preserve chronological failures and intermediate checkpoints, not outstanding work.

## MLV1-01 — Scope and authorization

The user approved MLP1-D01–MLP1-D06 and ordered staged implementation on 2026-10-24. Baseline `dbeff32`. This report records executed checks, not proposed results. [Specification](../specifications/monitoring/SPEC-market-linkage-p1.md) · [tasks](../../tasks/market-linkage-p1.md) · [Chinese copy](2026-10-24-market-linkage-p1.zh-CN.md).

## MLV1-02 — Baseline and boundary inventory

MLP1-T01: actual domain/draft/codec/hash/review/runtime/state/API/replay boundaries inspected; recorded in the paired [contract inventory](../specifications/monitoring/CONTRACT-market-linkage-p1.md). No user database or external provider was accessed.

Executed V01 from `trade-plan-monitor/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

Result: **91 passed in 1.20s**. The Python launcher emitted its existing installation-location diagnostic but the tests completed successfully with exit code 0. No P1 functional acceptance is claimed by this baseline. Remaining task results will be appended only after execution.

## MLV1-03 — Strict Schema 7 contracts (MLP1-T02)

RED: initial contract tests produced 9 failures / 1 pass for missing Schema 7 models/dispatch. New incomplete-draft and common-draft-constructor checks then failed twice before implementation. GREEN: 52 exception/linked/unified domain tests passed in 1.58s; 176 old plan/daily/bounded-codec tests passed in 0.45s. The unknown-version fixture now uses 8 because 7 is explicitly supported; the rejection assertion is retained. Targeted Ruff and whitespace checks passed.

The first expanded invocation named nonexistent `test_daily_plan_domain.py`; it ran no tests and was corrected to the actual test files. The default temporary directory failed initialization. An explicit workspace temporary directory fixed that issue; subsequent stack capture localized the remaining wait to Windows `asyncio` socketpair creation. Rerunning offline tests with local communication permitted succeeded. No application logic was changed to bypass the environment restriction.

Accepted commands (temporary paths are invocation-specific):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_unified_plan_domain.py -q --basetemp .test-tmp/p1-t02-accepted
.\.venv\Scripts\python.exe -m pytest tests/unit/test_plan_domain.py tests/unit/test_daily_plan.py tests/unit/test_bounded_validation_codec.py -q --basetemp .test-tmp/p1-t02-legacy-fixed
```

This accepts the strict domain/draft/codec/hash slice only. Source review, activation, runtime, approval and execution integration remain unchecked tasks.

## MLV1-04 — Pure eligibility and quantity (MLP1-T03 / MLP1-C01)

Added independent route/quantity fixtures before implementation; the missing module failed collection as expected. The quantity slice passed 24 tests. Two additional tests exposed a BROKEN candidate with no legal quantity under Q0; after adding grid feasibility admission, the combined V01–V03 suite passed **144 tests in 1.33s**, with targeted Ruff passing. Both P0 state/strength/confirmation equalities and the new exception boundaries are included.

Exact minimum substitution, no automatic broken-route quantity, legal choices on either side of half Q0, capacity/unknown/invalid-input blocks and ordinary-route independence are verified. Pure policies always return zero authorized quantity, even when eligible. MLP1-Q12's persisted stale/foreign approval scenarios remain assigned to authorization integration; no pure test is claimed as persistence acceptance.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_market_exception_policy.py tests/unit/test_market_exception_quantity.py tests/unit/test_market_exception_contract.py tests/unit/test_market_linkage_contract.py tests/unit/test_market_regime.py tests/unit/test_relative_strength.py tests/unit/test_confirmation_selection.py tests/unit/test_quantity_policy.py -q
```

MLP1-C01 accepts contracts and arithmetic only. Subsequent authority, runtime, UI and replay tasks remain incomplete.

## MLV1-05 — Source-bound extraction (MLP1-T04)

Schema 7 extraction now uses `plan-extract-v10`, requires complete exception definitions and per-route source permission, and cannot manufacture an approval. Negated permissions are checked for literal as well as interpreted bindings. Chinese and English definitions retain the same boundaries. Existing v8/v9 records remain readable.

RED: the expanded schema exposed a real 50,000-character input-limit regression; two prompt-budget tests failed. Shared identical schema definitions fixed the regression without increasing the limit or removing validation constraints. The final focused extraction, review, security and prompt-budget run passed **73 tests in 2.55s**; default-version regression tests passed **63 tests in 0.97s**. Full `ruff check src tests` passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_current_plan_extraction_security.py tests/integration/test_market_exception_review.py tests/integration/test_market_linkage_review.py tests/unit/test_current_review_contract.py tests/unit/test_preparation_prompt_budget.py -q --basetemp .test-tmp/p1-t04-verified
```

MLP1-T04 is accepted. Update/preparation, durable authority and all later checkpoints remain pending.

## MLV1-06 — Permission-preserving updates (MLP1-T05)

RED: four new tests failed for missing Schema 7 compact preparation and predecessor snapshot serialization; one authority-injection test already passed. Added explicit typed Schema 7 dispatch for compact preparation, delta prompts and predecessor contexts. Permission edits change review identity and unrelated source clauses cannot authorize them; plan copies reject occurrence authority. Missing permissions remain non-executable. One test initially expected an exception rather than the existing `to_executable()` return-None contract; its assertion was corrected to test that contract.

GREEN: **95 tests passed in 2.20s**, covering exception/linked review, exception updates, delta materialization, retained evidence, prompt budgets and existing preparation updates. Full Ruff passed. MLP1-T05 accepted; MLP1-C02 still requires durable storage acceptance.

## MLV1-07 — Durable state (MLP1-T06 / MLP1-C02)

RED: storage tests failed collection before the new models existed. Added closed candidate/event models, domain hashes, terminal-transition validation, immutable event writes and revision-fenced projections. SQLite's existing kind constraint required additive migration `0026_market_exceptions`; it preserves payload bytes, adds command uniqueness and refuses a downgrade with exception evidence. Tests use disposable databases only.

GREEN: 33 source/update/new-and-old-storage tests passed in 4.41s; after adding the durable command index, 9 storage regression tests passed in 3.72s. The final 5 new storage tests also passed. Verified rollback before commit, reopen, terminal reuse, unknown versions, modified hashes, immutable events, exact legacy bytes and cross-occurrence command uniqueness. Full Ruff passed. MLP1-C02 accepts source contracts and storage only; no production approval or execution capability is claimed.

## MLV1-08 — Exact preview and explicit decision (MLP1-T07)

RED: authorization tests failed collection before the service existed. Added strict preview/decision commands, immutable previews, server-context revision binding, exact quantity validation, command replay and explicit rejection. No inventory writes occur in this service. Both routes freeze only a valid displayed quantity; missing/invalid broken-route input never defaults.

GREEN: **21 authorization/storage tests passed in 3.49s** and full Ruff passed. Covered weak exact minimum, legal broken quantities below/above half Q0, empty/zero/off-grid/over-ceiling inputs, inventory/evaluation/evidence changes, unknown capacity, risk blocks, identical retries and rejection. Production authority collection and signal creation remain assigned to MLP1-T09; no HTTP access is exposed yet.

## MLV1-09 — Terminal lifecycle and contention (MLP1-T08)

Implemented explicit revocation, server expiry/invalidation and immutable retry receipts. Initial concurrent two-connection testing exposed SQLite read-to-write snapshot contention. The service now obtains its write fence before reading command authority and maps busy contention to an explicit conflict without treating other database failures as success. Terminal command construction preceded the first new lifecycle run; the concurrency fix followed its failing test.

GREEN: **31 tests passed in 5.94s**, including approval versus approval/rejection from separate connections, fresh-process reopening, revoke/retry, rejection/expiry/invalidation retention, backdating and early-expiry rejection. Ruff passed. Execution races remain assigned to MLP1-T10. Production correction and independent-reset continuity are completed with MLP1-T09.

## MLV1-10 — Owned runtime authority (MLP1-T09 / MLP1-C03)

Added v2 decision/calculation evidence without weakening v1 validators, shared independent-occurrence admission, persistent candidates and explicit approval-to-signal creation in one caller transaction. Schema 7 now passes reviewed activation and the production index adapter. Runtime cache identity includes candidate revisions. Pending reminders carry no quantity; send/read/completion checks fence current candidate state and consumed evidence.

GREEN: 45 combined decision/authorization/concurrency/old-and-new-runtime tests passed in 13.23s. The final 10 actual-runtime cases passed in 6.94s; Ruff passed. Verified both routes, no simulation on approval, same-clock refresh, unchanged refetch, correction invalidation, clone/rejection continuity, revoked read/send masking and completion-proof invalidation. Fixture corrections used the actual index fact-request field and alert repository; unchanged provider snapshots retain their receipt timestamp.

A broader API run reported 3 expected contract-projection failures: old assertions only allow two draft variants and versions [5,6]. These remain explicitly pending MLP1-T11/T12, where exact additive changes and old projections will be verified; they are not counted as passing. MLP1-C03 accepts per-occurrence runtime authority only. Simulation consumption, public commands, UI and replay are unfinished.

## MLV1-11 — Whole simulation consumption (MLP1-T10)

RED: both route tests exposed missing approval consumption and execution after revocation; independent-connection execution/revocation races then exposed the simulation entry's read-to-write lock upgrade. Simulation now acquires the authority fence before reads, validates the current grant and consumes candidate, signal and inventory in one transaction. Re-evaluation also retains the captured linked index source.

GREEN: **39 tests passed in 19.10s**, including 12 exception simulation cases, authorization contention and old daily/linked chains. Ruff passed after import formatting. Covered full quantity, capacity loss/recovery without resize, fault injection after inventory write with complete rollback, identical-key receipt replay, different-key duplicate rejection, revoke versus execution ordering and irreversible consumed history. No real account or broker execution is involved.

## MLV1-12 — Public API and generated contracts (MLP1-T11–MLP1-T12 / MLP1-C04)

RED: six public command tests initially returned 404; complete HTTP reevaluation then exposed an incomplete test calendar and an invalid error-detail location. Corrected both against the production contracts. The service now exposes preview, decision and revocation with same-origin, strict input, immutable receipt and idempotency protections. The first combined API/runtime/simulation run passed 32 tests in 20.19s. Exact legacy projections passed 8 tests in 7.73s, closing the three API assertions recorded in MLV1-10 without weakening legacy comparisons.

Generated both API profiles. Type-check found three shared display components still restricted to old variants; a separate three-file adapter slice explicitly adds the new union members. Type-check and generated `--check` pass. Final full V06–V08 passed **68 tests in 31.66s**, with one existing Starlette httpx deprecation warning. Full Ruff and `git diff --check` passed. This accepts MLP1-C04, not UI or replay.

| Artifact | SHA-256 |
| --- | --- |
| `openapi.json` | `bcf1c2591cb94b704d15d36ccfa681e540851c938e002bc5bddff9fb0dc3212f` |
| `openapi.runtime-status.json` | `e4115049f8ea95a90cfbe54383ab5a924cd5cc0cc274d7d151750657aef286a2` |
| `web/src/api/generated.ts` | `8d471ec572961e771f7d88cc859833c854bee25ce2def932b1783340fbc6826a` |
| `web/src/api/generated-runtime-status.ts` | `d7e2d8844e64be6347db5a2c248120e94ff8c351578233c2cf7b5140fc9b0107` |

## MLV1-13 — UI slice inventory (MLP1-T13–MLP1-T15; pending)

Component map: `usePlanWorkspace` owns editor state and server-defined schemas; `PlanExceptionPermissions` only presents plan-level route rules; `PlanExceptionApproval` owns a single candidate interaction through an exception composable; `PlanSimulationPanel` owns refresh and the existing separate simulation action. Props carry server evidence; events request refresh. No Vue calculation grants quantity or permission.

Sequential slices: T13a tests, `conditionPlans.ts`, `usePlanWorkspace.ts`, `planSchema.ts`; T13b permission component, existing review workspace integration and tests. T14a typed exception transport/response guards, composable and unit tests; T14b candidate component, simulation-panel integration and tests. T15 adds the isolated server fixture and real-browser tests. Each slice contains at most five implementation/test files; this inventory precedes edits.

## MLV1-14 — Permission review and occurrence UI (MLP1-T13–MLP1-T14)

Both new component suites first failed on missing implementation. Added explicit Schema 7 editor dispatch, server policy definitions and independent permission labels, then a read-only permission summary. Editing permissions clears prior review/activation bindings. Added guarded response handling and a per-occurrence composable/component with empty broken quantity, fixed weak minimum, exact preview, reasons, distinct reject/revoke controls, terminal states and stable command identity on uncertain retries. Existing simulation remains separate.

The first interaction run exposed Vue's numeric input coercion; accepting string/number input and normalizing its empty state fixed it without adding a quantity default. Final focused run: **34 tests passed in 1.27s**. Type-check and production build passed before the final added edit-invalidation test; they will be repeated at C05. One restricted run failed on Windows temporary-cache rename permissions; the same offline tests passed in the authorized local environment. Real-browser T15 and replay remain pending.

## MLV1-15 — Browser-driven repairs and replay inventory (in progress)

Real-browser testing found three independently reproduced omissions: the generic transport rejected the public `exceptionPolicyDefinitions.authorization` description; the extraction reader omitted `plan-extract-v10`; and complete exception source clauses exceeded the unchanged 50,000-character prompt limit because empty output-classification placeholders were repeated. Narrow endpoint-and-parent-path admission fixes only that public definition (16 transport tests pass, including negative credential cases); explicit v10 dispatch passes 10 reader tests; reuse of exact compact clause evidence passes 46 extraction/security/review tests in 2.12s. Source text, clause IDs/spans/excerpts and validation constraints remain intact. No input limit or security assertion was removed.

Browser inspection also found narrow-screen intrinsic grid overflow and a stale re-preview notice after approval. The isolated WEAK_MINIMUM complete journey now passes (10.9s), including explicit source review, approval without inventory change, reopening the saved version, four viewport widths and separate whole consumption. The first restart test incorrectly reloaded the unsaved `/plans` route; it now opens the actual saved version URL. Full T15/C05 remains pending the complete nine-scenario run and frontend regression.

T16–T18 sequential inventory: (a) strict frozen authorization envelope/stream and causality tests; (b) explicit Schema 7/run-v8 admission in single research and loop/schedule inputs; (c) frozen dataset/index/prepare adapters; (d) shared private-session event application and original-binding checks; (e) single replay time ordering and typed results; (f) monitor-loop time ordering with explicit exception execution scripts; (g) both-entry-path mutation/parity tests and generated contract updates. Each source/test slice has at most five files; documentation pairs track technical version additions before dependent implementation. Frozen events never query the current local approval store or directly change inventory.

## MLV1-16 — Real browser workflow checkpoint (MLP1-T15 / MLP1-C05)

Final V10: **9 real-browser scenarios passed in 1.5m** using fresh local SQLite fixtures and actual APIs (both exception routes × consume/revoke/reject/corrected-evidence, plus the old linked/independent-reminder journey). Verified keyboard approval, empty broken quantity, read-only weak minimum, stale preview clearing after refresh, no inventory change on approval/revocation, saved-version reopen, frozen whole consumption, terminal persistence and no external requests. Existing audit fixtures found no console errors, warnings or failed requests. Four viewports (320/768/1024/1440) pass horizontal-fit checks. Both approved-state screenshots were inspected: quantity, evidence, expiry, separate simulation and revoke controls are readable; raw debug blocker wording and post-approval re-preview notice were corrected.

Full frontend regression: **88 files / 1253 tests passed in 10.18s**. Type-check, production build and full Ruff pass. The current public-definition, v10-reader, prompt-budget and layout fixes close the earlier recorded browser failures. MLP1-C05 is accepted; frozen replay and final whole-project acceptance remain unfinished.

## MLV1-17 — Frozen replay integration and repair slices (in progress)

T16–T18 proceed through separate input/schedule admission, shared private-command translation, single research runner, loop request/report integration, real copied-data worker and mutation-test slices. The actual copied-data test exposed an absent pre-open price basis incorrectly terminating an approved occurrence. A three-file runtime/test repair keeps an absent required source non-executable without destroying its original grant; a supplied corrected source still invalidates. Runtime plus both actual workers: **14 passed, 36.39s**. Both-path negative scenarios: **36 passed, 34.70s**; future-loop prefix comparison: **2 passed, 3.91s**. These are intermediate results, not C06 acceptance.

The next interface slices are: (a) paired report header and native reader, (b) preparation transport readers and their focused test, (c) bounded loop-result/event reader and existing summary provenance display, (d) generated API/type artifacts and exact old projection verification. The frontend failing test reproduced Schema 6/7 preparation/result rejection and missing exception provenance display (3 failures before implementation). Preserve all existing payload/depth limits and reject unknown execution/version pairs. No new approval control or grant inference belongs in a research result.


## MLV1-18 — Frozen replay checkpoint (MLP1-T16–MLP1-T18 / MLP1-C06)

Final joint run: **88 passed, 1 existing Starlette deprecation warning, 184.99s**. Command: `python -m pytest tests/integration/test_market_exception_replay.py tests/integration/test_market_exception_replay_mutations.py tests/integration/test_market_exception_frozen_workers.py tests/integration/test_market_linkage_replay.py tests/integration/test_unified_replay_parity.py tests/integration/test_market_linkage_api.py tests/integration/test_market_exception_runtime.py -q --tb=short --basetemp .test-tmp/p1-c06-53`, using `.venv/Scripts/python.exe`. Both real frozen workers preserve each route, explicit whole execution, zero implicit fills, copied-input publication and isolated inventory. Future approvals preserve earlier decisions; rejected/revoked/late/corrected/quantity-mismatch scenarios block. Original plan scope, duplicate events and ambiguous time/order are rejected.

Follow-up slices: (a) persisted outcome identity/provenance, source-operation/audit binding and worker tests; (b) `research_signal_projection.py`, report/runner and worker tests, retaining complete evidence under the existing 32 KiB item cap; (c) runtime/calendar/original-receipt and candidate-reset risk checks in the existing runtime bridge/service/test; (d) single-research input/result transport, shared bounded replay reader and result display; (e) explicit loop-program transport and focused frontend tests. The persistence test first reproduced an oversized repeated evidence record; references now resolve to complete same-decision evidence, and substitution is rejected. Calendar correction and resealed approval tests reproduced **4 failures** before repair; risk-blocked candidate resets now reuse the existing signal risk gate.

The initial expanded V11 run had **68 passes / 2 failures** in old API projection comparisons. Only approved new input/report/reference variants and the generated union title are projected away; unchanged routes and legacy component schemas still compare exactly with `c7378a4`. Both profiles now pass. Both generated-artifact checks, full Ruff and frontend type-check pass. Focused frontend: **4 files / 188 passed, 1.41s**, including exact explicit-program submission, Schema 6/7 preparation/result dispatch and both provenance labels. Two initially named frontend test paths did not exist; the accepted command uses `UnifiedReplay.spec.ts`, `marketExceptionReplay.spec.ts`, `PlanPreparation.spec.ts` and `backtestsApi.spec.ts`.

Adversarial review temporarily disabled only the frozen-envelope hash comparison. Both corruption tests failed as expected (**2 failures, 3.04s**); original source bytes were restored in `finally`. No weakened guard remains. Paired contract/spec/task/report section IDs, code identifiers, quantities, paths and acceptance meanings were reconciled. C06 is accepted; T19–T21 remain pending. No live provider, external notification, user database migration, push or deployment occurred.


## MLV1-19 — Whole-project regression (MLP1-T19 / MLP1-T20, in progress)

The default V12 collection hit the existing duplicate basename `tests/unit/test_backtest_service_contract.py` / `tests/integration/test_backtest_service_contract.py`; no tests ran past collection. All non-live directories are therefore executed in separate processes, with no exclusions beyond `-m "not live"`: `tests/unit`, `tests/integration`, and `tests/contract tests/replay`. The full integration process, including the fixed 10-symbol/252-session capacity and traced-memory budgets, is still running. No full backend pass is claimed yet.

Unit regression initially gave **3653 passes / 6 failures**, then **3657 passes / 2 failures** while correcting a fixture assertion. The four-file repair updates exact default/current request expectations to the approved `plan-extract-v10`, still checks old configured labels dispatch to the current version, and verifies every compact source clause's exact ID/span/excerpt plus empty output-placeholder meaning. It changes no application behavior, limits or negative authority assertions. Final unit run: **3659 passed, 2 warnings, 46.26s**. Contract/replay directories: **13 passed, 4 live tests deselected, 8.44s**. The full integration run also loaded two stale extraction-version expectations; the exact production serializer fixture and adapter assertion were updated and the complete affected two modules passed **52 tests, 2.63s**.

The first full frontend run overlapped the production build and its installed-distribution immutability test detected that concurrent write (**1258 passed / 1 failed**). This was an orchestration error, not a reason to change the assertion. Independent rerun: **89 files / 1259 passed, 9.13s**. Production build and type-check passed. V10 rerun: **9 real-browser scenarios passed, 1.6m**; the final approved-state screenshots were inspected and retained ([WEAK_MINIMUM](assets/2026-10-24-market-linkage-p1-weak.png), [BROKEN_STRONG](assets/2026-10-24-market-linkage-p1-broken.png)). Quantity, evidence, original expiry and separate simulation/revocation remain readable; four viewport checks pass. The local Windows server logged a `ConnectionResetError` during connection teardown; browser console/request assertions and all scenarios passed. No production error handler was weakened to hide it.

Raw evidence: [initial collection](assets/2026-10-24-market-linkage-p1-full.log), [unit acceptance](assets/2026-10-24-market-linkage-p1-unit-accepted.log), [integration progress](assets/2026-10-24-market-linkage-p1-integration.log), [contract/replay](assets/2026-10-24-market-linkage-p1-other.log), [frontend](assets/2026-10-24-market-linkage-p1-web-final.log), [build](assets/2026-10-24-market-linkage-p1-build.log), [browser](assets/2026-10-24-market-linkage-p1-browser-final.log). Documentation slices T21a/b are prepared while final backend acceptance remains pending; T19–T21 and C07 are not yet accepted.

## MLV1-20 — Final regression repairs

Complete current-plan/source-review API modules exposed six additional stale current-request version assertions. Explicit historical configuration fixtures remain unchanged; current response/dispatch expectations now use `plan-extract-v10`. Both complete modules pass **13 tests in 5.82s** ([red](assets/2026-10-24-market-linkage-p1-api-fixtures-red.log), [green](assets/2026-10-24-market-linkage-p1-api-fixtures-final.log)). The already-running integration process had imported the old fixtures, so its eventual failures must be reconciled against these complete-module reruns.

After two added blocker-label checks, frontend **1261 tests**, type-check and build passed. The next browser run had **8 passes / 1 timeout** ([log](assets/2026-10-24-market-linkage-p1-browser-accepted.log)): an initial asynchronous inventory refresh replaced an equivalent binding object and erased quantities entered while loading. A deterministic form test reproduced the lost `100` before repair. `PlanOperationForm` now preserves input only when the schema identity and every binding field are unchanged; changed authority still resets it and blocks submission. No timeout or acceptance assertion was relaxed. Full frontend after this two-file repair: **89 files / 1262 passed, 9.22s** ([log](assets/2026-10-24-market-linkage-p1-web-final-accepted.log)); type-check and subsequent production build pass ([build](assets/2026-10-24-market-linkage-p1-build-final-accepted.log)). Final browser rerun: **9 passed, 1.5m** ([log](assets/2026-10-24-market-linkage-p1-browser-final-accepted.log)). Both API generated profiles and full Ruff pass. Full backend acceptance remains pending at this checkpoint.

Final input review found that a resealed candidate could change `minimum` or `increment` without changing the separately retained original grid evidence. Runtime translation already rejected the mismatch, but input admission did not. Four independent negative cases failed before the two-field binding check. The complete seven-module C06 run, including real frozen workers, both routes and old compatibility, now passes **92 tests, 1 existing warning, 186.58s** ([log](assets/2026-10-24-market-linkage-p1-replay-final-accepted.log)). This adds four cases beyond the earlier whole-suite collection; account for them separately in final coverage. No public schema, quantity rule or runtime grant policy changed.

## MLV1-21 — Explicit actor audit and final contract reruns

Specification reconciliation found that the transition path already separated explicit decisions from system effects but did not persist the required actor category. Six cases failed on the absent `actor_kind`; the forbidden-client-actor test already passed. The event model now requires the server-derived, hash-bound category, rejects missing/unknown/resealed inconsistent categories, and preserves the existing strict command inputs. No account authentication or automatic approval is inferred. MLC1-07 records exact event encoding and the distinct research provenance boundary. The generated profiles were regenerated together.

Complete storage/authorization/concurrency/simulation/runtime/API/replay/worker compatibility run: **152 passed, 1 existing warning, 216.13s** ([log](assets/2026-10-24-market-linkage-p1-authority-final-accepted.log)). It includes seven new audit cases and the four grid cases absent from the earlier integration collection. Final backend unit rerun: **3659 passed, 2 warnings, 49.64s** ([log](assets/2026-10-24-market-linkage-p1-unit-release.log)). Final frontend: **89 files / 1262 passed, 9.66s** ([log](assets/2026-10-24-market-linkage-p1-web-release.log)); type-check and sequential build pass ([build](assets/2026-10-24-market-linkage-p1-build-release.log)); **9 browser scenarios passed, 1.4m** ([log](assets/2026-10-24-market-linkage-p1-browser-release.log)). Both generated checks, full Ruff and whitespace checks pass.

The long integration process had already imported the pre-repair models before the generated files changed, so its two generated-service comparisons used mismatched in-memory/on-disk versions. Fresh complete modules for provider serialization, provider dispatch, current-plan API, explicit review API and generated service contracts pass **71 tests, 1 warning, 16.29s** ([log](assets/2026-10-24-market-linkage-p1-fixtures-release.log)). This also covers the stale v10 assertions described above; it is not a claim that the still-running original integration invocation exited green. Its final failure/skip list must still be reconciled before C07.

## MLV1-22 — Capability and migration regression repairs

The full integration run exposed an old `[5,6]` capability assertion and old migration-head assertions. Independent reproduction gave **3 failures / 5 passes** ([red](assets/2026-10-24-market-linkage-p1-restart-red.log)); the two complete modules now pass **8 tests, 13.21s** ([green](assets/2026-10-24-market-linkage-p1-restart-release.log)). The repository module then reproduced **13 failures / 96 passes**, all exact-head comparisons still expecting `0025_index_close_display` ([red](assets/2026-10-24-market-linkage-p1-migration-red.log)). They now require `0026_market_exceptions`; no row-preservation, rollback, permission or data-integrity assertions were removed.

Running the lot-index module independently additionally reproduced an import-order defect: Alembic's metadata did not register `DailyRecord` unless another test imported it first. The migration environment now explicitly loads that mapped model and uses its shared metadata. The old full collection masked this issue; the standalone test is retained. Joint repository/lot-index/exception-storage/process-restart regression: **127 passed, 5 warnings, 22.28s** ([log](assets/2026-10-24-market-linkage-p1-migration-release.log)). Independent lot-index module: **4 passed, 2 warnings, 0.95s** ([log](assets/2026-10-24-market-linkage-p1-lot-release.log)). SQLite cannot reflect the expression-based unique command index for automatic metadata comparison; the existing explicit duplicate-command and race tests still verify enforcement. Warnings are not suppressed. Full Ruff passes.

The original integration process also reached its fresh-process approval test with a pre-actor parent model and a current child model. The final 152-case authority run in MLV1-21 already passes that complete concurrency module with both processes on the current event contract. Final reconciliation still waits for the original invocation to finish.

## MLV1-23 — Final acceptance (MLP1-T19–MLP1-T21 / MLP1-C07)

The full integration invocation finished: **4606 passed, 35 failed, 1 skipped, 5 warnings, 4508.52s**. Every one of its 35 failures is matched to a passing complete-module rerun in the [machine-readable reconciliation](assets/2026-10-24-market-linkage-p1-reconciliation.json). The original invocation did not exit green. Final coverage combines its unaffected passing cases, repaired complete modules and the eleven added grid/actor cases; it is not presented as a single uninterrupted passing run.

Final remaining checks: the OpenAPI module reproduced **2 failures / 12 passes** for a missing P1 approval/hash entry and three approved paths absent from the test allowlist. Added the exact already-approved endpoints and paired U-MLP1 approval record, preserving the exact-set and error-schema assertions: **14 passed, 17.79s** ([log](assets/2026-10-24-market-linkage-p1-openapi-release.log)). The complete loop-contract module passes **13 tests, 8.88s** ([log](assets/2026-10-24-market-linkage-p1-loop-contract-release.log)). The last diagnostic failure used the old imported v9 fixture; its complete module passes **4 tests, 3.13s** with current fixtures ([log](assets/2026-10-24-market-linkage-p1-diagnostic-release.log)). No further application change was needed for that diagnostic case.

| Final check | Accepted evidence |
| --- | --- |
| Backend unit | **3659 passed**, 2 warnings, 44.16s; [final log](assets/2026-10-24-market-linkage-p1-backend-unit-final.log) |
| Backend integration | **4652 unique passing cases**, 1 existing Windows skip after full-run/rerun reconciliation; includes 11 added cases passing in the 152-case final authority run |
| Contract and replay directories | **13 passed**, 4 live tests deselected, 7.87s; [final log](assets/2026-10-24-market-linkage-p1-backend-other-final.log) |
| Total non-live backend | **8324 unique passing cases**, 1 platform skip; 4 live cases excluded from this local scope |
| Frontend | **89 files / 1262 passed**, 9.66s; type-check and production build pass; MLV1-21 final logs |
| Browser | **9 passed**, 1.4m; both routes and old linked/independent-reminder journey, four widths, final screenshots inspected |
| Contracts and quality | Both generated profiles current; full Ruff and whitespace checks pass; final hashes recorded in U-MLP1 and the reconciliation |

The platform skip is `test_cursor_key_rejects_foreign_posix_owner_before_use`, whose existing condition is Windows and reason is `requires POSIX ownership semantics`. No new skip, xfail, weakened assertion or relaxed timeout/capacity/payload budget was added. The ten-symbol/252-session capacity, traced-memory and 100k export budgets passed. SQLite expression-index reflection and the existing Starlette diagnostic remain visible; explicit uniqueness/concurrency tests enforce the unreflectable index.

| Criterion | Actual evidence / checkpoint | Result |
| --- | --- | --- |
| MLP1-A01 | [Contract cases](../../tests/unit/test_market_exception_contract.py), [exact legacy API projection](../../tests/integration/test_market_linkage_api.py); MLV1-03/12/18 | PASS |
| MLP1-A02 | [Policy matrix](../../tests/unit/test_market_exception_policy.py); MLV1-04 | PASS |
| MLP1-A03 | [Quantity oracles](../../tests/unit/test_market_exception_quantity.py), MLP1-Q01–MLP1-Q12; MLV1-04/08/11 | PASS |
| MLP1-A04 | [Source review](../../tests/integration/test_market_exception_review.py), [updates](../../tests/integration/test_market_exception_updates.py); MLV1-05/06/14 | PASS |
| MLP1-A05 | [Explicit authority](../../tests/integration/test_market_exception_authorization.py), [API](../../tests/integration/test_market_exception_api.py); MLV1-08/12/21 | PASS |
| MLP1-A06 | [Lifecycle/runtime](../../tests/integration/test_market_exception_runtime.py); MLV1-09/10/18/21 | PASS |
| MLP1-A07 | [Races/restart](../../tests/integration/test_market_exception_concurrency.py), [storage](../../tests/integration/test_market_exception_storage.py); MLV1-07/09/11/21/22 | PASS |
| MLP1-A08 | [Consumed-evidence/read/send fencing](../../tests/integration/test_market_exception_runtime.py); MLV1-10/18/21 | PASS |
| MLP1-A09 | [Whole simulation](../../tests/integration/test_market_exception_simulation.py), [frozen workers](../../tests/integration/test_market_exception_frozen_workers.py); MLV1-11/18/21 | PASS |
| MLP1-A10 | [API snapshot/error contracts](../../tests/integration/test_openapi_snapshot.py), [legacy projections](../../tests/integration/test_market_linkage_api.py); MLV1-12/21/23 | PASS |
| MLP1-A11 | [Browser exception journeys](../../web/tests/e2e/market-exceptions.spec.ts), [old linked journey](../../web/tests/e2e/market-linkage.spec.ts), [retry/blocked UI](../../web/tests/unit/marketExceptionRuntime.spec.ts); MLV1-16/20/21 | PASS |
| MLP1-A12 | [Replay mutations](../../tests/integration/test_market_exception_replay_mutations.py), [actual frozen workers](../../tests/integration/test_market_exception_frozen_workers.py); MLV1-18/20/21 | PASS |
| MLP1-A13 | [Full-run/rerun reconciliation](assets/2026-10-24-market-linkage-p1-reconciliation.json) and final check table above | PASS |
| MLP1-A14 | [Operations](../operations/market-linkage-p1.md), [specification](../specifications/monitoring/SPEC-market-linkage-p1.md), paired tasks/README/capability map/index and this report; V16 | PASS |

Final diff review covered authority/correctness, maintainability, performance, recovery/error behavior and security boundaries. Paired section IDs, all 28 task/checkpoint boxes, fourteen criteria, numeric rules, enum/API/JSON identifiers, generated hashes and local links are reconciled. The only inline formula text translated inside a code span describes the same integer-set intersection. No dependency or strategy decision changed. T21a–T21d and C07 are accepted. Both exceptions require separate explicit human approval and whole simulation; frozen replay retains source provenance and explicit operations. No user database was migrated, no live provider/notification or real order was sent, and no push/deployment occurred. Live service availability remains outside this local acceptance.
