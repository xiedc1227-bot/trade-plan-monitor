<script setup lang="ts">
import { computed, shallowRef } from "vue";

import type {
  ConnectionStatus,
  MarketIndexSnapshotView,
  MarketTurnoverSummaryView,
  MarketIndexOverviewResponse,
} from "../../api/generated";
import { dashboardMarketIndexIdentities } from "../../api/marketIndexIdentity";
import { overviewItemSnapshot } from "../../api/marketIndexOverview";
import type { DashboardMarketIndexTrend } from "../../composables/useDashboardMarketIndexTrends";
import { marketIndexDirection } from "./marketIndexChartOptions";
import MarketIndexTrendCard from "./MarketIndexTrendCard.vue";
import MarketTurnoverCard from "./MarketTurnoverCard.vue";

interface Props {
  connectionStatus: ConnectionStatus;
  indexes: readonly MarketIndexSnapshotView[];
  marketTurnover?: MarketTurnoverSummaryView | null;
  trends: Readonly<Record<MarketIndexSnapshotView["indexCode"], DashboardMarketIndexTrend>>;
  overview?: MarketIndexOverviewResponse | null;
  overviewCached?: boolean;
  overviewError?: string | null;
}

interface Emits {
  retryIndex: [indexCode: MarketIndexSnapshotView["indexCode"]];
}

const props = withDefaults(defineProps<Props>(), {
  marketTurnover: null,
});
const emit = defineEmits<Emits>();
const defaultIdentity = dashboardMarketIndexIdentities[0];
if (defaultIdentity === undefined) throw new Error("dashboard index identities cannot be empty");
const summariesByCode = computed(() =>
  new Map((props.overview === undefined ? props.indexes
    : (props.overview?.indexes ?? []).flatMap(item => {
      const snapshot = overviewItemSnapshot(item);
      return snapshot === null ? [] : [snapshot];
    })).map((item) => [item.indexCode, item] as const)),
);
const selectedItem = computed(() => props.overview === undefined ? undefined
  : props.overview?.indexes.find(item => item.indexCode === selectedIndexCode.value) ?? null);
const displayDate = computed(() => props.overview?.marketSession.displayTradeDate);
const titleDate = computed(() => !props.overview || displayDate.value === props.overview.marketSession.sessionDate
  ? "当日" : displayDate.value ?? "日期待确认");
const selectedIndexCode = shallowRef(defaultIdentity.indexCode);
const selectedIdentity = computed(
  () => dashboardMarketIndexIdentities.find(
    (identity) => identity.indexCode === selectedIndexCode.value,
  ) ?? defaultIdentity,
);

function formatSessionChange(value: string | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    signDisplay: "always",
    style: "percent",
  }).format(Number(value));
}

</script>

<template>
  <section class="index-strip" aria-labelledby="market-index-strip-title">
    <header class="index-strip__header">
      <h2 id="market-index-strip-title">主要指数走势 · {{ titleDate }}</h2>
      <p>已完成五分钟数据 · 虚线为昨收</p>
    </header>
    <div class="index-strip__surface">
      <div class="index-strip__selectors" role="group" aria-label="选择要查看的主要指数">
        <button
          v-for="identity in dashboardMarketIndexIdentities"
          :key="identity.indexCode"
          type="button"
          class="index-strip__selector"
          data-testid="market-index-selector"
          :aria-pressed="selectedIndexCode === identity.indexCode"
          :data-direction="marketIndexDirection(summariesByCode.get(identity.indexCode)?.sessionChangeRatio)"
          :data-health="summariesByCode.get(identity.indexCode)?.health ?? 'BLOCKED'"
          @click="selectedIndexCode = identity.indexCode"
        >
          <span>{{ identity.displayName }}</span>
          <strong>{{ formatSessionChange(summariesByCode.get(identity.indexCode)?.sessionChangeRatio) }}</strong>
        </button>
      </div>
      <div class="index-strip__content">
        <MarketIndexTrendCard
          :key="selectedIdentity.indexCode"
          :connection-status="connectionStatus"
          :identity="selectedIdentity"
          :summary="summariesByCode.get(selectedIdentity.indexCode) ?? null"
          :trend="trends[selectedIdentity.indexCode]"
          :item="selectedItem"
          :market-session="overview?.marketSession"
          :cached="overviewCached"
        />
        <MarketTurnoverCard :summary="overview === undefined ? marketTurnover : overview?.marketTurnover ?? null">
          <template v-if="overviewError || trends[selectedIdentity.indexCode].status === 'ERROR'" #actions>
            <div class="index-strip__retry">
              <p role="alert">{{ overviewError ?? trends[selectedIdentity.indexCode].error }}</p>
              <button type="button" @click="emit('retryIndex', selectedIdentity.indexCode)">重试</button>
            </div>
          </template>
        </MarketTurnoverCard>
      </div>
    </div>
  </section>
</template>

<style scoped>
.index-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-3);
  min-width: 0;
}

.index-strip > * {
  min-width: 0;
}

.index-strip__header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  align-items: baseline;
  justify-content: space-between;
}

.index-strip__header h2 { margin: 0; }
.index-strip__header p { font-size: .6875rem; }

.index-strip__header p {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--color-text-muted);
}

.index-strip__header > * {
  min-width: 0;
  overflow-wrap: anywhere;
}

.index-strip__surface {
  min-width: 0;
  overflow: hidden;
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-radius: var(--radius-panel);
}

.index-strip__selectors {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  min-width: 0;
  background: var(--color-border-quiet);
  border-block-end: var(--border-technical);
}

.index-strip__content {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(14rem, 18rem);
  min-width: 0;
}

.index-strip__retry {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-items: center;
  min-width: 0;
  text-align: center;
}

.index-strip__retry p {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--color-text-muted);
}

.index-strip__selector {
  position: relative;
  display: grid;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--space-4) var(--space-5);
  overflow-wrap: anywhere;
  color: var(--color-text-mineral);
  text-align: start;
  cursor: pointer;
  background: var(--color-surface-graphite);
  border: 0;
  border-radius: 0;
}

.index-strip__selector > span { font-size: .75rem; }
.index-strip__selector:hover { background: var(--color-surface-raised); }

.index-strip__selector::after {
  position: absolute;
  inset-inline: var(--space-3);
  inset-block-end: 0;
  height: .1875rem;
  content: "";
  background: transparent;
}

.index-strip__selector[aria-pressed="true"] {
  background: var(--color-surface-raised);
}

.index-strip__selector[aria-pressed="true"]::after {
  background: var(--color-signal-watch-amber);
}

.index-strip__selector strong {
  color: var(--color-text-muted);
  font-family: var(--font-numeric);
  font-size: 1.375rem;
  font-weight: 500;
}

.index-strip__selector[data-direction="down"] strong {
  color: var(--color-signal-live-sea-glass);
}

.index-strip__selector[data-direction="up"] strong {
  color: var(--color-signal-risk-vermilion);
}

.index-strip__selector[data-direction="flat"] strong {
  color: var(--color-text-mineral);
}

.index-strip__selector[data-health="BLOCKED"] strong,
.index-strip__selector[data-health="GAPPED"] strong {
  text-decoration: underline dotted;
}

@media (max-width: 39.999rem) {
  .index-strip__selectors {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .index-strip__selector { padding: var(--space-3) var(--space-4); }
}

@media (max-width: 69.999rem) {
  .index-strip__content {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
