import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { apiFetchKey } from "../../src/api/context";
import { dashboardMarketIndexIdentities } from "../../src/api/marketIndexIdentity";
import MarketIndexSparkline from "../../src/components/market-index/MarketIndexSparkline.vue";
import DashboardView from "../../src/runtime-status/DashboardView.vue";
import { runtimeContextKey } from "../../src/runtime-status/context";
import { createRuntimeApi } from "../../src/runtime-status/client";
import { createMonitorProtocol } from "../../src/runtime-status/protocol";
import { useRuntimeMonitorStore } from "../../src/runtime-status/store";
import { createRuntimeMonitor } from "../../src/runtime-status/stream";
import { isRuntimeDashboard, isRuntimeHealth } from "../../src/runtime-status/validators";
import { emptyDashboard } from "../fixtures/runtimeStatus";

async function dashboard(withData: boolean) {
  const pinia = createPinia(); setActivePinia(pinia);
  const store = useRuntimeMonitorStore();
  const base = emptyDashboard();
  const value = {
    ...base,
    marketIndexes: withData ? dashboardMarketIndexIdentities.map(identity => ({
      ...identity, closePoints: "1010", completedBucketAt: "2026-09-14T10:10:00+08:00",
      health: "LIVE", indicatorFacts: [], issues: [], mappedSymbolCount: 0,
      mappingVersion: "board-index-map-v1", observedAt: base.observedAt,
      priorClosePoints: "1000", revision: 1, sessionChangeRatio: "0.01", snapshotHash: "a".repeat(64),
    })).sort((left, right) => left.indexCode.localeCompare(right.indexCode)) : [],
  };
  if (!isRuntimeDashboard(value)) throw new Error("Invalid dashboard fixture");
  store.applySnapshot(value, performance.now(), performance.now());
  store.setTransport(withData ? "LIVE" : "DISCONNECTED");
  const fetchImplementation: typeof fetch = vi.fn(async input => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.origin);
    const indexCode = url.pathname.split("/")[4];
    return new Response(JSON.stringify({
      hasMore: false, limit: 64, nextCursor: null, snapshotHash: "b".repeat(64),
      items: ["09:35", "10:10"].map(time => ({
        amount: "100000000", barAt: `2026-09-14T${time}:00+08:00`, closePoints: "1010",
        highPoints: "1012", indexCode, interval: "FIVE_MINUTE", lowPoints: "1000",
        observedAt: base.observedAt, openPoints: "1005", providerRevision: 1,
        sourceKind: "PROVISIONAL", volume: "100",
      })),
    }), { headers: { "Content-Type": "application/json" } });
  });
  const protocol = createMonitorProtocol({ origin: window.location.origin, validateHealth: isRuntimeHealth });
  const api = createRuntimeApi(protocol);
  const ctx = { api, store, monitor: createRuntimeMonitor({ api, protocol, store, origin: window.location.origin }) };
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/", component: DashboardView }] });
  await router.push("/"); await router.isReady();
  const wrapper = mount(DashboardView, { global: {
    plugins: [pinia, router], provide: { [runtimeContextKey as symbol]: ctx, [apiFetchKey as symbol]: fetchImplementation },
  } });
  await flushPromises();
  return { wrapper, store, fetchImplementation };
}

describe("normal v2 dashboard trend preservation", () => {
  it("restores all original index selectors and stored-bar charts alongside runtime status", async () => {
    const { wrapper, store, fetchImplementation } = await dashboard(true);
    try {
      expect(wrapper.get("#market-index-strip-title").text()).toBe("主要指数走势");
      const selectors = wrapper.findAll('[data-testid="market-index-selector"]');
      expect(selectors.map(selector => selector.text())).toEqual([
        "上证指数+1.00%", "深证成指+1.00%", "创业板指+1.00%", "科创50+1.00%",
      ]);
      expect(fetchImplementation).toHaveBeenCalledTimes(4);
      for (const call of vi.mocked(fetchImplementation).mock.calls) {
        const url = new URL(String(call[0]), window.location.origin);
        expect(url.searchParams.get("limit")).toBe("64");
        expect(url.searchParams.get("startAt")).toBe("2026-09-14T09:30:00+08:00");
        expect(url.searchParams.get("endAt")).toBe(store.snapshot!.observedAt);
        expect(call[1]?.method).toBe("GET");
      }
      expect(wrapper.get('[data-testid="market-index-health"]').text()).toContain("实时");
      expect(wrapper.findComponent(MarketIndexSparkline).props("bars")).toHaveLength(2);
      await selectors[3]!.trigger("click");
      expect(wrapper.findComponent(MarketIndexSparkline).props("displayName")).toBe("科创50");
      expect(wrapper.text()).toContain("待机");
      expect(wrapper.text()).toContain("没有活动计划");
      expect(wrapper.get('[aria-label="监控状态"]').text()).toContain("没有活动计划");
      expect(wrapper.find('a[href="/system"]').text()).toBe("查看系统详情");
      expect(wrapper.text()).not.toContain("资源生命周期");
      expect(wrapper.text()).not.toContain("所需范围及进展");
      expect(wrapper.findAll('[data-testid="market-turnover-card"]')).toHaveLength(1);
      store.setTransport("DISCONNECTED"); await flushPromises();
      expect(wrapper.get('[data-testid="market-index-health"]').text()).toContain("已缓存");
      expect(wrapper.findComponent(MarketIndexSparkline).props("bars")).toHaveLength(2);
      expect(fetchImplementation).toHaveBeenCalledTimes(4);
    } finally { wrapper.unmount(); }
  });

  it("keeps the original chart area and four selectors visible before any index data exists", async () => {
    const { wrapper, fetchImplementation } = await dashboard(false);
    try {
      expect(wrapper.findAll('[data-testid="market-index-selector"]')).toHaveLength(4);
      expect(wrapper.get('[data-testid="market-index-sparkline"]').attributes("role")).toBe("img");
      expect(wrapper.text()).toContain("暂无快照");
      expect(wrapper.text()).toContain("当前暂无当日五分钟数据");
      expect(wrapper.text()).toContain("暂无成交额数据");
      expect(fetchImplementation).not.toHaveBeenCalled();
    } finally { wrapper.unmount(); }
  });
});
