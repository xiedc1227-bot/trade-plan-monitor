# Proposal: Complete the Backtest Workspace Interaction Flow

Status: Proposed for review; no implementation approval. Date: 2026-10-20. Baseline: `2be0a8b`. [Chinese review copy](PROPOSAL-backtest-workspace-ux.zh-CN.md).

## BW01. Objective and scope

Extend the recently delivered creation workflow and minimum result-to-cause review flow to the remaining backtest surfaces. Users should be able to find a run, understand whether work is progressing, distinguish unavailable reads from missing records, and navigate from data or plan evidence back to a result.

Inspect `/backtests`, `/backtests/data`, job states presented under `/backtests/:runId`, shared service controls, and the remaining audit/provenance/equity sections. Preserve the creation workflow in `SPEC-backtest-creation-ux.md` and the evidence contract in `SPEC-backtest-review.md`.

This document is a research-backed proposal and capability map. It does not modify application code, authorize a migration, or replace the existing specifications. P0/P1/P2 below describe this next round, not unfinished work in the previously accepted minimum scope.

## BW02. Inspection evidence and limits

### BW02.1 Browser observations

Read-only inspection used isolated Chrome at `http://127.0.0.1:8765`, viewport 1440 × 1000, on 2026-10-20:

- The run list returned HTTP 200 with 5 completed runs. Each visible row had the same symbol, interval and result timestamp; the long run ID was the main differentiator. Final equity and return displayed unavailable for all 5 rows. This alone does not establish whether each missing metric is expected or erroneous.
- The first row began around the bottom of the first viewport. Header, service strip, repeated navigation, research notice and the large filter form preceded the records.
- The historical-data page displayed no verified datasets, while the run list still contained those 5 runs. Code confirms that the page reads the verified-dataset catalog, not all stored history. Scheduled loop dataset readers explicitly do not rewrite the legacy market catalog. An empty catalog is not evidence that all historical data or results were deleted.
- Service management expanded normally and reported that history was readable. Its controls put refresh, pending-task lookup and stopping the service at a similar visual level.
- A result opened from the list did not show the result tabs within a 15-second wait window. A separate direct visit still showed the loading message after a 5-second observation. No page exception was observed; the summary response had not been observed at capture time. This is a delayed-read symptom, not a measured steady-state latency or a diagnosed backend cause.
- The initial run/data browser inspection recorded zero non-GET/HEAD requests and zero page exceptions. No run, data download, recovery, cancellation, retention change or cleanup was triggered.

The successful result subviews and active/failing job states were inspected in source and existing tests, not newly exercised against real jobs in this audit. This is not a full browser acceptance report or a usability study. The existing automated suite was not rerun for this proposal-only change.

### BW02.2 Source-supported findings

Paths are relative to the repository at the baseline above.

| ID | Evidence | User impact | Priority |
|---|---|---|---|
| BW-F01 | `web/src/components/backtests/BacktestRunTable.vue` uses 8 columns, a 72rem minimum table width and the full ID as the result link. | Similar runs are hard to distinguish; the useful action is hidden in an identifier. | P0 |
| BW-F02 | `BacktestRunFilters.vue` shows all main filters; `useBacktestRuns.ts` supports first/next but no previous-page action. Empty results use the same wording with and without filters. | Searching and undoing a search take unnecessary effort; pagination interrupts comparison. | P0 |
| BW-F03 | `BacktestDataView.vue` reads `GET /api/v1/backtest-datasets`; `DatasetCoveragePanel.vue` foregrounds hashes, Schema, 7 raw counts and blocker wording. | A technical catalog is presented as a general historical-data inventory. | P0 scope correction; P1 inventory |
| BW-F04 | `DatasetScopeForm.vue` uses text date fields; `DatasetCoveragePanel.vue` exposes next-page navigation without previous/first controls. | Date entry and returning to a previously viewed dataset are cumbersome. | P0 |
| BW-F05 | `BacktestRunDetailView.vue` has a plain loading message; `useBacktestResults.ts` and `api/transport.ts` do not provide a visible slow-read recovery flow. `useBacktestRuns.ts` clears the previous page before refresh. | Slow reads feel like stalled work or disappearing records. | P0 |
| BW-F06 | `BacktestJobStatus.vue` already has phase labels, progress, cancellation confirmation and stale-read notices, but prominent job IDs and raw diagnostic codes remain. `BacktestRunsView.vue` lists completed results only. | Active, failed and cancelled tasks lack a convenient history destination. | P1 |
| BW-F07 | `BacktestServiceState.vue` already collapses healthy controls and preserves explicit recovery; `useBacktestService.ts` reads at most 1 pending job. Stop is a peer action to refresh. | Rare management actions are too easy to confuse with routine navigation; a pending-task hint is not a task history. | P0 controls; P1 tasks |
| BW-F08 | `MonitorLoopTimeline.vue` renders one large card per event with full IDs. Existing exact cause links work, but global date/type/plan filters do not exist. | Finding a particular day's events remains laborious after cause lookup was added. | P1 |
| BW-F09 | `MonitorLoopSummary.vue` still mixes provenance, account, metrics, version calendar and rule changes. `ResultRuleChanges.vue` already loads comparison details on demand. | The plan/source tab remains long; users need to understand what changed before inspecting hashes. | P1 |
| BW-F10 | `BacktestEquityChart.vue` has three series without a legend toggle, zoom or selection contract; the exact-value table is always rendered below it. `openIndexDecisionDate(_tradeDate)` ignores the date and opens the first decision page. | Charts provide limited exploration; the index-date action implies more precise navigation than it performs. | P1 |
| BW-F11 | `BacktestResultActions.vue` hides export links for loop reports; retention text and technical export constraints are prominent. | Users cannot assume every result supports the same export, and may misread “retain” as merely bookmarking. | P1 presentation; P2 expanded export |

## BW03. Comparable projects and adaptations

Research date: 2026-10-20. These are verified interaction references; adaptations are recommendations, not claims that the implementations can be copied unchanged.

| Reference | Verified pattern | Adaptation |
|---|---|---|
| [FreqUI history source](https://github.com/freqtrade/frequi/blob/main/src/components/ftbot/BacktestHistoryLoad.vue), [raw source](https://raw.githubusercontent.com/freqtrade/frequi/main/src/components/ftbot/BacktestHistoryLoad.vue) | Compact history table, text filtering, range/context in a row, explicit load action and loaded-state distinction. | Put run identity and “View result” first. Keep our bounded server pagination; do not copy full-list client filtering. |
| [FreqUI background jobs](https://github.com/freqtrade/frequi/blob/main/src/components/ftbot/BackgroundJobTracking.vue), [raw source](https://raw.githubusercontent.com/freqtrade/frequi/main/src/components/ftbot/BackgroundJobTracking.vue) | Job status, errors, overall progress and named subtasks appear together. | One task card should explain the current phase and the next permitted action. Preserve our stronger uncertain-result and cancellation semantics. |
| [QuantConnect results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results#18-View-All-Backtests), [LEAN repository](https://github.com/QuantConnect/Lean) | Results list with filtering, pagination and sorting; results can be named. Result views expose statistics, charts, trades and logs; charts allow series toggling. | Readable result titles, clear task/result navigation and progressive chart detail. The reference UI is QuantConnect's platform, not a UI supplied by the open-source LEAN engine. |
| [Backtesting.py repository](https://github.com/kernc/backtesting.py), [plot documentation](https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html#backtesting.backtesting.Backtest.plot) | Interactive equity, returns, drawdown and trade plots, optional layers, bounded resampling. | Add useful time context and layer controls. Our fill records are not automatically round-trip trades; do not invent paired-trade PnL or fill-to-chart identities. |

Retain the existing dark graphite/amber visual language, exact money formatting, native accessible controls and evidence integrity. Adopt hierarchy and task flow, not another product's branding or market assumptions.

## BW04. Proposed capability map

These are workstream IDs within the existing backtest modules, not new services.

| Module ID | Responsibility | Depends on |
|---|---|---|
| `backtest-read-feedback` | Shared read states, slow-read feedback, safe refresh and service-action hierarchy. | Existing read/service contracts |
| `backtest-run-discovery` | Compact result history, filters, meaningful row summaries and return navigation. | `backtest-read-feedback` |
| `backtest-data-discovery` | Explain catalog scope, improve dataset browsing, then expose bounded coverage evidence. | `backtest-read-feedback` |
| `backtest-task-workspace` | Find active/terminal tasks, explain progress, open the correct task/result and recover explicitly. | `backtest-read-feedback` |
| `backtest-result-exploration` | Compact audit/provenance/equity views, precise time filtering and supported result actions. | `backtest-read-feedback` |

Recommended sequence: shared read feedback → run history + data scope → task workspace + data inventory → advanced result exploration. Comparison is an optional later extension of result exploration. Each workstream receives paired implementation specifications and tasks after this scope is accepted.

## BW05. P0 — Find records and understand read states

### BW05.1 Run history

Use a compact header with one primary “New backtest” action. Keep stock code and quick retention choice visible. Show active filter chips and “Clear filters”. Per the 2026-10-22 scope update, remove the backtest end-date bounds and “More filters” section. Retired `eventEndFrom`/`eventEndTo` URL conditions are cleared together with their cursor before reading page 1. Existing API date-filter support remains compatible.

Default row layout: **symbol + backtest interval | outcome summary | fill count | retention | View result**. Use a short run-ID suffix as a secondary differentiator; make the full ID available through details/copy. Add a stock name only when returned by an authoritative source. A symbol/date title is presentation-only; editable names and notes are deferred.

Select metrics according to funding mode and availability. Explain that `POSITION_LIMIT_ONLY` does not calculate capital return or net-worth drawdown. Distinguish that from invalid valuation, unavailable evidence and a failed read. Display legitimate available PnL/fees or counts; never turn missing values into zero. Normalize ratio presentation with explicit percent units and retain exact source values in details.

Provide previous/next/first navigation for visited cursors. Restore filters, page and row focus when returning from a result. A direct deep link with no known prior cursor must not fabricate a previous cursor. Distinguish an empty history from no matches. Label page-local counts as page-local; do not present them as global totals.

### BW05.2 Historical-data scope and browsing

Keep the route stable. Use navigation wording “Historical market data” and clearly label the current content as the **verified dataset catalog**. Explain that completed runs and plan histories are separate records, with direct navigation to them.

For the currently observed case, the empty-state meaning is: “No verified datasets are listed here. This does not mean previous backtests or plan records were deleted.” Offer “View run records” and “New backtest”. Do not claim that a particular missing period will definitely download successfully.

Use date controls and retain exact existing filter semantics: dataset start is on/after the lower bound and dataset end is on/before the upper bound. Explain that this is a catalog range filter, not a query proving coverage of a requested backtest interval. An eventual “covers my interval” query needs its own backend contract.

Dataset rows show symbol, labelled date range, verification time and backend-reported status. Expand for warmup dates, the 7 counts, schema, hashes and raw blocker codes. Add clear filters, retry and previous/next/first navigation. Keep error, no matches and empty catalog distinct.

### BW05.3 Read and service feedback

Use a shared vocabulary: loading, refreshing with previous data, delayed read, failed read, no matches, empty catalog/history, and expired/missing evidence. A successful service-status read does not guarantee that a specific result query has completed.

Proposed slow-read behavior: at 10 seconds, explain that reading is taking longer and retain a return link; at 30 seconds, allow retry with an aborted/superseded read and clear stale-response protection. This concerns read requests only: it never cancels or resubmits a backtest job. Verify the real delayed result separately before claiming a performance fix.

Preserve previous data during refresh of the same query and label its last successful read time. When filters change, do not display old rows as though they match the new filters. Keep a short research notice, and place technical protocol explanations in details/help.

Service status remains compact when healthy. When blocked, show impact, one recommended action and an expandable diagnostic section. Move stop into advanced management and explain its effect before confirmation. Preserve explicit selected-task recovery, revision checks and same-request retry for uncertain mutations. Repair does not automatically resume work.

## BW06. P1 — Task continuity and useful data evidence

### BW06.1 Task workspace

Within run history, add separate “Results” and “Tasks” views. Reuse `GET /api/v1/backtest-jobs` with bounded server filters for kind/status. Show running/pending work first in a compact section, and provide access to completed, failed and cancelled tasks. A job ID and a run ID remain distinct identities.

A task card answers: what it is doing, the current phase, last server update, and the next allowed action. Reuse existing phase and unit fields. For known totals show the actual fraction; for unknown totals show indeterminate activity, not invented percentages or ETA.

“View task” reads the accepted task. “View result” is available only when the response provides the matching run ID. A read failure offers a read retry; an uncertain cancellation offers retry of that same cancellation request; a cancelled/failed run does not offer a misleading automatic “Continue”. Preserve cancellation confirmation and the difference between requested and confirmed cancellation.

The existing automatic preparation chain is partly owned by the creation-page composable. Do not promise that closing/reloading the browser continues every preparation step. A durable cross-job journey and “copy settings to retry” require a validated stored intent/context contract; P1's minimum is reliable discovery and reopening of already accepted tasks.

### BW06.2 Data inventory

After correcting scope in P0, expose three clearly separated evidence categories as backend support becomes available: local market-data coverage, verified datasets, and frozen data referenced by completed runs. Show stock, date range, data kind and the recorded readiness/blocking reason before identifiers.

The current dataset catalog cannot establish all three categories. A new bounded read projection must carry explicit source identity, coverage scope, availability and related run references. Do not union intervals in the browser and call them complete. Do not issue one large report read per visible row. A historical frozen snapshot's validity and the current ability to start a new run are separate facts.

Replace raw blocker-only presentation with a known-code explanation and a concrete next step. Unknown codes retain a neutral explanation plus the original code. Browsing and filtering never start downloads; the existing explicit start flow still owns automatic data preparation.

## BW07. P1 — Complete result exploration

### BW07.1 Audit and time navigation

Replace large event cards with compact chronological rows: time, event type, one-line outcome, “Inspect”. Group or filter by date, event type and plan version only when the server provides those semantics across the entire run. Expand recorded payload/IDs on demand and reuse the existing cause panel.

Until a date-locator contract exists, rename the reference-index action to “Open decision records”, so it does not imply exact date targeting. With the contract, carry the selected date into a bounded query and focus the matching row. Do not filter only the loaded page while claiming run-wide results. Retain exact cause navigation across pages.

### BW07.2 Plans and provenance

Lead with a compact effective-date timeline. Selecting a version displays its rules and the available recorded comparison; technical IDs and hashes belong in “Evidence details”. Separate opening account, run assumptions and source evidence into disclosures. Reuse `ResultRuleChanges.vue`'s explicit read behavior; missing or failed comparison reads cannot be labelled “No changes”.

Keep the historical-availability assumption visible where it affects interpretation. Selecting a version changes the inspection context only, not the frozen run or the plans used in it.

### BW07.3 Equity and result actions

Offer a legend for equity/cash/market-value layers and a bounded time-range view. Place the exact-value table in an explicitly expandable section with an accessible keyboard path. Show a meaningful unavailable explanation for funding/valuation constraints instead of an empty chart.

Chart-to-fill/date linking is a subsequent bounded query/identity contract, not a visual-only change. Downsampled points remain display values and cannot replace exact evidence. Do not derive missing return/drawdown or per-trade PnL in the browser.

Place a compact retention action near the run identity and explain that retaining protects detail from routine expiry, rather than presenting it as a bookmark. Keep revision and uncertain-result safeguards. For formats that actually support exports, show them under “Export”; explain unsupported formats without offering a dead button. Expanded loop-report export is P2 and needs a real backend contract.

## BW08. P2 and explicit boundaries

Candidate later capabilities: user names/notes, copying run settings into an editable new-run draft, comparison of 2–3 runs, and supported loop-result exports.

Comparison must expose differences in symbol, interval, plan versions, funding mode, response policy, fees and frozen data before interpreting metric changes. It must not rank incomparable or unavailable returns. Copying settings never runs automatically and must preserve the provenance of the copied draft.

Keep these out of the first delivery: optimizer parameter sweeps, browser-invented financial attribution, forced historical backfills, historical-data deletion, and a broad layout rewrite of the newly accepted creation page.

## BW09. Delivery slices and proposed acceptance

| Slice | Scope | Backend dependency | Acceptance |
|---|---|---|---|
| BW-S01 / P0 | Read feedback, compact run list, filters/navigation, data scope/copy, service action hierarchy | Existing read contracts; profile delayed reads separately | The observed 5-run/empty-catalog case cannot imply deletion. Matching-query refresh preserves labelled previous data. List/result return restores context. |
| BW-S02 / P1 | Task list and readable progress; compact verified-dataset presentation | Existing job/dataset APIs; no full preparation-chain resume promise | Accepted tasks are discoverable; reading/reopening sends no execution command; unknown progress and cancellation remain truthful. |
| BW-S03 / P1 | Coverage inventory, global audit filters and exact date location | New bounded read projections/contracts with tests and generated types | Queries find records beyond page 1; all sources and availability states remain explicit; no unbounded scans or per-row report hydration. |
| BW-S04 / P1 | Provenance timeline, equity controls and supported result actions | Existing data for presentation; explicit contract for linked selection | Version inspection and chart controls do not mutate evidence; missing values and unsupported export remain clear. |
| BW-S05 / P2 | Names, draft reuse, comparable-run review and expanded exports | New metadata/copy/export contracts as applicable | No implicit run creation or misleading comparison. |

Proposed verification after implementation:

- Fixtures with at least 30 runs and 30 datasets exercise pagination, filters, no matches, stale cursors and return focus. Keep finite response and page-cache bounds.
- Check request failure, slow response, service degradation, empty success, expired evidence and partially available metrics separately. Old-query responses never overwrite a newer selection.
- Cover running, failed, cancelled, uncertain cancellation and recovered-task states. Read-only navigation must issue zero business mutation requests. Real cancellation/recovery tests use isolated fixtures.
- At 1440 × 900 with no active task/error banner, the first run row is visible without scrolling. At widths 320, 768, 1024 and 1440 and 200% text, primary controls and summaries do not cause page-level horizontal overflow; any exact-data table has an explicitly labelled scroll region.
- Keyboard access, visible focus, announced status changes, and at least 44px primary control targets are required. Preserve text meaning independently of colour.
- Run relevant unit/integration/browser tests, type checking and build. Update paired specifications, tasks and verification reports in the same implementation change.

## BW10. Recommendation and open decisions

Implement BW-S01 first, followed by BW-S02. These address the most visible friction using existing interfaces and establish a complete path from finding a record to seeing work status. Introduce BW-S03's new read capabilities before promising global coverage or date filtering. BW-S04 can then finish the secondary result views; BW-S05 remains optional.

Recommended scope for the next implementation approval: **P0 plus the existing-API portion of P1**, preserving current creation and cause-lookup behavior. Persistent names, global statistics, full preparation-chain continuation and comparison remain separate decisions. No open question prevents reviewing this proposal.
