# Repair Tasks: Daily Plan Continuity

Status: design for review, 2026-10-10, Asia/Shanghai. [Repair plan](plan.md); [Chinese copy](todo.zh-CN.md). **1 of 20 repair tasks complete.** RP IDs are separate from historical ML completion/cancellation records. This list is implementation scope, not a claim of implementation authorization or executed verification.


Implementation update, 2026-10-10: the user authorized this bounded repair in the current session. RP-T01 is complete: restored original ML01–ML13, concrete codec/order-edit matrix, 11 fixture checks and 14 fixture/legacy compatibility checks pass; deliberate 899500→899501 oracle mutation fails, exact bytes restored. Ruff, bilingual section/link checks and diff review pass. This validates the baseline only, not runtime continuity. **1 of 20 repair tasks complete.** Next: RP-T02. Historical planning-only authorization wording below is superseded by this instruction; concrete API review is still pending.

RP-T02 is complete: distinct v2 source/schedule/input codecs preserve v1 boundaries, canonical effective-day selection, first-day opening-account anchoring and causal authority. The independent review found and corrected nested subtype acceptance and skipped-first-day defects. 65 focused schedule/input/fixture/legacy compatibility checks pass; the successor-opening mutation is detected and restored. Ruff and diff checks pass. **2 of 20 repair tasks complete.** Next: RP-T03; RP-C01 is not yet passed.

## RP-TASK-RULES. Execution boundary

2026-10-10 parity erratum: the Chinese historical ML-T35/ML-T36 file counts are corrected to 5/6, matching their existing exact file lists and the English record. Historical completion and verification evidence are unchanged.

Follow the ordered list below; dependencies additionally identify each prerequisite. Each row contains its exact file allowlist, acceptance and verification. Prefix P/V commands as defined in RP-CHECKS. A file listed in a verification command is a read/test target, not extra edit permission. Planned new files are labelled. Per-task source changes may not exceed this list; routine bilingual progress/evidence updates to this plan/list and the existing verification pair must identify the actual outcome and cannot change the baseline. Split an increment to about five handwritten code/test files without changing its behavior; list paired documentation/mechanical outputs separately.

RP-T01 restores cancelled ML requirements without rewriting historical completion evidence. New v2 tests accept continuity while old-format rejection tests remain compatibility checks. Keep the current one-source workflow usable during integration; no incomplete candidate acquires execution authority. No new global feature-flag framework is part of this sequence.

## RP-TASKS. Ordered work

### RP-T01. Lock restored requirements and independent fixtures

- [x] Implemented, verified and diff reviewed.
- **Dependencies:** None; **Acceptance:** RP-A09, RP-A10, RP-A12.
- **Allowed files:** `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.md`; `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md`; `tests/fixtures/monitor_loop_continuity.json` (new); `tests/unit/test_monitor_loop_continuity_fixture.py` (new).
- **Result:** Restore original business clauses while retaining later platform decisions; record the RP04 field/version matrix, literal fixture oracle and old frozen compatibility cases. No runtime change.
- **Verify:** `P: tests/unit/test_monitor_loop_continuity_fixture.py`.

### RP-T02. Restore scheduled input

- [x] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T01; **Acceptance:** RP-A04, RP-A07, RP-A10.
- **Allowed files:** `src/trade_plan_monitor/backtest/plan_schedule.py`; `src/trade_plan_monitor/backtest/loop_input.py`; `tests/unit/test_monitor_loop_schedule.py`; `tests/unit/test_monitor_loop_input.py`.
- **Result:** Add new-mode version arrays, canonical order and effective-day selection. Reject date/conflict/start/size violations; preserve v1 decoding and same-version continuity.
- **Verify:** `P: tests/unit/test_monitor_loop_schedule.py tests/unit/test_monitor_loop_input.py`.

### RP-T03. Switch inside one continuous session

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T02; **Acceptance:** RP-A05, RP-A06, RP-A09.
- **Allowed files:** `src/trade_plan_monitor/backtest/loop_session.py`; `src/trade_plan_monitor/backtest/loop_runner.py`; `src/trade_plan_monitor/backtest/response_policy.py`; `src/trade_plan_monitor/backtest/loop_report.py`; `tests/integration/test_monitor_loop_plan_switch.py` (new).
- **Result:** Apply replacement before evaluation/execution; keep account/risk, close old ordinary intents, record lifecycle facts and account-context incompatibility. Prove the RP-A09 literal account across boundaries.
- **Verify:** `P: tests/integration/test_monitor_loop_plan_switch.py tests/integration/test_monitor_loop_account.py tests/integration/test_monitor_loop_cycle.py`.

### RP-T04. Persist ordered preparation items

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T01; **Acceptance:** RP-A01, RP-A03, RP-A10.
- **Allowed files:** `src/trade_plan_monitor/backtest/preparation_models.py`; `src/trade_plan_monitor/backtest/preparation_store.py`; `tests/integration/test_plan_preparation_store.py`; `tests/unit/test_monitor_loop_input.py`.
- **Result:** Store a v2 item collection and dependency/revision bindings inside the existing document table; enforce limits/idempotency and descendant invalidation; preserve old records/receipts.
- **Verify:** `P: tests/integration/test_plan_preparation_store.py tests/unit/test_monitor_loop_input.py`.

### RP-T05. Extract source-bound follow-up changes

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T04; **Acceptance:** RP-A02, RP-A10.
- **Allowed files:** `src/trade_plan_monitor/ai/loop_plan_extraction.py`; `src/trade_plan_monitor/ai/plan_update_extraction.py` (new); `src/trade_plan_monitor/web/ai_service.py`; `tests/unit/test_monitor_loop_extraction.py`.
- **Result:** Version the first/follow-up extraction contract; pass only validated past context and explicit change scope. Preserve provider safeguards and ordinary live extraction; no model-created approval.
- **Verify:** `P: tests/unit/test_monitor_loop_extraction.py tests/integration/test_ai_provider_contract.py`.

### RP-T06. Materialize complete reviewed candidates

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T05; **Acceptance:** RP-A02, RP-A06.
- **Allowed files:** `src/trade_plan_monitor/backtest/plan_updates.py` (new); `src/trade_plan_monitor/ai/update_review.py` (new); `tests/unit/test_plan_update_merge.py` (new); `tests/unit/test_plan_update_bindings.py` (new).
- **Result:** Apply supported changes deterministically; show removed/retained rules and original inherited bindings. Block ambiguous scope, unresolved bases and fabricated account changes.
- **Verify:** `P: tests/unit/test_plan_update_merge.py tests/unit/test_plan_update_bindings.py`.

### RP-T07. Run and recover sequential extraction

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T06; **Acceptance:** RP-A01, RP-A03, RP-A11.
- **Allowed files:** `src/trade_plan_monitor/backtest/preparation_service.py`; `src/trade_plan_monitor/backtest/preparation_worker.py`; `src/trade_plan_monitor/backtest/preparation_store.py`; `tests/integration/test_plan_preparation_worker.py`; `tests/integration/test_plan_preparation_api.py`.
- **Result:** One operation processes items serially and retains exclusion until settled; retry only affected work; source/base/generation fences reject late responses and stop dependent extraction.
- **Verify:** `P: tests/integration/test_plan_preparation_worker.py tests/integration/test_plan_preparation_api.py`.

### RP-T08. Review and freeze the chain

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T07; **Acceptance:** RP-A02, RP-A03, RP-A06.
- **Allowed files:** `src/trade_plan_monitor/backtest/preparation_review.py`; `src/trade_plan_monitor/backtest/preparation_models.py`; `src/trade_plan_monitor/backtest/preparation_store.py`; `tests/integration/test_plan_preparation_review.py`.
- **Result:** Freeze accepted full snapshots, differences, schedule and one opening account against exact revisions. Validation alone grants no replay authority; preserve unsupported clauses and old frozen input.
- **Verify:** `P: tests/integration/test_plan_preparation_review.py`.

### RP-T09. Freeze all applicable evidence requirements

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T03, RP-T08; **Acceptance:** RP-A04, RP-A07, RP-A10.
- **Allowed files:** `src/trade_plan_monitor/backtest/loop_dataset.py`; `src/trade_plan_monitor/backtest/loop_replay.py`; `tests/integration/test_monitor_loop_dataset.py`; `tests/unit/test_monitor_loop_cutoff.py`.
- **Result:** Freeze the relevant requirement union and feed only active-version evidence; report successor gaps; preserve warmup, calendar, cutoff and old dataset bytes.
- **Verify:** `P: tests/integration/test_monitor_loop_dataset.py tests/unit/test_monitor_loop_cutoff.py`.

### RP-T10. Submit and replay one frozen chain

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T09; **Acceptance:** RP-A01, RP-A06, RP-A07, RP-A10.
- **Allowed files:** `src/trade_plan_monitor/backtest/loop_input_store.py`; `src/trade_plan_monitor/backtest/composition.py`; `src/trade_plan_monitor/backtest/application.py`; `tests/integration/test_monitor_loop_input_store.py`; `tests/integration/test_monitor_loop_submission.py`.
- **Result:** Store a versioned immutable chain bundle and submit one bounded reference/job. Retry keeps run ID/cutoff; replay uses one account and cannot read mutable preparation or call AI.
- **Verify:** `P: tests/integration/test_monitor_loop_input_store.py tests/integration/test_monitor_loop_submission.py tests/integration/test_monitor_loop_worker.py`.

### RP-T11. Publish continuous causal results

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T10; **Acceptance:** RP-A07, RP-A08, RP-A10.
- **Allowed files:** `src/trade_plan_monitor/backtest/loop_report.py`; `src/trade_plan_monitor/backtest/loop_publication.py`; `src/trade_plan_monitor/backtest/results.py`; `src/trade_plan_monitor/backtest/loop_input_store.py`; `tests/integration/test_monitor_loop_publication.py`.
- **Result:** Publish one version-aware report with continuous valuation and causal event identity. Preserve atomic completion, bounds, old readers and latest-30 retention.
- **Verify:** `P: tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_loop_publication.py tests/integration/test_monitor_loop_retention.py`.

### RP-T12. Expose bounded preparation operations

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T08, RP-T11; **Acceptance:** RP-A01, RP-A03, RP-A11.
- **Allowed files:** `src/trade_plan_monitor/web/preparation_schemas.py`; `src/trade_plan_monitor/web/routers/backtest_preparations.py`; `src/trade_plan_monitor/backtest/preparation_service.py`; `tests/integration/test_plan_preparation_api.py`; `tests/integration/test_plan_preparation_contract.py`.
- **Result:** Extend only RP04 resources/branches for item entry, paging, corrections, retry and chain review. Verify 4 MiB HTTP/aggregate limits, revisions, exclusion and v1 compatibility.
- **Verify:** `P: tests/integration/test_plan_preparation_api.py tests/integration/test_plan_preparation_contract.py`.

### RP-T13. Expose one run and version-aware results

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T12; **Acceptance:** RP-A01, RP-A08, RP-A10.
- **Allowed files:** `src/trade_plan_monitor/web/backtest_schemas.py`; `src/trade_plan_monitor/web/routers/backtest_runs.py`; `src/trade_plan_monitor/backtest/composition.py`; `tests/integration/test_monitor_loop_result_api.py`; `tests/integration/test_monitor_loop_contract.py`.
- **Result:** Accept one reviewed-chain submission and return bounded version/calendar/event projections. Preserve old response branches, errors, history and the absence of new exports.
- **Verify:** `P: tests/integration/test_monitor_loop_result_api.py tests/integration/test_monitor_loop_contract.py`.

### RP-T14. Generate and inspect exact contract changes

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T13; **Acceptance:** RP-A10, RP-A12.
- **Allowed files:** `openapi.json`; `openapi.runtime-status.json`; `web/src/api/generated.ts`; `web/src/api/generated-runtime-status.ts`; `scripts/generate_frontend_types.py`; `tests/integration/test_openapi_snapshot.py`; `docs/specifications/monitoring/SPEC-unified-plan.md`; `docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md`.
- **Result:** Generate both profiles, inspect only agreed new branches/item-read path and verify old branches. Generator changes only if required for these shapes. Record contract approval through the existing process only after concrete diff review, distinguishing review evidence from user authorization; never hand-edit generated types or silently approve digests. The paired approval documents are separate from the mechanical outputs.
- **Verify:** `G; P: tests/integration/test_openapi_snapshot.py tests/integration/test_plan_preparation_contract.py tests/integration/test_monitor_loop_contract.py`.

### RP-T15. Connect preparation controller and transport

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T14; **Acceptance:** RP-A01, RP-A03.
- **Allowed files:** `web/src/api/preparations.ts`; `web/src/api/preparationReview.ts`; `web/src/composables/usePlanPreparation.ts`; `web/tests/unit/PlanPreparation.spec.ts`.
- **Result:** Keep one preparation controller with ordered item projections and stable mutation keys; preserve unsaved changes, revision fences, polling cleanup and settled/unknown-state controls.
- **Verify:** `V: web/tests/unit/PlanPreparation.spec.ts`.

### RP-T16. Show grouped entry and daily review

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T15; **Acceptance:** RP-A01, RP-A02, RP-A04.
- **Allowed files:** `web/src/components/backtests/PlanPreparationSourceForm.vue`; `web/src/components/backtests/PlanPreparationProgress.vue`; `web/src/components/backtests/PlanPreparationReview.vue`; `web/src/views/BacktestNewView.vue`; `web/tests/unit/PlanPreparationReview.spec.ts`.
- **Result:** One entry action shows explicit source boundaries, per-item progress/diffs, daily applicability, opening account and unresolved issues before chain review; retain existing layout conventions.
- **Verify:** `V: web/tests/unit/PlanPreparationReview.spec.ts web/tests/unit/BacktestNewView.spec.ts`.

### RP-T17. Submit once from the reviewed collection

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T16; **Acceptance:** RP-A01, RP-A07, RP-A11.
- **Allowed files:** `web/src/api/backtests.ts`; `web/src/composables/useBacktestRunForm.ts`; `web/src/components/backtests/BacktestRunForm.vue`; `web/tests/unit/MonitorLoopRunForm.spec.ts`.
- **Result:** Bind one reviewed-chain manifest, dataset/response/end settings and one submit action. No per-item replay loop; retries reuse the same accepted run.
- **Verify:** `V: web/tests/unit/MonitorLoopRunForm.spec.ts`.

### RP-T18. Display the continuous result

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T17; **Acceptance:** RP-A08, RP-A10.
- **Allowed files:** `web/src/components/backtests/MonitorLoopTimeline.vue`; `web/src/components/backtests/MonitorLoopSummary.vue`; `web/src/views/BacktestRunDetailView.vue`; `web/tests/unit/MonitorLoopResults.spec.ts`.
- **Result:** Show version transitions and account-context/old-intent explanations in the existing report with one continuous curve; keep old result rendering.
- **Verify:** `V: web/tests/unit/MonitorLoopResults.spec.ts web/tests/unit/BacktestRunDetailView.spec.ts`.

### RP-T19. Verify the original business journey

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T18; **Acceptance:** RP-A01–RP-A11.
- **Allowed files:** `tests/integration/test_monitor_loop_plan_switch.py`; `tests/integration/test_monitor_loop_parity.py`; `tests/integration/test_monitor_loop_faults.py`; `tests/integration/test_monitor_loop_worker.py`; `web/tests/e2e/monitor-loop-backtest.spec.ts`.
- **Result:** Exercise RP-A01–RP-A11 with the independent four-version fixture, future-input perturbation, failures and real browser flow; retain original platform thresholds. Record remaining real-source blockers honestly.
- **Verify:** `P: tests/integration/test_monitor_loop_plan_switch.py tests/integration/test_monitor_loop_parity.py tests/integration/test_monitor_loop_faults.py tests/integration/test_monitor_loop_worker.py; E; F`.

### RP-T20. Reconcile evidence and operating guidance

- [ ] Implemented, verified and diff reviewed.
- **Dependencies:** RP-T19; **Acceptance:** RP-A12.
- **Allowed files:** `docs/operations/monitor-loop-backtest.md`; `docs/operations/monitor-loop-backtest.zh-CN.md`; `docs/verification/monitor-loop-backtest.md`; `docs/verification/monitor-loop-backtest.zh-CN.md`; `docs/specifications/monitoring/SPEC-unified-plan.md`; `docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md`.
- **Result:** Document one-upload/one-run behavior and exact evidence/limits; reconcile original ML gates and both language/API versions through the existing concrete contract-review process. No invented approval or completion. Documentation may be split by pair.
- **Verify:** `D; G; inspect original ML-A07/ML-A11/ML-A13/ML-A16–ML-A18 evidence`.

## RP-CHECKPOINTS. Required checkpoints

| ID | After | Gate |
|---|---|---|
| RP-C01 | RP-T03 | Reviewed baseline plus actual offline schedule/switch/account continuity; RP-A09 literal values. |
| RP-C02 | RP-T06 | Durable source-bound extraction/merge with explicit unresolved cases. |
| RP-C03 | RP-T08 | Sequential recovery and whole-chain freeze; no second admitted operation. |
| RP-C04 | RP-T11 | Frozen data/input through one worker to atomic continuous report and old compatibility. |
| RP-C05 | RP-T14 | Actual API and both generated profiles match the bounded design; approval is not inferred from generation. |
| RP-C06 | RP-T17 | Grouped preparation/calendar/review leads to exactly one run. |
| RP-C07 | RP-T20 | Original business acceptance, browser/fault/compatibility evidence and bilingual instructions reconciled. |

## RP-CHECKS. Verification commands

Commands run from `trade-plan-monitor/`. Filenames marked new above are planned, not already executed. A passing task suite is not a substitute for the original business gates.

- **P:** `.venv/Scripts/python.exe -m pytest <listed paths> -q -m "not live"`.
- **V:** `npm --prefix web run test -- --run <listed paths with the leading web/ removed>`; then `npm --prefix web run type-check`.
- **G:** `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`; review both generated OpenAPI/type diffs against RP04. Existing approved-snapshot failures require concrete review, not silent digest changes.
- **E:** `npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts` with the existing fake-provider browser fixture.
- **F:** affected existing shared-runtime/accounting, one-task/recovery, frozen replay/export compatibility tests; `.venv/Scripts/python.exe -m ruff check src tests scripts`; `npm --prefix web run test -- --run`; `npm --prefix web run type-check`; `npm --prefix web run build`; original load experiment when RP07 requires it. Record exact selected test paths and outcomes; do not claim unexecuted checks.
- **D:** `git diff --check`, bilingual IDs/limits/paths/commands/acceptance parity and relative-link checks; inspect the final scope against RP05.

No implementation task/test has been executed by writing this plan. The earlier five focused checks established the fixed-version restriction only; they are not repair acceptance.

## RP-TASK-HISTORY. Superseded delivery record

The following previous task list is retained unchanged. Its 37 completed items, cancelled ML-T06/ML-T09 and prior completion statements describe the narrower fixed-version implementation. They cannot exclude original requirements from this repair or be counted as repair completion.

<!-- prior-delivery-record -->

# Active Task List: Monitoring-loop Backtest

> Implementation authorized, updated 2026-10-09. Plan: [plan.md](plan.md); Chinese copy: [todo.zh-CN.md](todo.zh-CN.md). Implemented and verified: ML-T01, ML-T02, ML-T03, ML-T04, ML-T05, ML-T07, ML-T08, ML-T10, ML-T11, ML-T12, ML-T13, ML-T14, ML-T15, ML-T16, ML-T17, ML-T18, ML-T19, ML-T20, ML-T21, ML-T22, ML-T23, ML-T24, ML-T25, ML-T26, ML-T27, ML-T28, ML-T29, ML-T30, ML-T31, ML-T32, ML-T33, ML-T34, ML-T35, ML-T39, ML-T36, ML-T37, ML-T38. Evidence: [verification](../docs/verification/monitor-loop-backtest.md). Previously completed historical tasks are retained below.
> Scope correction 2026-10-07; progress 2026-10-09: ML-T06/ML-T09 are cancelled; 37 completed, 0 pending active tasks, 37 active / 39 retained IDs, 13 checkpoints. ML-A07 is not a gate. One frozen plan and one unfinished task; evidence MV17–MV46.

Run commands from `trade-plan-monitor/`; new files are planned outputs. Execute verification after implementing its task; writing this list does not mean those checks ran. Keep each task to about five primary files; split expanded scope first. Contract generation and digest approval are separate; do not silently approve an API to pass a check.

Whole-delivery gaps are grouped in [MV10](../docs/verification/monitor-loop-backtest.md#mv10-complete-acceptance-gap-register). Startup-decoupling-only acceptance is [MV11](../docs/verification/monitor-loop-backtest.md#mv11-startup-decoupling-acceptance-only); do not make the pending business/resource redesign its prerequisite. Both reference existing scope without adding requirements. Cancelled protection items cannot return as implicit prerequisites.

## ML-T01. Define frozen loop input and time boundaries

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T30`
- **Acceptance:** Strict versioned input accepts exactly one plan/source and separates source/activation/end times, cost/mark and zero/unknown cash. Reject second entries through construction/copy/decoding; preserve cross-day activation, validity and deterministic end resolution without changing legacy bytes.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_input.py`, `src/trade_plan_monitor/backtest/plan_schedule.py`, `tests/unit/test_monitor_loop_input.py`, `tests/unit/test_monitor_loop_schedule.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A04, ML-A09, ML-A11, ML-A12, ML-A15.
- **Progress:** Separate `monitor-loop-input-v1` / `backtest-run-v5` contracts, exact opening cost, independent mark, unknown/zero cash, reviewed evidence and deterministic boundaries/calendar are implemented. The 2026-10-07 scope correction restricts source/entry count to one and removes successor selection. One activation continues across days while valid; authoring date-only inputs remain explicit. Other lot/safe-integer/evaluation/provider guards remain. Original evidence MV14; current scope regression MV17.

## ML-T02. Extract a shared simulation participant

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T01`
- **Acceptance:** Move existing authorization/quantity/inventory transitions behind an application participant with caller-owned transactions; online commands and old replay retain their prior receipts, errors and behavior.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_simulation_participant.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_unified_replay.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/state/simulation.py`, `src/trade_plan_monitor/web/daily_service.py`, `src/trade_plan_monitor/backtest/research_session.py`, `tests/integration/test_simulation_participant.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A05, ML-A08, ML-A09.
- **Progress:** `state/simulation.py` owns typed commands/receipts and the existing authorization, full-quantity, inventory, signal and risk transitions. The caller owns commit/rollback; Web maps domain rejections to its existing error envelope, and old research simulation no longer calls the private HTTP helper. Independent rollback/revision/no-Web-import tests and online/legacy replay regressions pass. This does not yet implement research cash commitment or reminder capture. Executed evidence: MV14.

## ML-T03. Capture reminders in a private loop session

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T02`
- **Acceptance:** Use shared monitoring/delivery eligibility, isolated repositories and deterministic clock/IDs; capture valid reminders and reject stale evidence. Pure technical alerts never authorize execution; no live sink is constructed.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_unified_runtime.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_session.py`, `src/trade_plan_monitor/backtest/reminder_capture.py`, `src/trade_plan_monitor/runtime/daily_service.py`, `src/trade_plan_monitor/state/daily_accounting.py`, `src/trade_plan_monitor/state/daily_state_models.py`, `tests/integration/test_monitor_loop_reminders.py`
- **Scope:** M (6 primary files including tests); **Trace:** ML-A02, ML-A03, ML-A06, ML-A08.
- **Implementation slices:** ML-T03.1 covers the opening-lot state model/accounting and its tests (3 files); ML-T03.2 covers the private session/capture, runtime ID/eligibility hooks and the same test file (4 files). The private variant preserves unknown acquisition dates/sellable quantities; no production migration or transport change is included.
- **Progress:** Fresh private SQLite state uses shared monitoring and send eligibility, frozen review/active rows, virtual time and causal reminder IDs. Bounded, paged capture is transactional/idempotent; stale quote/minute/fact/inventory/review/activation evidence is suppressed. Pure alerts retain no trade authority. The ordinary send path now rejects revised source minutes, matching the existing pure-alert fence. No sink/provider/network/Web participant is loaded by the private cycle. Executed evidence: MV15.

### ML-C01. Checkpoint

- [x] Shared monitoring participants preserve online behavior.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T04. Commit account and inventory atomically

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T02`, `ML-T03`
- **Acceptance:** Apply exact fees/slippage and full-quantity cash checks before one transaction covering money, lots, signal consumption and receipts. Preserve 401050-fen opening cost; failed/repeated commits cannot leave partial or duplicate effects.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_costs.py tests/integration/test_monitor_loop_account.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_account.py`, `src/trade_plan_monitor/backtest/loop_session.py`, `tests/unit/test_monitor_loop_costs.py`, `tests/integration/test_monitor_loop_account.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A05, ML-A09, ML-A12, ML-A13.
- **Progress:** Exact whole-fen settlement applies absolute per-share slippage and existing upward fee rounding. Private account/lot cost, shared inventory/signal/risk transitions and both receipts use one caller-owned transaction. Cash includes all fees; unknown or insufficient cash cannot commit partial quantity. Opening cost remains 401050 fen, sell basis follows the actually debited batches with residual fen retained, and unknown cost preserves unknown P/L. Repeated request keys verify command/cost bindings; early/late failures, stale revisions and revised source minutes cannot commit. Executed evidence: MV16. ML-T05 implements response timing/automatic cycles; evidence MV19.

## ML-T05. Run a single-plan reminder response cycle

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T03`, `ML-T04`
- **Acceptance:** A reviewed fixture discovers buy/sell times without a trade script; enforce next eligible interval, risk priority, single occurrence consumption and finite bounds. Observe/recorded modes do not add unsolicited trades.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_cycle.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_runner.py`, `src/trade_plan_monitor/backtest/response_policy.py`, `src/trade_plan_monitor/backtest/loop_session.py`, `tests/integration/test_monitor_loop_cycle.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01, ML-A02, ML-A03, ML-A04, ML-A06.
- **Progress:** Private frames bind current-minute execution evidence; eligible captured reminders create bounded intents, next complete minute intervals respect response delay, shared state controls risk/conflicts and full quantities, and each fill refreshes monitoring. Plan expiry closes ordinary authority while preserving risk maintenance. Observe/recorded modes generate no automatic trades. ML-T05/ML-C02 pass MV19; recorded-action import, frozen-dataset reader, worker/API/UI/report integration remain separate pending tasks.

## ML-T06. Cancelled: daily plan switching

- [ ] Cancelled by the user on 2026-10-07; excluded from implementation and completion gates, not marked complete.
- **Dependencies:** None
- **Acceptance:** Outside the single-plan release; retained ID preserves traceability.
- **Verification:** None; cancellation is a scope decision, not a passed test.
- **Primary files:** None; former switching/inheritance outputs are no longer planned.
- **Scope:** Cancelled; **Trace:** ML-A07.

### ML-C02. Checkpoint

- [x] Reviewed fixtures run a complete single-plan cycle with atomic accounts; ML-T06 is cancelled.
- [x] Record executed evidence in MV19; resolve failures before dependent work without lowering the bar.

## ML-T07. Persist single-plan preparation and revision state

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T01`
- **Acceptance:** Create a separately tagged preparation store with exactly one source, bounded attempts, candidate/review revisions and idempotency; reject cross-domain paths. Persist restart state while validation remains separate from approval.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_store.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/preparation_models.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_store.py`
- **Scope:** M (3 primary files including tests); **Trace:** ML-A16, ML-A18.
- **Evidence:** MV20: 53 preparation-store cases pass within the 92-case related integration gate. Private persistence only; MV21 completes ML-T08 extraction and ML-C03. ML-T10/ML-T11/ML-T12 retain worker drain/global admission, semantic review/freeze and API integration.

## ML-T08. Extract one complete plan and opening account

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T07`
- **Acceptance:** Version the complete-plan/opening-account output, reuse provider/parsing guards and retain source spans. One source contains no predecessor context/update operations; missing facts/unsupported semantics stay unresolved. Preserve ordinary extraction regressions.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_extraction.py tests/unit/test_current_plan_extraction_security.py tests/unit/test_ai_plan_extraction_v4.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/ai/loop_plan_extraction.py`, `src/trade_plan_monitor/ai/extraction.py`, `tests/unit/test_monitor_loop_extraction.py`, `tests/fixtures/ai/monitor-loop-extraction-cases.json`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A12, ML-A14, ML-A16, ML-A17.
- **Evidence:** MV21: 70 new extraction cases; the 93-case task gate and full related regression pass. One versioned Schema 5 candidate retains exact opening facts/spans and unknown inputs, rejects target/hypothetical/forged facts, and round-trips through ML-T07 storage. No worker, public entry or approval is added.

## ML-T09. Cancelled: successor inheritance and merge

- [ ] Cancelled by the user on 2026-10-07; excluded from implementation and completion gates, not marked complete.
- **Dependencies:** None
- **Acceptance:** Outside the single-plan release; retained ID preserves traceability.
- **Verification:** None; cancellation is a scope decision, not a passed test.
- **Primary files:** None; former switching/inheritance outputs are no longer planned.
- **Scope:** Cancelled; **Trace:** ML-A16, ML-A17.

### ML-C03. Checkpoint

- [x] Single-source persistence, complete extraction and original evidence bindings pass; ML-T09 is cancelled.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar. MV20/MV21 record the private persistence/extraction gate; ML-T10 passes MV22, ML-T11 passes MV23, ML-T12/ML-C04 pass MV24, ML-T13 passes MV25, ML-T14 passes MV26, and ML-T15 is next.

## ML-T10. Resume single-source extraction safely

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T07`, `ML-T08`, `ML-T34`
- **Acceptance:** Claim the one source with generation/source/revision fences and persist progress outside calls. Reuse existing guards and bounded retryable attempts; edit/cancel/restart rejects stale completion. Use owned backtest threads. Unknown paid outcomes require explicit recovery; no new global AI budget gates isolation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/preparation_models.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_worker.py`, `src/trade_plan_monitor/web/ai_service.py`, `tests/integration/test_plan_preparation_worker.py`
- **Scope:** Two M increments, 4 primary files each (7 unique including the shared test); **Trace:** ML-A16, ML-A18. First persist worker ownership/progress and read the existing admission reservation for recovery; then connect owned calls and configured AI. No new job kind, queue, database or public route.
- **Evidence:** MV22: 29 worker cases and the 3000-case final regression pass. Owned calls retain existing global admission through physical drain; unknown paid outcomes require explicit ended confirmation. Reads/replayed receipts never dispatch, and known retries remain within three durable attempts. Semantic review/freeze and public preparation integration pass ML-T11/ML-T12 in MV23/MV24.

## ML-T11. Review and freeze one complete prepared plan

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T08`, `ML-T10`
- **Acceptance:** Bind explicit review to exact source/content/account/evidence revisions and freeze one immutable manifest. Source corrections invalidate its candidate/review; submitted runs remain frozen. Validation cannot create approval or activate production plans.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_review.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/preparation_review.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_review.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A17, ML-A18.
- **Evidence:** MV23: 51 review cases pass. Exact revision/source/plan/account/evidence bindings, atomic manifest/declaration, original receipt replay and physical admission retention are verified. Unknown opening facts remain explicit; forged AI/legacy review flags and future opening marks cannot grant authority. Public preparation integration and ML-C04 pass MV24.

## ML-T12. Expose the preparation application path

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T10`, `ML-T11`, `ML-T33`
- **Acceptance:** Connect exactly-one-source create/read/edit/extract/cancel/review operations to on-demand capability ownership and acquired-resource shutdown. HTTP tests prove second-source rejection, revisions, idempotency, bounded projections and fake-AI progress without live-plan mutations. Guard readiness; preparation-store failure degrades backtest only.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/web/preparation_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_preparations.py`, `src/trade_plan_monitor/web/app.py`, `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_api.py`
- **Scope:** Two M increments, 4 primary files each (7 unique including shared tests); **Trace:** ML-A10, ML-A16, ML-A18. First close create admission/receipt and capability ownership, then mount bounded HTTP commands. Stage schema publication until ML-T13; preserve approved contracts/digests.
- **Evidence:** MV24: 53 task cases pass, including a real loopback HTTP fake-AI cancel/edit/extract/review/restart journey. Invalid requests acquire no resources; preparation storage opens on demand, failure is cached, reads never activate the job coordinator, original receipts replay during unrelated work, and global admission lasts through physical drain. Unknown recovery never resubmits; legacy flags/raw payloads cannot grant frozen authority. ML-T13 passes MV25, ML-T14 passes MV26; ML-T15 is next.

### ML-C04. Checkpoint

- [x] Restart/cancel/edit/review works through real HTTP with fake AI.
- [x] Record executed evidence in MV24; resolve failures before dependent work without lowering the bar.

## ML-T13. Generate preparation transport contracts

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T12`
- **Acceptance:** Generate contracts from mounted production routes and test the new discriminated payloads and error shapes. Preserve unaffected routes/types; document API changes for ML-T29 approval rather than stamping a digest early.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **Primary files:** `src/trade_plan_monitor/web/preparation_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_preparations.py`, `scripts/generate_frontend_types.py`, `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_plan_preparation_contract.py`
- **Scope:** Three increments (2 / 2 / 6 primary files; 8 unique including shared tests); **Trace:** ML-A10, ML-A16. First narrow candidate variants and public revision bounds without changing successful wire values; then publish the mounted router and its actual success/error statuses; finally normalize newly split input/output schema names while retaining old response names, generate both profiles and verify unchanged existing routes/types. The publication and generated-output increments are committed together after drift checks pass. Old approval digest/path gates remain untouched and pending ML-T29; record their exact results without suppressing them.
- **Evidence:** MV25: 20 preparation-contract cases pass; both profiles add seven operations while all old paths/schemas/types remain unchanged. Candidate narrowing and command rejection compile correctly. The final regression has 3509 passed and exactly two unchanged approval gates pending ML-T29; frontend 807 tests, type checking and build pass. ML-T14 passes MV26; ML-T15 is next and ML-C05 still requires route/review UI.

## ML-T14. Build one-source upload and progress UI

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T13`
- **Acceptance:** Accept exactly one source, show extraction state/errors and support stable retry/cancel. Polling stops on idle or terminal drained states, hidden tabs and unmount; edited evidence must be saved before extraction. Cancellation waiting, UNKNOWN and other unfinished work continue blocking fresh actions; malformed source/server errors remain visible and editable. No batch order or multi-plan selection.
- **Verification:** `npm --prefix web run test -- --run tests/unit/PlanPreparation.spec.ts`
- **Primary files:** `web/src/api/preparations.ts`, `web/src/composables/usePlanPreparation.ts`, `web/src/components/backtests/PlanPreparationSourceForm.vue`, `web/src/components/backtests/PlanPreparationProgress.vue`, `web/tests/unit/PlanPreparation.spec.ts`
- **Scope:** Three increments (2 / 2 / 4 primary files; 5 unique including shared tests); **Trace:** ML-A10, ML-A16, ML-A18. First add bounded same-origin transport and stable request receipts; then one preparation controller with revision-safe retry, physical-drain/unknown fences and stopped polling; finally controlled single-text/file input and progress components, with unsaved-evidence/stale-read refresh fences in the same controller; the total remains 5 unique primary files. Explicit ended confirmation only recovers UNKNOWN work and never resubmits. Bind the route and review preview in ML-T15. Reuse existing design tokens and validate real browser behavior with a temporary harness; no backend, generated contract or approval-gate change.
- **Evidence:** MV26: 50 focused tests pass; all frontend 857 tests / 58 files, type checking and build pass. A real isolated Chrome harness verifies cancellation physical-drain waiting, same-intent replay, explicit UNKNOWN recovery, invalid UTF-8 preservation and polling disposal. Widths 320 / 768 / 1024 / 1440 have no overflow, axe violations or browser errors. Related backend checks have 92 passed; the two existing API approval gates remain pending ML-T29. ML-T15 is next; ML-C05 still awaits route composition and review UI.

## ML-T15. Preview and review one prepared plan

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T14`
- **Acceptance:** Show initial account, complete rules, source evidence, historical start/availability and unresolved clauses. Proceed only with the exact reviewed revision; source edits visibly invalidate approval. No rule diffs, successor calendar or descendants.
- **Verification:** `npm --prefix web run test -- --run tests/unit/PlanPreparationReview.spec.ts`
- **Primary files:** `web/src/api/preparations.ts`, `web/src/api/preparationReview.ts`, `web/src/components/backtests/PlanPreparationReview.vue`, `web/src/views/BacktestNewView.vue`, `web/src/composables/usePlanPreparation.ts`, `web/tests/unit/PlanPreparationReview.spec.ts`, `web/tests/unit/PlanPreparation.spec.ts`, `web/tests/fixtures/plan-preparation-review.json`
- **Scope:** Four increments (5 / 3 / 2 / 5 primary files; 8 unique including shared tests); **Trace:** ML-A10, ML-A12, ML-A17, ML-A18. The first increment includes the real backend-generated candidate/frozen fixture and extends the existing API test double for the required review command. Real HTTP verification exposed the distinct `PreparationFrozenView` review receipt; the fourth increment corrects transport/controller and test doubles before final verification, without changing server contracts.

- **Implementation boundary:** First add review transport and bounded candidate/source/account shape checks for readonly previews; then explicit controller review and a readable complete preview; finally compose source/progress/review in the existing creation page after an explicit mode choice. Unsaved evidence, unfinished work and uncertain mutations block review and mode switching; confirmation clears when source/candidate/review revisions change. Missing facts remain visible; incomplete required chronology/lot attribution and unresolved rules block freezing, while preservable unknown account facts require explicit acknowledgement. Never invent prices/times/cash. Submit explicit review of current extracted contents only; source corrections require re-extraction and complex semantics remain server-owned. New loop submission remains ML-T24. No backend, generated contract or approval-gate change.

- **Evidence:** MV27: 27 review/page cases and 96 related frontend cases pass; all frontend 884 tests / 59 files, type checking, build, 124 preparation API/review/contract cases and both generated profiles pass. Real loopback HTTP with fake AI verifies upload, extraction, per-field confirmation, freezing and source-edit invalidation; four widths have no overflow, axe violations or browser errors. ML-C05 is complete; ML-T16 is next and API approval remains pending ML-T29.

### ML-C05. Checkpoint

- [x] Upload, progress and review UI uses generated contracts.
- [x] Record executed evidence in MV27; resolve failures before dependent work without lowering the bar.

## ML-T16. Freeze evidence through an explicit cutoff

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T05`
- **Acceptance:** Represent a partial terminal session without relabeling it complete; validate required closed intervals and this one plan's warm-up. Today/holiday/delayed data remains explicit; legacy manifest bytes/readiness stay unchanged.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_dataset.py tests/unit/test_monitor_loop_cutoff.py tests/integration/test_backtest_compatibility.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_dataset.py`, `src/trade_plan_monitor/backtest/dataset.py`, `src/trade_plan_monitor/backtest/market_store.py`, `tests/integration/test_monitor_loop_dataset.py`, `tests/unit/test_monitor_loop_cutoff.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A04, ML-A09, ML-A11, ML-A15.
- **Implementation boundary:** Add a separately versioned immutable selection and cutoff-aware day model; do not relax `FrozenSymbolDay`, historical batch validation or legacy catalog/manifest bytes. Read existing immutable calendar/minute/limit/daily revisions in one SQLite snapshot, exclude future availability and retain eligible corrections as later evidence. Derive requirements from the one reviewed snapshot, report missing closed intervals and initial warm-up, and keep a partial terminal day explicit. Opening a frozen selection reads referenced artifacts only, never mutable heads or providers. ML-T17 persists/copies the selection and its needed artifacts with the run input; no new database/table/migration or live ingestion is introduced here.
- **Evidence:** MV28: 30 task cases and 159 related regressions pass, covering lunch/close/holidays, missing minutes/limits/official close, minute corrections, complete five-minute warm-up, corrupt references, cancellation and legacy manifest/catalog compatibility. Initial minute warm-up shortages remain explicit and affected rules await sufficient completed intervals; insufficient daily warm-up rejects freezing. Mutation review detects missing constituent minutes. ML-T16 is complete; ML-T17 is next. No HTTP contract or approval change occurs.

## ML-T17. Persist frozen run references within job limits

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T07`, `ML-T11`, `ML-T16`
- **Acceptance:** Store complete reviewed inputs durably and queue only verified immutable references within 256 KiB. Copy needed artifacts before admission; retries, missing/corrupt inputs and preparation pruning cannot silently change a run.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_input_store.py tests/integration/test_backtest_jobs.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_input_store.py`, `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/jobs/models.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `tests/integration/test_monitor_loop_input_store.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A18.
- **Implementation boundary:** Persist complete reviewed source/account/plan, canonical loop input and cutoff manifest in an immutable content-addressed directory owned by the configured result store; copy each verified day before binding its reference in existing result-input tables. Keep the directory inert until explicit persistence/read, use atomic non-overwriting publication and reject damaged files. Queue a path-free reference under the unchanged 256 KiB limit; verify it before first admission through the existing single-task transaction. No new database/table/migration, provider call, retention policy or worker dispatch is introduced here; ML-T19 consumes the reference and ML-T21 handles retained/dependent artifacts.
- **Evidence:** MV29: 28 task checks and 199 related regressions pass. Complete reviewed inputs and required market evidence are durably copied; more than 256 KiB of market data queues only a small reference. Source removal, restart, repeat persistence, missing/corrupt inputs, atomic publication faults, canonical binding and single-task admission are verified. Both generated profiles stay current; dependency-verification mutation is detected. ML-T17 is complete; ML-T18 connects submission, ML-T19 worker dispatch and ML-T21 retention. API approval remains pending ML-T29.

## ML-T18. Submit a loop run with one resolved time boundary

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T16`, `ML-T17`, `ML-T33`
- **Acceptance:** Extend submission additively with reviewed preparation identity and optional end; freeze input and cutoff under the idempotency reservation. Duplicate requests after midnight reuse the original result; stale reviews and invalid ranges reject. Resolve/freeze submission through the backtest service and owned repository executor; preserve independent store ownership.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_submission.py tests/integration/test_backtest_run_api.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_runs.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `tests/integration/test_monitor_loop_submission.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A10, ML-A15, ML-A18.
- **Verification-driven correction:** A changed response under a committed public key must conflict. Compare the stored intent hash in the existing reservation transaction before returning a committed binding; keep expired-binding behavior and all admission rules. Metadata copy and reservation renewal use two inert, bounded roles of the existing owned-thread primitive; no queue or coordinator is added.
- **Implementation boundary:** Add a closed `PreparedBacktestRunCommand` variant to the existing `POST /api/v1/backtest-runs`, preserving legacy `BacktestRunCommand` bytes/fields. Require `preparationId`, exact `manifestHash`, typed `response`/`costs` and optional `endDate`; start comes from reviewed source availability/effective date. Claim the unchanged public intent before reading preparation/data and resolve submission time from its reservation. Read preparation through its independently owned service; derive only available warm-up sessions via the market store and freeze/copy through the backtest metadata executor. Replay the original receipt/reference before any new lookup. Missing preparation maps to 404, stale authority/missing market evidence to 409, invalid time/rate/range to 422 and unavailable owned services to 503. Generated contract publication remains ML-T23; worker consumption remains ML-T19, with no provider call or new admission mechanism.
- **Evidence:** MV30: 75 final task checks and 261 related regressions pass, with one pre-existing environment-conditional skip; changed-intent mutation fails as expected and exact bytes are restored. Mounted HTTP, original cutoff/midnight replay, missing evidence, stale review, exact rates, long-copy renewal, cancellation drain and single-task exclusion are verified. ML-T18/ML-C06 complete; ML-T19 is next. Contract publication/approval remain ML-T23/ML-T29.

### ML-C06. Checkpoint

- [x] Frozen cutoff input and job references survive retry and stale-review checks.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T19. Run frozen loop inputs through the background worker

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T05`, `ML-T17`, `ML-T18`, `ML-T20`, `ML-T21`, `ML-T34`
- **Acceptance:** Dispatch by input discriminator with existing lease/cancel ownership; load frozen artifacts only. No backtest CLI entry, compatibility adapter, or command-owned coordinator remains. Dispatch in the dedicated thread after lifecycle/admission gates; preserve single-slot and atomic-publication semantics.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_worker.py tests/integration/test_backtest_job_coordinator.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/loop_replay.py`, `src/trade_plan_monitor/backtest/jobs/operations.py`, `src/trade_plan_monitor/backtest/jobs/coordinator.py`, `tests/integration/test_monitor_loop_worker.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A01, ML-A09, ML-A10.
- **Implementation boundary:** New `loop_replay.py` builds availability-ordered market/calendar frames directly from owned frozen copies, driving existing `LoopRunner` in a temporary private session with streamed audit. Warm-up grants no authority; daily technical conditions stay explicitly unknown without frozen adjustment proof, never a fabricated certified series. Extend existing request discrimination/dispatch and execute on the same lifecycle/authorization-owned worker thread. After completion call existing bounded maintenance on that owned thread, honoring stop between passes. Existing `runner.py` compatibility replay stays unchanged; no command entry, queue or scheduler is added.
- **Evidence:** MV33: final task/production gate passes 46 checks with one existing environment skip; related regression passes 192. Same worker/maintenance thread, explicit authorization, copied-input independence, claim identity, single slot, cancellation drain and exact replay are verified; identity-guard mutation produces one expected failure and exact bytes are restored. ML-T19/ML-C07 complete; ML-T22 follows.

## ML-T20. Project causal events and valid valuations

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T04`, `ML-T05`
- **Acceptance:** Separate evaluated/reminded/requested/filled/resulting states and preserve causal links. Report cost-based P/L separately from interval return; unknown prices/cash and zero denominators do not fabricate metrics or liquidation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_loop_valuation.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_report.py`, `src/trade_plan_monitor/backtest/loop_runner.py`, `tests/unit/test_monitor_loop_report.py`, `tests/integration/test_monitor_loop_valuation.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01, ML-A03, ML-A09, ML-A12, ML-A13, ML-A15.
- **Implementation boundary:** Define separate `backtest-report-v4` and typed `monitor-loop-event-v1` envelopes for evaluation, captured reminder, response request, execution, resulting state and valuation. Stream a canonical ordered event digest through an optional report writer on `LoopRunner`; retain the existing attempt callback and private cycle behavior. Opening market equity uses only explicitly valid opening marks, never lot cost or a later quote. Keep cost P/L, interval return, paid fees and absolute slippage separate; unknown holdings/cash/prices and zero denominators preserve null metrics. Include original boundary and actual evidence/valuation times, without end liquidation. Report materialization/retention and worker dispatch remain ML-T21/ML-T19.
- **Evidence:** MV31: 24 focused report checks and 137 final related regressions pass; zero-denominator mutation produces one expected failure and exact bytes are restored. Full causal ancestry, risk/expiry/observation, cost versus market value, unknown/zero facts, canonical digest, identical replay, write failure and cancellation without a completed report are verified. ML-T20 completes; ML-T21 then ML-T19 follow, without changing deliverable count or acceptance.

## ML-T21. Publish and retain loop results atomically

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T17`, `ML-T20`
- **Acceptance:** Stream typed events, verify stored input/report hashes and publish only complete runs. Failure/cancel/overflow leaves no completed partial report. Retain latest 30 materialized historical runs total by publication/retention time descending and run_id tie-breaks. Existing bounded maintenance deletes oldest excess summaries/fills/details after publication; pins do not bypass the cap. Protect queued/running references, shared datasets/snapshots and retained frozen single-plan inputs. Existing exports remain byte-compatible; no new cleanup scheduler or resource-budget framework.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_publication.py tests/integration/test_monitor_loop_retention.py tests/integration/test_backtest_publication.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/loop_publication.py`, `src/trade_plan_monitor/backtest/loop_input_store.py`, `src/trade_plan_monitor/backtest/loop_account.py`, `src/trade_plan_monitor/backtest/jobs/maintenance.py`, `tests/integration/test_monitor_loop_publication.py`, `tests/integration/test_monitor_loop_retention.py`, `tests/integration/test_backtest_results.py`
- **Scope:** M, split into two slices before implementation; **Trace:** ML-A09, ML-A10.
- **Implementation slices:** ML-T21.1 covers typed staging/publication in `results.py`, `loop_publication.py`, `loop_input_store.py`, the shared pure opening-state constructor in `loop_account.py`, and its publication test (5 files). ML-T21.2 covers bounded whole-run/file retention in `results.py`, `loop_input_store.py`, `jobs/maintenance.py` and its retention test (4 files). Worker calls remain ML-T19. Existing canonical storage envelopes stay version-compatible; explicit `backtest-report-v4`/`monitor-loop-event-v1` payloads identify new semantics. Store large report headers as immutable result-owned files under existing object bounds, retaining the 32 KiB row limit. Use the existing decision artifact family for the ordered typed audit and the existing fill ledger for committed receipts; verify input/report bindings, every audit/fill and stage revision before the existing token-fenced publication. Reuse the existing caller-budgeted maintenance transaction and ownership tag for safe bounded file cleanup, with no scheduler, database or queue added.
- **Compatibility verification boundary:** ML-T21.2 also updates the obsolete retention-count assertions in existing `tests/integration/test_backtest_results.py` to the latest-30 total policy (5 primary files total). Keep age, batch budget, shared input and export regression assertions; do not weaken checks.
- **Evidence:** MV32: 22 final task checks and 118 related regressions pass; latest-30 mutation produces one expected failure and exact bytes are restored. Token-atomic publication, partial/cancel/corruption refusal, fill/audit bindings, total/time/tie ordering, pins within the cap, bounded owned-file cleanup and unfinished reservation/task protection are verified. ML-T19 follows with worker consumption and the existing post-completion maintenance call.

### ML-C07. Checkpoint

- [x] Worker publishes only complete retained results.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T22. Expose paginated loop results; retain export compatibility

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T21`
- **Acceptance:** Result/detail paths expose typed loop events, frozen plan provenance and cutoff coverage with stable paging/schema identification. Preserve old summaries and supported-mode CSV/JSON bytes. No new loop export format/route/UI/jobs/mutex. Heavy projection uses owned threads and bounded paging; backpressure affects backtest admission only.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_result_api.py tests/integration/test_backtest_exports.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_runs.py`, `tests/integration/test_monitor_loop_result_api.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A10, ML-A15.
- **Implementation boundary:** Extend the existing result-row decoder and existing run response union, alongside owned-thread projection, typed bounded result schemas and focused HTTP tests. Keep existing routes/cursors/export formats and legacy bytes; no scheduler, queue, lock or approval update.
- **Evidence:** MV34: 12 loop-result checks; final task/export/production gate passes 44 with one existing environment skip, and related regression passes 189. Paging, native causal hashes, frozen provenance/cutoff, unknown/zero values, expired details, pinning and thread backpressure are verified; identity-guard mutation produces one expected failure and exact bytes are restored. Legacy exports remain compatible; loop exports reject before streaming. ML-T23 follows; approval remains pending ML-T29.

## ML-T23. Generate final run and result contracts

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T18`, `ML-T22`
- **Acceptance:** Regenerate after the actual run/result API change and verify discriminated old/new payloads, bounds and safe numbers. Keep the approved-digest review pending ML-T29; do not silence baseline approval failures.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **Primary files:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_monitor_loop_contract.py`, `scripts/generate_frontend_types.py`, `web/src/components/backtests/BacktestDetailTable.vue`, `web/src/components/backtests/BacktestFillTable.vue`, `web/src/components/backtests/BacktestRunTable.vue`, `web/tests/unit/backtestsApi.spec.ts`
- **Scope:** M (10 primary files; three implementation slices); **Trace:** ML-A09, ML-A10.
- **Implementation slices:** ML-T23.1 fixes discriminator-aware generation with focused contract tests (2 files); ML-T23.2 generates both existing profiles (4 files); ML-T23.3 makes existing tables and their API fixture handle the new variants honestly (4 files). No complete loop timeline, new route/export, lifecycle or approval change; ML-T25 owns the full result experience.
- **Evidence:** MV35: both actual run/result profiles are generated and current. 11 focused, 50 related contract and 114 frontend checks pass; frontend type-check passes. Discriminator generation mutation produces one expected failure and exact bytes are restored. Both existing approval gates independently remain unapproved; no digest or path allowance changes. ML-T24 follows; final approval remains ML-T29.

## ML-T24. Submit one prepared plan from the existing run form

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T15`, `ML-T23`
- **Acceptance:** Use one reviewed snapshot and its extracted opening account without raw operations JSON. End defaults server-side. Show resolved cutoff, missing facts and unsupported clauses, then existing job/result navigation. No multi-plan selectors.
- **Verification:** `npm --prefix web run test -- --run tests/unit/MonitorLoopRunForm.spec.ts`
- **Primary files:** `web/src/components/backtests/BacktestRunForm.vue`, `web/src/composables/useBacktestRunForm.ts`, `web/src/api/backtests.ts`, `web/src/views/BacktestNewView.vue`, `web/tests/unit/MonitorLoopRunForm.spec.ts`, `web/tests/unit/BacktestNewView.spec.ts`, `web/tests/unit/BacktestAccessibility.spec.ts`
- **Scope:** M (7 primary files; two implementation slices); **Trace:** ML-A10, ML-A12, ML-A14, ML-A15.
- **Fixture compatibility:** Type-check requires the existing accessibility draft fixture to include the new fields. Update its values only; retain every existing accessibility assertion.
- **Implementation slices:** ML-T24.1 extends the existing API/composable and focused tests (3 files); ML-T24.2 connects the existing form/page and updates the obsolete unknown-outcome replacement assertion (4 files including shared tests). A pending submission freezes source/run controls and preserves its exact retry identity. The form explains server end resolution; the existing verified result boundary supplies the exact cutoff after completion, with its full presentation in ML-T25. Preserve unrelated page-caption edits when committing.
- **Evidence:** MV36: 11 prepared submission checks and 195 frontend regressions in total pass; type-check passes. Removing the unknown-outcome edit guard produces one expected failure; exact bytes restored. One frozen plan/account, server-default end, exact retry, preparation exclusion and existing navigation are verified; unrelated caption edits preserved. ML-C08 completes; ML-T25 follows, final approval remains ML-T29.

### ML-C08. Checkpoint

- [x] Result APIs and run creation work with old/new contracts; existing exports remain compatible without new development.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T25. Explain plan and execution history in results

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T22`, `ML-T23`
- **Acceptance:** Connect paginated causal events and frozen single-plan provenance to the result page; distinguish holds, blocked/unfilled intents and fills. Show account evolution, valid metrics and actual cutoff without client trading logic or version-switch timeline.
- **Verification:** `npm --prefix web run test -- --run tests/unit/MonitorLoopResults.spec.ts`
- **Primary files:** `web/src/components/backtests/MonitorLoopTimeline.vue`, `web/src/components/backtests/MonitorLoopSummary.vue`, `web/src/views/BacktestRunDetailView.vue`, `web/src/composables/useBacktestResults.ts`, `web/src/api/backtests.ts`, `web/src/api/monitorLoopValues.ts`, `web/src/components/backtests/BacktestResultActions.vue`, `web/tests/unit/MonitorLoopResults.spec.ts`, `web/tests/fixtures/monitor-loop-results.json`, `web/tests/unit/backtestsApi.spec.ts`
- **Scope:** M (10 primary files; three implementation slices); **Trace:** ML-A01, ML-A10, ML-A13, ML-A15.
- **Fixture compatibility:** Narrow one existing legacy API assertion before accessing its legacy-only assumptions; retain the assertion and all old behavior checks.
- **Implementation slices:** ML-T25.1 validates the existing native HTTP variants using actual backend fixture responses (API/validator/fixture/tests, 4 files); ML-T25.2 adds readonly summary/timeline presentation to the existing page (components/page/tests, 4 files); ML-T25.3 extends the existing result composable and pin actions, hiding unsupported native exports (3 files including shared tests). Preserve unrelated page-caption edits. No new route, export, replay, trading calculation or plan-switch support.
- **Evidence:** MV37: 17 native-result checks and 157 frontend checks in total pass; type-check passes. Real Chrome verifies 1440/390 pixels, 32 causal events and 2 selected-resource requests with no runtime error or horizontal overflow. Input/provenance binding mutation produces one expected failure; exact bytes restored. Actual HTTP fixtures, pagination, pinning, expiration and unknown/zero rendering are verified; unrelated caption edits preserved. ML-T26 follows; final approval remains ML-T29.

## ML-T26. Prove parity, causality and failure atomicity

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T05`, `ML-T11`, `ML-T16`, `ML-T21`, `ML-T34`
- **Acceptance:** Compare online application participants with loop state using independent expected outputs; mutate future evidence and inject transaction/worker faults. Include one deliberate invariant mutation check; fake AI/provider/sink counters prove isolation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_parity.py tests/integration/test_monitor_loop_faults.py tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **Primary files:** `tests/integration/test_monitor_loop_parity.py`, `tests/integration/test_monitor_loop_faults.py`, `tests/fixtures/monitor-loop/scenarios.json`, `tests/integration/test_plan_preparation_worker.py`, `src/trade_plan_monitor/backtest/loop_report.py`, `web/tests/fixtures/monitor-loop-results.json`
- **Scope:** M (6 primary files; two implementation slices); **Trace:** ML-A01–ML-A24 excluding cancelled ML-A07.
- **Implementation slices:** ML-T26.1 adds independent online/expected-value and future-evidence checks plus a minimal causal event identity correction if proven necessary (3 files). ML-T26.2 covers transaction/worker/preparation faults and refreshes the real HTTP fixture after any identity correction (3 files). The full stream digest and separate run binding must still detect cross-run substitution; no new schema fields, scheduler or execution policy.
- **Evidence:** MV38: 89 backend checks pass, including independent 15-evaluation online parity, two literal expected fills and account/publication/worker/preparation faults. Causal identity mutation fails as expected; exact bytes restored. Actual HTTP fixture refreshed. ML-T35 follows; final approval remains ML-T29.


## ML-T27. Verify the complete browser journey

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T24`, `ML-T25`, `ML-T26`, `ML-T36`
- **Acceptance:** Use real mounted API/composition with fake external services for upload → retry/edit → review → run → results. Prove the fixture supplies no future trade script and tests neither mocked result-only screens nor live user databases. Include service-down/unknown-cancel/recovery navigation while monitor pages remain usable.
- **Verification:** `npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts`; `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_production_composition.py -q -m "not live"`
- **Primary files:** `web/tests/e2e/monitor-loop-backtest.spec.ts`, `web/tests/fixtures/monitor-loop.json`, `tests/integration/test_monitor_loop_production_composition.py`, `web/src/router.ts`, `web/src/views/BacktestNewView.vue`, `src/trade_plan_monitor/web/preparation_schemas.py`, `web/tests/fixtures/plan-preparation-review.json`
- **Scope:** M (7 primary files; verified navigation and frozen identity corrections); **Trace:** ML-A10, ML-A16, ML-A18.

- **Verification-driven correction:** Real browser testing proves accepted source creation leaves no preparation identity in the URL, losing the target on reload/return. Add only accepted-record URL identity and initial route loading; preserve shared caption edits.

Frozen identity correction: The browser proves the FROZEN progress projection publishes the storage candidate digest instead of the authoritative prepared manifest digest used by run submission. Project the existing candidateHash from the validated frozen manifest, preserve extraction/storage bindings, and refresh the typed fixture. No API field/path or schema change.

### ML-C09. Checkpoint

- [x] Independent fault/parity and full browser journey pass.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.
- **Evidence:** MV42: Two real Chrome journeys, 75 backend checks, 96 frontend checks and type checking pass. The browser found and verified narrow navigation and authoritative frozen identity corrections. Removing the frozen identity projection produces one expected failure; exact bytes restored. C09 passes; ML-T37 follows.


## ML-T28. Record operation guidance and executed evidence

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T27`, `ML-T37`
- **Acceptance:** Document actual supported API/UI behavior and source limitations in both languages. Execute the plan's relevant final gates and record exact results, unresolved failures and evidence scope; never claim live AI/provider certification.
- **Verification:** `git diff --check`
- **Primary files:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`, `web/tests/e2e/backtests.spec.ts`
- **Scope:** M (5 primary files; operation evidence and verified legacy browser-fixture correction); **Trace:** ML-A01–ML-A24 excluding cancelled ML-A07.

Final-check correction: The full real Chrome suite exposes an outdated legacy browser fixture returning 500 for the new inert service-status read. Extend only the explicit fixture contract; keep all error/request/zoom/overflow assertions intact and preserve unrelated UI changes.
- **Evidence:** MV44: Paired operations cover the implemented single-plan source/review/run/result workflow, exact account/cutoff semantics, single unfinished task, cancellation/unknown recovery, export compatibility and measured-load limits. Final relevant checks pass: 58 backend, 935 frontend, type checking, build, 34 real Chrome journeys, Ruff and both generated profiles. Two unchanged exact API approval gates remain pending ML-T29; their actual failures are retained. ML-T28 completes; ML-T38 follows.


## ML-T29. Align reviewed specifications and API approval

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T23`, `ML-T28`, `ML-T38`, `ML-T39`
- **Acceptance:** Review the final API/behavior diff with its bilingual contract; record only the resulting approved snapshot identity and final implementation scope. Preserve old approval history and explicitly distinguish the previously known baseline mismatch.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m "not live"`
- **Primary files:** `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.md`, `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md`, `docs/specifications/monitoring/SPEC-unified-plan.md`, `docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md`, `tests/integration/test_openapi_snapshot.py`
- **Scope:** M (5 primary files; reviewed specifications and exact approved-path allowlist); **Trace:** ML-A09, ML-A10.

### ML-C10. Checkpoint

- [x] Active ML-A01–ML-A24 evidence (excluding cancelled ML-A07) and reviewed bilingual contracts are complete.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.
- **Evidence:** MV46: Final review retains all 52 original paths, approves exactly 10 additions and the documented additive native branches, preserving historical identities. Both reviewed snapshots/types match committed source. The exact allowlist, bilingual approval, public-error and generated TypeScript gates pass: 51 integration plus 18 service-value checks. Removing one approved path fails; exact bytes restored and the gate passes. C10 completes; all 37 active tasks and the user-requested 20-task sequence are complete.


## ML-T30. Freeze on-demand lifecycle and capability contracts

- [x] Complete implementation and task verification.
- **Dependencies:** None
- **Acceptance:** Define NOT_INITIALIZED/READ_READY versus execution readiness, inert startup/status, single-flight gates, per-session authorized job IDs and physical drain. Preserve identities/atomic publication; no background warm-up or approval stamping.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_backtest_service_contract.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/service_contract.py`, `src/trade_plan_monitor/backtest/service_config.py`, `tests/unit/test_backtest_service_contract.py`
- **Scope:** M (3 primary files including tests); **Trace:** ML-A19, ML-A22, ML-A24.

## ML-T31. Remove backtest preparation from application startup

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T30`
- **Acceptance:** Application startup/shutdown/status/OpenAPI/monitor navigation invokes no backtest factory/start/store/key/executor/provider and schedules no warm-up. Deliberately unusable backtest-only configuration does not block a healthy monitor/Web startup. Cleanup only acquired resources; first-use failure remains scoped.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_startup_isolation.py tests/integration/test_backtest_production_composition.py tests/integration/test_monitor_production_composition.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/web/lifespan.py`, `src/trade_plan_monitor/web/app.py`, `src/trade_plan_monitor/backtest/composition.py`, `tests/integration/test_backtest_startup_isolation.py`, `tests/integration/test_backtest_production_composition.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A19, ML-A20.

## ML-T32. Initialize bounded backtest capabilities once on demand

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T31`
- **Acceptance:** A guarded single-flight manager handles concurrent first use, lazy executors, waiter cancellation and generation fences. Split metadata READ_READY from execution READY; reads/status never activate the coordinator. Return truthful initializing/unavailable responses and retain resource ownership until physical drain.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_ownership.py tests/integration/test_backtest_production_composition.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/thread_lifecycle.py`, `src/trade_plan_monitor/backtest/thread_ownership.py`, `src/trade_plan_monitor/backtest/service_lifecycle.py`, `src/trade_plan_monitor/web/app.py`, `tests/integration/test_backtest_thread_ownership.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A19, ML-A20, ML-A22.
- **Executed connection changes:** `web/lifespan.py` imports the manager; `backtest/composition.py` owns the metadata adapter. The narrow 503 `Retry-After` extension in `web/errors.py` and its response test were explicitly authorized by the user. See verification for evidence.

### ML-C11. Checkpoint

- [x] Inert startup/status/shutdown, single-flight first use and read/execution separation pass.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T33. Gate job recovery and cancellation by explicit use

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T32`
- **Acceptance:** Restart leaves backlog dormant. Reads and readiness do not claim/recover/execute jobs; current-session new-job and explicitly selected resume IDs gate coordination. Preserve cancel/complete/lease fences, 30-second leases/3 claim generations and drain-before-replacement. No blind paid retry or failed/cancelled requeue.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_thread_recovery.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/service_lifecycle.py`, `src/trade_plan_monitor/backtest/jobs/coordinator.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `src/trade_plan_monitor/backtest/composition.py`, `tests/integration/test_backtest_thread_recovery.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A20, ML-A21.
- **Progress:** Latest user correction on 2026-10-07 supersedes expiry-based slot release: unfinished QUEUED/RUNNING/CANCEL_REQUESTED jobs retain admission until terminal, even with expired/unknown leases. Explicit recovery authorizes one existing job after physical drain; it never authorizes a second new task. Existing 30-second lease/3-generation, stale-token, cancellation/publication/idempotency guards remain. No new status/schema migration. Evidence: MV18, ADR 0009; MV12 is historical.

## ML-T34. Preserve existing limits and pace historical sync

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T33`
- **Acceptance:** Preserve and regress existing finite queues/input/event limits, single execution, bounded threads/paging and storage-domain guards. Add no dynamic memory/CPU sampling controller, pressure threshold or pressure-triggered admission/cancellation. Historical sync stays single-active and gains only local fixed request-start spacing, initially 1.25 seconds using the existing pacing value. Preserve existing request timeouts/error mapping and cancellation during waits; no new retry policy. Monitor request control is unchanged. No global quota pool, live-capacity reservation, cross-business scheduling, shared cooldown, account/interface registry, adaptive allocation or quota UI. Low-frequency AI extraction retains existing one-source extraction guards and does not block this task. Stream records and cooperatively cancel; no hard per-thread CPU/memory guarantee. Replay constructs no live provider/sink.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_sync_pacing.py tests/integration/test_backtest_results.py tests/integration/test_backtest_thread_ownership.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/sync.py`, `tests/integration/test_backtest_sync_pacing.py`
- **Scope:** S (2 primary files including tests); **Trace:** ML-A20, ML-A22, ML-A23.
- **Scope decision:** On 2026-10-07 the user requested minimal scope. The former live-capacity reservation item is replaced by local sync pacing in `backtest/sync.py` with fake spacing/cancellation tests. Remove the planned generic `backtest/capability_admission.py` module and provider-admission test; no new connections in `web/ai_service.py`, `runtime/request_control.py` or `backtest/application.py` are required for this item. Quota certification or shared-budget decisions no longer gate it. Storage protection retains existing independent defaults, path normalization and live-table/mixed-domain guards only; no new deep file identity or cross-file alias framework. Disk/log budgets and free-space admission thresholds are cancelled. The latest-30 historical-run retention policy belongs to ML-T21 and does not gate isolation. Cancel the planned `backtest/resource_control.py` and generic `test_backtest_resource_boundaries.py`; existing guards need regression only. Local sync pacing and existing guard regression pass, with the ML-T33 dependency completed; executed evidence is in MV12. Latest user correction requires one unfinished task and excludes new mutually exclusive preparation/sync/verify/replay before termination. Enforce existing transaction admission and preparation revision/freeze protections; no new generic lock, queue or scheduling layer. Implemented task admission evidence: MV18; preparation entry remains pending.

### ML-C12. Checkpoint

- [x] Drain-aware recovery/cancellation, existing guard regression and local sync pacing pass.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T35. Expose lazy service status and explicit recovery API

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T12`, `ML-T23`, `ML-T33`, `ML-T34`
- **Acceptance:** Status/stop are inert when unused; first actual data/operation request activates needed capabilities after guards/validation. Recovery explicitly retries preparation or selected resumeJobIds (<=1) with epoch/revision/idempotency. Scoped 503/Retry-After means no job admitted; initialization polling cannot restart failed preparation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_service_api.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/web/routers/backtest_service.py`, `src/trade_plan_monitor/web/backtest_service_schemas.py`, `src/trade_plan_monitor/web/app.py`, `src/trade_plan_monitor/backtest/service_lifecycle.py`, `tests/integration/test_backtest_service_api.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A19, ML-A21, ML-A24.
- **Evidence:** MV39: 77 checks pass with one existing environment skip. Epoch/revision/idempotency, one selected resume, cached first-use failure, physical-drain repair, inert status/stop and bounded 1000-receipt history pass. Removing the epoch fence produces one expected failure; exact bytes restored. ML-T39 follows.


## ML-T39. Generate independent service transport contracts

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T35`
- **Acceptance:** Generate mounted service resources and typed capabilities/errors in both contract profiles. Check that monitor endpoints and unaffected payloads retain their prior meaning; preserve the stale approval record for explicit final review. No handwritten duplicate transport models.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_service_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **Primary files:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_backtest_service_contract.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A19, ML-A24.
- **Evidence:** MV40: 37 contract checks and frontend type checking pass; both generated profiles are current. The two existing approval gates remain pending ML-T29 with snapshot dde2866b81a9710a51bf7817eeeb30513cfb4e844437adba7a2ef202fd52caa0. Expanding resume bounds produces two expected failures; exact bytes restored. ML-T36 follows.


## ML-T36. Show first-use preparation and scoped recovery in Web

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T39`
- **Acceptance:** Only active backtest data requests trigger lazy preparation; route prefetch/global status polling stays inert. Show unused/initializing/read-ready/execution-ready/failure distinctly, preserve forms across 503 and reuse mutation keys. Opening history never resumes jobs/AI; explicit retry/resume shows selected backlog and monitoring stays usable.
- **Verification:** `npm --prefix web run test -- --run tests/unit/BacktestServiceState.spec.ts`; `npm --prefix web run type-check`
- **Primary files:** `web/src/api/backtestService.ts`, `web/src/composables/useBacktestService.ts`, `web/src/components/backtests/BacktestServiceState.vue`, `web/src/layouts/AppShell.vue`, `web/src/composables/useBacktestRunForm.ts`, `web/tests/unit/BacktestServiceState.spec.ts`
- **Scope:** M (6 primary files; two slices); **Trace:** ML-A21, ML-A24.

- **Implementation slices:** First deliver independent API/composable/state component and focused tests, then integrate the shared layout on active backtest routes and retain existing submission intent across 503. No service control on prefetch or monitoring routes.
- **Evidence:** MV41: All 935 frontend checks, type checking and production build pass. Real Chrome verifies readonly history and one explicitly confirmed resume at 1440/390/320 pixels, with no runtime error or overflow. Removing 503 intent retention produces one expected failure; exact bytes restored. ML-T27 follows.


## ML-T37. Verify Windows lazy activation and thread boundaries

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T26`, `ML-T27`, `ML-T34`, `ML-T36`
- **Acceptance:** Prove zero backtest work across app startup/monitor navigation/status/prefetch/shutdown, concurrent first-use single initialization, read-only history without backlog execution and explicit selected resume. Inject first-use errors/late futures/cancel races with controllable fixtures; retain ML17 10-stock load gates and accepted thread limits.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_isolation_fault_matrix.py tests/integration/test_monitor_loop_parity.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/verify_backtest_thread_load.py --profile windows-threads --offline`
- **Primary files:** `tests/integration/test_backtest_isolation_fault_matrix.py`, `tests/fixtures/monitor-loop/isolation.json`, `scripts/verify_backtest_thread_load.py`, `tests/integration/test_backtest_sync_pacing.py`, `src/trade_plan_monitor/backtest/loop_publication.py`, `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/backtest/results.py`, `tests/integration/test_monitor_loop_publication.py`, `src/trade_plan_monitor/state/daily_accounting.py`, `tests/unit/test_daily_safety_boundaries.py`, `src/trade_plan_monitor/runtime/daily_service.py`
- **Scope:** M (11 primary files; verified publication, busy retry and transaction-local legacy-scan correction); **Trace:** ML-A08, ML-A19–ML-A24.

Verification-driven correction: Real admitted load proves sequential native runs with differing response delays collide on a global receipt fill key. Bind only the internal stored fill key to run_id, preserve public receipt identifiers, and strictly verify/replay existing legacy rows. No schema/API path or authority/event identity change.


Load-fixture correction: The initial 600/600-second unpaced replay stress exceeded the fixed monitoring cadence near phase end. Retain that failure, all original time/latency/completeness gates and the exact real monitoring workload; pace only the offline replay admissions to at least 120 seconds between starts, as ML17 permits reducing admitted load. Record phase counts and elapsed time before final assertions so a failed gate retains actual measurements. No production monitor or resource controller change.


Further measured-load correction: The 5-second fixture completed all evaluations but exposed >=30-input maintenance contention, a raw SQLite busy exception and a 7340.370 ms scheduling p99. Preserve that failed report and strict cleanup validation. Translate only actual SQLITE_BUSY/SQLITE_LOCKED metadata-call errors into the existing 503/Retry-After response, retaining original-intent retry and propagating other SQL faults. The offline accepted profile admits at most five native experiments per ten minutes (>=120 seconds between starts); all original monitor cadence/latency/completeness gates remain. No production pacing, new lock or generic resource system.


Measured monitor correction: Even five-per-ten-minute replay fails as history grows. A controlled ten-stock cycle profiles 0.964 seconds, with legacy_reason taking 0.631 seconds / 24,390 JSON loads across two scans per stock; the write lock takes only 0.119 seconds and stays unchanged. Filter only EVALUATION compatibility candidates using existing SQLite JSON support, retain the original Python predicate and malformed/non-object error semantics, and add bounded-decoding/legacy-tail/corruption safety cases. No cache, schema, monitor rule, task framework or quality-threshold change.

Transaction-local scan correction: Profiling actual accumulated history proves duplicate historical JSON scanning dominates evaluation cost. SQL filters only current EVALUATION rows without old order markers, preserving malformed/non-object/duplicate-key Python checks; reuse one legacy decision within the same transaction. No persistent cache, historical rewrite or monitor rule change. The admission script explicitly obeys the nominal phase deadline; post-phase drain cannot start another experiment.
- **Evidence:** MV43: Windows 600/600-second ten-stock load passes with 5 completed sequential native runs, 12000 exact evaluations and no duplicated/missing semantic reminders. The final 209-case affected regression and 131 shared runtime/accounting checks pass with one existing environment skip; Ruff passes. Public fill identities remain stable with run-bound internal storage; legacy exact retry passes. Initial unpaced failure is retained; all original gates remain. ML-T37 completes; ML-T28 follows.


## ML-T38. Record on-demand thread operation guidance

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T37`
- **Acceptance:** Paired guidance explains dormant startup, first-use preparation, metadata versus execution, explicit backlog resume, scoped repair and drain-aware stop. Document shared-process risks without mandatory process upgrade; preserve identities and the historical baseline approval mismatch with its reviewed correction.
- **Verification:** `git diff --check`
- **Primary files:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A19–ML-A24.

### ML-C13. Checkpoint

- [x] Service API/UI and recorded Windows thread fault/load acceptance pass; ML-C10 remains the final combined gate.
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar.
- **Evidence:** MV45: Paired guidance records dormant startup, explicit metadata/execution authority, one selected resume, scoped repair, accepted controls versus physical drain, boot/revision/idempotency fences and accepted shared-process limits. Actual MV43 load and MV44 final/browser evidence are referenced without rerunning or broadening them. C13 completes; only ML-T29/C10 final reviewed approval remains.


---

The following original completed historical record is preserved; it does not imply completion of the current implementation.

# Task List: market-index-context

> Canonical English task list. The Chinese review copy is `todo.zh-CN.md`; IDs, files, commands, and acceptance criteria stay aligned.

> Status: IDX001–IDX012 and WEBF13 complete. This table records historical acceptance scope; its42-path count and commands are not the current complete contract. See the [documentation index](../docs/README.md) for current daily and runtime contracts.

## Foundation

- [x] `IDX001` — Implement closed board-index identity mapping.
  - Acceptance: five mappings and all invalid/fallback cases are deterministic; bindings are immutable and recomputable.
  - Verify: `python -m pytest tests/unit/test_market_index_identity.py -q`.
  - Files: `tests/unit/test_market_index_identity.py`, `src/trade_plan_monitor/market_index/identity.py`, `src/trade_plan_monitor/market_index/__init__.py`.
- [x] `IDX002` — Implement index bars, canonical hashes, formulas, and health.
  - Acceptance: exact completed-bar validation, SMA/lookback/return goldens, issue codes, and content hashes match specs.
  - Verify: `python -m pytest tests/unit/test_market_index_data.py -q`.
  - Files: `tests/unit/test_market_index_data.py`, `market_index/models.py`, `market_index/canonical.py`, `market_index/formulas.py`.
- [x] `IDX003` — Implement provider boundary and shared cutoff snapshot coordinator.
  - Acceptance: unioned requests fetch once; concurrent equal keys share; board failures isolate; no provider secret leaks.
  - Verify: `python -m pytest tests/integration/test_market_index_snapshots.py -q`.
  - Files: `tests/integration/test_market_index_snapshots.py`, `market_index/provider.py`, `market_index/requirements.py`, `market_index/snapshots.py`.

## Plan Evaluation

- [x] `IDX004` — Add explicit Schema v2 binding and six condition models.
  - Acceptance: v1 rejects new fields/leaves without hash drift; v2 requires a recomputed binding and exact bounds.
  - Verify: `python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_plan_domain.py -q`.
  - Files: `tests/unit/test_plan_index_conditions.py`, `domain/plan_models.py`, `domain/plan_validation.py`, `domain/plan_codec.py`.
- [x] `IDX005` — Evaluate index leaves with exact plan paths and missing evidence.
  - Acceptance: equality, all roots, three-valued composition, two-plan divergence, and no-condition behavior pass.
  - Verify: `python -m pytest tests/unit/test_plan_index_conditions.py tests/unit/test_decision_engine.py tests/replay/test_decision_replay.py -q`.
  - Files: `decision/models.py`, `decision/conditions.py`, `decision/episodes.py`, `decision/risk.py`, `tests/unit/test_plan_index_conditions.py`.

## Monitoring

- [x] `IDX006` — Inject shared snapshots into live evaluation and keep latest shared/plan projections separate.
  - Acceptance: one snapshot per cutoff/index, no-condition failure isolation, and runtime evidence persistence pass.
  - Verify: `python -m pytest tests/integration/test_market_index_runtime.py tests/integration/test_ten_symbol_runtime.py -q`.
  - Files: `tests/integration/test_market_index_runtime.py`, `runtime/service.py`, `runtime/symbol_service.py`, `web/lifespan.py`.
- [x] `IDX007` — Add monitoring API, history endpoint, invalidation, OpenAPI, and generated types.
  - Acceptance: bounded safe schemas/endpoints/events and nullable migration fields pass contract tests.
  - Verify: `python -m pytest tests/integration/test_market_index_web.py tests/integration/test_openapi_snapshot.py tests/integration/test_websocket.py -q`; `python scripts/generate_frontend_types.py --check`.
  - Files: `web/schemas.py`, `web/routers/market_indexes.py`, `web/app.py`, `web/websocket.py`, generated contracts/tests.
- [x] `IDX008` — Add monitoring Vue components and series composable test-first.
  - Acceptance: shared data and plan outcomes are visually separate; loading/failure/not-used/keyboard/responsive states pass.
  - Verify: `npm --prefix web run type-check`; `npm --prefix web run test -- --run`.
  - Files: `web/src/components/market-index/*`, `web/src/composables/useMarketIndexSeries.ts`, dashboard/detail views, unit tests.

## Backtesting

- [x] `IDX009` — Add v2 index artifacts, dynamic coverage/warm-up, shared replay snapshots, and v3 run identity.
  - Acceptance: no lookahead, live/replay byte parity, old goldens unchanged, no-condition coverage isolation, zero network.
  - Verify: `python -m pytest tests/unit/test_backtest_index_data.py tests/integration/test_backtest_index_dataset.py tests/integration/test_backtest_runner.py -q`.
  - Files: `backtest/index_data.py`, `backtest/dataset.py`, `backtest/market_store.py`, `backtest/runner.py`, tests.
- [x] `IDX010` — Persist/project backtest index evidence, add series API, and version formal export.
  - Acceptance: nullable old runs, exact identities/counts, 512-point bound, retained details, and stable export pass.
  - Verify: `python -m pytest tests/integration/test_backtest_index_api.py tests/integration/test_backtest_export_api.py -q`; OpenAPI check.
  - Files: `backtest/results.py`, `web/backtest_schemas.py`, `web/routers/backtest_results.py`, `web/backtest_export.py`, tests/generated contracts.
- [x] `IDX011` — Add backtest index form/summary/tab components test-first.
  - Acceptance: backend coverage is read-only, summaries/path identities match, all availability states and accessibility pass.
  - Verify: `npm --prefix web run type-check`; `npm --prefix web run test -- --run`; targeted Playwright.
  - Files: backtest index components/composable, new/detail views, API adapter, unit/e2e tests.

## Completion

- [x] `IDX012` — Finish paired README/API/test report and run all offline gates.
  - Acceptance: bilingual parity, documented provider limitation, complete file/test/risk report, clean secret scan, all required gates green.
  - Verify: full commands in [project README](../README.md), `git diff --check`, `git status --short`.
  - Files: `README.md`, `README.zh-CN.md`, `docs/README*`, paired verification report, `openapi.json`, generated TypeScript.

## WEBF13 Route and Journey Closure

- [x] `WEBF13` — Prove the real production-route/new-backtest journey boundary and record offline acceptance evidence without changing the frozen contract.
  - Acceptance: paired specifications identify the former placeholder routes `/`, `/stocks/:symbol`, `/plans/:id`, `/alerts`, and `/system` as real lazy SFCs; the exact 10-route map and `submit → run+job URL → poll → remove jobId → materialized result` chain have unit, browser, and backend-fake evidence; OpenAPI remains exactly 42 paths (27 live plus 15 backtest); the paired report is `PASS`.
  - Verify: focused backend pytest plus the production-fake journey; Ruff; OpenAPI snapshot and generated-TypeScript consistency; full Vitest, `vue-tsc`, build, and Chromium suites; `git diff --check`.
  - Files: `README*`, `docs/README*`, paired local-Web/backtest/API/ADR specifications, `tasks/plan*`, `tasks/todo*`, `docs/verification/webf13-acceptance*`, `web/tests/unit/BacktestRouter.spec.ts`, `web/tests/e2e/backtests.spec.ts`, and `web/tests/e2e/accessibility.spec.ts`.
