import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BacktestRunView } from "../../src/api/generated";
import type { BacktestApi } from "../../src/api/backtests";
import { ApiClientError } from "../../src/api/transport";
import BacktestMetricsSummary from "../../src/components/backtests/BacktestMetricsSummary.vue";
import BacktestResultActions from "../../src/components/backtests/BacktestResultActions.vue";
import BacktestRunDetailView from "../../src/views/BacktestRunDetailView.vue";

const RUN_ID = "a".repeat(64);
const COMPLETED_AT = "2026-08-29T12:00:00.000000+08:00";

const LIMITATIONS = [
  "BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR",
  "CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE",
  "DAILY_EQUITY_DRAWDOWN_SAMPLING",
  "FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME",
  "HISTORICAL_MINUTES_DO_NOT_VERIFY_REALTIME",
  "METRIC_DECIMAL_PRECISION_28_HALF_EVEN",
  "SIMULATED_EXECUTION_NO_BROKER",
  "UNADJUSTED_PRICES_NO_CORPORATE_ACTIONS",
  "WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP",
  "ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY",
] as const;

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
      equitySeries: "EXPIRED",
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
    limitations: [...LIMITATIONS],
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
    revision: 2,
    runId: RUN_ID,
    status: "COMPLETED",
    symbol: "000001.SZ",
    ...overrides,
  };
}

function mutation(body: BacktestRunView) {
  return Object.freeze({
    body,
    location: null,
    retryAfterSeconds: null,
    status: 200 as const,
  });
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

function mountActions(options: {
  api: BacktestApi;
  createIdempotencyKey?: () => string;
  run?: BacktestRunView;
}) {
  return mount(BacktestResultActions, {
    props: {
      api: options.api,
      ...(options.createIdempotencyKey === undefined
        ? {}
        : { createIdempotencyKey: options.createIdempotencyKey }),
      run: options.run ?? run(),
    },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("BacktestResultActions", () => {
  it("binds a pin intent to the current revision and refreshes after success", async () => {
    const pinned = run({ pinned: true, revision: 3 });
    const pinRun = vi.fn(() => Promise.resolve(mutation(pinned)));
    const createIdempotencyKey = vi.fn(() => "pin-run-revision-2");
    const wrapper = mountActions({ api: apiWith({ pinRun }), createIdempotencyKey });

    await wrapper.get("[data-testid='toggle-run-pin']").trigger("click");
    await flushPromises();

    expect(pinRun).toHaveBeenCalledWith(
      RUN_ID,
      { expectedRevision: 2, pinned: true },
      "pin-run-revision-2",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(createIdempotencyKey).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted("refresh")).toHaveLength(1);
    expect(wrapper.find("[data-testid='toggle-run-pin']").exists()).toBe(false);
    expect(wrapper.get("[role='status']").text()).toContain("正在刷新服务端权威状态");
  });

  it("replays an uncertain pin with the same body and idempotency key", async () => {
    const pinRun = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiClientError({
          code: "NETWORK_ERROR",
          message: "private network detail",
          status: 0,
        }),
      )
      .mockResolvedValueOnce(mutation(run({ pinned: true, revision: 3 })));
    const createIdempotencyKey = vi.fn(() => "stable-pin-intent");
    const wrapper = mountActions({ api: apiWith({ pinRun }), createIdempotencyKey });

    await wrapper.get("[data-testid='toggle-run-pin']").trigger("click");
    await flushPromises();

    expect(wrapper.find("[data-testid='toggle-run-pin']").exists()).toBe(false);
    expect(wrapper.get("[data-testid='retry-run-pin']").text()).toContain("安全重试同一请求");
    expect(wrapper.text()).not.toContain("private network detail");

    await wrapper.get("[data-testid='retry-run-pin']").trigger("click");
    await flushPromises();

    expect(pinRun).toHaveBeenCalledTimes(2);
    expect(pinRun.mock.calls[0]?.slice(0, 3)).toEqual(pinRun.mock.calls[1]?.slice(0, 3));
    expect(createIdempotencyKey).toHaveBeenCalledTimes(1);
  });

  it("does not carry an idempotency key across a revision or opposite semantic intent", async () => {
    const pinRun = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiClientError({ code: "CONFLICT", message: "private conflict", status: 409 }),
      )
      .mockResolvedValueOnce(mutation(run({ pinned: false, revision: 4 })));
    const keys = ["pin-at-revision-2", "unpin-at-revision-3"];
    const createIdempotencyKey = vi.fn(() => keys.shift() ?? "unexpected-key");
    const wrapper = mountActions({ api: apiWith({ pinRun }), createIdempotencyKey });

    await wrapper.get("[data-testid='toggle-run-pin']").trigger("click");
    await flushPromises();

    expect(wrapper.emitted("refresh")).toHaveLength(1);
    expect(wrapper.text()).not.toContain("private conflict");
    expect(wrapper.find("[data-testid='toggle-run-pin']").exists()).toBe(false);

    await wrapper.setProps({ run: run({ pinned: true, revision: 3 }) });
    await wrapper.get("[data-testid='toggle-run-pin']").trigger("click");
    await flushPromises();

    expect(pinRun.mock.calls[0]?.slice(0, 3)).toEqual([
      RUN_ID,
      { expectedRevision: 2, pinned: true },
      "pin-at-revision-2",
    ]);
    expect(pinRun.mock.calls[1]?.slice(0, 3)).toEqual([
      RUN_ID,
      { expectedRevision: 3, pinned: false },
      "unpin-at-revision-3",
    ]);
    expect(createIdempotencyKey).toHaveBeenCalledTimes(2);
  });

  it("renders only same-origin allowlisted native export anchors", () => {
    const fetchSpy = vi.fn();
    const blobSpy = vi.fn();
    const pickerSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("Blob", blobSpy);
    vi.stubGlobal("showSaveFilePicker", pickerSpy);

    const wrapper = mountActions({ api: apiWith() });
    const summary = wrapper.get("[data-testid='export-summary-json']");
    const fills = wrapper.get("[data-testid='export-fills-csv']");

    expect(summary.element.tagName).toBe("A");
    expect(summary.attributes("href")).toBe(
      `/api/v1/backtest-runs/${RUN_ID}/exports/SUMMARY_JSON`,
    );
    expect(fills.element.tagName).toBe("A");
    expect(fills.attributes("href")).toBe(
      `/api/v1/backtest-runs/${RUN_ID}/exports/FILLS_CSV`,
    );
    expect(wrapper.find("input").exists()).toBe(false);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(blobSpy).not.toHaveBeenCalled();
    expect(pickerSpy).not.toHaveBeenCalled();
  });
});

describe("BacktestMetricsSummary", () => {
  it("renders every exact metric, cost, assumption, formula, availability, and limitation in text", () => {
    const wrapper = mount(BacktestMetricsSummary, { props: { run: run() } });
    const text = wrapper.text();

    expect(text).toContain("总交易成本（元）1.23");
    expect(text).toContain("成交额（元）1000.00");
    expect(text).toContain("盈利卖出成交数2");
    expect(text).toContain("总收益率 =（最终权益 − 初始权益）÷ 初始权益");
    expect(text).toContain("最大回撤 = 每日权益点相对此前峰值的最大跌幅");
    expect(text).toContain("胜率 = 已实现盈利的卖出成交数 ÷ 全部卖出成交数");
    expect(text).toContain("NO_EVENT_RISK");
    expect(text).toContain("TUSHARE_STK_MINS_241_END_V1");
    expect(text).toContain("NONE（未复权）");
    expect(text).toContain("佣金率0.03%");
    expect(text).toContain("最低佣金5.00 元/笔");
    expect(text).toContain("买入滑点0.0125%（价格比例）");
    expect(text).toContain("backtest-execution-v1");
    expect(text).toContain("backtest-metrics-v1");
    expect(text).toContain("backtest-report-summary-v2");
    expect(text).toContain("backtest-run-v2");
    expect(text).toContain("权益序列明细已过保留期");
    expect(text).toContain("信号明细运行时未记录");
    for (const limitation of LIMITATIONS) expect(text).toContain(limitation);
    expect(text).toContain("不支持公司行动建模");
    expect(text).toContain("模拟成交（仅供研究）");
    expect(text).toContain("历史分钟数据不能验证实时行情接口");
  });
});

describe("BacktestRunDetailView pin reconciliation", () => {
  it("refreshes the authoritative summary after a pin conflict", async () => {
    const getRun = vi
      .fn()
      .mockResolvedValueOnce(run())
      .mockResolvedValueOnce(run({ pinned: true, revision: 3 }));
    const pinRun = vi.fn(() =>
      Promise.reject(
        new ApiClientError({ code: "CONFLICT", message: "private conflict", status: 409 }),
      ),
    );
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/backtests/:runId", component: { template: "<div />" } }],
    });
    await router.push(`/backtests/${RUN_ID}?tab=summary`);
    await router.isReady();
    const wrapper: VueWrapper = mount(BacktestRunDetailView, {
      attachTo: document.body,
      global: { plugins: [router] },
      props: {
        api: apiWith({ getRun, pinRun }),
        createIdempotencyKey: () => "conflicting-pin-intent",
      },
    });
    await flushPromises();

    await wrapper.get("[data-testid='toggle-run-pin']").trigger("click");
    await flushPromises();

    expect(getRun).toHaveBeenCalledTimes(2);
    expect(wrapper.get("[data-testid='toggle-run-pin']").text()).toContain("取消保留");
    expect(wrapper.text()).not.toContain("private conflict");
    wrapper.unmount();
  });
});
