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
const sameDayLot = {
  acquiredTradeDate: "2026-08-24",
  bucket: "CORE",
  closedAt: null,
  costFen: 6_500,
  lotId: "11111111-1111-4111-8111-111111111111",
  quantity: 100,
  relatedAlertId: null,
  remainingQuantity: 100,
  revision: 0,
  sellableQuantity: 0,
  symbol,
};

interface PositionRequests {
  closures: unknown[];
  creates: unknown[];
  reads: Array<{ asOfTradeDate: string | null; limit: string | null; offset: string | null; symbol: string | null }>;
}

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

test("submits position commands for backend-only T+1 and maximum-policy decisions", async ({ page }) => {
  const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  const positionRequests: PositionRequests = { closures: [], creates: [], reads: [] };
  await page.route("**/api/v1/**", async (route) => fulfillApi(route, ranges, positionRequests));

  await page.goto(`${baseUrl}/stocks/${symbol}`);
  await expect(page.getByRole("heading", { level: 2, name: "人工持仓批次" })).toBeVisible();
  await expect.poll(() => positionRequests.reads.length).toBe(1);
  expect(positionRequests.reads[0]).toEqual({
    asOfTradeDate: "2026-08-24",
    limit: "100",
    offset: "0",
    symbol,
  });
  await expect(page.getByTestId(`reduce-${sameDayLot.lotId}`)).toBeEnabled();

  await page.locator('input[name="createCostFen"]').fill("6500");
  await page.getByRole("button", { name: "复核建仓" }).click();
  await expect(page.getByTestId("position-confirmation")).toBeVisible();
  await page.getByTestId("confirm-position").click();

  await expect.poll(() => positionRequests.creates.length).toBe(1);
  expect(positionRequests.creates[0]).toEqual({
    acquiredTradeDate: "2026-08-24",
    bucket: "CORE",
    costFen: 6_500,
    expectedRevision: 0,
    quantity: 100,
    relatedAlertId: null,
    symbol,
  });
  await expect(page.getByRole("alert")).toHaveText(
    "后端拒绝了持仓操作，请核对最新批次和计划规则后重试",
  );

  await page.getByTestId(`reduce-${sameDayLot.lotId}`).click();
  await page.getByRole("button", { name: "复核减仓" }).click();
  await expect(page.getByTestId("position-confirmation")).toBeVisible();
  await page.getByTestId("confirm-position").click();

  await expect.poll(() => positionRequests.closures.length).toBe(1);
  expect(positionRequests.closures[0]).toEqual({
    expectedRevision: 0,
    lotId: sameDayLot.lotId,
    quantity: 100,
    tradeDate: "2026-08-24",
  });
  await expect.poll(() => positionRequests.reads.length).toBe(3);
  await expect(page.getByRole("alert")).toHaveText(
    "后端拒绝了持仓操作，请核对最新批次和计划规则后重试",
  );
  await expect(page.locator("body")).not.toContainText("backend policy detail");
  await expect(page.getByText("T+1 / 当前日期不可卖")).toBeVisible();
});

async function fulfillApi(
  route: Route,
  ranges: Array<{ endAt: string | null; startAt: string | null }>,
  positionRequests?: PositionRequests,
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
  if (url.pathname === "/api/v1/position-lots" && route.request().method() === "GET") {
    positionRequests?.reads.push({
      asOfTradeDate: url.searchParams.get("asOfTradeDate"),
      limit: url.searchParams.get("limit"),
      offset: url.searchParams.get("offset"),
      symbol: url.searchParams.get("symbol"),
    });
    await route.fulfill({
      body: JSON.stringify({
        asOfTradeDate: url.searchParams.get("asOfTradeDate"),
        items: positionRequests === undefined ? [] : [sameDayLot],
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
        symbol: url.searchParams.get("symbol"),
        total: positionRequests === undefined ? 0 : 1,
      }),
      contentType: "application/json",
    });
    return;
  }
  if (url.pathname === "/api/v1/position-lots" && route.request().method() === "POST") {
    positionRequests?.creates.push(readJsonBody(route));
    await fulfillPositionConflict(route);
    return;
  }
  if (url.pathname === "/api/v1/position-lot-closures" && route.request().method() === "POST") {
    positionRequests?.closures.push(readJsonBody(route));
    await fulfillPositionConflict(route);
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

function readJsonBody(route: Route): unknown {
  const body = route.request().postData();
  if (body === null) throw new Error("position command had no JSON body");
  return JSON.parse(body) as unknown;
}

async function fulfillPositionConflict(route: Route): Promise<void> {
  await route.fulfill({
    body: JSON.stringify({
      error: {
        code: "CONFLICT",
        details: [],
        message: "backend policy detail",
        requestId: "c".repeat(32),
      },
    }),
    contentType: "application/json",
    status: 409,
  });
}
