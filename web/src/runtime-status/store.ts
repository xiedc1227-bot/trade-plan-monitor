import { defineStore } from "pinia";
import { computed, shallowReadonly, shallowRef } from "vue";
import type { RuntimeDashboardResponse, RuntimeHeartbeatFrame, RuntimeStatusView } from "../api/generated-runtime-status";
import { shanghaiDateTimeKey } from "../api/shanghaiTime";
import { monotonicDeadline } from "./deadlines";
import { isRuntimeDashboard } from "./validators";

export type PlanEntry = RuntimeDashboardResponse["symbols"][number];
export type TransportState = "CONNECTING" | "AWAITING_HEARTBEAT" | "LIVE" | "DISCONNECTED" | "RECONNECTING" | "RELOAD_REQUIRED";

export function presentationKey(row: PlanEntry, ruleId = ""): string {
  return JSON.stringify([row.symbol, row.planVersionId, row.planHash, row.activationRevision, ruleId]);
}

export const useRuntimeMonitorStore = defineStore("runtime-monitor-v2", () => {
  const snapshot = shallowRef<RuntimeDashboardResponse | null>(null);
  const runtimeStatus = shallowRef<RuntimeStatusView | null>(null);
  const observedAt = shallowRef<string | null>(null);
  const transport = shallowRef<TransportState>("DISCONNECTED");
  const invalidations = shallowRef<ReadonlySet<string>>(new Set());
  const deadlines = shallowRef<Readonly<Record<string, number>>>({});
  const error = shallowRef<string | null>(null);
  const nextDeadline = computed(() => {
    const remaining = Object.entries(deadlines.value).filter(([key]) => !invalidations.value.has(key)).map(([, value]) => value);
    return remaining.length ? Math.min(...remaining) : null;
  });

  function applySnapshot(value: RuntimeDashboardResponse, sentAt: number, receivedAt: number, resetObservation = false): boolean {
    if (!isRuntimeDashboard(value)) return false;
    if (snapshot.value && value.sequence < snapshot.value.sequence) return false;
    if (!resetObservation && snapshot.value?.runtimeGeneration === value.runtimeGeneration && observedAt.value !== null &&
      shanghaiDateTimeKey(value.observedAt) < shanghaiDateTimeKey(observedAt.value)) return false;
    const nextDeadlines: Record<string, number> = {};
    const expired = new Set<string>();
    for (const row of value.symbols) {
      if (row.availability !== "CURRENT") continue;
      const entries = row.planFamily === "LEGACY_LOW_BUY"
        ? [{ key: presentationKey(row), actionable: row.currentActionable, until: row.actionableUntil }]
        : row.planFamily === "CONDITION_PLAN" ? [
          ...row.planRuntime.signals.filter(signal => signal.executableQty > 0).map(signal => ({ key: presentationKey(row, signal.signalId), actionable: row.currentActionable, until: signal.executionDate ? `${signal.executionDate}T15:00:00+08:00` : null })),
          { key: presentationKey(row), actionable: row.currentActionable, until: null },
        ] : row.ruleEligibility.map((rule) => ({ key: presentationKey(row, rule.ruleId), actionable: rule.currentActionable, until: rule.actionableUntil }));
      for (const entry of entries) {
        if (!entry.actionable) continue;
        const deadline = monotonicDeadline(entry.until, value.observedAt, sentAt, receivedAt);
        if (deadline !== null) { nextDeadlines[entry.key] = deadline; if (deadline <= receivedAt) expired.add(entry.key); }
      }
    }
    snapshot.value = freeze(structuredClone(value));
    runtimeStatus.value = snapshot.value.runtimeStatus;
    observedAt.value = value.observedAt;
    deadlines.value = Object.freeze(nextDeadlines); invalidations.value = expired; error.value = null;
    return true;
  }

  function applyObservation(frame: RuntimeHeartbeatFrame): void {
    runtimeStatus.value = freeze(structuredClone(frame.runtimeStatus)); observedAt.value = frame.observedAt;
  }

  function invalidatePresentation(symbols?: readonly string[]): void {
    const next = new Set(invalidations.value);
    for (const row of snapshot.value?.symbols ?? []) {
      if (symbols && !symbols.includes(row.symbol)) continue;
      if (row.availability !== "UNAVAILABLE" && row.planFamily === "EXPLICIT_RULES") {
        for (const rule of row.ruleEligibility) next.add(presentationKey(row, rule.ruleId));
      } else next.add(presentationKey(row));
    }
    invalidations.value = next;
  }

  function expire(now: number): boolean {
    const next = new Set(invalidations.value);
    for (const [key, deadline] of Object.entries(deadlines.value)) if (now >= deadline) next.add(key);
    if (next.size === invalidations.value.size) return false;
    invalidations.value = next; return true;
  }

  function isActionable(row: PlanEntry, ruleId?: string, now = performance.now()): boolean {
    if (transport.value !== "LIVE" || row.availability !== "CURRENT") return false;
    const installed = snapshot.value?.symbols.find((entry) => entry.symbol === row.symbol);
    if (!installed || installed.availability !== "CURRENT" || presentationKey(installed) !== presentationKey(row)) return false;
    row = installed;
    if (row.planFamily === "EXPLICIT_RULES" && ruleId === undefined) return row.ruleEligibility.some((rule) => isActionable(row, rule.ruleId, now));
    const key = presentationKey(row, ruleId);
    if (invalidations.value.has(key) || (deadlines.value[key] !== undefined && now >= deadlines.value[key]!)) return false;
    return row.planFamily === "LEGACY_LOW_BUY" || row.planFamily === "CONDITION_PLAN" ? row.currentActionable : row.ruleEligibility.some((rule) => rule.ruleId === ruleId && rule.currentActionable);
  }

  function setTransport(value: TransportState): void { transport.value = value; }
  function setError(value: string | null): void { error.value = value; }
  return { snapshot: shallowReadonly(snapshot), runtimeStatus: shallowReadonly(runtimeStatus), observedAt: shallowReadonly(observedAt),
    transport: shallowReadonly(transport), invalidations: shallowReadonly(invalidations), deadlines: shallowReadonly(deadlines), error: shallowReadonly(error), nextDeadline,
    applySnapshot, applyObservation, invalidatePresentation, expire, isActionable, setTransport, setError };
});

function freeze<T>(value: T): T {
  if (value !== null && typeof value === "object") { for (const child of Object.values(value)) freeze(child); Object.freeze(value); }
  return value;
}
