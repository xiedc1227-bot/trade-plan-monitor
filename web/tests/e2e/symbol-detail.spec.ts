import { createRequire } from "node:module";

import { expect, test } from "./fixtures";
import type { Route } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");

const symbol = "003043.SZ";
const observedAt = "2026-08-24T10:05:05.000000+08:00";
const indexSnapshotHash = "d".repeat(64);
const referenceMarket = {
  board: "SZSE_MAIN",
  conditionProgress: { missing: 0, satisfied: 1, total: 2, unsatisfied: 1 },
  dataAt: observedAt,
  displayName: "深证成指",
  health: "LIVE",
  indexCode: "399001.SZ",
  issues: [],
  mappingVersion: "board-index-map-v1",
  snapshotHash: indexSnapshotHash,
};
const detail = {
  indexConditionEvidence: [
    {
      actualValue: "3220.88",
      comparisonValue: "3200.00",
      conditionType: "INDEX_CLOSE_GTE_MA",
      dataCutoff: observedAt,
      decisionCutoff: observedAt,
      formulaDefinitionHash: "e".repeat(64),
      formulaId: "SMA",
      indexCode: "399001.SZ",
      mappingVersion: "board-index-map-v1",
      missingInputs: [],
      outcome: "SATISFIED",
      parameters: [{ key: "period", unit: "COUNT", value: 20 }],
      planPath: "entry.condition.conditions[0]",
      snapshotHash: indexSnapshotHash,
      unit: "POINTS",
    },
  ],
  positionLots: [],
  referenceMarket,
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
    referenceMarket,
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

interface BrowserAudit {
  readonly consoleFailures: string[];
  readonly failedRequests: string[];
}

const browserAudits = new WeakMap<import("@playwright/test").Page, BrowserAudit>();

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const nativeFetch = globalThis.fetch.bind(globalThis);
    globalThis.fetch = async (...arguments_: Parameters<typeof fetch>) => {
      const response = await nativeFetch(...arguments_);
      const contractStatus = Number(response.headers.get("x-test-contract-status"));
      if (!Number.isInteger(contractStatus) || contractStatus < 400 || contractStatus > 599) {
        return response;
      }
      const headers = new Headers(response.headers);
      headers.delete("x-test-contract-status");
      return new Response(await response.text(), {
        headers,
        status: contractStatus,
      });
    };
  });
  const audit: BrowserAudit = { consoleFailures: [], failedRequests: [] };
  browserAudits.set(page, audit);
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      audit.consoleFailures.push(`${message.type()}: ${message.text()} @ ${message.location().url}`);
    }
  });
  page.on("requestfailed", (request) => audit.failedRequests.push(request.url()));
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204 }));
});

test.afterEach(({ page }) => {
  const audit = browserAudits.get(page);
  expect(audit?.consoleFailures ?? []).toEqual([]);
  expect(audit?.failedRequests ?? []).toEqual([]);
});

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
    throw new Error("Vite symbol-detail harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

test("reads backend detail, bars, and events for an explicit Shanghai history range", async ({ page }) => {
  const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  const indexRanges: Array<{
    endAt: string | null;
    indexCode: string;
    interval: string | null;
    startAt: string | null;
  }> = [];
  await page.route("**/api/v1/**", async (route) => fulfillApi(route, ranges, undefined, indexRanges));

  await page.goto(`${baseUrl}/stocks/${symbol}`);
  await expect(page.getByRole("heading", { level: 1, name: "华亚智能 · 003043.SZ" })).toBeVisible();
  await expect.poll(() => ranges.length).toBe(2);
  await expect.poll(() => indexRanges.length).toBe(1);
  expect(ranges).toEqual([
    { endAt: observedAt, startAt: "2026-08-24T00:00:00.000000+08:00" },
    { endAt: observedAt, startAt: "2026-08-24T00:00:00.000000+08:00" },
  ]);
  expect(indexRanges).toEqual([
    {
      endAt: observedAt,
      indexCode: "399001.SZ",
      interval: "FIVE_MINUTE",
      startAt: "2026-08-24T00:00:00.000000+08:00",
    },
  ]);
  await expect(page.getByRole("heading", { level: 2, name: "参考指数数据" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "计划指数条件" })).toBeVisible();
  await expect(page.getByText("当前计划 plan-1 · v1")).toBeVisible();
  await expect(page.getByText("entry.condition.conditions[0]")).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "板块指数历史" })).toBeVisible();
  await expect(
    page.getByRole("table", { name: "板块指数点位（与后端返回精度一致）" }),
  ).toContainText("3220.88");

  const startAt = "2026-08-22T09:30:00.000000+08:00";
  const endAt = "2026-08-22T15:00:00.000000+08:00";
  await page.locator("#symbol-history-start-at").fill(startAt);
  await page.locator("#symbol-history-end-at").fill(endAt);
  await page.getByRole("button", { name: "查询历史" }).click();

  await expect.poll(() => ranges.length).toBe(4);
  await expect.poll(() => indexRanges.length).toBe(2);
  expect(ranges.slice(-2)).toEqual([
    { endAt, startAt },
    { endAt, startAt },
  ]);
  expect(indexRanges.at(-1)).toEqual({
    endAt,
    indexCode: "399001.SZ",
    interval: "FIVE_MINUTE",
    startAt,
  });
});

test("keeps current-plan evidence visible when shared index history fails", async ({ page }) => {
  const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  await page.route("**/api/v1/**", async (route) =>
    fulfillApi(route, ranges, undefined, undefined, true),
  );

  await page.goto(`${baseUrl}/stocks/${symbol}`);

  await expect(page.getByRole("alert").filter({ hasText: "指数历史暂不可用" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "参考指数数据" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "计划指数条件" })).toBeVisible();
  await expect(page.getByText("entry.condition.conditions[0]")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("provider-private-detail");
});

test("keeps both sections explicit when the current plan has no index conditions", async ({ page }) => {
  const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  const detailWithoutReference = {
    ...structuredClone(detail),
    indexConditionEvidence: [],
    referenceMarket: null,
    summary: {
      ...structuredClone(detail.summary),
      referenceMarket: null,
    },
  };
  let indexHistoryRequests = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === `/api/v1/symbols/${symbol}`) {
      await route.fulfill({
        body: JSON.stringify(detailWithoutReference),
        contentType: "application/json",
      });
      return;
    }
    if (url.pathname.startsWith("/api/v1/market-indexes/")) {
      indexHistoryRequests += 1;
    }
    await fulfillApi(route, ranges);
  });

  await page.goto(`${baseUrl}/stocks/${symbol}`);

  await expect(page.getByRole("heading", { level: 2, name: "参考指数数据" })).toBeVisible();
  await expect(page.getByText("Schema v1 计划未配置参考指数；原有判断保持不变。")).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "计划指数条件" })).toBeVisible();
  await expect(page.getByText("当前计划 plan-1 · v1")).toBeVisible();
  await expect(page.getByText("计划未使用", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "板块指数历史" })).toHaveCount(0);
  expect(indexHistoryRequests).toBe(0);
});

test("marks a mapped Schema v2 plan with zero index leaves as unused", async ({ page }) => {
  const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  const unusedReference = {
    ...structuredClone(referenceMarket),
    conditionProgress: { missing: 0, satisfied: 0, total: 0, unsatisfied: 0 },
  };
  const detailWithoutIndexLeaves = {
    ...structuredClone(detail),
    indexConditionEvidence: [],
    referenceMarket: unusedReference,
    summary: {
      ...structuredClone(detail.summary),
      referenceMarket: structuredClone(unusedReference),
    },
  };
  const indexRanges: Array<{
    endAt: string | null;
    indexCode: string;
    interval: string | null;
    startAt: string | null;
  }> = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === `/api/v1/symbols/${symbol}`) {
      await route.fulfill({
        body: JSON.stringify(detailWithoutIndexLeaves),
        contentType: "application/json",
      });
      return;
    }
    await fulfillApi(route, ranges, undefined, indexRanges);
  });

  await page.goto(`${baseUrl}/stocks/${symbol}`);

  await expect(page.getByRole("heading", { level: 2, name: "参考指数数据" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "计划指数条件" })).toBeVisible();
  await expect(page.getByText("计划未使用", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "板块指数历史" })).toBeVisible();
  await expect.poll(() => indexRanges.length).toBe(1);
});

test("keeps the separated detail sections responsive and accessible", async ({ page }) => {
  const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  await page.route("**/api/v1/**", async (route) => fulfillApi(route, ranges));

  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ height: 900, width });
    await page.goto(`${baseUrl}/stocks/${symbol}`);
    await expect(page.getByRole("heading", { level: 2, name: "计划指数条件" })).toBeVisible();
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    const sizes = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    const overflowSources = await page.evaluate(() => {
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
    expect(
      sizes.scrollWidth,
      `symbol detail overflow at ${width}px: ${JSON.stringify(overflowSources)}`,
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

test("keeps history range inputs visible and operable at 320px with 200 percent text", async ({ page }) => {
  const ranges: Array<{ endAt: string | null; startAt: string | null }> = [];
  await page.route("**/api/v1/**", async (route) => fulfillApi(route, ranges));

  await page.setViewportSize({ height: 900, width: 320 });
  await page.goto(`${baseUrl}/stocks/${symbol}`);
  await expect(page.getByRole("heading", { level: 2, name: "计划指数条件" })).toBeVisible();
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });

  const startInput = page.locator("#symbol-history-start-at");
  const endInput = page.locator("#symbol-history-end-at");
  for (const input of [startInput, endInput]) {
    await expect(input).toBeVisible();
    const bounds = await input.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds?.x).toBeGreaterThanOrEqual(0);
    expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(320);
  }

  const startAt = "2026-08-22T09:30:00.000000+08:00";
  const endAt = "2026-08-22T15:00:00.000000+08:00";
  await startInput.fill(startAt);
  await endInput.fill(endAt);
  await expect(startInput).toHaveValue(startAt);
  await expect(endInput).toHaveValue(endAt);
  await endInput.focus();
  await expect(endInput).toBeFocused();
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

test("confirms plan-scoped manual event risk through the normal symbol page", async ({ page }) => {
  const manualRiskCommands: unknown[] = [];
  const planVersionId = "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93";
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/manual-event-risk") {
      await route.fulfill({
        body: JSON.stringify({
          confirmedAt: null,
          expiresOn: null,
          planVersionId,
          reason: "MISSING_CONFIRMATION",
          revision: 0,
          status: "UNKNOWN",
          symbol,
        }),
        contentType: "application/json",
      });
      return;
    }
    if (url.pathname === "/api/v1/manual-event-risk-confirmations") {
      manualRiskCommands.push({
        body: readJsonBody(route),
        idempotencyKey: await route.request().headerValue("Idempotency-Key"),
      });
      await route.fulfill({
        body: JSON.stringify({
          confirmedAt: observedAt,
          expiresOn: "2026-08-24",
          planVersionId,
          reason: null,
          revision: 1,
          status: "RISK_PRESENT",
          symbol,
        }),
        contentType: "application/json",
      });
      return;
    }
    await fulfillApi(route, []);
  });

  await page.goto(`${baseUrl}/stocks/${symbol}`);
  await expect(page.getByRole("heading", { level: 2, name: "人工事件风险确认" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "缺少人工事件风险确认" })).toBeVisible();

  await page.locator('select[name="manualRiskStatus"]').selectOption("RISK_PRESENT");
  await page.locator('input[name="manualRiskExpiresOn"]').fill("2026-08-24");
  await page.getByRole("button", { name: "复核确认" }).click();
  await expect(page.getByTestId("manual-risk-confirmation")).toBeVisible();
  await page.getByTestId("confirm-manual-risk").click();

  await expect.poll(() => manualRiskCommands.length).toBe(1);
  expect(manualRiskCommands).toEqual([
    {
      body: {
        expectedRevision: 0,
        expiresOn: "2026-08-24",
        status: "RISK_PRESENT",
        symbol,
      },
      idempotencyKey: expect.stringMatching(/^manual-risk-[0-9a-f-]{36}$/),
    },
  ]);
  await expect(page.getByRole("status").filter({ hasText: "已确认存在事件风险" })).toBeVisible();
});

async function fulfillApi(
  route: Route,
  ranges: Array<{ endAt: string | null; startAt: string | null }>,
  positionRequests?: PositionRequests,
  indexRanges?: Array<{
    endAt: string | null;
    indexCode: string;
    interval: string | null;
    startAt: string | null;
  }>,
  failIndexHistory = false,
): Promise<void> {
  const url = new URL(route.request().url());
  if (url.pathname === "/api/v1/dashboard") {
    await route.fulfill({
      body: JSON.stringify({
        availability: "UNAVAILABLE",
        observedAt,
        reason: "AWAITING_FIRST_EVALUATION",
        sequence: 0,
      }),
      contentType: "application/json",
      status: 200,
    });
    return;
  }
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
  if (url.pathname === "/api/v1/market-indexes/399001.SZ/bars") {
    indexRanges?.push({
      endAt: url.searchParams.get("endAt"),
      indexCode: "399001.SZ",
      interval: url.searchParams.get("interval"),
      startAt: url.searchParams.get("startAt"),
    });
    if (failIndexHistory) {
      await route.fulfill({
        body: JSON.stringify({
          error: {
            code: "SERVICE_UNAVAILABLE",
            details: [],
            message: "provider-private-detail",
            requestId: "f".repeat(32),
          },
        }),
        contentType: "application/json",
        headers: { "x-test-contract-status": "503" },
        status: 200,
      });
      return;
    }
    const barAt = url.searchParams.get("endAt") ?? observedAt;
    await route.fulfill({
      body: JSON.stringify({
        hasMore: false,
        items: [
          {
            amount: null,
            barAt,
            closePoints: "3220.88",
            highPoints: "3222.00",
            indexCode: "399001.SZ",
            interval: "FIVE_MINUTE",
            lowPoints: "3217.50",
            observedAt: barAt,
            openPoints: "3218.00",
            providerRevision: 1,
            sourceKind: "PROVISIONAL",
            volume: "100000",
          },
        ],
        limit: Number(url.searchParams.get("limit")),
        nextCursor: null,
        snapshotHash: indexSnapshotHash,
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
    headers: { "x-test-contract-status": "503" },
    status: 200,
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
    headers: { "x-test-contract-status": "409" },
    status: 200,
  });
}
