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
