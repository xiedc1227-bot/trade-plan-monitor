export const observedAt = "2026-09-14T10:10:15.000000+08:00";
export const generation = "00000000-0000-4000-8000-000000000001";
export const planVersionId = "00000000-0000-4000-8000-000000000002";

export function runtimeStatus() {
  return {
    lifecycle: "RUNNING", mode: "STANDBY", reasonCode: "NO_ACTIVE_PLANS" as string | null,
    nextWakeAt: "2026-09-14T10:10:30.000000+08:00", nextRetryAt: null,
    lastProgressAt: "2026-09-14T10:10:00.000000+08:00",
    coordinator: { state: "SCHEDULED", progressDueAt: "2026-09-14T10:10:30.000000+08:00" },
    scopes: [] as Record<string, unknown>[],
  };
}

export function planScope() {
  return {
    scopeKey: "plan:003043.SZ", kind: "PLAN", status: "READY", reasonCode: null,
    requiredTarget: { kind: "INTRADAY", targetEnd: "2026-09-14T10:10:00.000000+08:00" },
    dataCutoff: "2026-09-14T10:10:00.000000+08:00", nextRetryAt: null,
    progress: { requiredCount: 40, completedCount: 40 }, symbol: "003043.SZ",
    planFamily: "EXPLICIT_RULES", planVersionId, planHash: "a".repeat(64),
    activationRevision: 1, readOnly: false,
  };
}

export function emptyDashboard() {
  return { monitorContractVersion: 2, sequence: 7, runtimeGeneration: generation, observedAt,
    runtimeStatus: runtimeStatus(), counts: { actionable: 0, blocked: 0, lowZoneWatch: 0, normal: 0, risk: 0, stale: 0 },
    symbols: [] as Record<string, unknown>[], marketIndexes: [], marketTurnover: null };
}

export function explicitEntry() {
  return {
    symbol: "003043.SZ", name: "华亚智能", planFamily: "EXPLICIT_RULES", planVersionId,
    planHash: "a".repeat(64), activationRevision: 1, observedAt, availability: "CURRENT",
    scope: planScope(), currentActionable: true, resultHash: "b".repeat(64),
    explicitRuntime: { symbol: "003043.SZ", planVersionId, planHash: "a".repeat(64), activationRevision: 1,
      status: "CURRENT", evaluatedAt: "2026-09-14T10:10:00.000000+08:00", targetBucketEnd: "2026-09-14T10:10:00.000000+08:00",
      ruleOutcomes: [
        { ruleId: "buy", action: "BUY", conditionCode: "PRICE_ABOVE", outcome: "SATISFIED", missingInputs: [], blockers: [], suppressionReason: "ONCE_ALREADY_EMITTED", conditionEvidence: null },
        { ruleId: "risk", action: "RISK_ALERT", conditionCode: "PRICE_BELOW", outcome: "SATISFIED", missingInputs: [], blockers: [], suppressionReason: "ONCE_ALREADY_EMITTED", conditionEvidence: null },
      ] },
    ruleEligibility: [
      { ruleId: "buy", action: "BUY", currentActionable: false, reasonCode: "INTRADAY_EXPIRED", actionableUntil: null as string | null, sourceAlert: null },
      { ruleId: "risk", action: "RISK_ALERT", currentActionable: true, reasonCode: null, actionableUntil: null as string | null,
        sourceAlert: { eventId: "00000000-0000-1000-8000-000000000003", resultHash: "c".repeat(64),
          evaluatedAt: "2026-09-11T15:00:00.000000+08:00", dataCutoff: "2026-09-11T15:00:00.000000+08:00" } },
    ], actionableRuleIds: ["risk"],
  };
}

export function explicitDashboard() {
  const value = emptyDashboard();
  const row = explicitEntry();
  value.runtimeStatus.mode = "MONITORING";
  value.runtimeStatus.reasonCode = null;
  value.runtimeStatus.scopes = [row.scope];
  value.symbols = [row];
  value.counts = { actionable: 1, blocked: 0, lowZoneWatch: 0, normal: 0, risk: 1, stale: 1 };
  return value;
}

export function runtimeHealth() {
  return { monitorContractVersion: 2, runtimeGeneration: generation, observedAt, runtimeStatus: runtimeStatus(),
    startedAt: "2026-09-14T09:00:00.000000+08:00", stoppedAt: null,
    lastCompletedMinute: null, lastCompletedMinuteAgeSeconds: null, latestEvaluationAt: null, latestEvaluationAgeSeconds: null,
    gaps: [], cooldownUntil: null, providers: [], executor: { activeCount: 0, maxWorkers: 2, waitingCount: 0 },
    database: { status: "READY", walStatus: "READY", lastBackupAt: null, lastCheckpointAt: null, errorCode: null },
    delivery: { status: "READY", pendingCount: 0, failedCount: 0, lastDeliveredAt: null, nextRetryAt: null, errorCode: null },
  };
}

export function legacyEntry() {
  const scope = { ...planScope(), planFamily: "LEGACY_LOW_BUY" };
  return { symbol: scope.symbol, name: "华亚智能", planFamily: scope.planFamily, planVersionId: scope.planVersionId,
    planHash: scope.planHash, activationRevision: scope.activationRevision, observedAt, availability: "CURRENT", scope,
    currentActionable: false, actionableUntil: null, riskDistanceFen: 100, satisfiedConditionCount: 0, totalConditionCount: 1, referenceMarket: null,
    decision: { symbol: scope.symbol, planId: "plan-1", planVersion: 1, planHash: scope.planHash, resultHash: "d".repeat(64),
      evaluatedAt: "2026-09-14T10:10:00.000000+08:00", marketDataAt: "2026-09-14T10:10:00.000000+08:00", dataAgeSeconds: 0,
      dataHealth: { status: "LIVE", fresh: true, requiredDataComplete: true, latestBarEnd: "2026-09-14T10:10:00.000000+08:00", dataAgeSeconds: 0 },
      episodeLowFen: null, episodeStatus: null, evidence: [] as unknown[], nextStep: { code: "WAIT_FOR_COMPLETE_BAR" },
      position: { coreQuantity: 0, sellableCoreQuantity: 0, sellableTacticalQuantity: 0, tacticalQuantity: 0, totalQuantity: 0 },
      priceFen: 1000, riskBreachTradeDate: null, riskStatus: "CLEAR", signalType: "WAIT", zone: "OBSERVATION",
    } };
}
