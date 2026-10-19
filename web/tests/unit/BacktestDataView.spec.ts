import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import type {
  BacktestDatasetCoverageView,
  BacktestDatasetPage,
  BacktestDatasetScopeInput,
  BacktestDatasetView,
  BacktestJobView,
} from "../../src/api/generated";
import type { BacktestApi } from "../../src/api/backtests";
import BacktestDataView from "../../src/views/BacktestDataView.vue";

const DATASET_HASH_A = "a".repeat(64);
const DATASET_HASH_B = "b".repeat(64);
const JOB_ID = "data-job-001";

const defaultScope: BacktestDatasetScopeInput = {
  adjustmentPolicy: "NONE",
  end: "2026-08-28",
  historicalProfile: "TUSHARE_STK_MINS_241_END_V1",
  start: "2026-08-01",
  symbols: ["000001.SZ", "600000.SH"],
  warmupStart: "2026-07-01",
};

const defaultCoverage: BacktestDatasetCoverageView = {
  blockers: [],
  calendarRowCount: 20,
  dailyBarRowCount: 40,
  dailyLimitRowCount: 40,
  minuteBarCount: 9_600,
  minuteDayCount: 40,
  symbolCount: 2,
  tradingDayCount: 20,
};

function dataset(
  datasetHash = DATASET_HASH_A,
  overrides: Partial<BacktestDatasetView> = {},
): BacktestDatasetView {
  return {
    coverage: defaultCoverage,
    createdAt: "2026-08-29T10:00:00.000000+08:00",
    datasetHash,
    schemaVersion: "backtest-dataset-v1",
    scope: defaultScope,
    verifiedAt: "2026-08-29T10:01:00.000000+08:00",
    ...overrides,
  };
}

function page(
  items: BacktestDatasetView[] = [dataset()],
  overrides: Partial<BacktestDatasetPage> = {},
): BacktestDatasetPage {
  return {
    filters: {
      adjustmentPolicy: null,
      endOnOrBefore: null,
      historicalProfile: null,
      startOnOrAfter: null,
      symbol: null,
    },
    hasMore: false,
    highWatermark: "datasets-watermark-001",
    items,
    limit: 20,
    nextCursor: null,
    ...overrides,
  };
}

function job(
  kind: BacktestJobView["kind"] = "DATA_SYNC",
  overrides: Partial<BacktestJobView> = {},
): BacktestJobView {
  return {
    attempt: 1,
    cancelRequestedAt: null,
    createdAt: "2026-08-29T10:00:00.000000+08:00",
    datasetHash: kind === "DATA_SYNC" ? null : DATASET_HASH_A,
    errorCode: null,
    errorMessage: null,
    finishedAt: "2026-08-29T10:01:00.000000+08:00",
    jobId: JOB_ID,
    kind,
    progress: {
      completedUnits: 2,
      phase: "TERMINAL",
      totalUnits: 2,
      unit: "ITEMS",
      updatedAt: "2026-08-29T10:01:00.000000+08:00",
    },
    requestHash: "c".repeat(64),
    result:
      kind === "DATA_SYNC"
        ? {
            calendarRows: 20,
            dailyBarRows: 40,
            dailyLimitRows: 40,
            kind: "DATA_SYNC",
            minuteDays: 40,
            networkCalls: 8,
          }
        : kind === "DATASET_VERIFY"
          ? {
              blockers: [],
              coverage: defaultCoverage,
              datasetHash: DATASET_HASH_A,
              kind: "DATASET_VERIFY",
              ready: true,
            }
          : {
              kind: "BACKTEST_RUN",
              reportHash: "d".repeat(64),
              reused: false,
              runId: "f".repeat(64),
            },
    reused: false,
    revision: 1,
    runId: kind === "BACKTEST_RUN" ? "f".repeat(64) : null,
    startedAt: "2026-08-29T10:00:01.000000+08:00",
    status: "COMPLETED",
    updatedAt: "2026-08-29T10:01:00.000000+08:00",
    ...overrides,
  };
}

function apiWith(overrides: Partial<BacktestApi> = {}): BacktestApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected API call")));
  return {
    cancelJob: unused,
    getDataset: unused,
    getEquitySeries: unused,
    getJob: vi.fn().mockResolvedValue(job()),
    getRun: unused,
    listDatasets: vi.fn().mockResolvedValue(page()),
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
  const promise = new Promise<Value>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

async function mountDataView(options: {
  api?: BacktestApi;
  createIdempotencyKey?: () => string;
  url?: string;
} = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/backtests/data", component: { template: "<div />" } }],
  });
  await router.push(options.url ?? "/backtests/data");
  await router.isReady();
  const wrapper = mount(BacktestDataView, {
    global: { plugins: [router] },
    props: {
      api: options.api ?? apiWith(),
      ...(options.createIdempotencyKey === undefined
        ? {}
        : { createIdempotencyKey: options.createIdempotencyKey }),
    },
  });
  await flushPromises();
  return { router, wrapper };
}

describe("BacktestDataView", () => {
  it("normalizes URL-owned scope and filters once before loading one bounded page", async () => {
    const listDatasets = vi.fn().mockResolvedValue(
      page([dataset()], {
        filters: {
          adjustmentPolicy: null,
          endOnOrBefore: "2026-08-28",
          historicalProfile: null,
          startOnOrAfter: "2026-08-01",
          symbol: "000001.SZ",
        },
      }),
    );
    const { router, wrapper } = await mountDataView({
      api: apiWith({ listDatasets }),
      url:
        "/backtests/data?symbols=600000.sh,%20000001.sz&start=2026-08-01&end=2026-08-28" +
        "&warmupStart=2026-07-01&symbol=000001.sz&startOnOrAfter=2026-08-01" +
        "&endOnOrBefore=2026-08-28",
    });

    expect(router.currentRoute.value.query).toMatchObject({
      end: "2026-08-28",
      endOnOrBefore: "2026-08-28",
      start: "2026-08-01",
      startOnOrAfter: "2026-08-01",
      symbol: "000001.SZ",
      symbols: "000001.SZ,600000.SH",
      warmupStart: "2026-07-01",
    });
    expect(listDatasets).toHaveBeenCalledTimes(1);
    expect(listDatasets).toHaveBeenCalledWith(
      {
        endOnOrBefore: "2026-08-28",
        limit: 20,
        startOnOrAfter: "2026-08-01",
        symbol: "000001.SZ",
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get('[data-testid="dataset-card"]').text()).toContain(DATASET_HASH_A);
    expect(wrapper.find("main").exists()).toBe(false);
    wrapper.unmount();
  });

  it("reconstructs the form from URL back navigation without a hidden authority", async () => {
    const { router, wrapper } = await mountDataView({
      url:
        "/backtests/data?symbol=000001.SZ",
    });

    await wrapper.get<HTMLInputElement>('input[placeholder="000001.SZ"]').setValue("600000.sh");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(router.currentRoute.value.query.symbol).toBe("600000.SH");

    router.back();
    await flushPromises();
    expect(wrapper.get<HTMLInputElement>('input[placeholder="000001.SZ"]').element.value).toBe("000001.SZ");
    wrapper.unmount();
  });

  it("aborts stale URL work and never lets an older page overwrite the latest filters", async () => {
    const first = deferred<BacktestDatasetPage>();
    const second = deferred<BacktestDatasetPage>();
    const listDatasets = vi
      .fn<BacktestApi["listDatasets"]>()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { router, wrapper } = await mountDataView({ api: apiWith({ listDatasets }) });
    const firstSignal = listDatasets.mock.calls[0]?.[1]?.signal;

    await router.push({ path: "/backtests/data", query: { symbol: "600000.SH" } });
    await flushPromises();
    second.resolve(
      page([dataset(DATASET_HASH_B)], {
        filters: { ...page().filters, symbol: "600000.SH" },
      }),
    );
    await flushPromises();
    first.resolve(page([dataset(DATASET_HASH_A)]));
    await flushPromises();

    expect(firstSignal?.aborted).toBe(true);
    expect(wrapper.text()).toContain(DATASET_HASH_B);
    expect(wrapper.text()).not.toContain(DATASET_HASH_A);
    wrapper.unmount();
  });

  it("has no manual data preparation entry and never downloads on visits or filter changes", async () => {
    const syncData = vi.fn(), verifyDataset = vi.fn();
    const { wrapper } = await mountDataView({ api: apiWith({ syncData, verifyDataset }) });
    for (const text of ["应用到当前 URL", "同步历史数据", "本地验证数据集", "刷新已缓存表面"]) {
      expect(wrapper.findAll("button, label").some(item => item.text() === text)).toBe(false);
    }
    await wrapper.get('input[placeholder="000001.SZ"]').setValue("600000.SH");
    await wrapper.get("form").trigger("submit"); await flushPromises();
    expect(syncData).not.toHaveBeenCalled(); expect(verifyDataset).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("程序会自动检查"); wrapper.unmount();
  });

  it.each(["DATA_SYNC", "DATASET_VERIFY"] as const)(
    "renders a matching %s job and server-authored verification facts",
    async (kind) => {
      const getJob = vi.fn().mockResolvedValue(job(kind));
      const { wrapper } = await mountDataView({
        api: apiWith({ getJob }),
        url: `/backtests/data?jobId=${JOB_ID}`,
      });

      expect(wrapper.get('[data-testid="backtest-job-status"]').attributes("data-status")).toBe(
        "COMPLETED",
      );
      expect(wrapper.text()).toContain(kind === "DATA_SYNC" ? "历史数据同步" : "数据集验证");
      if (kind === "DATASET_VERIFY") {
        const result = wrapper.get('[data-testid="verification-result"]');
        expect(result.text()).toContain("服务端判定：可用于回测");
        expect(result.text()).toContain("9600");
      }
      wrapper.unmount();
    },
  );

  it("renders not-ready verification coverage and blockers without browser inference", async () => {
    const verificationJob = job("DATASET_VERIFY", {
      result: {
        blockers: ["MISSING_MINUTE_BARS"],
        coverage: { ...defaultCoverage, minuteBarCount: 123 },
        datasetHash: null,
        kind: "DATASET_VERIFY",
        ready: false,
      },
    });
    const { wrapper } = await mountDataView({
      api: apiWith({ getJob: vi.fn().mockResolvedValue(verificationJob) }),
      url: `/backtests/data?jobId=${JOB_ID}`,
    });

    const result = wrapper.get('[data-testid="verification-result"]');
    expect(result.text()).toContain("服务端判定：尚不可用于回测");
    expect(result.text()).toContain("123");
    expect(result.text()).toContain("MISSING_MINUTE_BARS");
    wrapper.unmount();
  });

  it("fails closed when jobId is malformed or resolves to a run job", async () => {
    const malformedGetJob = vi.fn();
    const malformed = await mountDataView({
      api: apiWith({ getJob: malformedGetJob }),
      url: "/backtests/data?jobId=%2Fprivate%2Fpath",
    });
    expect(malformedGetJob).not.toHaveBeenCalled();
    expect(malformed.wrapper.get('[data-testid="job-identity-error"]').text()).toContain(
      "任务标识无效",
    );
    malformed.wrapper.unmount();

    const runGetJob = vi.fn().mockResolvedValue(
      job("BACKTEST_RUN", {
        finishedAt: null,
        progress: {
          completedUnits: 1,
          phase: "REPLAYING",
          totalUnits: 2,
          unit: "ITEMS",
          updatedAt: "2026-08-29T10:00:02.000000+08:00",
        },
        result: null,
        status: "RUNNING",
      }),
    );
    const runJob = await mountDataView({
      api: apiWith({ getJob: runGetJob }),
      url: `/backtests/data?jobId=${JOB_ID}`,
    });
    expect(runJob.wrapper.find('[data-testid="backtest-job-status"]').exists()).toBe(false);
    expect(runJob.wrapper.get('[data-testid="job-identity-error"]').text()).toContain(
      "不属于历史数据任务",
    );
    expect(runJob.router.currentRoute.value.query.jobId).toBeUndefined();
    expect(runGetJob).toHaveBeenCalledTimes(1);
    runJob.wrapper.unmount();
  });

  it("changing filters resets paging and preserves the inspected data job", async () => {
    const { router, wrapper } = await mountDataView({ url: `/backtests/data?cursor=cursor.payload&jobId=${JOB_ID}` });
    await wrapper.get('input[placeholder="000001.SZ"]').setValue("600000.SH");
    await wrapper.get("form").trigger("submit"); await flushPromises();
    expect(router.currentRoute.value.query.symbol).toBe("600000.SH");
    expect(router.currentRoute.value.query.cursor).toBeUndefined();
    expect(router.currentRoute.value.query.jobId).toBe(JOB_ID); wrapper.unmount();
  });

  it("removes ambiguous scalar query values and invalid calendar dates without a loop", async () => {
    const { router, wrapper } = await mountDataView({
      url:
        "/backtests/data?symbol=000001.SZ&symbol=600000.SH&startOnOrAfter=2026-02-31" +
        "&symbols=000001.SZ&start=2026-08-01&unknown=discarded",
    });

    expect(router.currentRoute.value.query).toEqual({});
    expect(wrapper.get<HTMLInputElement>('input[placeholder="000001.SZ"]').element.value).toBe("");
    wrapper.unmount();
  });

  it("renders only backend-authored coverage and blocker facts", async () => {
    const coverage = {
      ...defaultCoverage,
      blockers: ["MISSING_MINUTE_BARS", "MISSING_DAILY_LIMITS"],
      minuteBarCount: 123,
      tradingDayCount: 7,
    };
    const { wrapper } = await mountDataView({
      api: apiWith({ listDatasets: vi.fn().mockResolvedValue(page([dataset(DATASET_HASH_A, { coverage })])) }),
    });

    const card = wrapper.get('[data-testid="dataset-card"]');
    expect(card.text()).toContain("123");
    expect(card.text()).toContain("7");
    expect(card.text()).toContain("MISSING_MINUTE_BARS");
    expect(card.text()).toContain("MISSING_DAILY_LIMITS");
    expect(card.text()).toContain("服务端阻断项");
    wrapper.unmount();
  });

  it("moves cursor state through the URL and replaces rather than accumulates pages", async () => {
    const cursor = "cursor.payload";
    const listDatasets = vi
      .fn<BacktestApi["listDatasets"]>()
      .mockResolvedValueOnce(
        page([dataset(DATASET_HASH_A)], { hasMore: true, nextCursor: cursor }),
      )
      .mockResolvedValueOnce(page([dataset(DATASET_HASH_B)]));
    const { router, wrapper } = await mountDataView({ api: apiWith({ listDatasets }) });

    await wrapper.get('[data-testid="next-dataset-page"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.cursor).toBe(cursor);
    expect(listDatasets.mock.calls[1]?.[0]).toEqual({ cursor, limit: 20 });
    expect(wrapper.text()).toContain(DATASET_HASH_B);
    expect(wrapper.text()).not.toContain(DATASET_HASH_A);
    wrapper.unmount();
  });

  it("shows bounded loading, empty, and fixed-copy failure states", async () => {
    const pending = deferred<BacktestDatasetPage>();
    const loading = await mountDataView({
      api: apiWith({ listDatasets: vi.fn().mockReturnValue(pending.promise) }),
    });
    expect(loading.wrapper.get('[data-testid="dataset-loading"]').attributes("aria-busy")).toBe(
      "true",
    );
    pending.resolve(page([]));
    await flushPromises();
    expect(loading.wrapper.get('[data-testid="dataset-empty"]').text()).toContain("尚无已验证数据集");
    loading.wrapper.unmount();

    const failed = await mountDataView({
      api: apiWith({
        listDatasets: vi.fn().mockRejectedValue(new Error("private database path")),
      }),
    });
    expect(failed.wrapper.get('[role="alert"]').text()).toContain("数据集列表暂不可用");
    expect(failed.wrapper.text()).not.toContain("private database path");
    failed.wrapper.unmount();
  });
});
