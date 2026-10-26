import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import P3CapitalRuntime from "../../src/components/plans/P3CapitalRuntime.vue";
import P3CapitalAssessment from "../../src/components/plans/P3CapitalAssessment.vue";
import { validCapitalResponse } from "../../src/api/p3Capital";
import fixture from "../fixtures/p3-capital.json";

const value = () => JSON.parse(JSON.stringify(fixture.ordinary));
function props(request: <T>(url: string, body?: object) => Promise<T>) {
  return {evidence: value().evidence, planVersionId: "p3-plan", current: true, authorityRevision: 1, request};
}
describe("current monetary preview", () => {
  it("validates strict non-authority and complete assessment responses", () => {
    expect(validCapitalResponse("/plan-capital-previews", value())).toBe(true);
    expect(validCapitalResponse("/plan-capital-previews", {...value(), authorityGranted: true})).toBe(false);
    expect(validCapitalResponse("/plan-capital-previews", {...value(), quantity: 100})).toBe(false);
    expect(validCapitalResponse("/plan-capital-previews", {...value(), assessment: {...value().assessment, after_fen: 1.5}})).toBe(false);
  });
  it("displays exact occupancy and explains the frozen whole quantity without trade buttons", async () => {
    const request = vi.fn(async (_url: string, _body?: object) => value());
    const wrapper = mount(P3CapitalRuntime, {props: props(request)});
    await wrapper.get("button").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("322.00 元");
    expect(wrapper.text()).toContain("200 股");
    expect(wrapper.text()).toContain("不设股数上限");
    expect(wrapper.text()).toContain("不会随预算变化重新计算");
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0]?.[0]).toBe("/api/v1/plan-capital-previews");
    expect(wrapper.findAll("button")).toHaveLength(1);
  });
  it("keeps broken quantity empty, sends exactly explicit intent and clears changed previews", async () => {
    const request = vi.fn(async () => JSON.parse(JSON.stringify(fixture.broken)));
    const wrapper = mount(P3CapitalRuntime, {props: {...props(request), manualQuantity: true, occurrenceId: "candidate"}});
    expect(wrapper.get<HTMLInputElement>("input").element.value).toBe("");
    await wrapper.get("button").trigger("click"); await flushPromises();
    expect(request).not.toHaveBeenCalled();
    await wrapper.get("input").setValue("300");
    await wrapper.get("button").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("483.00 元");
    await wrapper.get("input").setValue("200");
    expect(wrapper.findComponent(P3CapitalAssessment).exists()).toBe(false);
  });
  it("drops late responses after an authority revision or plan switch", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    const request = vi.fn(async (_url: string) => JSON.parse(JSON.stringify(
      await new Promise(done => {resolve = done;}))));
    const wrapper = mount(P3CapitalRuntime, {props: props(request)});
    await wrapper.get("button").trigger("click");
    await wrapper.setProps({authorityRevision: 2});
    resolve(value()); await flushPromises();
    expect(wrapper.findComponent(P3CapitalAssessment).exists()).toBe(false);
  });
  it("explains missing cost and over-cap failure with no implicit sell", () => {
    const assessment = value().assessment;
    assessment.outcome = "UNKNOWN"; assessment.blockers = ["CAPITAL_BASE_UNKNOWN"];
    const wrapper = mount(P3CapitalAssessment, {props: {assessment}});
    expect(wrapper.text()).toContain("需单独核对并确认");
    expect(wrapper.findAll("button")).toHaveLength(0);
    expect(wrapper.text()).toContain("不阻断技术风险卖出");
  });
});
