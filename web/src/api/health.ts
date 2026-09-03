import type {
  ProviderHealthView,
  RuntimeHealthResponse,
} from "./generated";
import { isShanghaiDateTime, shanghaiDateTimeKey } from "./shanghaiTime";
import { ApiClientError, invalidResponse, requestJson } from "./transport";

export interface HealthApi {
  getHealth(options?: { signal?: AbortSignal }): Promise<RuntimeHealthResponse>;
}

const runtimeStatuses = new Set(["STARTING", "RUNNING", "DEGRADED", "STOPPING", "STOPPED"]);
const resourceStatuses = new Set(["UNVERIFIED", "READY", "DEGRADED", "ERROR", "STOPPED"]);
const providerStatuses = new Set([
  "UNVERIFIED",
  "READY",
  "BLOCKED_PERMISSION",
  "RATE_LIMITED",
  "ERROR",
]);

export function createHealthApi(
  fetchImplementation: typeof fetch = globalThis.fetch.bind(globalThis),
): HealthApi {
  return Object.freeze({
    async getHealth(options?: { signal?: AbortSignal }) {
      const request: RequestInit = {
        headers: { Accept: "application/json" },
        method: "GET",
      };
      if (options?.signal !== undefined) {
        request.signal = options.signal;
      }
      const { body, status } = await requestJson(
        fetchImplementation,
        "/api/v1/health",
        request,
      );
      try {
        if (!isRuntimeHealthResponse(body)) {
          throw invalidResponse(status);
        }
        return body;
      } catch (error) {
        if (error instanceof ApiClientError) {
          throw error;
        }
        throw invalidResponse(status);
      }
    },
  });
}

function isRuntimeHealthResponse(value: unknown): value is RuntimeHealthResponse {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "cooldownUntil",
      "database",
      "delivery",
      "executor",
      "gaps",
      "lastCompletedMinute",
      "lastCompletedMinuteAgeSeconds",
      "latestEvaluationAgeSeconds",
      "latestEvaluationAt",
      "nextPollAt",
      "nextRetryAt",
      "observedAt",
      "providers",
      "readOnly",
      "startedAt",
      "status",
      "stoppedAt",
    ]) ||
    !hasKeys(value, [
      "cooldownUntil",
      "database",
      "delivery",
      "executor",
      "lastCompletedMinute",
      "lastCompletedMinuteAgeSeconds",
      "latestEvaluationAgeSeconds",
      "latestEvaluationAt",
      "nextPollAt",
      "nextRetryAt",
      "observedAt",
      "readOnly",
      "startedAt",
      "status",
      "stoppedAt",
    ])
  ) {
    return false;
  }

  const status = value.status;
  const stoppedAt = value.stoppedAt;
  const startedAt = value.startedAt;
  const observedAt = value.observedAt;
  const ageFactsMatch =
    matchesAge(value.lastCompletedMinute, value.lastCompletedMinuteAgeSeconds, observedAt) &&
    matchesAge(value.latestEvaluationAt, value.latestEvaluationAgeSeconds, observedAt);
  const lifecycleFactsMatch =
    shanghaiDateTimeKey(startedAt) <= shanghaiDateTimeKey(observedAt) &&
    (status !== "STOPPED") === (stoppedAt === null) &&
    (stoppedAt === null ||
      (shanghaiDateTimeKey(startedAt) <= shanghaiDateTimeKey(stoppedAt) &&
        shanghaiDateTimeKey(stoppedAt) <= shanghaiDateTimeKey(observedAt)));

  return (
    isNullableDateTime(value.cooldownUntil) &&
    isDatabase(value.database) &&
    isDelivery(value.delivery) &&
    isExecutor(value.executor) &&
    (value.gaps === undefined ||
      (Array.isArray(value.gaps) && value.gaps.length <= 2_400 && value.gaps.every(isGap))) &&
    isOrderedGaps(value.gaps) &&
    isNullableDateTime(value.lastCompletedMinute) &&
    isNullableNonnegativeInteger(value.lastCompletedMinuteAgeSeconds) &&
    isNullableNonnegativeInteger(value.latestEvaluationAgeSeconds) &&
    isNullableDateTime(value.latestEvaluationAt) &&
    isNullableDateTime(value.nextPollAt) &&
    isNullableDateTime(value.nextRetryAt) &&
    isShanghaiDateTime(value.observedAt) &&
    (value.providers === undefined ||
      (Array.isArray(value.providers) && value.providers.length <= 5 && value.providers.every(isProvider))) &&
    isUniqueProviders(value.providers, observedAt) &&
    typeof value.readOnly === "boolean" &&
    isShanghaiDateTime(value.startedAt) &&
    typeof status === "string" &&
    runtimeStatuses.has(status) &&
    isNullableDateTime(stoppedAt) &&
    (status !== "RUNNING" || value.readOnly === false) &&
    (status !== "DEGRADED" || value.readOnly === true) &&
    ageFactsMatch &&
    lifecycleFactsMatch
  );
}

function isOrderedGaps(value: unknown): boolean {
  if (value === undefined) {
    return true;
  }
  if (!Array.isArray(value)) {
    return false;
  }
  return value.every((gap, index) => {
    if (index === 0) {
      return true;
    }
    const previous = value[index - 1];
    if (!isRecord(previous) || !isRecord(gap)) {
      return false;
    }
    return `${String(previous.symbol)}:${String(previous.barEnd)}` <
      `${String(gap.symbol)}:${String(gap.barEnd)}`;
  });
}

function isUniqueProviders(value: unknown, observedAt: unknown): boolean {
  if (value === undefined) {
    return true;
  }
  if (!Array.isArray(value) || !isShanghaiDateTime(observedAt)) {
    return false;
  }
  const capabilities = value.map((provider) =>
    isRecord(provider) ? provider.capability : undefined,
  );
  return (
    new Set(capabilities).size === capabilities.length &&
    value.every(
      (provider) =>
        isRecord(provider) &&
        isShanghaiDateTime(provider.checkedAt) &&
        shanghaiDateTimeKey(provider.checkedAt) <= shanghaiDateTimeKey(observedAt),
    )
  );
}

function matchesAge(
  timestamp: unknown,
  ageSeconds: unknown,
  observedAt: unknown,
): boolean {
  if (timestamp === null || ageSeconds === null) {
    return timestamp === null && ageSeconds === null;
  }
  return (
    isShanghaiDateTime(timestamp) &&
    isNonnegativeInteger(ageSeconds) &&
    isShanghaiDateTime(observedAt) &&
    shanghaiDateTimeKey(observedAt) >= shanghaiDateTimeKey(timestamp) &&
    (shanghaiDateTimeKey(observedAt) - shanghaiDateTimeKey(timestamp)) / 1_000_000n ===
      BigInt(ageSeconds)
  );
}

function isDatabase(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["errorCode", "lastBackupAt", "lastCheckpointAt", "status", "walStatus"]) &&
    isNullableSafeCode(value.errorCode) &&
    isNullableDateTime(value.lastBackupAt) &&
    isNullableDateTime(value.lastCheckpointAt) &&
    isResourceStatus(value.status) &&
    isResourceStatus(value.walStatus) &&
    ((value.status === "READY" && value.walStatus === "READY") ||
      (isNeutralResource(value.status) && isNeutralResource(value.walStatus))
      ? value.errorCode === null
      : value.errorCode !== null)
  );
}

function isDelivery(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, [
      "errorCode",
      "failedCount",
      "lastDeliveredAt",
      "nextRetryAt",
      "pendingCount",
      "status",
    ]) &&
    isNullableSafeCode(value.errorCode) &&
    isNonnegativeInteger(value.failedCount) &&
    isNullableDateTime(value.lastDeliveredAt) &&
    isNullableDateTime(value.nextRetryAt) &&
    isNonnegativeInteger(value.pendingCount) &&
    isResourceStatus(value.status) &&
    ((isNeutralDelivery(value.status) &&
      value.failedCount === 0 &&
      value.nextRetryAt === null &&
      value.errorCode === null) ||
      (!isNeutralDelivery(value.status) && value.errorCode !== null))
  );
}

function isExecutor(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["activeCount", "maxWorkers", "waitingCount"]) &&
    isNonnegativeInteger(value.activeCount) &&
    isPositiveInteger(value.maxWorkers) &&
    value.maxWorkers <= 2 &&
    isNonnegativeInteger(value.waitingCount) &&
    value.waitingCount <= 32 &&
    value.activeCount <= value.maxWorkers
  );
}

function isGap(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["barEnd", "symbol"]) &&
    isShanghaiDateTime(value.barEnd) &&
    typeof value.symbol === "string" &&
    /^\d{6}\.(?:BJ|SH|SZ)$/.test(value.symbol)
  );
}

function isProvider(value: unknown): value is ProviderHealthView {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["capability", "checkedAt", "errorCode", "latencyMs", "nextRetryAt", "status"]) &&
    isHealthName(value.capability) &&
    isShanghaiDateTime(value.checkedAt) &&
    isNullableSafeCode(value.errorCode) &&
    isNonnegativeInteger(value.latencyMs) &&
    isNullableDateTime(value.nextRetryAt) &&
    typeof value.status === "string" &&
    providerStatuses.has(value.status) &&
    ((value.status === "READY" || value.status === "UNVERIFIED")
      ? value.errorCode === null && value.nextRetryAt === null
      : value.errorCode !== null &&
        (value.nextRetryAt === null ||
          shanghaiDateTimeKey(value.nextRetryAt) >= shanghaiDateTimeKey(value.checkedAt)))
  );
}

function isResourceStatus(value: unknown): boolean {
  return typeof value === "string" && resourceStatuses.has(value);
}

function isNeutralResource(value: unknown): boolean {
  return value === "UNVERIFIED" || value === "STOPPED";
}

function isNeutralDelivery(value: unknown): boolean {
  return value === "READY" || value === "UNVERIFIED" || value === "STOPPED";
}

function isNullableDateTime(value: unknown): boolean {
  return value === null || isShanghaiDateTime(value);
}

function isNullableNonnegativeInteger(value: unknown): boolean {
  return value === null || isNonnegativeInteger(value);
}

function isNullableSafeCode(value: unknown): boolean {
  return value === null || (typeof value === "string" && /^[A-Z][A-Z0-9_]{0,63}$/.test(value));
}

function isHealthName(value: unknown): value is string {
  return typeof value === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isNonnegativeInteger(value) && value > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => Object.hasOwn(value, key));
}

function hasOnlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const allowed = new Set(keys);
  return Object.keys(value).every((key) => allowed.has(key));
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && hasKeys(value, keys);
}
