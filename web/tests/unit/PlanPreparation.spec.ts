import { describe, expect, it, vi } from "vitest";

import type { PreparationView } from "../../src/api/generated-runtime-status";
import { createPreparationApi } from "../../src/api/preparations";

const BASE = "/api/v1/backtest-preparations";
const SOURCE = { source_id: "source-1", text: "完整计划原文" };

function preparation(overrides: Partial<PreparationView> = {}): PreparationView {
  return {
    preparationId: "prep-1", revision: 1, sourceRevision: 1, candidateRevision: 0,
    reviewRevision: 0, source: SOURCE, sourceEditPending: false, status: "DRAFT",
    attempts: [], candidate: null, workPhase: null, generation: null, ...overrides,
  };
}

function receipt(body = preparation(), status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status, headers: { "Cache-Control": "no-store", Location: `${BASE}/${body.preparationId}`,
      ...(status === 202 ? { "Retry-After": "2" } : {}), ...headers },
  });
}

describe("one-source preparation transport", () => {
  it("sends one embedded source, revision and stable mutation key without following redirects", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(receipt(preparation(), 201));
    const api = createPreparationApi(fetcher);
    const signal = new AbortController().signal;
    const command = { input: { preparation_id: "prep-1", sources: [SOURCE] } };
    const result = await api.create(command, "intent-1", { signal });
    expect(result.status).toBe(201);
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe(BASE);
    expect(init).toMatchObject({ method: "POST", credentials: "same-origin", redirect: "error", signal });
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("intent-1");
    expect(JSON.parse(String(init?.body))).toEqual(command);
  });

  it.each([
    { revision: Number.MAX_SAFE_INTEGER + 1 }, { sourceRevision: 0 }, { attempts: [{ source_revision: 1 }] },
    { preparationId: "other" }, { workPhase: "CALLING", generation: null }, { privateOwner: "hidden" },
  ])("rejects malformed progress: %o", async (override) => {
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(receipt(preparation(override as Partial<PreparationView>))));
    await expect(api.get("prep-1")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.each([
    { Location: "https://example.com/redirect" }, { "Cache-Control": "public" }, { "Retry-After": "-1" },
  ])("rejects invalid success metadata: %o", async (headers) => {
    const api = createPreparationApi(vi.fn<typeof fetch>().mockResolvedValue(receipt(preparation(), 200, headers)));
    await expect(api.get("prep-1")).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects a second source and an unsafe route before contacting the server", async () => {
    const fetcher = vi.fn<typeof fetch>();
    const api = createPreparationApi(fetcher);
    await expect(api.create({ input: { preparation_id: "p1", sources: [SOURCE, SOURCE] } }, "key-1")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    await expect(api.get("../private")).rejects.toMatchObject({ code: "VALIDATION_ERROR" });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("supports actual extraction, source-edit and cancellation receipts", async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(receipt(preparation({ status: "EXTRACTING", workPhase: "CALLING", generation: "g1" }), 202))
      .mockResolvedValueOnce(receipt(preparation({ revision: 2 }), 200))
      .mockResolvedValueOnce(receipt(preparation({ status: "CANCEL_REQUESTED", workPhase: "CALLING", generation: "g1" }), 202))
      .mockResolvedValueOnce(receipt(preparation({ status: "CANCELLED", workPhase: "ENDED", generation: "g1" }), 200));
    const api = createPreparationApi(fetcher);
    expect((await api.extract("prep-1", { expectedRevision: 1 }, "extract-1")).retryAfterSeconds).toBe(2);
    await api.edit("prep-1", { expectedRevision: 1, source: SOURCE }, "edit-1");
    expect((await api.cancel("prep-1", { expectedRevision: 2 }, "cancel-1")).status).toBe(202);
    expect((await api.cancel("prep-1", { expectedRevision: 2 }, "cancel-1")).status).toBe(200);
    expect(fetcher.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      [`${BASE}/prep-1/extractions`, "POST"], [`${BASE}/prep-1/source`, "PUT"],
      [`${BASE}/prep-1/cancellations`, "POST"], [`${BASE}/prep-1/cancellations`, "POST"],
    ]);
  });
});
