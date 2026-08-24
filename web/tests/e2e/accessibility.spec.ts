import { createRequire } from "node:module";

import { expect, test } from "@playwright/test";
import type { Browser, Page } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type { RuntimeHealthResponse } from "../../src/api/generated";

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

let server: ViteDevServer;
let baseUrl: string;

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
    throw new Error("Vite accessibility harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

async function mountSystemView(page: Page) {
  await page.route(`${baseUrl}/t051-accessibility`, async (route) => {
    await route.fulfill({
      body: '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>系统健康无障碍检查</title></head><body><div id="app"></div></body></html>',
      contentType: "text/html",
    });
  });
  await page.goto(`${baseUrl}/t051-accessibility`);
  await page.evaluate(async (runtimeHealth) => {
    const vuePath = "/@id/vue";
    const systemViewPath = "/src/views/SystemView.vue";
    const tokensPath = "/src/assets/tokens.css";
    const vueModule = (await import(vuePath)) as typeof import("vue");
    const systemModule = (await import(systemViewPath)) as {
      default: Parameters<typeof vueModule.createApp>[0];
    };
    await import(tokensPath);
    vueModule.createApp(systemModule.default, { health: runtimeHealth }).mount("#app");
  }, health);
  await expect(page.getByRole("heading", { level: 1, name: "系统健康" })).toBeVisible();
}

async function openSystemPage(browser: Browser, width: number) {
  const page = await browser.newPage({
    reducedMotion: "reduce",
    viewport: { height: 900, width },
  });
  await mountSystemView(page);
  return page;
}

test("has no WCAG 2.1 A/AA axe violations", async ({ browser }) => {
  const page = await openSystemPage(browser, 1024);
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
  await page.close();
});

test("fits 320, 768, 1024, and 1440 pixel layouts without horizontal overflow", async ({
  browser,
}) => {
  for (const width of [320, 768, 1024, 1440]) {
    const page = await openSystemPage(browser, width);
    const sizes = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(sizes.scrollWidth, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(
      sizes.clientWidth,
    );
    await page.close();
  }
});

test("keeps native keyboard order, visible focus, semantic state, and reduced motion", async ({
  browser,
}) => {
  const page = await openSystemPage(browser, 320);

  await page.keyboard.press("Tab");
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
  await page.close();
});
