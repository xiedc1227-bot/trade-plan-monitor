import { expect, test } from "@playwright/test";
import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import type { DashboardResponse } from "../../src/api/generated";

const dashboard: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: { actionable: 0, blocked: 0, lowZoneWatch: 1, normal: 0, risk: 0, stale: 0 },
  dataAgeSeconds: 2,
  marketIndexes: [
    {
      board: "STAR_MARKET",
      closePoints: "1234.56",
      completedBucketAt: "2026-09-02T10:35:00+08:00",
      displayName: "科创50",
      health: "LIVE",
      indexCode: "000688.SH",
      indicatorFacts: [],
      issues: [],
      mappedSymbolCount: 1,
      mappingVersion: "board-index-map-v1",
      observedAt: "2026-09-02T10:35:02+08:00",
      priorClosePoints: "1220.11",
      revision: 42,
      sessionChangeRatio: "0.011843",
      snapshotHash: "a".repeat(64),
    },
  ],
  observedAt: "2026-09-02T10:35:02+08:00",
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
  await page.route(`${baseUrl}/api/v1/dashboard`, async (route) => {
    await route.fulfill({
      body: JSON.stringify(dashboard),
      contentType: "application/json; charset=utf-8",
      status: 200,
    });
  });

  await page.goto(baseUrl);

  await expect(page.getByRole("heading", { level: 1, name: "监控总览" })).toBeVisible();
  await expect(page.getByText("华兴源创")).toBeVisible();
  await expect(page.getByText("参考板块指数：共用数据")).toBeVisible();
  await expect(page.getByText("科创50").first()).toBeVisible();
  await expect(page.getByText("计划指数条件")).toBeVisible();

  await page.getByRole("link", { name: "688001.SH" }).click();
  await expect(page).toHaveURL(/\/stocks\/688001\.SH$/);
});
