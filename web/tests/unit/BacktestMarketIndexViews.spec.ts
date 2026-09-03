import { enableAutoUnmount, mount } from "@vue/test-utils";
import { computed, isShallow, nextTick, shallowRef } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  BacktestMarketIndexSeriesView,
} from "../../src/api/generated";
import BacktestIndexConditionSummary from "../../src/components/backtests/BacktestIndexConditionSummary.vue";
import BacktestMarketIndexPanel from "../../src/components/backtests/BacktestMarketIndexPanel.vue";
import {
  useBacktestMarketIndexSeries,
  type BacktestMarketIndexSeriesRequest,
} from "../../src/composables/useMarketIndexSeries";

const runId = "a".repeat(64);
const datasetHash = "b".repeat(64);
const dataHash = "c".repeat(64);
const requirementHash = "d".repeat(64);
const formulaHash = "e".repeat(64);
const snapshotHash = "f".repeat(64);

const summary = Object.freeze({
  applicableBranchCount: 3,
  conditionType: "INDEX_CLOSE_GTE_MA" as const,
  formulaId: "SMA" as const,
  missingCount: 1,
  parameters: Object.freeze({ period: 20 }),
  planPath: "entry.conditions.all[0]",
  satisfiedCount: 1,
  unsatisfiedCount: 1,
});

const series: BacktestMarketIndexSeriesView = {
  conditionSummaries: [summary],
  healthTimeline: [
    {
      dataAt: "2026-08-01T15:00:00.000000+08:00",
      health: "LIVE" as const,
      issues: [],
    },
  ],
  items: [
    {
      closePoints: "10000.5",
      dataAt: "2026-08-01T15:00:00.000000+08:00",
      health: "LIVE" as const,
      indicatorFacts: [
        {
          formulaDefinitionHash: formulaHash,
          formulaId: "SMA" as const,
          period: 20,
          sourceBarHash: snapshotHash,
          unit: "POINTS" as const,
          value: "9999.5",
        },
      ],
      issues: [],
      snapshotHash,
      tradeDate: "2026-08-01",
    },
  ],
  referenceMarket: {
    binding: {
      board: "SZSE_MAIN" as const,
      displayName: "深证成指",
      indexCode: "399001.SZ" as const,
      mappingVersion: "board-index-map-v1" as const,
      selection: "AUTO_BOARD" as const,
    },
    blockers: [],
    conditionPaths: ["entry.conditions.all[0]"],
    conditionSummaries: [summary],
    coverageStatus: "AVAILABLE" as const,
    datasetHash,
    formulaDefinitionHash: formulaHash,
    indexRequirementHash: requirementHash,
    marketIndexDataHash: dataHash,
    required: true as const,
    warmupStart: "2026-07-01",
  },
  runId,
};

enableAutoUnmount(afterEach);

describe("backtest reference-index views", () => {
  it("renders backend-authored per-path counts without an overall market verdict", () => {
    const wrapper = mount(BacktestIndexConditionSummary, {
      props: { summaries: [summary] },
    });

    expect(wrapper.get("h2").text()).toBe("计划指数条件结果");
    expect(wrapper.text()).toContain("entry.conditions.all[0]");
    expect(wrapper.text()).toContain("INDEX_CLOSE_GTE_MA");
    expect(wrapper.text()).toContain("满足 1");
    expect(wrapper.text()).toContain("未满足 1");
    expect(wrapper.text()).toContain("缺失 1");
    expect(wrapper.text()).toContain("适用分支 3");
    expect(wrapper.text()).not.toMatch(/强势|弱势|允许买入|禁止买入/);
  });

  it("states explicitly when the plan has no index condition", () => {
    const wrapper = mount(BacktestIndexConditionSummary, { props: { summaries: [] } });

    expect(wrapper.get('[role="status"]').text()).toBe("计划未使用指数条件。");
  });

  it("keeps shared frozen data and plan results in separate labelled regions", async () => {
    const wrapper = mount(BacktestMarketIndexPanel, { props: { series } });

    expect(wrapper.get('[aria-labelledby="backtest-index-data-title"]').text()).toContain(
      "共用指数数据",
    );
    expect(wrapper.text()).toContain("深证成指");
    expect(wrapper.text()).toContain("board-index-map-v1");
    expect(wrapper.text()).toContain(dataHash);
    expect(wrapper.get("caption").text()).toContain("回测板块指数点位");
    expect(wrapper.text()).toContain("10000.5");
    expect(wrapper.text()).toContain("9999.5");

    await wrapper.get('button[data-trade-date="2026-08-01"]').trigger("click");
    expect(wrapper.emitted("select-date")).toEqual([["2026-08-01"]]);
  });

  it("does not synthesize shared data for an old or stock-only run", () => {
    const noIndex: BacktestMarketIndexSeriesView = {
      conditionSummaries: [],
      healthTimeline: [],
      items: [],
      referenceMarket: null,
      runId,
    };
    const wrapper = mount(BacktestMarketIndexPanel, { props: { series: noIndex } });

    expect(wrapper.text()).toContain("计划未使用指数条件。");
    expect(wrapper.text()).toContain("本次运行没有冻结的参考指数数据");
  });
});

describe("useBacktestMarketIndexSeries", () => {
  it("aborts stale requests and exposes only the newest immutable server series", async () => {
    const query = shallowRef<BacktestMarketIndexSeriesRequest | null>({ runId });
    const resolvers: Array<(value: BacktestMarketIndexSeriesView) => void> = [];
    const signals: AbortSignal[] = [];
    const loader = vi.fn(
      (_query: Readonly<BacktestMarketIndexSeriesRequest>, signal: AbortSignal) =>
        new Promise<BacktestMarketIndexSeriesView>((resolve) => {
          signals.push(signal);
          resolvers.push(resolve);
        }),
    );
    const result = useBacktestMarketIndexSeries({
      loader,
      query: computed(() => query.value),
    });

    expect(isShallow(result.series)).toBe(true);
    query.value = { limit: 100, runId, startOn: "2026-08-01" };
    await nextTick();
    expect(signals[0]?.aborted).toBe(true);

    const noIndex: BacktestMarketIndexSeriesView = {
      conditionSummaries: [],
      healthTimeline: [],
      items: [],
      referenceMarket: null,
      runId,
    };
    resolvers[0]?.(noIndex);
    resolvers[1]?.(series);
    await nextTick();
    await nextTick();

    expect(result.status.value).toBe("READY");
    expect(result.series.value?.referenceMarket?.marketIndexDataHash).toBe(dataHash);
    expect(Object.isFrozen(result.series.value)).toBe(true);
  });
});
