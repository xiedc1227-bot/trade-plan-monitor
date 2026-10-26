import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { isConditionPlanJson } from "../../src/api/conditionPlans";
import P3CapitalOpening from "../../src/components/plans/P3CapitalOpening.vue";
import { validCapitalResponse } from "../../src/api/p3Capital";
import P3PolicyReview from "../../src/components/plans/P3PolicyReview.vue";

describe("P3 source meaning review", () => {
  it("admits only the exact schema9 and v5 pair", () => {
    expect(isConditionPlanJson(JSON.stringify({schema_version: 9, execution_mode: "CONDITION_PLAN", execution_version: "condition-plan-v5"}))).toBe(true);
    expect(isConditionPlanJson(JSON.stringify({schema_version: 9, execution_mode: "CONDITION_PLAN", execution_version: "condition-plan-v4"}))).toBe(false);
  });
  it.each(["OPEN_COST_CAP", "MARKET_VALUE_CAP", null])("explains %s without inventing authority", mode => {
    const wrapper = mount(P3PolicyReview, {props: {candidate: {schema_version: 9, position: {limit: {
      mode: "CAPITAL_ONLY", capital_policy: {mode, cap_fen: 550500},
    }}}}});
    expect(wrapper.text()).toContain("仅金额上限，不设股数上限");
    expect(wrapper.text()).toContain("5505.00 元");
    expect(wrapper.text()).toContain("超限不会自动缩量");
    expect(wrapper.findAll("button")).toHaveLength(0);
    if (mode === "OPEN_COST_CAP") expect(wrapper.text()).toContain("缺少来源");
    if (mode === "MARKET_VALUE_CAP") expect(wrapper.text()).toContain("不需要开仓成本");
    if (mode === null) expect(wrapper.text()).toContain("总投入预算");
  });
});


function bookView() {
  return {computedAt: "2026-09-18T16:00:00+08:00", symbol: "601021.SH", inventoryKnown: true,
    inventoryRevision: 1, retainedBasisFen: null, bookRevision: null, book: null,
    inventoryLots: [{lot_id: "initial-TACTICAL", bucket: "TACTICAL", quantity: 400}], authorityGranted: false};
}
function props(request: <T>(url: string, body?: object, key?: string) => Promise<T>) {
  return {planVersionId: "version-a", symbol: "601021.SH", costRequired: true,
    current: true, authorityRevision: 1, request};
}
describe("independent budget opening review", () => {
  it("validates bounded server lots and literal false authority", () => {
    expect(validCapitalResponse("/simulation-capital-books/601021.SH", bookView())).toBe(true);
    expect(validCapitalResponse("/simulation-capital-books/601021.SH", {...bookView(), authorityGranted: true})).toBe(false);
    expect(validCapitalResponse("/simulation-capital-books/601021.SH", {...bookView(), inventoryLots: Array(501).fill(bookView().inventoryLots[0])})).toBe(false);
  });
  it("starts costs blank and requires complete explicit confirmation before one opening command", async () => {
    const request = vi.fn(async (url: string) => JSON.parse(JSON.stringify(url.endsWith("openings")
      ? {event: {received_at: "2026-09-18T16:01:00+08:00"}, authorityGranted: false, inventoryChanged: false} : bookView())));
    const wrapper = mount(P3CapitalOpening, {props: props(request)});
    await flushPromises();
    expect(wrapper.get<HTMLInputElement>('input[type="number"]').element.value).toBe("");
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get('input[type="number"]').setValue("450000");
    await wrapper.get('input[type="datetime-local"]').setValue("2026-09-18T16:00:00");
    await wrapper.get('input:not([type])').setValue("Explicit simulation statement");
    await wrapper.findAll("textarea")[0]!.setValue("Complete retained lot basis is450000fen");
    await wrapper.findAll("textarea")[1]!.setValue("Reviewed current complete lot");
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get('input[type="checkbox"]').setValue(true);
    await wrapper.get("form").trigger("submit"); await flushPromises();
    const writes = request.mock.calls.filter(c => c[0].endsWith("openings"));
    expect(writes).toHaveLength(1);
    expect(request.mock.calls.some(c => c[0].includes("simulated-trades"))).toBe(false);
    expect(wrapper.emitted("refresh")).toHaveLength(1);
    expect(wrapper.text()).toContain("仓位与买入权限未改变");
  });
  it("does not require a cost form for market-value policy", async () => {
    const wrapper = mount(P3CapitalOpening, {props: {...props(vi.fn(async () => JSON.parse(JSON.stringify(bookView())))), costRequired: false}});
    await flushPromises();
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.text()).toContain("不需要开仓成本");
  });
  it("discards a book response from a replaced plan context", async () => {
    let resolveFirst: (value: unknown) => void = () => undefined;
    const request = vi.fn().mockImplementationOnce(() => new Promise(resolve => {resolveFirst = resolve;}))
      .mockResolvedValue({...bookView(), inventoryLots: [], retainedBasisFen: 0});
    const wrapper = mount(P3CapitalOpening, {props: props(request)});
    await wrapper.setProps({planVersionId: "version-b"}); await flushPromises();
    resolveFirst(bookView()); await flushPromises();
    expect(wrapper.find('input[type="number"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("明确初始化为空仓");
  });
});
