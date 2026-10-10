import { createServer, type ViteDevServer } from "vite";
import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures";
import { emptyDashboard, runtimeHealth } from "../fixtures/runtimeStatus";
import { overviewFixture } from "../fixtures/indexOverview";

let server: ViteDevServer;
let origin: string;

test.beforeAll(async () => {
  server = await createServer({ configFile: "vite.config.ts", logLevel: "silent",
    server: { host: "127.0.0.1", port: 0, hmr: false } });
  await server.listen();
  const address = server.httpServer?.address();
  if (!address || typeof address === "string") throw new Error("Missing isolated UI port");
  origin = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => { await server.close(); });

async function prepare(page: Page, overview: ReturnType<typeof overviewFixture>): Promise<void> {
  const dashboard = emptyDashboard();
  const health = runtimeHealth();
  dashboard.observedAt = overview.observedAt;
  health.observedAt = overview.observedAt;
  overview.runtimeGeneration = dashboard.runtimeGeneration;
  overview.sequence = dashboard.sequence;
  await page.route(`${origin}/api/v1/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    expect(route.request().method()).toBe("GET");
    expect(["/api/v1/dashboard", "/api/v1/health", "/api/v1/market-indexes/overview"]).toContain(path);
    await route.fulfill({ json: path.endsWith("/health") ? health : path.endsWith("/overview") ? overview : dashboard,
      headers: { "X-Monitor-Contract-Version": "2" } });
  });
  await page.routeWebSocket(`${origin.replace("http:", "ws:")}/ws/v1/monitor**`, socket => {
    socket.send(JSON.stringify({ type: "heartbeat", monitorContractVersion: 2,
      observedAt: dashboard.observedAt, runtimeGeneration: dashboard.runtimeGeneration,
      sequence: dashboard.sequence, runtimeStatus: dashboard.runtimeStatus }));
  });
}

test("closed SSE uses the same 48 bars and point after a failed later acquisition", async ({ page }) => {
  const overview = overviewFixture();
  let chartModule = "";
  page.on("request", request => { if (request.url().includes("/echarts_core.js")) chartModule = request.url(); });
  await prepare(page, overview);
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(origin);
    const card = page.getByTestId("market-index-trend-card");
    await expect(card.getByRole("heading", { name: "上证指数", exact: true })).toBeVisible();
    await expect(page.getByTestId("market-index-health")).toContainText("已收市");
    await expect(card).not.toContainText("阻断");
    await expect(card).toContainText("3813.79");
    await expect(card).toContainText("最近更新失败，保留已取得行情");
    await expect(card.getByRole("img")).toHaveAttribute("aria-label", /最新点位 3813.791.*15:00.*已收市/);
    await expect.poll(async () => {
      if (!chartModule) return null;
      return page.evaluate(async url => {
        const core = await import(url);
        const element = document.querySelector(".market-index-sparkline");
        const chart = element ? core.getInstanceByDom(element) : null;
        if (!chart) return null;
        const option = chart.getOption();
        const data = option.series[0].data;
        return { count: data.length, last: data.at(-1), at: option.xAxis[0].data.at(-1) };
      }, chartModule);
    }).toEqual({ count: 49, last: 3813.791, at: "2026-10-09T15:00:00+08:00" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await expect(card.locator(".market-index-trend-card__health-symbol--live")).toHaveCount(0);
  }
  const selector = page.getByRole("button", { name: /深证成指/ });
  await selector.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("market-index-trend-card").getByRole("heading", { name: "深证成指" })).toBeVisible();
});

test("missing close retains partial data and makes the closed session explicit", async ({ page }) => {
  const overview = overviewFixture();
  const index = overview.indexes[0]!;
  index.dataStatus = "INCOMPLETE";
  index.data!.bars.pop();
  index.data!.completedBucketAt = index.data!.bars.at(-1)!.barAt;
  await prepare(page, overview);
  await page.goto(origin);
  await expect(page.getByTestId("market-index-health")).toContainText("已收市 · 数据待补齐");
  await expect(page.getByTestId("market-index-trend-card").getByRole("img")).toHaveAttribute("aria-label", /14:55/);
  await expect(page.getByTestId("market-index-trend-card")).toContainText("3813.79");
});
