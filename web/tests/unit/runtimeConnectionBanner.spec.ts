import { createPinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import RuntimeApp from "../../src/runtime-status/App.vue";
import { useRuntimeMonitorStore } from "../../src/runtime-status/store";
import { emptyDashboard } from "../fixtures/runtimeStatus";

class Socket extends EventTarget {
  open() { this.dispatchEvent(new Event("open")); }
  receive(value: unknown) { this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(value) })); }
  close() { this.dispatchEvent(new CloseEvent("close", { code: 1000 })); }
}
let wrapper: VueWrapper | undefined;
beforeEach(() => vi.useFakeTimers());
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.useRealTimers(); });

async function setup() {
  const routes = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/plans/:id", component: { template: "<h1>待审核草稿</h1>" } },
    { path: "/:pathMatch(.*)*", component: { template: "<main />" } },
  ] });
  await routes.push("/plans/draft"); await routes.isReady();
  const pinia = createPinia();
  const dashboard = emptyDashboard();
  const sockets: Socket[] = [];
  const fetchImplementation = vi.fn(async (_request: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(dashboard), {
    headers: { "X-Monitor-Contract-Version": "2", "Content-Type": "application/json" },
  }));
  wrapper = mount(RuntimeApp, { props: {
    fetchImplementation,
    createSocket: () => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket; },
  }, global: { plugins: [pinia, routes] } });
  await flushPromises(); await flushPromises();
  expect(sockets).toHaveLength(1);
  const heartbeat = () => ({ type: "heartbeat", monitorContractVersion: 2, sequence: dashboard.sequence,
    runtimeGeneration: dashboard.runtimeGeneration, observedAt: dashboard.observedAt, runtimeStatus: dashboard.runtimeStatus });
  return { store: useRuntimeMonitorStore(pinia), socket: sockets[0]!, heartbeat, fetchImplementation,
    banner: () => wrapper!.find('[role="status"]').text() };
}

it("distinguishes an open socket awaiting validated status from a live connection", async () => {
  const h = await setup();
  expect(h.banner()).toContain("正在连接监控服务");
  h.socket.open(); await flushPromises();
  expect(h.banner()).toContain("连接已建立，等待监控状态");
  expect(h.store.transport).not.toBe("LIVE");
  await vi.advanceTimersByTimeAsync(20_000);
  h.socket.receive(h.heartbeat()); await flushPromises();
  expect(h.banner()).toContain("传输连接正常");
  expect(h.store.transport).toBe("LIVE");
  expect(h.fetchImplementation.mock.calls.every(([request]) => (request as Request).method === "GET")).toBe(true);
});

it("does not describe a stopped runtime as running when its transport is healthy", async () => {
  const h = await setup(); h.socket.open();
  const current = h.heartbeat();
  const frame = { ...current, runtimeStatus: { ...current.runtimeStatus, lifecycle: "STOPPED", mode: "BLOCKED", reasonCode: "RUNTIME_STOPPED",
    nextWakeAt: null, coordinator: { state: "STOPPED", progressDueAt: null } } };
  // Keep the authoritative refresh pending so the stopped heartbeat remains visible.
  h.fetchImplementation.mockImplementation(() => new Promise(() => {}));
  h.socket.receive(frame); await flushPromises();
  expect(h.banner()).toContain("传输连接正常；监控已停止");
  expect(h.store.transport).toBe("LIVE");
  expect(h.store.runtimeStatus?.lifecycle).toBe("STOPPED");
});

it("times out an open silent connection and never certifies it as live", async () => {
  const h = await setup(); h.socket.open(); await flushPromises();
  await vi.advanceTimersByTimeAsync(40_000);
  expect(h.store.transport).toBe("RECONNECTING");
  expect(h.banner()).toContain("传输断开，正在重新连接");
});

it("rejects an incompatible heartbeat instead of turning the banner green", async () => {
  const h = await setup(); h.socket.open();
  h.socket.receive({ ...h.heartbeat(), monitorContractVersion: 1 }); await flushPromises();
  expect(h.store.transport).toBe("RELOAD_REQUIRED");
  expect(h.banner()).toContain("应用版本已变化");
});
