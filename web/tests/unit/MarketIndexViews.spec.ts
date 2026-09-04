import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { computed, isShallow, nextTick, shallowRef } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  IndexConditionEvidenceView,
  MarketIndexBarPage,
  MarketIndexBarView,
  MarketIndexSnapshotView,
  SymbolReferenceMarketView,
} from "../../src/api/generated";
import { createMarketIndexApi } from "../../src/api/marketIndexes";
import IndexConditionProgress from "../../src/components/market-index/IndexConditionProgress.vue";
import MarketIndexChart from "../../src/components/market-index/MarketIndexChart.vue";
import MarketIndexDataStrip from "../../src/components/market-index/MarketIndexDataStrip.vue";
import ReferenceMarketPanel from "../../src/components/market-index/ReferenceMarketPanel.vue";
import {
  useMarketIndexSeries,
  type MarketIndexSeriesQuery,
} from "../../src/composables/useMarketIndexSeries";

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
  it("keeps shared facts separate and leaves a failed board visible", () => {
    const wrapper = mount(MarketIndexDataStrip, {
      props: { indexes: [snapshot, blockedSnapshot] },
    });

    expect(wrapper.findAll('[data-testid="market-index-card"]')).toHaveLength(2);
    expect(wrapper.text()).toContain("参考板块指数：共用数据");
    expect(wrapper.text()).toContain("SMA 20");
    expect(wrapper.text()).toContain("PROVIDER_UNAVAILABLE");
    expect(wrapper.text()).not.toContain("允许买入");
    expect(wrapper.text()).not.toContain("计划条件");
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
  });

  it("shows exact point text in an accessible index-only table", () => {
    const wrapper = mount(MarketIndexChart, { props: { bars } });

    expect(wrapper.get("caption").text()).toContain("板块指数点位");
    expect(wrapper.get("table").text()).toContain("1234.56");
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
