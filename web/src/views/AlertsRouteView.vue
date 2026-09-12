<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, shallowRef } from "vue";

import type { AlertPage } from "../api/generated";
import { createAlertApi, type AlertApi, type AlertListRequest } from "../api/alerts";
import { useMonitorStore, type MonitorEventEnvelope } from "../stores/monitor";
import AlertsView from "./AlertsView.vue";
import type { AlertOperations, AlertQuery } from "./AlertsView.vue";

interface Props {
  readonly api?: AlertApi;
}

const props = defineProps<Props>();
const api = props.api ?? createAlertApi();
const monitor = useMonitorStore();
const initialPage = shallowRef<AlertPage | null>(null);
const initialLoading = shallowRef(true);
const initialController = new AbortController();
const emptyLiveEvents = Object.freeze([]) as readonly MonitorEventEnvelope[];
const defaultQuery: AlertQuery = Object.freeze({
  acknowledged: null,
  endAt: null,
  limit: 20,
  offset: 0,
  signalType: null,
  startAt: null,
  symbol: null,
});
const operations: AlertOperations = Object.freeze({
  acknowledgeAlert: (
    { command, idempotencyKey }: Parameters<AlertOperations["acknowledgeAlert"]>[0],
  ) => api.acknowledgeAlert(command, idempotencyKey),
  listAlerts: (query: AlertQuery) => api.listAlerts(query as AlertListRequest),
});
const liveEvents = computed<readonly MonitorEventEnvelope[]>(() => {
  const latest = monitor.lastEvent as MonitorEventEnvelope | null;
  return latest === null ? emptyLiveEvents : Object.freeze([latest]);
});

onMounted(async () => {
  try {
    initialPage.value = await api.listAlerts(defaultQuery, {
      signal: initialController.signal,
    });
  } catch {
    initialPage.value = null;
  } finally {
    initialLoading.value = false;
  }
});

onBeforeUnmount(() => {
  initialController.abort();
});
</script>

<template>
  <AlertsView
    :initial-loading="initialLoading"
    :initial-page="initialPage"
    :alert-refresh-revision="monitor.alertRefreshRevision"
    :live-events="liveEvents"
    :operations="operations"
  />
</template>
