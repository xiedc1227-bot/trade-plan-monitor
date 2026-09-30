<script setup lang="ts">
import { computed } from "vue";
import { createPositionApi } from "../api/positions";
import { createManualEventRiskApi } from "../api/manualEventRisk";
import PositionLots from "../components/symbol/PositionLots.vue";
import PositionInventoryPanel from "../components/symbol/PositionInventoryPanel.vue";
import ManualEventRiskPanel from "../components/symbol/ManualEventRiskPanel.vue";
import ReferenceMarketPanel from "../components/market-index/ReferenceMarketPanel.vue";
import type { PositionOperations } from "../composables/usePositions";
import { useRuntimeContext } from "./context";
import PlanRow from "./PlanRow.vue";
import StatusBoard from "./StatusBoard.vue";
import HistoryPanel from "./HistoryPanel.vue";
import { useRuntimeRead } from "./useRuntimeRead";
const props = defineProps<{ symbol: string }>();
const { api, store } = useRuntimeContext();
const positionApi = createPositionApi();
const manualApi = createManualEventRiskApi();
const operations: PositionOperations = {
  closePosition: ({ command, idempotencyKey }) => positionApi.closePosition(command, idempotencyKey),
  createPosition: ({ command, idempotencyKey }) => positionApi.createPosition(command, idempotencyKey),
  listPositions: (request) => positionApi.listPositions(request),
};
const { value: detail, error, loading } = useRuntimeRead((signal) => api.getSymbol(props.symbol, signal), [() => props.symbol, () => store.observedAt, () => store.snapshot]);
const currentDetail = computed(() => {
  const value = detail.value;
  const snapshot = store.snapshot;
  if (!value || !snapshot || value.runtimeGeneration !== snapshot.runtimeGeneration || value.sequence < snapshot.sequence) return null;
  if (!("summary" in value)) return value;
  const installed = snapshot.symbols.find(row => row.symbol === props.symbol);
  return installed && installed.planVersionId === value.summary.planVersionId && installed.planHash === value.summary.planHash &&
    installed.activationRevision === value.summary.activationRevision ? value : null;
});
const asOfTradeDate = computed(() => currentDetail.value?.observedAt.slice(0, 10) ?? null);
</script>

<template>
  <section class="runtime-page">
    <h1>个股详情 · {{ symbol }}</h1>
    <p v-if="loading" role="status">正在读取当前计划投影。</p>
    <p v-if="error" role="status">{{ error }}</p>
    <template v-if="currentDetail">
      <StatusBoard :status="currentDetail.runtimeStatus" />
      <template v-if="'summary' in currentDetail">
        <PlanRow :row="currentDetail.summary" detail />
        <ReferenceMarketPanel v-if="currentDetail.legacyDetails && currentDetail.summary.availability !== 'UNAVAILABLE' && currentDetail.summary.planFamily === 'LEGACY_LOW_BUY'"
          :plan="currentDetail.summary.decision" :reference="currentDetail.legacyDetails.referenceMarket" :evidence="currentDetail.legacyDetails.indexConditionEvidence" />
        <HistoryPanel :symbol="symbol" :observed-at="currentDetail.observedAt"
          :decision="currentDetail.summary.availability !== 'UNAVAILABLE' && currentDetail.summary.planFamily === 'LEGACY_LOW_BUY' ? currentDetail.summary.decision : null"
          :stale="currentDetail.summary.availability !== 'CURRENT' || store.transport !== 'LIVE'" />
        <PositionLots v-if="asOfTradeDate" :symbol="symbol" :as-of-trade-date="asOfTradeDate" :operations="operations" />
        <PositionInventoryPanel :symbol="symbol" :as-of-trade-date="asOfTradeDate" :api="positionApi" />
        <ManualEventRiskPanel :symbol="symbol" :api="manualApi" />
      </template>
      <p v-else>该股票当前没有活动计划。</p>
    </template>
  </section>
</template>
