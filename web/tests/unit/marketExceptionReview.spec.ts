import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { isConditionPlanJson } from "../../src/api/conditionPlans";
import PlanExceptionPermissions from "../../src/components/plans/PlanExceptionPermissions.vue";
import { usePlanWorkspace } from "../../src/composables/usePlanWorkspace";

describe("plan permission is distinct from occurrence approval", () => {
  it("invalidates the reviewed version when a route permission is edited", () => {
    let work!: ReturnType<typeof usePlanWorkspace>;
    const host = mount({ setup() { work = usePlanWorkspace(); return {}; }, template: "<div />" });
    work.saved.value = JSON.parse('{"id":"reviewed-version"}');
    work.activated.value = JSON.parse('{"active":true}');
    work.preview.value = JSON.parse('{"candidateJson":"{}"}');
    work.edit({ schema_version: 7, ordinary_rules: [{ market_policy: { exception_routes: { weak_minimum: "DISABLED", broken_strong: "PER_OCCURRENCE" } } }] });
    expect(work.saved.value).toBeNull(); expect(work.activated.value).toBeNull(); expect(work.preview.value).toBeNull();
    expect(work.dirty.value).toBe(true); host.unmount();
  });
  it("admits only the explicit schema 7 execution pair", () => {
    for (const execution_version of ["condition-plan-v1", "condition-plan-v2", "condition-plan-v3"]) {
      expect(isConditionPlanJson(JSON.stringify({ schema_version: 7, execution_mode: "CONDITION_PLAN", execution_version })))
        .toBe(execution_version === "condition-plan-v3");
    }
  });
  it("shows independent permissions, missing source and exact different quantity rules without an approval action", async () => {
    const candidate = { schema_version: 7, ordinary_rules: [{ rule_id: "buy", market_policy: {
      exception_routes: { weak_minimum: "PER_OCCURRENCE", broken_strong: "DISABLED" },
    } }] };
    const wrapper = mount(PlanExceptionPermissions, { props: { candidate } });
    expect(wrapper.text()).toContain("允许逐次申请");
    expect(wrapper.text()).toContain("不允许申请");
    expect(wrapper.text()).toContain("0.5 × Q0 < 官方最小量 ≤ Q0");
    expect(wrapper.text()).toContain("S1"); expect(wrapper.text()).toContain("S2");
    expect(wrapper.text()).toContain("Qe 必须人工填写");
    expect(wrapper.text()).toContain("批准不执行模拟交易");
    expect(wrapper.findAll("button")).toHaveLength(0);
    await wrapper.setProps({ candidate: { schema_version: 7, ordinary_rules: [{ rule_id: "buy", market_policy: {} }] } });
    expect(wrapper.text()).toContain("缺少许可，阻断审核与执行");
    expect(wrapper.emitted()).toEqual({});
  });
});
