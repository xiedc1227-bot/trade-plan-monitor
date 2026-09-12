import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ManualEventRiskView } from "../../src/api/generated";
import type { ManualEventRiskApi } from "../../src/api/manualEventRisk";
import ManualEventRiskPanel from "../../src/components/symbol/ManualEventRiskPanel.vue";

const symbol = "003043.SZ";
const unknown: ManualEventRiskView = Object.freeze({
  confirmedAt: null,
  expiresOn: null,
  planVersionId: "4c623c8c-ca26-4cd8-8cb2-08cd5e61be93",
  reason: "MISSING_CONFIRMATION",
  revision: 0,
  status: "UNKNOWN",
  symbol,
});

function installDialogPolyfill(): void {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
}

beforeEach(() => {
  installDialogPolyfill();
});
enableAutoUnmount(afterEach);

describe("ManualEventRiskPanel", () => {
  it("shows the unknown blocker and submits an explicit, dated risk confirmation", async () => {
    const confirmed: ManualEventRiskView = Object.freeze({
      ...unknown,
      confirmedAt: "2026-09-12T10:05:00+08:00",
      expiresOn: "2026-09-12",
      reason: null,
      revision: 1,
      status: "RISK_PRESENT",
    });
    const api: ManualEventRiskApi = {
      confirm: vi.fn(async () => confirmed),
      get: vi.fn(async () => unknown),
    };
    const wrapper = mount(ManualEventRiskPanel, {
      props: {
        api,
        createIdempotencyKey: () => "manual-risk-ui-1",
        symbol,
      },
    });

    await flushPromises();
    expect(wrapper.text()).toContain("尚未确认");
    expect(wrapper.text()).toContain("缺少人工事件风险确认");

    await wrapper.get("select[name='manualRiskStatus']").setValue("RISK_PRESENT");
    await wrapper.get("input[name='manualRiskExpiresOn']").setValue("2026-09-12");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get("[data-testid='manual-risk-confirmation']").attributes("open")).toBeDefined();
    await wrapper.get("[data-testid='confirm-manual-risk']").trigger("click");
    await flushPromises();

    expect(api.confirm).toHaveBeenCalledWith(
      {
        expectedRevision: 0,
        expiresOn: "2026-09-12",
        status: "RISK_PRESENT",
        symbol,
      },
      "manual-risk-ui-1",
    );
    expect(wrapper.text()).toContain("已确认存在事件风险");
    expect(wrapper.text()).toContain("2026-09-12");
  });
});
