# Specification: Unified Plan Selection and Reuse

## PRU01. Status, objective and assumptions

Status: **Approved for bounded implementation on 2026-10-19; includes removal of the JSON/YAML plan-import API.** Date: 2026-10-19, Asia/Shanghai. One capability within the existing `backtest-web`, `backtest-api` and `backtest-engine` boundaries: reuse reviewed plans without repeating extraction or choosing a replay implementation.

The user has no external plan generator, environment migration or JSON/YAML file workflow. The normal path is: prepare/review a plan → select the reviewed version → confirm missing research context → run/re-run. A saved, unreviewed draft is not a reusable execution plan. Live activation is unnecessary.

Scope assumption: “unified source” in this increment means one reusable-plan selection contract covering the two existing stores. It does **not** mean merging their databases or replacing their distinct preparation/review workflows. Workbench plans are the default source; existing prepared backtest plans remain reusable. This distinction must be stated in release notes; do not claim a single physical plan repository or a single authoring workflow.


User amendment, 2026-10-19: remove `POST /api/v1/plan-imports`, its transport command/client/form and direct tests/docs. Keep internal JSON/YAML codecs, historical plans/results and source-text extraction. No deprecation delay is required; the user explicitly authorized removal.

## PRU02. Verified baseline and the actual gap

| Existing surface | Actual responsibility | Relevant source |
|---|---|---|
| `/plans` | Save an immutable Schema 5 candidate; explicitly review it; activate separately | `web/src/composables/usePlanWorkspace.ts`, `state/daily_review_store.py` |
| `GET /api/v1/plan-versions?canActivate=true` | Read eligible workbench versions from `plan_version`; the current backtest selector uses this | `web/src/composables/useBacktestPlanVersions.ts`, `web/plan_service.py` |
| `GET /api/v1/backtest-plan-library` | Read reviewed preparation entries from `backtest_preparation` | `backtest/plan_library.py` |
| Existing-version run | Single-plan research; Schema 5 requires `researchInput`; an empty operation script does not simulate trades | `backtest/composition.py`, `backtest/research_runner.py` |
| Prepared-plan run | Frozen plan, historical dates and initial account; supports automatic response and predecessor-aware continuous replay | `backtest/preparation_review.py`, `backtest/plan_schedule.py` |

Source paths without a directory prefix above are under `src/trade_plan_monitor/`. Both current workflows use `UnifiedTradePlan`, but their approval envelopes and research context differ. Workbench `planHash` hashes the stored draft; the executable snapshot hash must be recomputed after validated conversion. They must not be treated as interchangeable hashes.

The gap is therefore more than two lists: selecting a workbench plan currently leads to a different execution-input workflow. A list-only merge would leave the JSON requirement and simulation differences unresolved.

## PRU03. Recommended user flow

1. `/backtests/new` displays one “Select reviewed plans” area. Default to workbench plans; show existing prepared plans in the same selector with an origin label for traceability. Preserve independent server pagination for each source; never present an incomplete browser-side merge as a complete globally sorted list.
2. Workbench rows show stock, name/version and review state; prepared rows show stock, name and effective date. Display dates according to their real meaning, not as a fabricated shared version/date. Selection binds exact identities, not “latest”.
3. Selecting a workbench version opens a structured “Research starting context” form only for information not already available in validated stored data. Then show the same response choices, end date and cost settings used by prepared-plan replay. Normal reuse must not require `researchInput` JSON, a dataset hash or another AI extraction.
4. Selecting an existing prepared plan/valid composition reuses its frozen account, chronology and original review. Keep the existing predecessor-selection checks and continuous account behavior.
5. “Start backtest” freezes the selection/context, checks and supplements historical data using the existing sequence, and submits once. Changing costs or the end date can reuse the frozen selection. A reload with `selectionId` recovers the confirmed context without re-entering it.

The existing raw-source preparation capability remains available through a secondary “Prepare a plan” action; retain its inheritance, review, recovery and deep-link behavior. This increment does not move its editor into `/plans`, change its extraction prompts, or remove its write APIs. Creating in either current workflow makes the reviewed output available to the shared selector. Do not duplicate it into the other store.

Remove the normal user's `LEGACY`/`PREPARED` workflow choice from selection. These remain internal compatibility details. Existing-version scripted research APIs and frozen results retain their behavior; the normal workbench path uses the existing monitoring-loop executor through the adapter below.

## PRU04. One reference contract, two readers

Reuse the current list/detail APIs. Add a small shared frontend selector/composable and a backend read-only workbench adapter; do not introduce a third plan catalogue table or another combined-list API.

```typescript
type ReusablePlanRef =
  | {
      origin: "WORKBENCH";
      planVersionId: string;
      planHash: string;
      contentHash: string;
      sourceHash: string;
      reviewEvidenceHash: string;
      reviewId: string;
      reviewRevision: number;
    }
  | {
      origin: "PREPARATION";
      preparationId: string;
      manifestHash: string;
    };
```

For a workbench row, fetch its existing detail before building the reference; the summary alone does not contain its complete review binding. The backend reads the exact version, source, mapping, review confirmation and timestamp through the existing plan service/unit-of-work boundary. Re-run existing source-review validation and validated draft-to-executable conversion. Reject unreviewed, obsolete, unsupported or mismatched references. Do not read active-plan inventory/facts, change activation or write any monitoring records.

For a preparation reference, use the existing frozen-preparation reader and composition API. Do not reinterpret a preparation ID as a workbench UUID, infer equivalence from identical text, or automatically transfer approval between origins.

**First-increment limit:** one workbench version per run; retain the existing preparation composition limit of 256 entries. Mixed-origin schedules and multiple workbench versions are out of scope and must receive an explicit selection error before data download. Existing preparation chains are not reduced to a single version. This limits new chronology/lineage work while making every eligible single workbench plan reusable.

## PRU05. Research context is separate from plan approval

Workbench review approves trading rules, not a historical opening account. Do not infer holdings from target allocation, use today's simulated inventory as historical inventory, or reset an account from a later plan's narrative.

The context contains `effectiveTradeDate`, optional historical `availableAt`, `informationCutoff`, `initialAccount`, and an explicit `confirmed`/`evidence` declaration. `initialAccount` reuses `LoopAccountInput` and its existing nested field names and validators. Read validated stored facts where available; otherwise ask only for the missing facts through labeled fields. Show the plan source beside the form for reference; do not run another extractor to obtain account facts.

- Keep unknown inventory, cost, acquisition date and sellable quantity unknown; an empty position requires explicit confirmation. Unknown inventory blocks simulated execution under the existing rules.
- Default new funding to the already supported `POSITION_LIMIT_ONLY`; explain that it enforces the plan's maximum position without a cash budget. Do not invent cash or require arbitrary initial capital. Preserve existing historical funding modes.
- Use existing activation constraints and calendars. A missing historical availability time may use the existing, visibly declared effective-day 09:30 assumption; never use today's import/review time as the historical starting point. Unknown authoring time stays unknown. `informationCutoff` must not exceed availability; it requires actual evidence or an explicitly confirmed research assumption, and cannot certify absence of future information.
- Reuse the current start, T+1, CORE, quantity, quote, fee and unknown-value rules. Availability, initial snapshot and opening marks must satisfy the existing loop input boundary checks. Context confirmation cannot widen the plan's own activation/validity window or alter a rule.

Confirming these research facts is not a second review of unchanged plan rules and never grants live activation. Editing a rule or its source returns the user to its existing authoring/review workflow.

## PRU06. Minimal API and persistence extension

All new outer JSON fields use camelCase; reused nested domain fields retain their existing names. These are the bounded first-increment contracts.

| Surface | Scoped change |
|---|---|
| `POST /api/v1/backtest-plan-selections` | Accept `schemaVersion: workbench-loop-selection-v1`, one `WORKBENCH` reference in `plan`, and the PRU05 `context`. Require existing Origin protection and `Idempotency-Key`. Return `201` with `selectionId`, `selectionHash`, the same schema version and the frozen context/plan summary. |
| `GET /api/v1/backtest-plan-selections/{selection_id}` | Read the immutable selection without live-plan reads, AI, data synchronization or worker startup. Return `200` with the same selection view. |
| `GET /api/v1/backtest-run-data` | Add an exclusive `selectionId`/`selectionHash` query alternative to the existing `preparationId`/`manifestHash` pair; retain `endDate`. Reject missing or mixed reference pairs. Add a corresponding typed response alternative; keep old responses unchanged. |
| `POST /api/v1/backtest-runs` | Add a `schemaVersion: workbench-loop-selection-v1` command with `selectionId`, `selectionHash`, existing `response`, `costs` and optional `endDate`. Keep all existing command variants. |

Use the existing error envelope: `404` for a missing reference, `409` for a changed review/hash or idempotency conflict, `422` for unsupported selection/context, and the existing sanitized `503`/retry behavior. Show an actionable message; do not convert an unsupported plan into a silently different replay mode.

Permit one additive `backtest_plan_selection` table in `data/backtest-preparation.sqlite3` to store `selection_id` and canonical immutable `document_json`. Reuse the existing preparation idempotency table through a separately typed selection operation; preserve old preparation decoding. Upgrade the tagged preparation-store schema transactionally, preserving every existing document and receipt. No monitoring, market or result SQL schema change, data migration or new database is required. This is a research-input snapshot, not a new editable plan library. Older binaries reject the upgraded tagged store; do not claim downgrade compatibility.

The document freezes the exact original draft/hash, executable snapshot/hash, source/mapping/review binding and real confirmation time, plus the separately confirmed context. Hash it under `workbench-loop-selection-v1`. Resolve persisted idempotency before reading live plans; same key/body replays the stored selection, different body conflicts. Publish the selection and its receipt atomically. Copy the immutable selection into accepted result-owned input before returning an accepted run receipt. Run, resume and results must then survive loss/unavailability of both original plan stores.

## PRU07. Execution reuse and historical compatibility

Build an actual `LoopPlanVersion` from the workbench executable snapshot and original approval, then use the existing `MonitorLoopInput` single-version path. Preserve original plan-review time separately from research-context confirmation. Do not fabricate extraction IDs, prepared-source hashes, opening-account extraction evidence, or a `FrozenPreparedPlan` just to satisfy its type.

Add a distinct `WorkbenchStoredLoopInput` envelope, proposed `monitor-loop-stored-input-v3`, for the copied selection plus a selection-bound loop input, dataset and day hashes. Extend artifact decoding and the relevant result projections additively. Extract only the small dataset-request construction seam needed to accept a validated schedule/start/account; keep existing prepared-plan wrappers and their output unchanged. No second rule evaluator, market provider, execution loop or worker owner is allowed.

Use the dedicated `workbench-loop-input-v1` input/hash domain and include `selection_hash`, so separately confirmed source/context declarations cannot collide. The execution formula stays `backtest-run-v5`; the existing executor is reused. The shared input decoder adds only this typed alternative. All existing input/hash domains remain unchanged. Source identity and research assumptions remain explicit. Cross-origin text equality does not authorize run deduplication. Leave all old codecs, report contents, run IDs/hashes, export formats and retention rules unchanged. New results show workbench version identity and research context through a new typed source projection; they must not pretend to have a preparation ID or review chain. Existing preparation-specific rule-change views remain unchanged and are not invented for a single workbench version.

The automatic-data sequence, one unfinished heavy-task limit, submission reservation, restart recovery and separate result-read thread remain authoritative. A selection freeze is a bounded metadata operation, not an AI task. Data-check results are provisional; the accepted run freezes its submission boundary once, and idempotent retries reuse it.

## PRU08. Change boundary and alternatives

| Allowed surface | Purpose |
|---|---|
| `web/plan_service.py` and a small read-only adapter | Obtain a validated, review-bound workbench snapshot through current ownership boundaries |
| New selection model/service/store methods under `backtest/` | Freeze only the missing research context and its plan reference |
| `backtest/composition.py`, `automatic_data.py`, `loop_input.py`, `loop_input_store.py` and necessary result projections | Bind the new source to existing data, execution and copied-input paths |
| Existing run schemas/routes, API client and generated contracts | Add the selection command/data-check alternatives and two resource routes |
| Shared selector/context components, `BacktestNewView.vue`, relevant composables | One reuse interaction with structured inputs and preserved preparation entry |
| Focused tests and matching English/Chinese contract/operations updates | Prove compatibility and document the exact extension |

Do not change rule models, AI prompts, predecessor inference, online monitoring decisions, active pointers, simulation inventory, market schemas/providers, task limits, read-thread budgets or CI/dependencies. Do not rewrite the full workbench, move the existing preparation editor, migrate historical plans into `plan_version`, add bidirectional synchronization, remove scripted-research APIs or clean up unrelated code. Preserve the existing uncommitted changes in the workspace.

Rejected alternatives: a browser-only list merge leaves execution differences unresolved; making workbench users re-extract their original text defeats reuse; manufacturing a prepared-plan manifest loses audit meaning; merging both databases or copying approvals introduces migration/dual-write scope. Moving all authoring into one workspace and supporting mixed/multiple workbench schedules require separate approval and design.

## PRU09. Acceptance criteria

- **AC01:** One selector lists both existing sources with correct independent pagination and exact identity. Workbench is the default; selecting either source does not start AI, synchronization or a run.
- **AC02:** An eligible, reviewed but inactive workbench version can run through both `FOLLOW_REMINDERS` and `OBSERVE_ONLY` without raw JSON, re-extraction, re-approval of its rules or live activation. A deterministic authorized fixture produces a fill in the first mode and none in the second; reminders alone cannot bypass execution blockers.
- **AC03:** Missing account/time facts have structured inputs. Unknown holdings are not zero; cost/acquisition/sellable unknowns remain unknown. Defaults and limits match PRU05. Changed source/review hashes, invalid dates and unsupported schedules fail before market downloads or run admission.
- **AC04:** After selection freeze, editing/reviewing another workbench version or changing its active pointer cannot alter the selection. After run acceptance, execution, restart and complete result reads make zero reads/writes to either source plan store.
- **AC05:** Same-key/same-body selection and run retries, including lost receipts and concurrent submissions, return their persisted binding. Different bodies conflict. Cancellation preserves existing task ownership; no duplicate freeze result or heavy run is admitted.
- **AC06:** Existing prepared single plans and valid multi-plan chains retain their chronology, inheritance, account continuity, automatic data and results. Existing `preparationId` links and unfinished preparation recovery remain usable. Mixed-origin and multiple-workbench schedules have explicit errors.
- **AC07:** Golden old prepared/research inputs, report responses and exports are unchanged in canonical bytes/hashes. Missing/corrupt copied dependencies remain visible errors. The new result identifies its actual workbench source and confirmed research assumptions.
- **AC08:** Upgrade a fixture containing both existing preparation formats/idempotency receipts without changing their bytes; fail transactionally on an incompatible store. New commands are strict/disjoint, OpenAPI/generated contracts match, and local Origin protections remain effective.

## PRU10. Verification, commands and conventions

The implementation verification and its limits are recorded in `../../verification/2026-10-19-plan-reuse-unification.md`. Use deterministic offline fixtures; no live AI, Tushare calls, real plan approval or production database modification is needed for acceptance.

New focused tests belong in `tests/unit/test_workbench_selection_context.py`, `tests/integration/test_workbench_plan_selection.py`, `web/tests/unit/WorkbenchPlanReuse.spec.ts` and `web/tests/unit/WorkbenchReplayContext.spec.ts`, and `web/tests/e2e/backtests.spec.ts`. Extend existing loop artifact/API and preparation-chain tests where their boundary changes. Follow Python 3.14, strict frozen Pydantic values and existing error/idempotency style; frontend changes use Vue Composition API, `<script setup lang="ts">`, explicit props/events and current API validators. Keep branch logic at adapters, not in rule evaluation.

From `trade-plan-monitor/`, after implementation:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_workbench_selection_context.py tests/integration/test_workbench_plan_selection.py tests/integration/test_single_plan_library.py tests/integration/test_unified_replay.py tests/integration/test_backtest_result_api.py -q -m "not live"
.venv/Scripts/python.exe -m pytest tests -q -m "not live"
.venv/Scripts/python.exe -m ruff check --no-cache src tests
.venv/Scripts/python.exe scripts/generate_frontend_types.py --check
npm --prefix web test -- --run
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts
```

Always preserve the existing trading and audit checks, use validated reader boundaries and update English/Chinese documentation together. Revisit this design before adding another store/table, broadening schedule support or changing an existing engine/contract's meaning. Never copy live inventory into history, weaken approval, fabricate evidence, or rewrite frozen history. Review relevant existing bilingual specification parity before implementation approval; the approved API addition/removal and current snapshot hashes are recorded in `../monitoring/SPEC-unified-plan.md` U27.

## PRU11. Approved decision

Recommended first increment: one selection/reference workflow, automatic loop reuse for a single reviewed workbench version, unchanged prepared-chain reuse, and no database consolidation. No business requirement is unresolved for this bounded proposal. The user approved the PRU01 meaning of unification and the PRU04 single-workbench/mixed-origin limit on 2026-10-19. A demand for one authoring entry, one physical repository or mixed-source continuous execution changes this scope and must not be absorbed silently.
