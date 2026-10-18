import { readFileSync } from "node:fs";
import { mount } from "@vue/test-utils";
import { expect, it } from "vitest";
import type { BacktestLoopEventView, BacktestLoopFillView } from "../../src/api/generated";
import { validLoopFill } from "../../src/api/monitorLoopValues";
import Timeline from "../../src/components/backtests/MonitorLoopTimeline.vue";
import RiskScopeSummary from "../../src/components/backtests/RiskScopeSummary.vue";

const fixture = JSON.parse(readFileSync("tests/fixtures/monitor-loop-results.json", "utf8")) as {
  fills: { items: BacktestLoopFillView[] }; details: { items: BacktestLoopEventView[] };
};

it("keeps legacy fills readable and accepts exact scoped-exit allocations", () => {
  const fill = structuredClone(fixture.fills.items[0]!);
  expect(validLoopFill(fill)).toBe(true);
  fill.receipt.authority_receipt.side = "SELL";
  fill.receipt.settlement.side = "SELL";
  fill.receipt.authority_receipt.lot_allocations = [{ id: "old-position", bucket: "TACTICAL",
    quantity: fill.receipt.authority_receipt.quantity }];
  expect(validLoopFill(fill)).toBe(true);
  fill.receipt.authority_receipt.lot_allocations[0]!.quantity += 100;
  expect(validLoopFill(fill)).toBe(false);
});

it("shows the actual exited lot separately from holdings outside its scope", () => {
  const item = structuredClone(fixture.details.items.find(row => row.event.payload.kind === "EXECUTED")!);
  const payload = item.event.payload;
  if (payload.kind !== "EXECUTED" || !payload.attempt.receipt) throw new Error("filled fixture required");
  const authority = payload.attempt.receipt.authority_receipt;
  authority.side = "SELL";
  authority.lot_allocations = [{ id: "old-position", bucket: "TACTICAL", quantity: authority.quantity }];
  const wrapper = mount(Timeline, { props: { items: [item] } });
  expect(wrapper.text()).toContain("实际退出批次 old-position");
  expect(wrapper.text()).toContain("范围外持仓按各自规则处理");
  wrapper.unmount();
});

it("does not describe a tactical-only severe exit as a full-position price stop", () => {
  const wrapper = mount(RiskScopeSummary, { props: { changes: [
    { target: "levels", rule_id: null, after: { risk_line_fen: 2599 } },
    { target: "risk_branches", rule_id: "severe-old", after: { kind: "SEVERE_TECHNICAL",
      involves_core: false, target_core_qty: 0, target_tactical_qty: 0,
      holding_scope: { mode: "BEFORE_TRADE_DATE", trade_date: "2026-10-09" } } },
  ] } });
  expect(wrapper.text()).toContain("不涉及核心仓");
  expect(wrapper.text()).not.toContain("范围内持仓全部退出");
  expect(wrapper.text()).not.toContain("风险线 25.99");
  wrapper.unmount();
});
