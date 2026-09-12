import { describe, expect, it, vi } from "vitest";

import type { AlertPage, AlertView } from "../../src/api/generated";
import { createAlertApi } from "../../src/api/alerts";

const eventId = "00000000-0000-4000-8000-000000000021";
const marketTime = "2026-08-24T10:05:00+08:00";
const sourceTime = "2026-08-24T10:04:55+08:00";

const alert: AlertView = {
  acknowledgedAt: null,
  blockers: [],
  bucket: "CORE",
  causeId: "episode-21",
  createdAt: "2026-08-24T10:05:05+08:00",
  currentActionable: true,
  dataAgeSeconds: 5,
  dedupKey: "a".repeat(64),
  evaluatedAt: marketTime,
  eventId,
  marketDataAt: sourceTime,
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
  messageText: "服务端权威提醒",
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
    symbol: "003043.SZ",
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
  symbol: "003043.SZ",
  targetLotId: null,
  tradingDate: "2026-08-24",
  unmetConditions: [],
  zone: "LOW_BUY",
};

const query = {
  acknowledged: false,
  endAt: "2026-08-24T15:00:00+08:00",
  limit: 20,
  offset: 0,
  signalType: "BUY_CORE_READY" as const,
  startAt: "2026-08-24T09:30:00+08:00",
  symbol: "003043.SZ",
};

const page: AlertPage = {
  ...query,
  items: [alert],
  total: 1,
};

describe("alert API", () => {
  it("serializes exact filters and caller-owned idempotency without position requests", async () => {
    const requests: Array<{ init: RequestInit | undefined; url: string }> = [];
    const acknowledged = {
      ...alert,
      acknowledgedAt: "2026-08-24T10:06:00+08:00",
      revision: 1,
    } satisfies AlertView;
    const fetchImplementation = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ init, url });
        return jsonResponse(init?.method === "POST" ? acknowledged : page);
      },
    ) as typeof fetch;
    const api = createAlertApi(fetchImplementation);

    await expect(api.listAlerts(query)).resolves.toEqual(page);
    await expect(
      api.acknowledgeAlert(
        { alertId: eventId, expectedRevision: 0 },
        "webf10-ack-1",
      ),
    ).resolves.toEqual(acknowledged);

    expect(requests[0]?.url).toBe(
      "/api/v1/alerts?symbol=003043.SZ&signalType=BUY_CORE_READY&acknowledged=false&startAt=2026-08-24T09%3A30%3A00%2B08%3A00&endAt=2026-08-24T15%3A00%3A00%2B08%3A00&offset=0&limit=20",
    );
    expect(requests[1]?.url).toBe("/api/v1/alert-acknowledgements");
    expect(requests[1]?.init).toMatchObject({ method: "POST" });
    expect((requests[1]?.init?.headers as Record<string, string>)["Idempotency-Key"]).toBe(
      "webf10-ack-1",
    );
    expect(JSON.parse(String(requests[1]?.init?.body))).toEqual({
      alertId: eventId,
      expectedRevision: 0,
    });
    expect(requests.some(({ url }) => url.includes("position"))).toBe(false);
  });

  it("rejects malformed pages, filter drift, duplicate identities, and extra fields", async () => {
    const invalidBodies: unknown[] = [
      { ...page, symbol: "600000.SH" },
      { ...page, items: [{ ...alert, acknowledgedAt: marketTime }] },
      { ...page, items: [alert, { ...alert }] , total: 2 },
      { ...page, token: "never-expose" },
      { ...page, items: [{ ...alert, matchedConditions: [{ code: "BAD" }] }] },
    ];

    for (const body of invalidBodies) {
      const api = createAlertApi(vi.fn(async () => jsonResponse(body)) as typeof fetch);
      await expect(api.listAlerts(query)).rejects.toMatchObject({
        code: "INVALID_RESPONSE",
      });
    }
  });

  it("accepts retained historical alerts only when their current action is removed", async () => {
    const historical = {
      ...alert,
      currentActionable: false,
      positionPrefill: null,
    } satisfies AlertView;
    const api = createAlertApi(
      vi.fn(async () => jsonResponse({ ...page, items: [historical] })) as typeof fetch,
    );
    await expect(api.listAlerts(query)).resolves.toEqual({ ...page, items: [historical] });

    const inconsistent = createAlertApi(
      vi.fn(async () =>
        jsonResponse({
          ...page,
          items: [{ ...alert, currentActionable: false }],
        }),
      ) as typeof fetch,
    );
    await expect(inconsistent.listAlerts(query)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("rejects acknowledgement receipts that do not prove the requested transition", async () => {
    const invalidReceipts: unknown[] = [
      alert,
      { ...alert, acknowledgedAt: marketTime, eventId: crypto.randomUUID(), revision: 1 },
      { ...alert, acknowledgedAt: marketTime, revision: 1, sequence: 0 },
      { ...alert, acknowledgedAt: marketTime, revision: 1, token: "never-expose" },
    ];

    for (const body of invalidReceipts) {
      const api = createAlertApi(vi.fn(async () => jsonResponse(body)) as typeof fetch);
      await expect(
        api.acknowledgeAlert(
          { alertId: eventId, expectedRevision: 0 },
          "webf10-ack-invalid",
        ),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });

  it("exposes only the transport's safe error message", async () => {
    const api = createAlertApi(
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: "CONFLICT",
              message: "raw storage detail",
              requestId: "a".repeat(32),
            },
          },
          409,
        ),
      ) as typeof fetch,
    );

    await expect(api.listAlerts(query)).rejects.toMatchObject({
      code: "CONFLICT",
      message: "请求与当前状态冲突",
      status: 409,
    });
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}
