# Active Task List: Monitoring-loop Backtest

> Implementation authorized, updated 2026-10-08. Plan: [plan.md](plan.md); Chinese copy: [todo.zh-CN.md](todo.zh-CN.md). ML-T01–ML-T05, ML-T07/ML-T08/ML-T10/ML-T11, ML-T30–ML-T34, ML-C01/ML-C02/ML-C03 and ML-C12 are implemented and verified; other tasks remain pending. Evidence: [verification](../docs/verification/monitor-loop-backtest.md). Previously completed historical tasks are retained below.
> Scope correction 2026-10-07; progress 2026-10-08: ML-T06/ML-T09 are cancelled; 14 completed, 23 pending active tasks, 37 active / 39 retained IDs, 13 checkpoints. ML-A07 is not a gate. One frozen plan and one unfinished task; evidence MV17–MV23.

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
- [x] Record executed evidence; resolve failures before dependent work without lowering the bar. MV20/MV21 record the private persistence/extraction gate; ML-T10 passes MV22, ML-T11 passes MV23, and ML-T12 is next.

## ML-T10. Resume single-source extraction safely

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T07`, `ML-T08`, `ML-T34`
- **Acceptance:** Claim the one source with generation/source/revision fences and persist progress outside calls. Reuse existing guards and bounded retryable attempts; edit/cancel/restart rejects stale completion. Use owned backtest threads. Unknown paid outcomes require explicit recovery; no new global AI budget gates isolation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/preparation_models.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_worker.py`, `src/trade_plan_monitor/web/ai_service.py`, `tests/integration/test_plan_preparation_worker.py`
- **Scope:** Two M increments, 4 primary files each (7 unique including the shared test); **Trace:** ML-A16, ML-A18. First persist worker ownership/progress and read the existing admission reservation for recovery; then connect owned calls and configured AI. No new job kind, queue, database or public route.
- **Evidence:** MV22: 29 worker cases and the 3000-case final regression pass. Owned calls retain existing global admission through physical drain; unknown paid outcomes require explicit ended confirmation. Reads/replayed receipts never dispatch, and known retries remain within three durable attempts. Semantic review/freeze and public preparation integration remain ML-T11/ML-T12.

## ML-T11. Review and freeze one complete prepared plan

- [x] Complete implementation and task verification.
- **Dependencies:** `ML-T08`, `ML-T10`
- **Acceptance:** Bind explicit review to exact source/content/account/evidence revisions and freeze one immutable manifest. Source corrections invalidate its candidate/review; submitted runs remain frozen. Validation cannot create approval or activate production plans.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_review.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/preparation_review.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_review.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A17, ML-A18.
- **Evidence:** MV23: 51 review cases pass. Exact revision/source/plan/account/evidence bindings, atomic manifest/declaration, original receipt replay and physical admission retention are verified. Unknown opening facts remain explicit; forged AI/legacy review flags and future opening marks cannot grant authority. Public preparation integration remains ML-T12; ML-C04 remains pending.

## ML-T12. Expose the preparation application path

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T10`, `ML-T11`, `ML-T33`
- **Acceptance:** Connect exactly-one-source create/read/edit/extract/cancel/review operations to on-demand capability ownership and acquired-resource shutdown. HTTP tests prove second-source rejection, revisions, idempotency, bounded projections and fake-AI progress without live-plan mutations. Guard readiness; preparation-store failure degrades backtest only.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_api.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/web/preparation_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_preparations.py`, `src/trade_plan_monitor/web/app.py`, `src/trade_plan_monitor/backtest/composition.py`, `tests/integration/test_plan_preparation_api.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A10, ML-A16, ML-A18.

### ML-C04. Checkpoint

- [ ] Restart/cancel/edit/review works through real HTTP with fake AI.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T13. Generate preparation transport contracts

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T12`
- **Acceptance:** Generate contracts from mounted production routes and test the new discriminated payloads and error shapes. Preserve unaffected routes/types; document API changes for ML-T29 approval rather than stamping a digest early.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **Primary files:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_plan_preparation_contract.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A10, ML-A16.

## ML-T14. Build one-source upload and progress UI

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T13`
- **Acceptance:** Accept exactly one source, show extraction state/errors and support stable retry/cancel. Polling stops on terminal state/unmount; malformed source/server errors remain visible and editable. No batch order or multi-plan selection.
- **Verification:** `npm --prefix web run test -- --run tests/unit/PlanPreparation.spec.ts`
- **Primary files:** `web/src/api/preparations.ts`, `web/src/composables/usePlanPreparation.ts`, `web/src/components/backtests/PlanPreparationSourceForm.vue`, `web/src/components/backtests/PlanPreparationProgress.vue`, `web/tests/unit/PlanPreparation.spec.ts`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A10, ML-A16, ML-A18.

## ML-T15. Preview and review one prepared plan

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T14`
- **Acceptance:** Show initial account, complete rules, source evidence, historical start/availability and unresolved clauses. Proceed only with the exact reviewed revision; source edits visibly invalidate approval. No rule diffs, successor calendar or descendants.
- **Verification:** `npm --prefix web run test -- --run tests/unit/PlanPreparationReview.spec.ts`
- **Primary files:** `web/src/components/backtests/PlanPreparationReview.vue`, `web/src/views/BacktestNewView.vue`, `web/src/composables/usePlanPreparation.ts`, `web/tests/unit/PlanPreparationReview.spec.ts`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A10, ML-A12, ML-A17, ML-A18.

### ML-C05. Checkpoint

- [ ] Upload, progress and review UI uses generated contracts.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T16. Freeze evidence through an explicit cutoff

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T05`
- **Acceptance:** Represent a partial terminal session without relabeling it complete; validate required closed intervals and this one plan's warm-up. Today/holiday/delayed data remains explicit; legacy manifest bytes/readiness stay unchanged.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_dataset.py tests/unit/test_monitor_loop_cutoff.py tests/integration/test_backtest_compatibility.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_dataset.py`, `src/trade_plan_monitor/backtest/dataset.py`, `src/trade_plan_monitor/backtest/market_store.py`, `tests/integration/test_monitor_loop_dataset.py`, `tests/unit/test_monitor_loop_cutoff.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A04, ML-A09, ML-A11, ML-A15.

## ML-T17. Persist frozen run references within job limits

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T07`, `ML-T11`, `ML-T16`
- **Acceptance:** Store complete reviewed inputs durably and queue only verified immutable references within 256 KiB. Copy needed artifacts before admission; retries, missing/corrupt inputs and preparation pruning cannot silently change a run.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_input_store.py tests/integration/test_backtest_jobs.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_input_store.py`, `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/jobs/models.py`, `src/trade_plan_monitor/backtest/jobs/repository.py`, `tests/integration/test_monitor_loop_input_store.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A18.

## ML-T18. Submit a loop run with one resolved time boundary

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T16`, `ML-T17`, `ML-T33`
- **Acceptance:** Extend submission additively with reviewed preparation identity and optional end; freeze input and cutoff under the idempotency reservation. Duplicate requests after midnight reuse the original result; stale reviews and invalid ranges reject. Resolve/freeze submission through the backtest service and owned repository executor; preserve independent store ownership.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_submission.py tests/integration/test_backtest_run_api.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_runs.py`, `tests/integration/test_monitor_loop_submission.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A09, ML-A10, ML-A15, ML-A18.

### ML-C06. Checkpoint

- [ ] Frozen cutoff input and job references survive retry and stale-review checks.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T19. Run frozen loop inputs through the background worker

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T05`, `ML-T17`, `ML-T18`, `ML-T34`
- **Acceptance:** Dispatch by input discriminator with existing lease/cancel ownership; load frozen artifacts only. No backtest CLI entry, compatibility adapter, or command-owned coordinator remains. Dispatch in the dedicated thread after lifecycle/admission gates; preserve single-slot and atomic-publication semantics.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_worker.py tests/integration/test_backtest_job_coordinator.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/runner.py`, `tests/integration/test_monitor_loop_worker.py`
- **Scope:** M (3 primary files including tests); **Trace:** ML-A01, ML-A09, ML-A10.

## ML-T20. Project causal events and valid valuations

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T04`, `ML-T05`
- **Acceptance:** Separate evaluated/reminded/requested/filled/resulting states and preserve causal links. Report cost-based P/L separately from interval return; unknown prices/cash and zero denominators do not fabricate metrics or liquidation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_loop_valuation.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_report.py`, `src/trade_plan_monitor/backtest/loop_runner.py`, `tests/unit/test_monitor_loop_report.py`, `tests/integration/test_monitor_loop_valuation.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01, ML-A03, ML-A09, ML-A12, ML-A13, ML-A15.

## ML-T21. Publish and retain loop results atomically

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T19`, `ML-T20`
- **Acceptance:** Stream typed events, verify stored input/report hashes and publish only complete runs. Failure/cancel/overflow leaves no completed partial report. Retain latest 30 materialized historical runs total by publication/retention time descending and run_id tie-breaks. Existing bounded maintenance deletes oldest excess summaries/fills/details after publication; pins do not bypass the cap. Protect queued/running references, shared datasets/snapshots and retained frozen single-plan inputs. Existing exports remain byte-compatible; no new cleanup scheduler or resource-budget framework.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_publication.py tests/integration/test_monitor_loop_retention.py tests/integration/test_backtest_publication.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/jobs/maintenance.py`, `tests/integration/test_monitor_loop_publication.py`, `tests/integration/test_monitor_loop_retention.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A10.

### ML-C07. Checkpoint

- [ ] Worker publishes only complete retained results.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T22. Expose paginated loop results; retain export compatibility

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T21`
- **Acceptance:** Result/detail paths expose typed loop events, frozen plan provenance and cutoff coverage with stable paging/schema identification. Preserve old summaries and supported-mode CSV/JSON bytes. No new loop export format/route/UI/jobs/mutex. Heavy projection uses owned threads and bounded paging; backpressure affects backtest admission only.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_result_api.py tests/integration/test_backtest_exports.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `tests/integration/test_monitor_loop_result_api.py`
- **Scope:** M (3 primary files including tests); **Trace:** ML-A09, ML-A10, ML-A15.

## ML-T23. Generate final run and result contracts

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T18`, `ML-T22`
- **Acceptance:** Regenerate after the actual run/result API change and verify discriminated old/new payloads, bounds and safe numbers. Keep the approved-digest review pending ML-T29; do not silence baseline approval failures.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **Primary files:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_monitor_loop_contract.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A10.

## ML-T24. Submit one prepared plan from the existing run form

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T15`, `ML-T23`
- **Acceptance:** Use one reviewed snapshot and its extracted opening account without raw operations JSON. End defaults server-side. Show resolved cutoff, missing facts and unsupported clauses, then existing job/result navigation. No multi-plan selectors.
- **Verification:** `npm --prefix web run test -- --run tests/unit/MonitorLoopRunForm.spec.ts`
- **Primary files:** `web/src/components/backtests/BacktestRunForm.vue`, `web/src/composables/useBacktestRunForm.ts`, `web/src/api/backtests.ts`, `web/src/views/BacktestNewView.vue`, `web/tests/unit/MonitorLoopRunForm.spec.ts`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A10, ML-A12, ML-A14, ML-A15.

### ML-C08. Checkpoint

- [ ] Result APIs and run creation work with old/new contracts; existing exports remain compatible without new development.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T25. Explain plan and execution history in results

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T22`, `ML-T23`
- **Acceptance:** Connect paginated causal events and frozen single-plan provenance to the result page; distinguish holds, blocked/unfilled intents and fills. Show account evolution, valid metrics and actual cutoff without client trading logic or version-switch timeline.
- **Verification:** `npm --prefix web run test -- --run tests/unit/MonitorLoopResults.spec.ts`
- **Primary files:** `web/src/components/backtests/MonitorLoopTimeline.vue`, `web/src/views/BacktestRunDetailView.vue`, `web/src/composables/useBacktestResults.ts`, `web/tests/unit/MonitorLoopResults.spec.ts`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01, ML-A10, ML-A13, ML-A15.

## ML-T26. Prove parity, causality and failure atomicity

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T05`, `ML-T11`, `ML-T16`, `ML-T21`, `ML-T34`
- **Acceptance:** Compare online application participants with loop state using independent expected outputs; mutate future evidence and inject transaction/worker faults. Include one deliberate invariant mutation check; fake AI/provider/sink counters prove isolation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_parity.py tests/integration/test_monitor_loop_faults.py tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **Primary files:** `tests/integration/test_monitor_loop_parity.py`, `tests/integration/test_monitor_loop_faults.py`, `tests/fixtures/monitor-loop/scenarios.json`, `tests/integration/test_plan_preparation_worker.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01–ML-A24 excluding cancelled ML-A07.

## ML-T27. Verify the complete browser journey

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T24`, `ML-T25`, `ML-T26`, `ML-T36`
- **Acceptance:** Use real mounted API/composition with fake external services for upload → retry/edit → review → run → results. Prove the fixture supplies no future trade script and tests neither mocked result-only screens nor live user databases. Include service-down/unknown-cancel/recovery navigation while monitor pages remain usable.
- **Verification:** `npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts`; `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_production_composition.py -q -m "not live"`
- **Primary files:** `web/tests/e2e/monitor-loop-backtest.spec.ts`, `web/tests/fixtures/monitor-loop.json`, `tests/integration/test_monitor_loop_production_composition.py`
- **Scope:** M (3 primary files including tests); **Trace:** ML-A10, ML-A16, ML-A18.

### ML-C09. Checkpoint

- [ ] Independent fault/parity and full browser journey pass.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T28. Record operation guidance and executed evidence

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T27`, `ML-T37`
- **Acceptance:** Document actual supported API/UI behavior and source limitations in both languages. Execute the plan's relevant final gates and record exact results, unresolved failures and evidence scope; never claim live AI/provider certification.
- **Verification:** `git diff --check`
- **Primary files:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01–ML-A24 excluding cancelled ML-A07.

## ML-T29. Align reviewed specifications and API approval

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T23`, `ML-T28`, `ML-T38`, `ML-T39`
- **Acceptance:** Review the final API/behavior diff with its bilingual contract; record only the resulting approved snapshot identity and final implementation scope. Preserve old approval history and explicitly distinguish the previously known baseline mismatch.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m "not live"`
- **Primary files:** `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.md`, `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md`, `docs/specifications/monitoring/SPEC-unified-plan.md`, `docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A09, ML-A10.

### ML-C10. Checkpoint

- [ ] Active ML-A01–ML-A24 evidence (excluding cancelled ML-A07) and reviewed bilingual contracts are complete.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

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

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T12`, `ML-T23`, `ML-T33`, `ML-T34`
- **Acceptance:** Status/stop are inert when unused; first actual data/operation request activates needed capabilities after guards/validation. Recovery explicitly retries preparation or selected resumeJobIds (<=1) with epoch/revision/idempotency. Scoped 503/Retry-After means no job admitted; initialization polling cannot restart failed preparation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_service_api.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/web/routers/backtest_service.py`, `src/trade_plan_monitor/web/backtest_service_schemas.py`, `src/trade_plan_monitor/web/app.py`, `tests/integration/test_backtest_service_api.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A19, ML-A21, ML-A24.

## ML-T39. Generate independent service transport contracts

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T35`
- **Acceptance:** Generate mounted service resources and typed capabilities/errors in both contract profiles. Check that monitor endpoints and unaffected payloads retain their prior meaning; preserve the stale approval record for explicit final review. No handwritten duplicate transport models.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_service_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **Primary files:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_backtest_service_contract.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A19, ML-A24.

## ML-T36. Show first-use preparation and scoped recovery in Web

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T39`
- **Acceptance:** Only active backtest data requests trigger lazy preparation; route prefetch/global status polling stays inert. Show unused/initializing/read-ready/execution-ready/failure distinctly, preserve forms across 503 and reuse mutation keys. Opening history never resumes jobs/AI; explicit retry/resume shows selected backlog and monitoring stays usable.
- **Verification:** `npm --prefix web run test -- --run tests/unit/BacktestServiceState.spec.ts`; `npm --prefix web run type-check`
- **Primary files:** `web/src/api/backtestService.ts`, `web/src/composables/useBacktestService.ts`, `web/src/components/backtests/BacktestServiceState.vue`, `web/src/views/BacktestNewView.vue`, `web/tests/unit/BacktestServiceState.spec.ts`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A21, ML-A24.

## ML-T37. Verify Windows lazy activation and thread boundaries

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T26`, `ML-T27`, `ML-T34`, `ML-T36`
- **Acceptance:** Prove zero backtest work across app startup/monitor navigation/status/prefetch/shutdown, concurrent first-use single initialization, read-only history without backlog execution and explicit selected resume. Inject first-use errors/late futures/cancel races with controllable fixtures; retain ML17 10-stock load gates and accepted thread limits.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_isolation_fault_matrix.py tests/integration/test_monitor_loop_parity.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/verify_backtest_thread_load.py --profile windows-threads --offline`
- **Primary files:** `tests/integration/test_backtest_isolation_fault_matrix.py`, `tests/fixtures/monitor-loop/isolation.json`, `scripts/verify_backtest_thread_load.py`, `tests/integration/test_backtest_sync_pacing.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A08, ML-A19–ML-A24.

## ML-T38. Record on-demand thread operation guidance

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T37`
- **Acceptance:** Paired guidance explains dormant startup, first-use preparation, metadata versus execution, explicit backlog resume, scoped repair and drain-aware stop. Document shared-process risks without mandatory process upgrade; preserve identities and the historical baseline approval mismatch with its reviewed correction.
- **Verification:** `git diff --check`
- **Primary files:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A19–ML-A24.

### ML-C13. Checkpoint

- [ ] Service API/UI and recorded Windows thread fault/load acceptance pass; ML-C10 remains the final combined gate.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.
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
