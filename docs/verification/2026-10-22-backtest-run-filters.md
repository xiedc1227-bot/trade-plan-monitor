# Backtest run-filter removal verification

Date: 2026-10-22 (Asia/Shanghai)

## Scope

Remove the run-history backtest end-date controls and their “More filters” section. Keep stock-code and retention filters. Retired `eventEndFrom`/`eventEndTo` URL parameters and their cursor are stripped before querying page 1. The run-history page no longer sends these parameters; API date-filter support stays compatible.

## Validation

- `npm test -- --run --maxWorkers=4`: 83 files, 1206 tests passed.
- `npm run type-check`: passed.
- `npm run build`: passed, including the packaged Python web distribution.
- `npm run test:e2e -- tests/e2e/backtest-workspace.spec.ts`: 7 browser tests passed, with console/request audits and accessibility checks.
- Run-history browser checks: retired URL parameters and cursor are removed; only `limit` is sent on the first list request; date controls and their disclosure are absent; stock-code/retention controls remain visible at widths 320, 768, 1024 and 1440 without page overflow. The 1440 × 900 screenshot was visually inspected.
- `git diff --check`: passed.

## Environment

The initial sandboxed suite hit file-access errors and a route-test timeout; the initial browser run could not access localhost. The complete unit suite was rerun outside the sandbox with 4 workers, and the browser suite was rerun outside the sandbox. Both passed without relaxing checks or changing test thresholds. Browser results use local fixtures and do not claim live-provider validation.
