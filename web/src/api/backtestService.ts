import type { BacktestServiceControlReceipt, BacktestServiceRecoveryCommand, BacktestServiceStopCommand, BacktestServiceView } from "./generated";
import { resolveApiFetch } from "./context";
import { invalidResponse, requestJson } from "./transport";

export interface BacktestServiceApi {
  getStatus(options?: { signal?: AbortSignal }): Promise<BacktestServiceView>;
  recover(command: BacktestServiceRecoveryCommand, key: string, options?: { signal?: AbortSignal }): Promise<BacktestServiceControlReceipt>;
  stop(command: BacktestServiceStopCommand, key: string, options?: { signal?: AbortSignal }): Promise<BacktestServiceControlReceipt>;
}
const base = "/api/v1/backtest-service";
const states = new Set(["DISABLED", "NOT_INITIALIZED", "STARTING", "READ_READY", "READY", "RECOVERING", "DEGRADED", "STOPPING", "STOPPED"]);
const epoch = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{32}$/.test(value);
const revision = (value: unknown): value is number => Number.isSafeInteger(value) && typeof value === "number" && value >= 0;
function closed(value: unknown, keys: string[]): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) &&
    Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
export function validServiceStatus(value: unknown): value is BacktestServiceView {
  if (!closed(value, ["epoch", "revision", "generation", "state", "canRead", "canSubmit", "canCancel", "canExport", "physicallyDrained", "authorizedJobIds", "reason"])) return false;
  if (!revision(value.revision) || !revision(value.generation) || !states.has(String(value.state)) ||
    !["canRead", "canSubmit", "canCancel", "canExport", "physicallyDrained"].every(key => typeof value[key] === "boolean") ||
    !Array.isArray(value.authorizedJobIds) || value.authorizedJobIds.length > 1 ||
    !value.authorizedJobIds.every(id => typeof id === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(id))) return false;
  if ((value.state === "DISABLED" ? value.epoch !== null : !epoch(value.epoch)) ||
    value.canSubmit && value.state !== "READY" || value.canCancel !== value.canRead || value.canExport !== value.canRead ||
    value.canRead && !["READ_READY", "READY", "DEGRADED"].includes(String(value.state))) return false;
  return value.reason === (value.state === "DEGRADED" ? "SERVICE_REPAIR_REQUIRED" : null);
}

export function createBacktestServiceApi(fetchImplementation: typeof fetch = resolveApiFetch()): BacktestServiceApi {
  async function control(path: string, command: BacktestServiceRecoveryCommand | BacktestServiceStopCommand, key: string, options?: { signal?: AbortSignal }) {
    if (!epoch(command.epoch) || !revision(command.expectedRevision) || key.length < 1 || key.length > 128) throw invalidResponse(0);
    const action = "action" in command ? command.action : "STOP";
    if (!closed(command, "action" in command ? ["epoch", "expectedRevision", "action", "resumeJobIds"] : ["epoch", "expectedRevision"])) throw invalidResponse(0);
    if ("action" in command && (!["RESUME_JOBS", "RETRY_PREPARATION"].includes(action) || !Array.isArray(command.resumeJobIds) || command.resumeJobIds.length > 1 || !command.resumeJobIds.every(id => /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(id)) ||
      (action === "RESUME_JOBS") !== (command.resumeJobIds.length === 1))) throw invalidResponse(0);
    const { body, status, headers } = await requestJson(fetchImplementation, base + path, {
      method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify(command), ...(options?.signal ? { signal: options.signal } : {}),
    });
    if (status !== 202 || headers.get("Location") !== base || headers.get("Retry-After") !== "1" ||
      !closed(body, ["accepted", "action", "epoch", "revision"]) || body.accepted !== true || body.action !== action ||
      body.epoch !== command.epoch || !revision(body.revision) || body.revision !== command.expectedRevision + 1) throw invalidResponse(status);
    return body as BacktestServiceControlReceipt;
  }
  const api: BacktestServiceApi = {
    async getStatus(options?: { signal?: AbortSignal }) {
      const { body, status, headers } = await requestJson(fetchImplementation, base, { method: "GET", headers: { Accept: "application/json" }, ...(options?.signal ? { signal: options.signal } : {}) });
      if (status !== 200 || headers.get("Cache-Control") !== "no-store" || !validServiceStatus(body)) throw invalidResponse(status);
      return body;
    },
    recover: (command, key, options) => control("/recovery-requests", command, key, options),
    stop: (command, key, options) => control("/stop-requests", command, key, options),
  };
  return Object.freeze(api);
}
