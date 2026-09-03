# Proposal: Shared Board-Index Data with Plan-Owned Usage

> Status: **APPROVED — IMPLEMENTATION AUTHORIZED**
> Approval date: `2026-09-02`. A later request on the same date authorized paired module specifications, code/API/schema/document changes, and offline verification. Commit, push, dependency installation, deployment, and real provider network calls remain unauthorized.

## Objective

Add board-index data to monitoring and backtesting while keeping the responsibility boundary explicit:

- The tool selects the stock's reference board index, fetches and validates its data, calculates reusable numeric facts, and exposes the same data to all plans that reference that index.
- The tool does not assign one universal market judgment and does not secretly block, allow, or change a trade.
- Each trade plan decides whether to use index data, which conditions to check, where those conditions belong, and how their results participate in the plan.

The Web UI must let a user answer these questions without reading logs:

1. Which board index is attached to the stock, and which mapping rule selected it?
2. What index data and reusable indicator facts were available at the decision cutoff?
3. Which index conditions are written in this plan, and what was each condition's result?
4. Did missing index data affect this plan, or was the index only informational?
5. Did monitoring and backtesting use the same data, formulas, cutoffs, and plan conditions?

## Confirmed Design Direction

### C1 — The tool owns data, not trading policy

The tool may provide index identity, bars, latest completed values, data health, moving averages, returns, timestamps, and hashes. These are data facts. The tool must not convert them into one shared “market is strong/weak” result that automatically controls every stock.

### C2 — The plan owns usage

A plan may place index conditions under `entry`, `reduction`, `risk`, or `blockers`, subject to the existing policy-tree rules. A plan may also contain no index condition. The condition's location and surrounding `ALL`/`ANY` structure determine its effect.

### C3 — Data is shared; condition results are plan-specific

Stocks mapped to the same index and evaluated at the same cutoff use the same immutable data snapshot. Two plans can evaluate that snapshot differently because their conditions or thresholds differ. Their condition evidence and final decisions are never shared.

### C4 — Board mapping is automatic

The reference index is selected from the validated stock code. The user and AI do not choose an arbitrary board benchmark in the first version.

### C5 — Monitoring and backtesting both show the data

Both functions display the reference index and its data. Plan-condition results are displayed separately from the shared index data so the user can distinguish “what the market data was” from “what this plan concluded.”

## Approved Assumptions

- **A1:** Phase 1 covers board indices. Industry indices are a later capability because the industry-classification source and mapping rules are not yet approved.
- **A2:** ChiNext and STAR Market are separate boards and use separate reference indices.
- **A3:** Existing `.BJ` stock support remains in scope, so BSE stocks use BSE 50.
- **A4:** The tool may calculate deterministic reusable facts such as SMA and period return. A fact has no trading effect until a plan condition references it.
- **A5:** Index conditions may appear in any supported policy tree. The tree location, not the condition type alone, determines its use.
- **A6:** Existing Schema v1 plans remain unchanged. A plan needs Schema v2 before it can store index binding and index conditions.
- **A7:** Intraday evidence uses only certified completed five-minute buckets. An unfinished minute or tick value is display-only and cannot satisfy a condition.
- **A8:** Monitoring and backtesting use the same mapping, validated bars, formulas, condition evaluator, cutoffs, and evidence format.

The user approved all eight assumptions on `2026-09-02`. A later material change requires a new design review and, when it changes the accepted architecture, a superseding ADR.

## Capability Map

| Module id | Responsibility | Depends on |
|---|---|---|
| `index-identity` | Closed index-code type, stock-board classification, and versioned mapping | — |
| `index-data` | Live and historical index bars, validation, reusable facts, shared cache, health, and hashes | `index-identity` |
| `plan-index-conditions` | Schema v2 binding, permitted condition types, validation, and evidence evaluation | `index-identity`, `index-data` |
| `monitor-index-view` | Shared dashboard data, plan-specific progress, detail evidence, and invalidation | `plan-index-conditions` |
| `backtest-index-data` | Historical coverage, warm-up, dataset identity, and deterministic replay input | `plan-index-conditions` |
| `backtest-index-view` | Run form, shared series, condition summaries, details, and exports | `backtest-index-data` |

Approved module-specification dependency order:

```text
index-identity
    -> index-data
        -> plan-index-conditions
            -> monitor-index-view
            -> backtest-index-data
                -> backtest-index-view
```

## Fixed Board-to-Index Mapping

Mapping version: `board-index-map-v1`.

| Stock classification | Deterministic stock rule | Reference index | Internal index code |
|---|---|---|---|
| SSE Main Board | `.SH`, except codes starting with `688` or `689` | SSE Composite Index | `000001.SH` |
| SZSE Main Board | `.SZ`, except codes starting with `300` or `301` | Shenzhen Component Index | `399001.SZ` |
| ChiNext | `.SZ` and code starts with `300` or `301` | ChiNext Index | `399006.SZ` |
| STAR Market | `.SH` and code starts with `688` or `689` | STAR 50 Index | `000688.SH` |
| BSE | `.BJ` | BSE 50 Index | `899050.BJ` |

Rules:

- Classification uses the validated stock code, not a company name, AI output, index membership, or a remote classification result.
- The index is a board reference. The stock does not need to be an index constituent.
- An unclassifiable code fails validation. The tool must not guess another index.
- `mappingVersion` and the resolved `indexCode` are immutable plan content and participate in the plan hash.
- A mapping change requires a new mapping version and a new plan version.

Reference sources for the candidate mapping:

- SSE technical material lists SSE Composite `000001` and STAR 50 `000688`: <https://www.sse.com.cn/services/tradingtech/data/c/10762484/files/152e4250c3e2406faa232b75b1da8143.pdf>
- CNI Index lists Shenzhen Component `399001` and ChiNext `399006`: <https://www.cnindex.com.cn/zh_indices/sese/scale/index.html?act_menu=0&index_type=100>
- BSE identifies BSE 50 as `899050`: <https://www.bse.cn/important_news/200013826.html>

## Tool Data Contract

### Shared raw facts

For each required reference index and decision cutoff, the tool provides one immutable snapshot containing:

- index code, display name, and board identity;
- latest certified completed five-minute OHLC values at or before the cutoff;
- official daily OHLC values required by the plan's longest lookback;
- prior close and, only when provider semantics are verified, volume or amount;
- completed-bucket cutoff, source observation time, official/provisional source marker, and provider revision;
- data health and exact missing, stale, duplicate, gap, identity, or future-data errors;
- mapping version, content revision, and snapshot hash.

All index-point and ratio values cross Python, JSON, and TypeScript boundaries as canonical decimal strings. Binary floating-point values are not authoritative evidence.

### Generic derived facts

The tool may calculate versioned, deterministic facts that several plans can reuse:

- simple moving average for an allowed period;
- change in that moving average over an allowed lookback;
- return over an allowed window;
- current value compared with a named prior value.

Each fact records its formula id, parameters, input cutoff, result, unit, source-bar hash, and health. These remain numeric facts. They do not contain a universal market label or an automatic decision effect.

## Approved Plan Condition DSL Direction

The first version may add these approved condition leaves to the existing plan allow-list. Exact request and storage schemas still belong in module specifications:

| Condition type | Exact test |
|---|---|
| `INDEX_CLOSE_GTE_MA` | Completed index close is greater than or equal to the selected SMA |
| `INDEX_CLOSE_LTE_MA` | Completed index close is less than or equal to the selected SMA |
| `INDEX_MA_NON_DECREASING` | Selected SMA now is greater than or equal to its value at the lookback point |
| `INDEX_MA_NON_INCREASING` | Selected SMA now is less than or equal to its value at the lookback point |
| `INDEX_RETURN_GTE` | Index return over the selected window is greater than or equal to the threshold |
| `INDEX_RETURN_LTE` | Index return over the selected window is less than or equal to the threshold |

Allowed parameters:

- `index_role`: fixed to `BOARD_REFERENCE` in Phase 1;
- `period`: SMA period from 2 to 250 official open days;
- `lookback`: comparison distance from 1 to 60 official open days;
- `window`: `FIVE_MINUTE_BUCKETS` or `OFFICIAL_OPEN_DAYS`;
- `window_size`: 1 to 250;
- `threshold_ratio`: canonical decimal ratio from `-1` to `10`, inclusive.

The existing policy-tree limits still apply: maximum nesting depth 4 and maximum 50 condition leaves. Each leaf returns the existing result `SATISFIED`, `UNSATISFIED`, or `MISSING_INPUT`.

There is no shared market-condition result. For example, one plan can require close at or above SMA20, while another requires only a five-day return above `-0.03`. Both read the same snapshot and can produce different results.

## Approved Plan Contract Direction

Schema v2 will add a read-only, automatically resolved reference-market binding. Exact serialization still belongs in the module specification:

```yaml
schema_version: 2
reference_market:
  selection: AUTO_BOARD
  mapping_version: board-index-map-v1
  index_code: 000688.SH
```

An index condition uses the same structure as another allowed plan condition. Example:

```yaml
entry:
  conditions:
    operator: ALL
    items:
      - type: NON_DECREASING_CLOSE
        lookback: 3
      - type: INDEX_CLOSE_GTE_MA
        index_role: BOARD_REFERENCE
        period: 20
      - type: INDEX_MA_NON_DECREASING
        index_role: BOARD_REFERENCE
        period: 20
        lookback: 5
```

Another plan may put an index condition under `reduction`, `risk`, or `blockers`, or may omit index conditions entirely.

Rules:

- The draft service derives `index_code` from the stock code and approved mapping.
- The user and AI cannot supply another benchmark code in Phase 1.
- AI extraction may extract an index rule stated in the source plan, but it may not invent a condition, threshold, code, or formula.
- Import and activation recompute the binding and reject a mismatch.
- The binding and every condition participate in canonical JSON and the immutable plan hash.

## Decision Execution

For each decision target:

```text
shared index snapshot + this plan's condition tree
    -> evaluate only the index leaves used by this plan
        -> combine them with stock leaves using the existing ALL/ANY rules
            -> apply the existing policy priority
                -> persist authoritative decision evidence
```

Condition placement determines behavior. An index leaf under `entry` can affect an entry branch. The same leaf under `risk` can affect a risk branch. The evaluator must not attach an extra hidden rule outside the plan tree.

Each index-condition evidence item includes:

- exact plan path and condition type;
- index code, mapping version, and snapshot hash;
- decision cutoff and data cutoff;
- formula id and parameters;
- actual values, comparison value, period/window, and unit;
- `SATISFIED`, `UNSATISFIED`, or `MISSING_INPUT`;
- exact missing-input codes when applicable.

## Runtime Data Flow

```text
active plans
    -> resolve distinct reference index codes (maximum 5)
        -> fetch and validate each index once per cutoff
            -> publish one immutable shared data snapshot per index
                -> each plan evaluates only its own index-condition leaves
                    -> persist plan-specific evidence and final decision
                        -> display shared data and plan results separately
```

Specific consequences:

- Five ChiNext stocks at the same cutoff use one validated `399006.SZ` data snapshot.
- A plan with no index condition is not blocked or changed when index data is unavailable; the UI may still show the index as information.
- A plan that requires index data receives `MISSING_INPUT` only on the affected condition paths.
- One bad index response affects only the mapped board; other index snapshots continue normally.
- No consumer may mutate a shared snapshot or add a plan result to it.

## Provider Feasibility Gate

The repository currently proves stock-minute and stock-daily adapters. It does not yet prove that the configured provider account supplies the required index data. Before implementation approval, one authorized read-only probe must verify:

- exact daily and intraday index endpoints;
- support for all five approved codes;
- index identity, timestamps, OHLC, prior close, and any volume/amount fields;
- historical range and the longest supported warm-up;
- update delay, quota, account permission, and response-size limits;
- compatible meanings between live and historical point/timestamp fields.

The probe must never copy a token into a report or log. If certified five-minute index data is unavailable, the design returns to review. The implementation must not silently use a stock endpoint, unfinished quote, synthetic constituent aggregation, or daily-only substitute.

## Data and Persistence Design

Use index-specific types rather than weakening stock types:

- `MarketIndexCode`: closed codes approved by `board-index-map-v1`.
- `MarketIndexBar`: validated index OHLC and provenance at an exact cutoff.
- `MarketIndexHealth`: `LIVE`, `STALE`, `GAPPED`, or `BLOCKED`, with exact issue codes.
- `MarketIndexIndicatorFact`: formula id, parameters, decimal result, unit, cutoff, and source hash.
- `MarketIndexSnapshot`: identity, raw facts, requested reusable facts, health, revision, and content hash.
- `IndexConditionEvidence`: plan path, input identity, facts, comparison, outcome, and missing inputs.

Live storage may deduplicate snapshots across stocks. Every persisted decision still stores enough immutable identity to prove which snapshot and formulas were used. A backtest dataset hash covers all index bars and fact definitions that can affect that run.

## Approved Web API Direction

These names and boundaries were approved design inputs for module specifications and were implemented through the separately authorized `2026-09-02` offline change. They may change only through an explicit specification review that preserves the accepted architecture.

### Shared monitoring data

`DashboardResponse.marketIndexes` contains at most five unique items:

```json
{
  "indexCode": "000688.SH",
  "displayName": "科创50",
  "board": "STAR_MARKET",
  "closePoints": "1234.56",
  "priorClosePoints": "1220.11",
  "sessionChangeRatio": "0.011843",
  "completedBucketAt": "2026-09-02T10:35:00+08:00",
  "observedAt": "2026-09-02T10:35:02+08:00",
  "health": "LIVE",
  "indicatorFacts": [
    {
      "formulaId": "SMA",
      "period": 20,
      "value": "1212.34",
      "sourceBarHash": "<sha256>"
    }
  ],
  "mappingVersion": "board-index-map-v1",
  "revision": 42,
  "snapshotHash": "<sha256>"
}
```

This shared item must not contain a universal market label, `entryAllowed`, or `decisionEffect`.

`SymbolSummaryView` and `SymbolDetailResponse` add nullable `referenceMarket` during migration:

```json
{
  "indexCode": "000688.SH",
  "snapshotHash": "<sha256>",
  "dataAt": "2026-09-02T10:35:00+08:00",
  "health": "LIVE",
  "conditionProgress": {
    "satisfied": 2,
    "unsatisfied": 1,
    "missing": 0,
    "total": 3
  }
}
```

The summary contains counts only. Complete meaning stays in server-authored decision evidence addressed by exact condition path.

### Index history

- `GET /api/v1/market-indexes/{indexCode}/bars`
- Required query: `interval`, `startAt`, `endAt`, and `limit`
- Signed cursor pagination for more pages
- At most 2,000 validated points per page and one bounded date range
- Unknown, unapproved, or mismatched codes use the existing safe error envelope

### Backtest projections

- `BacktestRunView.referenceMarket` stores binding, coverage, dataset hash, and the condition paths used by the run.
- `BacktestAuthoritativeDecisionView.referenceMarket` stores snapshot identity and complete path-level evidence.
- `GET /api/v1/backtest-runs/{runId}/market-index-series` returns at most 512 daily display points plus per-condition outcome counts. Exact five-minute evidence remains in paginated decision details.
- The formal export includes binding, index-data hash, formula hashes, condition paths, and outcome counts.

### Invalidation

Add `market.index.updated` to the WebSocket event union:

```json
{
  "entityId": "000688.SH",
  "revision": 42,
  "status": "LIVE"
}
```

The event only tells the browser to refetch authoritative data. The browser does not build snapshots or evaluate conditions from an event.

## Monitoring Web Design

### Dashboard

Place a “Reference board indices” strip below connection/data-age status. For each index used by active monitored stocks, show:

- display name, code, latest completed value, session change, cutoff, and health;
- requested reusable facts, such as SMA20, without an automatic interpretation;
- the number of monitored stocks mapped to the index.

The watchlist adds “Reference index” and “Plan index conditions” columns. The second column shows satisfied/total and missing counts for that stock's active plan. It does not show one universal board judgment.

### Symbol detail

Show two separate sections:

1. **Reference-index data:** board mapping, index identity, raw values, reusable facts, cutoff, health, and separate index chart.
2. **Plan index conditions:** exact plan path, condition type, parameters, input facts, result, and missing reason for every used leaf.

Stock and index charts remain separate because their units and scales differ.

### Loading and failure states

- A cached snapshot may remain visible while refreshing, but its original cutoff and current health must remain visible.
- An index failure remains visible and does not disappear from the strip.
- Failure of one board index does not replace or hide healthy indices.
- A plan with no index condition shows “not used by plan” and zero condition progress; index failure does not change its stock decision.
- Text and icons accompany color. Keyboard access, table captions, live announcements, and 320/768/1024/1440-pixel layouts remain required.

### Dashboard layout sketch

```text
┌ Monitoring overview ──────────────────────────────────────────────────────┐
│ Connected · snapshot 10:35:02                                            │
├ Reference board indices: shared data ─────────────────────────────────────┤
│ SSE Composite 000001.SH  3,418.22 +0.42%  cutoff 10:35  LIVE  SMA20 3,390│
│ ChiNext      399006.SZ   2,164.08 -0.71%  cutoff 10:35  LIVE  SMA20 2,180│
├ Watchlist ────────────────────────────────────────────────────────────────┤
│ Stock       Signal   Reference index       Plan index conditions          │
│ 300xxx.SZ  WAIT     ChiNext 399006.SZ     satisfied 2/3 · missing 0      │
│ 688xxx.SH  WAIT     STAR 50 000688.SH     not used by plan               │
└───────────────────────────────────────────────────────────────────────────┘
```

Values in the sketch illustrate layout only and are not market facts or defaults.

## Backtest Web Design

### New-run form and dataset check

After plan and stock selection, show the resolved index, mapping version, and every index-condition path. Require index history and warm-up only when the plan actually uses an index condition. The required warm-up is derived from that plan's longest period, lookback, and window, not from one global fixed number.

### Completed-run summary

Show:

- reference-index binding and index dataset hash;
- each condition path, type, parameters, and formula id;
- satisfied, unsatisfied, and missing counts for each condition;
- how often each condition participated in an applicable policy branch.

Do not invent one run-level market classification.

### Reference-index tab

Provide a separate index/indicator chart, data-health timeline, and daily counts for each plan condition. Selecting a date opens the exact decisions and five-minute evidence that produced those counts.

### Decision details and export

Each decision shows the exact condition path, cutoff, input facts, comparison, result, and snapshot/formula hashes. The formal export carries the same content so a result can be audited without a live service.

### Backtest layout sketch

```text
┌ Completed backtest · reference index: STAR 50 000688.SH ────────────────┐
│ [Summary] [Reference index] [Fills] [Decisions] [Equity]                │
├ Plan index-condition results ───────────────────────────────────────────┤
│ entry.conditions[1] INDEX_CLOSE_GTE_MA(20)                              │
│ satisfied 8,420 · unsatisfied 3,510 · missing 0                         │
│ entry.conditions[2] INDEX_MA_NON_DECREASING(20, lookback 5)             │
│ satisfied 7,980 · unsatisfied 3,950 · missing 0                         │
├ Reference-index tab ────────────────────────────────────────────────────┤
│ Separate index and indicator chart · select a date for exact decisions  │
└─────────────────────────────────────────────────────────────────────────┘
```

Values in the sketch illustrate layout only and are not backtest results.

## Vue Component Map

Use Vue 3 Composition API and `<script setup lang="ts">`. Route pages compose focused components; they do not contain the entire feature.

| Component/composable | Single responsibility |
|---|---|
| `MarketIndexDataStrip.vue` | Display bounded shared index facts and health |
| `IndexConditionProgress.vue` | Display plan-specific satisfied/total/missing counts |
| `ReferenceMarketPanel.vue` | Display one stock's mapping and shared data identity |
| `MarketIndexChart.vue` | Display validated index series without evaluating plan conditions |
| `BacktestIndexConditionSummary.vue` | Display per-path backtest outcome counts |
| `BacktestMarketIndexPanel.vue` | Compose backtest chart, health, and date navigation |
| `useMarketIndexSeries.ts` | Manage bounded requests, cancellation, loading, and safe errors |

Props carry read-only data down. User navigation or filtering emits events up. Components must not derive the mapping, evaluate a condition, alter policy priority, or render untrusted HTML.

## Backtest Determinism and Bias Controls

- A stock decision may use only index data whose cutoff is not later than that decision target.
- Future official closes, unfinished buckets, and future constituent information are forbidden.
- Warm-up bars earlier than the visible test range still participate in dataset identity.
- Monitoring and replay call the same pure fact and condition evaluators.
- Changing any relevant index bar, mapping, formula, condition, or cutoff changes the run identity and report hash.
- A completed result cannot be reused when stock data matches but relevant index data differs.
- Board classification comes from the stock code, not today's index membership, avoiding constituent survival bias.

## Failure and Safety Rules

- Provider responses are untrusted and are validated at the adapter boundary.
- Mixed stock/index identity, duplicates, noncanonical decimals, bad cutoffs, future data, or formula mismatch fail closed.
- Missing index data creates `MISSING_INPUT` only for plan paths that require it.
- A plan with no index condition continues with its original behavior.
- One index failure cannot stop other boards.
- The Web UI cannot reuse an earlier condition result with newer or missing data.
- Logs, errors, APIs, and exports must not expose provider tokens or unnecessary raw responses.

## Migration

1. Existing Schema v1 plans and historical results remain unchanged; `referenceMarket` is `null`.
2. A new draft may be converted to Schema v2 with the automatic binding.
3. Index conditions are added only when they exist in the source plan or the user explicitly reviews them.
4. The user activates a new immutable version after review.
5. Historical results are not rewritten with later index data or conclusions.

No runtime configuration change may silently add index conditions to an already hashed active plan.

## Verification Strategy

### Unit tests

- Every permitted stock-code pattern maps to exactly one board index; invalid combinations fail.
- Every condition implements the documented equality boundary and parameter bounds.
- Missing, stale, gapped, future, or mismatched inputs return `MISSING_INPUT`.
- Two plans can produce different condition outcomes from the same snapshot.
- A plan without index conditions has unchanged decision behavior.

### Integration tests

- Ten stocks sharing one index cause one provider request per cutoff.
- Board failures and health are isolated.
- Monitoring and backtesting produce byte-stable facts and condition evidence for identical inputs.
- Changing a relevant data point or formula changes the dataset and report hashes.
- Index coverage blocks a backtest only when its plan uses an index condition.
- An authorized capability probe verifies required provider fields and coverage without exposing a token.

### Frontend tests

- Shared data and plan-specific condition results are visibly separated.
- No dashboard, detail, or backtest view displays a universal market classification.
- A plan without index conditions displays “not used by plan” and remains unaffected by index failure.
- Backtest summaries, charts, details, and exports use matching index and path identities.
- Loading, cached, stale, missing, empty, narrow-screen, keyboard, and screen-reader states are covered.
- `vue-tsc`, unit tests, production build, Playwright, and axe-core pass with no serious or critical accessibility findings.

### Acceptance criteria

- Stocks on the same board share one exact index-data snapshot per cutoff.
- Every trade effect caused by index data can be traced to an explicit condition path in that plan.
- Removing all index conditions from a plan removes all index influence on its decisions.
- Monitoring and backtesting show the same index identity, values, cutoffs, formulas, and evidence for the same input.
- The browser displays server-authored facts and results and does not evaluate trading policy.

## Boundaries

- **Always:** version mappings and formulas; preserve exact cutoffs; display health and time; hash decision-relevant input; keep shared data immutable.
- **Confirm first:** capability map, Schema v2, condition allow-list and bounds, new API fields/endpoints, report changes, and provider capability.
- **Forbidden:** hidden market gates; arbitrary AI-selected benchmarks; unfinished or future bars; stock bars treated as index bars; browser-side condition evaluation; silent changes to active plans.

## Out of Scope

- Industry-index classification and industry-rotation rules.
- User-selected arbitrary benchmark indices.
- Market breadth, advance/decline counts, valuation, news, fund flow, or AI market scores.
- Account-wide industry exposure limits.
- Broker orders or automatic trading.
- A composite score built from several indices.

The design keeps an explicit index-role boundary so an approved industry-index capability can be added later without changing board-index identity.

## Approved Decisions

The user approved all five decisions on `2026-09-02`:

1. **D1 — Placement:** The six index condition types may appear under all supported policy trees (`entry`, `reduction`, `risk`, and `blockers`).
2. **D2 — Allow-list:** The six condition types and parameter bounds in this proposal are approved for module specifications.
3. **D3 — Migration:** Index bindings and conditions use explicit Schema v2 migration; Schema v1 plans are not changed silently.
4. **D4 — BSE:** `.BJ` stocks use BSE 50 `899050.BJ`.
5. **D5 — Scope:** Phase 1 covers board-index data. Industry indices remain a separately reviewed capability.

The paired module specifications and offline implementation were separately authorized on `2026-09-02`. Commit, push, dependency installation, deployment, and a real provider network call remain unauthorized.
