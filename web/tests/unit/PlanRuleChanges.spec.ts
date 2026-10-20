import { expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import PlanRuleChanges from "../../src/components/backtests/PlanRuleChanges.vue";

it("groups all four outcomes and shows only changed values with exact source text", () => {
  const wrapper = mount(PlanRuleChanges, { props: {
    changes: [
      { target: "position", rule_id: null, action: "MODIFY", before: { max_qty: 300, core_target_qty: 0 }, after: { max_qty: 500, core_target_qty: 0 }, clause_ids: ["c1"] },
      { target: "ordinary_rules", rule_id: "buy", action: "RETAIN", before: { quantity: 100 }, after: { quantity: 100 }, clause_ids: [] },
      { target: "alert_rules", rule_id: "alert", action: "ADD", before: null, after: { reason: "<script>source</script>" }, clause_ids: [] },
      { target: "ordinary_rules", rule_id: "sell", action: "REVOKE", before: { quantity: 200 }, after: null, clause_ids: ["c2"] },
    ], clauses: [{ clause_id: "c1", excerpt: "最大持仓调整为500股" }, { clause_id: "c2", excerpt: "取消卖出规则" }],
  } });
  for (const name of ["保留", "修改", "新增", "取消"]) expect(wrapper.text()).toContain(name + "（1）");
  expect(wrapper.text()).toContain("300 → 500");
  expect(wrapper.text()).toContain("最大持仓调整为500股");
  expect(wrapper.text()).not.toContain("拟定CORE");
  expect(wrapper.find('script').exists()).toBe(false);
  expect(wrapper.emitted()).toEqual({});
  wrapper.unmount();
});
it("shows business changes with yuan values and no internal rule identifiers or review actions", () => {
  const wrapper = mount(PlanRuleChanges, { props: { businessMode: true, changes: [
    { target: "levels", rule_id: "internal-rule", action: "MODIFY", before: { risk_line_fen: 2500 }, after: { risk_line_fen: 2599 }, clause_ids: [] },
    { target: "ordinary_rules", rule_id: "internal-buy", action: "ADD", before: null,
      after: { rule_id: "internal-buy", quantity: 200, condition: { reference_price_fen: 2600 } }, clause_ids: [] },
  ] } });
  expect(wrapper.text()).toContain("本次交易条件变化");
  expect(wrapper.text()).toContain("25.00 元 → 25.99 元");
  expect(wrapper.text()).toContain("26.00 元");
  expect(wrapper.text()).toContain("200");
  expect(wrapper.text()).not.toContain("internal-rule");
  expect(wrapper.text()).not.toContain("internal-buy");
  expect(wrapper.text()).not.toContain("统一审核本份计划");
  expect(wrapper.emitted()).toEqual({});
  wrapper.unmount();
});

it("explains changed prerequisite rules in business terms without displaying their internal IDs", () => {
  const wrapper = mount(PlanRuleChanges, { props: { businessMode: true, changes: [
    { target: "ordinary_rules", rule_id: "first-buy", action: "RETAIN", before: { side: "BUY", quantity: 100 }, after: { side: "BUY", quantity: 100 }, clause_ids: [] },
    { target: "ordinary_rules", rule_id: "second-buy", action: "RETAIN", before: { side: "BUY", quantity: 200 }, after: { side: "BUY", quantity: 200 }, clause_ids: [] },
    { target: "ordinary_rules", rule_id: "sell", action: "MODIFY", before: { independent_signal: { prior_rule_id: "first-buy" } },
      after: { independent_signal: { prior_rule_id: "second-buy" } }, clause_ids: [] },
  ] } });
  expect(wrapper.text()).toContain("买入 100 股（第 1 条规则） → 买入 200 股（第 2 条规则）");
  expect(wrapper.text()).toContain("必须先完成的规则");
  for (const id of ["first-buy", "second-buy", "prior_rule_id"]) expect(wrapper.text()).not.toContain(id);
  wrapper.unmount();
});

it("shows unresolved scope without claiming old rules were cancelled", () => {
  const wrapper = mount(PlanRuleChanges, { props: { changes: [], unresolved: true } });
  expect(wrapper.text()).toContain("部分变更含义或目标尚不明确");
  expect(wrapper.text()).toContain("未提及的规则默认保留");
  expect(wrapper.text()).not.toContain("取消（1）");
  wrapper.unmount();
});

it("shows removed nested values without a misleading unset-to-unset parent row", () => {
  const wrapper = mount(PlanRuleChanges, { props: { resultMode: true, changes: [
    { target: "levels", rule_id: null, action: "MODIFY", before: { low_buy: { low_fen: 2640, high_fen: 2670 } }, after: { low_buy: null }, clause_ids: [] },
  ] } });
  expect(wrapper.text()).toContain("26.40 元");
  expect(wrapper.findAll("tbody tr")).toHaveLength(2);
  wrapper.unmount();
});
