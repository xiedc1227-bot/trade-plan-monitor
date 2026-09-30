import type {
  LegacyPlanInvalidateResult,
  LegacyPlanPreviewResponse,
} from "./generated";
import { invalidResponse, requestJson } from "./transport";
import { resolveApiFetch } from "./context";

export interface LegacyPlanApi {
  getPreview(options?: { signal?: AbortSignal }): Promise<LegacyPlanPreviewResponse>;
  invalidate(fingerprint: string): Promise<LegacyPlanInvalidateResult>;
}

const endpoint = "/api/v1/system/legacy-plan-invalidation";
const fingerprintPattern = /^[0-9a-f]{64}$/;
const symbolPattern = /^\d{6}\.(?:BJ|SH|SZ)$/;

export function createLegacyPlanApi(
  fetchImplementation: typeof fetch = resolveApiFetch(),
): LegacyPlanApi {
  return Object.freeze({
    async getPreview(options?: { signal?: AbortSignal }) {
      const request: RequestInit = {
        method: "GET",
        headers: { Accept: "application/json" },
      };
      if (options?.signal !== undefined) request.signal = options.signal;
      const { body, status } = await requestJson(fetchImplementation, endpoint, request);
      if (!isPreview(body)) {
        throw invalidResponse(status);
      }
      return body;
    },
    async invalidate(fingerprint: string) {
      if (!fingerprintPattern.test(fingerprint)) {
        throw invalidResponse(0);
      }
      const { body, status } = await requestJson(fetchImplementation, endpoint, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ fingerprint, confirmation: "INVALIDATE_LEGACY_PLANS" }),
      });
      if (!isResult(body)) {
        throw invalidResponse(status);
      }
      return body;
    },
  });
}

function isPreview(value: unknown): value is LegacyPlanPreviewResponse {
  if (!isRecord(value) || typeof value.available !== "boolean" ||
    !Array.isArray(value.plans) || value.plans.length > 10) {
    return false;
  }
  const validPlans = value.plans.every((item) =>
    isRecord(item) && typeof item.symbol === "string" && symbolPattern.test(item.symbol) &&
    typeof item.planVersionId === "string" && item.planVersionId.length > 0 &&
    item.planVersionId.length <= 128 && typeof item.revision === "number" &&
    Number.isSafeInteger(item.revision) && item.revision >= 0,
  );
  if (!validPlans || new Set(value.plans.map((item) => item.symbol)).size !== value.plans.length) {
    return false;
  }
  return value.available
    ? value.plans.length > 0 && typeof value.fingerprint === "string" &&
      fingerprintPattern.test(value.fingerprint)
    : value.plans.length === 0 && value.fingerprint === null;
}

function isResult(value: unknown): value is LegacyPlanInvalidateResult {
  return isRecord(value) && value.restartRequired === true &&
    Array.isArray(value.symbols) && value.symbols.length > 0 && value.symbols.length <= 10 &&
    value.symbols.every((item) => typeof item === "string" && symbolPattern.test(item));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
