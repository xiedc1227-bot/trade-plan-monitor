<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import PageIntro from "../components/common/PageIntro.vue";
import ReferenceMarketPanel from "../components/market-index/ReferenceMarketPanel.vue";
import { useRuntimeContext } from "./context";
import PlanRow from "./PlanRow.vue";
import StatusBoard from "./StatusBoard.vue";
import HistoryPanel from "./HistoryPanel.vue";
import { useRuntimeRead } from "./useRuntimeRead";
const props = defineProps<{ symbol: string }>();
const { api, store } = useRuntimeContext();
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
</script>

<template>
  <section class="runtime-page">
    <PageIntro :title="`个股详情 · ${symbol}`" description="从当前判断到原始证据，逐项核对这份计划。" />
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
        <RouterLink :to="`/plans/${currentDetail.summary.planVersionId}`">查看计划与模拟仓位</RouterLink>
      </template>
      <p v-else>该股票当前没有活动计划。</p>
    </template>
  </section>
</template>
