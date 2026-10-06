# Active Task List: Monitoring-loop Backtest

> Pending implementation, 2026-10-06. Plan: [plan.md](plan.md); Chinese copy: [todo.zh-CN.md](todo.zh-CN.md). ML-T01–ML-T29 are not implemented. Previously completed historical tasks are retained below.

Run commands from `trade-plan-monitor/`; new files are planned outputs. Execute verification after implementing its task; writing this list does not mean those checks ran. Keep each task to about five primary files; split expanded scope first. Contract generation and digest approval are separate; do not silently approve an API to pass a check.

## ML-T01. Define frozen loop input and time boundaries

- [ ] Complete implementation and task verification.
- **Dependencies:** None
- **Acceptance:** Strict versioned inputs separate source/activation/end times, account cost/mark and zero/unknown cash; validate the proposed limits without altering legacy encodings. Same-version continuation and end-date resolution are deterministic.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_input.py tests/unit/test_monitor_loop_schedule.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_input.py`, `src/trade_plan_monitor/backtest/plan_schedule.py`, `tests/unit/test_monitor_loop_input.py`, `tests/unit/test_monitor_loop_schedule.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A04, ML-A09, ML-A11, ML-A12, ML-A15.

## ML-T02. Extract a shared simulation participant

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T01`
- **Acceptance:** Move existing authorization/quantity/inventory transitions behind an application participant with caller-owned transactions; online commands and old replay retain their prior receipts, errors and behavior.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_simulation_participant.py tests/integration/test_unified_simulation_transactions.py tests/integration/test_unified_replay.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/state/simulation.py`, `src/trade_plan_monitor/web/daily_service.py`, `src/trade_plan_monitor/backtest/research_session.py`, `tests/integration/test_simulation_participant.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A05, ML-A08, ML-A09.

## ML-T03. Capture reminders in a private loop session

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T02`
- **Acceptance:** Use shared monitoring/delivery eligibility, isolated repositories and deterministic clock/IDs; capture valid reminders and reject stale evidence. Pure technical alerts never authorize execution; no live sink is constructed.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_reminders.py tests/integration/test_unified_runtime.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_session.py`, `src/trade_plan_monitor/backtest/reminder_capture.py`, `src/trade_plan_monitor/runtime/daily_service.py`, `tests/integration/test_monitor_loop_reminders.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A02, ML-A03, ML-A06, ML-A08.

### ML-C01. Checkpoint

- [ ] Shared monitoring participants preserve online behavior.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T04. Commit account and inventory atomically

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T02`, `ML-T03`
- **Acceptance:** Apply exact fees/slippage and full-quantity cash checks before one transaction covering money, lots, signal consumption and receipts. Preserve 401050-fen opening cost; failed/repeated commits cannot leave partial or duplicate effects.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_costs.py tests/integration/test_monitor_loop_account.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_account.py`, `src/trade_plan_monitor/backtest/loop_session.py`, `tests/unit/test_monitor_loop_costs.py`, `tests/integration/test_monitor_loop_account.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A05, ML-A09, ML-A12, ML-A13.

## ML-T05. Run a single-plan reminder response cycle

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T03`, `ML-T04`
- **Acceptance:** A reviewed fixture discovers buy/sell times without a trade script; enforce next eligible interval, risk priority, single occurrence consumption and finite bounds. Observe/recorded modes do not add unsolicited trades.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_cycle.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_runner.py`, `src/trade_plan_monitor/backtest/response_policy.py`, `tests/integration/test_monitor_loop_cycle.py`
- **Scope:** M (3 primary files including tests); **Trace:** ML-A01, ML-A02, ML-A03, ML-A04, ML-A06.

## ML-T06. Continue replay across daily plan changes

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T05`
- **Acceptance:** Switch before eligible daily actions, preserve account/risk state and invalidate old ordinary intents; carry forward only valid plans without resetting identical versions. Later portfolio statements cannot overwrite the ledger.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_plan_switch.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/plan_schedule.py`, `src/trade_plan_monitor/backtest/loop_session.py`, `src/trade_plan_monitor/backtest/loop_runner.py`, `tests/integration/test_monitor_loop_plan_switch.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A07, ML-A11, ML-A13.

### ML-C02. Checkpoint

- [ ] Reviewed fixtures run a complete one-plan and daily-chain cycle with atomic accounts.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T07. Persist preparation batches and revision state

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T01`
- **Acceptance:** Create a separately tagged preparation store with bounded sources, per-item attempts, revisions and idempotency; reject cross-domain paths. Persist enough state for restart while approval remains separate from validation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_store.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/preparation_models.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_store.py`
- **Scope:** M (3 primary files including tests); **Trace:** ML-A16, ML-A18.

## ML-T08. Extract one plan with bounded predecessor context

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T07`
- **Acceptance:** Version the first/follow-up output contract, reuse provider/parsing safeguards and retain source spans. Requests contain only the current source and needed predecessor evidence; missing semantics remain unresolved and old single-plan extraction is unchanged.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_plan_update_extraction.py tests/unit/test_current_plan_extraction_security.py tests/unit/test_ai_plan_extraction_v4.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/ai/plan_update_extraction.py`, `src/trade_plan_monitor/ai/extraction.py`, `tests/unit/test_plan_update_extraction.py`, `tests/fixtures/ai/plan-update-cases.json`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A12, ML-A14, ML-A16, ML-A17.

## ML-T09. Materialize traceable complete plan versions

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T07`, `ML-T08`
- **Acceptance:** Apply typed add/modify/revoke/retain changes, distinguish full and partial updates, and preserve inherited source evidence. Reject ambiguous omissions, invalid targets and invented human facts; output complete snapshots with diffs.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_plan_update_merge.py tests/unit/test_plan_update_bindings.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/plan_updates.py`, `src/trade_plan_monitor/ai/update_review.py`, `tests/unit/test_plan_update_merge.py`, `tests/unit/test_plan_update_bindings.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A16, ML-A17.

### ML-C03. Checkpoint

- [ ] Preparation persistence, extraction and source-bound merging pass focused checks.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T10. Resume sequential extraction safely

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T07`, `ML-T08`, `ML-T09`
- **Acceptance:** Claim items with generation/source/base fences, reuse the AI concurrency budget and persist progress outside calls. Retry only bounded retryable failures; cancel/restart/edit rejects stale completion and preserves unaffected predecessors.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_worker.py`, `src/trade_plan_monitor/web/ai_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `tests/integration/test_plan_preparation_worker.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A16, ML-A18.

## ML-T11. Review and freeze a complete preparation chain

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T09`, `ML-T10`
- **Acceptance:** Bind explicit review to exact source/base/content/evidence revisions and freeze immutable manifests. Correcting an ancestor invalidates descendants; validation cannot create approval or activate a production plan.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_plan_preparation_review.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/preparation_review.py`, `src/trade_plan_monitor/backtest/preparation_service.py`, `src/trade_plan_monitor/backtest/preparation_store.py`, `src/trade_plan_monitor/ai/update_review.py`, `tests/integration/test_plan_preparation_review.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A17, ML-A18.

## ML-T12. Expose the preparation application path

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T10`, `ML-T11`
- **Acceptance:** Connect bounded create/read/edit/extract/cancel/review operations to application ownership and startup/shutdown. Real HTTP tests prove revision conflicts, idempotency, pagination and fake-AI progress without mutating live plans.
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

## ML-T14. Build batch upload and progress UI

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T13`
- **Acceptance:** Upload once with explicit order, show item state/errors and support stable retry/cancel intents. Polling stops on terminal state/unmount; malformed source or server errors remain editable and visible.
- **Verification:** `npm --prefix web run test -- --run tests/unit/PlanBatchPreparation.spec.ts`
- **Primary files:** `web/src/api/preparations.ts`, `web/src/composables/usePlanBatch.ts`, `web/src/components/backtests/PlanBatchSourceForm.vue`, `web/src/components/backtests/PlanBatchProgress.vue`, `web/tests/unit/PlanBatchPreparation.spec.ts`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A10, ML-A16, ML-A18.

## ML-T15. Preview and review the prepared plan calendar

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T14`
- **Acceptance:** Show initial account, rule diffs, source evidence, effective-day calendar and unresolved clauses. Only the exact server-reviewed revision can proceed; ancestor edits visibly invalidate affected descendants.
- **Verification:** `npm --prefix web run test -- --run tests/unit/PlanBatchReview.spec.ts`
- **Primary files:** `web/src/components/backtests/PlanBatchReview.vue`, `web/src/views/BacktestNewView.vue`, `web/src/composables/usePlanBatch.ts`, `web/tests/unit/PlanBatchReview.spec.ts`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A10, ML-A12, ML-A17, ML-A18.

### ML-C05. Checkpoint

- [ ] Upload, progress and review UI uses generated contracts.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T16. Freeze evidence through an explicit cutoff

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T01`, `ML-T06`
- **Acceptance:** Represent a partial terminal session without relabeling it complete; validate required closed intervals and unioned plan warm-up. Today/holiday/delayed data is explicit and legacy manifest bytes/readiness remain unchanged.
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
- **Dependencies:** `ML-T16`, `ML-T17`
- **Acceptance:** Extend submission additively with reviewed preparation identity and optional end; freeze input and cutoff under the idempotency reservation. Duplicate requests after midnight reuse the original result; stale reviews and invalid ranges reject.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_submission.py tests/integration/test_backtest_run_api.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/routers/backtest_runs.py`, `tests/integration/test_monitor_loop_submission.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A09, ML-A10, ML-A15, ML-A18.

### ML-C06. Checkpoint

- [ ] Frozen cutoff input and job references survive retry and stale-review checks.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T19. Run frozen loop inputs through the background worker

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T05`, `ML-T06`, `ML-T17`, `ML-T18`
- **Acceptance:** Dispatch by input discriminator with existing lease/cancel ownership; load frozen artifacts only. No backtest CLI entry, compatibility adapter, or command-owned coordinator remains.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_worker.py tests/integration/test_backtest_job_coordinator.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/runner.py`, `tests/integration/test_monitor_loop_worker.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A01, ML-A09, ML-A10.

## ML-T20. Project causal events and valid valuations

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T04`, `ML-T05`, `ML-T06`
- **Acceptance:** Separate evaluated/reminded/requested/filled/resulting states and preserve causal links. Report cost-based P/L separately from interval return; unknown prices/cash and zero denominators do not fabricate metrics or liquidation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_loop_report.py tests/integration/test_monitor_loop_valuation.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/loop_report.py`, `src/trade_plan_monitor/backtest/loop_runner.py`, `tests/unit/test_monitor_loop_report.py`, `tests/integration/test_monitor_loop_valuation.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01, ML-A03, ML-A09, ML-A12, ML-A13, ML-A15.

## ML-T21. Publish and retain loop results atomically

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T19`, `ML-T20`
- **Acceptance:** Stream typed events, verify stored input/report hashes and publish only complete runs. Cancel/failure/limit overflow leaves no completed partial report; retention pins chain artifacts required by results and exports.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_publication.py tests/integration/test_monitor_loop_retention.py tests/integration/test_backtest_publication.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/results.py`, `src/trade_plan_monitor/backtest/application.py`, `src/trade_plan_monitor/backtest/jobs/maintenance.py`, `tests/integration/test_monitor_loop_publication.py`, `tests/integration/test_monitor_loop_retention.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A10.

### ML-C07. Checkpoint

- [ ] Worker publishes only complete retained results.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T22. Expose paginated loop results and exports

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T21`
- **Acceptance:** Existing result/detail/export paths expose typed loop events, version history and cutoff coverage with stable paging. Old summaries/CSV/JSON remain byte-compatible; new projections identify their schema explicitly.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_result_api.py tests/integration/test_monitor_loop_exports.py tests/integration/test_backtest_exports.py -q -m "not live"`
- **Primary files:** `src/trade_plan_monitor/backtest/composition.py`, `src/trade_plan_monitor/web/backtest_schemas.py`, `src/trade_plan_monitor/web/backtest_export.py`, `tests/integration/test_monitor_loop_result_api.py`, `tests/integration/test_monitor_loop_exports.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A10, ML-A15.

## ML-T23. Generate final run and result contracts

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T18`, `ML-T22`
- **Acceptance:** Regenerate after the actual run/result API change and verify discriminated old/new payloads, bounds and safe numbers. Keep the approved-digest review pending ML-T29; do not silence baseline approval failures.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_contract.py -q -m "not live"`; `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`
- **Primary files:** `openapi.json`, `openapi.runtime-status.json`, `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `tests/integration/test_monitor_loop_contract.py`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A09, ML-A10.

## ML-T24. Submit prepared plans from the existing run form

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T15`, `ML-T23`
- **Acceptance:** Use the reviewed manifest and extracted initial account without raw operations JSON; optional end defaults on the server. Show resolved cutoff, missing facts and unsupported clauses, then follow the existing job/result navigation.
- **Verification:** `npm --prefix web run test -- --run tests/unit/MonitorLoopRunForm.spec.ts`
- **Primary files:** `web/src/components/backtests/BacktestRunForm.vue`, `web/src/composables/useBacktestRunForm.ts`, `web/src/api/backtests.ts`, `web/src/views/BacktestNewView.vue`, `web/tests/unit/MonitorLoopRunForm.spec.ts`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A10, ML-A12, ML-A14, ML-A15.

### ML-C08. Checkpoint

- [ ] Result/export APIs and run creation work with old/new contracts.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T25. Explain plan and execution history in results

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T22`, `ML-T23`
- **Acceptance:** Connect paginated causal events and daily plan history to the actual result page; distinguish holds, rejected/unfilled intents and completed fills. Show account evolution, valid metrics and actual data cutoff without client-side trading logic.
- **Verification:** `npm --prefix web run test -- --run tests/unit/MonitorLoopResults.spec.ts`
- **Primary files:** `web/src/components/backtests/MonitorLoopTimeline.vue`, `web/src/components/backtests/PlanVersionTimeline.vue`, `web/src/views/BacktestRunDetailView.vue`, `web/src/composables/useBacktestResults.ts`, `web/tests/unit/MonitorLoopResults.spec.ts`
- **Scope:** M (5 primary files including tests); **Trace:** ML-A01, ML-A07, ML-A10, ML-A13, ML-A15.

## ML-T26. Prove parity, causality and failure atomicity

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T06`, `ML-T11`, `ML-T16`, `ML-T21`
- **Acceptance:** Compare online application participants with loop state using independent expected outputs; mutate future evidence and inject transaction/worker faults. Include one deliberate invariant mutation check; fake AI/provider/sink counters prove isolation.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_parity.py tests/integration/test_monitor_loop_faults.py tests/integration/test_plan_preparation_worker.py -q -m "not live"`
- **Primary files:** `tests/integration/test_monitor_loop_parity.py`, `tests/integration/test_monitor_loop_faults.py`, `tests/fixtures/monitor-loop/scenarios.json`, `tests/integration/test_plan_preparation_worker.py`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01–ML-A18.

## ML-T27. Verify the complete browser journey

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T24`, `ML-T25`, `ML-T26`
- **Acceptance:** Use real mounted API/composition with fake external services for upload → retry/edit → review → run → results/export. Prove the fixture supplies no future trade script and tests neither mocked result-only screens nor live user databases.
- **Verification:** `npm --prefix web run test:e2e -- tests/e2e/monitor-loop-backtest.spec.ts`; `.venv/Scripts/python.exe -m pytest tests/integration/test_monitor_loop_production_composition.py -q -m "not live"`
- **Primary files:** `web/tests/e2e/monitor-loop-backtest.spec.ts`, `web/tests/fixtures/monitor-loop.json`, `tests/integration/test_monitor_loop_production_composition.py`
- **Scope:** M (3 primary files including tests); **Trace:** ML-A10, ML-A16, ML-A18.

### ML-C09. Checkpoint

- [ ] Independent fault/parity and full browser journey pass.
- [ ] Record executed evidence; resolve failures before dependent work without lowering the bar.

## ML-T28. Record operation guidance and executed evidence

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T27`
- **Acceptance:** Document actual supported API/UI behavior and source limitations in both languages. Execute the plan's relevant final gates and record exact results, unresolved failures and evidence scope; never claim live AI/provider certification.
- **Verification:** `git diff --check`
- **Primary files:** `docs/operations/monitor-loop-backtest.md`, `docs/operations/monitor-loop-backtest.zh-CN.md`, `docs/verification/monitor-loop-backtest.md`, `docs/verification/monitor-loop-backtest.zh-CN.md`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A01–ML-A18.

## ML-T29. Align reviewed specifications and API approval

- [ ] Complete implementation and task verification.
- **Dependencies:** `ML-T23`, `ML-T28`
- **Acceptance:** Review the final API/behavior diff with its bilingual contract; record only the resulting approved snapshot identity and final implementation scope. Preserve old approval history and explicitly distinguish the previously known baseline mismatch.
- **Verification:** `.venv/Scripts/python.exe -m pytest tests/integration/test_openapi_snapshot.py -q -m "not live"`
- **Primary files:** `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.md`, `docs/specifications/backtesting/PROPOSAL-monitor-loop-backtest.zh-CN.md`, `docs/specifications/monitoring/SPEC-unified-plan.md`, `docs/specifications/monitoring/SPEC-unified-plan.zh-CN.md`
- **Scope:** M (4 primary files including tests); **Trace:** ML-A09, ML-A10.

### ML-C10. Checkpoint

- [ ] All ML-A01–ML-A18 evidence and reviewed bilingual contracts are complete.
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
