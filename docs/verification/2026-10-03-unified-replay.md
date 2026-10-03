# Unified Replay Verification

## V01. Scope and review

Date: 2026-10-03, Asia/Shanghai. Baseline: `6118569`. This report covers [UR01–UR08](../specifications/backtesting/SPEC-unified-replay.md), the implementation [S1–S7](../../tasks/unified-replay-plan.md), and the [usable local guide](../operations/unified-replay.md). Status: **LOCALLY_VERIFIED**. Final independent parent review: **PASS** within UR01–UR08 and the declared limitations. Changes are local and uncommitted. No production database/configuration, external provider/AI, notification delivery, real order, commit, push or deployment was used.

The parent Astra/high agent owned design, scope and independent review. The explicitly selected Sol/high implementation agent encountered two capacity failures. A separate continuation subagent using the inherited parent configuration completed the remaining sequential implementation; there were no concurrent code editors. Parent review identified and verified fixes for missing reminder projections, pre/post-operation state ambiguity, the 500-occurrence lookup limit, monetary safe-number overflow, timestamp normalization, readable signal blockers, bounded calendar context and cancellation phase compatibility.

Schema 5 runs use `backtest-run-v4`, report `backtest-report-v3`, typed decision/operation/equity details, summary export `backtest-report-summary-v4` and valuation CSV `explicit-simulation-valuation-v1`. Existing durable v2 envelopes and set-hash domains remain. The current monitor applies explicit whole simulation; a separate pure fee/slippage projection cannot resize it or grant authority. Unknown inventory and insufficient research cash preserve null/invalid valuation. Legacy exports remain unchanged. UUID canonical serialization is additive support for the already-existing plan-version lookup metadata, not a new semantic identity component.

## V02. Acceptance evidence by requirement

| ID | Executed current evidence |
|---|---|
| UR-A01 | `test_unified_replay_input.py` rejects missing/mismatched research declarations, non-boolean confirmation, unknown inventory with lots and unsupported assumptions. `test_unified_replay_entries.py` rejects unreviewed/missing/mismatched authority and submits an inactive server-reviewed plan with optional bucket caps. |
| UR-A02 | Existing byte/round-trip compatibility suites remain green. Current identities change for input changes. The future-market test changes a later daily close, rebinds an already available proof to the new dataset, and compares every earlier event including IDs/state. |
| UR-A03 | `test_unified_replay.py` tests missing/explicit daily proof, scoped delayed negative/positive facts and future official proof rejection. Boundaries test an incomplete visible five-minute bucket, intraday warm-up, rejected incompatible minute receipt delay, 512-row calendar context, and a real two-day daily execution. An additional single `ALL(daily, minute, fact)` tree rejects the early fact, accepts negative then positive facts after the official close, and confirms only at the positive arrival while remaining non-executable after session end. |
| UR-A04 | Boundaries cover `PLAN_ACTIVE`, inclusive `DATE_RANGE`, activation windows, next-session daily execution, next-day minute expiry, independent second occurrence and no repeat without explicit evidence. |
| UR-A05 | Current tests cover deactivation/reviewed replacement, risk obligations surviving termination, explicit reassessment and a later evaluation keeping consumed risk evidence clear. The independent public oracle saves a successor draft and verifies original authority remains active. |
| UR-A06 | Actual reminder outcome/cause/confirmation evidence produces no inventory change. Positive/negative technical facts remain scoped. Mixed minute/daily/risk parity covers unavailable risk blocking an explicit request, followed by a fulfilled zero-target severe obligation suppressing ordinary daily confirmation. |
| UR-A07 | Whole quantity, duplicate consumption, partial rejection, T+1, CORE, maximum position and unknown holdings are asserted in current replay scenarios. A stored-ledger test resolves occurrence 501. Accumulated monetary fees exceeding the safe integer range fail explicitly. |
| UR-A08 | `test_unified_replay_parity.py` independently reconstructs visible minute prefixes, completed targets, quotes and certified daily inputs; activates a separate real temporary current monitor; and uses the public simulation endpoint. Every replay event's normalized signals, risks, action and inventory is compared. Normalization removes storage identities and revision counters only: public mutations additionally reevaluate at the same instant. Evidence, confirmation time/window, blockers and quantities remain compared, with independent successful/blocked operation expectations. |
| UR-A09 | Repeated report/JSON/CSV bytes, future facts and future market/proof rebinding are checked. Mid-replay cancellation returns a typed cancellation result. Real API cancellation after one evaluated event reaches `CANCELLED`, returns no result and publishes no run. |
| UR-A10 | Real local CLI and temporary API→durable worker→read/equity/export succeed. Idempotent submission returns the same job; worker cannot reread live plan authority. Guards fail on provider/AI/socket/live-lifecycle/outbox/delivery access and check isolated runtime DB cleanup. Browser form/detail coverage uses actual server projection bytes and checks accessibility, console and external requests. |

The oracle compares separately orchestrated stores and public operations, not two calls to the research adapter. Its severe branch has known zero holdings, so the zero target correctly reaches `FULFILLED`; the separate latched-risk scenario starts with 100 tactical shares and verifies `CONFIRMED` through stop and explicit removal. The synthetic plan is complete research input; it is not reconstructed from the incomplete Spring Airlines source and is not real AI acceptance.

## V03. Final commands and results

Run Python commands from `trade-plan-monitor/`, frontend commands from `web/`. Counts below refer to separate commands; overlapping suites are not added into an invented total.

| Command | Result |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/unit tests/contract -q -m 'not live'` | 2744 passed, 4 deselected, 1 existing Starlette/httpx deprecation warning; 21.94s. The deselection excludes `live` tests. |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_backtest_compatibility.py tests/integration/test_backtest_exports.py tests/integration/test_backtest_results.py tests/integration/test_backtest_run_api.py tests/integration/test_backtest_result_api.py tests/integration/test_backtest_export_api.py tests/integration/test_backtest_production_composition.py tests/integration/test_backtest_publication.py tests/integration/test_backtest_job_coordinator.py tests/integration/test_backtest_jobs.py tests/integration/test_unified_runtime.py tests/integration/test_unified_simulation_transactions.py -q -m 'not live' -rs` | 246 passed, 1 skipped, 1 existing warning; 46.13s. Skip: `test_backtest_production_composition.py:501` requires POSIX ownership semantics. |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_replay.py tests/integration/test_unified_replay_boundaries.py tests/integration/test_unified_replay_parity.py tests/integration/test_unified_replay_entries.py -q -m 'not live'` | 37 passed, 1 existing warning; 125.52s. Final candidate before the narrow online-default alert-gate correction; targeted regression recorded below. |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_runtime.py tests/integration/test_unified_replay_boundaries.py::test_reminder_only_has_actual_evidence_without_inventory_or_authority_outside_window tests/integration/test_unified_replay_parity.py -q -m 'not live'` | 26 passed, 1 existing warning; 37.66s after the narrow online-default alert-gate correction. |
| `.venv/Scripts/python.exe -m pytest tests/integration/test_unified_replay_boundaries.py::test_mixed_tree_needs_daily_minute_and_delayed_positive_fact_at_one_cutoff -q -m 'not live'` | 1 passed; 3.54s (implementation), independently 1 passed in 3.50s (parent). Added after the 37-case candidate; production code unchanged. |
| `.venv/Scripts/python.exe -m ruff check src tests scripts` | Passed. |
| `.venv/Scripts/python.exe -m compileall -q src` | Passed. |
| `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check` | Passed: canonical v2 and compatibility v1 artifacts synchronized. |
| `npm run test -- --run` | 57 files, 807 tests passed; 6.21s. |
| `npm run type-check` | Passed. |
| `npm run build` | Passed. |
| `npm run test:e2e -- tests/e2e/backtests.spec.ts` | 6 passed; 22.8s. Chrome routes, keyboard/axe, current research, job submission, layout and bounded rendering/polling checks. |
| `git diff --check` | Passed at final documentation handoff. |

An initial frontend test run was mistakenly scheduled concurrently with production build and reported one `runtimeStatusBuild` `ENOENT` while build replaced `dist` assets. The parent reran the suite sequentially after build: all 807 passed. No code or assertion was weakened for that orchestration race. Existing expensive capacity evidence is retained in [backtest acceptance](backtest-acceptance.md); it was not rerun or relabeled as current replay acceptance.

Independent mutation check: the parent temporarily replaced `_confirmed.__code__` in memory with a coercive implementation. `test_review_true_is_never_coerced` produced the expected 1 failed / 2 passed, detecting numeric `1` accepted as confirmation. The process exited and no source mutation remained.

## V04. Reproducible synthetic run and limits

Both agents independently ran `scripts/create_unified_replay_fixture.py --output <fresh-temp-directory> --run`. The builder and both real CLI runs succeeded. Reopening the generated results verified 49 typed decisions per run and actual minute/daily signals, not merely empty successful execution. Empty scripts kept 1,000,000 fen equity and zero trades.

- Dataset: `1704a62d8d35a08dceae6a6d62d8204b61d247ec6b6a9fb90a7f85d32881c752`.
- Minute run: `1bda3c0df33375d5470ee3403f283aaa11efe0b6447c798fa9482ceffc7ac44f`.
- Daily run: `ae604335984e58851d43af35821901d15c54ca6174849b4187dab9cba16d4bf4`.

The daily state uses `confirmed_trade_date`; `confirmed_at` is null for official daily confirmation. CSV `monitor_status` and `valuation_status` intentionally distinguish receipt application from the money projection. `FULL_SESSION_SUSPENSION` remains explicitly unsupported and visible. Dataset receipt grace remains a historical profile assumption, not real collection certification. Missing adjustment/session/quote evidence fails closed. No real source plan, production migration, live provider, notification, broker or deployment acceptance is claimed.
