# Plan update timeline verification, 2026-10-19

## PUT-V01. Authority and scope

The user approved [PUT01–PUT09](../specifications/backtesting/SPEC-plan-update-timeline.md), then explicitly requested that the end date default to the current date and remain editable. Implementation and checks span 2026-10-19–2026-10-20, Asia/Shanghai. This report covers the prepared-plan/source path, not a new live monitoring workflow or cross-store authoring system.

Production changes are limited to seven existing frontend files: the library presentation model/component, `usePlanLibrary`, `usePlanPreparation`, `useBacktestRunForm`, `BacktestNewView` and the run-form date hint. No backend, public API, generated artifact, dependency, database schema, engine, input/hash formula or result reader was changed by this increment. Existing unrelated worktree edits are compared against the task-start file hashes and preserved.

## PUT-V02. Implemented behavior

- Create a first source without stock selection; existing extraction/review establishes stock and conditions. Explicit timeline selection follows exact preparation-ID/manifest-hash links, loads all library pages, exposes independent roots/alternative endpoints and rejects incomplete/cyclic/mixed-stock/duplicate-source/non-increasing-date/over-256 paths.
- Replace manual member checkboxes/composition with timeline open/new/update. Opening is read-only. Updating binds the displayed reviewed endpoint; drafts do not change the reviewed timeline. Existing original/version/predecessor metadata and review change details remain available.
- Starting replay captures the original form and run key, automatically invokes the existing composition eligibility checks once, then uses existing automatic data preparation and the continuous replay engine. Reuse a confirmed frozen receipt and original command/key/settings for uncertain retries. No AI call or review occurs during freezing.
- Default `endDate` to the current Asia/Shanghai day when a form is created. It remains editable and is not overwritten by refresh or clock changes. An empty value retains the original server fallback. A UTC-to-Shanghai midnight test verifies the date boundary.
- Historical detail links open `inspect=1` in an independent `noopener` page. The page has no timeline selection or run form and locks source changes, extraction, review/correction and mode changes. The originating endpoint/form remain unchanged. Old ordinary preparation links, legacy batch/composition readers and workbench single-version replay retain their existing behavior.

## PUT-V03. Real records and historical data

SQLite was opened with `mode=ro` and `PRAGMA query_only=ON`; no store constructor or migration was used. Read-only metadata from the actual eight reviewed `SINGLE` records was evaluated using the actual frontend timeline model. It produced exactly two paths:

| Root | Selected latest endpoint | Updates |
|---|---|---|
| `full-chain-20261017-1` | `full-chain-20261017-4-v2` | 4 |
| `generic-live-final-20261017-1` | `cohort-plan-20261018-4-v6` | 4 |

All eight entries retain their different-content comparison labels. The projection did not mutate the metadata; no original text was exported. No record was merged, deleted, re-approved or selected automatically across roots. See the [original identity audit](2026-10-19-plan-library-versions.md) for the reviewed rule differences.

Before/after SHA-256 values of real databases match:

- `backtest-preparation.sqlite3`: `e710de8d995e88832ee9591b36ff07268c4266219261516ba651ff5a47d62f59`.
- `backtest-results.sqlite3`: `ffab0b51ff6c61342a56bebd6a14afd61a5f27e4d849a195ffe07afca8fcf012`.

All execution acceptance uses isolated stores and fake providers. Existing result-owned inputs, historical readers and exports are exercised by the original backend/browser regressions; timeline changes do not rewrite accepted results.

## PUT-V04. Executed checks

| Check | Result |
|---|---|
| Full Vitest suite, `npm --prefix web test -- --run --maxWorkers=2` | 76 files, 1147 tests passed, no skipped tests. |
| PUT08 backend command, including library, plan switches, stored inputs, both result APIs, workbench reuse and contracts/OpenAPI | 145 passed; one existing Starlette/httpx deprecation warning. |
| `scripts/generate_frontend_types.py --check` | Both API profiles remain current and unchanged. |
| `npm --prefix web run type-check` and `npm --prefix web run build` | Passed. |
| Focused real Chrome timeline check | Passed: two paths/eight records, zero manual member selectors, keyboard endpoint/update actions, 320/768/1024/1440px at 200% root text with expanded details, zero failed requests, console/page errors or business writes. |
| Final complete browser regression | All 20 passed in 6.0 minutes, zero retries; original continuity, history, audit, accessibility and layout gates retained. |
| Real eight-record model check and database hashes | Passed, PUT-V03. |
| `git diff --check` | Passed. |

The final full browser command was `npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/streamCompletion.spec.ts tests/e2e/plan-library-versions.spec.ts`.

The original four-plan browser oracle remains four frozen versions, one submitted run/account, two fills, cash `1019000` fen, remaining quantity `0`, fees `1000` fen, realized P&L `19000` fen and the exact seven-point equity sequence. Its actions now update a timeline and automatically freeze on submission; its original execution/history/layout assertions are preserved. It also checks the editable current-date default and a real historical-detail popup that leaves the originating endpoint and edited date unchanged.

## PUT-V05. Failure evidence and review

New exact-path/controller tests failed before implementation; the two new UI interaction tests failed against the old manual interface. New date/pre-submission-freeze tests failed before their implementation. Disabling the newly added duplicate-source guard caused the targeted regression to fail; exact original source bytes were restored immediately. The full suite subsequently passed without that mutation.

Independent review found one P2: opening a historical node in the same context could replace the chosen replay endpoint with a shorter prefix. Two new regression cases failed before repair. Independent read-only inspection plus unit/browser coverage now separates inspection from replay selection; the reviewer closed P2 and reported no remaining blockers. The in-progress earlier browser run was stopped before the repair; it is not counted as passed evidence.

A subsequent browser run passed 18 cases and exposed two old fixed-date fixture mismatches: the workbench fixture always returned `2026-08-30`, and the legacy-source fixture used a frozen `2026-08-20` server clock/cutoff, while the new form explicitly sent today's date. The unchanged application boundary/response checks correctly rejected those inconsistent inputs. Both journeys now assert the current-date default and explicitly enter their original frozen dates. The workbench case additionally verifies exact `endDate` in the complete submitted body; the legacy case retains its exact original evidence cutoff and result oracle. Both repaired cases passed the focused real-browser rerun before the final complete suite. No production validation, request audit, retry count, timeout, layout bound or original result oracle was loosened.

## PUT-V06. Retained limits

No arbitrary start-date clipping, intraday update scheduling, same-day replacement, backdated insertion, branch merge/delete/reorder or workbench/preparation cross-store timeline is added. The workbench single-version entry remains available. Preparation/review does not activate a live plan. This is offline functional evidence, not live-provider, profitability or deployment certification.

## PUT-V07. Final staged verification, 2026-10-20

The user authorized a final review and focused commit. The 37-file candidate includes the earlier optional library identity projection required by the timeline display. Nine unrelated whole-file edits and the unrelated U23 changes in the two mixed specification files were excluded. Independent staged review found no blockers. Candidate tree `edf54f1c411d8df4830c4a09dad3fd1b525f081f` was exported into an isolated directory and checked without those unrelated edits; only this bilingual verification section was added afterward.

The exact candidate passed all 1147 frontend tests in 76 files, all 145 required backend tests, all 20 real Chrome tests in 7.0 minutes with zero retries, both generated-contract checks, Ruff, type checking and production build. The existing Starlette/httpx deprecation warning remains. The editable Shanghai current-day default, historical-detail isolation, original four-plan account/fill/fee/equity oracle, historical readers, cancellation audit and layout gates passed. Real preparation/result database SHA-256 values still match PUT-V03.

Initial isolation attempts encountered archive CRLF conversion, an absent packaged build and sandbox `EPERM` access failures. Five affected files were restored from their exact staged bytes, the normal build was generated, and the original suites were rerun with the required filesystem access. An interrupted browser round is excluded from successful evidence. No candidate application/test changes, weakened assertions, skipped tests, audit exclusions, retries or timeout increases were used to resolve these environment failures. All task-start working-file bytes were preserved until this verification-only update.

## PUT-V08. Business plan details, 2026-10-20

The user authorized replacing visible internal identifiers with the plan date, stock, predecessor and concrete trading condition changes, followed by validation and a focused commit. Production changes are limited to `ReviewedPlanLibrary.vue`, `planLibraryPresentation.ts`, `PlanRuleChanges.vue` and the new `ReviewedPlanDetails.vue`. Five related test files and four bilingual operations/verification documents complete the change. No API, backend, database, execution controller, replay form or dependency changes are included.

Timeline/path display numbers, dates and review times distinguish independent approvals without showing preparation/source/version IDs or hashes. Exact internal IDs, manifest matching, root/path resolution and endpoint events remain unchanged. Expanding details lazily performs the existing `get` and paged `items` reads; it verifies the reviewed manifest, source, date, plan identity, revisions and summary/detail/candidate evidence before rendering. Failed or mismatched reads show an explicit retry; same-identity refresh preserves verified content, and identity changes abort/discard obsolete responses. No extraction, review, composition or execution is triggered.

The first plan displays its approved conditions; later updates display the stored retain/modify/add/revoke changes, with prices in yuan and prerequisite rules described by direction, quantity and order. Older records without itemized changes retain an explicit explanation and the independent read-only source link. The original review/result renderer defaults are unchanged. Historical `INITIAL` extraction evidence is checked against its own summary rather than the different derived frozen-evidence domain. An already reviewed `INITIAL` with `UNRESOLVED` validation is accepted only for the single `LOOP_ACCOUNT_FACT_REQUIRED: opening_account.cash_fen` issue, matching backend `policy_ready`; empty, different and mixed unresolved issues are rejected.

New display, initial-evidence, refresh, prerequisite and initial-account regressions failed before their corresponding repairs. Temporarily removing the new detail/summary `baseHash` comparison made the mismatch regression fail; original source bytes were restored immediately. Independent read-only review closed all findings with no remaining blockers. Early browser fixture syntax and 320px/200% nested-padding failures were corrected without changing any request audit, layout bound, retry, timeout or original continuity/history assertion. An interrupted browser round is excluded from passed evidence.

The final full frontend suite passed all 1168 tests in 77 files, with no skipped tests. All 54 focused tests, type checking and production build passed. The prescribed PUT08 backend regression passed all 145 tests, retaining one existing Starlette/httpx deprecation warning. Tests use isolated stores and fake providers. Real preparation/result database SHA-256 values still match PUT-V03; all 24 diagnostic result files remain intact, and unrelated tracked file bytes match the task-start audit. No running monitoring database was opened or modified for this change.

The complete browser command recorded in PUT-V04 passed all 20 cases in 6.8 minutes with zero retries. The original four-plan/one-account/two-fill oracle, cash `1019000` fen, quantity `0`, fees `1000` fen, realized P&L `19000` fen and exact seven-point equity sequence passed unchanged. It also verified the editable current-date default, the new initial-condition detail with the real API, the independent historical popup and originating form isolation. The eight-record/two-timeline case verified readable price changes and no visible internal identifiers at 320/768/1024/1440px with 200% text, exact endpoint events, zero failed requests/errors/business writes. Original history, cancellation and accessibility gates passed. Exactly the 13 related files were staged; staged whitespace and working/index consistency checks passed.

## PUT-V09. Bounded plan-list performance repair, 2026-10-20

The user authorized the proposed list-loading repair with strict scope control. Production changes touch only `plan_library.py`, `usePlanLibrary.ts` and `BacktestNewView.vue`; related tests touch `test_single_plan_library.py` and `PlanTimeline.spec.ts`, with this bilingual verification update. No schema, public API, dependencies, shared semantic validators, replay execution, history readers, transport timeout or admission thresholds change.

The list now projects the saved canonical reviewed manifest instead of decoding the complete preparation model and rebuilding every historical candidate prefix. It checks the stored preparation identity, schema, revision, review time, item count, pending work and terminal source before projecting metadata. Manifest/version hashes retain their original domains and canonical values. Listing is discovery only: update/composition/execution continue to use their original full verification. The frontend skips an automatic ready-state refresh only when the exact preparation ID and manifest are already present in a successfully loaded library; manual refresh, missing/new versions and error recovery retain reads.

Before repair, the live list GET took 2.064–2.293 seconds for eight records; metadata filtering took about 0.091 seconds. A read-only preparation-store connection copied the data to memory, then closed. The unchanged and repaired functions were measured alternately three times against that same snapshot. Before: 1768.57/1763.24/1760.12ms; after: 234.32/256.58/331.70ms. Median time fell from 1763.24ms to 256.58ms (85.4%). All eight complete API projections, including identities and predecessor references, were exactly equal. These are same-snapshot function timings, not post-restart live HTTP measurements.

The two new performance/refresh regressions failed against the old code. Five saved-envelope mismatch cases remain rejected; the original four-plan test additionally checks exact manifest/source/date output. Existing tests exposed JSON versus Python strict-date parsing and differing timestamp precision during implementation; JSON-mode source validation and equivalent-time comparison restored compatibility. Removing the new manifest equality guard made the refresh regression fail; original source bytes were restored and all 16 timeline tests passed. Independent read-only review found no remaining blockers. The full frontend suite passed 1169 tests in 77 files, and type checking, production build and focused Ruff checks passed. No source database constructor, migration, monitoring stop or service restart was used.

The original PUT08 backend command passed 151 tests, including the six added cases, with one existing Starlette/httpx warning. The complete PUT-V04 browser command passed all 20 tests in 6.6 minutes with zero retries and unchanged assertions, timeouts, audit rules and layout bounds. The original four-plan/one-account/two-fill oracle, cash `1019000` fen, quantity `0`, fees `1000` fen, realized P&L `19000` fen and exact seven-point equity sequence passed, together with history isolation, the editable Shanghai current-date default and cancellation handling. Real preparation/result SHA-256 values still match PUT-V03 and all 24 diagnostic result files remain intact. Exactly seven related files were staged; unrelated tracked bytes and staged/working consistency were checked. The running service was not restarted; the backend optimization takes effect on its next normal restart.
