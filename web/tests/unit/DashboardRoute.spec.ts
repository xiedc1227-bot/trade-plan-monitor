import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardResponse } from "../../src/api/generated";
import DashboardRouteView from "../../src/views/DashboardRouteView.vue";
import { routes } from "../../src/router";
import { useMonitorStore } from "../../src/stores/monitor";

const snapshot: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: {
    actionable: 0,
    blocked: 0,
    lowZoneWatch: 1,
    normal: 0,
    risk: 0,
    stale: 0,
  },
  marketIndexes: [
    {
      board: "STAR_MARKET",
      closePoints: "1234.56",
      completedBucketAt: "2026-09-02T10:35:00+08:00",
      displayName: "科创50",
      health: "LIVE",
      indexCode: "000688.SH",
      indicatorFacts: [],
      issues: [],
      mappedSymbolCount: 1,
      mappingVersion: "board-index-map-v1",
      observedAt: "2026-09-02T10:35:02+08:00",
      priorClosePoints: "1220.11",
      revision: 42,
      sessionChangeRatio: "0.011843",
      snapshotHash: "a".repeat(64),
    },
  ],
  observedAt: "2026-09-02T10:35:02+08:00",
  runtimeGeneration: "00000000-0000-4000-8000-000000000001",
  sequence: 7,
  symbols: [
    {
      connected: true,
      decision: {
        dataAgeSeconds: 2,
        dataHealth: {
          dataAgeSeconds: 2,
          fresh: true,
          latestBarEnd: "2026-09-02T10:35:00+08:00",
          requiredDataComplete: true,
          status: "LIVE",
        },
        episodeLowFen: 2010,
        episodeStatus: "ACTIVE",
        evaluatedAt: "2026-09-02T10:35:02+08:00",
        evidence: [],
        marketDataAt: "2026-09-02T10:35:00+08:00",
        nextStep: { code: "WATCH_LOW_ZONE" },
        planHash: "b".repeat(64),
        planId: "plan-1",
        planVersion: 1,
        position: {
          coreQuantity: 0,
          sellableCoreQuantity: 0,
          sellableTacticalQuantity: 0,
          tacticalQuantity: 0,
          totalQuantity: 0,
        },
        priceFen: 2020,
        resultHash: "c".repeat(64),
        riskBreachTradeDate: null,
        riskStatus: "CLEAR",
        signalType: "LOW_ZONE_WATCH",
        symbol: "688001.SH",
        zone: "LOW_BUY",
      },
      name: "华兴源创",
      observedAt: "2026-09-02T10:35:02+08:00",
      referenceMarket: {
        board: "STAR_MARKET",
        conditionProgress: { missing: 0, satisfied: 1, total: 2, unsatisfied: 1 },
        dataAt: "2026-09-02T10:35:00+08:00",
        displayName: "科创50",
        health: "LIVE",
        indexCode: "000688.SH",
        issues: [],
        mappingVersion: "board-index-map-v1",
        snapshotHash: "a".repeat(64),
      },
      riskDistanceFen: 120,
      satisfiedConditionCount: 1,
      symbol: "688001.SH",
      totalConditionCount: 3,
    },
  ],
};

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("DashboardRouteView", () => {
  it("renders backend-authoritative stock decisions and shared index data from the monitor store", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const router = createRouter({ history: createMemoryHistory(), routes });
    await router.push("/");
    await router.isReady();
    useMonitorStore().applySnapshot(snapshot);

    const wrapper = mount(DashboardRouteView, { global: { plugins: [pinia, router] } });

    expect(wrapper.text()).toContain("华兴源创");
    expect(wrapper.text()).toContain("低吸观察");
    expect(wrapper.get("#market-index-strip-title").text()).toBe("主要指数走势 · 当日");
    expect(wrapper.text()).toContain("科创50");
    expect(wrapper.text()).toContain("计划指数条件");

    await wrapper.get('a[href="/stocks/688001.SH"]').trigger("click");

    await vi.waitFor(() => {
      expect(router.currentRoute.value.path).toBe("/stocks/688001.SH");
    }, { timeout: 5_000 });
  });
});
