import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type { RuntimeHealthResponse } from "../../src/api/generated";
import { expect, test } from "./fixtures";

const fingerprint = "a".repeat(64);
const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");
const health: RuntimeHealthResponse = {
  blockReason: "LEGACY_PLANS_REQUIRE_REVIEW",
  cooldownUntil: null,
  database: {
    errorCode: null,
    lastBackupAt: null,
    lastCheckpointAt: null,
    status: "READY",
    walStatus: "READY",
  },
  delivery: {
    errorCode: null,
    failedCount: 0,
    lastDeliveredAt: null,
    nextRetryAt: null,
    pendingCount: 0,
    status: "UNVERIFIED",
  },
  executor: { activeCount: 0, maxWorkers: 1, waitingCount: 0 },
  gaps: [],
  lastCompletedMinute: null,
  lastCompletedMinuteAgeSeconds: null,
  latestEvaluationAgeSeconds: null,
  latestEvaluationAt: null,
  nextPollAt: null,
  nextRetryAt: null,
  observedAt: "2026-09-23T10:00:00+08:00",
  providers: [],
  readOnly: true,
  startedAt: "2026-09-23T10:00:00+08:00",
  status: "BLOCKED",
  stoppedAt: null,
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
    throw new Error("legacy maintenance browser harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => { await server.close(); });

test("system page previews and separately confirms missing-heartbeat invalidation", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const submitted: unknown[] = [];
  await page.route(`${baseUrl}/api/v1/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "GET" && path === "/api/v1/health") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(health) });
      return;
    }
    if (request.method() === "GET" && path === "/api/v1/dashboard") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        availability: "UNAVAILABLE", observedAt: health.observedAt,
        reason: "NO_ACTIVE_PLANS", sequence: 0,
      }) });
      return;
    }
    if (request.method() === "GET" && path === "/api/v1/system/legacy-plan-invalidation") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        available: true,
        fingerprint,
        plans: [{ symbol: "600000.SH", planVersionId: "plan-v1", revision: 1 }],
      }) });
      return;
    }
    if (request.method() === "POST" && path === "/api/v1/system/legacy-plan-invalidation") {
      submitted.push(request.postDataJSON());
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        restartRequired: true, symbols: ["600000.SH"],
      }) });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });

  await page.goto(`${baseUrl}/system`);
  await expect(page.getByRole("heading", { level: 1, name: "系统健康" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "旧计划缺少运行时间记录" })).toBeVisible();
  await expect(page.getByTestId("legacy-plan-list")).toContainText("600000.SH");
  await expect(page.getByTestId("market-status-strip")).toContainText("受阻");
  const screenshot = await page.screenshot({
    path: join(tmpdir(), "trade-plan-monitor-legacy-maintenance-preview.png"),
  });
  await testInfo.attach("legacy-maintenance-preview", { body: screenshot, contentType: "image/png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
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

  await page.getByTestId("open-legacy-confirmation").click();
  const confirm = page.getByTestId("confirm-legacy-invalidation");
  await expect(confirm).toBeDisabled();
  await page.getByRole("checkbox", { name: "我已核对清单，确认作废这些旧计划" }).check();
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page.getByText("已作废所列旧计划。请重启监控工具，确认健康状态正常后再新建计划。"))
    .toBeVisible();
  expect(submitted).toEqual([{ fingerprint, confirmation: "INVALIDATE_LEGACY_PLANS" }]);
});
