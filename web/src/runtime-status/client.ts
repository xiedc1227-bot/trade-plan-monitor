import { invalidResponse, requestJson } from "../api/transport";
import { isRuntimeDashboard, isRuntimeHealth, isRuntimeSymbolCollection, isRuntimeSymbolDetail, isRuntimeSymbolHealth } from "./validators";
import type { MonitorProtocol } from "./protocol";

export function createRuntimeApi(protocol: MonitorProtocol) {
  async function read<T>(path: string, validate: (body: unknown) => body is T, signal?: AbortSignal): Promise<T> {
    const { body, status } = await requestJson(protocol.fetch, path, { method: "GET", headers: { Accept: "application/json" }, ...(signal ? { signal } : {}) });
    if (!validate(body)) throw invalidResponse(status);
    return body;
  }
  return Object.freeze({
    getDashboard: (signal?: AbortSignal) => read("/api/v1/dashboard", isRuntimeDashboard, signal),
    getHealth: (signal?: AbortSignal) => read("/api/v1/health", isRuntimeHealth, signal),
    getSymbols: (offset = 0, limit = 100, signal?: AbortSignal) => read(`/api/v1/symbols?offset=${offset}&limit=${limit}`, isRuntimeSymbolCollection, signal),
    getSymbol: (symbol: string, signal?: AbortSignal) => read(`/api/v1/symbols/${encodeURIComponent(symbol)}`, (body) => isRuntimeSymbolDetail(body, symbol), signal),
    getSymbolHealth: (symbol: string, signal?: AbortSignal) => read(`/api/v1/health/symbols/${encodeURIComponent(symbol)}`, (body) => isRuntimeSymbolHealth(body, symbol), signal),
  });
}
export type RuntimeApi = ReturnType<typeof createRuntimeApi>;
