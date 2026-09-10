# Spec: monitor-index-trends

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-monitor-index-trends.zh-CN.md`; both documents must remain semantically equivalent.
>
> This is a focused extension of the approved `monitor-index-view` capability, not a new capability-map module.

## Review Status

**IMPLEMENTED — user authorized implementation.** This document records the delivered scope and validation boundary. It does not authorize provider-profile, API, dependency, push, or deployment changes outside that scope.

## Objective

Add a four-index trend area to the Monitoring Overview so the user can see the current direction and recent path of:

| Display order | Display name | `indexCode` | Board |
|---|---|---|---|
| 1 | 上证指数 | `000001.SH` | `SSE_MAIN` |
| 2 | 深证成指 | `399001.SZ` | `SZSE_MAIN` |
| 3 | 创业板指 | `399006.SZ` | `CHINEXT` |
| 4 | 科创50 | `000688.SH` | `STAR_MARKET` |

The four cards are always present, independent of which boards are referenced by active trade plans. They display market facts only and never add a market-strength label, recommendation, or hidden trading gate.

## Scope and Product Decisions

### Included in the first version

- A fixed two-by-two card grid below the connection/data-age strip and above monitor counts.
- One fixed current-trading-day view with no range selector.
- The current-day trend uses certified completed `FIVE_MINUTE` closes only.
- Each card shows name, code, latest completed value, session change ratio, data cutoff, health, and a compact line chart.
- When no index bars exist yet, all four cards still render an empty labelled chart area instead of disappearing.
- Chart annotations: prior-close dashed baseline when supplied by the authoritative snapshot, latest-point marker, “current trading day” label, and explicit health text/icon.
- One expandable accessible data table per card containing the exact returned time and close values.
- Cached bars remain visible during refresh or isolated failure, with the original cutoff and stale/error state visible.

### Excluded from the first version

- User-selected indices, BSE 50, industry/theme indices, constituent aggregation, candlestick/volume views, technical indicators, historical range switching, cross-index normalization, comparison ranking, market conclusions, and trading signals.
- Browser-side return, SMA, condition, or policy calculations.
- New provider endpoints or a new public Web API contract.

## Tech Stack, Commands, and Project Structure

- Vue 3 Composition API with `<script setup lang="ts">`, generated readonly API types, ECharts line series, and Vitest/Playwright.
- Existing Python runtime, market-index snapshot coordinator, persistence, dashboard projection, and signed history endpoint.

```powershell
python -m pytest tests/unit/test_monitor_runtime.py tests/integration/test_market_index_web.py -q
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e -- dashboard.spec.ts
```

```text
src/trade_plan_monitor/runtime/market_indexes.py       # fixed display-interest acquisition
src/trade_plan_monitor/web/persistent_monitor_read_service.py
web/src/views/DashboardRouteView.vue                   # composition and API injection
web/src/components/market-index/
├── MarketIndexDataStrip.vue                           # fixed current-day four-card layout
├── MarketIndexTrendCard.vue                           # one index summary and states
└── MarketIndexSparkline.vue                           # visual-only ECharts line
web/src/composables/useDashboardMarketIndexTrends.ts   # four bounded requests and cancellation
web/tests/unit/
web/tests/e2e/dashboard.spec.ts
```

## Data and Runtime Design

### Fixed display interest

The runtime defines one closed `DASHBOARD_INDEX_CODES` tuple containing the four codes above. At each normal completed five-minute cutoff it unions this display interest with plan-owned index requirements:

```text
four dashboard codes + distinct active-plan reference codes
  -> one acquisition per distinct index and cutoff
  -> immutable validated snapshots/bars
  -> plan evaluation uses only plan-owned fact requests
  -> dashboard/history read models consume the same stored facts
```

Display interest requests raw completed bars and prior close only. It must not introduce indicator fact requests into a plan or make a plan depend on an otherwise informational index. Acquisition remains deduplicated per `(indexCode, cutoff)` and isolated per index.

When no plan evaluation is due—including when there are no active plans—the production deadline still prepares and persists the four display-only indexes at completed five-minute boundaries. Official-close attempt one also refreshes them. Stock evaluation and display-only index acquisition remain independent outcomes.

The dashboard read service projects the latest snapshot for all four display codes and computes `mappedSymbolCount` separately. Therefore a card may validly show `mappedSymbolCount=0`. When the dashboard projection itself is unavailable, the frontend still renders the four fixed identities and empty charts. Missing acquisition never removes the cards or affects any plan decision.

### Existing API reuse

No new endpoint or response field is required:

- Summary and authoritative health: existing `DashboardResponse.marketIndexes`.
- Trend bars: existing `GET /api/v1/market-indexes/{indexCode}/bars`.
- Refresh: a newer dashboard snapshot or native retry triggers a bounded refetch of the current-day cards.

The browser issues at most four concurrent trend requests for the current Shanghai trading day. Each query uses `interval=FIVE_MINUTE` and `limit=64`, below the existing `2,000`-point endpoint limit. Requests use canonical `Asia/Shanghai` day boundaries, `AbortController`, generation guards, and no automatic pagination.

## Vue Component and State Design

| Unit | Single responsibility | Contract |
|---|---|---|
| `DashboardRouteView.vue` | Compose the existing dashboard snapshot, market-index API, and trend feature | Pass readonly data down; no chart mapping |
| `MarketIndexDataStrip.vue` | Render the fixed order and responsive current-day grid | Props: summaries and per-code trend states; emit `retry` |
| `MarketIndexTrendCard.vue` | Render one index's summary, chart state, and accessible table disclosure | Typed props for identity, snapshot, bars, loading, error |
| `MarketIndexSparkline.vue` | Render exact bar time/close coordinates and annotations | No requests, health policy, indicators, or trade inference |
| `useDashboardMarketIndexTrends.ts` | Build fixed current-day queries, fetch four pages, retain successful state during refresh, cancel stale generations | Returns readonly per-code `IDLE|LOADING|READY|EMPTY|ERROR` state |

Style example:

```ts
const orderedCards = computed(() =>
  DASHBOARD_INDEX_CODES.map((indexCode) => state.value[indexCode]),
);
```

Source state stays minimal. Display ordering and status copy are derived with `computed`; network side effects live in the composable. Components use typed props down and typed events up. Decimal strings remain authoritative; conversion to finite JavaScript numbers is allowed only at the chart rendering boundary and never feeds displayed evidence or decisions.

## Layout and Annotations

```text
┌ 主要指数走势 · 当日                                  ┐
│ ┌ 上证指数  000001.SH ───── +0.42%  实时 ● ────────┐ │
│ │ 3,126.45   截止 10:35  ──╮__╭──●               │ │
│ │ ····················· 昨收基线 ·············· │ │
│ └────────────────────────────── [查看数据] ───────┘ │
│ ┌ 深证成指 ──────────────┐ ┌ 创业板指 ────────────┐ │
│ └────────────────────────┘ └──────────────────────┘ │
│ ┌ 科创50 ─────────────────────────────────────────┐ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

- At `>=640px`, use a two-column grid; below `640px`, use one column. At `320px`, values wrap without page-level horizontal overflow.
- Charts have a fixed compact height of approximately `160px`; animation is disabled and reduced-motion is respected.
- Chinese market convention may color positive values red and negative values green, but direction must also be expressed with sign, text, and chart labeling. Neutral/unknown uses the normal text color.
- Each chart has an accessible name containing index name, “current trading day,” latest value, change, cutoff, and health. The disclosure table is the exact non-visual equivalent.
- Y axes use independent point scales. No overlay suggests that raw point levels are directly comparable.

## Loading, Empty, and Failure States

- `LOADING` with cache: keep the prior chart, add “刷新中” and preserve its cutoff.
- `LOADING` without cache: show an explicit loading status and index identity.
- `EMPTY`: keep the labelled empty chart area and show “该时段暂无已完成指数点位”; never draw a zero line.
- `ERROR` with cache: keep the chart, mark it stale/error, and expose a native retry button.
- `ERROR` without cache: keep the card and summary health; show “走势暂不可用”.
- Failure or delay of one index never blocks the other three.
- A disconnected dashboard never labels cached charts as real-time.

## Performance and Economic Constraints

- Four requests are parallel and capped; unmounting or a newer invalidation generation cancels obsolete requests.
- Retain the last successful page per code while a same-view refresh is in flight; a current-day query never requests historical pagination.
- Register only ECharts `LineChart`, `CanvasRenderer`, `GridComponent`, `MarkLineComponent`, `MarkPointComponent`, `TooltipComponent`, and `AriaComponent` needed by the feature.
- Do not add a charting dependency. Reuse the installed ECharts package.
- Target: first four cached/fixture charts become stable within `500 ms` after dashboard data is available in local verification.

## Testing Strategy

- Python unit/integration tests prove all four display codes are acquired without active plans, once per cutoff, deduplicated with plan interest, projected even with zero mapped symbols, persisted for history, and isolated on provider failure.
- Vitest proves fixed ordering, current-day query boundaries, four-request cap, cancellation/generation guards, retained success/error state, decimal conversion fail-closed behavior, annotation copy, table equivalence, and all state combinations.
- Playwright proves four visible current-day cards and charts at `320/768/1024/1440`, one failed card beside three healthy cards, no page overflow at 200% text, keyboard operation, reduced motion, and zero serious/critical axe findings.
- Build and generated-contract checks must pass. The change must add no API field, provider endpoint, browser policy calculation, or new dependency.

## Boundaries

- **Always:** show all four identities, source cutoff, health, “current trading day,” exact table alternative, and isolated errors; reuse validated bars and existing contracts.
- **Ask first:** change the four-code list, add a historical range, change interval/refresh cadence, endpoint/schema, provider quota profile, or add a calculated/interpretive annotation.
- **Never:** synthesize missing points, use unfinished quotes, normalize/compare raw point levels, hide a failed index, infer market strength, alter plan decisions, or render provider error text.

## Success Criteria

1. Monitoring Overview always contains exactly four ordered cards and chart areas for `000001.SH`, `399001.SZ`, `399006.SZ`, and `000688.SH`, including when the dashboard projection or index bars are not yet available.
2. Each healthy card renders the current trading day's visible trend from authoritative completed five-minute bars, plus latest value, signed session change, cutoff, and health.
3. One unavailable index remains visible and does not prevent the other charts from loading or updating.
4. With zero active plans, completed five-minute deadlines still acquire and persist the four display-only indexes; they do not affect any plan's fact requirements, evidence, hash, or decision.
5. The feature adds no public API contract or dependency and passes the commands listed above.
6. Keyboard, screen-reader/table alternative, reduced-motion, responsive layout, and 200% text acceptance checks pass.

## Open Questions

None. “两创” is defined as `创业板指 (399006.SZ)` and `科创50 (000688.SH)`, and the user has limited the first version to the current trading day only.
