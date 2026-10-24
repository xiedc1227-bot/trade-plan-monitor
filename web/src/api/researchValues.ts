import type { ExceptionResearchInput, ResearchDecisionView, ResearchOperationView, UnifiedResearchInput } from "./generated";
import { exceptionOutcomes, frozenExceptionEvents } from "./exceptionReplayValues";
import { normalizeShanghaiDateTime } from "./shanghaiTime";

function sameTime(first: unknown, second: unknown): boolean {
  const normalized = normalizeShanghaiDateTime(first);
  return normalized !== null && normalized === normalizeShanghaiDateTime(second);
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 500 && value.every((item) => typeof item === "string");
}

function inventory(value: unknown): boolean {
  return record(value) && typeof value.known === "boolean" &&
    ["total_qty", "core_qty", "tactical_qty", "sellable_core", "sellable_tactical"].every((key) => value[key] === null || Number.isSafeInteger(value[key]));
}

function signal(value: unknown): boolean {
  return record(value) && ["signal_id", "rule_id", "state", "execution_window", "execution_date"].every((key) => typeof value[key] === "string") &&
    Number.isSafeInteger(value.planned_qty) && Number.isSafeInteger(value.executable_qty) && strings(value.blockers);
}

function risk(value: unknown): boolean {
  return record(value) && typeof value.risk_id === "string" && typeof value.kind === "string" && typeof value.status === "string" &&
    (value.earliest_execution_date === null || typeof value.earliest_execution_date === "string");
}

function alert(value: unknown): boolean {
  return record(value) && typeof value.rule_id === "string" && typeof value.outcome === "string" &&
    (value.confirmed_at === null || normalizeShanghaiDateTime(value.confirmed_at) !== null);
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeTree(value: unknown, depth = 0): boolean {
  if (depth > 40) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isSafeInteger(value);
  if (Array.isArray(value)) return value.every((item) => safeTree(item, depth + 1));
  return record(value) && Object.values(value).every((item) => safeTree(item, depth + 1));
}

export function isResearchInput(value: unknown): value is UnifiedResearchInput | ExceptionResearchInput {
  if (!record(value) || !safeTree(value)) return false;
  const allowed = ["schema_version", "started_at", "inventory_known", "review", "operations", "adjustment_proofs", "calendar_extension"];
  const exceptions = value.schema_version === "unified-research-input-v2";
  if (exceptions) allowed.push("exception_authorization_events");
  return Object.keys(value).every((key) => allowed.includes(key)) &&
    (exceptions ? frozenExceptionEvents(value.exception_authorization_events) : value.schema_version === undefined || value.schema_version === "unified-research-input-v1") &&
    typeof value.started_at === "string" && value.started_at.endsWith("+08:00") &&
    typeof value.inventory_known === "boolean" && record(value.review) &&
    value.review.confirmed === true && typeof value.review.content_hash === "string" &&
    /^[0-9a-f]{64}$/.test(value.review.content_hash) &&
    typeof value.review.reviewed_at === "string" && typeof value.review.evidence === "string" &&
    (value.operations === undefined || Array.isArray(value.operations) && value.operations.length <= 10000) &&
    (value.adjustment_proofs === undefined || Array.isArray(value.adjustment_proofs) && value.adjustment_proofs.length <= 1500) &&
    (value.calendar_extension === undefined || Array.isArray(value.calendar_extension) && value.calendar_extension.length <= 32);
}

export function isResearchDetail(value: unknown): value is ResearchDecisionView | ResearchOperationView {
  if (!record(value) || !safeTree(value)) return false;
  const decision = value.researchDecision;
  const operation = value.researchOperation;
  if (value.kind === "DECISION" && record(decision)) {
    return Object.keys(value).sort().join() === ["detailId", "eventAt", "kind", "researchDecision", "runId"].sort().join() &&
      decision.schema_version === "unified-research-decision-v1" && typeof decision.event_id === "string" &&
      (decision.exception_outcomes === undefined || exceptionOutcomes(decision.exception_outcomes)) &&
      Array.isArray(decision.signals) && decision.signals.length <= 500 && decision.signals.every(signal) &&
      Array.isArray(decision.risks) && decision.risks.length <= 2 && decision.risks.every(risk) &&
      Array.isArray(decision.resulting_signals) && decision.resulting_signals.length <= 500 && decision.resulting_signals.every(signal) &&
      Array.isArray(decision.resulting_risks) && decision.resulting_risks.length <= 2 && decision.resulting_risks.every(risk) &&
      Array.isArray(decision.alerts) && decision.alerts.length <= 10 && decision.alerts.every(alert) &&
      strings(decision.blockers) && Array.isArray(decision.conditions) && inventory(decision.inventory_after) &&
      sameTime(decision.at, value.eventAt);
  }
  return value.kind === "EXECUTION_OUTCOME" && record(operation) &&
    Object.keys(value).sort().join() === ["detailId", "eventAt", "kind", "researchOperation", "runId"].sort().join() &&
    operation.schema_version === "unified-research-operation-v1" && typeof operation.operation_id === "string" &&
    ["APPLIED", "BLOCKED", "REPLAYED"].includes(String(operation.status)) &&
    strings(operation.blockers) && inventory(operation.inventory_after) &&
    (operation.quantity === null || Number.isSafeInteger(operation.quantity)) &&
    (operation.valuation === null || record(operation.valuation) &&
      ["PROJECTED", "BLOCKED"].includes(String(operation.valuation.status)) && strings(operation.valuation.blockers)) &&
    sameTime(operation.at, value.eventAt);
}
