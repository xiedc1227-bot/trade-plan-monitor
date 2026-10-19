import type { WorkbenchSelectionCommand, WorkbenchSelectionView } from "./generated";
import { resolveApiFetch } from "./context";
import { isConditionPlanJson } from "./conditionPlans";
import { account } from "./preparationReview";
import { isShanghaiDateTime, isCalendarDate, shanghaiDateTimeKey } from "./shanghaiTime";
import { invalidResponse, requestJson } from "./transport";

const BASE = "/api/v1/backtest-plan-selections";
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const hash = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const uuid = (value: unknown) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
function contextIdentity(context: WorkbenchSelectionCommand["context"]) {
  const account = context.initialAccount;
  const value = { ...context, availableAt: context.availableAt == null ? null : shanghaiDateTimeKey(context.availableAt),
    informationCutoff: shanghaiDateTimeKey(context.informationCutoff), initialAccount: { ...account,
      snapshot_at: shanghaiDateTimeKey(account.snapshot_at),
      lots: [...account.lots].sort((a, b) => {
        const left = `${a.bucket}:${a.lot_key}`, right = `${b.bucket}:${b.lot_key}`;
        return left < right ? -1 : left > right ? 1 : 0;
      }),
      opening_mark: account.opening_mark == null ? null : { ...account.opening_mark,
        price_at: shanghaiDateTimeKey(account.opening_mark.price_at), available_at: shanghaiDateTimeKey(account.opening_mark.available_at) },
    } };
  return JSON.stringify(value, (_key, item: unknown) => typeof item === "bigint" ? item.toString() : record(item) ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) : item);
}
export function validPlanSelection(value: unknown): value is WorkbenchSelectionView {
  if (!record(value) || value.schemaVersion !== "workbench-loop-selection-v1" ||
      !uuid(value.selectionId) || !hash(value.selectionHash) || !record(value.frozen)) return false;
  const frozen = value.frozen;
  if (frozen.schema_version !== value.schemaVersion || frozen.selection_id !== value.selectionId ||
      !isShanghaiDateTime(frozen.confirmed_at) || !record(frozen.context) || !record(frozen.reviewed) || !record(frozen.version)) return false;
  const context = frozen.context, reviewed = frozen.reviewed, version = frozen.version;
  if (!record(reviewed.reference) || !record(version.review) || !record(version.snapshot)) return false;
  const ref = reviewed.reference;
  return ref.origin === "WORKBENCH" && uuid(ref.planVersionId) && uuid(ref.reviewId) &&
    [ref.planHash, ref.contentHash, ref.sourceHash, ref.reviewEvidenceHash, version.plan_hash].every(hash) &&
    Number.isSafeInteger(ref.reviewRevision) && Number(ref.reviewRevision) >= 1 &&
    version.version_id === ref.planVersionId && version.evidence_hash === ref.reviewEvidenceHash &&
    version.review.confirmed === true && version.review.content_hash === ref.contentHash &&
    isShanghaiDateTime(version.review.reviewed_at) && isShanghaiDateTime(version.available_at) &&
    isShanghaiDateTime(version.information_cutoff) && isConditionPlanJson(JSON.stringify(version.snapshot)) &&
    isCalendarDate(context.effectiveTradeDate) && isShanghaiDateTime(context.informationCutoff) &&
    (context.availableAt === null || isShanghaiDateTime(context.availableAt)) &&
    account(context.initialAccount) && context.confirmed === true && typeof context.evidence === "string" && context.evidence.trim().length > 0;
}

export function createPlanSelectionApi(fetcher: typeof fetch = resolveApiFetch()) {
  async function read(method: "GET" | "POST", path: string, body?: WorkbenchSelectionCommand, key?: string) {
    const result = await requestJson(fetcher, path, {
      method, credentials: "same-origin", redirect: "error", cache: "no-store",
      ...(body ? { headers: { "Content-Type": "application/json", "Idempotency-Key": key! }, body: JSON.stringify(body) } : {}),
    });
    if (result.status !== (method === "POST" ? 201 : 200) || !validPlanSelection(result.body)) throw invalidResponse(result.status);
    return result.body;
  }
  return {
    async create(command: WorkbenchSelectionCommand, key: string) {
      const result = await read("POST", BASE, command, key);
      for (const field of ["origin", "planVersionId", "planHash", "contentHash", "sourceHash", "reviewEvidenceHash", "reviewId", "reviewRevision"] as const) {
        if (result.frozen.reviewed.reference[field] !== command.plan[field]) throw invalidResponse(201);
      }
      if (contextIdentity(result.frozen.context) !== contextIdentity(command.context)) throw invalidResponse(201);
      return result;
    },
    async get(id: string) {
      if (!uuid(id)) throw invalidResponse(0);
      const result = await read("GET", `${BASE}/${encodeURIComponent(id)}`);
      if (result.selectionId !== id) throw invalidResponse(200);
      return result;
    },
  };
}
export type PlanSelectionApi = ReturnType<typeof createPlanSelectionApi>;
