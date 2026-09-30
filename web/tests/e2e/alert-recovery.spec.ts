import { createServer } from "vite";
import type { ViteDevServer } from "vite";

import { expect, test } from "./fixtures";
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
  sequence: 22,
  severity: "ACTION",
  signalType: "BUY_CORE_READY",
  symbol,
  targetLotId: null,
  tradingDate: "2026-08-24",
  unmetConditions: [],
  zone: "LOW_BUY",
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
    throw new Error("Vite alert recovery harness did not expose a local port");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  await server.close();
});

for (const trigger of ["snapshot-required", "snapshot-then-alert"] as const) {
  test(`shows a persisted alert without manual refresh after ${trigger}`, async ({ page }) => {
    let sequence = 20;
    let hasAlert = false;
    let alertQueries = 0;
    const sockets: Array<{ send(message: string): void; url(): string }> = [];
    await page.route(`${baseUrl}/api/v1/**`, async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/v1/dashboard") {
        const dashboard: DashboardResponse = {
          connectionStatus: "CONNECTED",
          counts: { actionable: hasAlert ? 1 : 0, blocked: 0, lowZoneWatch: 0, normal: 0, risk: 0, stale: 0 },
          marketIndexes: [],
          observedAt: "2026-08-24T10:05:05+08:00",
          runtimeGeneration: "00000000-0000-4000-8000-000000000001",
          sequence,
          symbols: [],
        };
        await route.fulfill({ json: dashboard });
        return;
      }
      if (url.pathname === "/api/v1/alerts") {
        alertQueries += 1;
        const response: AlertPage = {
          acknowledged: null,
          endAt: null,
          items: hasAlert ? [alert] : [],
          limit: 20,
          offset: 0,
          signalType: null,
          startAt: null,
          symbol: null,
          total: hasAlert ? 1 : 0,
        };
        await route.fulfill({ json: response });
        return;
      }
      await route.fulfill({ json: {}, status: 503 });
    });
    await page.routeWebSocket(
      (url) => url.pathname === "/ws/v1/monitor",
      (socket) => sockets.push(socket),
    );

    await page.goto(`${baseUrl}/alerts`);
    await expect(page.getByText("当前筛选条件下暂无提醒。")).toBeVisible();
    await expect.poll(() => sockets.length).toBe(1);
    expect(alertQueries).toBe(1);

    hasAlert = true;
    sequence = 22;
    if (trigger === "snapshot-required") {
      sockets[0]!.send(JSON.stringify({ reason: "REPLAY_UNAVAILABLE", sequence: 22, type: "snapshot.required" }));
    } else {
      sockets[0]!.send(JSON.stringify({
        aggregateId: symbol,
        eventId: "00000000-0000-0000-0000-000000000031",
        occurredAt: "2026-08-24T10:05:05+08:00",
        payload: { entityId: symbol, resultHash: "d".repeat(64), symbol },
        schemaVersion: 1,
        sequence: 21,
        type: "symbol.snapshot.updated",
      }));
      sockets[0]!.send(JSON.stringify({
        aggregateId: eventId,
        eventId,
        occurredAt: "2026-08-24T10:05:05+08:00",
        payload: { entityId: eventId, revision: 0, symbol },
        schemaVersion: 1,
        sequence: 22,
        type: "alert.created",
      }));
    }

    await expect.poll(() => sockets.length).toBe(2);
    sockets[1]!.send(JSON.stringify({
      runtimeGeneration: "00000000-0000-4000-8000-000000000001",
      runtimeLive: true,
      runtimeStartedAt: "2026-08-24T09:00:00+08:00",
      sequence: 22,
      type: "heartbeat",
    }));
    await expect(page.locator(".app-shell__connection-banner")).toHaveAttribute("data-connection-state", "LIVE");
    await expect.poll(() => alertQueries).toBeGreaterThanOrEqual(2);
    await expect(page.getByText("服务端权威提醒")).toBeVisible();
  });
}
