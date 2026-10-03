import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PlanDraftingView from "../../src/views/PlanDraftingView.vue";

describe("canonical plan route composition", () => {
  it("wires a version link into the sole plan workspace", () => {
    const wrapper = mount(PlanDraftingView, { props: { planVersionId: "saved-version" },
      global: { stubs: { PlanWorkbench: { props: ["planVersionId"], template: '<p>{{ planVersionId }}</p>' } } } });
    expect(wrapper.text()).toBe("saved-version");
    expect(wrapper.findComponent({ name: "PlanCreationSwitcher" }).exists()).toBe(false);
  });
});
