import { createRequire } from "node:module";

import { expect, test } from "./fixtures";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type {
  DashboardProjectionUnavailableResponse,
  DashboardResponse,
} from "../../src/api/generated";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");

const dashboard: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: { actionable: 0, blocked: 0, lowZoneWatch: 2, normal: 0, risk: 0, stale: 0 },
  marketIndexes: [
    {
      board: "SSE_MAIN",
      closePoints: "3400.12",
      completedBucketAt: "2026-09-02T10:35:00+08:00",
      displayName: "上证指数",
      health: "LIVE",
      indexCode: "000001.SH",
      indicatorFacts: [],
      issues: [],
      mappedSymbolCount: 0,
      mappingVersion: "board-index-map-v1",
      observedAt: "2026-09-02T10:35:02+08:00",
      priorClosePoints: "3388.10",
      revision: 43,
      sessionChangeRatio: "0.003547",
      snapshotHash: "f".repeat(64),
    },
    {
      board: "STAR_MARKET",
      closePoints: "1234.56",
      completedBucketAt: "2026-09-02T10:35:00+08:00",
      displayName: "科创50",
      health: "LIVE",
      indexCode: "000688.SH",
      indicatorFacts: [],
      issues: [],
      mappedSymbolCount: 2,
      mappingVersion: "board-index-map-v1",
      observedAt: "2026-09-02T10:35:02+08:00",
      priorClosePoints: "1220.11",
      revision: 42,
      sessionChangeRatio: "0.011843",
      snapshotHash: "a".repeat(64),
    },
    {
      board: "SZSE_MAIN", closePoints: "10800.24", completedBucketAt: "2026-09-02T10:35:00+08:00",
      displayName: "深证成指", health: "LIVE", indexCode: "399001.SZ", indicatorFacts: [], issues: [],
      mappedSymbolCount: 0, mappingVersion: "board-index-map-v1", observedAt: "2026-09-02T10:35:02+08:00",
      priorClosePoints: "10788.20", revision: 44, sessionChangeRatio: "-0.001116", snapshotHash: "b".repeat(64),
    },
    {
      board: "CHINEXT", closePoints: "2210.11", completedBucketAt: "2026-09-02T10:35:00+08:00",
      displayName: "创业板指", health: "LIVE", indexCode: "399006.SZ", indicatorFacts: [], issues: [],
      mappedSymbolCount: 0, mappingVersion: "board-index-map-v1", observedAt: "2026-09-02T10:35:02+08:00",
      priorClosePoints: "2200.10", revision: 45, sessionChangeRatio: "0", snapshotHash: "c".repeat(64),
    },
  ],
  marketTurnover: {
    benchmarkCodes: ["000001.SH", "399107.SZ"],
    changeAmount: "-210700000000",
    completedBucketAt: "2026-09-02T10:35:00+08:00",
    currentAmount: "1660000000000",
    estimateMethod: "LINEAR_COMPLETED_FIVE_MINUTE_BUCKETS",
    estimatedFullDayAmount: "1880000000000",
    previousAmount: "1870700000000",
  },
  observedAt: "2026-09-02T10:35:02+08:00",
  runtimeGeneration: "00000000-0000-4000-8000-000000000001",
  sequence: 7,
  symbols: [
    {
      connected: true,
      decision: {
        dataAgeSeconds: 2,
        dataHealth: {
          dataAgeSeconds: 2,
          fresh: true,
          latestBarEnd: "2026-09-02T10:35:00+08:00",
          requiredDataComplete: true,
          status: "LIVE",
        },
        episodeLowFen: 2010,
        episodeStatus: "ACTIVE",
        evaluatedAt: "2026-09-02T10:35:02+08:00",
        evidence: [],
        marketDataAt: "2026-09-02T10:35:00+08:00",
        nextStep: { code: "WATCH_LOW_ZONE" },
        planHash: "b".repeat(64),
        planId: "plan-1",
        planVersion: 1,
        position: {
          coreQuantity: 0,
          sellableCoreQuantity: 0,
          sellableTacticalQuantity: 0,
          tacticalQuantity: 0,
          totalQuantity: 0,
        },
        priceFen: 2020,
        resultHash: "c".repeat(64),
        riskBreachTradeDate: null,
        riskStatus: "CLEAR",
        signalType: "LOW_ZONE_WATCH",
        symbol: "688001.SH",
        zone: "LOW_BUY",
      },
      name: "华兴源创",
      observedAt: "2026-09-02T10:35:02+08:00",
      referenceMarket: {
        board: "STAR_MARKET",
        conditionProgress: { missing: 0, satisfied: 1, total: 2, unsatisfied: 1 },
        dataAt: "2026-09-02T10:35:00+08:00",
        displayName: "科创50",
        health: "LIVE",
        indexCode: "000688.SH",
        issues: [],
        mappingVersion: "board-index-map-v1",
        snapshotHash: "a".repeat(64),
      },
      riskDistanceFen: 120,
      satisfiedConditionCount: 1,
      symbol: "688001.SH",
      totalConditionCount: 3,
    },
  ],
};

const unavailableDashboard: DashboardProjectionUnavailableResponse = {
  availability: "UNAVAILABLE",
  observedAt: "2026-09-04T10:00:00+08:00",
  reason: "AWAITING_FIRST_EVALUATION",
  sequence: 0,
};

const firstSymbol = dashboard.symbols?.[0];
const firstReference = firstSymbol?.referenceMarket;
if (firstSymbol === undefined || firstReference === undefined || firstReference === null) {
  throw new Error("dashboard fixture requires one symbol with a reference market");
}
dashboard.symbols?.push({
  ...structuredClone(firstSymbol),
  decision: {
    ...structuredClone(firstSymbol.decision),
    planHash: "d".repeat(64),
    planId: "plan-2",
    planVersion: 2,
    resultHash: "e".repeat(64),
    symbol: "688002.SH",
  },
  name: "睿创微纳",
  referenceMarket: {
    ...structuredClone(firstReference),
    conditionProgress: { missing: 0, satisfied: 0, total: 2, unsatisfied: 2 },
  },
  satisfiedConditionCount: 0,
  symbol: "688002.SH",
});

let server: ViteDevServer;
let baseUrl: string;

interface BrowserAudit {
  readonly consoleFailures: string[];
  readonly failedRequests: string[];
}

const browserAudits = new WeakMap<import("@playwright/test").Page, BrowserAudit>();

test.beforeEach(async ({ page }) => {
  const audit: BrowserAudit = { consoleFailures: [], failedRequests: [] };
  browserAudits.set(page, audit);
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      audit.consoleFailures.push(`${message.type()}: ${message.text()} @ ${message.location().url}`);
    }
  });
  page.on("requestfailed", (request) => audit.failedRequests.push(request.url()));
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204 }));
  await page.route(/\/api\/v1\/plan-versions\?/, async (route) => {
    const url = new URL(route.request().url());
    expect(url.pathname).toBe("/api/v1/plan-versions");
    expect([...url.searchParams.entries()]).toEqual([
      ["offset", "0"], ["limit", "100"], ["status", "ACTIVE"],
    ]);
    await route.fulfill({
      body: JSON.stringify({ items: [], limit: 100, offset: 0, total: 0 }),
      contentType: "application/json; charset=utf-8",
      status: 200,
    });
  });
  await page.route(/\/api\/v1\/market-indexes\/[^/]+\/bars\?/, async (route) => {
    const requestUrl = new URL(route.request().url());
    const indexCode = decodeURIComponent(requestUrl.pathname.split("/")[4] ?? "");
    await route.fulfill({
      body: JSON.stringify({
        hasMore: false,
        items: [
          {
            amount: null, barAt: "2026-09-02T09:35:00+08:00", closePoints: "1231.25",
            highPoints: "1235.20", indexCode, interval: "FIVE_MINUTE",
            lowPoints: "1229.90", observedAt: "2026-09-02T10:35:02+08:00", openPoints: "1230.10",
            providerRevision: 3, sourceKind: "PROVISIONAL", volume: "1000",
          },
          {
            amount: null, barAt: "2026-09-02T10:35:00+08:00", closePoints: "1234.56",
            highPoints: "1235.20", indexCode, interval: "FIVE_MINUTE",
            lowPoints: "1229.90", observedAt: "2026-09-02T10:35:02+08:00", openPoints: "1231.25",
            providerRevision: 3, sourceKind: "PROVISIONAL", volume: "1000",
          },
        ],
        limit: 64, nextCursor: null, snapshotHash: "a".repeat(64),
      }),
      contentType: "application/json; charset=utf-8",
      status: 200,
    });
  });
});

test.afterEach(({ page }) => {
  const audit = browserAudits.get(page);
  expect(audit?.consoleFailures ?? []).toEqual([]);
  expect(audit?.failedRequests ?? []).toEqual([]);
});

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
    throw new Error("Vite dashboard harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

test("renders the authoritative dashboard and shared board-index summary at the root route", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const chartRequests: string[] = [];
  page.on("request", (request) => {
    if (/PriceChart|installCanvasRenderer|echarts/i.test(request.url())) {
      chartRequests.push(request.url());
    }
  });
  await page.route(`${baseUrl}/api/v1/dashboard`, async (route) => {
    await route.fulfill({
      body: JSON.stringify(dashboard),
      contentType: "application/json; charset=utf-8",
      status: 200,
    });
  });
  await page.route(`${baseUrl}/api/v1/symbols/688001.SH`, async (route) => {
    await route.fulfill({
      body: JSON.stringify({
        availability: "UNAVAILABLE",
        observedAt: dashboard.observedAt,
        reason: "AWAITING_FIRST_EVALUATION",
        sequence: dashboard.sequence,
        symbol: "688001.SH",
      }),
      contentType: "application/json; charset=utf-8",
      status: 200,
    });
  });

  await page.goto(baseUrl);

  await expect(page.getByRole("heading", { level: 1, name: "监控总览" })).toBeVisible();
  await expect(page.getByText("TEN-SYMBOL MONITOR")).toHaveCount(0);
  await expect(page.locator(".app-shell__connection-banner")).toBeVisible();
  const mainContent = page.locator("#main-content");
  await mainContent.focus();
  expect(
    await mainContent.evaluate((element) => getComputedStyle(element).outlineStyle),
  ).toBe("none");
  await expect(page.getByText("华兴源创")).toBeVisible();
  await expect(page.getByText("没有活动的明确规则计划。")).toBeVisible();
  await expect(page.getByTestId("market-status-strip")).toHaveCount(0);
  await expect(page.getByText("主要指数走势 · 当日")).toBeVisible();
  await expect(page.getByText("科创50").first()).toBeVisible();
  await expect(page.getByText("计划指数条件")).toBeVisible();
  await expect(page.getByTestId("market-index-selector")).toHaveCount(4);
  const selectorColor = async (name: string) => page
    .getByTestId("market-index-selector")
    .filter({ hasText: name })
    .locator("strong")
    .evaluate((element) => getComputedStyle(element).color);
  expect(await selectorColor("上证指数")).toBe("rgb(245, 139, 119)");
  expect(await selectorColor("深证成指")).toBe("rgb(135, 198, 165)");
  expect(await selectorColor("创业板指")).toBe("rgb(240, 240, 232)");
  const indexCards = page.getByTestId("market-index-trend-card");
  await expect(indexCards).toHaveCount(1);
  await expect(indexCards).toContainText("上证指数");
  await expect(indexCards).toContainText("3400.12");
  await expect(indexCards).toContainText("数据截止2026-09-02 10:35:00");
  expect(await page.getByTestId("market-index-health-symbol").evaluate(
    (element) => getComputedStyle(element).animationName,
  )).toBe("none");
  const high = indexCards.locator(".market-index-trend-card__high");
  const low = indexCards.locator(".market-index-trend-card__low");
  await expect(high).toHaveText("1235.20");
  await expect(low).toHaveText("1229.90");
  await expect(high).toHaveAttribute("data-direction", "down");
  await expect(low).toHaveAttribute("data-direction", "down");
  await expect(high).toHaveCSS("color", "rgb(135, 198, 165)");
  await expect(low).toHaveCSS("color", "rgb(135, 198, 165)");
  await expect(page.getByTestId("market-index-sparkline")).toHaveCount(1);
  const turnoverCard = page.getByTestId("market-turnover-card");
  await expect(turnoverCard).toContainText("今日累计成交额");
  await expect(turnoverCard).toContainText("1.66万亿");
  await expect(turnoverCard).toContainText("-2107亿");
  await expect(turnoverCard).toContainText("1.88万亿");
  await expect(turnoverCard).not.toContainText("线性估算");
  await expect(turnoverCard).not.toContainText("截至 2026-09-02 10:35:00");
  const countStripBox = await page.locator(".dashboard-view__counts").boundingBox();
  const toolbarBox = await page.locator(".watchlist-toolbar").boundingBox();
  expect(countStripBox).not.toBeNull();
  expect(toolbarBox).not.toBeNull();
  expect((toolbarBox?.y ?? 0) - ((countStripBox?.y ?? 0) + (countStripBox?.height ?? 0)))
    .toBeGreaterThanOrEqual(16);
  await page.getByTestId("market-index-selector").filter({ hasText: "科创50" }).click();
  await expect(indexCards).toContainText("科创50");
  await expect(page.getByTestId("market-index-health")).toContainText("实时");
  await expect(page.getByTestId("market-index-health-symbol")).toHaveText("●");
  await expect(page.getByText("查看当日点位数据")).toHaveCount(0);
  const rows = page.getByTestId("watchlist-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("满足 1");
  await expect(rows.nth(0)).toContainText("未满足 1");
  await expect(rows.nth(1)).toContainText("满足 0");
  await expect(rows.nth(1)).toContainText("未满足 2");
  await expect(rows.nth(0)).toContainText("000688.SH");
  await expect(rows.nth(1)).toContainText("000688.SH");
  expect(chartRequests.some((url) => /echarts_core|installCanvasRenderer/.test(url))).toBe(true);

  await page.getByRole("link", { name: "688001.SH" }).click();
  await expect(page).toHaveURL(/\/stocks\/688001\.SH$/);
});

test("keeps the shared-index and per-plan dashboard boundary responsive and accessible", async ({
  page,
}) => {
  await page.route(`${baseUrl}/api/v1/dashboard`, async (route) => {
    await route.fulfill({
      body: JSON.stringify(dashboard),
      contentType: "application/json; charset=utf-8",
      status: 200,
    });
  });

  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ height: 900, width });
    await page.goto(baseUrl);
    await expect(page.getByTestId("watchlist-row")).toHaveCount(2);
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    await page.evaluate(
      () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())),
    );
    const sizes = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    const overflowSources = await collectOverflowSources(page);
    expect(
      sizes.scrollWidth,
      `dashboard overflow at ${width}px: ${JSON.stringify(overflowSources)}`,
    ).toBeLessThanOrEqual(sizes.clientWidth);
  }

  await page.addScriptTag({ path: axePath });
  const seriousViolations = await page.evaluate(async () => {
    const axe = (globalThis as typeof globalThis & {
      axe: { run: (root: Document, options: object) => Promise<{ violations: { impact: string | null }[] }> };
    }).axe;
    const result = await axe.run(document, {
      runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    });
    return result.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );
  });
  expect(seriousViolations).toEqual([]);
});

test("distinguishes typed unavailable monitoring from a real disconnected service", async ({
  page,
}) => {
  let dashboardRequests = 0;
  const socketUrls: string[] = [];
  const consoleFailures: string[] = [];
  const failedRequests: string[] = [];

  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleFailures.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("requestfailed", (request) => failedRequests.push(request.url()));
  await page.route(`${baseUrl}/api/v1/dashboard`, async (route) => {
    dashboardRequests += 1;
    await route.fulfill({
      body: JSON.stringify(unavailableDashboard),
      contentType: "application/json; charset=utf-8",
      status: 200,
    });
  });
  await page.routeWebSocket(
    (url) => url.pathname === "/ws/v1/monitor",
    (socket) => socketUrls.push(socket.url()),
  );

  await page.goto(baseUrl);

  const banner = page.locator(".app-shell__connection-banner");
  await expect(banner).toHaveAttribute("data-connection-state", "UNAVAILABLE");
  await expect(banner).toContainText("服务已连接，实时监控未就绪");
  await expect(banner).not.toContainText("连接中断");
  await expect(page.getByTestId("market-index-selector")).toHaveCount(4);
  await expect(page.getByTestId("market-index-trend-card")).toHaveCount(1);
  await expect(page.getByTestId("market-index-sparkline")).toHaveCount(1);
  expect(dashboardRequests).toBeGreaterThanOrEqual(1);
  expect(socketUrls).toEqual([]);
  expect(consoleFailures).toEqual([]);
  expect(failedRequests).toEqual([]);
});

async function collectOverflowSources(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    return [...document.querySelectorAll<HTMLElement>("body *")]
      .map((element) => ({
        className: element.className,
        clientWidth: element.clientWidth,
        overflowX: getComputedStyle(element).overflowX,
        scrollWidth: element.scrollWidth,
        tagName: element.tagName,
      }))
      .filter(
        (element) =>
          element.clientWidth > viewportWidth ||
          (element.scrollWidth > element.clientWidth && element.overflowX === "visible"),
      )
      .sort((left, right) => right.scrollWidth - left.scrollWidth)
      .slice(0, 20);
  });
}

test("recovers a sequence gap with a fresh dashboard snapshot before replaying from its cursor", async ({
  page,
}) => {
  const recoveredDashboard = structuredClone(dashboard);
  const recoveredSymbol = recoveredDashboard.symbols?.[0];
  if (recoveredSymbol === undefined) {
    throw new Error("dashboard fixture must contain one symbol");
  }
  recoveredDashboard.sequence = 9;
  recoveredSymbol.name = "权威恢复后的华兴源创";

  let dashboardRequests = 0;
  let releaseRecoveredDashboard: (() => void) | undefined;
  const recoveredDashboardGate = new Promise<void>((resolve) => {
    releaseRecoveredDashboard = resolve;
  });
  const socketUrls: string[] = [];
  const sockets: Array<{ send(message: string): void; url(): string }> = [];

  await page.route(`${baseUrl}/api/v1/dashboard`, async (route) => {
    dashboardRequests += 1;
    if (dashboardRequests === 2) {
      await recoveredDashboardGate;
    }
    await route.fulfill({
      body: JSON.stringify(dashboardRequests === 1 ? dashboard : recoveredDashboard),
      contentType: "application/json; charset=utf-8",
      status: 200,
    });
  });
  await page.routeWebSocket(
    (url) => url.pathname === "/ws/v1/monitor",
    (socket) => {
      socketUrls.push(socket.url());
      sockets.push(socket);
    },
  );

  await page.goto(baseUrl);
  await expect(page.getByText("华兴源创")).toBeVisible();
  const initialSocketUrl = `${baseUrl.replace("http", "ws")}/ws/v1/monitor?after=7`;
  await expect.poll(() => socketUrls).toEqual([initialSocketUrl]);

  sockets[0]?.send(
    JSON.stringify({
      aggregateId: "688001.SH",
      eventId: "00000000-0000-0000-0000-000000000009",
      occurredAt: "2026-09-02T10:35:03+08:00",
      payload: {
        entityId: "688001.SH",
        resultHash: "d".repeat(64),
        symbol: "688001.SH",
      },
      schemaVersion: 1,
      sequence: 9,
      type: "symbol.snapshot.updated",
    }),
  );

  await expect.poll(() => dashboardRequests).toBe(2);
  await expect(page.locator('[role="status"]')).toHaveAttribute("data-connection-state", "STALE");
  expect(socketUrls).toEqual([initialSocketUrl]);
  expect(releaseRecoveredDashboard).toBeDefined();
  releaseRecoveredDashboard?.();

  await expect(page.getByText("权威恢复后的华兴源创")).toBeVisible();
  await expect.poll(() => socketUrls).toEqual([
    `${baseUrl.replace("http", "ws")}/ws/v1/monitor?after=7`,
    `${baseUrl.replace("http", "ws")}/ws/v1/monitor?after=9`,
  ]);

  sockets[1]?.send(
    JSON.stringify({
      runtimeGeneration: dashboard.runtimeGeneration,
      runtimeLive: true,
      runtimeStartedAt: "2026-08-24T09:00:00+08:00",
      sequence: 9,
      type: "heartbeat",
    }),
  );
  await expect(page.locator('[role="status"]')).toHaveAttribute("data-connection-state", "LIVE");
  await expect(page.locator(".app-shell__connection-banner")).toContainText("实时连接");
  await expect(page.getByTestId("market-status-strip")).toHaveCount(0);
});
