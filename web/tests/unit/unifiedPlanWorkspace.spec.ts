import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { routes } from "../../src/router";
import SymbolView from "../../src/runtime-status/SymbolView.vue";
import { runtimeContextKey } from "../../src/runtime-status/context";

describe("one plan workspace", () => {
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
