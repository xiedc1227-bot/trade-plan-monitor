# Backtest creation UX verification — 2026-10-20

## BC-V01 Scope

Contract: [SPEC-backtest-creation-ux](../specifications/backtesting/SPEC-backtest-creation-ux.md). The implementation preserves the workbench default and existing preparation, review and submission rules. It adds metadata search, compact timeline rows, explicit new/update workspaces, selected-path navigation and focus, and compact run settings with collapsed effective-date details. Existing result-review and cost-default changes are retained.

## BC-V02 Automated checks

- `npm run test -- --run`: 80 files, 1192 tests passed. After the final account-summary layout adjustment, 113 relevant tests in `MonitorLoopRunForm.spec.ts`, `BacktestAccessibility.spec.ts`, `BacktestServiceState.spec.ts` and `PlanPreparationReview.spec.ts` passed again.
- `npm run type-check` and `npm run build`: passed. The packaged local web distribution was updated.
- `npm run test:e2e -- tests/e2e/plan-library-versions.spec.ts tests/e2e/monitor-loop-backtest.spec.ts`: 9 distinct Chrome journeys verified across the full run and targeted rerun. The full run passed 7 journeys; a stale assertion for the visible locked cancellation source and a missing fixture document title were corrected. The targeted rerun passed all 6 selected journeys, including both corrected cases.
- Coverage: search/clear/locate by keyboard; 30 timelines paged without changing selected identity; 8 records retained in 2 independent chains; failed-read retry and stale results; explicit preparation entry/close and dirty-draft locks; upload/edit/review/run; cancellation and resumed unfinished work; automatic data completion; 4 continuous reviewed updates and one account/run; required date confirmation before extraction; historical read-only inspection.
- `git diff --check`: passed. Bilingual section/task IDs, inline technical values and checklist state were checked for parity.

## BC-V03 Real-page browser evidence

Fresh isolated Chrome contexts opened `http://127.0.0.1:8765/backtests/new`. The page loaded 2 timelines and 8 reviewed plans. Initial timeline mode had no unused source form. Selecting an endpoint focused the run-settings region; updating focused the source heading; closing an untouched workspace returned focus to new-timeline creation.

Both the library and final settings page were checked at 320/768/1024/1440px with 200% text. In each case document width equaled viewport width. Axe checks for `wcag2a`, `wcag2aa`, `wcag21aa` returned no violations. Browser runtime evaluation was used for the real-page axe audit without changing its CSP.

Effective-date details started collapsed and expanded by keyboard to 4 entries. Commission and end-date drafts remained editable. The real-page sessions recorded no non-GET/HEAD requests and no page errors; no original, preparation or run was submitted. Creation and replay mutation tests used isolated fixture storage.

Screenshots:

- [Timeline selection](C:/Users/xiedc/.codex/visualizations/2026/10/20/01a15810-0738-7f02-b3b1-8100372be616/backtest-creation-updated.png)
- [Run settings](C:/Users/xiedc/.codex/visualizations/2026/10/20/01a15810-0738-7f02-b3b1-8100372be616/backtest-creation-settings.png)

## BC-V04 Limits

This is UI and local-browser acceptance. It does not certify live AI/market providers or manual screen-reader use. Real-history evidence establishes that the currently loaded reviewed records remain readable; it is not a forensic reconstruction of every historical record. No backend or database migration was introduced in this creation-page change.
