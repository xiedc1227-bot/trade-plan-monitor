import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { useRuntimeMonitorStore } from "../../src/runtime-status/store";
import { explicitDashboard, explicitEntry, observedAt } from "../fixtures/runtimeStatus";
import { isRuntimeDashboard } from "../../src/runtime-status/validators";

const dashboard = () => { const value = explicitDashboard(); if (!isRuntimeDashboard(value)) throw new Error("invalid fixture"); return value; };
beforeEach(() => setActivePinia(createPinia()));
describe("immutable runtime snapshot and local invalidation", () => {
  it("separates transport from backend status and never changes immutable eligibility", () => {
    const store = useRuntimeMonitorStore(); const value = dashboard();
    expect(store.applySnapshot(value, 0, 0)).toBe(true); store.setTransport("LIVE");
    expect(store.isActionable(value.symbols[0]!, "risk", 0)).toBe(true);
    expect(store.isActionable(value.symbols[0]!, "buy", 0)).toBe(false);
    store.invalidatePresentation();
    expect(store.isActionable(value.symbols[0]!, "risk", 0)).toBe(false);
    expect(store.snapshot?.symbols[0]?.currentActionable).toBe(true);
    expect(store.runtimeStatus?.mode).toBe("MONITORING");
  });
  it("expires one explicit rule at its server deadline while retaining independently proven risk", () => {
    const value = explicitDashboard(); const row = explicitEntry();
    Object.assign(row.ruleEligibility[0]!, { currentActionable: true, reasonCode: null, sourceAlert: row.ruleEligibility[1]!.sourceAlert, actionableUntil: "2026-09-14T10:10:20.000000+08:00" });
    row.actionableRuleIds = ["buy", "risk"]; value.symbols = [row]; value.counts.stale = 0;
    if (!isRuntimeDashboard(value)) throw new Error("invalid fixture");
    const store = useRuntimeMonitorStore(); store.applySnapshot(value, 1000, 2000); store.setTransport("LIVE");
    expect(store.nextDeadline).toBe(6000);
    expect(store.isActionable(value.symbols[0]!, "buy", 5999)).toBe(true);
    expect(store.expire(6000)).toBe(true);
    expect(store.isActionable(value.symbols[0]!, "buy", 6000)).toBe(false);
    expect(store.isActionable(value.symbols[0]!, "risk", 6000)).toBe(true);
    expect(store.snapshot?.symbols[0]?.currentActionable).toBe(true);
  });
  it("rejects a delayed snapshot behind a newer status observation", () => {
    const store = useRuntimeMonitorStore(); const value = dashboard(); store.applySnapshot(value, 0, 0);
    store.applyObservation({ type: "heartbeat", monitorContractVersion: 2, sequence: value.sequence, runtimeGeneration: value.runtimeGeneration,
      observedAt: "2026-09-14T10:10:16.000000+08:00", runtimeStatus: value.runtimeStatus });
    expect(store.applySnapshot(value, 0, 100)).toBe(false);
    expect(store.observedAt).not.toBe(observedAt);
  });
  it("cannot restore local invalidation through heartbeat or transport alone", () => {
    const store = useRuntimeMonitorStore(); const value = dashboard(); store.applySnapshot(value, 0, 0); store.invalidatePresentation();
    store.applyObservation({ type: "heartbeat", monitorContractVersion: 2, sequence: 7, runtimeGeneration: value.runtimeGeneration, observedAt, runtimeStatus: value.runtimeStatus });
    store.setTransport("LIVE"); expect(store.isActionable(value.symbols[0]!, "risk", 0)).toBe(false);
  });
});
