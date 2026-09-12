<script setup lang="ts">
import { computed, shallowRef } from "vue";

import type {
  ActionableSignalType,
  ConnectionStatus,
  DashboardCounts,
  DashboardProjectionUnavailableResponse,
  MarketIndexSnapshotView,
  MarketTurnoverSummaryView,
  SignalType,
  SymbolSummaryView,
} from "../api/generated";
import WatchlistTable from "../components/dashboard/WatchlistTable.vue";
import WatchlistToolbar from "../components/dashboard/WatchlistToolbar.vue";
import ExplicitRuntimeDashboardPanel from "../components/dashboard/ExplicitRuntimeDashboardPanel.vue";
import MarketIndexDataStrip from "../components/market-index/MarketIndexDataStrip.vue";
import {
  emptyDashboardMarketIndexTrends,
  type DashboardMarketIndexTrend,
} from "../composables/useDashboardMarketIndexTrends";
import type {
  SortDirection,
  WatchlistFilter,
  WatchlistSort,
  WatchlistViewMode,
} from "../components/dashboard/WatchlistToolbar.vue";

interface Props {
  connectionStatus: ConnectionStatus;
  counts: DashboardCounts;
  error?: string | null;
  loading?: boolean;
  marketIndexes?: readonly MarketIndexSnapshotView[];
  marketTurnover?: MarketTurnoverSummaryView | null;
  marketIndexTrends?: Readonly<
    Record<MarketIndexSnapshotView["indexCode"], DashboardMarketIndexTrend>
  >;
  symbols: readonly SymbolSummaryView[];
  unavailable?: DashboardProjectionUnavailableResponse | null;
}

interface Emits {
  retryMarketIndex: [indexCode: MarketIndexSnapshotView["indexCode"]];
  selectSymbol: [symbol: string];
}

const props = withDefaults(defineProps<Props>(), {
  error: null,
  loading: false,
  marketIndexes: () => [],
  marketTurnover: null,
  marketIndexTrends: () => emptyDashboardMarketIndexTrends,
  unavailable: null,
});
const emit = defineEmits<Emits>();
defineSlots<{
  actionableRail?(props: { symbols: readonly SymbolSummaryView[] }): unknown;
}>();

const query = shallowRef("");
const filter = shallowRef<WatchlistFilter>("ALL");
const sort = shallowRef<WatchlistSort>("SYMBOL");
const sortDirection = shallowRef<SortDirection>("ASC");
const viewMode = shallowRef<WatchlistViewMode>("COMPACT");

const actionableSignalSet = new Set<SignalType>([
  "BUY_CORE_READY",
  "BUY_TACTICAL_READY",
  "PRESSURE_REDUCE_READY",
  "RISK_BREACH",
  "RISK_EXIT_READY",
  "RISK_EXIT_PENDING_SETTLEMENT",
] satisfies readonly ActionableSignalType[]);
const riskSignalSet = new Set<SignalType>([
  "RISK_BREACH",
  "RISK_EXIT_READY",
  "RISK_EXIT_PENDING_SETTLEMENT",
]);

const actionableSymbols = computed<readonly SymbolSummaryView[]>(() =>
  Object.freeze(props.symbols.filter((row) => actionableSignalSet.has(row.decision.signalType))),
);
const displayRows = computed<readonly SymbolSummaryView[]>(() => {
  const normalizedQuery = query.value.trim().toUpperCase();
  const filtered = props.symbols.filter(
    (row) =>
      matchesQuery(row, normalizedQuery) &&
      matchesFilter(row, filter.value),
  );
  return Object.freeze([...filtered].sort(compareRows));
});

function matchesQuery(row: SymbolSummaryView, normalizedQuery: string): boolean {
  return (
    normalizedQuery.length === 0 ||
    row.symbol.toUpperCase().includes(normalizedQuery) ||
    row.name.toUpperCase().includes(normalizedQuery)
  );
}

function matchesFilter(row: SymbolSummaryView, selected: WatchlistFilter): boolean {
  const signal = row.decision.signalType;
  const live =
    row.connected &&
    row.decision.dataHealth.status === "LIVE" &&
    row.decision.dataHealth.fresh;
  switch (selected) {
    case "ACTIONABLE":
      return actionableSignalSet.has(signal);
    case "BLOCKED":
      return signal === "BLOCKED_DATA" || signal === "BLOCKED_RISK";
    case "NORMAL":
      return live && (signal === "WAIT" || signal === "RISK_RECOVERED");
    case "RISK":
      return riskSignalSet.has(signal);
    case "STALE":
      return !live;
    case "WATCH":
      return signal === "LOW_ZONE_WATCH";
    case "ALL":
      return true;
  }
}

function compareRows(left: SymbolSummaryView, right: SymbolSummaryView): number {
  let compared: number;
  switch (sort.value) {
    case "HEALTH":
      compared = compareText(left.decision.dataHealth.status, right.decision.dataHealth.status);
      break;
    case "MARKET_TIME":
      compared = compareNullable(
        left.decision.marketDataAt,
        right.decision.marketDataAt,
        compareText,
      );
      break;
    case "PRICE":
      compared = compareNullable(left.decision.priceFen, right.decision.priceFen, compareNumber);
      break;
    case "RISK_DISTANCE":
      compared = compareNullable(left.riskDistanceFen, right.riskDistanceFen, compareNumber);
      break;
    case "SYMBOL":
      compared = compareText(left.symbol, right.symbol);
      break;
  }
  if (compared === 0) {
    return compareText(left.symbol, right.symbol);
  }
  if (sortValueIsNull(left) || sortValueIsNull(right)) {
    return compared;
  }
  return sortDirection.value === "ASC" ? compared : -compared;
}

function sortValueIsNull(row: SymbolSummaryView): boolean {
  return sort.value === "PRICE"
    ? row.decision.priceFen === null
    : sort.value === "RISK_DISTANCE"
      ? row.riskDistanceFen === null
      : sort.value === "MARKET_TIME"
        ? row.decision.marketDataAt === null
        : false;
}

function compareNullable<Value>(
  left: Value | null,
  right: Value | null,
  compare: (first: Value, second: Value) => number,
): number {
  if (left === null) {
    return right === null ? 0 : 1;
  }
  if (right === null) {
    return -1;
  }
  return compare(left, right);
}

function compareNumber(left: number, right: number): number {
  return left === right ? 0 : left < right ? -1 : 1;
}

function compareText(left: string, right: string): number {
  return left === right ? 0 : left < right ? -1 : 1;
}
</script>

<template>
  <section class="dashboard-view" aria-labelledby="dashboard-title">
    <header class="dashboard-view__header">
      <div>
        <h1 id="dashboard-title">监控总览</h1>
      </div>
      <p>只读权威快照 · 序列由监控 store 管理</p>
    </header>

    <p
      v-if="unavailable !== null"
      class="dashboard-view__unavailable"
      data-testid="dashboard-unavailable"
      role="status"
      aria-live="polite"
    >
      权威监控投影尚未就绪（{{ unavailable.reason }}，序列 {{ unavailable.sequence }}）。
    </p>

    <MarketIndexDataStrip
      :connection-status="connectionStatus"
      :indexes="marketIndexes"
      :market-turnover="marketTurnover"
      :trends="marketIndexTrends"
      @retry-index="emit('retryMarketIndex', $event)"
    />

    <ExplicitRuntimeDashboardPanel />

    <p v-if="error" class="dashboard-view__error" role="alert">{{ error }}</p>
    <p v-if="loading" class="dashboard-view__loading" role="status" aria-live="polite">
      正在刷新权威快照；已缓存行继续明确显示。
    </p>

    <section v-if="unavailable === null" class="dashboard-view__counts" aria-label="监控状态计数">
      <article data-testid="dashboard-count-actionable"><span>可执行</span><strong>{{ counts.actionable }}</strong></article>
      <article><span>低吸观察</span><strong>{{ counts.lowZoneWatch }}</strong></article>
      <article><span>阻断</span><strong>{{ counts.blocked }}</strong></article>
      <article><span>风险</span><strong>{{ counts.risk }}</strong></article>
      <article data-testid="dashboard-count-stale"><span>陈旧</span><strong>{{ counts.stale }}</strong></article>
      <article><span>正常</span><strong>{{ counts.normal }}</strong></article>
    </section>

    <WatchlistToolbar
      v-if="unavailable === null"
      v-model:filter="filter"
      v-model:query="query"
      v-model:sort="sort"
      v-model:sort-direction="sortDirection"
      v-model:view-mode="viewMode"
    />

    <p
      v-if="unavailable === null && !loading && !error && symbols.length === 0"
      class="dashboard-view__empty"
      data-testid="watchlist-empty"
    >
      尚无监控股票。请先激活至少一个计划。
    </p>
    <p
      v-else-if="unavailable === null && symbols.length > 0 && displayRows.length === 0"
      class="dashboard-view__empty"
      data-testid="watchlist-empty"
    >
      没有匹配当前条件的股票。
    </p>
    <WatchlistTable
      v-else-if="unavailable === null && displayRows.length > 0"
      :density="viewMode"
      :rows="displayRows"
      @select-symbol="emit('selectSymbol', $event)"
    />

    <aside
      v-if="unavailable === null && symbols.length > 0"
      class="dashboard-view__actionable-rail"
      aria-labelledby="actionable-rail-title"
    >
      <h2 id="actionable-rail-title">可执行提醒栏</h2>
      <slot name="actionableRail" :symbols="actionableSymbols">
        <p>当前有 {{ actionableSymbols.length }} 只股票具备后端权威可执行信号。</p>
      </slot>
    </aside>
  </section>
</template>

<style scoped>
.dashboard-view {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-5);
  width: 100%;
  min-width: 0;
  max-width: 100rem;
  margin: 0 auto;
}

.dashboard-view > * {
  min-width: 0;
  max-width: 100%;
}

.dashboard-view__header {
  display: flex;
  gap: var(--space-4);
  align-items: end;
  justify-content: space-between;
  border-block-end: var(--border-technical);
}

.dashboard-view__header h1,
.dashboard-view__header p {
  overflow-wrap: anywhere;
}

.dashboard-view__error,
.dashboard-view__loading,
.dashboard-view__empty,
.dashboard-view__unavailable {
  margin: 0;
  padding: var(--space-4);
  overflow-wrap: anywhere;
  background: var(--color-surface-raised);
  border-inline-start: 0.25rem solid var(--color-signal-watch-amber);
}

.dashboard-view__error {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.dashboard-view__counts {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--space-3);
}

.dashboard-view__counts article {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-3);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.dashboard-view__counts strong {
  font-family: var(--font-numeric);
  font-size: 1.5rem;
}

.dashboard-view__actionable-rail {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border-inline-start: 0.25rem solid var(--color-signal-watch-amber);
}

@media (max-width: 63.999rem) {
  .dashboard-view__counts {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 39.999rem) {
  .dashboard-view__header {
    align-items: start;
    flex-direction: column;
  }

  .dashboard-view__counts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
