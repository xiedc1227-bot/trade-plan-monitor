import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardView from "../../src/runtime-status/DashboardView.vue";
import StatusBoard from "../../src/runtime-status/StatusBoard.vue";
import { createRuntimeApi } from "../../src/runtime-status/client";
import { runtimeContextKey } from "../../src/runtime-status/context";
import { createMonitorProtocol } from "../../src/runtime-status/protocol";
import { useRuntimeMonitorStore } from "../../src/runtime-status/store";
import { createRuntimeMonitor } from "../../src/runtime-status/stream";
import { isRuntimeDashboard, isRuntimeHealth } from "../../src/runtime-status/validators";
import { emptyDashboard, explicitDashboard, planScope, runtimeStatus } from "../fixtures/runtimeStatus";

afterEach(() => vi.useRealTimers());
function context(value = explicitDashboard()) {
  const pinia = createPinia(); setActivePinia(pinia);
  const store = useRuntimeMonitorStore();
  if (!isRuntimeDashboard(value)) throw new Error("invalid fixture");
  store.applySnapshot(value, performance.now(), performance.now()); store.setTransport("LIVE");
  const protocol = createMonitorProtocol({ origin: window.location.origin, validateHealth: isRuntimeHealth });
  const api = createRuntimeApi(protocol);
  return { pinia, store, api, monitor: createRuntimeMonitor({ api, protocol, store, origin: window.location.origin }) };
}
async function routerFor(component: typeof DashboardView | ReturnType<typeof defineComponent>) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/", component }] });
  await router.push("/"); await router.isReady(); return router;
}

describe("runtime status UI", () => {
  it("keeps expired BUY separate from current risk and displays the original risk dates", async () => {
    const ctx = context(); const router = await routerFor(DashboardView);
    const wrapper = mount(DashboardView, { global: { plugins: [ctx.pinia, router], provide: { [runtimeContextKey as symbol]: ctx } } });
    expect(wrapper.get('[data-rule-id="buy"]').attributes("data-actionable")).toBe("false");
    expect(wrapper.get('[data-rule-id="risk"]').attributes("data-actionable")).toBe("true");
    expect(wrapper.get('[data-rule-id="risk"]').text()).toContain("2026-09-11 15:00:00");
    expect(wrapper.text()).not.toContain("T10:10");
    ctx.store.invalidatePresentation(); await wrapper.vm.$nextTick();
    expect(wrapper.get('[data-rule-id="risk"]').attributes("data-actionable")).toBe("false");
    wrapper.unmount();
  });

  it("shows a waiting sibling without hiding the healthy explicit plan", async () => {
    const value = explicitDashboard();
    const scope = { ...planScope(), scopeKey: "plan:600000.SH", symbol: "600000.SH", planFamily: "LEGACY_LOW_BUY",
      planVersionId: "00000000-0000-4000-8000-000000000004", status: "WAITING", reasonCode: "AWAITING_FIRST_EVALUATION", readOnly: true };
    value.runtimeStatus.scopes.push(scope);
    value.symbols.push({ symbol: "600000.SH", name: "等待标的", planFamily: scope.planFamily, planVersionId: scope.planVersionId,
      planHash: scope.planHash, activationRevision: scope.activationRevision, observedAt: value.observedAt, scope,
      availability: "UNAVAILABLE", projectionState: "WAITING", reasonCode: "AWAITING_FIRST_EVALUATION", currentActionable: false });
    const ctx = context(value); const router = await routerFor(DashboardView);
    const wrapper = mount(DashboardView, { global: { plugins: [ctx.pinia, router], provide: { [runtimeContextKey as symbol]: ctx } } });
    expect(wrapper.findAll("article[data-symbol]")).toHaveLength(2);
    expect(wrapper.get('[data-symbol="600000.SH"]').text()).toContain("等待首次求值");
    expect(wrapper.get('[data-symbol="003043.SZ"] [data-rule-id="risk"]').attributes("data-actionable")).toBe("true");
    wrapper.unmount();
  });

  it("presents standby honestly without a stale-data recovery warning", () => {
    const ctx = context(emptyDashboard());
    const wrapper = mount(StatusBoard, { props: { status: ctx.store.runtimeStatus! } });
    expect(wrapper.text()).toContain("待机"); expect(wrapper.text()).toContain("等待下一次所需工作");
    expect(wrapper.text()).not.toContain("正在恢复"); expect(wrapper.text()).not.toContain("陈旧数据");
    wrapper.unmount();
  });

  it("shows stalled coordinator separately from resource lifecycle", () => {
    const status = runtimeStatus(); status.mode = "BLOCKED"; status.reasonCode = "COORDINATOR_STALLED"; status.coordinator.state = "STALLED";
    const ctx = context(); const frozen = { ...ctx.store.runtimeStatus!, ...status, scopes: [] };
    const wrapper = mount(StatusBoard, { props: { status: frozen as NonNullable<typeof ctx.store.runtimeStatus> } });
    expect(wrapper.text()).toContain("RUNNING"); expect(wrapper.text()).toContain("协调器进展已逾期");
    expect(wrapper.text()).toContain("传输心跳不能恢复"); wrapper.unmount();
  });

});
