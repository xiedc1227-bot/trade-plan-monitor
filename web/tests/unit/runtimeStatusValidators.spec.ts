import { describe, expect, it } from "vitest";
import { isRuntimeStatus, isRuntimeDashboard, isRuntimeHealth, isHeartbeat, isSnapshotRequired, isRuntimeSymbolCollection, isRuntimeSymbolDetail, isRuntimeSymbolHealth } from "../../src/runtime-status/validators";
import { emptyDashboard, explicitDashboard, generation, observedAt, planScope, runtimeStatus, runtimeHealth, explicitEntry, legacyEntry } from "../fixtures/runtimeStatus";

describe("runtime status closed contract", () => {
  it("rejects an explicit CURRENT result for a different or official-close target", () => {
    for (const target of [{ kind: "INTRADAY", targetEnd: "2026-09-14T10:05:00+08:00" }, { kind: "OFFICIAL_CLOSE", tradeDate: "2026-09-14" }]) {
      const value = explicitDashboard(); value.runtimeStatus.scopes[0]!.requiredTarget = target;
      expect(isRuntimeDashboard(value)).toBe(false);
    }
  });
  it("rejects non-running monitoring and repeated symbols with distinct scope keys", () => {
    expect(isRuntimeStatus({ ...runtimeStatus(), lifecycle: "STOPPING" }, observedAt)).toBe(false);
    const scope = planScope();
    expect(isRuntimeStatus({ ...runtimeStatus(), scopes: [{ ...scope, scopeKey: "plan:a" }, { ...scope, scopeKey: "plan:b" }] }, observedAt)).toBe(false);
  });
  it("accepts standby and a healthy scope before any decision exists", () => {
    const status = runtimeStatus();
    expect(isRuntimeStatus(status, observedAt)).toBe(true);
    status.scopes = [planScope()];
    expect(isRuntimeStatus(status, observedAt)).toBe(true);
  });
  it.each([
    { readOnly: true }, { reasonCode: "UNKNOWN" }, { lastProgressAt: "2026-09-14T10:11:00+08:00" },
    { coordinator: { state: "SCHEDULED", progressDueAt: null } },
    { coordinator: { state: "STALLED", progressDueAt: observedAt } },
    { coordinator: { state: "WORKING", progressDueAt: null } },
    { nextWakeAt: null }, { mode: "MONITORING" },
  ])("rejects contradictory or extra status fields %j", (change) => {
    expect(isRuntimeStatus({ ...runtimeStatus(), ...change }, observedAt)).toBe(false);
  });
  it.each([
    { readOnly: false, status: "WAITING", reasonCode: "AWAITING_FIRST_EVALUATION" },
    { progress: { requiredCount: null, completedCount: 0 } },
    { progress: { requiredCount: 1, completedCount: 2 } },
    { progress: { requiredCount: 2, completedCount: 1 } },
    { dataCutoff: "2026-09-14T10:11:00+08:00" },
    { reasonCode: "SCOPED_DEPENDENCY_FAILURE" },
    { requiredTarget: { kind: "INTRADAY", targetEnd: "2026-09-14T10:11:00+08:00" } },
    { activationRevision: Number.MAX_SAFE_INTEGER + 1 }, { kind: "PROVIDER" },
  ])("rejects invalid scope %j", (change) => {
    expect(isRuntimeStatus({ ...runtimeStatus(), scopes: [{ ...planScope(), ...change }] }, observedAt)).toBe(false);
  });
  it("rejects duplicate, unordered and overflowing scopes", () => {
    const scope = planScope();
    for (const scopes of [[scope, scope], [{ ...scope, scopeKey: "z" }, scope], Array.from({ length: 33 }, () => scope)]) {
      expect(isRuntimeStatus({ ...runtimeStatus(), scopes }, observedAt)).toBe(false);
    }
  });
});

describe("health and control frames", () => {
  it("requires the complete health resource envelope", () => {
    expect(isRuntimeHealth(runtimeHealth())).toBe(true);
    expect(isRuntimeHealth({ monitorContractVersion: 2 })).toBe(false);
    expect(isRuntimeHealth({ ...runtimeHealth(), readOnly: false })).toBe(false);
    expect(isRuntimeHealth({ ...runtimeHealth(), providers: undefined })).toBe(false);
    expect(isRuntimeHealth({ ...runtimeHealth(), lastCompletedMinuteAgeSeconds: 0 })).toBe(false);
    expect(isRuntimeHealth({ ...runtimeHealth(), database: { ...runtimeHealth().database, password: "secret" } })).toBe(false);
    expect(isRuntimeHealth({ ...runtimeHealth(), executor: { activeCount: 2, maxWorkers: 1, waitingCount: 0 } })).toBe(false);
  });
  it("accepts authoritative owner absence without inventing start timestamps", () => {
    const value = { ...runtimeHealth(), runtimeGeneration: null, startedAt: null,
      runtimeStatus: { ...runtimeStatus(), lifecycle: "STOPPED", mode: "BLOCKED", reasonCode: "RUNTIME_STOPPED", nextWakeAt: null,
        coordinator: { state: "STOPPED", progressDueAt: null } } };
    expect(isRuntimeHealth(value)).toBe(true);
    expect(isRuntimeHealth({ ...value, startedAt: observedAt })).toBe(false);
    const knownOwner = { ...value, runtimeGeneration: generation, startedAt: "2026-09-14T09:00:00+08:00" };
    expect(isRuntimeHealth(knownOwner)).toBe(false);
    expect(isRuntimeHealth({ ...knownOwner, stoppedAt: observedAt })).toBe(true);
    expect(isRuntimeHealth({ ...runtimeHealth(), stoppedAt: observedAt })).toBe(false);
  });
  it("requires exact v2 heartbeat and snapshot-required shapes", () => {
    const heartbeat = { type: "heartbeat", monitorContractVersion: 2, sequence: 7, runtimeGeneration: generation, observedAt, runtimeStatus: runtimeStatus() };
    expect(isHeartbeat(heartbeat)).toBe(true);
    expect(isHeartbeat({ ...heartbeat, runtimeLive: true })).toBe(false);
    expect(isHeartbeat({ ...heartbeat, sequence: Number.MAX_SAFE_INTEGER + 1 })).toBe(false);
    expect(isSnapshotRequired({ type: "snapshot.required", monitorContractVersion: 2, sequence: 7, reason: "REPLAY_UNAVAILABLE" })).toBe(true);
    expect(isSnapshotRequired({ type: "snapshot.required", sequence: 7, reason: "REPLAY_UNAVAILABLE" })).toBe(false);
  });
});

describe("remaining monitoring read roots", () => {
  const envelope = () => {
    const value = explicitDashboard();
    return { monitorContractVersion: 2, runtimeGeneration: generation, observedAt, runtimeStatus: value.runtimeStatus, sequence: 7 };
  };
  it("validates collection bounds and active total", () => {
    const value = { ...envelope(), items: [explicitEntry()], offset: 0, limit: 10, total: 1 };
    expect(isRuntimeSymbolCollection(value)).toBe(true);
    expect(isRuntimeSymbolCollection({ ...value, total: 2 })).toBe(false);
    expect(isRuntimeSymbolCollection({ ...value, offset: 1 })).toBe(false);
    expect(isRuntimeSymbolCollection({ ...value, items: [explicitEntry(), explicitEntry()] })).toBe(false);
  });
  it("uses the same explicit union in detail and the exact scope in symbol health", () => {
    const value = { ...envelope(), summary: explicitEntry(), legacyDetails: null };
    expect(isRuntimeSymbolDetail(value, "003043.SZ", true)).toBe(true);
    expect(isRuntimeSymbolDetail(value, "600000.SH", true)).toBe(false);
    expect(isRuntimeSymbolDetail({ ...value, legacyDetails: {} }, "003043.SZ", true)).toBe(false);
    const { sequence: _sequence, ...status } = envelope();
    expect(isRuntimeSymbolHealth({ ...status, scope: planScope() }, "003043.SZ")).toBe(true);
    expect(isRuntimeSymbolHealth({ ...status, scope: { ...planScope(), activationRevision: 2 } }, "003043.SZ")).toBe(false);
  });
  it("does not allow active identity to be replaced by an inactive envelope", () => {
    const value = { ...envelope(), symbol: "003043.SZ", availability: "UNAVAILABLE", reasonCode: "NO_ACTIVE_PLAN" };
    expect(isRuntimeSymbolDetail(value, "003043.SZ")).toBe(false);
    value.runtimeStatus.scopes = [];
    expect(isRuntimeSymbolDetail(value, "003043.SZ")).toBe(true);
    expect(isRuntimeSymbolDetail({ ...value, summary: null }, "003043.SZ")).toBe(false);
  });
  it("checks legacy lot totals against the immutable position summary", () => {
    const row = legacyEntry(); const value = { ...envelope(), runtimeStatus: { ...runtimeStatus(), scopes: [row.scope] }, summary: row,
      legacyDetails: { positionLots: [] as Record<string, unknown>[], referenceMarket: null, indexConditionEvidence: [] } };
    expect(isRuntimeSymbolDetail(value, row.symbol)).toBe(true);
    expect(isRuntimeSymbolDetail(value, row.symbol, true)).toBe(false);
    value.legacyDetails.positionLots = [{ acquiredTradeDate: "2026-09-11", bucket: "CORE", costFen: 1000, lotId: "lot", quantity: 100, remainingQuantity: 100, sellableQuantity: 100 }];
    expect(isRuntimeSymbolDetail(value, row.symbol)).toBe(false);
  });
});

describe("runtime dashboard authority", () => {
  it("accepts an empty authoritative dashboard", () => expect(isRuntimeDashboard(emptyDashboard())).toBe(true));
  it("accepts mixed expired buy/current risk with original UUIDv1 alert provenance", () => expect(isRuntimeDashboard(explicitDashboard())).toBe(true));
  it.each([
    (value: ReturnType<typeof explicitDashboard>) => { value.counts.actionable = 0; },
    (value: ReturnType<typeof explicitDashboard>) => { value.symbols.push(value.symbols[0]!); },
    (value: ReturnType<typeof explicitDashboard>) => { value.runtimeStatus.scopes = []; },
    (value: ReturnType<typeof explicitDashboard>) => { value.symbols[0]!.currentActionable = false; },
    (value: ReturnType<typeof explicitDashboard>) => { value.symbols[0]!.actionableRuleIds = ["buy", "risk"]; },
    (value: ReturnType<typeof explicitDashboard>) => { value.symbols[0]!.availability = "CACHED"; },
    (value: ReturnType<typeof explicitDashboard>) => { value.symbols[0]!.observedAt = "2026-09-14T10:10:16+08:00"; },
    (value: ReturnType<typeof explicitDashboard>) => { value.symbols[0]!.actionableUntil = null; },
  ])("fails closed for contradictory row/count/identity", (change) => {
    const value = explicitDashboard(); change(value); expect(isRuntimeDashboard(value)).toBe(false);
  });
  it("accepts legacy current, cached and unavailable entries without synthesizing evidence", () => {
    const value = emptyDashboard(); const row = legacyEntry();
    value.symbols = [row]; value.runtimeStatus.scopes = [row.scope]; value.counts.normal = 1;
    expect(isRuntimeDashboard(value)).toBe(true);
    row.availability = "CACHED"; value.counts.normal = 0; value.counts.stale = 1;
    expect(isRuntimeDashboard(value)).toBe(true);
    value.symbols = [{ symbol: row.symbol, name: row.name, planFamily: row.planFamily, planVersionId: row.planVersionId,
      planHash: row.planHash, activationRevision: row.activationRevision, observedAt, availability: "UNAVAILABLE", scope: row.scope,
      currentActionable: false, projectionState: "WAITING", reasonCode: "AWAITING_FIRST_EVALUATION" }];
    value.counts.stale = 0;
    expect(isRuntimeDashboard(value)).toBe(true);
    value.symbols[0]!.decision = row.decision;
    expect(isRuntimeDashboard(value)).toBe(false);
  });
  it.each([
    { sourceAlert: null }, { actionableUntil: observedAt }, { reasonCode: "NO_CURRENT_SIGNAL" },
    { sourceAlert: { eventId: "invalid", resultHash: "c".repeat(64), evaluatedAt: observedAt, dataCutoff: observedAt } },
    { sourceAlert: { eventId: "00000000-0000-1000-8000-000000000003", resultHash: "c".repeat(64), evaluatedAt: observedAt, dataCutoff: "2026-09-14T10:11:00+08:00" } },
    { action: "SELL" }, { ruleId: "other" }, { unexpected: true },
  ])("rejects contradictory true explicit risk eligibility %j", (change) => {
    const value = explicitDashboard(); const row = explicitEntry();
    row.ruleEligibility[1] = { ...row.ruleEligibility[1]!, ...change } as typeof row.ruleEligibility[number];
    value.symbols = [row]; expect(isRuntimeDashboard(value)).toBe(false);
  });
  it("accepts a future server BUY deadline but rejects equality and absent deadline", () => {
    const value = explicitDashboard(); const row = explicitEntry();
    row.ruleEligibility[0] = { ...row.ruleEligibility[0]!, currentActionable: true, reasonCode: null,
      sourceAlert: row.ruleEligibility[1]!.sourceAlert, actionableUntil: "2026-09-14T10:11:00+08:00" } as typeof row.ruleEligibility[number];
    row.actionableRuleIds = ["buy", "risk"]; value.symbols = [row]; value.counts.stale = 0;
    expect(isRuntimeDashboard(value)).toBe(true);
    row.ruleEligibility[0]!.actionableUntil = observedAt;
    expect(isRuntimeDashboard(value)).toBe(false);
    row.ruleEligibility[0]!.actionableUntil = null;
    expect(isRuntimeDashboard(value)).toBe(false);
  });
  it("preserves six-digit official-close risk result timestamps", () => {
    const value = emptyDashboard(); const row = legacyEntry();
    row.currentActionable = true;
    Object.assign(row.decision, { marketDataAt: "2026-09-11T15:00:00.000000+08:00", evaluatedAt: "2026-09-12T10:00:00.000000+08:00", dataAgeSeconds: 68400,
      dataHealth: { status: "STALE", fresh: false, requiredDataComplete: true, latestBarEnd: null, dataAgeSeconds: null },
      nextStep: { code: "WAIT_FOR_NEXT_TRADING_DAY" }, riskBreachTradeDate: "2026-09-11", riskStatus: "BREACHED_PENDING_CONFIRMATION", signalType: "RISK_BREACH", zone: "BELOW_RISK",
      evidence: [{ kind: "CONDITION", code: "OFFICIAL_CLOSE_BELOW_LEVEL", outcome: "SATISFIED", children: [], missingInputs: [], facts: [
        { key: "official_close_fen", unit: "FEN", value: 1000 }, { key: "risk_line_fen", unit: "FEN", value: 1100 }, { key: "official_trade_date", unit: "DATE", value: "2026-09-11" },
      ] }],
    });
    value.symbols = [row]; value.runtimeStatus.scopes = [row.scope]; value.counts = { actionable: 1, blocked: 0, stale: 1, risk: 1, lowZoneWatch: 0, normal: 0 };
    expect(isRuntimeDashboard(value)).toBe(true);
  });
});
