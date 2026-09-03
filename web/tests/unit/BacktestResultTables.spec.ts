import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import type {
  BacktestDecisionView,
  BacktestDetailPage,
  BacktestExecutionOutcomeView,
  BacktestFillPage,
  BacktestFillView,
  BacktestRunView,
  BacktestSignalView,
} from "../../src/api/generated";
import type { BacktestApi } from "../../src/api/backtests";
import BacktestDetailTable from "../../src/components/backtests/BacktestDetailTable.vue";
import BacktestFillTable from "../../src/components/backtests/BacktestFillTable.vue";
import BacktestRunDetailView from "../../src/views/BacktestRunDetailView.vue";

const RUN_ID = "a".repeat(64);
const CURSOR = "page.next_001";
const TIME = "2026-08-29T12:00:00.000000+08:00";

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
      executionConfigHash: "b".repeat(64),
      historicalProfile: "TUSHARE_STK_MINS_241_END_V1",
      priceAdjustmentPolicy: "NONE",
    },
    availability: {
      decisionDetails: "AVAILABLE",
      equitySeries: "AVAILABLE",
      executionOutcomeDetails: "AVAILABLE",
      signalDetails: "AVAILABLE",
    },
    completedAt: TIME,
    coverage: {
      decisionCount: 1,
      equityPointCount: 1,
      eventEnd: "2026-08-29",
      eventStart: "2026-08-28",
      fillCount: 1,
      orderCount: 1,
      outcomeCount: 1,
      signalCount: 1,
      tradingDayCount: 2,
    },
    datasetHash: "c".repeat(64),
    eventEnd: "2026-08-29",
    eventStart: "2026-08-28",
    fillCount: 1,
    formulaVersions: {
      executionFormulaVersion: "execution-v1",
      metricFormulaVersion: "metrics-v1",
      reportSchemaVersion: "report-v2",
      runFormulaVersion: "run-v2",
    },
    initialCashFen: "9007199254740993123",
    limitations: ["HISTORICAL_SIMULATION"],
    metrics: {
      blockedCount: 0,
      finalCashFen: "9007199254740993000",
      finalEquityFen: "9007199254740993999",
      initialCashFen: "9007199254740993123",
      initialEquityFen: "9007199254740993123",
      maximumDrawdown: "0.01",
      realizedPnlFen: "876",
      skippedCount: 0,
      totalCostFen: "123",
      totalReturn: "0.1",
      tradeCount: 1,
      turnoverFen: "1000",
      unrealizedPnlFen: "0",
      winRate: "1",
      winningSellCount: 1,
    },
    pinned: false,
    planHash: "d".repeat(64),
    planVersionId: "123e4567-e89b-42d3-a456-426614174000",
    reportHash: "e".repeat(64),
    revision: 0,
    runId: RUN_ID,
    status: "COMPLETED",
    symbol: "000001.SZ",
    ...overrides,
  };
}

function fill(index = 1): BacktestFillView {
  const id = index.toString().padStart(3, "0");
  return {
    bucket: "CORE",
    cashDeltaFen: "-9007199254740993123",
    configHash: "b".repeat(64),
    costBasisReleasedFen: "0",
    datasetHash: "c".repeat(64),
    fees: {
      commissionFen: "5",
      stampDutyFen: "0",
      totalFen: "10",
      transferFeeFen: "5",
    },
    fillId: `fill-${id}`,
    filledAt: TIME,
    notionalFen: "9007199254740993113",
    orderId: `order-${id}`,
    planHash: "d".repeat(64),
    priceFen: "9007199254740993123",
    quantity: 100,
    realizedPnlFen: null,
    requestedQuantity: 100,
    resultHash: "f".repeat(64),
    runId: RUN_ID,
    side: "BUY",
    signalId: `signal-${id}`,
    sourceBarId: `bar-${id}`,
    symbol: "000001.SZ",
    targetLotId: null,
  };
}

function fillPage(overrides: Partial<BacktestFillPage> = {}): BacktestFillPage {
  return {
    filters: {},
    hasMore: false,
    highWatermark: CURSOR,
    items: [fill()],
    limit: 100,
    nextCursor: null,
    ...overrides,
  };
}

function signalDetail(index = 1): BacktestSignalView {
  const id = index.toString().padStart(3, "0");
  return {
    bucket: "CORE",
    causeId: `decision-${id}`,
    detailId: `detail-signal-${id}`,
    eventAt: TIME,
    kind: "SIGNAL",
    quantity: 100,
    resultHash: "f".repeat(64),
    runId: RUN_ID,
    signalId: `signal-${id}`,
    signalType: "BUY_CORE_READY",
    symbol: "000001.SZ",
    targetLotId: null,
  };
}

function decisionDetail(): BacktestDecisionView {
  return {
    decision: {
      dataAgeSeconds: 0,
      dataHealth: {
        dataAgeSeconds: 0,
        fresh: true,
        latestBarEnd: TIME,
        requiredDataComplete: true,
        status: "LIVE",
      },
      episodeLowFen: null,
      episodeStatus: null,
      evaluatedAt: TIME,
      evidence: [],
      marketDataAt: TIME,
      nextStep: { code: "WAIT_FOR_COMPLETE_BAR", notBefore: null, requiredInputs: [] },
      planHash: "d".repeat(64),
      planId: "plan-001",
      planVersion: 1,
      position: {
        coreQuantity: 0,
        sellableCoreQuantity: 0,
        sellableTacticalQuantity: 0,
        tacticalQuantity: 0,
        totalQuantity: 0,
      },
      priceFen: "9007199254740993123",
      resultHash: "f".repeat(64),
      riskBreachTradeDate: null,
      riskStatus: "CLEAR",
      signalType: "WAIT",
      symbol: "000001.SZ",
      zone: "OBSERVATION",
    },
    detailId: "detail-decision-001",
    eventAt: TIME,
    kind: "DECISION",
    resultHash: "f".repeat(64),
    runId: RUN_ID,
  };
}

function outcomeDetail(): BacktestExecutionOutcomeView {
  return {
    detailId: "detail-outcome-001",
    eventAt: TIME,
    fillId: null,
    kind: "EXECUTION_OUTCOME",
    orderId: "order-001",
    outcomeId: "outcome-001",
    reason: "T_PLUS_ONE",
    runId: RUN_ID,
    signalId: "signal-001",
    sourceBarId: "bar-001",
    status: "UNFILLED",
  };
}

function detailPage(
  kind: BacktestDetailPage["kind"] = "SIGNAL",
  overrides: Partial<BacktestDetailPage> = {},
): BacktestDetailPage {
  const items =
    kind === "DECISION"
      ? [decisionDetail()]
      : kind === "EXECUTION_OUTCOME"
        ? [outcomeDetail()]
        : [signalDetail()];
  return {
    availability: "AVAILABLE",
    filters: { kind },
    hasMore: false,
    highWatermark: CURSOR,
    items,
    kind,
    limit: 100,
    nextCursor: null,
    ...overrides,
  };
}

function apiWith(overrides: Partial<BacktestApi> = {}): BacktestApi {
  const unused = vi.fn(() => Promise.reject(new Error("unexpected API call")));
  return {
    cancelJob: unused,
    getDataset: unused,
    getEquitySeries: unused,
    getJob: unused,
    getRun: vi.fn().mockResolvedValue(run()),
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
  const promise = new Promise<Value>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

async function mountDetail(
  api: BacktestApi,
  query: Record<string, string | string[]> = {},
): Promise<{ router: Router; wrapper: VueWrapper }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/backtests/:runId", component: { template: "<div />" } }],
  });
  await router.push({ path: `/backtests/${RUN_ID}`, query });
  await router.isReady();
  const wrapper = mount(BacktestRunDetailView, {
    attachTo: document.body,
    global: { plugins: [router] },
    props: { api },
  });
  await flushPromises();
  return { router, wrapper };
}

describe("backtest result tables", () => {
  it("renders exact FenText and caps a fill page at 100 research-labelled rows", () => {
    const wrapper = mount(BacktestFillTable, {
      props: { items: Array.from({ length: 101 }, (_item, index) => fill(index + 1)) },
    });

    const rows = wrapper.findAll('[data-testid="backtest-fill-row"]');
    expect(rows).toHaveLength(100);
    expect(rows[0]?.text()).toContain("90071992547409931.23");
    expect(rows.every((row) => row.text().includes("模拟成交（仅供研究）"))).toBe(true);
    expect(wrapper.get("time").attributes("datetime")).toBe(TIME);
  });

  it.each([
    ["DECISION", decisionDetail(), "90071992547409931.23"],
    ["SIGNAL", signalDetail(), "BUY_CORE_READY"],
    ["EXECUTION_OUTCOME", outcomeDetail(), "T_PLUS_ONE"],
  ] as const)("renders the closed %s detail discriminator", (kind, item, copy) => {
    const wrapper = mount(BacktestDetailTable, { props: { items: [item], kind } });

    expect(wrapper.get('[data-testid="backtest-detail-row"]').text()).toContain(copy);
    expect(wrapper.get("time").attributes("datetime")).toBe(TIME);
  });

  it("renders the persisted decision-time index identity and exact plan-path evidence", () => {
    const item = decisionDetail();
    item.decision.referenceMarket = {
      dataAt: TIME,
      evidence: [
        {
          actualValue: "10000.5",
          comparisonValue: "9999.5",
          conditionType: "INDEX_CLOSE_GTE_MA",
          dataCutoff: TIME,
          decisionCutoff: TIME,
          formulaDefinitionHash: "1".repeat(64),
          formulaId: "SMA",
          indexCode: "399001.SZ",
          mappingVersion: "board-index-map-v1",
          missingInputs: [],
          outcome: "SATISFIED",
          parameters: [{ key: "period", unit: "COUNT", value: 20 }],
          planPath: "entry.conditions.all[0]",
          snapshotHash: "2".repeat(64),
          unit: "POINTS",
        },
      ],
      health: "LIVE",
      indexCode: "399001.SZ",
      snapshotHash: "2".repeat(64),
    };
    const wrapper = mount(BacktestDetailTable, { props: { items: [item], kind: "DECISION" } });

    const row = wrapper.get('[data-testid="backtest-detail-row"]');
    expect(row.text()).toContain("399001.SZ");
    expect(row.text()).toContain("entry.conditions.all[0]");
    expect(row.text()).toContain("SATISFIED");
    expect(row.text()).toContain("10000.5");
    expect(row.text()).toContain("9999.5");
  });

  it("caps a discriminated detail page at 100 DOM rows", () => {
    const wrapper = mount(BacktestDetailTable, {
      props: {
        items: Array.from({ length: 101 }, (_item, index) => signalDetail(index + 1)),
        kind: "SIGNAL",
      },
    });

    expect(wrapper.findAll('[data-testid="backtest-detail-row"]')).toHaveLength(100);
    expect(wrapper.text()).not.toContain("detail-signal-101");
  });

  it("loads only the URL-selected fills page after the summary", async () => {
    const listFills = vi.fn<BacktestApi["listFills"]>().mockResolvedValue(fillPage());
    const listDetails = vi.fn<BacktestApi["listDetails"]>();
    const { wrapper } = await mountDetail(
      apiWith({ listDetails, listFills }),
      { tab: "fills" },
    );

    expect(listFills).toHaveBeenCalledWith(
      RUN_ID,
      { limit: 100 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(listDetails).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="result-tab-fills"]').attributes("aria-current")).toBe("page");
    expect(wrapper.get('[data-testid="backtest-fill-row"]').text()).toContain(
      "模拟成交（仅供研究）",
    );
    wrapper.unmount();
  });

  it.each([
    ["EXPIRED", "该明细已超过保留期，不能重建"],
    ["NOT_RECORDED", "本次运行未记录该明细"],
  ] as const)("does not request unavailable %s detail or fabricate it", async (availability, copy) => {
    const listDetails = vi.fn<BacktestApi["listDetails"]>();
    const { wrapper } = await mountDetail(
      apiWith({
        getRun: vi.fn().mockResolvedValue(
          run({ availability: { ...run().availability, signalDetails: availability } }),
        ),
        listDetails,
      }),
      { kind: "SIGNAL", tab: "details" },
    );

    expect(listDetails).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="detail-availability"]').text()).toContain(copy);
    expect(wrapper.find('[data-testid="backtest-detail-row"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="refresh-result-details"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("preserves a server availability change that occurs between summary and detail read", async () => {
    const listDetails = vi.fn<BacktestApi["listDetails"]>().mockResolvedValue(
      detailPage("SIGNAL", { availability: "EXPIRED", items: [] }),
    );
    const { wrapper } = await mountDetail(
      apiWith({ listDetails }),
      { kind: "SIGNAL", tab: "details" },
    );

    expect(wrapper.get('[data-testid="detail-availability"]').text()).toContain(
      "该明细已超过保留期，不能重建",
    );
    expect(wrapper.find('[data-testid="backtest-detail-row"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("renders AVAILABLE as a distinct field-level state with its valid refresh action", async () => {
    const { wrapper } = await mountDetail(
      apiWith({
        listDetails: vi.fn().mockResolvedValue(detailPage("DECISION")),
      }),
      { kind: "DECISION", tab: "details" },
    );

    expect(wrapper.get('[data-testid="detail-availability"]').attributes("data-availability")).toBe(
      "AVAILABLE",
    );
    expect(wrapper.get('[data-testid="detail-availability"]').text()).toContain(
      "该明细可读取",
    );
    expect(wrapper.find('[data-testid="refresh-result-details"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("aborts stale tab work and never lets it replace the active detail kind", async () => {
    const pendingFills = deferred<BacktestFillPage>();
    const fillSignals: AbortSignal[] = [];
    const listFills = vi.fn<BacktestApi["listFills"]>((_runId, _query, options) => {
      if (options?.signal !== undefined) fillSignals.push(options.signal);
      return pendingFills.promise;
    });
    const listDetails = vi.fn<BacktestApi["listDetails"]>().mockResolvedValue(
      detailPage("SIGNAL"),
    );
    const { router, wrapper } = await mountDetail(
      apiWith({ listDetails, listFills }),
      { tab: "fills" },
    );

    await router.push({
      path: `/backtests/${RUN_ID}`,
      query: { kind: "SIGNAL", tab: "details" },
    });
    await flushPromises();
    expect(fillSignals[0]?.aborted).toBe(true);
    expect(wrapper.get('[data-testid="backtest-detail-row"]').text()).toContain("BUY_CORE_READY");

    pendingFills.resolve(fillPage());
    await flushPromises();
    expect(wrapper.find('[data-testid="backtest-fill-row"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="backtest-detail-row"]').text()).toContain("BUY_CORE_READY");
    wrapper.unmount();
  });

  it("round-trips opaque cursor pages without accumulating prior rows", async () => {
    const listFills = vi
      .fn<BacktestApi["listFills"]>()
      .mockResolvedValueOnce(
        fillPage({ hasMore: true, items: [fill(1)], nextCursor: CURSOR }),
      )
      .mockResolvedValueOnce(fillPage({ items: [fill(2)] }));
    const { router, wrapper } = await mountDetail(apiWith({ listFills }), { tab: "fills" });

    await wrapper.get('[data-testid="next-result-page"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({ cursor: CURSOR, tab: "fills" });
    expect(listFills).toHaveBeenLastCalledWith(
      RUN_ID,
      { cursor: CURSOR, limit: 100 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.findAll('[data-testid="backtest-fill-row"]')).toHaveLength(1);
    expect(wrapper.get('[data-testid="backtest-fill-row"]').text()).toContain("fill-002");
    expect(wrapper.text()).not.toContain("fill-001");
    wrapper.unmount();
  });

  it("switches discriminated kinds through canonical URL state and clears the old cursor", async () => {
    const listDetails = vi.fn<BacktestApi["listDetails"]>().mockImplementation(
      async (_runId, query) => detailPage(query.kind),
    );
    const { router, wrapper } = await mountDetail(
      apiWith({ listDetails }),
      { cursor: CURSOR, kind: "SIGNAL", tab: "details" },
    );

    await wrapper.get('[data-testid="detail-kind-EXECUTION_OUTCOME"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toEqual({
      kind: "EXECUTION_OUTCOME",
      tab: "details",
    });
    expect(listDetails).toHaveBeenLastCalledWith(
      RUN_ID,
      { kind: "EXECUTION_OUTCOME", limit: 100 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.get('[data-testid="backtest-detail-row"]').text()).toContain("T_PLUS_ONE");
    wrapper.unmount();
  });

  it("canonicalizes repeated or malformed result query values before loading", async () => {
    const listFills = vi.fn<BacktestApi["listFills"]>();
    const listDetails = vi.fn<BacktestApi["listDetails"]>();
    const { router, wrapper } = await mountDetail(
      apiWith({ listDetails, listFills }),
      { cursor: "private/path", kind: "DEBUG_TRACE", tab: "details" },
    );

    expect(router.currentRoute.value.query).toEqual({ kind: "DECISION", tab: "details" });
    expect(listFills).not.toHaveBeenCalled();
    expect(listDetails).toHaveBeenCalledWith(
      RUN_ID,
      { kind: "DECISION", limit: 100 },
      expect.any(Object),
    );
    expect(wrapper.text()).not.toContain("private/path");
    wrapper.unmount();
  });

  it("drops a repeated opaque cursor before issuing the selected request", async () => {
    const listFills = vi.fn<BacktestApi["listFills"]>().mockResolvedValue(fillPage());
    const { router, wrapper } = await mountDetail(
      apiWith({ listFills }),
      { cursor: [CURSOR, "other.cursor"], tab: "fills" },
    );

    expect(router.currentRoute.value.query).toEqual({ tab: "fills" });
    expect(listFills).toHaveBeenCalledTimes(1);
    expect(listFills).toHaveBeenCalledWith(
      RUN_ID,
      { limit: 100 },
      expect.any(Object),
    );
    wrapper.unmount();
  });

  it("uses fixed failure copy and never renders raw diagnostics as result detail", async () => {
    const { wrapper } = await mountDetail(
      apiWith({
        listDetails: vi.fn().mockRejectedValue(new Error("private database path")),
      }),
      { kind: "DECISION", tab: "details" },
    );

    expect(wrapper.get('[data-testid="result-resource-error"]').text()).toContain(
      "结果明细暂不可用，请稍后重试",
    );
    expect(wrapper.text()).not.toContain("private database path");
    wrapper.unmount();
  });
});
