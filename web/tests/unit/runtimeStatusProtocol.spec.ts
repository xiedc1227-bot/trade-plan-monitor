import { describe, expect, it, vi } from "vitest";

import { createMonitorProtocol } from "../../src/runtime-status/protocol";

const origin = "http://127.0.0.1:32109";
const header = "X-Monitor-Contract-Version";
const health = { monitorContractVersion: 2, verifiedHealth: true };
const validateHealth = (value: unknown) =>
  typeof value === "object" && value !== null &&
  "verifiedHealth" in value && value.verifiedHealth === true;
const response = (body: unknown = health, version: string | null = "2", status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: version === null ? {} : { [header]: version },
  });
const post = { method: "POST", headers: { "Idempotency-Key": "same-intent" }, body: "{}" };

describe("isolated monitor v2 protocol", () => {
  it("requires an explicit health validator before it can be used", () => {
    expect(() => createMonitorProtocol({ origin, fetchImplementation: vi.fn() } as never)).toThrow();
  });

  it.each([null, "1", "02", "2, 2"])("enters terminal reload for response header %s before accepting JSON", async (version) => {
    const fetchImplementation = vi.fn(async () => new Response("not JSON", { headers: version === null ? {} : { [header]: version } }));
    const onReloadRequired = vi.fn();
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth, onReloadRequired });
    await expect(protocol.fetch("/api/v1/dashboard")).rejects.toMatchObject({ code: "RELOAD_REQUIRED" });
    await expect(protocol.fetch("/api/v1/plan-activations", post)).rejects.toMatchObject({ code: "RELOAD_REQUIRED" });
    expect(protocol.state).toBe("RELOAD_REQUIRED");
    expect(fetchImplementation).toHaveBeenCalledTimes(1);
    expect(onReloadRequired).toHaveBeenCalledTimes(1);
  });

  it.each([{}, { monitorContractVersion: 1 }, { monitorContractVersion: "2" }])("rejects missing or incompatible projection body version", async (body) => {
    const protocol = createMonitorProtocol({ origin, fetchImplementation: vi.fn(async () => response(body)), validateHealth });
    await expect(protocol.fetch("/api/v1/dashboard")).rejects.toMatchObject({ code: "RELOAD_REQUIRED" });
  });

  it("recognizes the safe mismatch detail even with a compatible response header", async () => {
    const protocol = createMonitorProtocol({ origin, validateHealth, fetchImplementation: vi.fn(async () => response({ error: {
      code: "CONFLICT", message: "Reload the application to use monitor contract 2", requestId: "a".repeat(32),
      details: [{ code: "MONITOR_CONTRACT_MISMATCH", location: ["header", header], message: "Reload the application to use monitor contract 2" }],
    } }, "2", 409)) });
    await expect(protocol.fetch("/api/v1/health")).rejects.toMatchObject({ code: "RELOAD_REQUIRED" });
  });

  it.each([
    "plan-activations", "plan-deactivations", "position-lots", "position-lot-closures",
    "position-inventory-closures", "position-inventory-confirmations", "manual-event-risk-confirmations",
    "alert-acknowledgements", "diagnostic-evaluations", "system/legacy-plan-invalidation",
  ])("preflights every %s submission and identical retry, retaining the idempotency key", async (path) => {
    const requests: Request[] = [];
    const fetchImplementation: typeof fetch = vi.fn(async (input, init) => {
      const request = new Request(input, init);
      requests.push(request);
      return response(request.method === "GET" ? health : { accepted: true });
    });
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth });
    for (let count = 0; count < 2; count++) await protocol.fetch(`/api/v1/${path}`, post);
    expect(requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)).toEqual([
      "GET /api/v1/health", `POST /api/v1/${path}`, "GET /api/v1/health", `POST /api/v1/${path}`,
    ]);
    expect(requests.every((request) => request.headers.get(header) === "2")).toBe(true);
    expect(requests.filter((request) => request.method === "POST").map((request) => request.headers.get("Idempotency-Key"))).toEqual(["same-intent", "same-intent"]);
  });

  it.each(["/api/v1/health", "/api/v1/health/symbols/003043.SZ", "/api/v1/dashboard", "/api/v1/symbols", "/api/v1/symbols/003043.SZ"])("guards changed read %s without an extra preflight", async (path) => {
    const fetchImplementation = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Request(input, init).headers.get(header)).toBe("2");
      return response();
    });
    await createMonitorProtocol({ origin, fetchImplementation, validateHealth }).fetch(path);
    expect(fetchImplementation).toHaveBeenCalledTimes(1);
  });

  it.each(["/api/v1/plan-versions", "/api/v1/ai/extractions", "/api/v1/backtest-runs"])("leaves unchanged command %s unguarded", async (path) => {
    const fetchImplementation = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Request(input, init).headers.has(header)).toBe(false);
      return response({}, null);
    });
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth });
    protocol.requireReload();
    await protocol.fetch(path, post);
    expect(fetchImplementation).toHaveBeenCalledTimes(1);
  });

  it("leaves the read-only legacy maintenance preview unguarded", async () => {
    const fetchImplementation = vi.fn(async () => response({}, null));
    await createMonitorProtocol({ origin, fetchImplementation, validateHealth }).fetch("/api/v1/system/legacy-plan-invalidation");
    expect(fetchImplementation).toHaveBeenCalledTimes(1);
  });

  it.each(["old-header", "invalid-health", "failed-health", "network"])("sends zero POST calls when preflight has %s", async (failure) => {
    const requests: Request[] = [];
    const fetchImplementation: typeof fetch = vi.fn(async (input, init) => {
      requests.push(new Request(input, init));
      if (failure === "network") throw new TypeError("offline");
      if (failure === "old-header") return response(health, null);
      if (failure === "failed-health") return response({ error: { code: "SERVICE_UNAVAILABLE", message: "Unavailable", requestId: "a".repeat(32) } }, "2", 503);
      return response({ monitorContractVersion: 2 });
    });
    await expect(createMonitorProtocol({ origin, fetchImplementation, validateHealth }).fetch("/api/v1/plan-activations", post)).rejects.toThrow();
    expect(requests.map((request) => request.method)).toEqual(["GET"]);
  });

  it.each(["invalidate", "abort", "reload"])("cancels a pending preflight on %s even if fetch ignores abort", async (action) => {
    let finish!: (value: Response) => void;
    const fetchImplementation = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth });
    const controller = new AbortController();
    const pending = protocol.fetch("/api/v1/plan-activations", { ...post, signal: controller.signal });
    if (action === "invalidate") protocol.invalidate();
    else if (action === "abort") controller.abort();
    else protocol.requireReload();
    finish(response());
    await expect(pending).rejects.toThrow();
    expect(fetchImplementation).toHaveBeenCalledTimes(1);
  });

  it("does not let a stale successful guarded read escape after epoch replacement", async () => {
    let finish!: (value: Response) => void;
    const protocol = createMonitorProtocol({ origin, validateHealth, fetchImplementation: vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })) });
    const pending = protocol.fetch("/api/v1/dashboard");
    protocol.invalidate();
    finish(response());
    await expect(pending).rejects.toThrow();
  });

  it("rejects cross-origin requests without fetching or sending preflight", async () => {
    const fetchImplementation = vi.fn();
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth });
    await expect(protocol.fetch("http://localhost:32109/api/v1/plan-activations", post)).rejects.toThrow();
    expect(fetchImplementation).not.toHaveBeenCalled();
  });

  it("rejects an oversized preflight without hanging on an unread response clone", async () => {
    const fetchImplementation = vi.fn(async () => new Response(new ReadableStream(), {
      headers: { [header]: "2", "Content-Length": String(4 * 1024 * 1024 + 1) },
    }));
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth });
    await expect(protocol.fetch("/api/v1/plan-activations", post)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    expect(fetchImplementation).toHaveBeenCalledTimes(1);
  }, 1_000);

  it.each(["/api/v1/plan-activations/", "/api/v1/%70lan-activations"])("preflights equivalent route spelling %s and refuses redirects", async (path) => {
    const requests: Request[] = [];
    const fetchImplementation: typeof fetch = vi.fn(async (input, init) => {
      const request = new Request(input, init);
      requests.push(request);
      return response(request.method === "GET" ? health : {});
    });
    await createMonitorProtocol({ origin, fetchImplementation, validateHealth }).fetch(path, post);
    expect(requests.map((request) => request.method)).toEqual(["GET", "POST"]);
    expect(requests.every((request) => request.redirect === "error" && request.cache === "no-store")).toBe(true);
  });

  it("rejects duplicate outgoing version headers without any request", async () => {
    const fetchImplementation = vi.fn();
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth });
    await expect(protocol.fetch("/api/v1/dashboard", { headers: [[header, "2"], [header, "2"]] })).rejects.toMatchObject({ code: "RELOAD_REQUIRED" });
    expect(fetchImplementation).not.toHaveBeenCalled();
  });

  it("keeps a normal command conflict available to the existing safe error adapter", async () => {
    const error = { error: { code: "CONFLICT", message: "Changed revision", requestId: "a".repeat(32) } };
    const fetchImplementation: typeof fetch = vi.fn(async (input, init) => new Request(input, init).method === "GET" ? response() : response(error, "2", 409));
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth });
    const result = await protocol.fetch("/api/v1/plan-activations", post);
    expect(result.status).toBe(409);
    expect(await result.json()).toEqual(error);
    expect(protocol.state).toBe("COMPATIBLE");
  });

  it("does not accept a health validator that throws or returns a truthy non-boolean", async () => {
    for (const validator of [() => { throw new Error("invalid schema"); }, () => "yes" as unknown as boolean]) {
      const fetchImplementation = vi.fn(async () => response());
      await expect(createMonitorProtocol({ origin, fetchImplementation, validateHealth: validator }).fetch("/api/v1/plan-activations", post)).rejects.toThrow();
      expect(fetchImplementation).toHaveBeenCalledTimes(1);
    }
  });

  it("aborts other guarded requests when one response proves a mismatch", async () => {
    let pendingSignal: AbortSignal | undefined;
    let finish!: (value: Response) => void;
    const fetchImplementation: typeof fetch = vi.fn(async (input, init) => {
      const request = new Request(input, init);
      if (new URL(request.url).pathname === "/api/v1/dashboard") {
        pendingSignal = request.signal;
        return new Promise<Response>((resolve) => { finish = resolve; });
      }
      return response(health, null);
    });
    const protocol = createMonitorProtocol({ origin, fetchImplementation, validateHealth });
    const pending = protocol.fetch("/api/v1/dashboard");
    await expect(protocol.fetch("/api/v1/health")).rejects.toMatchObject({ code: "RELOAD_REQUIRED" });
    expect(pendingSignal?.aborted).toBe(true);
    finish(response());
    await expect(pending).rejects.toMatchObject({ code: "RELOAD_REQUIRED" });
  });
});
