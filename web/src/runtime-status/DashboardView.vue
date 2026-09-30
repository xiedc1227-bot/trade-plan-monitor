<script setup lang="ts">
import { computed } from "vue";
import type { ConnectionStatus } from "../api/generated";
import { resolveApiFetch } from "../api/context";
import { createMarketIndexApi } from "../api/marketIndexes";
import MarketIndexDataStrip from "../components/market-index/MarketIndexDataStrip.vue";
import { useDashboardMarketIndexTrends } from "../composables/useDashboardMarketIndexTrends";
import { useRuntimeContext } from "./context";
import OverviewStatus from "./OverviewStatus.vue";
import PlanRow from "./PlanRow.vue";
const { store } = useRuntimeContext();
const marketIndexes = computed(() => store.snapshot?.marketIndexes ?? []);
const connectionStatus = computed<ConnectionStatus>(() =>
  store.transport === "LIVE" ? "CONNECTED" : store.transport === "CONNECTING" ? "UNKNOWN" : "DISCONNECTED",
);
const marketIndexTrends = useDashboardMarketIndexTrends({
  api: createMarketIndexApi(resolveApiFetch()),
  connectionStatus,
  observedAt: computed(() => store.snapshot?.observedAt ?? null),
  summaries: marketIndexes,
});
const counts = { actionable: "当前提醒", blocked: "受阻", stale: "陈旧", risk: "风险", lowZoneWatch: "低吸观察", normal: "正常" };
</script>

<template>
  <section class="runtime-page">
    <h1>监控总览</h1>
    <p v-if="store.error" role="status">{{ store.error }}</p>
    <OverviewStatus v-if="store.runtimeStatus" :status="store.runtimeStatus" :live="store.transport === 'LIVE' && !store.error" :no-active-plans="store.snapshot !== null && !store.snapshot.symbols.length" />
    <MarketIndexDataStrip
      :connection-status="connectionStatus"
      :indexes="marketIndexes"
      :market-turnover="store.snapshot?.marketTurnover ?? null"
      :trends="marketIndexTrends.trends.value"
      @retry-index="marketIndexTrends.refresh($event)"
    />
    <p v-if="!store.snapshot" role="status">正在读取监控快照。</p>
    <template v-else>
      <dl class="runtime-counts" aria-label="后端快照统计">
        <div v-for="(label, key) in counts" :key="key"><dt>{{ label }}</dt><dd>{{ store.snapshot.counts[key] }}</dd></div>
      </dl>
      <PlanRow v-for="row in store.snapshot.symbols" :key="`${row.symbol}:${row.activationRevision}`" :row="row" />
    </template>
  </section>
</template>
