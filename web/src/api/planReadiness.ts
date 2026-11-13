import type { AxisReadiness, ReadinessAssessment, RuleReadiness } from "./generated-runtime-status";
import { resolveApiFetch } from "./context";
import { invalidResponse, requestJson } from "./transport";

export type { ReadinessAssessment } from "./generated-runtime-status";

/** Saved UI identity; receipt hashes belong to the current coverage summary. */
export interface ReadinessContext {
  readonly planVersionId: string;
  readonly contentHash: string;
  readonly sourceHash: string;
  readonly coverageHash?: string | null;
  readonly reviewReceiptHash: string | null;
  readonly ownerGeneration: number;
}

const axes: readonly AxisReadiness["axis"][] = ["SOURCE_COVERAGE", "REVIEW_ACTIVATION", "RUNTIME_OWNERSHIP",
  "DATA_EVALUATION", "INVENTORY_CAPITAL", "NOTIFICATION_DELIVERY"];
const axisStates = ["PASS", "WAIT", "BLOCKED", "UNKNOWN", "NOT_APPLICABLE"];
const ruleStates: readonly RuleReadiness["state"][] = ["CONDITION_TRUE", "CONDITION_FALSE",
  "WAITING_OFFICIAL_CONFIRMATION", "AWAITING_FIRST_EVALUATION", "MISSING_INPUT", "BLOCKED", "UNKNOWN"];
const summaries = ["READY_FOR_MONITORING", "WAITING_EXPECTED_CONFIRMATION", "WAITING_REQUIRED_SERVICE", "NEEDS_REVIEW", "BLOCKED", "UNKNOWN"];
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
const text = (value: unknown) => typeof value === "string" && value.length <= 512;
const optionalText = (value: unknown) => value == null || text(value);
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const instant = (value: unknown) => typeof value === "string" && /(Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
const optionalInstant = (value: unknown) => value == null || instant(value);
const optionalBoolean = (value: unknown) => value == null || typeof value === "boolean";
const optionalQuantity = (value: unknown) => value == null || typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const date = (value: unknown) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
  Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
function target(value: unknown): boolean {
  return value == null || record(value) && (value.kind === "INTRADAY" && instant(value.bucket_end) ||
    value.kind === "OFFICIAL_CLOSE" && date(value.trade_date));
}
function observation(value: unknown): boolean {
  return value == null || record(value) && ["CURRENT", "CACHED", "UNAVAILABLE", "PERSISTED_ONLY"].includes(String(value.availability)) &&
    instant(value.observedAt) && (value.asOf === null || instant(value.asOf)) && (value.expiresAt === null || instant(value.expiresAt));
}

function axis(value: unknown): boolean {
  return record(value) && axes.includes(value.axis as AxisReadiness["axis"]) &&
    axisStates.includes(String(value.state)) && optionalText(value.reason) && observation(value.observation);
}
function rule(value: unknown): boolean {
  if (!record(value) || !ruleStates.includes(value.state as RuleReadiness["state"]) || !optionalText(value.reason) || !record(value.facts)) return false;
  const f = value.facts, requirements = f.requirements;
  if (!["ORDINARY_RULE", "ALERT_RULE", "RISK_BRANCH"].includes(String(f.ownerKind)) || !text(f.ownerId) ||
      !(f.side === null || f.side === "BUY" || f.side === "SELL") || !optionalInstant(f.evaluatedAt) ||
      !target(f.expectedTarget) || !target(f.evaluatedTarget) || !observation(f.observation) || !record(requirements) ||
      !["inventory", "sellability", "quote", "simulationBook", "costBasis", "fees", "economics"].every(key =>
        requirements[key] === undefined || typeof requirements[key] === "boolean") ||
      !Array.isArray(f.leaves) || f.leaves.length > 50 || !f.leaves.every(leaf => record(leaf) &&
        text(leaf.conditionPath) && ruleStates.includes(leaf.state as RuleReadiness["state"]) && optionalText(leaf.reason))) return false;
  if (f.expectedConfirmation != null && (!record(f.expectedConfirmation) || !instant(f.expectedConfirmation.expectedAt) ||
      !target(f.expectedConfirmation.target) || !observation(f.expectedConfirmation.observation))) return false;
  if (f.execution != null && (!record(f.execution) || !optionalQuantity(f.execution.approvedQuantity) ||
      !optionalBoolean(f.execution.consumed) || !optionalBoolean(f.execution.eligible) ||
      !(f.execution.executionDate == null || date(f.execution.executionDate)) || !observation(f.execution.observation) ||
      ![undefined, null, "CURRENT_SESSION", "NEXT_EXCHANGE_SESSION_ONLY"].includes(f.execution.executionWindow as string | null | undefined) ||
      ![undefined, "OPEN", "CLOSED", "UNKNOWN"].includes(f.execution.windowState as string | undefined))) return false;
  if (f.risk != null) {
    if (!record(f.risk) || !axis(f.risk.maintenance)) return false;
    if (f.risk.current != null && !record(f.risk.current)) return false;
    if (f.risk.obligation != null && (!record(f.risk.obligation) ||
        !["CLEAR", "PENDING", "OBSERVATION", "CONFIRMED", "FULFILLED"].includes(String(f.risk.obligation.status)))) return false;
    if (f.risk.origin != null && (!record(f.risk.origin) || !text(f.risk.origin.planVersionId) || !instant(f.risk.origin.evaluatedAt))) return false;
  }
  if (f.money != null) {
    if (!record(f.money) || !axis(f.money.inputs)) return false;
    for (const key of ["capital", "economics"]) {
      const verdict = f.money[key];
      if (verdict != null && (!record(verdict) ||
          !(key === "economics" ? ["PASS", "FAIL", "UNKNOWN", "NONE"] : ["PASS", "FAIL", "UNKNOWN"]).includes(String(verdict.outcome)) ||
          !optionalQuantity(verdict.quantity))) return false;
    }
  }
  if (f.notification != null) {
    const n = f.notification;
    if (!record(n) || !optionalInstant(n.createdAt) || !optionalText(n.eventId) || !target(n.target) || !observation(n.observation) ||
        !(n.channels === undefined || Array.isArray(n.channels) && n.channels.length <= 3 && n.channels.every(channel => {
          if (!record(channel) || !["IN_APP", "CONSOLE", "WEBHOOK"].includes(String(channel.channel)) ||
              ![channel.configured, channel.enabled, channel.eligible].every(optionalBoolean) || !optionalInstant(channel.historicalUpdatedAt) ||
              ![undefined, null, "HOLD", "ELIGIBLE", "SUPPRESS"].includes(channel.historicalStatus as string | null | undefined)) return false;
          const attempt = channel.latestAttempt;
          return attempt == null || record(attempt) && ["CLAIMED", "DELIVERED", "RETRY_PENDING", "FAILED"].includes(String(attempt.status)) &&
            optionalInstant(attempt.deliveredAt) && optionalInstant(attempt.nextRetryAt);
        }))) return false;
  }
  return true;
}

/** Guard only this view's consumed wire values; semantic proof remains server-owned. */
function readable(value: unknown, versionId: string): value is ReadinessAssessment {
  if (!record(value) || value.authorityGranted !== false || value.contractVersion !== "plan-monitor-readiness-v1" ||
      !summaries.includes(String(value.summary)) || !(value.freshUntil === null || instant(value.freshUntil)) || !record(value.snapshot)) return false;
  const snapshot = value.snapshot, context = snapshot.context;
  if (!record(context) || context.planVersionId !== versionId || !digest(context.contentHash) ||
      !(context.sourceHash === null || digest(context.sourceHash)) ||
      !(context.coverageHash === null || digest(context.coverageHash)) ||
      !(context.reviewReceiptHash === null || digest(context.reviewReceiptHash)) || !instant(snapshot.computedAt) ||
      !["ALERT_ONLY", "TRADE_RULES", "MIXED"].includes(String(snapshot.scope)) ||
      !Array.isArray(value.axes) || value.axes.length !== 6 || !value.axes.every(axis) ||
      new Set(value.axes.map(item => item.axis)).size !== 6 || !Array.isArray(value.rules) ||
      value.rules.length < 1 || value.rules.length > 76 || !value.rules.every(rule)) return false;
  return new Set(value.rules.map(item => `${item.facts.ownerKind}:${item.facts.ownerId}`)).size === value.rules.length &&
    value.rules.reduce((total, item) => total + item.facts.leaves.length, 0) <= 50;
}

export function createPlanReadinessApi(fetcher: typeof fetch = resolveApiFetch()) {
  return Object.freeze({ async get(versionId: string, signal?: AbortSignal): Promise<ReadinessAssessment> {
    const { body, status } = await requestJson(fetcher,
      `/api/v1/plan-versions/${encodeURIComponent(versionId)}/monitor-readiness`,
      { method: "GET", headers: { Accept: "application/json" }, ...(signal ? { signal } : {}) },
      { maxResponseBytes: 1024 * 1024 });
    if (!readable(body, versionId)) throw invalidResponse(status);
    return body;
  } });
}
