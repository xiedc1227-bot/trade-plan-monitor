import type { ReviewedPlanLibraryPage, ReviewedPlanReference, PreparedPlanCompositionInput, CollectionPreparationFrozenView } from "./generated-runtime-status";
import { resolveApiFetch } from "./context";
import { invalidResponse } from "./transport";
import { requestBacktestJson as requestJson } from "./backtestRead";
import { validCollectionFrozen } from "./preparationReview";
import { isCalendarDate } from "./shanghaiTime";

const BASE = "/api/v1/backtest-plan-library";
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const identifier = (v: unknown): v is string => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(v);
const digest = (v: unknown) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
function reference(v: unknown): v is ReviewedPlanReference {
  return object(v) && identifier(v.preparation_id) && digest(v.manifest_hash);
}
function identity(v: unknown): boolean {
  return v == null || object(v) && Object.keys(v).length === 4 && digest(v.sourceHash) && digest(v.planHash) &&
    identifier(v.planVersionId) && digest(v.reviewedVersionHash);
}
export function createPlanLibraryApi(fetcher: typeof fetch = resolveApiFetch()) {
  return {
    async list(offset = 0, signal?: AbortSignal): Promise<ReviewedPlanLibraryPage> {
      const result = await requestJson(fetcher, `${BASE}?offset=${offset}&limit=100`, {
        method: "GET", cache: "no-store", credentials: "same-origin", redirect: "error", ...(signal ? { signal } : {}),
      });
      const v = result.body;
      if (result.status !== 200 || result.headers.get("Cache-Control") !== "no-store" || !object(v) ||
          v.offset !== offset || v.limit !== 100 || !Number.isSafeInteger(v.total) || Number(v.total) < 0 ||
          !Array.isArray(v.items) || v.items.length > 100 || offset + v.items.length > Number(v.total) ||
          v.items.some(item => !object(item) || !identifier(item.preparationId) || !digest(item.manifestHash) ||
            !isCalendarDate(item.effectiveTradeDate) || typeof item.name !== "string" || typeof item.symbol !== "string" ||
            !identity(item.identity) || item.reviewedBase != null && !reference(item.reviewedBase))) throw invalidResponse(result.status);
      return v as unknown as ReviewedPlanLibraryPage;
    },
    async compose(command: PreparedPlanCompositionInput, key: string, signal?: AbortSignal): Promise<CollectionPreparationFrozenView> {
      const result = await requestJson(fetcher, `${BASE}/compositions`, {
        method: "POST", cache: "no-store", credentials: "same-origin", redirect: "error", ...(signal ? { signal } : {}),
        headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(command),
      });
      if (result.status !== 201 || result.headers.get("Cache-Control") !== "no-store" || !validCollectionFrozen(result.body) ||
          result.body.preparationId !== command.preparation_id || result.body.versions.length !== command.plans.length) throw invalidResponse(result.status);
      return result.body;
    },
  };
}
export type PlanLibraryApi = ReturnType<typeof createPlanLibraryApi>;
