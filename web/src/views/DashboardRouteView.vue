<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";

import type { MarketIndexSnapshotView } from "../api/generated";
import DashboardView from "./DashboardView.vue";
import { useMonitorStore } from "../stores/monitor";

const router = useRouter();
const monitor = useMonitorStore();

const isLoadingSnapshot = computed(() => !monitor.hasSnapshot);
const marketIndexes = computed<readonly MarketIndexSnapshotView[]>(
  () => monitor.marketIndexes as unknown as readonly MarketIndexSnapshotView[],
);

function selectSymbol(symbol: string): void {
  void router.push({ name: "stock-detail", params: { symbol } });
}
</script>

<template>
  <DashboardView
    :connection-status="monitor.connectionStatus"
    :counts="monitor.counts"
    :data-age-seconds="monitor.dataAgeSeconds"
    :loading="isLoadingSnapshot"
    :market-indexes="marketIndexes"
    :observed-at="monitor.observedAt"
    :symbols="monitor.symbols"
    @select-symbol="selectSymbol"
  />
</template>
