import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  BacktestJobView,
  BacktestMarketIndexSeriesView,
  BacktestRunView,
} from "../../src/api/generated";
import type { BacktestApi } from "../../src/api/backtests";
import BacktestRunDetailView from "../../src/views/BacktestRunDetailView.vue";

const RUN_ID = "a".repeat(64);
const OTHER_RUN_ID = "b".repeat(64);
const JOB_ID = "run-job-001";
const COMPLETED_AT = "2026-08-29T12:00:00.000000+08:00";

function run(overrides: Partial<BacktestRunView> = {}): BacktestRunView {
  return {
    assumptions: {
      eventRiskAssumption: "NO_EVENT_RISK",
      executionConfig: {
        buySlippageBps: "1.25",
        commissionRate: "0.0003",
        minimumCommissionFen: "500",
        sellSlippageBps: "1.75",
        stampDutyRate: "0.001",
        transferFeeRate: "0.00001",
      },
      executionConfigHash: "c".repeat(64),
      historicalProfile: "TUSHARE_STK_MINS_241_END_V1",
      priceAdjustmentPolicy: "NONE",
    },
    availability: {
      decisionDetails: "AVAILABLE",
      equitySeries: "AVAILABLE",
      executionOutcomeDetails: "EXPIRED",
      signalDetails: "NOT_RECORDED",
    },
    completedAt: COMPLETED_AT,
    coverage: {
      decisionCount: 8,
      equityPointCount: 20,
      eventEnd: "2026-08-28",
      eventStart: "2026-08-01",
      fillCount: 3,
      orderCount: 4,
      outcomeCount: 4,
      signalCount: 4,
      tradingDayCount: 20,
    },
    datasetHash: "d".repeat(64),
    eventEnd: "2026-08-28",
    eventStart: "2026-08-01",
    fillCount: 3,
    formulaVersions: {
      executionFormulaVersion: "backtest-execution-v1",
      metricFormulaVersion: "backtest-metrics-v1",
      reportSchemaVersion: "backtest-report-summary-v2",
      runFormulaVersion: "backtest-run-v2",
    },
    initialCashFen: "9007199254740993123",
    limitations: ["HISTORICAL_SIMULATION", "NO_MARKET_IMPACT"],
    metrics: {
      blockedCount: 1,
      finalCashFen: "9007199254740993000",
      finalEquityFen: "9007199254740993999",
      initialCashFen: "9007199254740993123",
      initialEquityFen: "9007199254740993123",
      maximumDrawdown: "0.01234567890123456789",
      realizedPnlFen: "876",
      skippedCount: 2,
      totalCostFen: "123",
      totalReturn: "0.1234567890123456789012345678",
      tradeCount: 3,
      turnoverFen: "100000",
      unrealizedPnlFen: "0",
      winRate: "0.6666666666666666666666666667",
      winningSellCount: 2,
    },
    pinned: false,
    planHash: "e".repeat(64),
    planVersionId: "123e4567-e89b-42d3-a456-426614174000",
    reportHash: "f".repeat(64),
    revision: 0,
    runId: RUN_ID,
    status: "COMPLETED",
    symbol: "000001.SZ",
    ...overrides,
  };
}

function job(
  status: BacktestJobView["status"],
  overrides: Partial<BacktestJobView> = {},
): BacktestJobView {
  const terminal = status === "COMPLETED" || status === "FAILED" || status === "CANCELLED";
  return {
    attempt: status === "QUEUED" ? 0 : 1,
    cancelRequestedAt:
      status === "CANCEL_REQUESTED" || status === "CANCELLED" ? COMPLETED_AT : null,
    createdAt: COMPLETED_AT,
    datasetHash: "d".repeat(64),
    errorCode: status === "FAILED" ? "RUN_FAILED_SAFE" : status === "CANCELLED" ? "RUN_CANCELLED_SAFE" : null,
    errorMessage:
      status === "FAILED"
        ? "The job failed."
        : status === "CANCELLED"
          ? "The job was cancelled."
          : null,
    finishedAt: terminal ? COMPLETED_AT : null,
    jobId: JOB_ID,
    kind: "BACKTEST_RUN",
    progress: {
      completedUnits: terminal ? 20 : 5,
      phase: terminal ? "TERMINAL" : "REPLAYING",
      totalUnits: 20,
      unit: "EVENTS",
      updatedAt: COMPLETED_AT,
    },
    requestHash: "1".repeat(64),
    result:
      status === "COMPLETED"
        ? { kind: "BACKTEST_RUN", reportHash: "f".repeat(64), reused: false, runId: RUN_ID }
        : null,
    reused: false,
    revision: 1,
    runId: RUN_ID,
    startedAt: status === "QUEUED" ? null : COMPLETED_AT,
    status,
    updatedAt: COMPLETED_AT,
    ...overrides,
  };
}

function apiWith(overrides: Partial<BacktestApi> = {}): BacktestApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected API call")));
  return {
    cancelJob: unused,
    getDataset: unused,
    getEquitySeries: unused,
    getMarketIndexSeries: unused,
    getReferenceMarketCoverage: unused,
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

function marketIndexSeries(): BacktestMarketIndexSeriesView {
  const summary = {
    applicableBranchCount: 2,
    conditionType: "INDEX_CLOSE_GTE_MA" as const,
    formulaId: "SMA" as const,
    missingCount: 0,
    parameters: { period: 20 },
    planPath: "entry.conditions.all[0]",
    satisfiedCount: 1,
    unsatisfiedCount: 1,
  };
  return {
    conditionSummaries: [summary],
    healthTimeline: [
      { dataAt: COMPLETED_AT, health: "LIVE", issues: [] },
    ],
    items: [
      {
        closePoints: "10000.5",
        dataAt: COMPLETED_AT,
        health: "LIVE",
        indicatorFacts: [],
        issues: [],
        snapshotHash: "2".repeat(64),
        tradeDate: "2026-08-29",
      },
    ],
    referenceMarket: {
      binding: {
        board: "SZSE_MAIN",
        displayName: "深证成指",
        indexCode: "399001.SZ",
        mappingVersion: "board-index-map-v1",
        selection: "AUTO_BOARD",
      },
      blockers: [],
      conditionPaths: ["entry.conditions.all[0]"],
      conditionSummaries: [summary],
      coverageStatus: "AVAILABLE",
      datasetHash: "d".repeat(64),
      formulaDefinitionHash: "3".repeat(64),
      indexRequirementHash: "4".repeat(64),
      marketIndexDataHash: "5".repeat(64),
      required: true,
      warmupStart: "2026-07-01",
    },
    runId: RUN_ID,
  };
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

async function mountDetail(options: {
  api?: BacktestApi;
  blockCompletedCanonicalization?: boolean;
  url?: string;
} = {}): Promise<{ router: Router; wrapper: VueWrapper }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/backtests/:runId", component: { template: "<div />" } }],
  });
  await router.push(options.url ?? `/backtests/${RUN_ID}`);
  await router.isReady();
  if (options.blockCompletedCanonicalization) {
    router.beforeEach((to, from) =>
      from.query.jobId !== undefined && to.query.jobId === undefined ? false : undefined,
    );
  }
  const wrapper = mount(BacktestRunDetailView, {
    attachTo: document.body,
    global: { plugins: [router] },
    props: { api: options.api ?? apiWith() },
  });
  await flushPromises();
  return { router, wrapper };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("BacktestRunDetailView", () => {
  it("loads the reference-index resource only for its URL tab and navigates a date to decisions", async () => {
    const getRun = vi.fn<BacktestApi["getRun"]>().mockResolvedValue(run());
    const getMarketIndexSeries = vi
      .fn<BacktestApi["getMarketIndexSeries"]>()
      .mockResolvedValue(marketIndexSeries());
    const { router, wrapper } = await mountDetail({
      api: apiWith({ getMarketIndexSeries, getRun }),
      url: `/backtests/${RUN_ID}?tab=market-index`,
    });

    expect(wrapper.get('[data-testid="result-tab-market-index"]').attributes("aria-current")).toBe("page");
    expect(getMarketIndexSeries).toHaveBeenCalledWith(
      RUN_ID,
      { limit: 512 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.text()).toContain("共用指数数据");
    expect(wrapper.text()).toContain("计划指数条件结果");

    await wrapper.get('button[data-trade-date="2026-08-29"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ kind: "DECISION", tab: "details" });
    wrapper.unmount();
  });

  it("loads only the materialized summary for a no-job deep link and renders exact facts", async () => {
    const getRun = vi.fn<BacktestApi["getRun"]>().mockResolvedValue(run());
    const getJob = vi.fn<BacktestApi["getJob"]>();
    const { wrapper } = await mountDetail({ api: apiWith({ getJob, getRun }) });

    expect(getRun).toHaveBeenCalledWith(RUN_ID, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(getJob).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("90071992547409939.99");
    expect(wrapper.text()).toContain("0.1234567890123456789012345678");
    expect(wrapper.get("time").attributes("datetime")).toBe(COMPLETED_AT);
    wrapper.unmount();
  });

  it.each([
    [`/backtests/not-a-run`, "运行标识无效"],
    [`/backtests/${RUN_ID}?jobId=%2Fprivate%2Fjob`, "任务标识无效"],
  ])("fails closed for malformed route identity %s", async (url, expectedCopy) => {
    const getRun = vi.fn<BacktestApi["getRun"]>();
    const getJob = vi.fn<BacktestApi["getJob"]>();
    const { wrapper } = await mountDetail({ api: apiWith({ getJob, getRun }), url });

    expect(wrapper.get('[data-testid="run-identity-error"]').text()).toContain(expectedCopy);
    expect(wrapper.text()).not.toContain("private");
    expect(wrapper.get('[data-testid="back-to-run-history"]').attributes("href")).toBe("/backtests");
    expect(getRun).not.toHaveBeenCalled();
    expect(getJob).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("rejects a repeated jobId query without reading either identity", async () => {
    const getRun = vi.fn<BacktestApi["getRun"]>();
    const getJob = vi.fn<BacktestApi["getJob"]>();
    const { wrapper } = await mountDetail({
      api: apiWith({ getJob, getRun }),
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}&jobId=second-job`,
    });

    expect(wrapper.get('[data-testid="run-identity-error"]').text()).toContain(
      "任务标识无效",
    );
    expect(getRun).not.toHaveBeenCalled();
    expect(getJob).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("stops polling immediately after an exact job identity mismatch", async () => {
    vi.useFakeTimers();
    const getJob = vi
      .fn<BacktestApi["getJob"]>()
      .mockResolvedValue(job("RUNNING", { runId: OTHER_RUN_ID }));
    const { wrapper } = await mountDetail({
      api: apiWith({ getJob }),
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}`,
    });

    expect(getJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2_000);
    await flushPromises();
    expect(getJob).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("shows a matching active run job without reading an unmaterialized result", async () => {
    const getJob = vi.fn<BacktestApi["getJob"]>().mockResolvedValue(job("RUNNING"));
    const getRun = vi.fn<BacktestApi["getRun"]>();
    const { router, wrapper } = await mountDetail({
      api: apiWith({ getJob, getRun }),
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}`,
    });

    expect(wrapper.get('[data-testid="backtest-job-status"]').attributes("data-status")).toBe("RUNNING");
    expect(getRun).not.toHaveBeenCalled();
    expect(router.currentRoute.value.query.jobId).toBe(JOB_ID);
    wrapper.unmount();
  });

  it.each([
    job("RUNNING", { runId: OTHER_RUN_ID }),
    job("RUNNING", { kind: "DATA_SYNC", runId: null }),
  ])("rejects a job that does not belong to the exact run", async (wrongJob) => {
    const getRun = vi.fn<BacktestApi["getRun"]>();
    const { wrapper } = await mountDetail({
      api: apiWith({ getJob: vi.fn().mockResolvedValue(wrongJob), getRun }),
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}`,
    });

    expect(wrapper.get('[data-testid="run-identity-error"]').text()).toContain("任务与运行标识不匹配");
    expect(wrapper.find('[data-testid="backtest-job-status"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("服务端安全失败诊断");
    expect(getRun).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("canonicalizes a matching completed job before loading its materialized summary", async () => {
    const getJob = vi.fn<BacktestApi["getJob"]>().mockResolvedValue(job("COMPLETED"));
    const getRun = vi.fn<BacktestApi["getRun"]>().mockResolvedValue(run());
    const { router, wrapper } = await mountDetail({
      api: apiWith({ getJob, getRun }),
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}`,
    });

    expect(router.currentRoute.value.query.jobId).toBeUndefined();
    expect(getRun).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="backtest-metrics-summary"]').text()).toContain("000001.SZ");
    wrapper.unmount();
  });

  it("keeps one completed-job announcement across canonicalization without stealing focus", async () => {
    vi.useFakeTimers();
    const getJob = vi
      .fn<BacktestApi["getJob"]>()
      .mockResolvedValueOnce(job("RUNNING"))
      .mockResolvedValueOnce(job("COMPLETED"));
    const focusTarget = document.createElement("button");
    focusTarget.textContent = "Stable focus target";
    document.body.append(focusTarget);
    const { router, wrapper } = await mountDetail({
      api: apiWith({ getJob, getRun: vi.fn().mockResolvedValue(run()) }),
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}`,
    });
    focusTarget.focus();

    await vi.advanceTimersByTimeAsync(2_000);
    await flushPromises();

    expect(router.currentRoute.value.query.jobId).toBeUndefined();
    const announcement = wrapper.get('[data-testid="completed-job-announcement"]');
    expect(announcement.attributes()).toMatchObject({
      "aria-atomic": "true",
      "aria-live": "polite",
      role: "status",
    });
    expect(announcement.text()).toBe("任务已完成，已打开回测结果");
    expect(document.activeElement).toBe(focusTarget);

    await vi.advanceTimersByTimeAsync(2_200);
    await flushPromises();
    expect(getJob).toHaveBeenCalledTimes(2);
    expect(announcement.text()).toBe("任务已完成，已打开回测结果");
    expect(document.activeElement).toBe(focusTarget);
    wrapper.unmount();
    focusTarget.remove();
  });

  it("removes only jobId when canonicalizing a completed job", async () => {
    const { router, wrapper } = await mountDetail({
      api: apiWith({
        getJob: vi.fn().mockResolvedValue(job("COMPLETED")),
        getRun: vi.fn().mockResolvedValue(run()),
      }),
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}&tab=summary&source=history`,
    });

    expect(router.currentRoute.value.query).toEqual({
      source: "history",
      tab: "summary",
    });
    wrapper.unmount();
  });

  it.each(["FAILED", "CANCELLED"] as const)(
    "keeps a matching %s job as job-only diagnostics",
    async (status) => {
      const getRun = vi.fn<BacktestApi["getRun"]>();
      const { router, wrapper } = await mountDetail({
        api: apiWith({ getJob: vi.fn().mockResolvedValue(job(status)), getRun }),
        url: `/backtests/${RUN_ID}?jobId=${JOB_ID}`,
      });

      expect(router.currentRoute.value.query.jobId).toBe(JOB_ID);
      expect(wrapper.get('[data-testid="job-diagnostic"]').text()).toContain(
        status === "FAILED" ? "RUN_FAILED_SAFE" : "RUN_CANCELLED_SAFE",
      );
      expect(wrapper.find('[data-testid="backtest-metrics-summary"]').exists()).toBe(false);
      expect(getRun).not.toHaveBeenCalled();
      wrapper.unmount();
    },
  );

  it("rechecks a terminal job when the route switches to another run", async () => {
    const getJob = vi.fn<BacktestApi["getJob"]>().mockResolvedValue(job("FAILED"));
    const getRun = vi.fn<BacktestApi["getRun"]>();
    const { router, wrapper } = await mountDetail({
      api: apiWith({ getJob, getRun }),
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}`,
    });
    expect(wrapper.get('[data-testid="job-diagnostic"]').text()).toContain(
      "RUN_FAILED_SAFE",
    );

    await router.push(`/backtests/${OTHER_RUN_ID}?jobId=${JOB_ID}`);
    await flushPromises();

    expect(wrapper.get('[data-testid="run-identity-error"]').text()).toContain(
      "任务与运行标识不匹配",
    );
    expect(wrapper.find('[data-testid="backtest-job-status"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("RUN_FAILED_SAFE");
    expect(getRun).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("aborts a stale summary request when the run route changes", async () => {
    const stale = deferred<BacktestRunView>();
    const signals: AbortSignal[] = [];
    const getRun = vi.fn<BacktestApi["getRun"]>().mockImplementation((runId, options) => {
      if (options?.signal !== undefined) signals.push(options.signal);
      return runId === RUN_ID ? stale.promise : Promise.resolve(run({ runId: OTHER_RUN_ID, symbol: "600000.SH" }));
    });
    const { router, wrapper } = await mountDetail({ api: apiWith({ getRun }) });

    await router.push(`/backtests/${OTHER_RUN_ID}`);
    await flushPromises();
    expect(signals[0]?.aborted).toBe(true);
    expect(wrapper.text()).toContain("600000.SH");
    stale.resolve(run({ symbol: "000001.SZ" }));
    await flushPromises();
    expect(wrapper.text()).not.toContain("000001.SZ");
    wrapper.unmount();
  });

  it("aborts the active summary request on unmount", async () => {
    const pending = deferred<BacktestRunView>();
    let signal: AbortSignal | undefined;
    const getRun = vi.fn<BacktestApi["getRun"]>((_runId, options) => {
      signal = options?.signal;
      return pending.promise;
    });
    const { wrapper } = await mountDetail({ api: apiWith({ getRun }) });

    expect(signal?.aborted).toBe(false);
    wrapper.unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("rejects a summary response for a different run identity", async () => {
    const { wrapper } = await mountDetail({
      api: apiWith({
        getRun: vi.fn().mockResolvedValue(run({ runId: OTHER_RUN_ID })),
      }),
    });

    expect(wrapper.get('[role="alert"]').text()).toContain("回测结果暂不可用");
    expect(wrapper.text()).not.toContain(OTHER_RUN_ID);
    wrapper.unmount();
  });

  it("uses fixed copy for summary failure and can retry the same run", async () => {
    const getRun = vi
      .fn<BacktestApi["getRun"]>()
      .mockRejectedValueOnce(new Error("private database path"))
      .mockResolvedValueOnce(run());
    const { wrapper } = await mountDetail({ api: apiWith({ getRun }) });

    expect(wrapper.get('[role="alert"]').text()).toContain("回测结果暂不可用");
    expect(wrapper.text()).not.toContain("private database path");
    await wrapper.get('[data-testid="refresh-run-summary"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="backtest-metrics-summary"]').text()).toContain("000001.SZ");
    wrapper.unmount();
  });

  it("fails closed when completed-job canonical navigation is cancelled", async () => {
    const getRun = vi.fn<BacktestApi["getRun"]>();
    const { router, wrapper } = await mountDetail({
      api: apiWith({ getJob: vi.fn().mockResolvedValue(job("COMPLETED")), getRun }),
      blockCompletedCanonicalization: true,
      url: `/backtests/${RUN_ID}?jobId=${JOB_ID}`,
    });

    expect(router.currentRoute.value.query.jobId).toBe(JOB_ID);
    expect(wrapper.get('[data-testid="run-identity-error"]').text()).toContain("无法切换到已完成结果");
    expect(getRun).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
