import { ApiClientError, invalidResponse, requestJson } from "../api/transport";

export const MONITOR_CONTRACT_VERSION = 2;
export const MONITOR_VERSION_HEADER = "X-Monitor-Contract-Version";

const guardedCommands = new Set([
  "/api/v1/plan-activations",
  "/api/v1/plan-deactivations",
  "/api/v1/position-lots",
  "/api/v1/position-lot-closures",
  "/api/v1/position-inventory-closures",
  "/api/v1/position-inventory-confirmations",
  "/api/v1/manual-event-risk-confirmations",
  "/api/v1/alert-acknowledgements",
  "/api/v1/diagnostic-evaluations",
  "/api/v1/system/legacy-plan-invalidation",
]);
const guardedRead = /^\/api\/v1\/(?:health(?:\/symbols\/[^/]+)?|dashboard|symbols(?:\/[^/]+)?|explicit-plan-runtime\/[^/]+)$/;

export type MonitorProtocolState = "NEGOTIATING" | "COMPATIBLE" | "RELOAD_REQUIRED";

export class MonitorProtocolError extends Error {
  constructor(readonly code: "RELOAD_REQUIRED" | "CANCELLED" | "INVALID_ORIGIN") {
    super(code === "RELOAD_REQUIRED" ? "请重新加载应用以使用监控协议 2。" : "监控请求已取消。");
    this.name = "MonitorProtocolError";
  }
}

export interface MonitorProtocolOptions {
  readonly origin: string;
  readonly fetchImplementation?: typeof fetch;
  /** Must validate the complete authoritative health schema, not just its version. */
  readonly validateHealth: (body: unknown) => boolean;
  /** Clear actionable UI and stop stream/reconnect ownership when called. */
  readonly onReloadRequired?: () => void;
}

export interface MonitorProtocol {
  readonly state: MonitorProtocolState;
  readonly epoch: number;
  readonly fetch: typeof fetch;
  /** Navigation, reconnect and generation replacement each revoke pending work. */
  invalidate(): void;
  /** Also used for a socket's MONITOR_CONTRACT_MISMATCH close. Terminal until reload. */
  requireReload(): void;
}

export function createMonitorProtocol(options: MonitorProtocolOptions): MonitorProtocol {
  if (typeof options.validateHealth !== "function") throw new TypeError("A health validator is required");
  const base = new URL(options.origin);
  if (!/^https?:$/.test(base.protocol) || base.origin !== options.origin || base.username || base.password) {
    throw new MonitorProtocolError("INVALID_ORIGIN");
  }
  const fetchImplementation = options.fetchImplementation ?? globalThis.fetch.bind(globalThis);
  const active = new Set<AbortController>();
  let state: MonitorProtocolState = "NEGOTIATING";
  let epoch = 0;

  function invalidate(): void {
    epoch += 1;
    for (const controller of active) controller.abort();
    active.clear();
    if (state !== "RELOAD_REQUIRED") state = "NEGOTIATING";
  }

  function requireReload(): void {
    if (state === "RELOAD_REQUIRED") return;
    state = "RELOAD_REQUIRED";
    invalidate();
    options.onReloadRequired?.();
  }

  function mismatch(): never {
    requireReload();
    throw new MonitorProtocolError("RELOAD_REQUIRED");
  }

  function requireCurrent(revision: number, signal: AbortSignal): void {
    if (state === "RELOAD_REQUIRED") throw new MonitorProtocolError("RELOAD_REQUIRED");
    if (revision !== epoch || signal.aborted) throw new MonitorProtocolError("CANCELLED");
  }

  async function inspect(response: Response, projection: boolean, health: boolean): Promise<void> {
    if (response.headers.get(MONITOR_VERSION_HEADER) !== "2") mismatch();
    try {
      // Shared bounded parsing and safe error details also apply at this boundary.
      const { body } = await requestJson(async () => inspectionResponse(response), "protocol-response");
      if (projection && (!isRecord(body) || body.monitorContractVersion !== 2)) mismatch();
      if (health && options.validateHealth(body) !== true) throw invalidResponse(response.status);
    } catch (error) {
      if (error instanceof ApiClientError && error.details.some((detail) => detail.code === "MONITOR_CONTRACT_MISMATCH")) mismatch();
      // A normal command/read error remains available to its existing adapter.
      if (!response.ok && error instanceof ApiClientError && error.code !== "INVALID_RESPONSE" && !health) return;
      throw error;
    }
  }

  const guardedFetch: typeof fetch = async (input, init) => {
    const inputUrl = input instanceof Request ? input.url : String(input);
    const url = new URL(inputUrl, base);
    if (url.origin !== base.origin || url.username || url.password) throw new MonitorProtocolError("INVALID_ORIGIN");
    const request = input instanceof Request ? new Request(input, init) : new Request(url, init);
    // FastAPI can redirect a trailing slash or decode an escaped route segment.
    const path = decodeURIComponent(url.pathname).replace(/\/+$/, "");
    const command = request.method === "POST" && guardedCommands.has(path);
    const projection = request.method === "GET" && guardedRead.test(path);
    if (!command && !projection) return fetchImplementation(request);

    const controller = new AbortController();
    const revision = epoch;
    const abort = () => controller.abort();
    if (request.signal.aborted) abort();
    request.signal.addEventListener("abort", abort, { once: true });
    active.add(controller);
    try {
      requireCurrent(revision, controller.signal);
      const headers = new Headers(request.headers);
      const suppliedVersion = headers.get(MONITOR_VERSION_HEADER);
      if (suppliedVersion !== null && suppliedVersion !== "2") mismatch();
      headers.set(MONITOR_VERSION_HEADER, "2");
      if (command) {
        const preflight = await fetchImplementation(new Request(new URL("/api/v1/health", base), {
          method: "GET", headers: { Accept: "application/json", [MONITOR_VERSION_HEADER]: "2" },
          cache: "no-store", redirect: "error", signal: controller.signal,
        }));
        requireCurrent(revision, controller.signal);
        await inspect(preflight, true, true);
        requireCurrent(revision, controller.signal);
      }
      const response = await fetchImplementation(new Request(request, {
        headers, cache: "no-store", redirect: "error", signal: controller.signal,
      }));
      requireCurrent(revision, controller.signal);
      await inspect(response, projection, projection && path === "/api/v1/health");
      requireCurrent(revision, controller.signal);
      state = "COMPATIBLE";
      return response;
    } finally {
      request.signal.removeEventListener("abort", abort);
      active.delete(controller);
    }
  };

  return Object.freeze({
    get state() { return state; },
    get epoch() { return epoch; },
    fetch: guardedFetch,
    invalidate,
    requireReload,
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function inspectionResponse(response: Response): Response {
  const clone = response.clone();
  if (clone.body === null) return clone;
  const reader = clone.body.getReader();
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      const chunk = await reader.read();
      if (chunk.done) controller.close();
      else controller.enqueue(chunk.value);
    },
    async cancel(reason) {
      // Cancelling only one tee branch waits for the unread original forever.
      // A rejected bounded parse must cancel both branches together.
      await Promise.allSettled([reader.cancel(reason), response.body?.cancel(reason)]);
    },
  });
  return new Response(body, { status: clone.status, statusText: clone.statusText, headers: clone.headers });
}
