import { isAuthoritativeDecision, isDashboardMarketIndexes, isMarketTurnoverSummary, isSymbolReferenceMarket } from "../api/client";
import type { RuntimeDashboardResponse, RuntimeHealthV2Response, RuntimeHeartbeatFrame, RuntimeSnapshotRequiredFrame, RuntimeSymbolCollectionResponse, RuntimeSymbolHealthResponse, RuntimeSymbolDetailResponse, RuntimeInactiveSymbolResponse } from "../api/generated-runtime-status";
import { isExplicitEvidence } from "../api/alerts";
import { isSymbolDetail } from "../api/symbols";
import { isDatabase, isDelivery, isExecutor, isGap, isOrderedGaps, isProvider, isUniqueProviders, matchesAge } from "../api/health";
import { isShanghaiDateTime, shanghaiDateTimeKey } from "../api/shanghaiTime";
import { isPlanIdentity, isRuntimeStatus, planIdentityKeys, runtimeReasons } from "./statusValidators";
import { equalJson, exact, hash, integer, isRecord, notLater, nullableTime, oneOf, safeGuard, sameTime, symbol, text, uuid, uuid4 } from "./values";
export { isRuntimeStatus } from "./statusValidators";

const envelopeKeys = ["monitorContractVersion", "runtimeGeneration", "observedAt", "runtimeStatus"];
const entryKeys = [...planIdentityKeys, "name", "observedAt", "availability", "scope", "currentActionable"];
const legacyActionable = ["BUY_CORE_READY", "BUY_TACTICAL_READY", "PRESSURE_REDUCE_READY", "RISK_BREACH", "RISK_EXIT_READY", "RISK_EXIT_PENDING_SETTLEMENT"];
const stateRisk = ["RISK_BREACH", "RISK_EXIT_READY", "RISK_EXIT_PENDING_SETTLEMENT"];
const eligibilityReasons = ["NO_CURRENT_SIGNAL", "INTRADAY_EXPIRED", "RECOVERY_HOLD", "RISK_NO_LONGER_VALID", "CURRENT_STATE_UNVERIFIED", "CACHED_RESULT"];

export function isStatusEnvelope(value: unknown): value is Record<string, unknown> & { observedAt: string; runtimeStatus: Record<string, unknown> } {
  return isRecord(value) && value.monitorContractVersion === 2 && isShanghaiDateTime(value.observedAt) &&
    (value.runtimeGeneration === null || uuid4(value.runtimeGeneration)) && isRuntimeStatus(value.runtimeStatus, value.observedAt) && isRecord(value.runtimeStatus) &&
    (value.runtimeGeneration !== null || value.runtimeStatus.lifecycle === "STOPPED");
}

export function isRuntimeDashboard(value: unknown): value is RuntimeDashboardResponse {
  return safeGuard(() => {
    if (!isStatusEnvelope(value) || !exact(value, [...envelopeKeys, "sequence", "counts", "symbols", "marketIndexes", "marketTurnover"]) || !integer(value.sequence) ||
      !Array.isArray(value.symbols) || value.symbols.length > 10 || !value.symbols.every((entry) => isPlanEntry(entry, value)) ||
      !isDashboardMarketIndexes(value.marketIndexes, value.observedAt) ||
      !(value.marketTurnover === null || isMarketTurnoverSummary(value.marketTurnover, value.observedAt))) return false;
    const rows = value.symbols as Record<string, unknown>[];
    if (!rows.every((row, index) => index === 0 || String(rows[index - 1]!.symbol) < String(row.symbol))) return false;
    const plans = (value.runtimeStatus.scopes as Record<string, unknown>[]).filter((scope) => scope.kind === "PLAN");
    if (plans.length !== rows.length) return false;
    return countsMatch(value.counts, rows);
  });
}

export function isRuntimeHealth(value: unknown): value is RuntimeHealthV2Response {
  return safeGuard(() => {
    if (!isStatusEnvelope(value) || !exact(value, [...envelopeKeys, "startedAt", "stoppedAt", "lastCompletedMinute", "lastCompletedMinuteAgeSeconds", "latestEvaluationAt", "latestEvaluationAgeSeconds", "gaps", "cooldownUntil", "providers", "executor", "database", "delivery"]) ||
      !nullableTime(value.startedAt) || !nullableTime(value.stoppedAt) || !nullableTime(value.cooldownUntil) ||
      !matchesAge(value.lastCompletedMinute, value.lastCompletedMinuteAgeSeconds, value.observedAt) ||
      !matchesAge(value.latestEvaluationAt, value.latestEvaluationAgeSeconds, value.observedAt) ||
      !Array.isArray(value.gaps) || value.gaps.length > 2400 || !value.gaps.every((gap) => isGap(gap) && isRecord(gap) && notLater(gap.barEnd, value.observedAt)) || !isOrderedGaps(value.gaps) ||
      !Array.isArray(value.providers) || value.providers.length > 5 || !value.providers.every(isProvider) || !isUniqueProviders(value.providers, value.observedAt) ||
      !isDatabase(value.database) || !isDelivery(value.delivery) || !isExecutor(value.executor)) return false;
    if (value.runtimeGeneration === null) return value.startedAt === null && value.stoppedAt === null;
    if ((value.runtimeStatus.lifecycle === "STOPPED") !== (value.stoppedAt !== null)) return false;
    return notLater(value.startedAt, value.observedAt) && (value.stoppedAt === null ||
      value.runtimeStatus.lifecycle === "STOPPED" && notLater(value.startedAt, value.stoppedAt) && notLater(value.stoppedAt, value.observedAt));
  });
}

export function isHeartbeat(value: unknown): value is RuntimeHeartbeatFrame {
  return isStatusEnvelope(value) && exact(value, [...envelopeKeys, "type", "sequence"]) && value.type === "heartbeat" && integer(value.sequence);
}

export function isSnapshotRequired(value: unknown): value is RuntimeSnapshotRequiredFrame {
  return isRecord(value) && exact(value, ["type", "monitorContractVersion", "sequence", "reason"]) && value.type === "snapshot.required" &&
    value.monitorContractVersion === 2 && integer(value.sequence) && value.reason === "REPLAY_UNAVAILABLE";
}

export function isRuntimeSymbolCollection(value: unknown): value is RuntimeSymbolCollectionResponse {
  return safeGuard(() => {
    if (!isStatusEnvelope(value) || !exact(value, [...envelopeKeys, "sequence", "items", "offset", "limit", "total"]) || !integer(value.sequence) ||
      !integer(value.offset) || value.offset > 10_000 || !integer(value.limit) || value.limit < 1 || value.limit > 100 || !integer(value.total) || value.total > 10 ||
      !Array.isArray(value.items) || value.items.length > value.limit || value.items.length > 0 && value.offset + value.items.length > value.total ||
      !value.items.every((item) => isPlanEntry(item, value))) return false;
    const rows = value.items as Record<string, unknown>[];
    return rows.every((row, index) => index === 0 || String(rows[index - 1]!.symbol) < String(row.symbol)) &&
      (value.runtimeStatus.scopes as Record<string, unknown>[]).filter((scope) => scope.kind === "PLAN").length === value.total;
  });
}

export function isRuntimeSymbolHealth(value: unknown, expectedSymbol: string): value is RuntimeSymbolHealthResponse {
  return isStatusEnvelope(value) && exact(value, [...envelopeKeys, "scope"]) && isRecord(value.scope) && value.scope.kind === "PLAN" && value.scope.symbol === expectedSymbol &&
    (value.runtimeStatus.scopes as unknown[]).some((scope) => equalJson(scope, value.scope));
}

export function isRuntimeSymbolDetail(value: unknown, expectedSymbol: string, explicitOnly = false): value is RuntimeSymbolDetailResponse | RuntimeInactiveSymbolResponse {
  return safeGuard(() => {
    if (!isStatusEnvelope(value) || !integer(value.sequence) || !symbol(expectedSymbol)) return false;
    if (value.availability === "UNAVAILABLE") return exact(value, [...envelopeKeys, "sequence", "symbol", "availability", "reasonCode"]) &&
      value.symbol === expectedSymbol && value.reasonCode === "NO_ACTIVE_PLAN" &&
      !(value.runtimeStatus.scopes as Record<string, unknown>[]).some((scope) => scope.kind === "PLAN" && scope.symbol === expectedSymbol);
    if (!exact(value, [...envelopeKeys, "sequence", "summary", "legacyDetails"]) || !isPlanEntry(value.summary, value) || !isRecord(value.summary) ||
      value.summary.symbol !== expectedSymbol || explicitOnly && value.summary.planFamily !== "EXPLICIT_RULES") return false;
    const row = value.summary;
    if (row.availability === "UNAVAILABLE" || ["EXPLICIT_RULES", "CONDITION_PLAN"].includes(String(row.planFamily))) return value.legacyDetails === null;
    const details = value.legacyDetails;
    if (!isRecord(details) || !exact(details, ["positionLots", "referenceMarket", "indexConditionEvidence"])) return false;
    // Reuse only v1 value validation. This temporary object never becomes a v2 projection.
    const legacy = { ...details, summary: { symbol: row.symbol, name: row.name, observedAt: row.observedAt, connected: false,
      decision: row.decision, riskDistanceFen: row.riskDistanceFen, satisfiedConditionCount: row.satisfiedConditionCount,
      totalConditionCount: row.totalConditionCount, referenceMarket: row.referenceMarket } };
    if (!isSymbolDetail(legacy, expectedSymbol)) return false;
    const lots = legacy.positionLots ?? [];
    if (new Set(lots.map((lot) => lot.lotId)).size !== lots.length) return false;
    const position = legacy.summary.decision.position;
    const sum = (bucket: string, field: "remainingQuantity" | "sellableQuantity") => lots.filter((lot) => lot.bucket === bucket).reduce((count, lot) => count + lot[field], 0);
    return sum("CORE", "remainingQuantity") === position.coreQuantity && sum("TACTICAL", "remainingQuantity") === position.tacticalQuantity &&
      sum("CORE", "sellableQuantity") === position.sellableCoreQuantity && sum("TACTICAL", "sellableQuantity") === position.sellableTacticalQuantity;
  });
}

function isPlanEntry(value: unknown, envelope: Record<string, unknown> & { observedAt: string; runtimeStatus: Record<string, unknown> }): boolean {
  if (!isRecord(value) || !isPlanIdentity(value) || !text(value.name) || !sameTime(value.observedAt, envelope.observedAt) ||
    !oneOf(value.availability, ["CURRENT", "CACHED", "UNAVAILABLE"]) || typeof value.currentActionable !== "boolean" || !isRecord(value.scope)) return false;
  const scope = (envelope.runtimeStatus.scopes as Record<string, unknown>[]).find((item) => item.scopeKey === (value.scope as Record<string, unknown>).scopeKey);
  if (!scope || scope.kind !== "PLAN" || !equalJson(scope, value.scope) || !planIdentityKeys.every((key) => value[key] === scope[key])) return false;
  if (value.availability === "UNAVAILABLE") return exact(value, [...entryKeys, "projectionState", "reasonCode"]) && !value.currentActionable &&
    oneOf(value.projectionState, ["WAITING", "RECOVERING", "BLOCKED"]) && oneOf(value.reasonCode, runtimeReasons) &&
    ((value.projectionState === scope.status && value.reasonCode === scope.reasonCode) ||
      (scope.status === "READY" && value.projectionState === "WAITING" && value.reasonCode === "AWAITING_FIRST_EVALUATION"));
  const coordinator = envelope.runtimeStatus.coordinator as Record<string, unknown>;
  if (value.currentActionable && (value.availability !== "CURRENT" || envelope.runtimeGeneration === null ||
    !oneOf(coordinator.state, ["SCHEDULED", "WORKING"]))) return false;
  return value.planFamily === "LEGACY_LOW_BUY" ? isLegacyEntry(value, envelope.observedAt) : value.planFamily === "CONDITION_PLAN" ? isConditionEntry(value, envelope.observedAt) : isExplicitEntry(value, envelope.observedAt);
}

function isConditionEntry(value: Record<string, unknown>, observedAt: string): boolean {
  if (!exact(value, [...entryKeys, "planRuntime"]) || !isRecord(value.planRuntime)) return false;
  const runtime = value.planRuntime;
  if (!["symbol", "planVersionId", "planHash", "activationRevision"].every(key => runtime[key] === value[key]) ||
    !notLater(runtime.evaluatedAt, observedAt) || !Array.isArray(runtime.dataBlockers) || !runtime.dataBlockers.every(text) ||
    !Array.isArray(runtime.signals) || !Array.isArray(runtime.risks) || !isRecord(runtime.riskAction)) return false;
  if (!runtime.signals.every(s => isRecord(s) && text(s.signalId) && oneOf(s.side, ["BUY", "SELL"]) &&
    oneOf(s.state, ["CONFIRMED", "READY", "SIMULATED", "EXPIRED", "INVALIDATED"]) &&
    integer(s.plannedQty) && integer(s.simulatedQty) && integer(s.executableQty) && Array.isArray(s.blockers)) ||
    !runtime.risks.every(r => isRecord(r) && oneOf(r.status, ["CLEAR", "PENDING", "OBSERVATION", "CONFIRMED", "FULFILLED"]))) return false;
  const offered = runtime.signals.some(s => isRecord(s) && Number(s.executableQty) > 0) ||
    runtime.riskAction.status === "RISK_EXIT" && Number(runtime.riskAction.coreQty ?? 0) + Number(runtime.riskAction.tacticalQty ?? 0) > 0;
  return !value.currentActionable || value.availability === "CURRENT" && isRecord(value.scope) && value.scope.readOnly === false && offered;
}

function isLegacyEntry(value: Record<string, unknown>, observedAt: string): boolean {
  if (!exact(value, [...entryKeys, "decision", "riskDistanceFen", "satisfiedConditionCount", "totalConditionCount", "referenceMarket", "actionableUntil"]) ||
    !isAuthoritativeDecision(value.decision) || !isRecord(value.decision) || value.decision.symbol !== value.symbol || value.decision.planHash !== value.planHash ||
    !notLater(value.decision.evaluatedAt, observedAt) ||
    !(value.riskDistanceFen === null || typeof value.riskDistanceFen === "number" && Number.isSafeInteger(value.riskDistanceFen)) ||
    !integer(value.satisfiedConditionCount) || !integer(value.totalConditionCount) || value.satisfiedConditionCount > value.totalConditionCount ||
    !(value.referenceMarket === null || isSymbolReferenceMarket(value.referenceMarket))) return false;
  if (!value.currentActionable) return value.actionableUntil === null;
  return oneOf(value.decision.signalType, legacyActionable) && validDeadline(value.actionableUntil, oneOf(value.decision.signalType, stateRisk), observedAt);
}

function isExplicitEntry(value: Record<string, unknown>, observedAt: string): boolean {
  if (!exact(value, [...entryKeys, "explicitRuntime", "resultHash", "ruleEligibility", "actionableRuleIds"]) || !hash(value.resultHash) ||
    !isRecord(value.explicitRuntime) || !exact(value.explicitRuntime, ["symbol", "planVersionId", "planHash", "activationRevision", "status", "evaluatedAt", "targetBucketEnd", "ruleOutcomes"])) return false;
  const runtime = value.explicitRuntime;
  const target = isRecord(value.scope) ? value.scope.requiredTarget : null;
  if (value.availability === "CURRENT" && (!isRecord(target) || target.kind !== "INTRADAY" || !sameTime(target.targetEnd, runtime.targetBucketEnd))) return false;
  if (!["symbol", "planVersionId", "planHash", "activationRevision"].every((key) => runtime[key] === value[key]) || runtime.status !== "CURRENT" ||
    !notLater(runtime.targetBucketEnd, runtime.evaluatedAt) || !notLater(runtime.evaluatedAt, observedAt) ||
    !Array.isArray(runtime.ruleOutcomes) || runtime.ruleOutcomes.length < 1 || runtime.ruleOutcomes.length > 3 || !runtime.ruleOutcomes.every(isRuleOutcome) ||
    !Array.isArray(value.ruleEligibility) || value.ruleEligibility.length !== runtime.ruleOutcomes.length || !Array.isArray(value.actionableRuleIds)) return false;
  const rules = runtime.ruleOutcomes as Record<string, unknown>[];
  if (new Set(rules.map((rule) => rule.ruleId)).size !== rules.length) return false;
  const eligible: unknown[] = [];
  for (const [index, eligibility] of value.ruleEligibility.entries()) {
    const rule = rules[index]!;
    if (!isRecord(eligibility) || !exact(eligibility, ["ruleId", "action", "currentActionable", "reasonCode", "actionableUntil", "sourceAlert"]) ||
      eligibility.ruleId !== rule.ruleId || eligibility.action !== rule.action || typeof eligibility.currentActionable !== "boolean" ||
      !isSourceAlert(eligibility.sourceAlert, observedAt)) return false;
    if (eligibility.currentActionable) {
      if (value.availability !== "CURRENT" || eligibility.reasonCode !== null || eligibility.sourceAlert === null ||
        !validDeadline(eligibility.actionableUntil, eligibility.action === "RISK_ALERT", observedAt)) return false;
      eligible.push(eligibility.ruleId);
    } else if (!oneOf(eligibility.reasonCode, eligibilityReasons) || eligibility.actionableUntil !== null ||
      (value.availability === "CACHED" && eligibility.reasonCode !== "CACHED_RESULT")) return false;
  }
  return equalJson(eligible, value.actionableRuleIds) && value.currentActionable === (eligible.length > 0);
}

function isRuleOutcome(value: unknown): boolean {
  if (!isRecord(value) || !Object.keys(value).every((key) => ["ruleId", "action", "conditionCode", "outcome", "missingInputs", "blockers", "suppressionReason", "conditionEvidence"].includes(key))) return false;
  return text(value.ruleId) && oneOf(value.action, ["BUY", "SELL", "RISK_ALERT"]) && text(value.conditionCode) &&
    oneOf(value.outcome, ["SATISFIED", "UNSATISFIED", "MISSING_INPUT"]) &&
    (value.suppressionReason === null || oneOf(value.suppressionReason, ["ONCE_ALREADY_EMITTED", "TARGET_ALREADY_EMITTED"])) &&
    [value.missingInputs, value.blockers].every((items) => items === undefined || Array.isArray(items) && items.length <= 32 && items.every((item) => text(item))) &&
    (value.conditionEvidence === undefined || value.conditionEvidence === null || isExplicitEvidence(value.conditionEvidence));
}

function isSourceAlert(value: unknown, observedAt: string): boolean {
  return value === null || isRecord(value) && exact(value, ["eventId", "resultHash", "evaluatedAt", "dataCutoff"]) && uuid(value.eventId) && hash(value.resultHash) &&
    notLater(value.dataCutoff, value.evaluatedAt) && notLater(value.evaluatedAt, observedAt);
}

function validDeadline(value: unknown, risk: boolean, observedAt: string): boolean {
  return risk ? value === null : isShanghaiDateTime(value) && shanghaiDateTimeKey(value) > shanghaiDateTimeKey(observedAt);
}

function countsMatch(value: unknown, rows: Record<string, unknown>[]): boolean {
  const counts = { actionable: 0, blocked: 0, lowZoneWatch: 0, normal: 0, risk: 0, stale: 0 };
  if (!isRecord(value) || !exact(value, Object.keys(counts))) return false;
  for (const row of rows) {
    const scope = row.scope as Record<string, unknown>;
    const current = row.availability === "CURRENT";
    const legacy = row.planFamily === "LEGACY_LOW_BUY" && current ? row.decision as Record<string, unknown> : null;
    const health = legacy ? (legacy.dataHealth as Record<string, unknown>).status : null;
    const eligibility = current && row.planFamily === "EXPLICIT_RULES" ? row.ruleEligibility as Record<string, unknown>[] : [];
    const blocked = scope.status === "BLOCKED" || !!legacy && oneOf(health, ["BLOCKED", "GAPPED"]);
    const stale = row.availability === "CACHED" || !!legacy && !oneOf(health, ["LIVE", "BLOCKED", "GAPPED"]) || eligibility.some((rule) => rule.reasonCode === "INTRADAY_EXPIRED");
    const condition = current && row.planFamily === "CONDITION_PLAN" && isRecord(row.planRuntime) ? row.planRuntime : null;
    const conditionRisk = !!condition && Array.isArray(condition.risks) && condition.risks.some(r => isRecord(r) && r.status !== "CLEAR");
    const conditionStale = !!condition && Array.isArray(condition.dataBlockers) && condition.dataBlockers.length > 0;
    const risk = conditionRisk || !!legacy && legacy.riskStatus !== "CLEAR" || eligibility.some((rule) => rule.currentActionable && rule.action === "RISK_ALERT");
    const watch = !!legacy && scope.status === "READY" && health === "LIVE" && legacy.signalType === "LOW_ZONE_WATCH";
    const normal = current && scope.status === "READY" && !row.currentActionable && !blocked && !stale && !conditionStale && !risk && !watch &&
      (legacy ? health === "LIVE" && !oneOf(legacy.signalType, legacyActionable) : eligibility.every((rule) => rule.reasonCode === "NO_CURRENT_SIGNAL"));
    counts.actionable += Number(row.currentActionable); counts.blocked += Number(blocked); counts.stale += Number(stale || conditionStale);
    counts.risk += Number(risk); counts.lowZoneWatch += Number(watch); counts.normal += Number(normal);
  }
  return Object.entries(counts).every(([key, count]) => integer(value[key]) && value[key] === count);
}
