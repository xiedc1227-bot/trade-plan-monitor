import { expect, test } from "@playwright/test";
import type { Route } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

const symbol = "003043.SZ";
const observedAt = "2026-08-24T10:05:05.000000+08:00";
const detail = {
  positionLots: [],
  summary: {
    connected: false,
    decision: {
      dataAgeSeconds: null,
      dataHealth: {
        dataAgeSeconds: null,
        fresh: false,
        latestBarEnd: null,
        requiredDataComplete: false,
        status: "DEGRADED",
      },
      episodeLowFen: null,
      episodeStatus: null,
      evaluatedAt: observedAt,
      marketDataAt: null,
      nextStep: { code: "WAIT_FOR_REQUIRED_DATA" },
      planHash: "a".repeat(64),
      planId: "plan-1",
      planVersion: 1,
      position: {
        coreQuantity: 0,
        sellableCoreQuantity: 0,
        sellableTacticalQuantity: 0,
        tacticalQuantity: 0,
        totalQuantity: 0,
      },
      priceFen: null,
      resultHash: "b".repeat(64),
      riskBreachTradeDate: null,
      riskStatus: "CLEAR",
      signalType: "WAIT",
      symbol,
      zone: "UNKNOWN",
    },
    name: "华亚智能",
    observedAt,
    riskDistanceFen: null,
    satisfiedConditionCount: 0,
    symbol,
    totalConditionCount: 0,
  },
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
    throw new Error("Vite symbol-detail harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

test("reads backend detail, bars, and events for an explicit Shanghai history range", async ({ page }) => {
  const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  await page.route("**/api/v1/**", async (route) => fulfillApi(route, ranges));

  await page.goto(`${baseUrl}/stocks/${symbol}`);
  await expect(page.getByRole("heading", { level: 1, name: "华亚智能 · 003043.SZ" })).toBeVisible();
  await expect.poll(() => ranges.length).toBe(2);
  expect(ranges).toEqual([
    { endAt: observedAt, startAt: "2026-08-24T00:00:00.000000+08:00" },
    { endAt: observedAt, startAt: "2026-08-24T00:00:00.000000+08:00" },
  ]);

  const startAt = "2026-08-22T09:30:00.000000+08:00";
  const endAt = "2026-08-22T15:00:00.000000+08:00";
  await page.locator("#symbol-history-start-at").fill(startAt);
  await page.locator("#symbol-history-end-at").fill(endAt);
  await page.getByRole("button", { name: "查询历史" }).click();

  await expect.poll(() => ranges.length).toBe(4);
  expect(ranges.slice(-2)).toEqual([
    { endAt, startAt },
    { endAt, startAt },
  ]);
});

async function fulfillApi(
  route: Route,
  ranges: Array<{ endAt: string | null; startAt: string | null }>,
): Promise<void> {
  const url = new URL(route.request().url());
  if (url.pathname === `/api/v1/symbols/${symbol}`) {
    await route.fulfill({ body: JSON.stringify(detail), contentType: "application/json" });
    return;
  }
  if (
    url.pathname === `/api/v1/symbols/${symbol}/bars` ||
    url.pathname === `/api/v1/symbols/${symbol}/events`
  ) {
    ranges.push({ endAt: url.searchParams.get("endAt"), startAt: url.searchParams.get("startAt") });
    await route.fulfill({
      body: JSON.stringify({
        endAt: url.searchParams.get("endAt"),
        items: [],
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
        startAt: url.searchParams.get("startAt"),
        total: 0,
      }),
      contentType: "application/json",
    });
    return;
  }
  await route.fulfill({
    body: JSON.stringify({
      error: { code: "SERVICE_UNAVAILABLE", details: [], message: "unavailable", requestId: "a".repeat(32) },
    }),
    contentType: "application/json",
    status: 503,
  });
}
