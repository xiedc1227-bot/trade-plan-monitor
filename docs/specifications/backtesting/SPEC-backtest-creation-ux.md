# Backtest creation interaction

Status: implementation contract. Companion: `SPEC-backtest-creation-ux.zh-CN.md`.

## BC-01 Problem and reference evidence

The creation page currently places source selection, timeline history, raw-source preparation, review and run settings in one long flow. Reusing a reviewed timeline requires scanning preparation controls that are irrelevant to that task.

References inspected on 2026-10-20:

- [FreqUI backtest page](https://github.com/freqtrade/frequi/blob/main/src/pages/backtest.vue) separates running, history and analysis; [BacktestRun](https://github.com/freqtrade/frequi/blob/main/src/components/ftbot/BacktestRun.vue) selects a strategy before parameters, collapses optional strategy parameters and has an explicit start action. Adopt progressive disclosure and distinct selection/configuration/start stages.
- [Hummingbot backtesting](https://github.com/hummingbot/hummingbot-site/blob/main/docs/dashboard/backtest.md) configures a strategy before date range and costs, then explicitly runs the backtest. Adopt that ordering. Its older Streamlit dashboard is an interaction reference, not a new dependency.
- [QuantConnect deployment](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/deployment) separates explicit submission from accepted/running/result feedback. Retain the existing server receipt, automatic data preparation and result navigation.

Use the product's existing mineral/graphite/amber tokens and components. Do not copy branding, add a UI dependency, or redesign the result page again.

## BC-02 Selection and information hierarchy

- Keep the existing default workbench source and direct `preparationId` resume behavior.
- Short source labels explain workbench reuse versus reviewed timeline reuse. Compact the heading and research boundary.
- Show loaded timeline/record counts, a stock name/code search, and explicit refresh/new actions.
- Each timeline shows stock name/code, a stable ordinal, root review time, update count and effective-date range. Show exact branch endpoints separately. Never merge independent chains or branches.
- Keep ten complete timelines per page. Search filters existing metadata only, resets the page and preserves the selected endpoint. Locating the selection clears the filter and opens its page.
- Collapse update records and review evidence initially. Selecting a timeline is a read action; it never composes a preparation or starts a run.

## BC-03 Progressive preparation and settings

- Initial timeline mode shows the library and next-step guidance; it does not show an unused raw-source form or idle preparation progress.
- Selecting a reviewed timeline reveals existing run settings and moves keyboard focus there after the read completes.
- New/update explicitly reveals the preparation workspace and focuses its heading. Update retains the exact reviewed predecessor.
- Resumed unfinished preparations, errors and uncertain mutations remain visible. Review completion returns to run settings; historical `inspect=1` retains read-only evidence.
- An untouched, unsaved workspace may be closed. A dirty draft cannot be hidden or replaced through this control. Existing draft, submission, preparation and uncertain-result locks remain effective.
- Run settings, fees, admission, automatic data completion, idempotency and backend interpretation remain unchanged.
- Place the frozen account summary above the fee inputs across the full form width. Collapse per-plan effective-date details so a long timeline cannot stretch the first fee-input row.

## BC-04 State and accessibility contract

Loading, successful empty, failed initial read, stale retained results, no search matches, selected, dirty, busy and uncertain states remain distinct. Failed reads never imply deleted history or show a confirmed zero count. A no-match state offers clearing the search; it does not offer recreating historical data.

Use native buttons, labeled search, text plus color for selection, visible keyboard focus and 44px minimum action targets. Verify 320/768/1024/1440px widths and 200% text without horizontal page overflow.

## BC-05 Component map and verification

- `BacktestNewView`: existing API orchestration and composition; owns explicit workspace visibility/focus, not timeline rendering.
- `ReviewedPlanLibrary`: receives items, selection and request/lock states; owns metadata search/paging and emits `open`, `update`, `new`, `refresh`.
- `PlanTimelineCard`: receives one immutable group, ordinal, endpoint, disabled state and optional details API; emits exact endpoint `open`/`update`, renders history disclosures.
- Existing preparation/review/run components retain their business contracts.

Tests cover selection identity through search/paging, branches, failed reads, explicit preparation entry, dirty drafts, resume and review-to-settings. Browser validation covers keyboard operation, reflow, no unintended writes and the existing end-to-end creation/update/inspection paths using isolated test storage. Real-history verification is read-only.
