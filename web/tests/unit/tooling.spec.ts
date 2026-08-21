import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { describe, expect, it } from "vitest";

import { createMonitorApp } from "../../src/main";

const ToolingProbe = defineComponent({
  name: "ToolingProbe",
  setup() {
    return () => h("p", { "data-testid": "tooling-probe" }, "Vue toolchain ready");
  },
});

describe("frontend toolchain", () => {
  it("loads Vue components through Vue Test Utils", () => {
    const wrapper = mount(ToolingProbe);

    expect(wrapper.get('[data-testid="tooling-probe"]').text()).toBe("Vue toolchain ready");
  });

  it("creates an unmounted application from a typed root component", () => {
    const app = createMonitorApp(ToolingProbe);
    const host = document.createElement("div");

    expect(app.version).toMatch(/^3\./);

    app.mount(host);
    expect(host.querySelector('[data-testid="tooling-probe"]')?.textContent).toBe(
      "Vue toolchain ready",
    );
    app.unmount();
  });
});
