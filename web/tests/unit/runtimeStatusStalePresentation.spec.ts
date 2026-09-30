import { createPinia, setActivePinia } from "pinia";
import { expect, it } from "vitest";
import { useRuntimeMonitorStore } from "../../src/runtime-status/store";
import { explicitDashboard } from "../fixtures/runtimeStatus";
import { isRuntimeDashboard } from "../../src/runtime-status/validators";
it("never restores eligibility from an older result with the same activation identity", () => {
  setActivePinia(createPinia()); const store = useRuntimeMonitorStore();
  const old = explicitDashboard(); if (!isRuntimeDashboard(old)) throw new Error();
  store.applySnapshot(old, 0, 0); store.setTransport("LIVE");
  const next = explicitDashboard(); next.symbols[0]!.currentActionable = false; next.symbols[0]!.actionableRuleIds = [];
  const rules = next.symbols[0]!.ruleEligibility;
  if (!Array.isArray(rules)) throw new Error("fixture requires rules");
  Object.assign(rules[1]!, { currentActionable: false, reasonCode: "CURRENT_STATE_UNVERIFIED" });
  next.counts.risk = 0; next.counts.actionable = 0; next.counts.stale = 1;
  if (!isRuntimeDashboard(next)) throw new Error("fixture invalid");
  store.applySnapshot(next, 0, 0);
  expect(store.isActionable(old.symbols[0]!, "risk", 0)).toBe(false);
});
