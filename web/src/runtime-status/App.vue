<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, provide, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { apiFetchKey } from "../api/context";
import type { MonitorStreamConnectionState } from "../composables/useMonitorStream";
import AppShell from "../layouts/AppShell.vue";
import { shellConnectionKey } from "../layouts/connection";
import { createRuntimeApi } from "./client";
import { runtimeContextKey } from "./context";
import { createMonitorProtocol } from "./protocol";
import { useRuntimeMonitorStore } from "./store";
import { createRuntimeMonitor } from "./stream";
import { createInitialResultStartup, initialResultSettledKey } from "./initialResultStartup";
import { isRuntimeHealth } from "./validators";

const props = defineProps<{ fetchImplementation?: typeof fetch; createSocket?: (url: string) => WebSocket }>();
const route = useRoute();
const router = useRouter();
const store = useRuntimeMonitorStore();
const protocol = createMonitorProtocol({ origin: window.location.origin, validateHealth: isRuntimeHealth,
  ...(props.fetchImplementation ? { fetchImplementation: props.fetchImplementation } : {}),
  onReloadRequired: () => monitor.reloadRequired() });
const api = createRuntimeApi(protocol);
const monitor = createRuntimeMonitor({ api, protocol, store, origin: window.location.origin,
  ...(props.createSocket ? { createSocket: props.createSocket } : {}) });
const startup = createInitialResultStartup(monitor.start);
provide(initialResultSettledKey, startup.settled);
provide(apiFetchKey, protocol.fetch);
provide(runtimeContextKey, { api, monitor, store });
const connectionState = computed<MonitorStreamConnectionState>(() => {
  switch (store.transport) {
    case "LIVE": return { code: "LIVE", label: "传输连接正常", marker: "●" };
    case "RELOAD_REQUIRED": return { code: "UNAVAILABLE", label: "应用版本已变化，请重新加载页面", marker: "!" };
    case "CONNECTING": return { code: "CONNECTING", label: "正在连接监控服务", marker: "…" };
    default: return { code: "DISCONNECTED", label: "传输断开，正在重新连接", marker: "×" };
  }
});
provide(shellConnectionKey, connectionState);
watch(
  () => route.matched.length === 0 ? null : route.meta.section === "backtests" ? "backtests" : route.fullPath,
  (surface, previous) => {
    if (surface !== null && previous !== null) monitor.navigation();
  },
);
function resolveStartup(): void {
  if (route.matched.length) startup.route(route.path, route.name === "backtest-run-detail");
}
watch(() => route.path, resolveStartup);
onMounted(() => {
  store.setTransport("CONNECTING");
  startup.mount();
  resolveStartup();
  void router.isReady().then(resolveStartup);
});
onBeforeUnmount(() => { startup.dispose(); monitor.stop(); });
function reload(): void { window.location.reload(); }
</script>

<template>
  <AppShell>
    <template #connectionBanner="{ state }">
      <span>{{ state.marker }} {{ state.label }}</span>
      <button v-if="store.transport === 'RELOAD_REQUIRED'" type="button" @click="reload">重新加载页面</button>
    </template>
  </AppShell>
</template>

<style src="../assets/tokens.css"></style>
<style src="./runtime.css"></style>
