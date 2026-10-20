# Backtest cost default verification, 2026-10-20

## BCD-V01. Authority and scope

The user requested minimum-cost defaults, then explicitly selected actual low-cost transaction assumptions with zero slippage instead of making every cost zero. The implementation uses the editable PR-O08 preset: `commissionRate=0.0001`, `minimumCommissionFen=500`, `stampDutyRate=0.0005`, `transferFeeRate=0.00001`, zero fen/BPS slippage. Commission is a research assumption, not a universal minimum quote. Statutory-rate context is recorded with its source in the paired [operations guide](../operations/plan-reuse.md#pr-o08-editable-low-cost-replay-defaults).

Production changes are limited to six initialization strings in `useBacktestRunForm.ts` and one explanatory sentence in `BacktestRunForm.vue`. The existing fen-slippage defaults were already zero. No API schema, backend, execution/fee calculation, rounding, plan linkage, timing, database, historical reader or dependency changes are included. Costs remain required API inputs; only a new frontend draft is prefilled.

## BCD-V02. Regression and review evidence

Two new default-submission cases failed before implementation. They then passed for both an existing single-plan review and an ordered timeline, checking exact default fee values and the submitted numeric fen values without manually filling costs. A third case verifies that explicit zero values survive a plan change and that clearing commission is still rejected. Existing helper calls keep their explicit original fees and execution/result expectations. Browser journeys now assert the initial defaults for workbench, source-preparation and four-plan entries before entering their original fees.

Temporarily changing default commission from `0.0001` to `0` caused both new default cases to fail; original source bytes were restored and all 29 run-form tests passed. Independent read-only review found no blockers: draft initialization runs once, no new reset/watch overrides user input, and fee/slippage units match the original API. All 1175 frontend tests in 78 files passed, as did type checking and production build.

The first complete browser round passed 20 cases and found one outdated keyboard fixture: it expected empty costs to trigger an error, but the newly prefilled form is valid. That case now asserts the commission default, explicitly clears commission, then retains the original error-summary focus and accessibility checks. It additionally checks the invalid-field state and absence of run submissions. The repaired case passed its focused browser rerun. No production validation, audit exclusion, timeout, retry count or layout threshold was changed.

## BCD-V03. Preserved boundaries

Defaults apply to newly created forms only. No existing stored result is repriced, and no historical fee data is changed. Explicit edits, including zero, retain the original validation, captured intent and same-request retry behavior. Rates are not selected automatically by replay date. Tests use isolated stores/providers; the running monitoring service is not stopped or restarted.

## BCD-V04. Final browser and scope checks

The complete command `npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/streamCompletion.spec.ts tests/e2e/plan-library-versions.spec.ts` passed all 21 cases in 6.5 minutes with zero retries. It checks prefilled costs in workbench, source-preparation and four-plan forms before explicitly overriding them with the original fixture costs. The original four-plan/one-account/two-fill oracle, cash `1019000` fen, quantity `0`, fees `1000` fen, realized P&L `19000` fen and exact seven-point equity sequence passed unchanged, together with history isolation, keyboard/axe checks, cancellation audits and 320/768/1024/1440px layout bounds. No assertions or test thresholds were lowered.

The nine-file candidate contains two production files, three test files and four paired operations/verification documents. All backend and unrelated tracked file bytes match the task-start audit. Real preparation/result database hashes still match PUT-V03 in the timeline report, and all 24 diagnostic result files remain intact. Staged whitespace and index/working-file consistency checks passed.
