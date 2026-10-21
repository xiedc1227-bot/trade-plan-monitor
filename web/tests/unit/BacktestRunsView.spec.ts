import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { defineComponent, h, nextTick, shallowRef } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import type { LocationQuery, LocationQueryRaw } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import type {
  BacktestRunFiltersView,
  BacktestRunPage,
  BacktestRunSummaryView,
} from "../../src/api/generated";
import type { BacktestApi, BacktestRunListQuery } from "../../src/api/backtests";
import { ApiClientError } from "../../src/api/transport";
import {
  useBacktestRuns,
  type UseBacktestRunsOptions,
} from "../../src/composables/useBacktestRuns";
import BacktestRunsView from "../../src/views/BacktestRunsView.vue";

const PLAN_VERSION_ID = "123e4567-e89b-42d3-a456-426614174000";
const DATASET_HASH = "a".repeat(64);
const CURSOR = "cursor_payload.cursor_mac";
const COMPLETED_AT = "2026-08-29T12:00:00.000000+08:00";

function filters(overrides: Partial<BacktestRunFiltersView> = {}): BacktestRunFiltersView {
  return {
    completedFrom: null,
    completedTo: null,
    datasetHash: null,
    pinned: null,
    planVersionId: null,
    symbol: null,
    ...overrides,
  };
}

function summary(index = 1, overrides: Partial<BacktestRunSummaryView> = {}): BacktestRunSummaryView {
  return {
    availability: {
      decisionDetails: "AVAILABLE",
      equitySeries: "AVAILABLE",
      executionOutcomeDetails: "AVAILABLE",
      signalDetails: "AVAILABLE",
    },
    completedAt: COMPLETED_AT,
    datasetHash: DATASET_HASH,
    eventEnd: "2026-08-28",
    eventStart: "2026-08-01",
    fillCount: 3,
    metrics: {
      blockedCount: 0,
      finalCashFen: "10000",
      finalEquityFen: "12000",
      initialCashFen: "10000",
      initialEquityFen: "10000",
      maximumDrawdown: "0.05",
      realizedPnlFen: "2000",
      skippedCount: 0,
      totalCostFen: "100",
      totalReturn: "0.2",
      tradeCount: 3,
      turnoverFen: "30000",
      unrealizedPnlFen: "0",
      winRate: "0.6666666666666666666666666667",
      winningSellCount: 2,
    },
    pinned: false,
    planHash: "b".repeat(64),
    planVersionId: PLAN_VERSION_ID,
    reportHash: "c".repeat(64),
    revision: 0,
    runId: index.toString(16).padStart(64, "0"),
    status: "COMPLETED",
    symbol: "000001.SZ",
    ...overrides,
  };
}

function page(options: {
  filters?: BacktestRunFiltersView;
  hasMore?: boolean;
  items?: BacktestRunSummaryView[];
  nextCursor?: string | null;
} = {}): BacktestRunPage {
  return {
    filters: options.filters ?? filters(),
    hasMore: options.hasMore ?? false,
    highWatermark: "watermark.anchor",
    items: options.items ?? [summary()],
    limit: 20,
    nextCursor: options.nextCursor ?? null,
  };
}

function apiWith(overrides: Partial<BacktestApi> = {}): BacktestApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected API call")));
  return {
    cancelJob: unused,
    getDataset: unused,
    getEquitySeries: unused,
    getJob: unused,
    getRun: unused,
    listDatasets: unused,
    listDetails: unused,
    listFills: unused,
    listJobs: unused,
    listRuns: unused,
    pinRun: unused,
    submitRun: unused,
    syncData: unused,
    verifyDataset: unused,
    ...overrides,
  } as BacktestApi;
}

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<Value>((resolver, rejecter) => {
    resolve = resolver;
    reject = rejecter;
  });
  return { promise, reject, resolve };
}

async function mountRunsView(options: {
  api?: BacktestApi;
  cancelSymbolNavigation?: string;
  query?: Record<string, string>;
} = {}): Promise<{ router: Router; wrapper: VueWrapper }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/backtests", component: { template: "<div />" } },
      { path: "/backtests/:runId", component: { template: "<div />" } },
    ],
  });
  await router.push({ path: "/backtests", query: options.query ?? {} });
  await router.isReady();
  if (options.cancelSymbolNavigation !== undefined) {
    router.beforeEach((to) =>
      to.query.symbol === options.cancelSymbolNavigation ? false : undefined,
    );
  }
  const wrapper = mount(BacktestRunsView, {
    attachTo: document.body,
    global: { plugins: [router] },
    props: { api: options.api ?? apiWith() },
  });
  await flushPromises();
  return { router, wrapper };
}

describe("BacktestRunsView", () => {
  it("retains same-query rows through a failed refresh and restores a visited previous page", async () => {
    const refreshing = deferred<BacktestRunPage>();
    const listRuns = vi.fn<BacktestApi["listRuns"]>()
      .mockResolvedValueOnce(page({ hasMore: true, nextCursor: CURSOR }))
      .mockReturnValueOnce(refreshing.promise)
      .mockResolvedValueOnce(page({ items: [summary(2)] }))
      .mockResolvedValueOnce(page({ hasMore: true, nextCursor: CURSOR }));
    const { wrapper, router } = await mountRunsView({ api: apiWith({ listRuns }) });
    await wrapper.get('[data-testid="refresh-run-list"]').trigger("click");
    expect(wrapper.findAll('[data-testid="backtest-run-row"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("上次读取");
    refreshing.reject(new Error("failed")); await flushPromises();
    expect(wrapper.findAll('[data-testid="backtest-run-row"]')).toHaveLength(1);
    expect(wrapper.get('[role="alert"]').text()).toContain("上次读取");
    await wrapper.get('[data-testid="next-run-page"]').trigger("click"); await flushPromises();
    expect(router.currentRoute.value.query.cursor).toBe(CURSOR);
    await wrapper.get('[data-testid="previous-run-page"]').trigger("click"); await flushPromises();
    expect(router.currentRoute.value.query.cursor).toBeUndefined();
    expect(wrapper.get('[data-testid="run-page-number"]').text()).toContain("1");
    wrapper.unmount();
  });

  it("reads accepted tasks and status filters without submitting or treating a job ID as a run", async () => {
    const listRuns = vi.fn();
    const listJobs = vi.fn().mockResolvedValue({ items: [{ jobId: "queued-data", status: "QUEUED", kind: "DATA_SYNC", updatedAt: COMPLETED_AT, runId: null }], nextCursor: null, hasMore: false });
    const client = apiWith({ listJobs, listRuns });
    const { wrapper, router } = await mountRunsView({ api: client, query: { view: "tasks" } });
    expect(listRuns).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="task-row"]').text()).toContain("准备历史数据");
    expect(wrapper.find('[data-testid="run-detail-link"]').exists()).toBe(false);
    await wrapper.get('[data-testid="task-status-filter"]').setValue("FAILED"); await flushPromises();
    expect(router.currentRoute.value.query.status).toBe("FAILED");
    expect(listJobs.mock.calls.some(([query]) => query.status?.includes("FAILED"))).toBe(true);
    expect(client.submitRun).not.toHaveBeenCalled(); expect(client.syncData).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it("shows common filters without dataset or plan-version lookup controls", async () => {
    const { wrapper } = await mountRunsView({ api: apiWith({ listRuns: vi.fn().mockResolvedValue(page()) }) });
    expect(wrapper.get('#run-filter-end-from').attributes('type')).toBe('date');
    expect(wrapper.get('#run-filter-end-to').attributes('type')).toBe('date');
    expect(wrapper.get('[data-testid="advanced-run-filters"]').attributes("open")).toBeUndefined();
    expect(wrapper.find('[data-testid="legacy-run-filters"]').exists()).toBe(false);
    expect(wrapper.find('#run-filter-dataset-hash').exists()).toBe(false);
    expect(wrapper.find('#run-filter-plan-version').exists()).toBe(false);
    expect(wrapper.find('#run-filter-sort').exists()).toBe(false);
    expect(wrapper.text()).toContain('回测截止日期');
    expect(wrapper.text()).not.toContain('完成开始时间');
    wrapper.unmount();
  });
  it("restores and submits end-date filters without converting them into completion timestamps", async () => {
    const listRuns = vi.fn<BacktestApi['listRuns']>().mockImplementation(async query => page({ filters: filters({ eventEndFrom: query?.eventEndFrom ?? null, eventEndTo: query?.eventEndTo ?? null }) }));
    const { wrapper, router } = await mountRunsView({ api: apiWith({ listRuns }), query: { eventEndFrom: '2026-08-28' } });
    expect(wrapper.get<HTMLInputElement>('#run-filter-end-from').element.value).toBe('2026-08-28');
    await wrapper.get('#run-filter-end-to').setValue('2026-08-29');
    await wrapper.get('[data-testid="apply-run-filters"]').trigger('click'); await flushPromises();
    expect(listRuns.mock.calls.at(-1)?.[0]).toEqual({ eventEndFrom: '2026-08-28', eventEndTo: '2026-08-29', limit: 20 });
    expect(router.currentRoute.value.query.completedFrom).toBeUndefined();
    wrapper.unmount();
  });
  it("normalizes all URL filters, fixed sort, and first-page identity before one request", async () => {
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockResolvedValue(
      page({
        filters: filters({
          completedFrom: "2026-08-29T10:00:00.000000+08:00",
          pinned: true,
          symbol: "000001.SZ",
        }),
      }),
    );
    const { router, wrapper } = await mountRunsView({
      api: apiWith({ listRuns }),
      query: {
        completedFrom: "2026-08-29T10:00:00+08:00",
        datasetHash: DATASET_HASH.toUpperCase(),
        page: "9",
        pinned: "true",
        planVersionId: PLAN_VERSION_ID.toUpperCase(),
        sort: "unsupported",
        symbol: "000001.sz",
      },
    });

    expect(listRuns).toHaveBeenCalledWith(
      {
        completedFrom: "2026-08-29T10:00:00.000000+08:00",
        limit: 20,
        pinned: "true",
        symbol: "000001.SZ",
      } satisfies BacktestRunListQuery,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(router.currentRoute.value.query).toEqual({
      completedFrom: "2026-08-29T10:00:00.000000+08:00",
      page: "1",
      pinned: "true",
      sort: "completedAt_desc",
      symbol: "000001.SZ",
    });
    expect(listRuns).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="legacy-run-filters"]').attributes('open')).toBeDefined();
    expect(wrapper.get('#run-filter-completed-from').element).toBeInstanceOf(HTMLInputElement);
    expect(wrapper.find('#run-filter-dataset-hash').exists()).toBe(false);
    expect(wrapper.find('#run-filter-plan-version').exists()).toBe(false);
    wrapper.unmount();
  });

  it.each([
    { datasetHash: DATASET_HASH },
    { planVersionId: PLAN_VERSION_ID },
    { datasetHash: "invalid", planVersionId: "invalid" },
  ])("removes retired URL conditions and their cursor before querying: %j", async (retired) => {
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockResolvedValue(
      page({ filters: filters({ eventEndFrom: "2026-08-28", pinned: false, symbol: "000001.SZ" }) }),
    );
    const { router, wrapper } = await mountRunsView({
      api: apiWith({ listRuns }),
      query: { ...retired, cursor: CURSOR, page: "2", symbol: "000001.SZ", eventEndFrom: "2026-08-28", pinned: "false" },
    });
    expect(router.currentRoute.value.query).toEqual({
      page: "1", sort: "completedAt_desc", symbol: "000001.SZ", eventEndFrom: "2026-08-28", pinned: "false",
    });
    expect(listRuns).toHaveBeenCalledTimes(1);
    expect(listRuns.mock.calls[0]?.[0]).toEqual({ symbol: "000001.SZ", eventEndFrom: "2026-08-28", pinned: "false", limit: 20 });
    expect(wrapper.find('#run-filter-dataset-hash').exists()).toBe(false);
    expect(wrapper.find('#run-filter-plan-version').exists()).toBe(false);
    wrapper.unmount();
  });

  it("applies validated filters through the URL and clears cursor traversal", async () => {
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockImplementation(async (query) => {
      const current = query ?? {};
      return page({
        filters: filters({
          eventEndTo: current.eventEndTo ?? null,
          pinned: current.pinned == null ? null : current.pinned === "true",
          symbol: current.symbol ?? null,
        }),
      });
    });
    const { router, wrapper } = await mountRunsView({
      api: apiWith({ listRuns }),
      query: { cursor: CURSOR, page: "2", sort: "completedAt_desc" },
    });
    await wrapper.get<HTMLInputElement>("#run-filter-symbol").setValue("600000.sh");
    await wrapper
      .get<HTMLInputElement>("#run-filter-end-to")
      .setValue("2026-08-29");
    await wrapper.get<HTMLSelectElement>("#run-filter-pinned").setValue("false");
    await wrapper.get('[data-testid="apply-run-filters"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.query).toEqual({
      eventEndTo: "2026-08-29",
      page: "1",
      pinned: "false",
      sort: "completedAt_desc",
      symbol: "600000.SH",
    });
    expect(listRuns.mock.calls.at(-1)?.[0]).toEqual({
      eventEndTo: "2026-08-29",
      limit: 20,
      pinned: "false",
      symbol: "600000.SH",
    });
    wrapper.unmount();
  });

  it("focuses filter errors and performs no request for invalid filter shape", async () => {
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockResolvedValue(page());
    const { wrapper } = await mountRunsView({ api: apiWith({ listRuns }) });
    await wrapper.get<HTMLInputElement>("#run-filter-symbol").setValue("private<script>");
    await wrapper
      .get<HTMLInputElement>("#run-filter-end-from")
      .setValue("2026-08-29");
    await wrapper.get('#run-filter-end-to').setValue('2026-08-28');
    await wrapper.get('[data-testid="apply-run-filters"]').trigger("click");
    await flushPromises();

    const errors = wrapper.get('[data-testid="run-filter-errors"]');
    expect(document.activeElement).toBe(errors.element);
    expect(errors.text()).toContain("股票代码");
    expect(errors.text()).toContain("截止开始日期不得晚于截止结束日期");
    expect(wrapper.html()).not.toContain("<script>");
    expect(listRuns).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("aborts stale generations and never lets an older page replace the active route", async () => {
    const stale = deferred<BacktestRunPage>();
    const signals: AbortSignal[] = [];
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockImplementation((query, options) => {
      const current = query ?? {};
      if (options?.signal !== undefined) signals.push(options.signal);
      return current.symbol == null
        ? stale.promise
        : Promise.resolve(
            page({
              filters: filters({ symbol: current.symbol }),
              items: [summary(2, { symbol: current.symbol })],
            }),
          );
    });
    const { router, wrapper } = await mountRunsView({ api: apiWith({ listRuns }) });
    await router.push({
      path: "/backtests",
      query: { page: "1", sort: "completedAt_desc", symbol: "600000.SH" },
    });
    await flushPromises();

    expect(signals[0]?.aborted).toBe(true);
    expect(wrapper.text()).toContain("600000.SH");
    stale.resolve(page({ items: [summary(1, { symbol: "000001.SZ" })] }));
    await flushPromises();
    const activeRow = wrapper.get('[data-testid="backtest-run-row"]');
    expect(activeRow.text()).toContain("600000.SH");
    expect(activeRow.text()).not.toContain("000001.SZ");
    wrapper.unmount();
  });

  it("invalidates an old request before awaiting delayed canonical replacement", async () => {
    const stale = deferred<BacktestRunPage>();
    const replacement = deferred<void>();
    const signals: AbortSignal[] = [];
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockImplementation((query, options) => {
      if (options?.signal !== undefined) signals.push(options.signal);
      return query?.symbol === "600000.SZ"
        ? Promise.resolve(
            page({
              filters: filters({ symbol: "600000.SZ" }),
              items: [summary(2, { symbol: "600000.SZ" })],
            }),
          )
        : stale.promise;
    });
    const query = shallowRef<LocationQuery>({ page: "1", sort: "completedAt_desc" });
    let runs!: ReturnType<typeof useBacktestRuns>;
    const Harness = defineComponent({
      setup() {
        runs = useBacktestRuns({
          api: apiWith({ listRuns }),
          pushQuery: () => undefined,
          query,
          replaceQuery: async (next: LocationQueryRaw) => {
            await replacement.promise;
            query.value = next as LocationQuery;
          },
        });
        return () => h("div", runs.items.value.map((item) => item.symbol).join(","));
      },
    });
    const wrapper = mount(Harness);
    await flushPromises();

    query.value = { symbol: "600000.sz" };
    await nextTick();
    expect(signals[0]?.aborted).toBe(true);
    stale.resolve(page({ items: [summary(1, { symbol: "000001.SZ" })] }));
    await flushPromises();
    expect(runs.items.value).toHaveLength(0);

    replacement.resolve();
    await flushPromises();
    expect(runs.items.value[0]?.symbol).toBe("600000.SZ");
    wrapper.unmount();
  });

  it("restarts a pending request after same-key URL canonicalization", async () => {
    const stale = deferred<BacktestRunPage>();
    const replacement = deferred<void>();
    const signals: AbortSignal[] = [];
    const listRuns = vi
      .fn<BacktestApi["listRuns"]>()
      .mockImplementationOnce((_query, options) => {
        if (options?.signal !== undefined) signals.push(options.signal);
        return stale.promise;
      })
      .mockImplementationOnce((_query, options) => {
        if (options?.signal !== undefined) signals.push(options.signal);
        return Promise.resolve(
          page({ items: [summary(2, { symbol: "600000.SH" })] }),
        );
      });
    const query = shallowRef<LocationQuery>({ page: "1", sort: "completedAt_desc" });
    let runs!: ReturnType<typeof useBacktestRuns>;
    const Harness = defineComponent({
      setup() {
        runs = useBacktestRuns({
          api: apiWith({ listRuns }),
          pushQuery: () => undefined,
          query,
          replaceQuery: async (next: LocationQueryRaw) => {
            await replacement.promise;
            query.value = next as LocationQuery;
          },
        });
        return () => h("div", runs.items.value.map((item) => item.symbol).join(","));
      },
    });
    const wrapper = mount(Harness);
    await flushPromises();

    query.value = { page: "01", sort: "completedAt_desc" };
    await nextTick();
    expect(signals[0]?.aborted).toBe(true);
    replacement.resolve();
    await flushPromises();

    expect(listRuns).toHaveBeenCalledTimes(2);
    expect(runs.queryState.value).toBe("READY");
    expect(runs.items.value[0]?.symbol).toBe("600000.SH");
    stale.resolve(page({ items: [summary(1, { symbol: "000001.SZ" })] }));
    await flushPromises();
    expect(runs.items.value[0]?.symbol).toBe("600000.SH");
    wrapper.unmount();
  });

  it("advances with an opaque cursor and replaces rather than accumulates 100-row pages", async () => {
    const firstItems = Array.from({ length: 100 }, (_item, index) => summary(index + 1));
    const secondItems = Array.from({ length: 100 }, (_item, index) => summary(index + 101));
    const listRuns = vi
      .fn<BacktestApi["listRuns"]>()
      .mockResolvedValueOnce(
        page({ hasMore: true, items: firstItems, nextCursor: CURSOR }),
      )
      .mockResolvedValueOnce(page({ items: secondItems }));
    const { router, wrapper } = await mountRunsView({ api: apiWith({ listRuns }) });

    expect(wrapper.findAll('[data-testid="backtest-run-row"]')).toHaveLength(100);
    await wrapper.get('[data-testid="next-run-page"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({
      cursor: CURSOR,
      page: "2",
      sort: "completedAt_desc",
    });
    expect(wrapper.findAll('[data-testid="backtest-run-row"]')).toHaveLength(100);
    expect(wrapper.text()).not.toContain(firstItems[0]?.runId ?? "missing");
    expect(wrapper.text()).toContain(secondItems[0]?.runId ?? "missing");
    wrapper.unmount();
  });

  it("clears a stale membership cursor, returns to page one, and politely announces it", async () => {
    const listRuns = vi
      .fn<BacktestApi["listRuns"]>()
      .mockRejectedValueOnce(
        new ApiClientError({ code: "CONFLICT", message: "private", status: 409 }),
      )
      .mockResolvedValueOnce(
        page({ filters: filters({ pinned: true }), items: [summary()] }),
      );
    const { router, wrapper } = await mountRunsView({
      api: apiWith({ listRuns }),
      query: { cursor: CURSOR, page: "2", pinned: "true", sort: "completedAt_desc" },
    });

    expect(router.currentRoute.value.query).toEqual({
      page: "1",
      pinned: "true",
      sort: "completedAt_desc",
    });
    expect(listRuns).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="run-list-announcement"]').text()).toContain(
      "列表成员已变化，已返回第一页",
    );
    expect(wrapper.text()).not.toContain("private");
    wrapper.unmount();
  });

  it("round-trips browser back/forward state without keeping hidden filter authority", async () => {
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockImplementation(async (query) => {
      const current = query ?? {};
      return page({
        filters: filters({ symbol: current.symbol ?? null }),
        items: [
          summary(current.symbol === "600000.SH" ? 2 : 1, {
            symbol: current.symbol ?? "000001.SZ",
          }),
        ],
      });
    });
    const { router, wrapper } = await mountRunsView({ api: apiWith({ listRuns }) });
    await router.push({
      path: "/backtests",
      query: { page: "1", sort: "completedAt_desc", symbol: "600000.SH" },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("600000.SH");

    router.back();
    await flushPromises();
    expect(wrapper.text()).toContain("000001.SZ");
    router.forward();
    await flushPromises();
    expect(wrapper.text()).toContain("600000.SH");
    wrapper.unmount();
  });

  it("fails closed with fixed copy when a filter push is cancelled by navigation", async () => {
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockResolvedValue(page());
    const { wrapper } = await mountRunsView({
      api: apiWith({ listRuns }),
      cancelSymbolNavigation: "600000.SH",
      query: { page: "1", sort: "completedAt_desc" },
    });
    await wrapper.get<HTMLInputElement>("#run-filter-symbol").setValue("600000.SH");
    await wrapper.get('[data-testid="apply-run-filters"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("URL 无法更新");
    expect(listRuns).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("treats reapplying the current canonical filters as a successful no-op", async () => {
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockResolvedValue(page());
    const { wrapper } = await mountRunsView({
      api: apiWith({ listRuns }),
      query: { page: "1", sort: "completedAt_desc" },
    });

    await wrapper.get('[data-testid="apply-run-filters"]').trigger("click");
    await flushPromises();

    expect(listRuns).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="backtest-run-row"]').text()).toContain(
      "000001.SZ",
    );
    wrapper.unmount();
  });

  it("ignores an old push failure after a newer filter intent succeeds", async () => {
    const oldNavigation = deferred<void>();
    const query = shallowRef<LocationQuery>({ page: "1", sort: "completedAt_desc" });
    const pushQuery = vi
      .fn<UseBacktestRunsOptions["pushQuery"]>()
      .mockImplementationOnce(() => oldNavigation.promise)
      .mockImplementationOnce((next) => {
        query.value = next as LocationQuery;
      });
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockImplementation(async (request) =>
      page({
        filters: filters({ symbol: request?.symbol ?? null }),
        items: [summary(2, { symbol: request?.symbol ?? "000001.SZ" })],
      }),
    );
    let runs!: ReturnType<typeof useBacktestRuns>;
    const Harness = defineComponent({
      setup() {
        runs = useBacktestRuns({
          api: apiWith({ listRuns }),
          pushQuery,
          query,
          replaceQuery: () => undefined,
        });
        return () => h("div", runs.items.value.map((item) => item.symbol).join(","));
      },
    });
    const wrapper = mount(Harness);
    await flushPromises();

    void runs.applyFilters(filters({ symbol: "600000.SH" }));
    await nextTick();
    void runs.applyFilters(filters({ symbol: "000001.SZ" }));
    await flushPromises();
    oldNavigation.reject(new Error("old cancelled navigation"));
    await flushPromises();

    expect(runs.queryState.value).toBe("READY");
    expect(runs.errorMessage.value).toBeNull();
    expect(runs.items.value[0]?.symbol).toBe("000001.SZ");
    wrapper.unmount();
  });

  it("restarts an interrupted refresh when URL normalization keeps the same API filters", async () => {
    const pending = deferred<BacktestRunPage>();
    const query = shallowRef<LocationQuery>({ page: "1", sort: "completedAt_desc" });
    const listRuns = vi.fn<BacktestApi["listRuns"]>()
      .mockResolvedValueOnce(page())
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValue(page());
    let runs!: ReturnType<typeof useBacktestRuns>;
    const wrapper = mount(defineComponent({ setup() {
      runs = useBacktestRuns({ api: apiWith({ listRuns }), query,
        pushQuery: () => undefined,
        replaceQuery: next => { query.value = next as LocationQuery; },
      });
      return () => null;
    } }));
    await flushPromises();
    void runs.refresh();
    await nextTick();
    expect(runs.refreshing.value).toBe(true);
    query.value = { ...query.value, unused: "remove" };
    await flushPromises();
    expect(listRuns).toHaveBeenCalledTimes(3);
    expect(runs.queryState.value).toBe("READY");
    expect(runs.refreshing.value).toBe(false);
    pending.resolve(page({ items: [] }));
    await flushPromises();
    expect(runs.queryState.value).toBe("READY");
    wrapper.unmount();
  });

  it("ignores an old canonical replace failure after a newer route succeeds", async () => {
    const oldReplacement = deferred<void>();
    const query = shallowRef<LocationQuery>({ symbol: "600000.sz" });
    const listRuns = vi.fn<BacktestApi["listRuns"]>().mockImplementation(async (request) =>
      page({
        filters: filters({ symbol: request?.symbol ?? null }),
        items: [summary(2, { symbol: request?.symbol ?? "000001.SZ" })],
      }),
    );
    let runs!: ReturnType<typeof useBacktestRuns>;
    const Harness = defineComponent({
      setup() {
        runs = useBacktestRuns({
          api: apiWith({ listRuns }),
          pushQuery: () => undefined,
          query,
          replaceQuery: () => oldReplacement.promise,
        });
        return () => h("div", runs.items.value.map((item) => item.symbol).join(","));
      },
    });
    const wrapper = mount(Harness);
    await nextTick();

    query.value = {
      page: "1",
      sort: "completedAt_desc",
      symbol: "000001.SZ",
    };
    await flushPromises();
    oldReplacement.reject(new Error("old canonical replacement failed"));
    await flushPromises();

    expect(runs.queryState.value).toBe("READY");
    expect(runs.errorMessage.value).toBeNull();
    expect(runs.items.value[0]?.symbol).toBe("000001.SZ");
    wrapper.unmount();
  });

  it("renders exact values, canonical machine time, fixed sort semantics, and native run links", async () => {
    const exact = summary(1, {
      metrics: {
        ...summary().metrics,
        finalEquityFen: "9007199254740993123",
        totalReturn: "0.1234567890123456789012345678",
      },
      pinned: true,
    });
    const { wrapper } = await mountRunsView({
      api: apiWith({ listRuns: vi.fn().mockResolvedValue(page({ items: [exact] })) }),
    });

    expect(wrapper.text()).toContain("90071992547409931.23");
    expect(wrapper.text()).toContain("0.1234567890123456789012345678");
    expect(wrapper.get("time").attributes("datetime")).toBe(COMPLETED_AT);
    expect(wrapper.get("th[aria-sort]").attributes("aria-sort")).toBe("descending");
    expect(wrapper.get('[data-testid="run-detail-link"]').attributes("href")).toBe(
      `/backtests/${exact.runId}`,
    );
    wrapper.unmount();
  });

  it("exposes loading, empty, safe failure, and refresh states", async () => {
    const pending = deferred<BacktestRunPage>();
    const listRuns = vi
      .fn<BacktestApi["listRuns"]>()
      .mockReturnValueOnce(pending.promise)
      .mockRejectedValueOnce(new Error("private provider body"))
      .mockResolvedValueOnce(page({ items: [] }));
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/backtests", component: { template: "<div />" } }],
    });
    await router.push("/backtests");
    await router.isReady();
    const wrapper = mount(BacktestRunsView, {
      attachTo: document.body,
      global: { plugins: [router] },
      props: { api: apiWith({ listRuns }) },
    });
    await flushPromises();
    expect(wrapper.get('[data-testid="run-list-state"]').text()).toContain("正在读取");

    pending.resolve(page({ items: [] }));
    await flushPromises();
    expect(wrapper.get('[data-testid="run-list-state"]').text()).toContain("暂无回测运行");
    await wrapper.get('[data-testid="refresh-run-list"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("运行记录暂不可用");
    expect(wrapper.text()).not.toContain("private provider body");
    await wrapper.get('[data-testid="refresh-run-list"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="run-list-state"]').text()).toContain("暂无回测运行");
    wrapper.unmount();
  });
});
