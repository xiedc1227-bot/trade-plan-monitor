import { createRequire } from "node:module";

import { expect, test } from "./fixtures";
import type { Page, TestInfo } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type { DashboardResponse, RuntimeHealthResponse } from "../../src/api/generated";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");

const health: RuntimeHealthResponse = {
  cooldownUntil: "2026-08-24T10:05:00+08:00",
  database: {
    errorCode: null,
    lastBackupAt: "2026-08-24T08:00:00+08:00",
    lastCheckpointAt: "2026-08-24T09:50:00+08:00",
    status: "READY",
    walStatus: "READY",
  },
  delivery: {
    errorCode: "WEBHOOK_TRANSIENT",
    failedCount: 1,
    lastDeliveredAt: "2026-08-24T09:54:00+08:00",
    nextRetryAt: "2026-08-24T10:01:00+08:00",
    pendingCount: 2,
    status: "DEGRADED",
  },
  executor: { activeCount: 1, maxWorkers: 2, waitingCount: 3 },
  gaps: [{ barEnd: "2026-08-24T09:58:00+08:00", symbol: "600000.SH" }],
  lastCompletedMinute: "2026-08-24T09:59:00+08:00",
  lastCompletedMinuteAgeSeconds: 60,
  latestEvaluationAgeSeconds: 300,
  latestEvaluationAt: "2026-08-24T09:55:00+08:00",
  nextPollAt: "2026-08-24T10:00:12+08:00",
  nextRetryAt: "2026-08-24T10:01:00+08:00",
  observedAt: "2026-08-24T10:00:00+08:00",
  providers: [
    {
      capability: "realtime_minutes",
      checkedAt: "2026-08-24T09:59:00+08:00",
      errorCode: "RATE_LIMITED",
      latencyMs: 125,
      nextRetryAt: "2026-08-24T10:01:00+08:00",
      status: "RATE_LIMITED",
    },
  ],
  readOnly: true,
  startedAt: "2026-08-24T09:00:00+08:00",
  status: "DEGRADED",
  stoppedAt: null,
};

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
  observedAt: health.observedAt,
  runtimeGeneration: "00000000-0000-4000-8000-000000000001",
  sequence: 1,
  symbols: [],
};

let server: ViteDevServer;
let baseUrl: string;

test.beforeAll(async () => {
  server = await createServer({
    clearScreen: false,
    logLevel: "silent",
    root: process.cwd(),
    server: { hmr: false, host: "127.0.0.1", port: 0 },
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (address === null || address === undefined || typeof address === "string") {
    throw new Error("Vite accessibility harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

test("loads system health through the production /system route", async ({ page }, testInfo) => {
  const consoleFailures: string[] = [];
  const externalRequests: string[] = [];
  const requestFailures: string[] = [];
  const chartRequests: string[] = [];
  const unexpectedRequests: string[] = [];
  let healthRequests = 0;
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      consoleFailures.push(`${message.type()}:${message.text()}`);
    }
  });
  page.on("request", (request) => {
    if (/PriceChart|BacktestEquityChart|installCanvasRenderer|echarts/i.test(request.url())) {
      chartRequests.push(request.url());
    }
    const requestUrl = new URL(request.url());
    if (
      (requestUrl.protocol === "http:" || requestUrl.protocol === "https:") &&
      requestUrl.host !== new URL(baseUrl).host
    ) {
      externalRequests.push(request.url());
    }
  });
  page.on("requestfailed", (request) => {
    requestFailures.push(`${request.method()} ${request.url()}`);
  });
  await page.route(`${baseUrl}/api/v1/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/health") {
      healthRequests += 1;
      await route.fulfill({
        body: JSON.stringify(health),
        contentType: "application/json; charset=utf-8",
        status: 200,
      });
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/dashboard") {
      await route.fulfill({
        body: JSON.stringify(dashboard),
        contentType: "application/json; charset=utf-8",
        status: 200,
      });
      return;
    }
    unexpectedRequests.push(`${request.method()} ${url.pathname}`);
    await route.fulfill({ body: "unexpected request", status: 500 });
  });

  await page.goto(`${baseUrl}/system`);
  await expect(page.getByRole("heading", { level: 1, name: "系统健康" })).toBeVisible();
  await expect(page).toHaveTitle("系统健康 · Trade Plan Monitor");
  expect(healthRequests).toBe(1);
  expect(consoleFailures).toEqual([]);
  expect(externalRequests).toEqual([]);
  expect(requestFailures).toEqual([]);
  expect(unexpectedRequests).toEqual([]);
  expect(chartRequests).toEqual([]);
  expectChromeProject(testInfo);
});

async function openProductionSystemRoute(page: Page) {
  await page.unroute(`${baseUrl}/api/v1/**`);
  await page.route(`${baseUrl}/api/v1/**`, async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "GET" && url.pathname === "/api/v1/health") {
      await route.fulfill({
        body: JSON.stringify(health),
        contentType: "application/json; charset=utf-8",
        status: 200,
      });
      return;
    }
    if (route.request().method() === "GET" && url.pathname === "/api/v1/dashboard") {
      await route.fulfill({
        body: JSON.stringify(dashboard),
        contentType: "application/json; charset=utf-8",
        status: 200,
      });
      return;
    }
    await route.fulfill({ body: "unexpected request", status: 500 });
  });
  await page.goto(`${baseUrl}/system`);
  await expect(page.getByRole("heading", { level: 1, name: "系统健康" })).toBeVisible();
}

async function openSystemPage(page: Page, width: number) {
  await page.setViewportSize({ height: 900, width });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openProductionSystemRoute(page);
  return page;
}

function expectChromeProject(testInfo: TestInfo): void {
  expect(testInfo.project.name).toBe("chrome");
}

test("has no WCAG 2.1 A/AA axe violations", async ({ page }, testInfo) => {
  await openSystemPage(page, 1024);
  await page.addScriptTag({ path: axePath });
  const violations = await page.evaluate(async () => {
    const axe = (globalThis as typeof globalThis & {
      axe: { run: (root: Document, options: object) => Promise<{ violations: unknown[] }> };
    }).axe;
    const result = await axe.run(document, {
      runOnly: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    });
    return result.violations;
  });

  expect(violations).toEqual([]);
  expectChromeProject(testInfo);
});

test("fits 320, 768, 1024, and 1440 pixel layouts without horizontal overflow", async ({
  page,
}, testInfo) => {
  for (const width of [320, 768, 1024, 1440]) {
    await openSystemPage(page, width);
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    const sizes = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(sizes.scrollWidth, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(
      sizes.clientWidth,
    );
  }
  expectChromeProject(testInfo);
});

test("keeps native keyboard order, visible focus, semantic state, and reduced motion", async ({
  page,
}, testInfo) => {
  await openSystemPage(page, 320);

  await page.getByTestId("refresh-system-health").focus();
  await expect(page.getByTestId("refresh-system-health")).toBeFocused();
  const focusOutline = await page.getByTestId("refresh-system-health").evaluate((element) =>
    getComputedStyle(element).outlineStyle,
  );
  expect(focusOutline).not.toBe("none");

  await page.keyboard.press("Tab");
  await expect(page.getByTestId("provider-table-scroll")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("gap-table-scroll")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("health-gap-link")).toBeFocused();
  await expect(page.getByTestId("market-status-strip")).toHaveAttribute("aria-live", "polite");
  await expect(page.getByTestId("market-status-strip")).toContainText("▲");
  await expect(page.getByTestId("market-status-strip")).toContainText("降级");

  const motionSeconds = await page.getByTestId("refresh-system-health").evaluate((element) => {
    const duration = getComputedStyle(element).transitionDuration;
    const numeric = Number.parseFloat(duration);
    return duration.endsWith("ms") ? numeric / 1_000 : numeric;
  });
  expect(motionSeconds).toBeLessThanOrEqual(0.000_01);
  expectChromeProject(testInfo);
});
