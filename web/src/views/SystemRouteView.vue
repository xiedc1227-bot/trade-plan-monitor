<script setup lang="ts">
import { useRouter } from "vue-router";

import { createHealthApi, type HealthApi } from "../api/health";
import { useSystemHealth } from "../composables/useSystemHealth";
import SystemView from "./SystemView.vue";

interface Props {
  api?: HealthApi;
}

const props = defineProps<Props>();
const router = useRouter();
const healthApi = props.api ?? createHealthApi();
const { error, health, loading, refresh } = useSystemHealth({ api: healthApi });

function selectSymbol(symbol: string): void {
  void router.push({ name: "stock-detail", params: { symbol } });
}
</script>

<template>
  <SystemView
    :error="error"
    :health="health"
    :loading="loading"
    @refresh="refresh"
    @select-symbol="selectSymbol"
  />
</template>
