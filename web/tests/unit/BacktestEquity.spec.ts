import { existsSync, readFileSync } from "node:fs";
import { dirname, extname, resolve } from "node:path";

import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import * as ts from "typescript";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  BacktestEquityPointView,
  BacktestEquitySeries,
  BacktestRunView,
} from "../../src/api/generated";
import type { BacktestApi } from "../../src/api/backtests";
import BacktestEquityTable from "../../src/components/backtests/BacktestEquityTable.vue";
import BacktestRunDetailView from "../../src/views/BacktestRunDetailView.vue";

const chartRuntime = vi.hoisted(() => {
  const chart = {
    dispose: vi.fn(),
    resize: vi.fn(),
    setOption: vi.fn(),
  };
  return {
    chart,
    init: vi.fn(() => chart),
    use: vi.fn(),
  };
});

vi.mock("echarts/core", () => ({
  init: chartRuntime.init,
  use: chartRuntime.use,
}));
vi.mock("echarts/charts", () => ({ LineChart: {} }));
vi.mock("echarts/components", () => ({
  GridComponent: {},
  TooltipComponent: {},
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));

const RUN_ID = "a".repeat(64);
const MARKED_AT = "2026-08-29T15:00:00.000000+08:00";

interface StaticImportGraph {
  files: Set<string>;
  packages: Set<string>;
}

function staticImportGraph(entries: string[]): StaticImportGraph {
  const files = new Set<string>();
  const packages = new Set<string>();
  const pending = entries.map((entry) => resolve(process.cwd(), entry));
  while (pending.length > 0) {
    const file = pending.pop();
    if (file === undefined || files.has(file)) continue;
    files.add(file);
    const source = readFileSync(file, "utf8");
    const script = extname(file) === ".vue" ? vueScript(source, file) : source;
    const sourceFile = ts.createSourceFile(
      file,
      script,
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TS,
    );
    for (const statement of sourceFile.statements) {
      const specifier = runtimeModuleSpecifier(statement);
      if (specifier === null) continue;
      if (!specifier.startsWith(".")) {
        packages.add(specifier);
        continue;
      }
      pending.push(resolveStaticModule(file, specifier));
    }
  }
  return { files, packages };
}

function runtimeModuleSpecifier(statement: ts.Statement): string | null {
  if (
    ts.isImportDeclaration(statement) &&
    ts.isStringLiteral(statement.moduleSpecifier) &&
    isRuntimeImport(statement)
  ) {
    return statement.moduleSpecifier.text;
  }
  if (
    ts.isExportDeclaration(statement) &&
    statement.moduleSpecifier !== undefined &&
    ts.isStringLiteral(statement.moduleSpecifier) &&
    isRuntimeExport(statement)
  ) {
    return statement.moduleSpecifier.text;
  }
  return null;
}

function vueScript(source: string, file: string): string {
  const match = source.match(/<script\s+setup(?:\s+lang="ts")?>([\s\S]*?)<\/script>/);
  if (match?.[1] === undefined) throw new Error(`missing script setup: ${file}`);
  return match[1];
}

function isRuntimeImport(statement: ts.ImportDeclaration): boolean {
  const clause = statement.importClause;
  if (clause === undefined) return true;
  if (clause.isTypeOnly) return false;
  if (clause.name !== undefined) return true;
  const bindings = clause.namedBindings;
  if (bindings === undefined || ts.isNamespaceImport(bindings)) return true;
  return bindings.elements.some((element) => !element.isTypeOnly);
}

function isRuntimeExport(statement: ts.ExportDeclaration): boolean {
  if (statement.isTypeOnly) return false;
  const clause = statement.exportClause;
  if (clause === undefined || ts.isNamespaceExport(clause)) return true;
  return clause.elements.some((element) => !element.isTypeOnly);
}

function resolveStaticModule(importer: string, specifier: string): string {
  const base = resolve(dirname(importer), specifier);
  const candidates =
    extname(base) === ""
      ? [
          `${base}.ts`,
          `${base}.vue`,
          resolve(base, "index.ts"),
          resolve(base, "index.vue"),
        ]
      : [base];
  const match = candidates.find((candidate) => existsSync(candidate));
  if (match === undefined) {
    throw new Error(`unresolved static import ${specifier} from ${importer}`);
  }
  return match;
}

function point(
  index: number,
  overrides: Partial<BacktestEquityPointView> = {},
): BacktestEquityPointView {
  return {
    cashFen: "90000",
    costBasisFen: "9000",
    equityFen: String(100000 + index),
    markPriceFen: "100",
    markedAt: `2026-08-${String(index + 1).padStart(2, "0")}T15:00:00.000000+08:00`,
    marketValueFen: "10000",
    positionQuantity: 100,
    realizedPnlFen: "0",
    runId: RUN_ID,
    snapshotId: `snapshot-${String(index).padStart(4, "0")}`,
    symbol: "000001.SZ",
    totalCostFen: "12",
    unrealizedPnlFen: "1000",
    ...overrides,
  };
}

function series(
  items: BacktestEquityPointView[] = [point(0)],
  availability: BacktestEquitySeries["availability"] = "AVAILABLE",
): BacktestEquitySeries {
  return { availability, items };
}

function run(
  availability: BacktestRunView["availability"]["equitySeries"] = "AVAILABLE",
): BacktestRunView {
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
      equitySeries: availability,
      executionOutcomeDetails: "AVAILABLE",
      signalDetails: "AVAILABLE",
    },
    completedAt: MARKED_AT,
    coverage: {
      decisionCount: 1,
      equityPointCount: availability === "AVAILABLE" ? 1 : 0,
      eventEnd: "2026-08-29",
      eventStart: "2026-08-01",
      fillCount: 1,
      orderCount: 1,
      outcomeCount: 1,
      signalCount: 1,
      tradingDayCount: 1,
    },
    datasetHash: "d".repeat(64),
    eventEnd: "2026-08-29",
    eventStart: "2026-08-01",
    fillCount: 1,
    formulaVersions: {
      executionFormulaVersion: "backtest-execution-v1",
      metricFormulaVersion: "backtest-metrics-v1",
      reportSchemaVersion: "backtest-report-summary-v2",
      runFormulaVersion: "backtest-run-v2",
    },
    initialCashFen: "100000",
    limitations: ["HISTORICAL_SIMULATION"],
    metrics: {
      blockedCount: 0,
      finalCashFen: "90000",
      finalEquityFen: "100000",
      initialCashFen: "100000",
      initialEquityFen: "100000",
      maximumDrawdown: "0",
      realizedPnlFen: "0",
      skippedCount: 0,
      totalCostFen: "12",
      totalReturn: "0",
      tradeCount: 1,
      turnoverFen: "10000",
      unrealizedPnlFen: "1000",
      winRate: "0",
      winningSellCount: 0,
    },
    pinned: false,
    planHash: "e".repeat(64),
    planVersionId: "123e4567-e89b-42d3-a456-426614174000",
    reportHash: "f".repeat(64),
    revision: 0,
    runId: RUN_ID,
    status: "COMPLETED",
    symbol: "000001.SZ",
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
  const promise = new Promise<Value>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

async function mountDetail(
  api: BacktestApi,
  query = "",
): Promise<{ router: Router; wrapper: VueWrapper }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/backtests/:runId", component: { template: "<div />" } }],
  });
  await router.push(`/backtests/${RUN_ID}${query}`);
  await router.isReady();
  const wrapper = mount(BacktestRunDetailView, {
    attachTo: document.body,
    global: { plugins: [router] },
    props: { api },
  });
  await flushPromises();
  return { router, wrapper };
}

beforeEach(() => {
  chartRuntime.chart.dispose.mockClear();
  chartRuntime.chart.resize.mockClear();
  chartRuntime.chart.setOption.mockClear();
  chartRuntime.init.mockClear();
  chartRuntime.use.mockClear();
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("BT046 equity review", () => {
  it("keeps runs, new, data, and the initial detail summary free of ECharts modules", async () => {
    await Promise.all([
      import("../../src/views/BacktestRunsView.vue"),
      import("../../src/views/BacktestNewView.vue"),
      import("../../src/views/BacktestDataView.vue"),
    ]);
    const detailSource = readFileSync(
      resolve(process.cwd(), "src/views/BacktestRunDetailView.vue"),
      "utf8",
    );
    expect(detailSource).toMatch(
      /defineAsyncComponent\(\s*\(\) => import\("\.\.\/components\/backtests\/BacktestEquityChart\.vue"\),\s*\)/,
    );
    expect(detailSource).not.toMatch(/import\s+BacktestEquityChart\s+from/);
    const graph = staticImportGraph([
      "src/views/BacktestRunsView.vue",
      "src/views/BacktestNewView.vue",
      "src/views/BacktestDataView.vue",
      "src/views/BacktestRunDetailView.vue",
    ]);
    expect(graph.files).not.toContain(
      resolve(process.cwd(), "src/components/backtests/BacktestEquityChart.vue"),
    );
    expect(
      [...graph.packages].filter(
        (specifier) => specifier === "echarts" || specifier.startsWith("echarts/"),
      ),
    ).toEqual([]);
    const getEquitySeries = vi.fn<BacktestApi["getEquitySeries"]>();
    const { wrapper } = await mountDetail(
      apiWith({ getEquitySeries, getRun: vi.fn().mockResolvedValue(run()) }),
    );

    expect(getEquitySeries).not.toHaveBeenCalled();
    expect(chartRuntime.init).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="backtest-equity-chart"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("loads equity only after its URL-backed tab is selected", async () => {
    const items = [point(0), point(1)];
    const getEquitySeries = vi
      .fn<BacktestApi["getEquitySeries"]>()
      .mockResolvedValue(series(items));
    const { router, wrapper } = await mountDetail(
      apiWith({ getEquitySeries, getRun: vi.fn().mockResolvedValue(run()) }),
    );

    await wrapper.get('[data-testid="result-tab-equity"]').trigger("click");
    await vi.dynamicImportSettled();
    await flushPromises();

    expect(router.currentRoute.value.query).toEqual({ tab: "equity" });
    expect(getEquitySeries).toHaveBeenCalledWith(
      RUN_ID,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(wrapper.findAll('[data-testid="backtest-equity-row"]')).toHaveLength(2);
    expect(chartRuntime.init).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it.each(["EXPIRED", "NOT_RECORDED"] as const)(
    "does not request or fabricate %s equity",
    async (availability) => {
      const getEquitySeries = vi.fn<BacktestApi["getEquitySeries"]>();
      const { wrapper } = await mountDetail(
        apiWith({ getEquitySeries, getRun: vi.fn().mockResolvedValue(run(availability)) }),
        "?tab=equity",
      );

      expect(getEquitySeries).not.toHaveBeenCalled();
      expect(wrapper.get('[data-testid="equity-availability"]').attributes("data-availability")).toBe(
        availability,
      );
      expect(wrapper.find('[data-testid="backtest-equity-row"]').exists()).toBe(false);
      expect(chartRuntime.init).not.toHaveBeenCalled();
      wrapper.unmount();
    },
  );

  it("aborts selected equity work when the user leaves the tab", async () => {
    const pending = deferred<BacktestEquitySeries>();
    let signal: AbortSignal | undefined;
    const getEquitySeries = vi.fn<BacktestApi["getEquitySeries"]>((_runId, options) => {
      signal = options?.signal;
      return pending.promise;
    });
    const { router, wrapper } = await mountDetail(
      apiWith({ getEquitySeries, getRun: vi.fn().mockResolvedValue(run()) }),
      "?tab=equity",
    );

    expect(signal?.aborted).toBe(false);
    await router.push(`/backtests/${RUN_ID}?tab=summary`);
    await flushPromises();
    expect(signal?.aborted).toBe(true);
    pending.resolve(series([point(0)]));
    await flushPromises();
    expect(wrapper.find('[data-testid="backtest-equity-row"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("canonicalizes equity without a detail kind or cursor", async () => {
    const getEquitySeries = vi
      .fn<BacktestApi["getEquitySeries"]>()
      .mockResolvedValue(series([point(0)]));
    const { router, wrapper } = await mountDetail(
      apiWith({ getEquitySeries, getRun: vi.fn().mockResolvedValue(run()) }),
      "?tab=equity&kind=SIGNAL&cursor=opaque.cursor",
    );

    expect(router.currentRoute.value.query).toEqual({ tab: "equity" });
    expect(getEquitySeries).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("renders all bounded points in server order with exact FenText and China time", () => {
    const items = Array.from({ length: 2_001 }, (_, index) =>
      point(index, {
        equityFen: index === 0 ? "9007199254740993123" : String(100000 + index),
      }),
    );
    const wrapper = mount(BacktestEquityTable, { props: { items } });

    const rows = wrapper.findAll('[data-testid="backtest-equity-row"]');
    expect(rows).toHaveLength(2_000);
    expect(rows[0]?.text()).toContain("snapshot-0000");
    expect(rows[0]?.text()).toContain("90071992547409931.23");
    expect(rows[0]?.text()).toContain("2026-08-01 15:00:00");
    expect(rows[1]?.text()).toContain("snapshot-0001");
    expect(rows[1]?.get("time").attributes("datetime")).toBe(
      "2026-08-02T15:00:00.000000+08:00",
    );
  });

  it("plots the same order with safe display numbers and disposes the instance", async () => {
    const { default: BacktestEquityChart } = await import(
      "../../src/components/backtests/BacktestEquityChart.vue"
    );
    const items = [
      point(0, { equityFen: "100001" }),
      point(1, { equityFen: "9007199254740992" }),
    ];
    const wrapper = mount(BacktestEquityChart, { props: { items } });
    await flushPromises();

    expect(chartRuntime.use).toHaveBeenCalledTimes(1);
    expect(chartRuntime.init).toHaveBeenCalledTimes(1);
    const option = chartRuntime.chart.setOption.mock.calls[0]?.[0] as {
      series: Array<{ data: Array<number | null> }>;
      xAxis: { data: string[] };
    };
    expect(option.xAxis.data).toEqual([
      "2026-08-01 15:00:00",
      "2026-08-02 15:00:00",
    ]);
    expect(option.series[0]?.data).toEqual([1000.01, null]);

    wrapper.unmount();
    expect(chartRuntime.chart.dispose).toHaveBeenCalledTimes(1);
  });

  it("uses fixed failure copy and never exposes raw equity errors", async () => {
    const { wrapper } = await mountDetail(
      apiWith({
        getEquitySeries: vi.fn().mockRejectedValue(new Error("private storage path")),
        getRun: vi.fn().mockResolvedValue(run()),
      }),
      "?tab=equity",
    );

    expect(wrapper.get('[data-testid="result-resource-error"]').text()).toContain(
      "权益序列暂不可用，请稍后重试",
    );
    expect(wrapper.text()).not.toContain("private storage path");
    wrapper.unmount();
  });
});
