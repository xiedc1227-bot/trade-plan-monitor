# Specification: Plan Update Timeline, First Increment

## PUT01. Status, objective and assumptions

Status: **Approved for bounded implementation on 2026-10-19; includes an editable end date defaulting to the current Asia/Shanghai date.** Date: 2026-10-19, Asia/Shanghai. One capability in the existing `backtest-web` boundary: replace manual reviewed-plan selection with maintenance and replay of a plan update timeline. Chinese review copy: [SPEC-plan-update-timeline.zh-CN.md](SPEC-plan-update-timeline.zh-CN.md).

The agreed business flow is: submit a first trading plan → extract and review its stock and conditions → append reviewed plan updates with effective dates → replay the conditions in chronological order with one continuous account. Stock code/name continue to come from the existing extraction and review workflow; no preliminary stock selection or separate stock-maintenance feature is introduced.

Approved first-increment boundaries:

- Adjust the current prepared-plan/source-preparation path on `/backtests/new`. Preserve the existing workbench single-version replay entry; do not join the workbench and preparation stores into a new cross-store timeline.
- A timeline represents a sequence of reviewed trading-plan updates, not a historical backtest run. Replaying it produces a new immutable result. Editing a source or saving a draft does not approve it or change a running replay.
- Reuse existing daily effective-date semantics. Start from the first plan/account under current availability rules; prefill editable `endDate` with the current Asia/Shanghai calendar date when a new form is created; never overwrite user edits on refresh. Retain the existing server fallback if the field is cleared. Arbitrary start-date clipping and intraday update scheduling are outside this increment.
- Permit appending a later update. Same-day replacement, backdated insertion, reordering, deleting, merging and creating branches from arbitrary historical nodes are outside this increment.

## PUT02. Verified reusable baseline

| Existing surface | Reuse |
|---|---|
| `create_single_preparation`, `SingleSourcePreparationInput.reviewed_base` | A first source has no base; an update binds the exact reviewed predecessor and inherits its items/account. |
| Existing source extraction, correction and review | Extract the stock and conditions; materialize and review additions, changes, retained rules and revocations. Only the new source is editable; reviewed predecessors remain frozen. |
| `CollectionPreparationView.frozen` | A reviewed `SINGLE` record already exposes the complete prefix and schedule through `CollectionPreparationFrozenView`. Use it to display the selected timeline and existing run settings. |
| Reviewed-plan library and `planLibraryPresentation.ts` | Load every existing library page and follow exact preparation-ID/manifest-hash predecessors. Preserve original and reviewed-version metadata. |
| `POST /api/v1/backtest-plan-library/compositions` | Internally freeze the selected exact path before replay, preserving the existing per-entry review/risk rechecks, chronology and same-stock checks. The user no longer selects individual composition members. |
| Existing automatic data preparation, `prepared-loop-plan-v2`, worker and result reader | Run the frozen schedule through the current engine; switch conditions at effective dates without reinitializing the account. Preserve history and exports. |

The direct reviewed head contains a complete schedule, but the first increment deliberately retains the existing composition validation boundary for new runs. Removing its UI does not delete its API or bypass its eligibility checks. This avoids a database migration, public API change, new execution model or changed historical codec/hash.

## PUT03. User workflow and page presentation

| Action | Visible behavior | Existing authority |
|---|---|---|
| Create a plan timeline | Open the first-source form immediately, without selecting a stock. Extract, correct, confirm the effective date and review. Then show the extracted stock and first timeline node. | `reviewed_base=null`; existing preparation/review commands. |
| Open a timeline | Show stock, first effective date, latest reviewed effective date, number of updates and approval identity. Show one chronological list of effective date, review time, source and rule-change summary/detail links. | Exact root and selected reviewed endpoint; complete frozen schedule and existing item/review views. |
| Update the trading plan | Start one new source attached to the displayed reviewed endpoint. Show the predecessor read-only. After review, append the node and offer replay of the updated timeline. | Exact `reviewed_base`; existing later-date, same-stock, provenance and review checks. |
| Start replay | Show the frozen first-plan/account start, optional end date, response and cost settings. One user action automatically freezes all nodes on the chosen path, prepares data and submits the existing run command. | Existing composition, data preparation and run submission APIs. |

Replace the per-entry checkboxes, manual composition button and general predecessor dropdown in this path with timeline selection, **Create plan timeline**, **Update trading plan** and **Start replay** actions. The update action determines the predecessor from the selected timeline; users do not assemble it again. Keep source/review corrections and unfinished-preparation recovery visible in their existing contexts.

Show changes using the existing add/modify/retain/revoke review details; do not infer trading-rule differences from hashes. Hash/ID details remain expandable for source/version verification. Newly extracted drafts appear as pending updates and never replace the effective reviewed endpoint before approval. Preparing or reviewing a replay source does not activate a live plan.

## PUT04. Timeline identity, existing records and branches

- Derive a timeline root from exact `preparationId` + `manifestHash` predecessor references. A stock, name, source hash, content version ID or approval time alone never identifies a timeline. Do not add a timeline table or rewrite existing preparation records.
- For a linear root-to-leaf chain, the leaf is its latest reviewed endpoint. The displayed replay/update selection binds that exact endpoint and its full predecessor path. Never choose a global latest date across unrelated roots.
- When an existing root has multiple leaves, label the alternative paths and require one endpoint choice. Do not union branches or guess which approval is authoritative. Updating an explicitly selected endpoint may continue that path; this increment adds no branch creation/merge editor.
- Missing or mismatched predecessors, cycles, mixed stocks, repeated source IDs/dates, invalid chronology or paths exceeding 256 plans do not become a guessed automatic timeline. Show the reason and preserve access to existing records/results. The server's existing composition checks remain authoritative for new replay acceptance.
- The eight audited local records appear as **two separate four-update timelines for the same stock**. Both remain available, with review/version distinctions. Do not deduplicate, merge, auto-pick the later approval or re-approve either version.
- Preserve existing `preparationId` deep links, legacy batch/composition preparation readers, progress/recovery and result links. Historical nodes remain inspectable; inspection alone does not change the selected replay endpoint or create a branch.
- Refreshing or discovering an additional update must not silently replace the displayed endpoint or an in-progress request. The user confirms the newer path before it becomes the new replay input.

## PUT05. Run snapshot and failure behavior

1. Opening/inspecting a timeline is read-only. Load its reviewed head and all library pages needed to verify the exact path; do not compose, extract or run simply because a card was opened.
2. At **Start replay**, capture the exact ordered references, displayed endpoint, immutable form values and original idempotency keys. Call the existing composition API once for this intent, then pass its frozen receipt to existing automatic data preparation/run submission. No AI call or re-review occurs during this step.
3. If the selected path/draft changes before submission, invalidate any prepared new-run selection instead of combining old and new inputs. During uncertain outcomes, retain the existing locks and retry the same command/key. After a composition receipt is confirmed, reuse it rather than creating another composition on a data/run retry.
4. Each accepted run owns copied frozen inputs as today. Later plan updates do not alter accepted/running runs or prior results. A later deliberate replay uses the newly confirmed path. Current data, cost, T+1, risk and funding semantics remain unchanged.

Internally composed snapshots remain existing `COMPOSITION` preparations and are not extra timeline updates. Keep the old composition API usable for existing callers; remove only the manual member-selection interaction in the adjusted page.

## PUT06. Scope, structure and style

Expected production changes are limited to the existing timeline presentation model/component, `usePlanLibrary.ts`, `BacktestNewView.vue`, and the small load/select seam in `usePlanPreparation.ts` needed to open an exact existing preparation safely. Reuse `useBacktestRunForm.ts` and the source/review components; modify only a narrow integration seam if necessary. Add or extend focused unit/browser tests and bilingual operations/verification documents after approval. No unrelated run-list/filter/result-action changes belong to this work.

Use the established Vue 3 Composition API, `<script setup lang="ts">`, typed readonly inputs, original IDs and explicit actions. Pure timeline derivation returns data without changing input or emitting writes; for example:

```typescript
type TimelineEndpoint = Readonly<{
  preparationId: string;
  manifestHash: string;
}>;
// Select one exact path; source extraction and run commands retain their existing models.
```

- Always: keep current server authority, full pagination, pending/uncertain-operation locks, same-request retries, no-overflow and accessibility checks; update English/Chinese documents together.
- Scope changes requiring a revised proposal: a new public API/schema, database table/migration, new dependency, workbench/preparation cross-store lineage, arbitrary start date or changes to live activation/execution.
- Never: rewrite/delete original reviewed records or results, merge independent chains automatically, change stored hash/codec formulas, weaken test gates, reset the account on a later update, or send orders/notifications from replay.

## PUT07. Acceptance criteria

- **PUT-A01:** With an empty library, a user submits a first source without selecting a stock; review establishes the extracted stock and first timeline node.
- **PUT-A02:** Two later same-stock updates append to the chosen exact predecessor. Only the newest source is editable; existing additions/changes/retentions/revocations are visible. A draft alone is not effective. A mismatched stock or invalid effective date is rejected by existing review/validation checks.
- **PUT-A03:** The audited eight records render as two four-node timelines. Equal names/dates/content version IDs never merge independent roots or approvals. A branch requires one path choice; broken/missing/cyclic references and multi-page libraries cannot yield a silently incomplete path.
- **PUT-A04:** The adjusted workflow contains no manual plan-member checkboxes/composition action. Inspecting a timeline sends no business writes. Starting replay automatically freezes exactly its selected path, makes no extraction call and creates exactly one run for the accepted intent. Pending/uncertain retries retain the original path/key/body and confirmed composition receipt.
- **PUT-A05:** The original four-plan continuous replay preserves the existing exact oracle: four versions, one account, two fills, final cash `1019000` fen, remaining quantity `0`, fees `1000` fen, realized P&L `19000` fen and the exact seven-point equity sequence. Existing `POSITION_LIMIT_ONLY` defaults and historical funding modes remain unchanged.
- **PUT-A06:** Updating a timeline after a run does not alter that run's copied input, result response, equity, export or deep links. Old single/batch/composition preparations and workbench single-version replay remain readable/usable under existing eligibility rules; API snapshots and codecs do not change.
- **PUT-A07:** Reload restores the exact selected reviewed endpoint or unfinished update context from existing preparation links; navigation, background reads and late responses cannot mix timelines or silently update a frozen form. Existing cancellation audits and 320/768/1024/1440px checks remain; expanded details at 200% root text do not overflow.
- **PUT-A08:** No production database is modified by acceptance tests. Run the original assertions without skipped tests, broadened tolerances, reduced coverage, suppressed request failures or lowered thresholds. Compare existing owned-result artifacts/read responses where applicable and review the final diff for unrelated changes.

## PUT08. Verification commands after approval

Run from `trade-plan-monitor/`; use offline fixtures and isolated stores. These are required implementation checks, **not tests run while writing this proposal**. Extend the relevant suites with PUT-A01–PUT-A08 cases before implementation. Adapt only interactions/selector assertions that specifically describe the superseded manual UI; retain all existing integrity, continuity, history, request-audit, layout and threshold assertions.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_single_plan_library.py tests/integration/test_monitor_loop_plan_switch.py tests/integration/test_monitor_loop_input_store.py tests/integration/test_monitor_loop_result_api.py tests/integration/test_backtest_result_api.py tests/integration/test_workbench_plan_selection.py tests/integration/test_backtest_service_contract.py tests/integration/test_openapi_snapshot.py -q --tb=short
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
npm --prefix web test -- --run --maxWorkers=2
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/streamCompletion.spec.ts tests/e2e/plan-library-versions.spec.ts
git diff --check
```

Use the existing pinned test browser; do not install/update system Chrome or use live AI/market providers for deterministic acceptance. For a frontend-only implementation, no new backend lint surface is expected; if an approved small Python test helper changes, run Ruff on that file too. The exact original backend compatibility checks still run.

## PUT09. Confirmation boundary

User confirmation authorizes the append-only timeline workflow, explicit choice between independent/branched update paths, existing first-plan start/optional end-date boundary, internal reuse of composition validation, and preservation of the workbench single-version entry. The proposal review changed no application code, OpenAPI or database; implementation now follows only this confirmed scope. Implement and test in bounded slices under this approved scope. Retain the existing [plan-reuse boundary](SPEC-plan-reuse-unification.md), [daily continuity contract](PROPOSAL-monitor-loop-backtest.md) and [eight-record audit](../../verification/2026-10-19-plan-library-versions.md) except for the specifically superseded manual prepared-plan selection interaction.
