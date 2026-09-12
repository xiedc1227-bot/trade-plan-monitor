import { describe, expect, it, vi } from "vitest";

import type {
  PositionLotClosureCommand,
  PositionLotClosureView,
  PositionLotCreateCommand,
  PositionLotPage,
  PositionInventoryClosureCommand,
  PositionInventoryClosureView,
  PositionInventoryConfirmationCommand,
  PositionInventoryView,
  components,
} from "../../src/api/generated";
import { createPositionApi } from "../../src/api/positions";

type PositionLot =
  components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"];

const symbol = "003043.SZ";
const asOfTradeDate = "2026-08-24";
const lotId = "00000000-0000-4000-8000-000000000011";

const lot: PositionLot = {
  acquiredTradeDate: "2026-08-21",
  bucket: "CORE",
  closedAt: null,
  costFen: 6_400,
  lotId,
  quantity: 200,
  relatedAlertId: null,
  remainingQuantity: 100,
  revision: 1,
  sellableQuantity: 100,
  symbol,
};

const page: PositionLotPage = {
  asOfTradeDate,
  items: [lot],
  limit: 100,
  offset: 0,
  symbol,
  total: 1,
};

const inventory: PositionInventoryView = {
  asOfTradeDate,
  confirmationId: "00000000-0000-4000-8000-000000000013",
  confirmedAt: observedAt(),
  cutoff: observedAt(),
  includedLotIds: [],
  inventoryRevision: 2,
  missingReasons: [],
  openingBalances: [{
    openingBalanceId: "00000000-0000-4000-8000-000000000014",
    originalQuantity: 200,
    remainingQuantity: 200,
    revision: 0,
    sellableFrom: asOfTradeDate,
    symbol,
  }],
  sellableQuantity: 200,
  status: "KNOWN",
  symbol,
  totalQuantity: 200,
};

describe("position API", () => {
  it("uses camelCase position endpoints and caller-owned idempotency keys", async () => {
    const requests: Array<{ init: RequestInit | undefined; url: string }> = [];
    const createCommand: PositionLotCreateCommand = {
      acquiredTradeDate: asOfTradeDate,
      bucket: "TACTICAL",
      costFen: 6_500,
      expectedRevision: 0,
      quantity: 100,
      relatedAlertId: null,
      symbol,
    };
    const closeCommand: PositionLotClosureCommand = {
      expectedRevision: 1,
      lotId,
      quantity: 100,
      tradeDate: asOfTradeDate,
    };
    const createdLot: PositionLot = {
      ...lot,
      acquiredTradeDate: createCommand.acquiredTradeDate,
      bucket: createCommand.bucket,
      costFen: createCommand.costFen,
      lotId: "00000000-0000-4000-8000-000000000012",
      quantity: createCommand.quantity,
      remainingQuantity: createCommand.quantity,
      revision: 0,
      sellableQuantity: 0,
    };
    const closedLot: PositionLot = {
      ...lot,
      closedAt: "2026-08-24T10:05:05.000000+08:00",
      remainingQuantity: 0,
      revision: 2,
      sellableQuantity: 0,
    };
    const closure: PositionLotClosureView = {
      afterRemainingQuantity: 0,
      appliedQuantity: closeCommand.quantity,
      beforeRemainingQuantity: lot.remainingQuantity,
      lot: closedLot,
      tradeDate: closeCommand.tradeDate,
    };
    const fetchImplementation = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ init, url });
        if (url.startsWith("/api/v1/position-lots?")) return jsonResponse(page);
        if (url === "/api/v1/position-lot-closures") return jsonResponse(closure);
        return jsonResponse(createdLot);
      },
    ) as typeof fetch;
    const api = createPositionApi(fetchImplementation);

    await expect(
      api.listPositions({ asOfTradeDate, limit: 100, offset: 0, symbol }),
    ).resolves.toEqual(page);
    await expect(api.createPosition(createCommand, "position-create-1")).resolves.toEqual(
      createdLot,
    );
    await expect(api.closePosition(closeCommand, "position-close-1")).resolves.toEqual(closure);

    expect(requests.map(({ url }) => url)).toEqual([
      "/api/v1/position-lots?symbol=003043.SZ&asOfTradeDate=2026-08-24&offset=0&limit=100",
      "/api/v1/position-lots",
      "/api/v1/position-lot-closures",
    ]);
    expect(requests[0]?.init).toMatchObject({ method: "GET" });
    expect(requests.slice(1).map(({ init }) => init?.method)).toEqual(["POST", "POST"]);
    expect(
      requests.slice(1).map(
        ({ init }) => (init?.headers as Record<string, string>)["Idempotency-Key"],
      ),
    ).toEqual(["position-create-1", "position-close-1"]);
    expect(requests.slice(1).map(({ init }) => JSON.parse(String(init?.body)))).toEqual([
      createCommand,
      closeCommand,
    ]);
  });

  it("rejects malformed and filter-identity-mismatched pages before exposing them", async () => {
    const invalidBodies: unknown[] = [
      { ...page, symbol: "600000.SH" },
      { ...page, asOfTradeDate: "2026-08-25" },
      { ...page, items: [{ ...lot, symbol: "600000.SH" }] },
      { ...page, token: "must-not-be-returned" },
    ];

    for (const body of invalidBodies) {
      const api = createPositionApi(
        vi.fn(async () => jsonResponse(body)) as typeof fetch,
      );
      await expect(
        api.listPositions({ asOfTradeDate, limit: 100, offset: 0, symbol }),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });

  it("keeps independent inventory confirmation and real closure separate from alerts", async () => {
    const confirm: PositionInventoryConfirmationCommand = {
      asOfTradeDate,
      completeRegistration: true,
      expectedRevision: 1,
      includedLotIds: [],
      sellableQuantity: 200,
      symbol,
      totalQuantity: 200,
    };
    const close: PositionInventoryClosureCommand = {
      expectedRevision: 0,
      quantity: 100,
      sourceId: inventory.openingBalances?.[0]?.openingBalanceId ?? "",
      sourceType: "OPENING_BALANCE",
      tradeDate: asOfTradeDate,
    };
    const closure: PositionInventoryClosureView = {
      afterRemainingQuantity: 100,
      appliedQuantity: 100,
      beforeRemainingQuantity: 200,
      revision: 1,
      sourceId: close.sourceId,
      sourceType: "OPENING_BALANCE",
      symbol,
      tradeDate: asOfTradeDate,
    };
    const requests: string[] = [];
    const api = createPositionApi(vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      if (url.startsWith("/api/v1/position-inventory?")) return jsonResponse(inventory);
      if (url.endsWith("confirmations")) return jsonResponse({ ...inventory, inventoryRevision: 2 });
      return jsonResponse(closure);
    }) as typeof fetch);

    await expect(api.getInventory(symbol, asOfTradeDate)).resolves.toEqual(inventory);
    await expect(api.confirmInventory(confirm, "inventory-confirm-1")).resolves.toMatchObject({
      inventoryRevision: 2,
      status: "KNOWN",
    });
    await expect(api.closeInventory(close, "inventory-close-1")).resolves.toEqual(closure);
    expect(requests).toEqual([
      "/api/v1/position-inventory?asOfTradeDate=2026-08-24&symbol=003043.SZ",
      "/api/v1/position-inventory-confirmations",
      "/api/v1/position-inventory-closures",
    ]);
  });

  it("rejects mutation receipts that do not prove the requested lot transition", async () => {
    const createCommand: PositionLotCreateCommand = {
      acquiredTradeDate: asOfTradeDate,
      bucket: "TACTICAL",
      costFen: 6_500,
      expectedRevision: 0,
      quantity: 100,
      relatedAlertId: null,
      symbol,
    };
    const closeCommand: PositionLotClosureCommand = {
      expectedRevision: 1,
      lotId,
      quantity: 100,
      tradeDate: asOfTradeDate,
    };
    const creationApi = createPositionApi(
      vi.fn(async () =>
        jsonResponse({ ...lot, bucket: createCommand.bucket, revision: 1 }),
      ) as typeof fetch,
    );
    const closureApi = createPositionApi(
      vi.fn(async () =>
        jsonResponse({
          afterRemainingQuantity: 100,
          appliedQuantity: 100,
          beforeRemainingQuantity: 200,
          lot,
          tradeDate: "2026-08-25",
        }),
      ) as typeof fetch,
    );

    await expect(
      creationApi.createPosition(createCommand, "bad-create-receipt"),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    await expect(
      closureApi.closePosition(closeCommand, "bad-close-receipt"),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("returns only the transport's generic error for failed position requests", async () => {
    const api = createPositionApi(
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: "CONFLICT",
              message: "raw backend detail must never reach the UI",
              requestId: "a".repeat(32),
            },
          },
          409,
        ),
      ) as typeof fetch,
    );

    await expect(
      api.listPositions({ asOfTradeDate, limit: 100, offset: 0, symbol }),
    ).rejects.toMatchObject({
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

function observedAt(): string {
  return "2026-08-24T10:05:05.000000+08:00";
}
