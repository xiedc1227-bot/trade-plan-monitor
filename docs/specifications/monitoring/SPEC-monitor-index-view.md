# Spec: monitor-index-view

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-monitor-index-view.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Project shared board-index facts and plan-specific index-condition outcomes separately across the monitoring dashboard, symbol detail, history API, and invalidation stream. The backend remains authoritative; Vue only validates and renders returned data.

## Commands and Structure

```powershell
python -m pytest tests/integration/test_market_index_web.py tests/integration/test_websocket.py -q
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
```

```text
src/trade_plan_monitor/web/routers/market_indexes.py
src/trade_plan_monitor/web/schemas.py
src/trade_plan_monitor/web/websocket.py
web/src/components/market-index/
├── MarketIndexDataStrip.vue
├── IndexConditionProgress.vue
├── ReferenceMarketPanel.vue
└── MarketIndexChart.vue
web/src/composables/useMarketIndexSeries.ts
```

## Backend Runtime Projection

At each cutoff, runtime first unions plan fact requirements and obtains at most five shared snapshots. Both intraday and official-close multi-plan entry points perform this union once before per-plan evaluation; official-close evaluations remain serialized after snapshot preparation. Each stock evaluation receives its board snapshot by immutable reference. Runtime stores the latest snapshot by `indexCode` and the latest per-plan path evidence separately. One index failure remains visible and does not suppress another index.

A Schema v1 plan has `referenceMarket=null`. A Schema v2 plan with no index leaf can show shared data and `conditionProgress.total=0`; absence/failure of that shared data cannot change the stock decision. A Schema v2 plan with leaves derives progress only from backend-authored evidence whose plan hash, snapshot hash, and cutoff agree.

## API Contracts

`DashboardResponse.marketIndexes` is a required array with at most five unique items, sorted by `indexCode`. Existing responses remain compatible because the array may be empty.

`MarketIndexSnapshotView` has exactly:

- `indexCode`, `displayName`, `board`, `closePoints`, `priorClosePoints`, `sessionChangeRatio`;
- `completedBucketAt`, `observedAt`, `health`, `issues`, `indicatorFacts`;
- `mappedSymbolCount`, `mappingVersion`, `revision`, `snapshotHash`.

Exact point/ratio values are canonical decimal strings. `indicatorFacts` is bounded to 50 and contains `formulaId`, typed parameters, `value`, `unit`, `sourceBarHash`, and `formulaDefinitionHash`. The shared item never contains a market label, plan id, condition result, `entryAllowed`, or `decisionEffect`.

`SymbolSummaryView.referenceMarket` and `SymbolDetailResponse.referenceMarket` are nullable. When present, `SymbolReferenceMarketView` has exactly `indexCode`, `displayName`, `board`, `mappingVersion`, nullable `snapshotHash`, nullable `dataAt`, `health`, `issues`, and `conditionProgress`. `IndexConditionProgressView` has non-negative `satisfied`, `unsatisfied`, `missing`, and `total`, with their sum equal to `total`. Zero means “not used by plan,” not “satisfied.”

Symbol detail additionally exposes `indexConditionEvidence`, ordered by exact `planPath`. Each item is the server projection of `IndexConditionEvidence`; the browser does not join it to bars or recompute an outcome.

### Index bars

`GET /api/v1/market-indexes/{indexCode}/bars` requires `interval`, `startAt`, `endAt`, and `limit`.

- `interval=FIVE_MINUTE|OFFICIAL_DAILY`; `startAt`/`endAt` are canonical `+08:00` and inclusive.
- `limit` is `1..2000`; the date range is at most 31 days for five-minute and 10 years for daily.
- The page has `items`, `limit`, `nextCursor`, `hasMore`, and `snapshotHash`; every item is validated and ordered by `barAt ASC`.
- More data uses the existing installation-local signed cursor pattern, bound to index, interval, range, ordering, and high-water identity.
- Unknown/unapproved/mismatched codes and malformed cursors use the existing safe error envelope and never expose provider details.

### Invalidation

The WebSocket union adds `market.index.updated` with exactly `entityId`, `revision`, and `status`. It is an invalidation notice only. The browser refetches dashboard/detail/history data and never constructs a snapshot or condition outcome from the event.

## Vue Component Map and Data Flow

| Component/composable | Single responsibility |
|---|---|
| `MarketIndexDataStrip.vue` | Render bounded shared facts, cutoff, health, issues, facts, and mapped-stock count |
| `IndexConditionProgress.vue` | Render one plan's counts or explicit “计划未使用” state |
| `ReferenceMarketPanel.vue` | Render one stock's mapping and shared snapshot identity |
| `MarketIndexChart.vue` | Render validated index points and a textual table alternative; no policy calculation |
| `useMarketIndexSeries.ts` | Own bounded request, cancellation, generation guard, loading/empty/error states |

Route views remain composition surfaces. Readonly generated types flow down through typed props; navigation and range changes emit typed events up. Reusable derived presentation uses `computed`; requests use cleanup-aware watchers; large immutable series use `shallowRef`. Components never derive the board mapping, SMA, return, condition result, policy priority, or final decision.

## Presentation and Accessibility

- Dashboard places “参考板块指数：共用数据” below connection/data-age status and adds “参考指数” plus “计划指数条件” watchlist columns.
- Symbol detail has two headings: “参考指数数据” and “计划指数条件.” Stock and index charts remain separate.
- Refresh may retain cached facts only with original cutoff and explicit refreshing/health text. Failed indices remain present.
- Health and outcomes use text plus icons, never color alone. Tables have captions; changes use bounded polite announcements.
- Native controls, visible focus, keyboard navigation, 200% text, reduced motion, and responsive 320/768/1024/1440 layouts are required. Charts have an equivalent table.
- All text uses escaped interpolation; `v-html`, raw provider text, arbitrary URL, and local path rendering are forbidden.

## Testing Strategy

- Backend tests prove snapshot deduplication, bounded/signed history, exact decimals/time, safe errors, nullable migration fields, progress invariants, path evidence, and invalidation payloads.
- Vitest covers shared-vs-plan separation, no-condition copy, cached/stale/gapped/blocked/empty/loading/failure states, cancellation races, keyboard/table semantics, and zero browser policy functions.
- Playwright covers dashboard/detail with two plans sharing one snapshot but different outcomes, one failed board beside a healthy board, no-condition behavior, responsive widths, and axe with no serious/critical findings.

## Boundaries and Success Criteria

- Always: show cutoff and health, keep shared facts separate from plan outcomes, and consume generated contracts.
- Ask first: add an endpoint/field/event, browser store, chart calculation, or new display conclusion.
- Never: let Vue map symbols, compute indicators/conditions, infer trade effects, hide failed indices, or expose secrets.
- The user can trace displayed plan impact to an exact path and snapshot while a plan with no index leaf remains behaviorally unchanged.

## Review Status

Approved for implementation and offline browser/API verification on `2026-09-02`; real provider calls remain unauthorized.
