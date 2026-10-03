import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { routes } from "../../src/router";
import SymbolView from "../../src/runtime-status/SymbolView.vue";
import { runtimeContextKey } from "../../src/runtime-status/context";
import PlanFieldEditor from "../../src/components/plans/PlanFieldEditor.vue";

describe("one plan workspace", () => {
  it("edits persistent validity explicitly and labels dated source compatibility", async () => {
    const schema = { anyOf: [
      { title: "PlanActiveValidity", type: "object", properties: { mode: { const: "PLAN_ACTIVE" } } },
      { title: "DailyValidity", type: "object", properties: { mode: { const: "DATE_RANGE" },
        start_date: { type: "string", format: "date" }, end_date: { type: "string", format: "date" } } },
      { type: "null" },
    ] };
    const wrapper = mount(PlanFieldEditor, { props: { schema, definitions: {}, path: "validity",
      modelValue: { mode: "PLAN_ACTIVE" } } });
    expect(wrapper.text()).toContain("持续有效直到人工停用或审核启用新版本替换");
    expect(wrapper.text()).toContain("保留原文或历史日期限制");
    expect(wrapper.find('input[type="date"]').exists()).toBe(false);
    await wrapper.find("select").setValue("1");
    expect(wrapper.emitted("update:modelValue")?.[0]).toEqual([
      { mode: "DATE_RANGE", start_date: null, end_date: null },
    ]);
    expect(wrapper.props("modelValue")).toEqual({ mode: "PLAN_ACTIVE" });
  });
  it("has only the canonical plan creation and version routes", () => {
    expect(routes.filter(route => route.path.includes("plans")).map(route => route.path))
      .toEqual(["/plans", "/plans/:id"]);
  });
  it("does not expose real fills or recurring event-risk inputs in the normal symbol page", () => {
    const wrapper = mount(SymbolView, { props: { symbol: "601021.SH" }, global: { provide: {
      [runtimeContextKey as symbol]: {
        api: { getSymbol: vi.fn(() => new Promise(() => {})) },
        store: { observedAt: null, snapshot: null },
      },
    } } });
    expect(wrapper.findComponent({ name: "PositionLots" }).exists()).toBe(false);
    expect(wrapper.findComponent({ name: "PositionInventoryPanel" }).exists()).toBe(false);
    expect(wrapper.findComponent({ name: "ManualEventRiskPanel" }).exists()).toBe(false);
  });
});
