# Backtest workspace interaction contract

Status: Approved implementation scope by user instruction on 2026-10-21. Baseline: `2be0a8b`. [Chinese review copy](SPEC-backtest-workspace-ux.zh-CN.md). Design: [proposal](PROPOSAL-backtest-workspace-ux.md). Tasks: [implementation](../../../tasks/backtest-workspace-ux.md).

## BW-C01. Scope

Deliver all P0 and the existing-interface portion of P1 from the proposal: run discovery, verified-dataset browsing, accepted-task discovery, service action hierarchy, compact audit/provenance views, equity controls and supported result actions. Diagnose and correct the measured result-read bottleneck without weakening integrity validation.

Existing routes and mutation semantics remain authoritative. Defer global coverage inventory, new run-wide audit/date filters, chart-to-fill linkage, editable names, draft copying, comparison and additional exports. No historical backfill, deletion or provider download is part of browsing.

## BW-C02. Component boundaries

| Owner | Responsibility and interface |
|---|---|
| `BacktestRunsView.vue` | Compose result/task navigation, filters and tables; route query owns selected view and accepted task. |
| `BacktestRunFilters.vue`, `BacktestRunTable.vue` | Emit filter/pagination/refresh actions; show readable identity, available metrics and explicit result links. |
| `useBacktestRuns.ts`, `useBacktestData.ts` | Bounded reads, visited cursor history, query identity, previous-data refresh and stale response rejection. |
| `useBacktestTasks.ts`, `BacktestTaskWorkspace.vue` | Read existing `listJobs/getJob`, bounded status/kind selection and accepted-task status. Reuse cancellation behavior. |
| `useBacktestReadFeedback.ts`, `BacktestReadFeedback.vue` | Shared delayed/timeout feedback with request cancellation, cleanup and retry events; no business commands. |
| `DatasetScopeForm.vue`, `DatasetCoveragePanel.vue` | Catalog-only scope, native dates, labelled rows, expandable technical evidence and navigation events. |
| `BacktestServiceState.vue` | Primary repair/read actions, advanced stop confirmation and explicit selected-task recovery. |
| `MonitorLoopTimeline.vue`, `MonitorLoopSummary.vue` | Compact recorded-event rows and selectable effective-version evidence without changing frozen plans. |
| `BacktestEquityChart.vue`, `BacktestResultActions.vue` | Layer/range controls and real supported actions; precise table remains keyboard accessible. |
| `BacktestResultStore`, publication readers | Measure duplicated input/report/event work; preserve typed, content-hash, event-set and retention validation. |

## BW-C03. Read contract

At 10 seconds show delayed-read feedback. At 30 seconds end/supersede that read and allow retry, retaining stale-response protection. Unmount/query change clears timers and aborts obsolete reads. This never cancels or submits a job. Same-query refresh retains labelled previous data and last-success time; new filters clear mismatched rows. Failed refresh must not present retained data as current success.

Keep empty history, empty catalog, no matches, failed reads, missing and expired evidence distinct. Service readability and result readability are separate facts. No global totals or server completion times may be invented from a page or evidence cutoff.

## BW-C04. Run and data discovery

Use compact headers/filters. Main run rows contain symbol, event interval, short identity, available result metrics, fills, retention and explicit result action. Full IDs remain available in disclosures. Ratios use explicit percentage units without binary float money calculations. Missing metrics stay unavailable with an explanation when the response supports it.

Date filters preserve their API meaning. Run dates filter the backtest end date. Dataset dates filter catalog start/end bounds, not overlap or complete coverage. Native date controls, clear filters and active-condition summaries are required. Known visited cursors support previous/first/next navigation with finite history capped at 30 entries; unknown predecessors are not fabricated. Return from a result restores URL filters/page and selected-row focus.

Historical-market-data copy explicitly identifies the verified catalog. Empty catalog cannot imply deleted results/plans; navigation to those records remains available. Dataset rows show symbols, labelled interval and verification state/time; warmup, all 7 counts, hashes, schema and raw blockers are expandable. Known blockers have an actionable explanation and unknown codes remain inspectable.

## BW-C05. Task and service contract

Results/tasks are distinct views under `/backtests`. Task queries use existing bounded `GET /api/v1/backtest-jobs` with status/kind and cursor; a selected task is opened by `jobId`. Display pending/running and terminal states without pretending a task ID is a run ID. Result links require the task's matching non-null run ID and completed state. Reads never resume tasks or create new jobs.

Show phase, actual units, last server update and allowed actions. Unknown totals have no invented percentage/ETA. Reuse cancellation confirmation, requested-versus-confirmed cancellation and same-request uncertain retries. Reopening accepted data/run tasks does not promise continuation of the browser-owned preparation chain. Service stop belongs in advanced controls with explicit confirmation; repair never implicitly resumes a task.

## BW-C06. Existing-data result exploration

Audit events use compact rows with on-demand recorded payload/identity and existing exact cause links. The reference-index action says it opens decision records until exact date querying is supported.

Provenance leads with effective-version selection and existing on-demand rule comparison. Account, assumptions, metrics and technical source identity are disclosures. Missing/failed comparison cannot mean no changes. Keep the historical availability assumption visible.

Equity offers legend toggles and bounded zoom over the existing maximum 2,000 returned display points. Exact values remain in an expandable native table. Funding/valuation restrictions are explained. No new return/drawdown, paired-trade PnL or time/fill identity is inferred. Retention explains protection from routine detail expiry; exports appear only for formats actually supported by the backend.

## BW-C07. Performance and integrity

Record separate API/body/browser and store-projection measurements on the same completed run. Current observations include about 9.6/4.7 seconds for the detail API and a profiled store read about 9.3 seconds; profiler overhead means these are not directly comparable timings.

Optimize verified duplicate work rather than skipping validation or caching mutable availability. Result values must still reflect retention/pin revisions and reject tampered artifacts/events. Any cache must be bounded, bind all evidence identities and invalidate on backing-state changes; prefer a single verified traversal when it removes repeated work. Verify before/after using identical inputs and report remaining cold-read costs honestly.

## BW-C08. Verification and commands

Run from `web/`: `npm run test -- --run`, `npm run type-check`, `npm run build`, and focused `npm run test:e2e -- tests/e2e/backtest-workspace.spec.ts`. Run backend checks from the project root with `.venv/Scripts/python.exe -m pytest` and targeted result/publication/retention tests; use `.venv/Scripts/python.exe -m ruff check` on changed Python files.

Cover 30-record pagination fixtures, delayed reads/timeouts, query races, failed refresh with retained data, no-match/empty catalog, task identities and cancellation. Browser checks include keyboard/filter/return/pagination/version/chart/disclosure interactions, zero business writes during real-history inspection, no page exceptions, and accessible primary controls at least 44px. At 1440 × 900 with no active task/error banner, the first run is visible without scrolling. Verify widths 320, 768, 1024, 1440 and 200% text with no page-level overflow. Record paired verification reports and keep pre-existing changes.
