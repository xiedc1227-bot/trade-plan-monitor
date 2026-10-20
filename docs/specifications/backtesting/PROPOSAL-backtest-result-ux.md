# Proposal: Make Backtest Results Easier to Read and Explain

Status: Proposed design, not an implementation approval. Date: 2026-10-20. Code baseline: `6fc98f1`. [Chinese review copy](PROPOSAL-backtest-result-ux.zh-CN.md).

## UX01. Objective and scope

The user identified the main problem as **results being difficult to read, with trades and their causes difficult to locate**. Prioritize reviewing a completed run: understand its outcome, select a trade or a non-trade, and inspect the recorded evidence without manually searching event IDs.

Keep the existing `backtest-web` → `backtest-api` → `backtest-results` boundaries. This proposal changes presentation and proposes bounded read interfaces; it does not change `backtest-engine` decisions. Configuration simplification and run comparison are secondary.

Deliver a results workspace organized around questions:

1. What happened during this run?
2. Why did this transaction execute?
3. Why did this condition or reminder not lead to a transaction?
4. Which plan and historical evidence produced that outcome?

The findings below come from source inspection, existing contracts and tests. They are not measurements from a usability study or a live-data browser acceptance run.

## UX02. Current friction supported by code

Paths and line numbers refer to the baseline above, relative to the project root.

| ID | Evidence | User consequence | Priority |
|---|---|---|---|
| UX-F01 | `web/src/components/backtests/BacktestFillTable.vue:53` renders 16 columns, including nature, full ID, separate fees and cash movement. It declares no selection event. | Scanning a trade requires horizontal movement; there is no path from the row to its reason. | P0 |
| UX-F02 | `web/src/components/backtests/MonitorLoopTimeline.vue:13` displays current-page events, warns that a cause may be on a previous page, and prints `cause_event_id` as text. | The causal relationship exists but users must reconstruct it manually. | P1 |
| UX-F03 | `web/src/components/backtests/PlanExecutionDiagnostics.vue:45` already shows requirement versus actual evidence. The example's `sequence` is only in a disclosure at line 55. | Useful explanations are separated from the underlying record; representative samples cannot be followed directly. | P0 + P1 |
| UX-F04 | `web/src/views/BacktestRunDetailView.vue:495` puts profit, result operations and technical explanatory text before the resource tabs. `MonitorLoopSummary.vue:41` mixes provenance, account, diagnostics, rule changes, metrics and version history. | Reading results means navigating implementation concepts and a long mixed-purpose summary. | P0 |
| UX-F05 | `BacktestFillTable.vue:13` projects loop receipts into the legacy row shape, drops `eventId`, and sets `realizedPnlFen` and `cashDeltaFen` to `null`. | A populated run-level PnL does not imply usable per-trade PnL or attribution in the table. Do not promise a loss-ranked trade list as a presentation-only change. | P1 |
| UX-F06 | `src/trade_plan_monitor/web/routers/backtest_results.py:88` accepts only `limit,cursor` for fills and `kind,limit,cursor` for details. `useBacktestResults.ts:43` requests at most 100 rows. | Date, plan and reason filtering across the run cannot be implemented by filtering the loaded page. | P1 |
| UX-F07 | `BacktestRunDetailView.vue:227` receives `_tradeDate` from the reference-index panel but navigates only to the first decision page. Lines 780 onward offer first/next page links. | Clicking a date does not locate that day's decision; there is no explicit previous-page control. | P1 |
| UX-F08 | `MonitorLoopSummary.vue:26` lists equity, return and drawdown even when funding is `POSITION_LIMIT_ONLY`; line 40 explains that these are not calculated. `BacktestRunTable.vue:92` still emphasizes final equity and return. | A normal run presents several unavailable values where the user expects useful results. | P0 |

Retain the existing strengths: exact money formatting, URL-selected result tabs, cancellation of stale reads, explicit unavailable/expired states, frozen evidence, native tables, and separate run/job identities. This is a reorganization of an existing evidence system.

## UX03. References and what to adopt

Research date: 2026-10-20. References establish interaction patterns; the adaptation column is a design recommendation for this project.

| Reference | Verified pattern | Adaptation and limits |
|---|---|---|
| [FreqUI repository](https://github.com/freqtrade/frequi), [official UI documentation](https://www.freqtrade.io/en/latest/freq-ui/#backtesting) | Separate historical results, run, analysis and visualization views. The documented UI supports loading and comparing previous results. | Separate creating a run from reviewing one. Do not copy the number of tabs or cryptocurrency execution assumptions. |
| [FreqUI BacktestResultChart.vue](https://github.com/freqtrade/frequi/blob/bbb7824b8bf586f396b3dff82983efcd04c0c884/src/components/ftbot/BacktestResultChart.vue), [BacktestResultAnalysis.vue](https://github.com/freqtrade/frequi/blob/bbb7824b8bf586f396b3dff82983efcd04c0c884/src/components/ftbot/BacktestResultAnalysis.vue) | `navigateChartToTrade` selects the trade's opening/closing timestamps; `TradeListNav` emits selection. Analysis includes a filterable single-trade list. | One selected record should drive a shared time range and evidence panel. Our fills are not automatically round-trip trades, so do not invent entry/exit pairing. |
| [Backtesting.py repository](https://github.com/kernc/backtesting.py), [plot documentation](https://kernc.github.io/backtesting.py/doc/backtesting/backtesting.html#backtesting.backtesting.Backtest.plot) | Interactive plots can show trades, PnL, volume and optional drawdown, with bounded resampling. | Bring time context closer to the selected transaction. Preserve exact records separately from downsampled display points. |
| [QuantConnect LEAN repository](https://github.com/QuantConnect/Lean), [QuantConnect results documentation](https://www.quantconnect.com/docs/v2/local-platform/backtesting/results) | Results organize statistics, charts, trades and logs; a trade expands to its fills, and charts share zoom changes. | Use overview → transaction → evidence drill-down. The documented platform UI is a product reference, not a claim that LEAN includes that complete UI. |

The official FreqUI backtest and trade-panel screenshots were visually inspected. They illustrate dense controls and chart/table proximity, not runtime verification of its current source revision. QuantConnect and Backtesting.py behavior above was checked against official documentation; no installed instance was exercised.

## UX04. Proposed information architecture

Keep `/backtests` for history, `/backtests/new` for creation and `/backtests/:runId` for results. Make the result page's human-readable title the symbol plus the study interval; shorten the run ID visually and retain its full copyable value under provenance.

| Main area | Primary question | Default content |
|---|---|---|
| Overview | What happened? | Applicable financial facts, fill count, unfilled-intent count, final holdings, plan-level exceptions and links into review |
| Trade review | Why did this execute or fail to execute? | Compact rows, time/plan filters, selected-record evidence, costs and inventory changes |
| Non-trade reasons | Why was there no trade? | Existing per-plan diagnostics, response mode, requirement versus actual evidence, links to exact records |
| Plans and provenance | What rules and data were used? | Frozen plan versions, rule changes, run settings, evidence boundary and copyable audit identities |

Retain a secondary “Audit events” view for the complete recorded sequence. Retain reference-index and equity views where their schema and availability support them. Existing `tab=summary|fills|details|equity|market-index` links remain readable; new presentation routes must not reinterpret their historical meaning.

Desktop layout: compact header and metrics → navigation → review list on the left and selected evidence on the right. The evidence panel should use approximately 40% of the available review width, with a readable minimum. Below 1024px, put evidence below the selected list; below 768px, use stacked record summaries. Use route navigation for a focused mobile detail view where needed, with Back restoring filters and selection.

The conversation's interactive illustration demonstrates record selection and two reason states with explicitly synthetic data. It is not a screenshot of implemented product functionality.

## UX05. Reading the overview

### UX05.1 Financial facts

- Preserve `BacktestProfitSummary`: total cost-basis PnL, realized PnL and unrealized PnL. Add fees and fill count as compact supporting facts; avoid repeating the same amounts in a long definition list.
- For `POSITION_LIMIT_ONLY`, prioritize PnL amounts, fees, inventory and execution facts. Replace inapplicable equity/return/drawdown tiles with a concise funding-mode explanation. Do not manufacture a starting capital, return, Sharpe ratio or benchmark excess return.
- For historical `KNOWN` funding, retain equity and existing server-calculated ratios when valid. Format ratios as readable percentages without changing the canonical value. `UNKNOWN`, incomplete valuation and missing opening costs remain explicitly unknown.
- `null` means unavailable, not zero. Fees already included in PnL must not be subtracted again. A cumulative account PnL must not be labeled as one trade's PnL.
- Show both the requested study interval and the actual `evidence_cutoff` in Asia/Shanghai. Keep missing-evidence implications next to the affected result.

### UX05.2 Actionable exceptions

Show concise links such as “View executions that were blocked” or “Review plans with incomplete evidence”. Before full-run query support exists, label a link as opening a **representative plan example**, not the full set of matching events.

Do not render an execution funnel from incomparable counts: `evaluations`, conditions, reminders, intents, attempts and fills have different units. An intent may be attempted multiple times; `unfilled_intents` is not a count of `BLOCKED` attempts.

## UX06. Trade review and causal explanation

### UX06.1 Compact records

Default desktop columns: time, direction, quantity, fill price, fees, result, “View reason”. Keep full IDs, individual fee components, released cost, lot allocations and cash details in the selected panel. A phase P0 implementation can open existing receipt facts immediately; it must label unavailable causal details honestly.

Phase P1 adds run-wide date, plan version and execution-status filtering. Keep fills distinct from execution attempts: allow a switch between “Completed fills” and “Execution attempts”; a blocked attempt is not a trade. Show exact quantities and status text, not color alone.

Only offer per-trade PnL sorting after the server provides a verified per-fill accounting projection. A buy can be “Not applicable”, a sale with unknown opening cost can be “Unknown”. Do not derive sale PnL from two arbitrary adjacent pages or match buys and sells FIFO in the browser.

### UX06.2 Selected evidence

Selecting a row opens one evidence panel while preserving list context:

1. **Outcome sentence:** concise explanation assembled from recorded structured facts.
2. **Plan requirement and actual evidence:** version, rule, operator, threshold, observed value, timestamp, data frequency and price basis when recorded.
3. **Causal path:** plan context → evaluation → reminder → request → execution → resulting inventory/account state. Use actual `cause_event_id` edges and explicit version/authority bindings; plan context is not an invented causal edge.
4. **Execution limits:** full-quantity authorization, sellability/T+1, maximum holdings, response mode, response delay and recorded block reason.
5. **Accounting:** price, quantities, fees, released cost and before/after holdings when authoritative snapshots exist.
6. **Audit disclosure:** complete IDs, raw enum/reason code, exact values and source references.

Examples of wording, not findings about a real run:

- “Buy condition met; 100 shares were simulated after the selected response delay.”
- “The requested lot had 0 sellable shares; this sell attempt did not fill.”
- “The required historical window is incomplete; the condition cannot be classified as met or unmet.”

Do not generate fresh AI narratives as the default explanation. Use deterministic display mappings plus evidence; unknown codes retain their original text. Recorded failures must not be presented as automatically repairable by changing a plan.

### UX06.3 Navigation

Use persistent selection URLs, for example proposed `/backtests/:runId?tab=trades&fillId=...` and `/backtests/:runId?tab=reasons&versionId=...&sequence=...`. Validate identity and incompatible query combinations; keep filters when opening and closing a record.

Back/Forward restores selection and filters. Add explicit previous-page navigation using visited cursor history without manufacturing unsigned cursors. A direct deep link can show “Back to first page” when no previous-page history exists.

A cross-page cause opens by identity, not by downloading every preceding page. Changing run or selection aborts outdated reads and clears the old evidence. When a reference-index date is selected, preserve that date in the result query and apply it server-side.

## UX07. Explain non-trades without false certainty

Promote `PlanExecutionDiagnostics` into an independent, visible area. Each plan shows its effective date, fill count when available, response policy and the existing categories:

| Existing category | User-facing meaning |
|---|---|
| `MARKET_UNMET` | Market condition not met |
| `QUALITATIVE_UNRESOLVED` | Qualitative condition not quantified or verified |
| `PROCESSING_ERROR` | Recorded extraction or validation problem |
| `DATA_UNAVAILABLE` | Market evidence missing |
| `EXECUTION_BLOCKED` | Execution or response restriction |
| `NO_BUY_RULE` | No direct buy authorization |
| `NO_EVALUATION` | No usable evaluation |
| `CONDITION_MET` | Condition met; inspect subsequent execution |

`LoopDiagnosticExample` already supplies `sequence`, `requirement`, `actual`, `root_outcome` and `reason`. Phase P0 surfaces these well; phase P1 makes the example link directly to its context.

Current diagnostics contain at most 8 examples per plan and 256 examples overall. `sampled` must remain visible. Do not turn sampled examples into reason totals, percentages or rankings. Existing evaluation counts include repeated evaluations; they are not counts of independent trading opportunities.

`OBSERVE_ONLY` should prominently explain that no simulated response was requested. `NO_BUY_RULE` does not imply that a plan has no sell/risk-exit behavior. A satisfied alternative in an `ANY` condition must not turn unused branches into blocking reasons. Preserve server `root_outcome` instead of recalculating the condition tree in the UI.

## UX08. Data readiness and proposed read interfaces

### UX08.1 What can be reused

| Need | Existing support | Remaining work |
|---|---|---|
| Run overview | Metrics, `report.cycle`, final inventory and boundary | Presentation and funding-mode applicability |
| Trade basic facts | `BacktestLoopFillView.eventId`, receipt settlement, account and inventory | Preserve identity in the display model; compact row and receipt panel |
| Representative explanations | `planDiagnostics` and example `sequence` | Selection and exact lookup |
| Event relationships | `event_id`, `cause_event_id`; scheduled `version_id`, `authority_id` | Indexed, bounded lookup of causes and effects |
| Search/filter across run | Existing bounded signed pagination, but no relevant filters | New public query contract and read indexes |
| Per-trade PnL | Settlement, released cost and cumulative account PnL | Server accounting projection with availability and correct buy/sell semantics |
| Charts linked to trades | Existing equity chart has axis tooltip but no selection or zoom contract | Shared selection, bounded time series, and verified marker identities |

### UX08.2 Candidate interfaces

These endpoints and fields are **proposed**, not available APIs. Freeze the concrete contracts in paired `SPEC-backtest-api` / `SPEC-backtest-results` updates before implementation and regenerate client types.

| Candidate read | Purpose and constraints |
|---|---|
| `GET /api/v1/backtest-runs/{run_id}/review-events` | `startOn`, `endOn`, `versionId`, `eventKind`, `executionStatus`, `reasonCategory`, `limit`, `cursor`. Single values; reject unknown, duplicate or incompatible filters. `executionStatus` applies only to `EXECUTED`. Use server-defined category semantics. |
| `GET /api/v1/backtest-runs/{run_id}/review-context` | Exactly one selector: `fillId`, `eventId` or `sequence`; plus `limit,cursor`. Return the selected record, verified cause/effect records, frozen plan context and explicit missing links. |
| `GET /api/v1/backtest-runs/{run_id}/review-series` | Phase P2 only: requested interval and supported series identifier; bounded chart points and stable event references. Publish series applicability, source frequency, price basis and availability. |

Proposed limits: list/context default 20 records, maximum 100; chart maximum 2,000 points; each response remains below the existing 4 MiB result-page boundary. Paginate large causal neighborhoods and indicate omitted/missing relations. Cursor identity binds the run, normalized filters or selector, stable order and snapshot/high-watermark.

For new reads, separate `availability` (`AVAILABLE`, `EXPIRED`, `NOT_RECORDED`) from lookup completeness (`COMPLETE`, `PARTIAL`) and projection readiness (`READY`, `NOT_READY`). These are proposed fields, not replacements for existing schemas. A missing identity in an otherwise available result is a lookup failure, not “zero trades”. Preserve a long-lived fill even when its expiring cause details are gone.

Read only verified, published artifacts. No GET may start a job, call a provider, perform AI extraction, replay decisions, reconstruct pruned evidence or build a full-run index on demand.

Use a derived read index for identities, sequence, timestamp, plan, event kind and causal edges if existing indexes cannot serve the queries. Construct it during publication or an explicit, bounded maintenance operation over retained verified records. Link to existing content hashes; do not rewrite canonical event payloads, result hashes or historical results. Old runs whose index is absent remain accessible through existing views and show the lookup limitation.

### UX08.3 Chart boundaries

For `POSITION_LIMIT_ONLY`, chart recorded cumulative PnL amounts and holdings only when an appropriate frozen series exists. A run-level total is insufficient to synthesize a daily curve. An initial P0 screen may omit the chart.

Price candles, buy/sell markers and changing rule levels are phase P2. They require a bounded view over the exact frozen run dataset with matching price basis and frequency; do not fetch today's adjusted series or overlay daily and five-minute values without labels. Downsampling affects display only, never exact tables or event lookup. Keep gaps visible and do not interpolate missing evidence.

## UX09. Components and interaction states

Keep Vue 3 Composition API, `<script setup lang="ts">`, existing tokens and ECharts. No new framework or chart dependency is needed.

| Proposed boundary | Responsibility / contract |
|---|---|
| `BacktestRunDetailView.vue` | Route composition, identity and job/result gate; retain existing canonical URL/error handling |
| `BacktestOverview.vue` | Read-only run facts and applicable metrics; emits a typed review target |
| `BacktestTradeList.vue` | Rows, active filters and selected identity; emits select/filter/page actions |
| `BacktestEvidencePanel.vue` | Recorded requirement, evidence, result and relationships; emits select-related/close |
| `BacktestReasonExplorer.vue` | Existing diagnostics by plan; emits version/sequence target |
| `BacktestProvenance.vue` | Frozen settings, plans and full audit identities |
| `useBacktestReview.ts` | URL-derived selection, bounded reads, cancellation and independent request states |
| `backtestReviewPresentation.ts` | Pure display adapters and reason labels; never trading or accounting rules |

Existing `BacktestProfitSummary`, `ResultRuleChanges`, `PlanExecutionDiagnostics`, table formatting and result operations can be reused. Avoid a second copy of server state in Pinia; keep shareable filters in the URL.

A concurrent workspace change adds `BacktestCostSummary.vue` for frozen cost settings. Integrate that component once finalized instead of duplicating its display. It does not supply the missing cross-page navigation.

| State | Required behavior |
|---|---|
| Loading | Keep run identity; skeleton only in the region being read |
| Zero fills | Explain the chosen response mode and available diagnostics; do not report a guessed cause |
| Filter has no matches | State the active range/filter and offer clear-filter action |
| Partial / expired evidence | Keep verified fill facts; label unavailable causal segments without reconstructing them |
| Unknown cost or valuation | Display unavailable amount and recorded reason; never show zero |
| Read failure | Retry that read; never submit a new backtest |
| Running / failed / cancelled job | Preserve `useBacktestJob` and current publication gate; do not present incomplete data as final results |
| Old schema or index absent | Preserve compatible historical view and explain which drill-down is unavailable |

Use the existing ink/mineral/amber design tokens and tabular numbers. Keep one short research-context label and move engineering details such as “materialized” and “canonical hash” into provenance. Preserve essential uncertainty beside the value it qualifies.

Keyboard selection, clear focus, 44px touch targets, Escape/Back behavior and focus return are required. At 320, 768, 1024 and 1440px there must be no page-level horizontal overflow; technical tables may scroll locally. Changing selection must not move focus unexpectedly or reset list scroll.

## UX10. Recommended delivery order

These are proposed slices, not completed implementation tasks or changes to the active project task list.

| Slice | Deliverable | Dependency / exit condition |
|---|---|---|
| P0 Readability | Mode-aware overview, fewer default trade columns, receipt details, prominent per-plan explanations, collapsed provenance and clearer labels | Existing reads suffice. Clearly label representative/page-only scope; do not advertise global search or a complete cause chain. |
| P1 Exact navigation | Review-context lookup, filtered event reads, diagnostic deep links, cross-page causes, previous-page history, stable URL selection, verified accounting projection | Public contract, read-index strategy, retention behavior and backend contract tests agreed and implemented. This is the core fix for locating causes. |
| P2 Time context | Linked PnL/holdings or valid equity views; optional frozen price chart and markers | Correct series and price basis available; tables and explanations remain usable without charts. |
| P3 Reuse | Better run titles/list metrics, copy settings into an explicitly submitted new run, comparison only for compatible modes and intervals | Preserve frozen identity, single unfinished-task policy and existing idempotency. Never silently rerun or queue a batch. |

Recommended first release combines P0 and the minimal P1 context lookup. A cosmetic P0-only release would improve readability while leaving the user's main cross-page problem unresolved.

Creation can later become “Select plan → Review settings → Prepare data and run”, with fees in advanced settings and internal units formatted for people. Existing automatic data preparation stays in place. Historical compatibility inputs and raw JSON do not belong on the main new-user path.

## UX11. Acceptance criteria

Targets are proposed acceptance gates, not already measured results.

| ID | Scenario and measurable outcome |
|---|---|
| UX-A01 | From a completed run, reach a selected fill's recorded cause in at most 2 intentional navigation actions; no copying IDs or scanning intervening pages. |
| UX-A02 | From a plan diagnostic example, reach the matching `sequence` and evidence in 1 action, even when outside the first 100 events. |
| UX-A03 | A run with 10,000 events supports server-side interval/plan filtering without downloading the entire run. All reads respect 100-record / 2,000-point / 4 MiB bounds. |
| UX-A04 | “No buy rule”, “condition unmet”, “missing evidence”, “execution blocked” and `OBSERVE_ONLY` remain distinct; repeated attempts are not counted as separate unfilled intents. |
| UX-A05 | `POSITION_LIMIT_ONLY`, `KNOWN`, `UNKNOWN` and unknown opening-cost fixtures show only valid metrics. Sampled diagnostics never produce full-run percentages. |
| UX-A06 | Back/Forward and direct links restore filters and selected identity. Switching rapidly across runs cannot display an earlier run's response. |
| UX-A07 | Pruning between list and context reads leaves the retained fill visible and its missing cause explicitly unavailable; no provider, replay, extraction or mutation is triggered. |
| UX-A08 | Keyboard-only review works; focus returns to the selected row; 320/768/1024/1440px layouts avoid page overflow; relevant axe checks pass. |
| UX-A09 | A user can identify outcome, selected-trade reason and a non-trade reason within 30/60/60 seconds in a short moderated walkthrough. Record actual times; do not infer success from unit tests. |
| UX-A10 | New projections verify published identity/content and preserve legacy routes, result hashes, exact money, availability, idempotency and research isolation. |

Use deterministic fixtures for: a filled buy/sell, a blocked response, zero fills, multiple plan versions, `ANY` conditions, cross-page causes, unknown costs, expired details, old schema, read errors and racing navigation.

Relevant existing test locations: `web/tests/unit/BacktestRunDetailView.spec.ts`, `BacktestResultTables.spec.ts`, `BacktestProfitSummary.spec.ts`, `BacktestAccessibility.spec.ts`, `web/tests/e2e/backtests.spec.ts`, `monitor-loop-backtest.spec.ts`, and `tests/integration/test_backtest_result_api.py`.

Future implementation verification commands:

```powershell
# From trade-plan-monitor/
.\.venv\Scripts\python.exe -m pytest tests/integration/test_backtest_result_api.py tests/integration/test_backtest_result_queries.py tests/integration/test_backtest_retention.py -q
.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check

# From trade-plan-monitor/web/
npm run type-check
npm test -- --run
npm run build
npm run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts
```

Add targeted tests for the new read contract and interactions when implementing. This design-only change does not claim these implementation checks passed.

## UX12. Design decisions and review status

- Prefer a list with adjacent evidence over more independent tabs for each data resource: it preserves context.
- Prefer exact recorded explanations over an AI summary: claims remain traceable and unknown evidence remains visible.
- Prefer a small server read extension over downloading all pages: it solves cross-page navigation while retaining bounded reads.
- Prefer applicable PnL and execution facts over generic performance dashboards: the primary funding mode has no capital denominator.
- Defer optimizer, strategy rankings, automatic execution, batch jobs and benchmark-return features.

The product priority is confirmed. Remaining implementation decisions are the precise read-index migration, exact new DTOs and the accounting projection for per-fill PnL. Resolve them in the existing paired module specifications before code changes. This proposal does not supersede current accepted contracts.
