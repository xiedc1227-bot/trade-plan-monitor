import type { LoopDiagnostics } from "./generated";
import { isCalendarDate, isShanghaiDateTime } from "./shanghaiTime";

const categories = new Set(["MARKET_UNMET", "QUALITATIVE_UNRESOLVED", "PROCESSING_ERROR", "DATA_UNAVAILABLE",
  "EXECUTION_BLOCKED", "NO_BUY_RULE", "NO_EVALUATION", "CONDITION_MET"]);
const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const count = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length <= max;
const exact = (v: Record<string, unknown>, fields: string[]) => Object.keys(v).length === fields.length && fields.every(k => Object.hasOwn(v, k));

export function validPlanDiagnostics(value: unknown, versions: string[], fills: number): value is LoopDiagnostics | null | undefined {
  if (value === undefined || value === null) return true;
  if (!record(value) || !exact(value, ["availability", "plans"]) || !["AVAILABLE", "EXPIRED", "UNAVAILABLE"].includes(String(value.availability)) ||
      !Array.isArray(value.plans) || value.plans.length !== versions.length || value.plans.length > 256) return false;
  let exampleCount = 0, totalFills = 0;
  const valid = value.plans.every((p, i) => {
    if (!record(p) || !exact(p, ["source_id", "version_id", "effective_trade_date", "buy_rule_count", "fill_count", "evaluation_count",
      "unmet_count", "missing_count", "satisfied_count", "review_status", "categories", "examples", "sampled"]) ||
      p.version_id !== versions[i] || !text(p.source_id, 160) || !isCalendarDate(p.effective_trade_date) || p.review_status !== "PASSED" ||
      ![p.buy_rule_count, p.evaluation_count, p.unmet_count, p.missing_count, p.satisfied_count].every(count) ||
      (value.availability === "AVAILABLE" ? !count(p.fill_count) : p.fill_count !== null) || typeof p.sampled !== "boolean" ||
      !Array.isArray(p.categories) || p.categories.length > 8 || !p.categories.every(c => categories.has(String(c))) ||
      !Array.isArray(p.examples) || p.examples.length > 8 || (value.availability !== "AVAILABLE" && p.examples.length)) return false;
    totalFills += typeof p.fill_count === "number" ? p.fill_count : 0;
    exampleCount += p.examples.length;
    return p.examples.every(e => record(e) && exact(e, ["category", "rule_id", "at", "sequence", "root_outcome", "requirement", "actual", "reason"]) &&
      categories.has(String(e.category)) && text(e.rule_id, 160) && isShanghaiDateTime(e.at) && count(e.sequence) && e.sequence > 0 &&
      [null, "SATISFIED", "UNSATISFIED", "MISSING_INPUT"].includes(e.root_outcome as string | null) &&
      text(e.requirement, 400) && text(e.actual, 400) && text(e.reason, 200));
  });
  return valid && exampleCount <= 256 && (value.availability !== "AVAILABLE" || totalFills === fills);
}
