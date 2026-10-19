import { createRequire } from "node:module";
import researchDecision from "../fixtures/unified-replay-decision.json" with { type: "json" };

import { expect, test } from "./fixtures";
import type { Browser, Page, Route, TestInfo } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type {
  BacktestDatasetPage,
  BacktestDetailPage,
  BacktestEquitySeries,
  BacktestJobReceipt,
  BacktestJobView,
  BacktestJobPage,
  BacktestMarketIndexSeriesView,
  BacktestReferenceMarketCoverageView,
  BacktestRunPage,
  BacktestRunSummaryView,
  BacktestRunView,
  BacktestServiceView,
  DashboardResponse,
  PlanVersionPage,
} from "../../src/api/generated";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const RUN_ID = "a".repeat(64);
const DATASET_HASH = "d".repeat(64);
const JOB_ID = "e2e-run-job-001";
const PLAN_VERSION_ID = "123e4567-e89b-42d3-a456-426614174000";
const TIME = "2026-08-30T10:00:00.000000+08:00";
const INDEX_TIME = "2026-08-28T15:00:00.000000+08:00";
const serviceStatus: BacktestServiceView = {
  epoch: "f".repeat(32), revision: 1, generation: 1, state: "READY",
  canRead: true, canSubmit: true, canCancel: true, canExport: true,
  physicallyDrained: true, authorizedJobIds: [], reason: null,
};
const ROUTES = [
  { heading: "回测运行记录", path: "/backtests", readyTestId: "run-detail-link", viewSelector: ".backtest-runs-view" },
  { heading: "创建回测", path: "/backtests/new", readyTestId: "submit-backtest-run", viewSelector: ".backtest-new-view" },
  {
    heading: "历史数据管理",
    path: "/backtests/data?symbols=000001.SZ&start=2026-08-01&end=2026-08-28&warmupStart=2026-07-01",
    readyTestId: "apply-dataset-filters",
    viewSelector: ".backtest-data-view",
  },
  {
    heading: "回测结果",
    path: `/backtests/${RUN_ID}`,
    readyTestId: "result-tab-summary",
    viewSelector: ".run-detail-view",
  },
] as const;

const dashboard: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: {
    actionable: 0,
    blocked: 0,
    lowZoneWatch: 0,
    normal: 0,
    risk: 0,
    stale: 0,
  },
  marketIndexes: [],
  observedAt: TIME,
  runtimeGeneration: "00000000-0000-4000-8000-000000000001",
  sequence: 1,
  symbols: [],
};

const planVersionPage: PlanVersionPage = {
  items: [
    {
      canActivate: true,
      createdAt: TIME,
      id: PLAN_VERSION_ID,
      planHash: "e".repeat(64),
      planId: "e2e-backtest-plan",
      revision: 0,
      status: "DRAFT",
      symbol: "000001.SZ",
      version: 1,
    },
  ],
  limit: 20,
  offset: 0,
  total: 1,
};

interface BrowserAudit {
  apiFailures: string[];
  chartRequests: string[];
  consoleFailures: string[];
  externalRequests: string[];
  inFlight: Map<string, number>;
  jobRequestTimes: number[];
  maxInFlight: Map<string, number>;
  requestFailures: string[];
  requestTotals: Map<string, number>;
  runSubmissions: { body: unknown; idempotencyKey: string | null }[];
  unexpectedRequests: string[];
}

let server: ViteDevServer;
let baseUrl: string;

const runView: BacktestRunView = {
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
    executionOutcomeDetails: "AVAILABLE",
    signalDetails: "AVAILABLE",
  },
  completedAt: TIME,
  coverage: {
    decisionCount: 1,
    equityPointCount: 1,
    eventEnd: "2026-08-28",
    eventStart: "2026-08-01",
    fillCount: 1,
    orderCount: 1,
    outcomeCount: 1,
    signalCount: 1,
    tradingDayCount: 20,
  },
  datasetHash: DATASET_HASH,
  eventEnd: "2026-08-28",
  eventStart: "2026-08-01",
  fillCount: 1,
  formulaVersions: {
    executionFormulaVersion: "backtest-execution-v1",
    metricFormulaVersion: "backtest-metrics-v1",
    reportSchemaVersion: "backtest-report-summary-v2",
    runFormulaVersion: "backtest-run-v2",
  },
  initialCashFen: "1000000",
  limitations: ["HISTORICAL_SIMULATION"],
  metrics: {
    blockedCount: 0,
    finalCashFen: "900000",
    finalEquityFen: "1100000",
    initialCashFen: "1000000",
    initialEquityFen: "1000000",
    maximumDrawdown: "0.01",
    realizedPnlFen: "100000",
    skippedCount: 0,
    totalCostFen: "100",
    totalReturn: "0.1",
    tradeCount: 1,
    turnoverFen: "100000",
    unrealizedPnlFen: "0",
    winRate: "1",
    winningSellCount: 1,
  },
  pinned: false,
  planHash: "e".repeat(64),
  planVersionId: PLAN_VERSION_ID,
  referenceMarket: null,
  reportHash: "f".repeat(64),
  revision: 0,
  runId: RUN_ID,
  status: "COMPLETED",
  symbol: "000001.SZ",
};

const runSummary: BacktestRunSummaryView = {
  availability: runView.availability,
  completedAt: runView.completedAt,
  datasetHash: runView.datasetHash,
  eventEnd: runView.eventEnd,
  eventStart: runView.eventStart,
  fillCount: runView.fillCount,
  metrics: runView.metrics,
  pinned: runView.pinned,
  planHash: runView.planHash,
  planVersionId: PLAN_VERSION_ID,
  reportHash: runView.reportHash,
  revision: runView.revision,
  runId: runView.runId,
  status: runView.status,
  symbol: runView.symbol,
};

const runPage: BacktestRunPage = {
  filters: {
    completedFrom: null,
    completedTo: null,
    datasetHash: null,
    pinned: null,
    planVersionId: null,
    symbol: null,
  },
  hasMore: false,
  highWatermark: "watermark.anchor",
  items: [runSummary],
  limit: 20,
  nextCursor: null,
};

const datasetPage: BacktestDatasetPage = {
  filters: {
    adjustmentPolicy: null,
    endOnOrBefore: null,
    historicalProfile: null,
    startOnOrAfter: null,
    symbol: null,
  },
  hasMore: false,
  highWatermark: "datasets-watermark-001",
  items: [
    {
      coverage: {
        blockers: [],
        calendarRowCount: 20,
        dailyBarRowCount: 20,
        dailyLimitRowCount: 20,
        minuteBarCount: 4_800,
        minuteDayCount: 20,
        symbolCount: 1,
        tradingDayCount: 20,
      },
      createdAt: TIME,
      datasetHash: DATASET_HASH,
      schemaVersion: "backtest-dataset-v2",
      scope: {
        adjustmentPolicy: "NONE",
        end: "2026-08-28",
        historicalProfile: "TUSHARE_STK_MINS_241_END_V1",
        start: "2026-08-01",
        symbols: ["000001.SZ"],
        warmupStart: "2026-07-01",
      },
      verifiedAt: TIME,
    },
  ],
  limit: 20,
  nextCursor: null,
};

const equitySeries: BacktestEquitySeries = {
  availability: "AVAILABLE",
  items: [
    {
      cashFen: "900000",
      costBasisFen: "90000",
      equityFen: "1100000",
      markPriceFen: "2000",
      markedAt: TIME,
      marketValueFen: "200000",
      positionQuantity: 100,
      realizedPnlFen: "100000",
      runId: RUN_ID,
      snapshotId: "snapshot-0001",
      symbol: "000001.SZ",
      totalCostFen: "100",
      unrealizedPnlFen: "110000",
    },
  ],
};

const referenceMarketCoverage: BacktestReferenceMarketCoverageView = {
  availableFiveMinuteCount: 0,
  availableOfficialDayCount: 22,
  binding: {
    board: "SZSE_MAIN",
    displayName: "深证成指",
    indexCode: "399001.SZ",
    mappingVersion: "board-index-map-v1",
    selection: "AUTO_BOARD",
  },
  blockers: [],
  conditionPaths: ["entry.conditions.all[0]"],
  coverageStatus: "AVAILABLE",
  datasetHash: DATASET_HASH,
  formulaDefinitionHash: "2".repeat(64),
  indexRequirementHash: "3".repeat(64),
  marketIndexDataHash: "4".repeat(64),
  planVersionId: PLAN_VERSION_ID,
  required: true,
  requiredFiveMinuteCount: 0,
  requiredOfficialDayCount: 21,
  warmupEnd: "2026-08-28",
  warmupStart: "2026-07-01",
};

const conditionSummary = {
  applicableBranchCount: 1,
  conditionType: "INDEX_CLOSE_GTE_MA" as const,
  formulaId: "SMA" as const,
  missingCount: 0,
  parameters: { period: 20 },
  planPath: "entry.conditions.all[0]",
  satisfiedCount: 1,
  unsatisfiedCount: 0,
};

const marketIndexSeries: BacktestMarketIndexSeriesView = {
  conditionSummaries: [conditionSummary],
  healthTimeline: [{ dataAt: INDEX_TIME, health: "LIVE", issues: [] }],
  items: [
    {
      closePoints: "10000.5",
      dataAt: INDEX_TIME,
      health: "LIVE",
      indicatorFacts: [
        {
          formulaDefinitionHash: "2".repeat(64),
          formulaId: "SMA",
          period: 20,
          sourceBarHash: "5".repeat(64),
          unit: "POINTS",
          value: "9999.5",
        },
      ],
      issues: [],
      snapshotHash: "6".repeat(64),
      tradeDate: "2026-08-28",
    },
  ],
  referenceMarket: {
    binding: referenceMarketCoverage.binding,
    blockers: [],
    conditionPaths: referenceMarketCoverage.conditionPaths,
    conditionSummaries: [conditionSummary],
    coverageStatus: "AVAILABLE",
    datasetHash: DATASET_HASH,
    formulaDefinitionHash: referenceMarketCoverage.formulaDefinitionHash,
    indexRequirementHash: referenceMarketCoverage.indexRequirementHash,
    marketIndexDataHash: referenceMarketCoverage.marketIndexDataHash!,
    required: true,
    warmupStart: referenceMarketCoverage.warmupStart,
  },
  runId: RUN_ID,
};

const decisionDetails: BacktestDetailPage = {
  availability: "AVAILABLE",
  filters: { kind: "DECISION" },
  hasMore: false,
  highWatermark: "decision.watermark_001",
  items: [
    {
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
        planHash: runView.planHash,
        planId: "plan-001",
        planVersion: 1,
        position: {
          coreQuantity: 0,
          sellableCoreQuantity: 0,
          sellableTacticalQuantity: 0,
          tacticalQuantity: 0,
          totalQuantity: 0,
        },
        priceFen: "100000",
        referenceMarket: {
          dataAt: INDEX_TIME,
          evidence: [
            {
              actualValue: "10000.5",
              comparisonValue: "9999.5",
              conditionType: "INDEX_CLOSE_GTE_MA",
              dataCutoff: INDEX_TIME,
              decisionCutoff: TIME,
              formulaDefinitionHash: referenceMarketCoverage.formulaDefinitionHash,
              formulaId: "SMA",
              indexCode: "399001.SZ",
              mappingVersion: "board-index-map-v1",
              missingInputs: [],
              outcome: "SATISFIED",
              parameters: [{ key: "period", unit: "BARS", value: 20 }],
              planPath: "entry.conditions.all[0]",
              snapshotHash: "6".repeat(64),
              unit: "POINTS",
            },
          ],
          health: "LIVE",
          indexCode: "399001.SZ",
          snapshotHash: "6".repeat(64),
        },
        resultHash: "7".repeat(64),
        riskBreachTradeDate: null,
        riskStatus: "CLEAR",
        signalType: "BUY_CORE_READY",
        symbol: "000001.SZ",
        zone: "LOW_BUY",
      },
      detailId: "detail-decision-001",
      eventAt: TIME,
      kind: "DECISION",
      resultHash: "7".repeat(64),
      runId: RUN_ID,
    },
  ],
  kind: "DECISION",
  limit: 100,
  nextCursor: null,
};

const queuedRunReceipt: BacktestJobReceipt = {
  attempt: 0,
  datasetHash: DATASET_HASH,
  jobId: JOB_ID,
  kind: "BACKTEST_RUN",
  reused: false,
  revision: 0,
  runId: RUN_ID,
  status: "QUEUED",
  submittedAt: TIME,
};

test.beforeAll(async () => {
  server = await createServer({
    configFile: "vite.legacy-test.config.ts",
    clearScreen: false,
    logLevel: "silent",
    root: process.cwd(),
    server: { hmr: false, host: "127.0.0.1", port: 0 },
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (address === null || address === undefined || typeof address === "string") {
    throw new Error("Vite backtest harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

function completedJob(): BacktestJobView {
  return {
    attempt: 1,
    cancelRequestedAt: null,
    createdAt: TIME,
    datasetHash: DATASET_HASH,
    errorCode: null,
    errorMessage: null,
    finishedAt: TIME,
    jobId: JOB_ID,
    kind: "BACKTEST_RUN",
    progress: {
      completedUnits: 20,
      phase: "TERMINAL",
      totalUnits: 20,
      unit: "EVENTS",
      updatedAt: TIME,
    },
    requestHash: "1".repeat(64),
    result: {
      kind: "BACKTEST_RUN",
      reportHash: runView.reportHash,
      reused: false,
      runId: RUN_ID,
    },
    reused: false,
    revision: 2,
    runId: RUN_ID,
    startedAt: TIME,
    status: "COMPLETED",
    updatedAt: TIME,
  };
}

function runningJob(): BacktestJobView {
  return {
    ...completedJob(),
    finishedAt: null,
    progress: {
      completedUnits: 5,
      phase: "REPLAYING",
      totalUnits: 20,
      unit: "EVENTS",
      updatedAt: TIME,
    },
    result: null,
    revision: 1,
    status: "RUNNING",
  };
}

function pendingJobs(items: BacktestJobView[] = []): BacktestJobPage {
  return { items, limit: 1, hasMore: false, nextCursor: null, highWatermark: "jobs.watermark_001",
    filters: { kind: null, status: ["CANCEL_REQUESTED", "QUEUED", "RUNNING"], runId: null, datasetHash: null, createdFrom: null, createdTo: null } };
}

function newAudit(): BrowserAudit {
  return {
    apiFailures: [],
    chartRequests: [],
    consoleFailures: [],
    externalRequests: [],
    inFlight: new Map(),
    jobRequestTimes: [],
    maxInFlight: new Map(),
    requestFailures: [],
    requestTotals: new Map(),
    runSubmissions: [],
    unexpectedRequests: [],
  };
}

async function fulfillJson(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json; charset=utf-8",
    headers: { "Cache-Control": "no-store" },
    status: 200,
  });
}

async function installFakeContract(page: Page, audit: BrowserAudit): Promise<void> {
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      audit.consoleFailures.push(`${message.type()}:${message.text()}`);
    }
  });
  page.on("request", (request) => {
    const requestUrl = new URL(request.url());
    const applicationUrl = new URL(baseUrl);
    if (
      (requestUrl.protocol === "http:" ||
        requestUrl.protocol === "https:" ||
        requestUrl.protocol === "ws:" ||
        requestUrl.protocol === "wss:") &&
      requestUrl.host !== applicationUrl.host
    ) {
      audit.externalRequests.push(request.url());
    }
    if (/echarts|BacktestEquityChart|installCanvasRenderer/i.test(request.url())) {
      audit.chartRequests.push(request.url());
    }
  });
  page.on("requestfailed", (request) => {
    audit.requestFailures.push(`${request.method()} ${request.url()}`);
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/") && response.status() >= 400) {
      audit.apiFailures.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.route(`${baseUrl}/api/v1/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const key = `${request.method()} ${url.pathname}`;
    const active = (audit.inFlight.get(key) ?? 0) + 1;
    audit.inFlight.set(key, active);
    audit.maxInFlight.set(key, Math.max(audit.maxInFlight.get(key) ?? 0, active));
    audit.requestTotals.set(key, (audit.requestTotals.get(key) ?? 0) + 1);
    try {
      if (key === "GET /api/v1/dashboard") {
        await fulfillJson(route, dashboard);
      } else if (key === "GET /api/v1/backtest-service") {
        await fulfillJson(route, serviceStatus);
      } else if (key === "GET /api/v1/backtest-jobs") {
        expect(url.searchParams.get("limit")).toBe("1");
        expect(url.searchParams.getAll("status")).toEqual(["CANCEL_REQUESTED", "QUEUED", "RUNNING"]);
        await fulfillJson(route, pendingJobs());
      } else if (key === "GET /api/v1/backtest-plan-library") {
        expect(url.searchParams.get("offset")).toBe("0");
        expect(url.searchParams.get("limit")).toBe("100");
        await fulfillJson(route, { items: [], offset: 0, limit: 100, total: 0 });
      } else if (key === "GET /api/v1/plan-versions") {
        expect(url.searchParams.get("canActivate")).toBe("true");
        await fulfillJson(route, planVersionPage);
      } else if (key === "POST /api/v1/backtest-runs") {
        audit.runSubmissions.push({
          body: request.postDataJSON(),
          idempotencyKey: request.headers()["idempotency-key"] ?? null,
        });
        await route.fulfill({
          body: JSON.stringify(queuedRunReceipt),
          contentType: "application/json; charset=utf-8",
          headers: {
            Location: `/api/v1/backtest-jobs/${JOB_ID}`,
            "Retry-After": "2",
          },
          status: 202,
        });
      } else if (key === "GET /api/v1/backtest-runs") {
        const from = url.searchParams.get("eventEndFrom"), to = url.searchParams.get("eventEndTo");
        await fulfillJson(route, { ...runPage,
          filters: { ...runPage.filters, ...(from ? { eventEndFrom: from } : {}), ...(to ? { eventEndTo: to } : {}) },
          items: runPage.items.filter(item => (!from || item.eventEnd >= from) && (!to || item.eventEnd <= to)),
        });
      } else if (key === "GET /api/v1/backtest-datasets") {
        await fulfillJson(route, datasetPage);
      } else if (key === `GET /api/v1/backtest-runs/${RUN_ID}/equity-series`) {
        await fulfillJson(route, equitySeries);
      } else if (key === `GET /api/v1/backtest-runs/${RUN_ID}/market-index-series`) {
        await fulfillJson(route, marketIndexSeries);
      } else if (key === `GET /api/v1/backtest-runs/${RUN_ID}/details`) {
        await fulfillJson(route, decisionDetails);
      } else if (key === `GET /api/v1/backtest-datasets/${DATASET_HASH}/reference-market-coverage`) {
        await fulfillJson(route, referenceMarketCoverage);
      } else if (key === `GET /api/v1/backtest-runs/${RUN_ID}`) {
        await fulfillJson(route, runView);
      } else if (key === `GET /api/v1/backtest-jobs/${JOB_ID}`) {
        audit.jobRequestTimes.push(Date.now());
        await fulfillJson(
          route,
          audit.jobRequestTimes.length === 1 ? runningJob() : completedJob(),
        );
      } else {
        audit.unexpectedRequests.push(key);
        await route.fulfill({ body: "unexpected fake-contract request", status: 500 });
      }
    } finally {
      audit.inFlight.set(key, (audit.inFlight.get(key) ?? 1) - 1);
    }
  });
}

async function openPage(browser: Browser, width = 1024): Promise<{ audit: BrowserAudit; page: Page }> {
  const page = await browser.newPage({
    locale: "zh-CN",
    reducedMotion: "reduce",
    timezoneId: "Asia/Shanghai",
    viewport: { height: 900, width },
  });
  const audit = newAudit();
  await installFakeContract(page, audit);
  return { audit, page };
}

async function openRoute(page: Page, route: (typeof ROUTES)[number]): Promise<void> {
  await page.waitForLoadState("networkidle");
  await page.goto(`${baseUrl}${route.path}`);
  await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
  await expect(page.getByTestId(route.readyTestId)).toBeVisible();
}

async function fillValidRunCommand(page: Page): Promise<void> {
  await page.locator("#plan-version-id").selectOption(PLAN_VERSION_ID);
  await page.locator("#dataset-hash").fill(DATASET_HASH);
  await page.locator("#initial-cash-fen").fill("10000000");
  await page.locator("#commission-rate").fill("0.0003");
  await page.locator("#minimum-commission-fen").fill("500");
  await page.locator("#stamp-duty-rate").fill("0.001");
  await page.locator("#transfer-fee-rate").fill("0.00001");
  await page.locator("#buy-slippage-bps").fill("2.5");
  await page.locator("#sell-slippage-bps").fill("3.75");
}

async function expectNoSeriousAxeViolations(page: Page): Promise<void> {
  await page.addScriptTag({ path: axePath });
  const violations = await page.evaluate(async () => {
    const axe = (globalThis as typeof globalThis & {
      axe: {
        run: (
          root: Document,
          options: object,
        ) => Promise<{
          violations: {
            id: string;
            impact: string | null;
            nodes: { target: string[] }[];
          }[];
        }>;
      };
    }).axe;
    const result = await axe.run(document, {
      runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    });
    return result.violations
      .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
      .map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        targets: violation.nodes.flatMap((node) => node.target),
      }));
  });
  expect(violations).toEqual([]);
}

function expectChromeProject(testInfo: TestInfo): void {
  expect(testInfo.project.name).toBe("chrome");
}

function expectCleanAudit(audit: BrowserAudit): void {
  expect(audit.apiFailures).toEqual([]);
  expect(audit.consoleFailures).toEqual([]);
  expect(audit.externalRequests).toEqual([]);
  expect(audit.requestFailures).toEqual([]);
  expect(audit.unexpectedRequests).toEqual([]);
  expect([...audit.maxInFlight.values()].every((maximum) => maximum <= 1)).toBe(true);
}

test("service management stays compact and supports keyboard disclosure at desktop and mobile widths", async ({ browser }, testInfo) => {
  const { audit, page } = await openPage(browser);
  await openRoute(page, ROUTES[0]);
  await expect.poll(() => audit.requestTotals.get("GET /api/v1/backtest-jobs")).toBe(1);
  const toggle = page.getByTestId("backtest-service-management-toggle");
  const panel = page.getByTestId("backtest-service-management");
  for (const width of [1440, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(toggle).toHaveAttribute("aria-expanded", "false"); await expect(panel).toHaveCount(0);
    await page.getByTestId("backtest-service-state").screenshot({ path: testInfo.outputPath(`compact-service-${width}.png`) });
    await toggle.focus(); await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    for (const name of ["刷新服务状态", "查看待恢复任务", "停止回测服务"]) await expect(panel.getByRole("button", { name, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "返回监控总览", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expectNoSeriousAxeViolations(page);
    await page.getByTestId("backtest-service-state").screenshot({ path: testInfo.outputPath(`expanded-service-${width}.png`) });
    await toggle.focus(); await page.keyboard.press("Space"); await expect(panel).toHaveCount(0);
  }
  expect(audit.requestTotals.get("POST /api/v1/backtest-service/recovery-requests")).toBeUndefined();
  expect(audit.requestTotals.get("POST /api/v1/backtest-service/stop-requests")).toBeUndefined();
  expectCleanAudit(audit); await page.close();
});

test("interrupted jobs and service faults expand management without automatically resuming work", async ({ browser }) => {
  const { audit, page } = await openPage(browser);
  const controls: string[] = []; page.on("request", request => { if (request.method() === "POST") controls.push(request.url()); });
  await page.route(`${baseUrl}/api/v1/backtest-jobs?*`, route => fulfillJson(route, pendingJobs([runningJob()])));
  await openRoute(page, ROUTES[0]);
  const toggle = page.getByTestId("backtest-service-management-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const panel = page.getByTestId("backtest-service-management");
  await expect(panel).toContainText(`待恢复任务：${JOB_ID}`);
  await expect(panel.getByRole("button", { name: "恢复已选任务", exact: true })).toBeDisabled();
  await panel.getByLabel("确认只恢复此任务").check();
  await expect(panel.getByRole("button", { name: "恢复已选任务", exact: true })).toBeEnabled();
  expect(controls).toEqual([]);
  await page.route(`${baseUrl}/api/v1/backtest-service`, route => fulfillJson(route, { ...serviceStatus, state: "DEGRADED", canSubmit: false, physicallyDrained: false, reason: "SERVICE_REPAIR_REQUIRED" }));
  await page.reload();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(panel).toContainText("正在等待已有工作实际结束");
  await expect(panel.getByRole("button", { name: "重新准备回测服务", exact: true })).toHaveCount(0);
  expect(controls).toEqual([]); expectCleanAudit(audit); await page.close();
});

test("compact service controls preserve job progress, refresh, cancellation and same-request retry", async ({ browser }) => {
  const { audit, page } = await openPage(browser);
  let reads = 0, cancellations = 0;
  const intents: Array<{ body: unknown; key: string | undefined }> = [];
  const cancellingJob = () => ({ ...runningJob(), status: "CANCEL_REQUESTED", cancelRequestedAt: TIME, revision: 2 });
  await page.route(`${baseUrl}/api/v1/backtest-service`, route => fulfillJson(route, { ...serviceStatus, authorizedJobIds: [JOB_ID], physicallyDrained: false }));
  await page.route(`${baseUrl}/api/v1/backtest-jobs/${JOB_ID}`, route => {
    reads += 1;
    return fulfillJson(route, reads === 1 ? {} : cancellations > 1 ? cancellingJob() : runningJob());
  });
  await page.route(`${baseUrl}/api/v1/backtest-job-cancellations`, async route => {
    cancellations += 1;
    intents.push({ body: route.request().postDataJSON(), key: route.request().headers()["idempotency-key"] });
    await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify(cancellations === 1 ? {} : cancellingJob()),
      headers: { Location: `/api/v1/backtest-jobs/${JOB_ID}`, "Retry-After": "2" } });
  });
  await page.goto(`${baseUrl}/backtests/${RUN_ID}?jobId=${JOB_ID}`);
  await expect(page.getByTestId("refresh-job-status")).toBeVisible();
  await page.getByTestId("refresh-job-status").click();
  await expect(page.getByRole("progressbar")).toHaveAttribute("value", "5");
  await expect(page.getByRole("progressbar")).toHaveAttribute("max", "20");
  const toggle = page.getByTestId("backtest-service-management-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click(); await toggle.click();
  await expect(page.getByTestId("request-job-cancel")).toBeVisible();
  await page.getByTestId("request-job-cancel").click();
  await expect(page.getByRole("dialog", { name: "确认请求取消" })).toBeVisible();
  await page.getByTestId("confirm-job-cancel").click();
  await expect(page.getByTestId("retry-job-cancel")).toBeVisible();
  await page.getByTestId("retry-job-cancel").click();
  await expect(page.getByTestId("job-status-announcement")).toHaveText("取消已请求，等待服务端确认");
  await expect(page.locator(".backtest-job-status__notice").filter({ hasText: "取消已请求，等待服务端确认" })).toBeVisible();
  expect(intents).toHaveLength(2); expect(intents[0]?.key).toBeTruthy(); expect(intents[1]).toEqual(intents[0]);
  expect(intents[0]?.body).toEqual({ jobId: JOB_ID });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  expectCleanAudit(audit); await page.close();
});

test("run filters use inclusive coverage dates without technical lookup conditions", async ({ browser }, testInfo) => {
  const { audit, page } = await openPage(browser);
  await openRoute(page, ROUTES[0]);
  await expect(page.getByTestId("advanced-run-filters")).toHaveCount(0);
  await expect(page.getByTestId("legacy-run-filters")).toHaveCount(0);
  await expect(page.locator("#run-filter-dataset-hash")).toHaveCount(0);
  await expect(page.locator("#run-filter-plan-version")).toHaveCount(0);
  await expect(page.locator("#run-filter-sort")).toHaveCount(0);
  await page.locator("#run-filter-end-from").fill("2026-08-28"); await page.locator("#run-filter-end-to").fill("2026-08-28");
  await page.getByTestId("apply-run-filters").click();
  await expect(page.getByTestId("backtest-run-row")).toHaveCount(1);
  await expect(page).toHaveURL(url => url.searchParams.get("eventEndFrom") === "2026-08-28" && !url.searchParams.has("completedFrom"));
  await page.locator("#run-filter-end-from").fill("2026-08-30"); await page.locator("#run-filter-end-to").fill("2026-08-30");
  await page.getByTestId("apply-run-filters").click(); await expect(page.getByTestId("backtest-run-row")).toHaveCount(0);
  await page.locator("#run-filter-end-from").fill("2026-08-28"); await page.locator("#run-filter-end-to").fill("2026-08-28");
  await page.getByTestId("apply-run-filters").focus(); await page.keyboard.press("Enter");
  await expect(page.getByTestId("backtest-run-row")).toHaveCount(1);
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator(".run-filters").screenshot({ path: testInfo.outputPath(`run-filters-${width}.png`) });
  }
  await expectNoSeriousAxeViolations(page); expectCleanAudit(audit); await page.close();
});

test("covers the four backtest routes with keyboard flows and serious axe checks", async ({
  browser,
}, testInfo) => {
  const { audit, page } = await openPage(browser);

  await openRoute(page, ROUTES[0]);
  await expect(page.getByTestId("run-detail-link")).toHaveAttribute(
    "href",
    `/backtests/${RUN_ID}`,
  );
  await expectNoSeriousAxeViolations(page);

  await openRoute(page, ROUTES[1]);
  await page.locator("#plan-version-id").selectOption(PLAN_VERSION_ID);
  await page.locator("#dataset-hash").fill(DATASET_HASH);
  await expect(page.getByTestId("reference-market-coverage")).toContainText("深证成指");
  await expect(page.getByTestId("reference-market-coverage")).toContainText(
    "entry.conditions.all[0]",
  );
  await page.getByTestId("submit-backtest-run").focus();
  const reducedMotionSeconds = await page.getByTestId("submit-backtest-run").evaluate((element) =>
    Math.max(
      ...getComputedStyle(element)
        .transitionDuration.split(",")
        .map((duration) => {
          const value = Number.parseFloat(duration);
          return duration.trim().endsWith("ms") ? value / 1_000 : value;
        }),
    ),
  );
  expect(reducedMotionSeconds).toBeLessThanOrEqual(0.000_01);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("run-form-error-summary")).toBeFocused();
  await expectNoSeriousAxeViolations(page);

  await openRoute(page, ROUTES[2]);
  await page.getByTestId("apply-dataset-filters").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByTestId("apply-dataset-filters")).toBeFocused();
  await expectNoSeriousAxeViolations(page);

  await openRoute(page, ROUTES[3]);
  await expect(page.getByTestId("result-tab-summary")).toHaveAttribute("aria-current", "page");
  await page.getByTestId("export-summary-json").focus();
  await expect(page.getByTestId("export-summary-json")).toBeFocused();
  await expectNoSeriousAxeViolations(page);

  await page.getByTestId("result-tab-market-index").click();
  await expect(page.getByRole("heading", { name: "共用指数数据" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "计划指数条件结果" })).toBeVisible();
  await expect(page.getByText("entry.conditions.all[0]", { exact: true })).toBeVisible();
  await page.locator('button[data-trade-date="2026-08-28"]').click();
  await expect(page).toHaveURL((url) =>
    url.searchParams.get("tab") === "details" && url.searchParams.get("kind") === "DECISION",
  );
  await expect(page.getByTestId("backtest-detail-row")).toContainText("399001.SZ");
  await expect(page.getByTestId("backtest-detail-row")).toContainText(
    "entry.conditions.all[0]",
  );
  await expectNoSeriousAxeViolations(page);

  expectChromeProject(testInfo);
  expectCleanAudit(audit);
  await page.close();
});

test("current research input and actual typed decision bytes work in the existing pages", async ({ browser }, testInfo) => {
  const { audit, page } = await openPage(browser);
  await openRoute(page, ROUTES[1]);
  await fillValidRunCommand(page);
  const researchInput = { schema_version: "unified-research-input-v1", started_at: "2026-08-24T09:00:00+08:00",
    inventory_known: true, operations: [], review: {content_hash: "a".repeat(64), confirmed: true,
      reviewed_at: "2026-10-03T12:00:00+08:00", evidence: "Synthetic reviewed research fixture"} };
  await page.getByLabel("统一计划研究输入 JSON").fill(JSON.stringify(researchInput));
  await page.getByTestId("submit-backtest-run").click();
  await expect(page).toHaveURL(`${baseUrl}/backtests/${RUN_ID}?tab=summary`, {timeout: 7000});
  expect(audit.runSubmissions[0]?.body).toMatchObject({researchInput});
  await page.route(`${baseUrl}/api/v1/backtest-runs/${RUN_ID}/details?**`, async (route) => {
    await fulfillJson(route, { ...decisionDetails, items: [{...researchDecision, runId: RUN_ID}] });
  });
  await page.goto(`${baseUrl}/backtests/${RUN_ID}?tab=details&kind=DECISION`);
  await expect(page.getByTestId("backtest-detail-row")).toContainText("计划 100 股 / 可执行 100 股");
  await expect(page.getByTestId("backtest-detail-row")).toContainText("数据阻断");
  await expectNoSeriousAxeViolations(page);
  expectChromeProject(testInfo);
  expectCleanAudit(audit);
  await page.close();
});

test("submits a complete new run and follows the authoritative job to its result", async ({
  browser,
}, testInfo) => {
  const { audit, page } = await openPage(browser);

  await openRoute(page, ROUTES[1]);
  await fillValidRunCommand(page);
  await expect(page.getByTestId("reference-market-coverage")).toContainText("深证成指");
  const submissionResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/backtest-runs",
  );
  await page.getByTestId("submit-backtest-run").click();
  const acceptedResponse = await submissionResponse;

  expect(acceptedResponse.status()).toBe(202);
  expect(await acceptedResponse.headerValue("location")).toBe(
    `/api/v1/backtest-jobs/${JOB_ID}`,
  );
  expect(await acceptedResponse.headerValue("retry-after")).toBe("2");
  expect(acceptedResponse.request().headers()["content-type"]).toBe("application/json");
  await expect(page).toHaveURL(`${baseUrl}/backtests/${RUN_ID}?jobId=${JOB_ID}`);
  await expect(page.getByTestId("backtest-job-status")).toHaveAttribute(
    "data-status",
    "RUNNING",
  );
  await expect(page).toHaveURL(`${baseUrl}/backtests/${RUN_ID}?tab=summary`, {
    timeout: 7_000,
  });
  await expect(page.getByRole("heading", { level: 2, name: "结果审阅" })).toBeVisible();

  expect(audit.requestTotals.get("POST /api/v1/backtest-runs")).toBe(1);
  expect(audit.runSubmissions).toHaveLength(1);
  expect(audit.runSubmissions[0]?.body).toEqual({
    datasetHash: DATASET_HASH,
    eventRiskAssumption: "NO_EVENT_RISK",
    executionConfig: {
      buySlippageBps: "2.5",
      commissionRate: "0.0003",
      minimumCommissionFen: 500,
      sellSlippageBps: "3.75",
      stampDutyRate: "0.001",
      transferFeeRate: "0.00001",
    },
    initialCashFen: 10_000_000,
    initialLots: [],
    planVersionId: PLAN_VERSION_ID,
  });
  expect(audit.runSubmissions[0]?.idempotencyKey).toMatch(/^[A-Za-z0-9._:-]{1,128}$/);
  expect(audit.jobRequestTimes).toHaveLength(2);
  expectChromeProject(testInfo);
  expectCleanAudit(audit);
  await page.close();
});

test("keeps 320/768/1024/1440 layouts and 200 percent text inside route boundaries", async ({
  browser,
}, testInfo) => {
  const { audit, page } = await openPage(browser, 320);

  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ height: 900, width });
    for (const route of ROUTES) {
      await openRoute(page, route);
      await expect(page.locator(route.viewSelector)).toHaveCSS("display", "grid");
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
      });
      await page.evaluate(async () => {
        await document.fonts.ready;
        await new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        );
      });
      const sizes = await page.evaluate(() => {
        const clientWidth = document.documentElement.clientWidth;
        const overflow = [...document.querySelectorAll<HTMLElement>("body *")]
          .map((element) => ({
            left: Math.round(element.getBoundingClientRect().left),
            name: `${element.tagName.toLowerCase()}.${element.className}`,
            right: Math.round(element.getBoundingClientRect().right),
          }))
          .filter((element) => element.left < 0 || element.right > clientWidth)
          .slice(0, 5);
        return {
          clientWidth,
          fontSize: getComputedStyle(document.documentElement).fontSize,
          overflow,
          scrollWidth: document.documentElement.scrollWidth,
        };
      });
      expect(sizes.fontSize).toBe("32px");
      expect(
        sizes.scrollWidth,
        `${route.path} overflow at ${width}px and 200% text: ${JSON.stringify(sizes.overflow)}`,
      ).toBeLessThanOrEqual(sizes.clientWidth);
    }
  }

  expectChromeProject(testInfo);
  expectCleanAudit(audit);
  await page.close();
});

test("R13 records immediate and settled narrow backtest layout without changing its gate", async ({ browser }, testInfo) => {
  const { audit, page } = await openPage(browser, 320);
  const measurements: unknown[] = [];
  const measure = () => page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    fontStatus: document.fonts.status,
    activeElement: `${document.activeElement?.tagName}.${document.activeElement?.className}`,
    scrollContainers: [...document.querySelectorAll<HTMLElement>('body *')].filter(element => element.scrollWidth > element.clientWidth).map(element => ({
      element: `${element.tagName}.${element.className}`,
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      left: element.getBoundingClientRect().left,
      right: element.getBoundingClientRect().right,
      overflowX: getComputedStyle(element).overflowX,
    })),
    overflow: [...document.querySelectorAll<HTMLElement>('body *')].map(element => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      let scroller: string | null = null;
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        if (['auto', 'scroll', 'hidden', 'clip'].includes(getComputedStyle(parent).overflowX)) {
          scroller = `${parent.tagName}.${parent.className}`;
          break;
        }
      }
      return { element: `${element.tagName}.${element.className}`, left: rect.left, right: rect.right, width: rect.width, overflowX: style.overflowX, scroller };
    }).filter(element => element.left < 0 || element.right > document.documentElement.clientWidth),
  }));
  for (const [index, route] of ROUTES.entries()) {
    await openRoute(page, route);
    await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    const immediate = await measure();
    await page.evaluate(async () => {
      await document.fonts.ready;
      await new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done())));
    });
    const settled = await measure();
    measurements.push({route: route.path, immediate, settled});
    await page.screenshot({path: testInfo.outputPath(`layout-${index}.png`), fullPage: true});
  }
  await testInfo.attach('layout-measurements', {body: JSON.stringify(measurements, null, 2), contentType: 'application/json'});
  expectCleanAudit(audit);
  await page.close();
});

test("enforces request, DOM, polling, and pre-equity ECharts bounds", async ({ browser }, testInfo) => {
  const { audit, page } = await openPage(browser);

  await openRoute(page, ROUTES[0]);
  expect(await page.getByTestId("backtest-run-row").count()).toBeLessThanOrEqual(100);
  await openRoute(page, ROUTES[1]);
  await openRoute(page, ROUTES[2]);
  await openRoute(page, ROUTES[3]);
  expect(audit.chartRequests).toEqual([]);

  await page.getByTestId("result-tab-equity").click();
  await expect(page.getByTestId("backtest-equity-chart")).toBeVisible();
  await expect(page.getByRole("region", { name: "完整权益序列表格" })).toBeVisible();
  expect(await page.getByTestId("backtest-equity-row").count()).toBeLessThanOrEqual(2_000);
  expect(audit.chartRequests.length).toBeGreaterThan(0);

  await page.goto(`${baseUrl}/backtests/${RUN_ID}?jobId=${JOB_ID}`);
  await expect.poll(() => audit.jobRequestTimes.length, { timeout: 7_000 }).toBe(2);
  await expect(page.getByRole("heading", { level: 2, name: "结果审阅" })).toBeVisible();
  expect(audit.jobRequestTimes[1]! - audit.jobRequestTimes[0]!).toBeGreaterThanOrEqual(1_900);
  const terminalRequestCount = audit.jobRequestTimes.length;
  await page.waitForTimeout(2_200);
  expect(audit.jobRequestTimes).toHaveLength(terminalRequestCount);

  audit.jobRequestTimes.length = 0;
  await page.goto(`${baseUrl}/backtests/${RUN_ID}?jobId=${JOB_ID}`);
  await expect.poll(() => audit.jobRequestTimes.length).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(2_200);
  expect(audit.jobRequestTimes).toHaveLength(1);

  audit.jobRequestTimes.length = 0;
  await page.goto(`${baseUrl}/backtests/${RUN_ID}?jobId=${JOB_ID}`);
  await expect.poll(() => audit.jobRequestTimes.length).toBe(1);
  await openRoute(page, ROUTES[0]);
  await page.waitForTimeout(2_200);
  expect(audit.jobRequestTimes).toHaveLength(1);

  expectChromeProject(testInfo);
  expectCleanAudit(audit);
  await page.close();
});
