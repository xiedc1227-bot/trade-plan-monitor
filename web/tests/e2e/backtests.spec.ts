import { createRequire } from "node:module";

import { expect, test } from "@playwright/test";
import type { Browser, Page, Route, TestInfo } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type {
  BacktestDatasetPage,
  BacktestEquitySeries,
  BacktestJobView,
  BacktestRunPage,
  BacktestRunSummaryView,
  BacktestRunView,
  DashboardResponse,
} from "../../src/api/generated";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const RUN_ID = "a".repeat(64);
const DATASET_HASH = "d".repeat(64);
const JOB_ID = "e2e-run-job-001";
const TIME = "2026-08-30T10:00:00.000000+08:00";
const ROUTES = [
  { heading: "回测运行记录", path: "/backtests", readyTestId: "run-detail-link" },
  { heading: "创建回测", path: "/backtests/new", readyTestId: "submit-backtest-run" },
  {
    heading: "历史数据管理",
    path: "/backtests/data?symbols=000001.SZ&start=2026-08-01&end=2026-08-28&warmupStart=2026-07-01",
    readyTestId: "request-dataset-sync",
  },
  {
    heading: "回测结果",
    path: `/backtests/${RUN_ID}`,
    readyTestId: "result-tab-summary",
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
  dataAgeSeconds: 0,
  observedAt: TIME,
  sequence: 1,
  symbols: [],
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
  planVersionId: "123e4567-e89b-42d3-a456-426614174000",
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
  planVersionId: runView.planVersionId,
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
      schemaVersion: "backtest-dataset-v1",
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

test.beforeAll(async () => {
  server = await createServer({
    clearScreen: false,
    logLevel: "silent",
    root: process.cwd(),
    server: { host: "127.0.0.1", port: 0 },
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
    unexpectedRequests: [],
  };
}

async function fulfillJson(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json; charset=utf-8",
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
    if (/echarts|BacktestEquityChart/i.test(request.url())) {
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
      } else if (key === "GET /api/v1/backtest-runs") {
        await fulfillJson(route, runPage);
      } else if (key === "GET /api/v1/backtest-datasets") {
        await fulfillJson(route, datasetPage);
      } else if (key === `GET /api/v1/backtest-runs/${RUN_ID}/equity-series`) {
        await fulfillJson(route, equitySeries);
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
  await page.goto(`${baseUrl}${route.path}`);
  await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
  await expect(page.getByTestId(route.readyTestId)).toBeVisible();
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

function expectChromiumProject(testInfo: TestInfo): void {
  expect(testInfo.project.name).toBe("chromium");
}

function expectCleanAudit(audit: BrowserAudit): void {
  expect(audit.apiFailures).toEqual([]);
  expect(audit.consoleFailures).toEqual([]);
  expect(audit.externalRequests).toEqual([]);
  expect(audit.requestFailures).toEqual([]);
  expect(audit.unexpectedRequests).toEqual([]);
  expect([...audit.maxInFlight.values()].every((maximum) => maximum <= 1)).toBe(true);
}

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
  await page.getByTestId("request-dataset-sync").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "确认联网同步历史数据" })).toBeVisible();
  await expect(page.getByTestId("confirm-dataset-sync")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "确认联网同步历史数据" })).toBeHidden();
  await expectNoSeriousAxeViolations(page);

  await openRoute(page, ROUTES[3]);
  await expect(page.getByTestId("result-tab-summary")).toHaveAttribute("aria-current", "page");
  await page.getByTestId("export-summary-json").focus();
  await expect(page.getByTestId("export-summary-json")).toBeFocused();
  await expectNoSeriousAxeViolations(page);

  expectChromiumProject(testInfo);
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
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
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
        return { clientWidth, overflow, scrollWidth: document.documentElement.scrollWidth };
      });
      expect(
        sizes.scrollWidth,
        `${route.path} overflow at ${width}px and 200% text: ${JSON.stringify(sizes.overflow)}`,
      ).toBeLessThanOrEqual(sizes.clientWidth);
    }
  }

  expectChromiumProject(testInfo);
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

  expectChromiumProject(testInfo);
  expectCleanAudit(audit);
  await page.close();
});
