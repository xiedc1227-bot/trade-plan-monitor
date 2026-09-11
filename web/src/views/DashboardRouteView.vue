<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";

import type { MarketIndexSnapshotView, MarketTurnoverSummaryView } from "../api/generated";
import { createMarketIndexApi } from "../api/marketIndexes";
import { useDashboardMarketIndexTrends } from "../composables/useDashboardMarketIndexTrends";
import DashboardView from "./DashboardView.vue";
import { useMonitorStore } from "../stores/monitor";

const router = useRouter();
const monitor = useMonitorStore();

const isLoadingSnapshot = computed(() => !monitor.hasSnapshot && monitor.unavailable === null);
const marketIndexes = computed<readonly MarketIndexSnapshotView[]>(
  () => monitor.marketIndexes as unknown as readonly MarketIndexSnapshotView[],
);
const marketTurnover = computed<MarketTurnoverSummaryView | null>(
  () => monitor.marketTurnover as unknown as MarketTurnoverSummaryView | null,
);
const marketIndexTrends = useDashboardMarketIndexTrends({
  api: createMarketIndexApi(),
  connectionStatus: computed(() => monitor.connectionStatus),
  observedAt: computed(() => monitor.observedAt),
  summaries: marketIndexes,
});

function selectSymbol(symbol: string): void {
  void router.push({ name: "stock-detail", params: { symbol } });
}
</script>

<template>
  <DashboardView
    :connection-status="monitor.connectionStatus"
    :counts="monitor.counts"
    :loading="isLoadingSnapshot"
    :market-indexes="marketIndexes"
    :market-index-trends="marketIndexTrends.trends.value"
    :market-turnover="marketTurnover"
    :symbols="monitor.symbols"
    :unavailable="monitor.unavailable"
    @select-symbol="selectSymbol"
    @retry-market-index="marketIndexTrends.refresh($event)"
  />
</template>
