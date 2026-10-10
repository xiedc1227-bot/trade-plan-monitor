import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, shallowRef } from "vue";
import { describe, expect, it, vi } from "vitest";
import { useMarketIndexOverview } from "../../src/composables/useMarketIndexOverview";
import { overviewFixture } from "../fixtures/indexOverview";
import { isMarketIndexOverview } from "../../src/api/marketIndexOverview";
import MarketIndexDataStrip from "../../src/components/market-index/MarketIndexDataStrip.vue";
import MarketIndexSparkline from "../../src/components/market-index/MarketIndexSparkline.vue";
import { emptyDashboardMarketIndexTrends } from "../../src/composables/useDashboardMarketIndexTrends";
import { buildMarketIndexChartPoints } from "../../src/components/market-index/marketIndexChartOptions";

describe("atomic index overview", () => {
  it("shows the SSE close and a coherent 48-bar endpoint after a later failed refresh", () => {
    const overview = overviewFixture();
    expect(isMarketIndexOverview(overview)).toBe(true);
    const wrapper = mount(MarketIndexDataStrip, { props: { overview, connectionStatus: "CONNECTED", indexes: [], trends: emptyDashboardMarketIndexTrends } });
    expect(wrapper.get('[data-testid="market-index-health"]').text()).toContain("已收市");
    expect(wrapper.text()).not.toContain("阻断");
    expect(wrapper.text()).toContain("3813.79");
    expect(wrapper.text()).toContain("最近更新失败，保留已取得行情");
    const chart = wrapper.findComponent(MarketIndexSparkline);
    expect(chart.props("displayName")).toBe("上证指数");
    expect(chart.props("bars")).toHaveLength(48);
    expect(chart.props("bars").at(-1)?.closePoints).toBe(overview.indexes[0]?.data?.closePoints);
    wrapper.unmount();
  });

  it("breaks missing intraday bars and preserves the normal lunch interval", () => {
    const bars = overviewFixture().indexes[0]!.data!.bars;
    const gap = buildMarketIndexChartPoints(bars.filter((_, i) => i !== 5));
    expect(gap.find(point => point.at.includes("T10:00:"))?.value).toBeNull();
    const complete = buildMarketIndexChartPoints(bars);
    expect(complete.filter(point => point.value === null)).toHaveLength(0);
  });

  it("rejects mixed quote and chart revisions", () => {
    const overview = overviewFixture();
    overview.indexes[0]!.data!.closePoints = "4000";
    expect(isMarketIndexOverview(overview)).toBe(false);
  });
  it("retains the whole envelope after refresh failure", async () => {
    const api = { getOverview: vi.fn().mockResolvedValueOnce(overviewFixture()).mockRejectedValueOnce(new Error("offline")) };
    let result!: ReturnType<typeof useMarketIndexOverview>;
    const wrapper = mount(defineComponent({ setup() {
      result = useMarketIndexOverview({ api, connectionStatus: "CONNECTED", runtimeGeneration: null, sequence: 1, observedAt: "2026-10-09T16:00:00+08:00" });
      return () => null;
    } }));
    await flushPromises();
    const saved = result.overview.value;
    result.refresh(); await flushPromises();
    expect(result.overview.value).toBe(saved);
    expect(result.cached.value).toBe(true);
    expect(result.error.value).toContain("保留");
    wrapper.unmount();
  });

  it.each(["generation", "sequence"])("retains coherent data when a response has an obsolete %s", async fence => {
    const generation = "00000000-0000-4000-8000-000000000001";
    const valid = overviewFixture();
    valid.runtimeGeneration = generation;
    const obsolete = structuredClone(valid);
    if (fence === "generation") obsolete.runtimeGeneration = "00000000-0000-4000-8000-000000000002";
    else obsolete.sequence = 2;
    const api = { getOverview: vi.fn().mockResolvedValueOnce(valid).mockResolvedValueOnce(obsolete) };
    let result!: ReturnType<typeof useMarketIndexOverview>;
    const wrapper = mount(defineComponent({ setup() {
      result = useMarketIndexOverview({ api, connectionStatus: "CONNECTED", runtimeGeneration: generation, sequence: 3, observedAt: valid.observedAt });
      return () => null;
    } }));
    await flushPromises();
    const saved = result.overview.value;
    expect(saved).not.toBeNull();
    result.refresh(); await flushPromises();
    expect(result.overview.value).toBe(saved);
    expect(result.cached.value).toBe(true);
    wrapper.unmount();
  });

  it("coalesces invalidations and discards an old in-flight response", async () => {
    const sequence = shallowRef(1);
    let complete!: (value: ReturnType<typeof overviewFixture>) => void;
    const api = { getOverview: vi.fn().mockImplementationOnce(() => new Promise(resolve => { complete = resolve; })).mockResolvedValue(overviewFixture()) };
    let result!: ReturnType<typeof useMarketIndexOverview>;
    const wrapper = mount(defineComponent({ setup() {
      result = useMarketIndexOverview({ api, connectionStatus: "CONNECTED", runtimeGeneration: null, sequence, observedAt: "2026-10-09T16:00:00+08:00" });
      return () => null;
    } }));
    await flushPromises(); sequence.value = 2; await flushPromises(); sequence.value = 3; await flushPromises();
    expect(api.getOverview).toHaveBeenCalledTimes(1);
    complete(overviewFixture()); await flushPromises();
    expect(api.getOverview).toHaveBeenCalledTimes(2);
    expect(result.overview.value?.indexes[0]?.data?.closePoints).toBe("3813.791");
    wrapper.unmount();
  });
});
