import type { DailyReviewPreview, PlanVersionView, ConfiguredAIRuntimeView } from "./generated";
import { resolveApiFetch } from "./context";
import { requestJson, invalidResponse } from "./transport";
import type { Schema } from "../components/plans/planSchema";
import { validP2Preview } from "./p2Pretrade";
import { validExceptionResponse } from "./planExceptions";

export interface PlanEditorContract {
  candidateSchema: Schema;
  linkedCandidateSchema?: Schema;
  linkedPolicyDefinitions?: Record<string, string>;
  pretradeCandidateSchema?: Schema;
  exceptionCandidateSchema?: Schema;
  exceptionPolicyDefinitions?: Record<string, string>;
  operationSchemas: Record<string, Schema>;
}

export function isConditionPlanJson(value: string): boolean {
  try {
    const document: unknown = JSON.parse(value);
    return isRecord(document) && document.execution_mode === "CONDITION_PLAN" &&
      (document.schema_version === 5 && document.execution_version === "condition-plan-v1" ||
       document.schema_version === 6 && document.execution_version === "condition-plan-v2" ||
       document.schema_version === 7 && document.execution_version === "condition-plan-v3" ||
       document.schema_version === 8 && document.execution_version === "condition-plan-v4");
  } catch { return false; }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function validResponse(url: string, value: unknown): boolean {
  if (!isRecord(value)) return false;
  const path = url.split("?")[0] ?? url;
  if (path.endsWith("/plan-economics-previews")) return validP2Preview(value);
  if (path.includes("/plan-exception-")) return validExceptionResponse(path, value);
  if (path.endsWith("/plan-editor-schema")) return isRecord(value.candidateSchema) && isRecord(value.operationSchemas);
  if (path.endsWith("/ai-runtime")) return typeof value.providerId === "string" && typeof value.configured === "boolean";
  if (path.endsWith("/plan-versions")) return Array.isArray(value.items) && Number.isSafeInteger(value.total);
  if (/\/plan-versions\//.test(path) || path.endsWith("/plan-drafts")) {
    return typeof value.id === "string" && typeof value.planJson === "string" && typeof value.sourceText === "string" &&
      typeof value.canActivate === "boolean" && ["DRAFT", "ACTIVE", "SUPERSEDED"].includes(String(value.status));
  }
  if (path.endsWith("/plan-review-previews")) return typeof value.candidateJson === "string" && isConditionPlanJson(value.candidateJson) &&
    isRecord(value.review) && typeof value.review.content_hash === "string" && isRecord(value.review.mapping) && Array.isArray(value.review.issues);
  if (path.endsWith("/plan-extractions")) return typeof value.operationId === "string" && value.status === "QUEUED";
  if (/\/plan-extractions\//.test(path)) return typeof value.id === "string" && typeof value.status === "string" &&
    (value.status !== "SUCCEEDED" || (typeof value.draftPlanJson === "string" && isConditionPlanJson(value.draftPlanJson) && isRecord(value.dailyMapping)));
  if (path.includes("/plan-activation-states/") || path.endsWith("/plan-activations") || path.endsWith("/plan-deactivations"))
    return typeof value.active === "boolean" && Number.isSafeInteger(value.revision);
  if (path.endsWith("/plan-review-confirmations")) return typeof value.canActivate === "boolean" && Number.isSafeInteger(value.revision);
  if (path.endsWith("/simulation-position-inventory")) return ["CURRENT", "UNKNOWN", "UNSUPPORTED"].includes(String(value.status)) ||
    (isRecord(value.snapshot) && typeof value.snapshot.known === "boolean" && Number.isSafeInteger(value.snapshot.revision));
  if (path.includes("/plan-runtime/")) return ["CURRENT", "AWAITING_EVALUATION", "INACTIVE", "UNSUPPORTED"].includes(String(value.status)) &&
    (value.snapshot === null || (isRecord(value.snapshot) && Array.isArray(value.snapshot.signals) && Array.isArray(value.snapshot.risks)));
  if (path.endsWith("/simulated-trades")) return typeof value.simulationId === "string" && ["BUY", "SELL"].includes(String(value.side)) &&
    Number.isSafeInteger(value.quantity) && Number(value.quantity) > 0 && Number(value.quantity) % 100 === 0 && Number.isSafeInteger(value.priceFen);
  return path.endsWith("/plan-review-supplements") || path.endsWith("/plan-facts") ||
    path.endsWith("/simulation-position-confirmations") || path.endsWith("/plan-risk-reassessments");
}

/** One validated transport for the plan editor, source review and simulation authority. */
export function createConditionPlanApi(fetcher: typeof fetch = resolveApiFetch(), signal?: AbortSignal) {
  const pendingKeys = new Map<string, string>();
  async function request<T>(url: string, body?: object, suppliedKey?: string): Promise<T> {
    const identity = `${url}:${JSON.stringify(body)}`;
    const key = suppliedKey ?? pendingKeys.get(identity) ?? crypto.randomUUID();
    if (body) pendingKeys.set(identity, key);
    const result = await requestJson(fetcher, url, {
      method: body ? "POST" : "GET", ...(signal ? { signal } : {}),
      headers: body ? { Accept: "application/json", "Content-Type": "application/json", "Idempotency-Key": key } : { Accept: "application/json" },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!validResponse(url, result.body)) throw invalidResponse(result.status);
    pendingKeys.delete(identity);
    return result.body as T;
  }
  return {
    request,
    getEditor: () => request<PlanEditorContract>("/api/v1/plan-editor-schema"),
    getRuntime: () => request<ConfiguredAIRuntimeView>("/api/v1/ai-runtime"),
    getVersion: (id: string) => request<PlanVersionView>(`/api/v1/plan-versions/${encodeURIComponent(id)}`),
    preview: (body: object) => request<DailyReviewPreview>("/api/v1/plan-review-previews", body),
  };
}
