import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import WorkbenchReplayContextForm from "../../src/components/backtests/WorkbenchReplayContextForm.vue";

describe("workbench historical context", () => {
  it("keeps unknown inventory unknown and confirms no rule changes", async () => {
    const wrapper = mount(WorkbenchReplayContextForm, { props: { disabled: false } });
    await wrapper.get("#research-effective-date").setValue("2026-08-20");
    await wrapper.get("#research-cutoff").setValue("2026-08-20T09:00");
    await wrapper.get("#research-snapshot").setValue("2026-08-20T09:00");
    await wrapper.get("#research-evidence").setValue("已核对历史研究起点，原文未提供库存。");
    await wrapper.get("#research-confirmed").setValue(true);
    await wrapper.get("form").trigger("submit");
    const value = wrapper.emitted("confirm")?.[0]?.[0] as {
      initialAccount: { inventory_known: boolean; lots: unknown[]; cash: { kind: string } };
      availableAt: null;
    };
    expect(value.initialAccount.inventory_known).toBe(false);
    expect(value.initialAccount.lots).toEqual([]);
    expect(value.initialAccount.cash.kind).toBe("POSITION_LIMIT_ONLY");
    expect(value.availableAt).toBeNull();
    expect(wrapper.find("textarea[aria-label='研究输入 JSON']").exists()).toBe(false);
  });

  it("requires explicit confirmation before creating a research snapshot", async () => {
    const wrapper = mount(WorkbenchReplayContextForm, { props: { disabled: false } });
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("confirm")).toBeUndefined();
    expect(wrapper.get("[role='alert']").text()).toBeTruthy();
  });

  it("rejects future context locally before emitting a network intent", async () => {
    const wrapper = mount(WorkbenchReplayContextForm, { props: { disabled: false } });
    await wrapper.get("#research-effective-date").setValue("2026-08-20");
    await wrapper.get("#research-cutoff").setValue("2026-08-20T10:00");
    await wrapper.get("#research-snapshot").setValue("2026-08-20T09:00");
    await wrapper.get("#research-evidence").setValue("明确的历史研究假设。");
    await wrapper.get("#research-confirmed").setValue(true);
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("confirm")).toBeUndefined();
    expect(wrapper.get("[role='alert']").text()).toContain("信息截止时间");
  });
});
