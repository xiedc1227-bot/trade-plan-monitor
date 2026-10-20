# Spec: backtest-web

> `SPEC-backtest-web.md` is the canonical agent-facing English version; `SPEC-backtest-web.zh-CN.md` is the human-review Chinese version; both documents must remain semantically equivalent.

## Objective

Provide a production-routed Vue 3 backtest workbench for historical-data synchronization/verification, one-plan/one-symbol run submission, persistent job progress/cancellation, paginated run history, and accessible result inspection without duplicating backend rules or presenting simulated activity as live trading.

## Relationship and Scope

`backtest-web` consumes only generated `backtest-api` contracts and the shared `local-web` shell, security boundary, and design tokens. The backend is authoritative for validation, data coverage, job state, plan eligibility, execution, metrics, retention, and result availability. Vue owns display state, explicit user intent, request lifecycle, safe formatting, navigation, and accessibility.

The product UI remains Chinese (`zh-CN`). The project's bilingual rule applies to specifications, plans, tasks, README/API/operations/test documentation; adding runtime UI internationalization is a separate capability and is not included.

## Commands

Run from `trade-plan-monitor/web`:

```powershell
npm test -- --run
npm run type-check
npm run build
npm run test:e2e
```

OpenAPI types are generated from the backend with `python scripts/generate_frontend_types.py`; `web/src/api/generated.ts` is never edited by hand.

## Routes and Information Architecture

Add four real or lazy-loaded route views:

```text
/backtests
/backtests/new
/backtests/data
/backtests/:runId
```

Static `new` and `data` routes precede the dynamic `:runId` route. `/backtests` is paginated run history; `/backtests/new` is the run configuration/submission flow; `/backtests/data` owns historical scope, sync, verification, and dataset lists; `/backtests/:runId` owns active-job or completed-result detail.

An accepted run submission navigates to `/backtests/:runId?jobId=<jobId>`. The optional bounded `jobId` query selects one exact durable job. The page validates both route values with generated contracts, fetches that job, and requires `job.kind=BACKTEST_RUN` and `job.runId === route.params.runId` before showing its progress or diagnostic. A mismatch fails closed as an identity error, never associates the job with the run, and offers a safe link back to history. A deep link without `jobId` reads only the materialized result. After `COMPLETED`, canonical navigation removes `jobId` with `router.replace`; `FAILED` or `CANCELLED` keeps the job identity visible for job-only diagnostics and a new-intent retry. Sync/verification job identity remains on `/backtests/data?jobId=<jobId>` and must have the matching `DATA_SYNC|DATASET_VERIFY` kind. Query parameters do not add production routes.

The route plus normalized URL query is the source of truth for every refresh/share-safe view choice: resource identity, filters, sort, cursor/page traversal, selected result `tab`, detail `kind`, and `jobId`. Components either derive directly from `route` or use an explicit loop-safe two-way route synchronization; they never maintain a second hidden authoritative copy. Back/forward navigation cancels stale work and reconstructs the exact view. Server-normalized `filters` replace equivalent non-canonical query spellings without adding a history entry. A job-list pagination `409 CONFLICT` clears the stale cursor, returns to page one, and announces that the list changed.

The historical proposal baseline had six `createRoutePlaceholder` production routes. The current production router has exactly 10 real or lazy-loaded SFC routes: the former placeholders `/`, `/stocks/:symbol`, `/plans/:id`, `/alerts`, and `/system`; the existing `/plans`; and the four backtest routes above. WEBF13 records this completed routing boundary and the exact new-backtest journey; a placeholder-only route remains insufficient.

`AppShell` desktop and mobile navigation add one top-level `回测` link. Backtest sub-navigation uses native links for `运行记录`, `新建回测`, and `历史数据`.

## Component Map

Route views remain thin composition surfaces.

| Component/composable | Single responsibility |
|---|---|
| `BacktestRunsView` | Compose filters, paginated run list, and query states |
| `BacktestNewView` | Compose plan/dataset selection, assumptions, initial lots, and submission |
| `BacktestDataView` | Compose scope, sync/verification jobs, coverage/blockers, and datasets |
| `BacktestRunDetailView` | Compose an exact optional `jobId` attempt and completed result modules by matching `runId` |
| `BacktestRunFilters` | Edit URL-backed run filters |
| `BacktestRunTable` | Render read-only summaries and native navigation |
| `BacktestRunForm` | Edit typed run input and emit explicit submit intent |
| `BacktestPlanVersionSelector` | Render backend-approved immutable plan-version pages and emit selection/paging intent |
| `DatasetScopeForm` | Edit symbols/date/warm-up scope and explicit network intent |
| `DatasetCoveragePanel` | Render backend-authored coverage and blocker facts |
| `BacktestJobStatus` | Render phase/progress/failure and emit cancel intent |
| `BacktestMetricsSummary` | Render exact metrics, costs, assumptions, and limitations |
| `BacktestEquityChart` | Render ECharts daily equity/drawdown projection |
| `BacktestEquityTable` | Provide complete textual/tabular chart alternative |
| `BacktestFillTable` | Render one server-paginated simulated-fill page |
| `BacktestDetailTable` | Render one discriminated decision/signal/execution-outcome page |
| `useBacktestRuns` | Own filters, cursor requests, generation guards, and readonly state |
| `useBacktestPlanVersions` | Own eligible plan-version requests, paging, cancellation, selection, and readonly state |
| `useBacktestRunForm` | Own local draft, exact value parsing, validation hints, and idempotent submission |
| `useBacktestJob` | Own one bounded polling loop, cancellation, visibility, and cleanup |
| `useBacktestResults` | Own independently paginated summary/equity/fill/detail requests |

Components use readonly props and typed events up. Composables return readonly state and explicit actions. Pure formatters remain utilities. ECharts instances and large immutable series use `shallowRef`; derived presentation uses pure `computed`; watchers are limited to cancellable side effects with cleanup.

## State and API Boundary

Backtest state does not enter the existing real-time `monitor` Pinia store. The first release uses URL state plus route-scoped composables and requires no new Pinia store. If later evidence separately approves a backtest store, the URL remains authoritative for identity, filters, sort, pagination/cursor, tab, detail kind, and `jobId`; the store may hold only authoritative entities already loaded from the server, request generation/polling state, and a short-lived form draft. It must not copy computed server results or hide URL view state. A setup-style store returns every reactive state value so DevTools/HMR can observe it. Components use `storeToRefs` when destructuring state/getters; only actions may be destructured directly.

`web/src/api/transport.ts` owns one shared bounded JSON/error transport used by both the existing client and `web/src/api/backtests.ts`; neither adapter may copy its reader or error parser. `readBoundedJson` rejects an oversized `Content-Length` before reading, incrementally counts chunked bytes, cancels the body above `MAX_RESPONSE_BYTES = 4 * 1024 * 1024`, decodes fatal UTF-8 once, bounds traversal to `MAX_VALIDATION_DEPTH = 32` and `MAX_VALIDATION_NODES = 50_000`, and rejects malformed/empty/trailing JSON. `parseApiError` accepts only the closed generated `ErrorResponse`, maps `ApiErrorCode` to local fixed Chinese copy, and never displays raw server/provider text. Abort/network/invalid-response errors remain typed and secret-safe.

`web/src/api/backtests.ts` consumes generated types, performs bounded runtime validation of every closed backtest schema and cross-field discriminator, deep-freezes accepted records, and exposes typed methods rather than raw `fetch`. Every JSON response stays below the shared 4 MiB limit. Its datetime guard reuses the shared strict Shanghai parser: inputs must carry `+08:00` with 0–6 fractional-second digits, accepted values normalize before URL/request construction, and every response must use exact `YYYY-MM-DDTHH:MM:SS.ffffff+08:00`; `Z`, offsetless, overprecision, and other-offset values fail closed. `buildBacktestExportHref` accepts only validated `runId` plus `SUMMARY_JSON|FILLS_CSV` and returns the corresponding same-origin API URL. Export uses a native `<a>`/browser navigation so the browser streams the server's `Content-Disposition` response to disk; it never fetches the file into a whole `Blob`, uses the File System Access API, accepts a path, or reveals a path. Optional preflight reads only the run summary/availability and never downloads export content.

Form values preserve exact backend contracts. Money is entered with explicit yuan/fen labels and converted without binary-float arithmetic; public fen input must remain at most `9007199254740991`. Fees/rates remain canonical decimal strings in `0..1`, and slippage remains a canonical decimal string in `0..<10000`. `BacktestInitialLotInput` rows expose stable `lotKey`, are capped at 200, and retain exact string drafts until validated. Every output `FenText` is formatted from its string or `BigInt`, never through `Number`, so values above JavaScript safe-integer range remain exact. The browser may reject invalid shape early but never computes plan eligibility, position caps, trading calendars, T+1, fills, metrics, or data completeness.

`/backtests/new` obtains real immutable choices only from server-paginated `GET /plan-versions?canActivate=true&offset=<n>&limit=20`. It renders the returned summary identity and pages without combining status queries or filtering an incomplete page in the browser. An eligible inactive version remains selectable; the backend revalidates eligibility when the user explicitly submits the exact `planVersionId`. Before returning the accepted run receipt, the application service persists the selected version's canonical plan snapshot and hash inside the durable job input. Later plan edits create other versions and cannot rewrite that frozen input, an old result, or an existing run hash. Idempotent replay uses the already persisted binding and does not re-read a newer plan. The browser never caches or submits `planJson` for this flow and exposes fixed secret-safe loading, empty, failure, retry, and paging states.

URL datetime filters, server-echoed filters, and `<time datetime>` values preserve canonical China time. User-visible table and chart timestamps use `YYYY-MM-DD HH:mm:ss` while preserving the source wall-clock fields; the machine-readable `datetime` keeps the fixed-six-digit `+08:00` value. Backtest code never calls `Date.toISOString()` for a contract value and never converts through the host/browser timezone.

## Asynchronous Interaction Contract

Query state is `IDLE|LOADING|READY|EMPTY|FAILED`. Submission state is `IDLE|SUBMITTING|ACCEPTED|CONFLICT|UNCERTAIN|FAILED`.

- A timeout or lost response enters `UNCERTAIN` and retains the same idempotency key for safe retry.
- A new key is generated only when the user starts a new semantic intent or changes submitted input.
- Every submission success is handled as `202 BacktestJobReceipt`. A nonterminal receipt follows `Location` and `Retry-After`; an immediately reused `status=COMPLETED` receipt has no required `Retry-After`, skips active polling, and loads its materialized run.
- Route/filter/cursor changes abort prior requests; an older generation cannot replace newer state.
- Only one request per resource and one polling timer per active job may exist.
- While visible, active jobs poll no more often than every 2 seconds and never start a second poll before the first finishes; `Retry-After` controls slower pacing.
- Hidden/unmounted pages stop polling and abort in-flight work; becoming visible triggers one immediate refresh.
- Terminal job state stops the timer. The first release adds no backtest WebSocket.
- A cancel button expresses intent only. `QUEUED -> 200 CANCELLED` renders the terminal state; `RUNNING -> 202 CANCEL_REQUESTED` and replayed `CANCEL_REQUESTED -> 202` keep polling; replayed `CANCELLED -> 200` is terminal; `COMPLETED|FAILED -> 409 CONFLICT` refreshes the authoritative job and explains that cancellation is unavailable. The UI never optimistically claims cancellation or completion.
- Cached facts may remain visible during refresh but must be labelled as refreshing/unavailable rather than current success.

## Result Presentation

The detail page loads the run summary first. Equity, fills, and only `DECISION|SIGNAL|EXECUTION_OUTCOME` detail kinds load independently and only when their URL-selected tab is active. It never accumulates all years of fills/details in one reactive array. The run's field-level `decisionDetails`, `signalDetails`, `executionOutcomeDetails`, and `equitySeries` availability drives requests and presentation. `AVAILABLE`, `EXPIRED`, and `NOT_RECORDED` receive distinct copy and actions; an unavailable projection never triggers speculative reconstruction. Failure/cancellation diagnostics are rendered only from a matching job resource and never appear as a run-detail tab.

All displayed fills are labelled `模拟成交（仅供研究）`. Metrics display their exact definition and limitation Tokens; unadjusted prices and unsupported corporate actions remain prominent. Export buttons request only `runId` plus `SUMMARY_JSON` or `FILLS_CSV` and do not reveal a filesystem location.

## Visual, Responsive, and Accessibility Contract

Reuse the existing graphite/ink, mineral text, amber, sea-glass, vermilion, cyan, spacing, border, focus, and tabular-numeric tokens. Avoid decorative gradients, generic card grids, excessive rounding/shadows, and stock imagery. Content hierarchy follows workflow priority rather than equal KPI tiles.

- Each route has one `<h1>`, ordered headings, and a descriptive Chinese `document.title`. Client navigation moves focus to the new `<h1>`; ordinary polling never steals focus.
- Every form control has a visible label, unit, requirement state, and associated field error. Invalid controls set `aria-invalid=true` and `aria-describedby` to stable help/error IDs. A failed submission focuses an error-summary heading whose links move focus to the corresponding control; corrected resubmission clears obsolete associations.
- Prefer native button/link/select/table/progress/dialog semantics. Known totals use `<progress>`; unknown totals use phase text.
- Critical state changes use `role="status"`/`aria-live="polite"`; one failure transition may use `role="alert"`, but poll ticks are never repeatedly announced.
- Cancellation confirmation traps focus, supports Escape, and restores focus to its trigger.
- URL-backed result tabs use native links and `aria-current`; sortable table headers expose the current `aria-sort`; pagination controls have resource/page labels and a disabled state that is not conveyed by color alone.
- Charts have accessible names and a complete table/text alternative containing the same points and exact `FenText` values. Profit/loss/risk/job state never relies on red/green alone.
- Focus remains visible, text scales to 200%, reduced motion is respected, and mobile touch targets are at least 44×44px.
- At 320px forms are single-column and wide tables use labelled focusable horizontal scroll regions; 768px may use two columns without changing logical Tab order; 1024px may use main/side status layout; 1440px retains a readable maximum width.

Automated checks do not replace a manual NVDA pass on Windows. The acceptance pass covers all four routes, landmark/heading announcement, form labels/errors and error-summary focus, job progress/failure without poll spam, cancellation-dialog focus return, tabs/sort/pagination, chart-table equivalence, expiry copy, and download naming using keyboard-only navigation in both Chrome and Firefox.

## Security and Performance

All plan/provider/error text is rendered through escaped Vue interpolation; `v-html`, dynamic script, arbitrary URLs, local paths, and raw server exception messages are forbidden. The user must explicitly confirm the only network-capable sync action; the UI never accepts or displays the Tushare token.

Backtest routes use route-level lazy loading. ECharts is loaded only by the result-detail chart subchunk and only when the equity tab is selected; runs/new/data pages do not load the chart runtime. At most 100 result rows exist in the DOM per table page, equity contains at most 2,000 daily points, one resource has at most one request and one active job has at most one polling timer, and maximum JSON pages remain below 4 MiB. These are structural gates. The implementation plan must define fixed fixtures/devices, route-chunk budgets, request-count scenarios, and LCP/INP/CLS and interaction thresholds before performance implementation begins; this specification approves no empirical performance number.

## Project Structure

Use feature folders under `web/src/components/backtests/`, route views under `web/src/views/`, focused composables under `web/src/composables/` or the feature folder, shared bounded transport in `web/src/api/transport.ts`, backtest methods/validators in `web/src/api/backtests.ts`, and existing `web/src/assets/tokens.css`. Route views must not grow into multi-section feature implementations.

## Code Style

Use Vue 3 Composition API, `<script setup lang="ts">`, PascalCase SFCs, script/template/scoped-style order, class selectors in scoped CSS, `useTemplateRef` for imperative focus/DOM handles, `ref` for primitives/local drafts, `shallowRef` for ECharts and large immutable server records, typed `defineProps`/`defineEmits`, stable `v-for` keys, and `v-if`/`v-show` chosen by lifecycle. Never mutate props or shared records directly. If a setup-style Pinia store is later approved, return all reactive state, use `storeToRefs` for state/getter destructuring, and destructure actions directly only.

## Testing Strategy

Vitest covers every component/composable state, readonly/action boundary, request abort/generation race, idempotency-key reuse under `UNCERTAIN`, immediate-completed `202`, poll timing/cleanup, the full cancellation matrix, field-level availability copy, exact `FenText`/`BigInt` display and bounded decimal input, all datetime fields and 0–6-to-fixed-six `Asia/Shanghai` normalization, rejection of `Z`/offsetless/overprecision/other-offset values, `<time datetime>` preservation, zero `Date.toISOString()` contract conversion, chart mapping/table equivalence, focus management, and 100-row bounds. Shared-transport tests cover oversized declared/chunked bodies, body cancellation, fatal UTF-8, malformed/trailing JSON, depth/node limits, closed safe-error parsing, abort, network failure, and redaction. Export tests prove only the allowlisted same-origin anchor URL is constructed and that no export-content `fetch`, whole-file `Blob`, File System Access API, or path input is used.

Router tests fix exactly 10 paths and prove all four backtest paths render real views. They round-trip canonical `+08:00` datetime filters, other filters, sort, cursor/page, tab, detail kind, and `jobId` through refresh/back/forward; prove `/backtests/:runId?jobId=<jobId>` accepts only a `BACKTEST_RUN` job with the exact same `runId`; prove mismatched/malformed IDs fail closed; prove no-`jobId` deep links read only materialized runs; and prove canonical query replacement creates no loop. If a Pinia store is later approved, tests also enforce URL authority, complete setup-state return, and `storeToRefs` use.

Browser tests cover the complete fake-provider data-sync → verify → submit → poll → result → pin/export journey, immediate reuse, cursor-membership restart, all availability states, console/network failures, 320/768/1024/1440 layouts, keyboard order, 200% text, reduced motion, and axe WCAG 2.1 A/AA. Manual NVDA acceptance follows the checklist above. Performance fixtures and measured thresholds come from the approved implementation plan, while structural lazy-load/DOM/request/timer/response bounds remain test gates here.

## Boundaries

- Always: use generated contracts, shared bounded transport, server-authoritative state, URL-authoritative shareable view state, explicit idempotent intent, bounded requests, thin views, typed props/events, safe escaped text, and complete loading/empty/error/uncertain/cancel states.
- Always: label simulation/research limitations and keep historical data independent of live monitoring.
- Ask first: add a Pinia backtest store, WebSocket, UI localization, new chart library, browser notification, comparison/optimizer workflow, or remote access.
- Never: duplicate strategy/T+1/metric logic, reuse the monitor store, hide filters/sort/page/tab/`jobId` in a store, render raw HTML, expose tokens/paths, accumulate unbounded detail, expose job diagnostics as run details, optimistically invent terminal state, or add placeholder-only routes.

## Success Criteria

- Production routing has exactly 10 approved paths and every backtest path renders a real lazy route view.
- A user can explicitly sync/verify data, submit one validated plan/symbol run, observe/cancel the persistent job, and inspect a completed result without a page reload.
- Duplicate click/timeout retry creates no duplicate job or run.
- Refresh/share/back/forward preserve URL-selected filters, sort, page, tab, and correctly mapped `jobId` without stale-request overwrite.
- All JSON and errors pass through the one bounded transport; exact `FenText` never loses precision.
- Every API/URL/machine-readable datetime remains canonical `Asia/Shanghai`/`+08:00`; user-visible datetimes use `YYYY-MM-DD HH:mm:ss` and never depend on the host/browser timezone.
- Summary-first, independently paginated result loading stays below 4 MiB and 100 DOM rows per page.
- Simulation, expiry, data limitations, and server state are always represented truthfully with text, not color alone.
- Keyboard, focus, manual NVDA, responsive, reduced-motion, 200%-text, axe, unit, type-check, build, and real-browser gates pass.
- Production composition reaches real backtest services; a Router plus `SERVICE_UNAVAILABLE` stubs is not completion.

## Open Questions

No blocking question remains for the first workbench proposal. Runtime internationalization, multi-run comparison, portfolio/shared-cash backtests, parameter optimization, WebSocket progress, browser/OS notifications, a cross-route Pinia store, and empirical performance budgets remain separate future capabilities or implementation-plan decisions as applicable.

## BR-WEB01. Result review workspace

[BR01–BR06](SPEC-backtest-review.md) govern the P0 + minimal P1 slice. Existing `summary`, `fills`, `details`, `equity`, `market-index` URL meanings remain readable; add `reasons` and `provenance` for monitoring-loop runs. The compact overview and fill list lead to recorded evidence through URL `fillId|eventId|sequence`, `relation`, `reviewCursor`. Keep the resource cursor when opening/closing evidence; abort and ignore stale reads. Back/Forward restores selection. Visited signed cursors support Previous; direct links retain First page fallback. Preserve exact amounts, funding-mode applicability, representative diagnostic sampling, engine root outcomes and legacy readers. Evidence moves below records below 1024px; controls have 44px targets and visible keyboard focus. No whole-run client filtering or single-fill accounting reconstruction.
