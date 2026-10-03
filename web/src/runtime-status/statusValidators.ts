import { isCalendarDate, isShanghaiDateTime } from "../api/shanghaiTime";
import type { RuntimeStatusView } from "../api/generated-runtime-status";
import { exact, hash, integer, isRecord, notLater, nullableTime, oneOf, symbol, uuid } from "./values";

export const runtimeReasons = [
  "RUNTIME_STARTING", "RUNTIME_STOPPING", "RUNTIME_STOPPED", "RUNTIME_FAULT", "COORDINATOR_STALLED", "STORAGE_UNAVAILABLE",
  "BEFORE_FIRST_MINUTE", "SESSION_BREAK", "SESSION_CLOSED", "NO_ACTIVE_PLANS", "AWAITING_FIRST_EVALUATION",
  "CALENDAR_UNKNOWN", "REFERENCE_PENDING", "COVERAGE_INCOMPLETE", "CLOSE_PENDING", "PUBLICATION_PENDING", "PROVIDER_UNAVAILABLE", "RATE_LIMITED",
  "CREDENTIAL_MISSING", "PERMISSION_DENIED", "SEMANTICS_INCOMPATIBLE", "CONFIGURATION_INVALID", "HISTORY_UNAVAILABLE", "STATE_UNAVAILABLE", "GENERATION_CHANGED",
  "NEEDS_RESTART", "LEGACY_PLANS_REQUIRE_REVIEW", "SCOPED_DEPENDENCY_FAILURE",
] as const;
const scopeKeys = ["scopeKey", "kind", "status", "reasonCode", "requiredTarget", "dataCutoff", "nextRetryAt", "progress"];
export const planIdentityKeys = ["symbol", "planFamily", "planVersionId", "planHash", "activationRevision"];

export function isPlanIdentity(value: Record<string, unknown>): boolean {
  return symbol(value.symbol) && oneOf(value.planFamily, ["LEGACY_LOW_BUY", "EXPLICIT_RULES", "CONDITION_PLAN"]) && uuid(value.planVersionId) && hash(value.planHash) && integer(value.activationRevision) && value.activationRevision > 0;
}

export function isRuntimeScope(value: unknown, observedAt: string): boolean {
  if (!isRecord(value) || !oneOf(value.kind, ["PLAN", "INDEX", "PROVIDER", "CALENDAR"]) ||
    !exact(value, [...scopeKeys, ...(value.kind === "PLAN" ? [...planIdentityKeys, "readOnly"] : value.kind === "INDEX" ? ["indexCode"] : [])]) ||
    typeof value.scopeKey !== "string" || !/^[A-Za-z0-9._:-]{1,128}$/.test(value.scopeKey) ||
    !oneOf(value.status, ["WAITING", "RECOVERING", "READY", "BLOCKED"]) ||
    !nullableTime(value.nextRetryAt) || !(value.dataCutoff === null || notLater(value.dataCutoff, observedAt)) ||
    !isTarget(value.requiredTarget, observedAt) || !isRecord(value.progress) || !exact(value.progress, ["requiredCount", "completedCount"])) return false;
  const { requiredCount, completedCount } = value.progress;
  if (!(requiredCount === null && completedCount === null) &&
    !(integer(requiredCount) && integer(completedCount) && completedCount <= requiredCount)) return false;
  if (value.status === "READY") {
    if (value.reasonCode !== null || value.nextRetryAt !== null || requiredCount !== completedCount) return false;
  } else if (!oneOf(value.reasonCode, runtimeReasons) || value.reasonCode === "SCOPED_DEPENDENCY_FAILURE") return false;
  if (value.kind === "PLAN") return isPlanIdentity(value) && typeof value.readOnly === "boolean" &&
    (value.readOnly || (value.status === "READY" && value.requiredTarget !== null && requiredCount !== null));
  return value.kind !== "INDEX" || oneOf(value.indexCode, ["000001.SH", "000688.SH", "399001.SZ", "399006.SZ", "399107.SZ", "899050.BJ"]);
}

function isTarget(value: unknown, observedAt: string): boolean {
  if (value === null) return true;
  if (!isRecord(value)) return false;
  return value.kind === "INTRADAY"
    ? exact(value, ["kind", "targetEnd"]) && notLater(value.targetEnd, observedAt)
    : value.kind === "OFFICIAL_CLOSE" && exact(value, ["kind", "tradeDate"]) && isCalendarDate(value.tradeDate) && value.tradeDate <= observedAt.slice(0, 10);
}

export function isRuntimeStatus(value: unknown, observedAt: string): value is RuntimeStatusView {
  if (!isShanghaiDateTime(observedAt) || !isRecord(value) || !exact(value, ["lifecycle", "mode", "reasonCode", "nextWakeAt", "nextRetryAt", "lastProgressAt", "coordinator", "scopes"]) ||
    !oneOf(value.lifecycle, ["STARTING", "RUNNING", "STOPPING", "STOPPED"]) ||
    !oneOf(value.mode, ["RECOVERING", "MONITORING", "STANDBY", "DEGRADED", "BLOCKED"]) ||
    !(value.mode === "MONITORING" ? value.reasonCode === null : oneOf(value.reasonCode, runtimeReasons)) ||
    !nullableTime(value.nextWakeAt) || !nullableTime(value.nextRetryAt) || !(value.lastProgressAt === null || notLater(value.lastProgressAt, observedAt)) ||
    !isRecord(value.coordinator) || !exact(value.coordinator, ["state", "progressDueAt"]) ||
    !oneOf(value.coordinator.state, ["STARTING", "SCHEDULED", "WORKING", "STALLED", "STOPPED"]) || !nullableTime(value.coordinator.progressDueAt) ||
    !Array.isArray(value.scopes) || value.scopes.length > 32 || !value.scopes.every((scope) => isRuntimeScope(scope, observedAt))) return false;
  const scopes = value.scopes as Record<string, unknown>[];
  if (value.lifecycle !== "RUNNING" && value.mode !== "BLOCKED") return false;
  const planSymbols = scopes.filter(scope => scope.kind === "PLAN").map(scope => scope.symbol);
  if (new Set(planSymbols).size !== planSymbols.length) return false;
  if (!scopes.every((scope, index) => index === 0 || String(scopes[index - 1]!.scopeKey) < String(scope.scopeKey))) return false;
  if (value.coordinator.state === "SCHEDULED" && (value.nextWakeAt === null || value.coordinator.progressDueAt === null)) return false;
  if (oneOf(value.coordinator.state, ["WORKING", "STALLED"]) && value.coordinator.progressDueAt === null) return false;
  if (value.coordinator.state === "STALLED" && (value.mode !== "BLOCKED" || value.reasonCode !== "COORDINATOR_STALLED")) return false;
  if (value.coordinator.state === "STOPPED" && (value.lifecycle !== "STOPPED" || value.mode !== "BLOCKED" || value.reasonCode !== "RUNTIME_STOPPED" ||
    value.nextWakeAt !== null || value.nextRetryAt !== null || value.coordinator.progressDueAt !== null)) return false;
  if (value.lifecycle === "STOPPED" && value.coordinator.state !== "STOPPED") return false;
  const liveCoordinator = value.lifecycle === "RUNNING" && oneOf(value.coordinator.state, ["SCHEDULED", "WORKING"]);
  return scopes.every((scope) => scope.kind !== "PLAN" || scope.readOnly === true || liveCoordinator);
}
