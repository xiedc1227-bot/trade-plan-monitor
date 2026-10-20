import type { BacktestReviewContext, BacktestReviewSelector } from "./generated";
import { validLoopEvent, validScheduledEvent, validLoopFill } from "./monitorLoopValues";
import { requestBacktestJson } from "./backtestRead";
import { invalidResponse } from "./transport";
import { isShanghaiDateTime } from "./shanghaiTime";

export type ReviewSelection = { fillId: string } | { eventId: string } | { sequence: number };
export type ReviewRelation = BacktestReviewContext["relation"];
export interface ReviewQuery {
  selector: ReviewSelection;
  relation: ReviewRelation;
  cursor?: string;
  limit?: number;
}
export interface BacktestReviewApi {
  getContext(runId: string, query: ReviewQuery, signal?: AbortSignal): Promise<BacktestReviewContext>;
}

const record = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const hash = (v: unknown) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
export const validReviewCursor = (v: unknown): v is string =>
  typeof v === "string" && v.length <= 512 && /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(v);
export function validReviewSelection(value: unknown): value is ReviewSelection {
  if (!record(value) || Object.keys(value).length !== 1) return false;
  if ("eventId" in value) return hash(value.eventId);
  if ("fillId" in value) return typeof value.fillId === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value.fillId);
  return "sequence" in value && typeof value.sequence === "number" &&
    Number.isSafeInteger(value.sequence) && value.sequence >= 1 && value.sequence <= 420_001;
}
function matchesSelector(actual: BacktestReviewSelector, selected: ReviewSelection): boolean {
  return ["fillId", "eventId", "sequence"].every(key =>
    actual[key as keyof BacktestReviewSelector] === (selected[key as keyof ReviewSelection] ?? null));
}
function validContext(body: unknown, runId: string, query: ReviewQuery): body is BacktestReviewContext {
  if (!record(body) || !record(body.selector) || body.runId !== runId ||
      body.relation !== query.relation || body.limit !== (query.limit ?? 20) ||
      !matchesSelector(body.selector as BacktestReviewSelector, query.selector) ||
      !["AVAILABLE", "EXPIRED", "NOT_RECORDED"].includes(String(body.availability)) ||
      !["READY", "NOT_READY"].includes(String(body.projectionStatus)) ||
      !["COMPLETE", "PARTIAL"].includes(String(body.completeness)) ||
      !(body.missingEventId === null || hash(body.missingEventId)) ||
      typeof body.hasMore !== "boolean" ||
      !(body.nextCursor === null || validReviewCursor(body.nextCursor)) ||
      body.hasMore !== (body.nextCursor !== null) ||
      !Array.isArray(body.evidence) || body.evidence.length > 100 ||
      !body.evidence.every(item => record(item) && Number.isSafeInteger(item.sequence) && Number(item.sequence) >= 1 &&
        typeof item.ruleId === "string" && isShanghaiDateTime(item.at) &&
        ["SATISFIED", "UNSATISFIED", "MISSING_INPUT"].includes(String(item.rootOutcome)) &&
        ["requirement", "actual", "reason"].every(key => typeof item[key] === "string" && item[key].length <= (key === "reason" ? 200 : 400))) ||
      !Array.isArray(body.items) || body.items.length > (query.limit ?? 20)) return false;
  const event = (v: unknown) => (validLoopEvent(v) || validScheduledEvent(v)) && v.runId === runId;
  if (!(body.selected === null || event(body.selected)) ||
      !(body.fill === null || validLoopFill(body.fill) && body.fill.runId === runId) ||
      !body.items.every(event)) return false;
  const context = body as unknown as BacktestReviewContext;
  const selected = context.selected?.event;
  if ("fillId" in query.selector && context.fill?.fillId !== query.selector.fillId) return false;
  if (selected && ("sequence" in query.selector && selected.sequence !== query.selector.sequence ||
      "eventId" in query.selector && selected.event_id !== query.selector.eventId ||
      "fillId" in query.selector && (context.fill?.fillId !== query.selector.fillId || context.fill.eventId !== selected.event_id))) return false;
  if (new Set(context.items.map(row => row.event.event_id)).size !== context.items.length) return false;
  if (selected && context.items.some(row => row.event.event_id === selected.event_id)) return false;
  if (selected && query.relation === "EFFECTS" && context.items.some((row, index) =>
    row.event.cause_event_id !== selected.event_id || row.event.sequence <= selected.sequence ||
    index > 0 && row.event.sequence <= context.items[index - 1]!.event.sequence)) return false;
  if (selected && query.relation === "CAUSES" && context.items.some((row, index) =>
    row.event.sequence >= (index ? context.items[index - 1]!.event.sequence : selected.sequence) ||
    index > 0 && context.items[index - 1]!.event.cause_event_id !== row.event.event_id)) return false;
  if (selected && query.relation === "CAUSES" && !query.cursor && context.items.length &&
    selected.cause_event_id !== context.items[0]!.event.event_id) return false;
  return true;
}

export function createBacktestReviewApi(fetcher: typeof fetch = fetch): BacktestReviewApi {
  return {
    async getContext(runId, query, signal) {
      if (!hash(runId) || !validReviewSelection(query.selector) ||
          !["CAUSES", "EFFECTS"].includes(query.relation) ||
          !Number.isInteger(query.limit ?? 20) || (query.limit ?? 20) < 1 || (query.limit ?? 20) > 100 ||
          query.cursor !== undefined && !validReviewCursor(query.cursor)) throw invalidResponse(0);
      const search = new URLSearchParams();
      for (const [key, value] of Object.entries(query.selector)) search.set(key, String(value));
      search.set("relation", query.relation);
      search.set("limit", String(query.limit ?? 20));
      if (query.cursor) search.set("cursor", query.cursor);
      const { body, status } = await requestBacktestJson(fetcher,
        `/api/v1/backtest-runs/${runId}/review-context?${search}`, {
          method: "GET", headers: { Accept: "application/json" }, ...(signal ? { signal } : {}),
        });
      if (status !== 200 || !validContext(body, runId, query)) throw invalidResponse(status);
      return body;
    },
  };
}
