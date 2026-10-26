import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { isConditionPlanJson } from "../../src/api/conditionPlans";
import P2PolicyReview from "../../src/components/plans/P2PolicyReview.vue";

describe("P2 reviewed policy boundaries", () => {
  it("admits only the schema 8 / v4 pair", () => {
    expect(isConditionPlanJson(JSON.stringify({ schema_version: 8, execution_mode: "CONDITION_PLAN", execution_version: "condition-plan-v4" }))).toBe(true);
    expect(isConditionPlanJson(JSON.stringify({ schema_version: 8, execution_mode: "CONDITION_PLAN", execution_version: "condition-plan-v3" }))).toBe(false);
  });
  it("shows source modes, missing evidence and separate approval without controls", async () => {
    const wrapper = mount(P2PolicyReview, { props: { candidate: { schema_version: 8, ordinary_rules: [{ rule_id: "buy", pretrade_policy: {
      sizing: { mode: "ATR_RATIO_TIERS", base_qty: 1000 }, economics: { mode: "PREVIEW_ONLY" }, level_evidence: [],
    } }] } } });
    expect(wrapper.text()).toContain("研究估算");
    expect(wrapper.text()).toContain("先按波动分档");
    expect(wrapper.text()).toContain("缺少来源");
    expect(wrapper.text()).toContain("逐次批准");
    expect(wrapper.findAll("button")).toHaveLength(0);
    await wrapper.setProps({ candidate: { schema_version: 7 } });
    expect(wrapper.text()).toBe("");
  });
});
