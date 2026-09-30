<script setup lang="ts">
import { computed } from "vue";
import { useRuntimeContext } from "./context";
import PlanRow from "./PlanRow.vue";
import { useRuntimeRead } from "./useRuntimeRead";
const props = defineProps<{ symbol: string }>();
const { api, store } = useRuntimeContext();
const { value, error, loading } = useRuntimeRead((signal) => api.getExplicitRuntime(props.symbol, signal), [() => props.symbol, () => store.observedAt, () => store.snapshot]);
const row = computed(() => {
  if (!value.value || !("summary" in value.value) || !store.snapshot || value.value.runtimeGeneration !== store.snapshot.runtimeGeneration || value.value.sequence < store.snapshot.sequence) return null;
  const installed = store.snapshot.symbols.find(item => item.symbol === props.symbol);
  const summary = value.value.summary;
  return installed && installed.planVersionId === summary.planVersionId && installed.planHash === summary.planHash && installed.activationRevision === summary.activationRevision ? summary : null;
});
</script>

<template>
  <section aria-label="当前明确规则投影">
    <p v-if="loading" role="status">正在读取已持久化的明确规则结果。</p>
    <p v-else-if="error" role="status">{{ error }}</p>
    <PlanRow v-else-if="row" :row="row" detail />
    <p v-else>当前没有匹配的活动明确规则投影。</p>
  </section>
</template>
