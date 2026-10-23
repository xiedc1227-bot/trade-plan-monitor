import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RuntimeApp from "../../src/runtime-status/App.vue";

const lifecycle = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), navigation: vi.fn(), reloadRequired: vi.fn() }));
vi.mock("../../src/runtime-status/stream", () => ({ createRuntimeMonitor: () => lifecycle }));
const view = { template: "<h1>页面</h1>" };
function router() {
  return createRouter({ history: createMemoryHistory(), routes: [
    { path: "/", component: view },
    { path: "/stocks/:symbol", component: view },
    { path: "/backtests", component: view, meta: { section: "backtests" } },
    { path: "/backtests/data", component: view, meta: { section: "backtests" } },
    { path: "/backtests/:runId", name: "backtest-run-detail", component: view, meta: { section: "backtests" } },
  ] });
}
beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.useRealTimers());

describe("runtime navigation refresh scope", () => {
  it("keeps canonical query changes deferred, releases on leaving, and cancels timeout", async () => {
    vi.useFakeTimers(); const routes=router(); await routes.push("/backtests/"+"a".repeat(64));
    const wrapper=mount(RuntimeApp,{global:{plugins:[createPinia(),routes],stubs:{AppShell:{template:"<main />"}}}});
    await routes.replace({query:{tab:"summary"}}); await flushPromises();
    expect(lifecycle.start).not.toHaveBeenCalled();
    await routes.push("/backtests"); await flushPromises(); expect(lifecycle.start).toHaveBeenCalledTimes(1);
    wrapper.unmount(); vi.runAllTimers(); expect(lifecycle.start).toHaveBeenCalledTimes(1);
  });

  it("does not restart the initial snapshot during initial resolution or backtest URL changes", async () => {
    const routes = router();
    const wrapper = mount(RuntimeApp, { global: { plugins: [createPinia(), routes], stubs: { AppShell: { template: "<main />" } } } });
    expect(lifecycle.start).not.toHaveBeenCalled();
    for (const path of ["/backtests", "/backtests?page=1&sort=completedAt_desc", "/backtests/" + "a".repeat(64), "/backtests/" + "a".repeat(64) + "?tab=provenance", "/backtests?view=tasks", "/backtests/data?symbol=002240.SZ"]) {
      await routes.push(path); await flushPromises();
    }
    expect(lifecycle.navigation).not.toHaveBeenCalled();
    wrapper.unmount(); expect(lifecycle.stop).toHaveBeenCalledTimes(1);
  });

  it("refreshes on monitor re-entry and preserves monitor route identity changes", async () => {
    const routes = router(); await routes.push("/backtests"); await routes.isReady();
    const wrapper = mount(RuntimeApp, { global: { plugins: [createPinia(), routes], stubs: { AppShell: { template: "<main />" } } } });
    for (const path of ["/", "/stocks/002240.SZ", "/stocks/600000.SH", "/backtests"]) {
      await routes.push(path); await flushPromises();
    }
    expect(lifecycle.navigation).toHaveBeenCalledTimes(4);
    await routes.push("/backtests?view=tasks"); await flushPromises();
    expect(lifecycle.navigation).toHaveBeenCalledTimes(4);
    wrapper.unmount();
  });
});
