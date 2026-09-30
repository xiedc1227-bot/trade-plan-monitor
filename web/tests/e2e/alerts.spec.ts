import { expect, test } from "./fixtures";
import type { Locator, Page, Route } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type { AlertPage, AlertView, DashboardResponse } from "../../src/api/generated";

const eventId = "00000000-0000-4000-8000-000000000021";
const symbol = "003043.SZ";
const alert: AlertView = {
  acknowledgedAt: null,
  blockers: [
    {
      children: [],
      code: "MANUAL_EVENT_RISK_CLEAR",
      facts: [],
      kind: "RULE",
      missingInputs: ["MANUAL_EVENT_RISK"],
      outcome: "MISSING_INPUT",
    },
  ],
  bucket: "CORE",
  causeId: "episode-21",
  createdAt: "2026-08-24T10:05:05+08:00",
  currentActionable: true,
  dataAgeSeconds: 5,
  dedupKey: "a".repeat(64),
  evaluatedAt: "2026-08-24T10:05:00+08:00",
  eventId,
  marketDataAt: "2026-08-24T10:04:55+08:00",
  matchedConditions: [
    {
      children: [],
      code: "PRICE_IN_ZONE",
      facts: [{ key: "current_price_fen", unit: "FEN", value: 6_420 }],
      kind: "CONDITION",
      missingInputs: [],
      outcome: "SATISFIED",
    },
  ],
  messageText: "<script>never execute</script> 服务端权威提醒",
  name: "华亚智能",
  nextStep: { code: "RECORD_CONFIRMED_FILL", requiredInputs: [] },
  planHash: "b".repeat(64),
  planId: "huaya-smart",
  planVersion: 1,
  positionPrefill: {
    action: "BUY",
    bucket: "CORE",
    quantity: 100,
    relatedAlertId: eventId,
    symbol,
    targetLotId: null,
  },
  priceFen: 6_420,
  quantity: 100,
  relevantZone: {
    highFen: 6_450,
    includeHigh: true,
    includeLow: true,
    lowFen: 6_300,
    zone: "LOW_BUY",
  },
  revision: 0,
  riskLineFen: 6_080,
  satisfiedConditions: [],
  sequence: 21,
  severity: "ACTION",
  signalType: "BUY_CORE_READY",
  symbol,
  targetLotId: null,
  tradingDate: "2026-08-24",
  unmetConditions: [],
  zone: "LOW_BUY",
};

const dashboard: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: { actionable: 1, blocked: 0, lowZoneWatch: 0, normal: 0, risk: 0, stale: 0 },
  marketIndexes: [],
  observedAt: "2026-08-24T10:05:05+08:00",
  runtimeGeneration: "00000000-0000-4000-8000-000000000001",
  sequence: 21,
  symbols: [],
};

let server: ViteDevServer;
let baseUrl: string;

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
    throw new Error("Vite alert harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

test("queries, filters, expands evidence, and acknowledges without a position request", async ({
  page,
}) => {
  const alertQueries: Array<Record<string, string>> = [];
  const acknowledgements: unknown[] = [];
  const positionRequests: string[] = [];
  const chartRequests: string[] = [];
  let acknowledged = false;
  page.on("request", (request) => {
    if (/PriceChart|BacktestEquityChart|installCanvasRenderer|echarts/i.test(request.url())) {
      chartRequests.push(request.url());
    }
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.includes("position")) positionRequests.push(url.pathname);
    if (url.pathname === "/api/v1/dashboard") {
      await fulfillJson(route, dashboard);
      return;
    }
    if (url.pathname === "/api/v1/alerts" && request.method() === "GET") {
      alertQueries.push(Object.fromEntries(url.searchParams));
      const requestedAcknowledged = url.searchParams.get("acknowledged");
      const visible = requestedAcknowledged === "false" ? !acknowledged : true;
      const item = acknowledged
        ? { ...alert, acknowledgedAt: "2026-08-24T10:06:00+08:00", revision: 1 }
        : alert;
      const response: AlertPage = {
        acknowledged:
          requestedAcknowledged === null ? null : requestedAcknowledged === "true",
        endAt: url.searchParams.get("endAt"),
        items: visible ? [item] : [],
        limit: Number(url.searchParams.get("limit")),
        offset: Number(url.searchParams.get("offset")),
        signalType: (url.searchParams.get("signalType") as AlertView["signalType"] | null),
        startAt: url.searchParams.get("startAt"),
        symbol: url.searchParams.get("symbol"),
        total: visible ? 1 : 0,
      };
      await fulfillJson(route, response);
      return;
    }
    if (
      url.pathname === "/api/v1/alert-acknowledgements" &&
      request.method() === "POST"
    ) {
      acknowledgements.push(request.postDataJSON());
      acknowledged = true;
      await fulfillJson(route, {
        ...alert,
        acknowledgedAt: "2026-08-24T10:06:00+08:00",
        revision: 1,
      });
      return;
    }
    await route.fulfill({ body: "unexpected request", status: 500 });
  });

  await page.goto(`${baseUrl}/alerts`);
  await expect(page.getByRole("heading", { level: 1, name: "文字提醒中心" })).toBeVisible();
  const filterControls: ReadonlyArray<readonly [string, Locator]> = [
    ["股票代码", page.getByLabel("股票代码")],
    ["信号类型", page.getByLabel("信号类型")],
    ["确认状态", page.getByLabel("确认状态")],
    ["开始时间", page.getByLabel("开始时间")],
    ["结束时间", page.getByLabel("结束时间")],
    ["应用筛选", page.getByRole("button", { name: "应用筛选" })],
  ];
  for (const width of [320, 768, 1_024, 1_440]) {
    await page.setViewportSize({ height: 900, width });
    await expectControlsNotToOverlap(page, filterControls);
  }
  await page.setViewportSize({ height: 720, width: 1_280 });
  await expect(page.getByText("<script>never execute</script> 服务端权威提醒")).toBeVisible();
  await expect(page.locator("script").filter({ hasText: "never execute" })).toHaveCount(0);

  await page.getByRole("button", { name: "查看证据" }).click();
  await expect(page.getByRole("region", { name: "华亚智能提醒证据" })).toContainText(
    "PRICE_IN_ZONE",
  );
  await expect(page.getByRole("region", { name: "华亚智能提醒证据" })).toContainText(
    "MANUAL_EVENT_RISK",
  );

  await page.getByLabel("股票代码").fill(symbol);
  await page.getByLabel("信号类型").selectOption("BUY_CORE_READY");
  await page.getByLabel("确认状态").selectOption("false");
  await page.getByLabel("开始时间").fill("2026-08-24T09:30");
  await page.getByLabel("结束时间").fill("2026-08-24T15:00");
  await page.getByRole("button", { name: "应用筛选" }).click();
  await expect.poll(() => alertQueries.length).toBe(2);
  expect(alertQueries[1]).toEqual({
    acknowledged: "false",
    endAt: "2026-08-24T15:00:00+08:00",
    limit: "20",
    offset: "0",
    signalType: "BUY_CORE_READY",
    startAt: "2026-08-24T09:30:00+08:00",
    symbol,
  });

  await page.getByRole("button", { name: "确认已查看（不代表成交）" }).click();
  await expect(page.locator(".alerts-view__operation-status")).toContainText("提醒已确认");
  await expect(page.getByText("当前筛选条件下暂无提醒。")).toBeVisible();
  expect(acknowledgements).toEqual([{ alertId: eventId, expectedRevision: 0 }]);
  expect(positionRequests).toEqual([]);
  expect(chartRequests).toEqual([]);
});

async function fulfillJson(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    body: JSON.stringify(body),
    contentType: "application/json; charset=utf-8",
    status: 200,
  });
}

async function expectControlsNotToOverlap(
  page: Page,
  controls: ReadonlyArray<readonly [string, Locator]>,
): Promise<void> {
  const boxes = await Promise.all(
    controls.map(async ([name, control]) => {
      const box = await control.boundingBox();
      expect(box, `${name}控件应可见并具有布局尺寸`).not.toBeNull();
      return { box: box!, name };
    }),
  );

  for (let leftIndex = 0; leftIndex < boxes.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < boxes.length; rightIndex += 1) {
      const left = boxes[leftIndex]!;
      const right = boxes[rightIndex]!;
      const overlapsHorizontally =
        left.box.x < right.box.x + right.box.width &&
        right.box.x < left.box.x + left.box.width;
      const overlapsVertically =
        left.box.y < right.box.y + right.box.height &&
        right.box.y < left.box.y + left.box.height;
      expect(
        overlapsHorizontally && overlapsVertically,
        `${left.name}与${right.name}控件不应互相覆盖（viewport=${page.viewportSize()?.width ?? "unknown"}px）`,
      ).toBe(false);
    }
  }
}
