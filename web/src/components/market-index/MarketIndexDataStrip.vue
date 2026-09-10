<script setup lang="ts">
import { computed } from "vue";

import type { MarketIndexSnapshotView } from "../../api/generated";
import { dashboardMarketIndexIdentities } from "../../api/marketIndexIdentity";
import type { DashboardMarketIndexTrend } from "../../composables/useDashboardMarketIndexTrends";
import MarketIndexTrendCard from "./MarketIndexTrendCard.vue";

interface Props {
  indexes: readonly MarketIndexSnapshotView[];
  trends: Readonly<Record<MarketIndexSnapshotView["indexCode"], DashboardMarketIndexTrend>>;
}

interface Emits {
  retryIndex: [indexCode: MarketIndexSnapshotView["indexCode"]];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();
const summariesByCode = computed(() =>
  new Map(props.indexes.map((item) => [item.indexCode, item] as const)),
);
</script>

<template>
  <section class="index-strip" aria-labelledby="market-index-strip-title">
    <header class="index-strip__header">
      <h2 id="market-index-strip-title">主要指数走势 · 当日</h2>
      <p>上证、深证、创业板、科创50 · 已完成五分钟数据 · 虚线为昨收</p>
    </header>
    <div class="index-strip__grid">
      <MarketIndexTrendCard
        v-for="identity in dashboardMarketIndexIdentities"
        :key="identity.indexCode"
        :identity="identity"
        :summary="summariesByCode.get(identity.indexCode) ?? null"
        :trend="trends[identity.indexCode]"
        @retry="emit('retryIndex', $event)"
      />
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

.index-strip__header p {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--color-text-muted);
}

.index-strip__header > * {
  min-width: 0;
  overflow-wrap: anywhere;
}

.index-strip__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

@media (max-width: 39.999rem) {
  .index-strip__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
