# Result profit summary — 2026-10-18

## PS-V01 — Behavior and scope

The result page now begins its loaded-result area with total PnL, realized PnL, floating PnL and the resolved backtest cutoff date. It remains above result actions/tabs and per-plan diagnostics on every tab. `BacktestProfitSummary.vue` is a presentation component; `BacktestRunDetailView.vue` supplies the existing result. No API call, report schema/hash, replay, AI extraction or stored result changes were introduced.

Loop values use `cost_pnl_fen`, `realized_pnl_fen` and `unrealized_pnl_fen` directly. A missing initial capital value does not hide known cost PnL. Null displays `暂不可用`, zero displays `0.00 元`, and positive/negative values carry signs. The resolved `eventEnd` is independent of completion date; the loop's Shanghai `evidence_cutoff` is also shown. The panel contains no principal return percentage. Classic legacy PnL is summed using exact integer fen; old research reports without PnL fields remain unavailable. Fees already included in cost are not deducted twice.

## PS-V02 — Automated checks

The new component tests initially failed because the component did not exist. Focused component/result-page tests then passed: **69 tests** across three suites. Cases cover signed values, zero with `POSITION_LIMIT_ONLY` and invalid capital valuation, partial unknown values, changed run props, legacy large-integer precision, old research compatibility, cutoff versus completion date, top placement and no extra summary request when switching tabs.

An earlier test assumed the first `<time>` on the entire page was the job completion time. It now explicitly checks both the original completion time and the new replay cutoff date. No assertion was removed. Final frontend suite: **71 files, 1079 tests passed**. Type checking, production build and targeted whitespace checks passed. Existing isolated-test router warnings remain in the test log. No backend code or contract changed, so no historical replay or unrelated capacity suite was repeated.

## PS-V03 — Actual browser verification

The built assets were loaded by the existing local service at port `8765`. Opened the actual four-source run `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2` at `/backtests/{run_id}?tab=summary`. It displayed total, realized and floating PnL each as **0.00 yuan**, cutoff **2026-10-09**, and Shanghai evidence cutoff **2026-10-09 23:59:59**. Its zero-fill outcome remains unchanged; the cutoff is not the October 18 publication date.

At viewport 1440 × 1000 the four cards occupied four columns. At 390 × 844 they stacked in one column, with all four values readable and no horizontal document overflow. Page error/warning logs were empty; the browser host's unrelated Statsig notice is not an application log. The temporary viewport override was reset, and the result tab was retained for review.

Local evidence: `data/verification/2026-10-18-result-profit-summary/desktop.jpg`, `narrow.jpg`, `narrow-cutoff.jpg` and `page.txt`. Test/build logs remain under `data/verification/2026-10-18-cohort-risk/profit-summary-tests.log` and `profit-summary-build.log`. README, operations ML-O20 and task PS-01/PS-02 were updated in matching English/Chinese versions.
