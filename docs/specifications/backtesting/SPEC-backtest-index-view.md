# Spec: backtest-index-view

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-backtest-index-view.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Expose and render backtest reference-market binding, coverage, shared index series, path-level condition counts, exact decision evidence, and formal export identity without inventing a run-level market classification. Browser code remains a read-only projection of backend results.

## Commands and Structure

```powershell
python -m pytest tests/integration/test_backtest_index_api.py tests/integration/test_backtest_export_api.py -q
python scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
```

```text
src/trade_plan_monitor/web/backtest_schemas.py
src/trade_plan_monitor/web/routers/backtest_results.py
src/trade_plan_monitor/web/backtest_export.py
web/src/components/backtests/BacktestIndexConditionSummary.vue
web/src/components/backtests/BacktestMarketIndexPanel.vue
web/src/components/market-index/MarketIndexChart.vue
web/src/composables/useMarketIndexSeries.ts
```

## API Contract

All additions are nullable/additive for old runs. Existing v1/v2 stock-only result rows, hashes, JSON, CSV, and API projections are not rewritten.

`BacktestRunView.referenceMarket` is nullable. For a Schema v2 index-bearing run it has exactly:

- `binding` (`selection`, `mappingVersion`, `indexCode`, derived `displayName`, derived `board`);
- `required`, ordered unique `conditionPaths`, `warmupStart`, `coverageStatus`, and ordered `blockers`;
- `marketIndexDataHash`, `indexRequirementHash`, `formulaDefinitionHash`, and `datasetHash`;
- `conditionSummaries` sorted by `planPath`.

Each `BacktestIndexConditionSummaryView` contains `planPath`, `conditionType`, typed parameters, `formulaId`, `satisfiedCount`, `unsatisfiedCount`, `missingCount`, and `applicableBranchCount`. Counts are non-negative safe integers. No summary field represents overall market strength or an automatic trade effect.

`BacktestAuthoritativeDecisionView.referenceMarket` is nullable. When present it contains `indexCode`, `snapshotHash`, `dataAt`, `health`, and the complete ordered path-level `IndexConditionEvidenceView[]` used by that decision. It is persisted with the decision and is never joined to newer data at read time.

### Series resource

`GET /api/v1/backtest-runs/{runId}/market-index-series` returns `BacktestMarketIndexSeriesView`.

- Old/no-index runs return `referenceMarket=null`, `items=[]`, and `conditionSummaries=[]` without synthesizing history.
- Index-bearing runs return exact binding/hash identity, at most 512 ordered `OFFICIAL_DAILY` display points, requested indicator facts, a bounded health timeline, and the same condition summaries as the run resource.
- Query accepts optional canonical `startOn`, `endOn`, and `limit=1..512`; the server downsamples only for display with a deterministic first/last-preserving algorithm. Exact five-minute evidence remains in paginated decision details.
- Unknown run, unavailable/expired evidence, malformed range, and identity mismatch use the existing safe error envelope. The response remains below 4 MiB.

### Export and versioning

Schema v2 runs with index leaves use canonical report domain `backtest-report-v2` and summary export domain `backtest-report-summary-v3`; existing report/export domains remain immutable. Formal JSON export includes binding, `marketIndexDataHash`, `indexRequirementHash`, `formulaDefinitionHash`, condition paths/counts, and each retained decision's snapshot/formula evidence. Fill CSV remains fill-only but its metadata identity references the run/report hash. Export never recomputes expired detail or queries a provider.

## New-Run and Result UI

After plan and stock selection, the new-run form displays the backend-resolved index, mapping version, every index condition path, derived warm-up, and coverage. Only a plan that uses index leaves requires index coverage. The browser cannot edit the binding or calculate warm-up.

The completed detail view adds a native-link tab `参考指数`. Summary content keeps “共用指数数据” and “计划指数条件结果” as separate regions:

- `BacktestIndexConditionSummary.vue` renders per-path counts and applicable-branch counts.
- `BacktestMarketIndexPanel.vue` composes binding/hash identity, health timeline, `MarketIndexChart.vue`, date navigation, and condition summary.
- Selecting a day navigates to the existing decision-detail page/filter, whose authoritative record contains exact five-minute evidence.

Route views remain thin. Generated readonly records flow through typed props; tab/date/filter intent emits upward or updates URL-authoritative state. Large immutable series use `shallowRef`; presentation derivations use pure `computed`; cancellable fetching stays in `useMarketIndexSeries.ts`. No Vue file maps stock symbols, calculates SMA/return, evaluates a condition, counts outcomes from raw decisions, or changes priority.

## Accessibility and States

- Use one ordered heading hierarchy, native tab links with `aria-current`, labelled date controls, table captions, explicit units/cutoffs, and a full textual chart alternative.
- `AVAILABLE`, `EXPIRED`, `NOT_RECORDED`, loading, refreshing, empty, missing, gapped, stale, and blocked states have distinct text. A no-index plan says “计划未使用指数条件.”
- Health/outcome never relies on color alone. Keyboard, visible focus, 200% text, reduced motion, and 320/768/1024/1440 layouts remain required.
- Cached series can remain visible during refresh only with their original dataset/snapshot identity and explicit status. Newer data can never be paired with older outcomes.

## Testing Strategy

- Backend tests cover nullable migration, exact hashes/paths/counts, 512-point bound, deterministic display reduction, retained five-minute detail, safe errors, and versioned export bytes.
- Vitest proves generated contract use, shared/plan separation, no browser calculations, no-condition behavior, every availability/health state, stale-request cancellation, URL tab/date round trips, chart-table equivalence, and keyboard semantics.
- Playwright covers create → verify coverage → submit → completed reference-index tab → exact decision → export using offline fakes; two plans share one index dataset but produce different counts. Run at all approved widths and axe with no serious/critical findings.

## Boundaries and Success Criteria

- Always: preserve authoritative identities, keep exact evidence in decisions/exports, and separate data from plan outcomes.
- Ask first: add API fields/endpoints, report/export domains, browser calculations, or an overall classification.
- Never: rewrite historical results, infer a market label, calculate policy in Vue, expose local/provider secrets, or reconstruct expired evidence.
- Monitoring and backtest show identical mapping, cutoff, formula, snapshot, and path evidence for identical inputs.

## Review Status

Approved for implementation and offline API/Vue/Playwright verification on `2026-09-02`; commit, push, deployment, dependency installation, and real provider access remain unauthorized.
