import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { computed, isShallow, nextTick, shallowRef } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  IndexConditionEvidenceView,
  MarketIndexBarPage,
  MarketIndexBarView,
  MarketIndexSnapshotView,
  MarketTurnoverSummaryView,
  SymbolReferenceMarketView,
} from "../../src/api/generated";
import { createMarketIndexApi } from "../../src/api/marketIndexes";
import IndexConditionProgress from "../../src/components/market-index/IndexConditionProgress.vue";
import MarketIndexChart from "../../src/components/market-index/MarketIndexChart.vue";
import MarketIndexDataStrip from "../../src/components/market-index/MarketIndexDataStrip.vue";
import MarketIndexTrendCard from "../../src/components/market-index/MarketIndexTrendCard.vue";
import MarketTurnoverCard from "../../src/components/market-index/MarketTurnoverCard.vue";
import ReferenceMarketPanel from "../../src/components/market-index/ReferenceMarketPanel.vue";
import {
  useMarketIndexSeries,
  type MarketIndexSeriesQuery,
} from "../../src/composables/useMarketIndexSeries";
import {
  buildCurrentDayQuery,
  emptyDashboardMarketIndexTrends,
  useDashboardMarketIndexTrends,
} from "../../src/composables/useDashboardMarketIndexTrends";

const hash = "a".repeat(64);
const at = "2026-09-02T10:35:00+08:00";

const snapshot: MarketIndexSnapshotView = Object.freeze({
  board: "STAR_MARKET",
  closePoints: "1234.56",
  completedBucketAt: at,
  displayName: "科创50",
  health: "LIVE",
  indexCode: "000688.SH",
  indicatorFacts: [
    {
      formulaDefinitionHash: "b".repeat(64),
      formulaId: "SMA",
      period: 20,
      sourceBarHash: "c".repeat(64),
      unit: "POINTS",
      value: "1212.34",
    },
  ],
  issues: [],
  mappedSymbolCount: 2,
  mappingVersion: "board-index-map-v1",
  observedAt: "2026-09-02T10:35:02+08:00",
  priorClosePoints: "1220.11",
  revision: 42,
  sessionChangeRatio: "0.011843",
  snapshotHash: hash,
} satisfies MarketIndexSnapshotView);

const blockedSnapshot: MarketIndexSnapshotView = Object.freeze({
  ...snapshot,
  closePoints: null,
  completedBucketAt: null,
  health: "BLOCKED",
  indexCode: "399006.SZ",
  displayName: "创业板指",
  board: "CHINEXT",
  indicatorFacts: [],
  issues: ["PROVIDER_UNAVAILABLE"],
  priorClosePoints: null,
  sessionChangeRatio: null,
  snapshotHash: "d".repeat(64),
} satisfies MarketIndexSnapshotView);

const marketTurnover: MarketTurnoverSummaryView = {
  benchmarkCodes: ["000001.SH", "399107.SZ"],
  changeAmount: "-210700000000",
  completedBucketAt: "2026-09-02T10:35:00+08:00",
  currentAmount: "1660000000000",
  estimateMethod: "LINEAR_COMPLETED_FIVE_MINUTE_BUCKETS",
  estimatedFullDayAmount: "1660000000000",
  previousAmount: "1870700000000",
};

const reference: SymbolReferenceMarketView = Object.freeze({
  board: "STAR_MARKET",
  conditionProgress: Object.freeze({
    missing: 0,
    satisfied: 1,
    total: 2,
    unsatisfied: 1,
  }),
  dataAt: at,
  displayName: "科创50",
  health: "LIVE",
  indexCode: "000688.SH",
  issues: [],
  mappingVersion: "board-index-map-v1",
  snapshotHash: hash,
});

const evidence: readonly IndexConditionEvidenceView[] = Object.freeze([
  Object.freeze({
    actualValue: "1234.56",
    comparisonValue: "1212.34",
    conditionType: "INDEX_CLOSE_GTE_MA",
    dataCutoff: at,
    decisionCutoff: at,
    formulaDefinitionHash: "b".repeat(64),
    formulaId: "SMA",
    indexCode: "000688.SH",
    mappingVersion: "board-index-map-v1",
    missingInputs: [],
    outcome: "SATISFIED",
    parameters: [{ key: "period", unit: "COUNT", value: 20 }],
    planPath: "entry.condition.conditions[0]",
    snapshotHash: hash,
    unit: "POINTS",
  } satisfies IndexConditionEvidenceView),
]);

const bars: readonly MarketIndexBarView[] = Object.freeze([
  Object.freeze({
    amount: null,
    barAt: at,
    closePoints: "1234.56",
    highPoints: "1235.2",
    indexCode: "000688.SH",
    interval: "FIVE_MINUTE",
    lowPoints: "1229.9",
    observedAt: "2026-09-02T10:35:02+08:00",
    openPoints: "1230.1",
    providerRevision: 3,
    sourceKind: "PROVISIONAL",
    volume: "1000",
  }),
]);

enableAutoUnmount(afterEach);

describe("market index monitor views", () => {
  it("renders the market-wide turnover summary without explanatory footer text", () => {
    const wrapper = mount(MarketTurnoverCard, {
      props: { summary: marketTurnover },
    });

    expect(wrapper.get('[data-testid="market-turnover-card"]').text()).toContain("今日累计成交额");
    expect(wrapper.text()).toContain("1.66万亿");
    expect(wrapper.text()).toContain("较上一日");
    expect(wrapper.text()).toContain("-2107亿");
    expect(wrapper.text()).toContain("预测全天成交额");
    expect(wrapper.text()).not.toContain("按最近完整五分钟时段线性估算");
    expect(wrapper.text()).not.toContain("截至 2026-09-02 10:35:00");
  });

  it("keeps the turnover card visible with placeholders before data is available", () => {
    const wrapper = mount(MarketTurnoverCard, { props: { summary: null } });

    expect(wrapper.text()).toContain("今日累计成交额");
    expect(wrapper.text()).toContain("暂无成交额数据");
    expect(wrapper.text()).toContain("—");
  });

  it("renders four fixed index selectors with one current-day chart panel", async () => {
    const wrapper = mount(MarketIndexDataStrip, {
      props: {
        connectionStatus: "CONNECTED",
        indexes: [snapshot, blockedSnapshot],
        trends: emptyDashboardMarketIndexTrends,
      },
    });

    expect(wrapper.findAll('[data-testid="market-index-selector"]')).toHaveLength(4);
    expect(wrapper.findAll('[data-testid="market-index-trend-card"]')).toHaveLength(1);
    expect(wrapper.findAll('[data-testid="market-index-sparkline"]')).toHaveLength(1);
    expect(wrapper.get("#market-index-strip-title").text()).toBe("主要指数走势 · 当日");
    expect(wrapper.text()).toContain("上证指数");
    expect(wrapper.text()).toContain("深证成指");
    expect(wrapper.text()).toContain("创业板指");
    expect(wrapper.text()).toContain("当前暂无当日五分钟数据");

    const scienceTechnology = wrapper
      .findAll('[data-testid="market-index-selector"]')
      .find((item) => item.text().includes("科创50"));
    await scienceTechnology?.trigger("click");

    expect(scienceTechnology?.attributes("aria-pressed")).toBe("true");
    expect(wrapper.get('[data-testid="market-index-trend-card"]').text()).toContain("1234.56");
  });

  it("retries the selected index from the turnover footer only when its trend failed", async () => {
    const failedTrend = { error: "当日指数走势暂不可用", page: null, status: "ERROR" as const };
    const wrapper = mount(MarketIndexDataStrip, {
      props: {
        connectionStatus: "CONNECTED",
        indexes: [snapshot],
        marketTurnover,
        trends: {
          ...emptyDashboardMarketIndexTrends,
          "000001.SH": failedTrend,
          "000688.SH": failedTrend,
        },
      },
    });

    const footerButton = () => wrapper.get('[data-testid="market-turnover-card"] .market-turnover-card__actions button');
    expect(footerButton().text()).toBe("重试");
    expect(wrapper.get(".market-turnover-card__actions [role='alert']").text()).toBe("当日指数走势暂不可用");
    expect(wrapper.get('[data-testid="market-index-trend-card"]').text()).not.toContain("当日指数走势暂不可用");
    expect(wrapper.get('[data-testid="market-index-trend-card"]').text()).not.toContain("当前暂无当日五分钟数据");
    expect(wrapper.get('[data-testid="market-index-trend-card"]').find("button").exists()).toBe(false);
    await footerButton().trigger("click");
    expect(wrapper.emitted("retryIndex")).toEqual([["000001.SH"]]);

    await wrapper.findAll('[data-testid="market-index-selector"]')[3]!.trigger("click");
    await footerButton().trigger("click");
    expect(wrapper.emitted("retryIndex")).toEqual([["000001.SH"], ["000688.SH"]]);

    await wrapper.findAll('[data-testid="market-index-selector"]')[1]!.trigger("click");
    expect(wrapper.find(".market-turnover-card__actions").exists()).toBe(false);
  });

  it("keeps cached chart data visible while the parent displays refresh errors", () => {
    const wrapper = mount(MarketIndexTrendCard, {
      props: {
        connectionStatus: "CONNECTED",
        identity: { board: "STAR_MARKET", displayName: "科创50", indexCode: "000688.SH" },
        summary: snapshot,
        trend: {
          error: "当日指数走势暂不可用",
          page: { hasMore: false, items: [...bars], limit: 64, nextCursor: null, snapshotHash: hash },
          status: "ERROR",
        },
      },
    });

    const chartLabel = wrapper
      .get('[data-testid="market-index-sparkline"]')
      .attributes("aria-label");
    expect(chartLabel).toContain("科创50");
    expect(chartLabel).toContain("涨跌 1.18%");
    expect(chartLabel).not.toContain("会话涨跌");
    expect(wrapper.get('[data-testid="market-index-trend-card"]').attributes("data-direction")).toBe("up");
    expect(wrapper.get(".market-index-trend-card__high").text()).toBe("1235.20");
    expect(wrapper.get(".market-index-trend-card__high").attributes("data-direction")).toBe("up");
    expect(wrapper.get(".market-index-trend-card__low").text()).toBe("1229.90");
    expect(wrapper.get(".market-index-trend-card__low").attributes("data-direction")).toBe("up");
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.find("button").exists()).toBe(false);
    const cutoffFact = wrapper
      .findAll(".market-index-trend-card__facts > div")
      .find((fact) => fact.text().includes("数据截止"));
    expect(cutoffFact?.text()).toBe("数据截止2026-09-02 10:35:00");
    expect(wrapper.findAll("dt").map((term) => term.text())).toContain("涨跌");
    expect(wrapper.findAll("dt").map((term) => term.text())).not.toContain("会话涨跌");
    expect(wrapper.find("details").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("查看当日点位数据");
  });

  it("labels historical chart data while a blocked index awaits recovery", () => {
    const wrapper = mount(MarketIndexTrendCard, {
      props: {
        connectionStatus: "CONNECTED",
        identity: { board: "CHINEXT", displayName: "创业板指", indexCode: "399006.SZ" },
        summary: {
          ...blockedSnapshot,
          recoveryAttempts: 0,
          nextRetryAt: "2026-09-02T10:35:32+08:00",
        },
        trend: {
          error: null,
          page: { hasMore: false, items: [...bars], limit: 64, nextCursor: null, snapshotHash: hash },
          status: "READY",
        },
      },
    });

    expect(wrapper.text()).toContain("第 1/3 次恢复");
    expect(wrapper.text()).toContain("图表仅供参考");
    expect(wrapper.text()).toContain("数据截至");
    expect(wrapper.find('[data-testid="market-index-sparkline"]').exists()).toBe(true);
  });

  it("restarts a one-shot live pulse only when a new healthy snapshot arrives", async () => {
    const wrapper = mount(MarketIndexTrendCard, {
      props: {
        connectionStatus: "CONNECTED",
        identity: { board: "STAR_MARKET", displayName: "科创50", indexCode: "000688.SH" },
        summary: snapshot,
        trend: emptyDashboardMarketIndexTrends["000688.SH"],
      },
    });

    const initialDot = wrapper.get('[data-testid="market-index-health-symbol"]');
    expect(wrapper.get('[data-testid="market-index-health"]').text()).toContain("实时");
    expect(initialDot.text()).toBe("●");
    expect(initialDot.classes()).toContain("market-index-trend-card__health-symbol--live");

    await wrapper.setProps({
      summary: { ...snapshot, snapshotHash: "e".repeat(64) },
    });

    expect(wrapper.get('[data-testid="market-index-health-symbol"]').element).not.toBe(
      initialDot.element,
    );
  });

  it("labels absent and disconnected snapshots without claiming live data", () => {
    const absent = mount(MarketIndexTrendCard, {
      props: {
        connectionStatus: "UNKNOWN",
        identity: { board: "STAR_MARKET", displayName: "科创50", indexCode: "000688.SH" },
        summary: null,
        trend: emptyDashboardMarketIndexTrends["000688.SH"],
      },
    });
    const cached = mount(MarketIndexTrendCard, {
      props: {
        connectionStatus: "DISCONNECTED",
        identity: { board: "STAR_MARKET", displayName: "科创50", indexCode: "000688.SH" },
        summary: snapshot,
        trend: emptyDashboardMarketIndexTrends["000688.SH"],
      },
    });

    expect(absent.text()).toContain("暂无快照");
    expect(absent.text()).not.toContain("等待快照");
    expect(cached.text()).toContain("已缓存");
    expect(cached.text()).not.toContain("实时 ●");
    expect(cached.get('[data-testid="market-index-health-symbol"]').text()).toBe("○");
    expect(cached.find(".market-index-trend-card__health-symbol--live").exists()).toBe(false);
  });

  it("distinguishes an unused plan from satisfied index conditions", () => {
    const unused = mount(IndexConditionProgress, {
      props: { progress: { missing: 0, satisfied: 0, total: 0, unsatisfied: 0 } },
    });
    const used = mount(IndexConditionProgress, {
      props: { progress: reference.conditionProgress },
    });

    expect(unused.text()).toContain("计划未使用");
    expect(used.text()).toContain("满足 1");
    expect(used.text()).toContain("未满足 1");
  });

  it("renders mapping and exact server evidence paths without recomputation", () => {
    const wrapper = mount(ReferenceMarketPanel, {
      props: {
        evidence,
        plan: {
          planHash: "e".repeat(64),
          planId: "plan-star-1",
          planVersion: 3,
        },
        reference,
      },
    });

    expect(wrapper.text()).toContain("参考指数数据");
    expect(wrapper.text()).toContain("计划指数条件");
    expect(wrapper.text()).toContain("当前计划 plan-star-1 · v3");
    expect(wrapper.text()).toContain("e".repeat(64));
    expect(wrapper.text()).toContain("entry.condition.conditions[0]");
    expect(wrapper.text()).toContain("INDEX_CLOSE_GTE_MA");
    expect(wrapper.text()).toContain("1234.56");
    expect(wrapper.text()).toContain("1212.34");
    expect(wrapper.text()).toContain("2026-09-02 10:35:00");
    expect(wrapper.text()).not.toContain(at);
  });

  it("shows exact point text in an accessible index-only table", () => {
    const wrapper = mount(MarketIndexChart, { props: { bars } });

    expect(wrapper.get("caption").text()).toContain("板块指数点位");
    expect(wrapper.get("table").text()).toContain("1234.56");
    expect(wrapper.get("table").text()).toContain("2026-09-02 10:35:00");
    expect(wrapper.get("time").attributes("datetime")).toBe(at);
    expect(wrapper.text()).not.toContain("元");
  });

  it("keeps a cached index page visible while reporting refresh state", () => {
    const wrapper = mount(MarketIndexChart, {
      props: {
        bars,
        error: "指数历史暂不可用",
        loading: true,
        snapshotHash: hash,
      },
    });

    expect(wrapper.get('[role="alert"]').text()).toContain("指数历史暂不可用");
    expect(wrapper.get('[role="status"]').text()).toContain("正在刷新共享指数历史");
    expect(wrapper.text()).toContain("已缓存后端点位继续显示");
    expect(wrapper.text()).toContain(hash);
    expect(wrapper.get("table").text()).toContain("1234.56");
  });

  it("does not expose an empty scroll region while no index history is available", () => {
    const loadingWrapper = mount(MarketIndexChart, { props: { loading: true } });
    const errorWrapper = mount(MarketIndexChart, {
      props: { error: "指数历史暂不可用" },
    });

    expect(loadingWrapper.find(".index-chart__scroller").exists()).toBe(false);
    expect(errorWrapper.find(".index-chart__scroller").exists()).toBe(false);
    expect(loadingWrapper.find("table").exists()).toBe(false);
    expect(errorWrapper.find("table").exists()).toBe(false);
  });
});

describe("useDashboardMarketIndexTrends", () => {
  it("loads four independent current-day five-minute series from the dashboard cutoff", async () => {
    const observedAt = shallowRef("2026-09-02T10:35:02+08:00");
    const loader = vi.fn(async (query: MarketIndexSeriesQuery) => ({
      hasMore: false,
      items: [{ ...bars[0]!, indexCode: query.indexCode }],
      limit: query.limit,
      nextCursor: null,
      snapshotHash: hash,
    }));
    const result = useDashboardMarketIndexTrends({
      api: { getBars: (query, _options) => loader(query) },
      connectionStatus: "CONNECTED",
      observedAt,
      summaries: shallowRef([snapshot]),
    });

    await flushPromises();

    expect(loader).toHaveBeenCalledTimes(4);
    expect(loader.mock.calls.map(([query]) => query.indexCode)).toEqual([
      "000001.SH", "399001.SZ", "399006.SZ", "000688.SH",
    ]);
    expect(loader).toHaveBeenCalledWith(
      expect.objectContaining({
        endAt: "2026-09-02T10:35:02+08:00",
        indexCode: "000688.SH",
        interval: "FIVE_MINUTE",
        limit: 64,
        startAt: "2026-09-02T09:30:00+08:00",
      }),
    );
    expect(result.trends.value["000688.SH"].status).toBe("READY");
    expect(result.trends.value["000001.SH"].page?.items?.[0]?.indexCode).toBe("000001.SH");
  });

  it("anchors the current-day range to dashboard time instead of a prior-day summary", async () => {
    const loader = vi.fn(async (query: MarketIndexSeriesQuery) => ({
      hasMore: false,
      items: [],
      limit: query.limit,
      nextCursor: null,
      snapshotHash: hash,
    }));
    useDashboardMarketIndexTrends({
      api: { getBars: (query, _options) => loader(query) },
      connectionStatus: "CONNECTED",
      observedAt: "2026-09-03T09:40:02+08:00",
      summaries: [snapshot],
    });

    await flushPromises();

    expect(loader).toHaveBeenCalledWith(
      expect.objectContaining({
        endAt: "2026-09-03T09:40:02+08:00",
        indexCode: "000688.SH",
        startAt: "2026-09-03T09:30:00+08:00",
      }),
    );
  });

  it("keeps successful index data visible when only one trend request fails", async () => {
    const loader = vi.fn(async (query: MarketIndexSeriesQuery) => {
      if (query.indexCode === "399006.SZ") throw new Error("provider unavailable");
      return {
        hasMore: false,
        items: [{ ...bars[0]!, indexCode: query.indexCode }],
        limit: query.limit,
        nextCursor: null,
        snapshotHash: hash,
      };
    });
    const result = useDashboardMarketIndexTrends({
      api: { getBars: (query, _options) => loader(query) },
      connectionStatus: "CONNECTED",
      observedAt: at,
      summaries: [snapshot],
    });

    await flushPromises();

    expect(result.trends.value["399006.SZ"].status).toBe("ERROR");
    expect(result.trends.value["399006.SZ"].error).toBe("当日指数走势暂不可用");
    expect(result.trends.value["000688.SH"].status).toBe("READY");
  });

  it("accepts canonical timestamps with fractional seconds", () => {
    expect(
      buildCurrentDayQuery("000001.SH", "2026-09-02T10:35:02.123456+08:00"),
    ).toEqual({
      endAt: "2026-09-02T10:35:02.123456+08:00",
      indexCode: "000001.SH",
      interval: "FIVE_MINUTE",
      limit: 64,
      startAt: "2026-09-02T09:30:00+08:00",
    });
  });

  it("does not request trends while the dashboard connection is unavailable", async () => {
    const loader = vi.fn();
    useDashboardMarketIndexTrends({
      api: { getBars: loader },
      connectionStatus: "DISCONNECTED",
      observedAt: at,
      summaries: [snapshot],
    });

    await flushPromises();

    expect(loader).not.toHaveBeenCalled();
  });
});

describe("useMarketIndexSeries", () => {
  it("aborts stale requests and keeps only the newest immutable page", async () => {
    const query = shallowRef<MarketIndexSeriesQuery | null>({
      endAt: "2026-09-02T10:45:00+08:00",
      indexCode: "000688.SH",
      interval: "FIVE_MINUTE",
      limit: 100,
      startAt: "2026-09-02T09:35:00+08:00",
    });
    const resolvers: Array<(page: MarketIndexBarPage) => void> = [];
    const signals: AbortSignal[] = [];
    const loader = vi.fn(
      (_query: MarketIndexSeriesQuery, signal: AbortSignal) =>
        new Promise<MarketIndexBarPage>((resolve) => {
          signals.push(signal);
          resolvers.push(resolve);
        }),
    );
    const result = useMarketIndexSeries({ loader, query: computed(() => query.value) });

    expect(isShallow(result.page)).toBe(true);
    query.value = {
      endAt: "2026-09-02T10:45:00+08:00",
      indexCode: "000688.SH",
      interval: "OFFICIAL_DAILY",
      limit: 100,
      startAt: "2026-09-02T09:35:00+08:00",
    };
    await nextTick();
    expect(signals[0]?.aborted).toBe(true);

    resolvers[0]?.({ hasMore: false, items: [], limit: 100, nextCursor: null, snapshotHash: hash });
    resolvers[1]?.({ hasMore: false, items: [...bars], limit: 100, nextCursor: null, snapshotHash: hash });
    await nextTick();
    await nextTick();

    expect(result.status.value).toBe("READY");
    expect(result.page.value?.items).toEqual(bars);
    expect(Object.isFrozen(result.page.value)).toBe(true);
  });

  it("retains the last validated page when a later range refresh fails", async () => {
    const query = shallowRef<MarketIndexSeriesQuery | null>({
      endAt: "2026-09-02T10:45:00+08:00",
      indexCode: "000688.SH",
      interval: "FIVE_MINUTE",
      limit: 100,
      startAt: "2026-09-02T09:35:00+08:00",
    });
    const page: MarketIndexBarPage = {
      hasMore: false,
      items: [...bars],
      limit: 100,
      nextCursor: null,
      snapshotHash: hash,
    };
    const loader = vi
      .fn()
      .mockResolvedValueOnce(page)
      .mockRejectedValueOnce(new Error("untrusted detail"));
    const result = useMarketIndexSeries({ loader, query: computed(() => query.value) });
    await flushPromises();
    expect(result.status.value).toBe("READY");

    query.value = { ...query.value!, startAt: "2026-09-02T09:30:00+08:00" };
    await nextTick();
    await flushPromises();

    expect(result.status.value).toBe("ERROR");
    expect(result.error.value).toBe("指数历史暂不可用");
    expect(result.page.value).toEqual(page);
  });
});

describe("market index history API", () => {
  it("uses generated identities and rejects undeclared response fields", async () => {
    const page: MarketIndexBarPage = {
      hasMore: false,
      items: [...bars],
      limit: 100,
      nextCursor: null,
      snapshotHash: hash,
    };
    const fetchImplementation = vi.fn(async () => new Response(JSON.stringify(page)));
    const api = createMarketIndexApi(fetchImplementation);
    const query: MarketIndexSeriesQuery = {
      endAt: "2026-09-02T10:45:00+08:00",
      indexCode: "000688.SH",
      interval: "FIVE_MINUTE",
      limit: 100,
      startAt: "2026-09-02T09:35:00+08:00",
    };

    await expect(api.getBars(query)).resolves.toEqual(page);
    expect(fetchImplementation).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/market-indexes/000688.SH/bars?"),
      expect.objectContaining({ method: "GET" }),
    );

    const unsafe = createMarketIndexApi(async () =>
      new Response(JSON.stringify({ ...page, decisionEffect: "BUY" })),
    );
    await expect(unsafe.getBars(query)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
