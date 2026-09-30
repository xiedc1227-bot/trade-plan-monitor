import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { apiFetchKey } from "../../src/api/context";
import PlanInventoryPanel from "../../src/components/plans/PlanInventoryPanel.vue";
import { createMonitorProtocol } from "../../src/runtime-status/protocol";
import { isRuntimeHealth } from "../../src/runtime-status/validators";

describe("deep command component protocol injection", () => {
  it("uses the real inventory adapter and sends zero POSTs against an old health server", async () => {
    const requests: Request[] = [];
    const rawFetch: typeof fetch = vi.fn(async (input, init) => {
      const request = new Request(input, init); requests.push(request);
      return new Response(JSON.stringify(new URL(request.url).pathname === "/api/v1/health" ? { status: "RUNNING" } : {
        asOfTradeDate: "2026-09-14", confirmationId: null, confirmedAt: null, cutoff: "2026-09-14T10:10:15.000000+08:00",
        includedLotIds: [], inventoryRevision: 0, missingReasons: ["POSITION_UNKNOWN"], openingBalances: [],
        sellableQuantity: null, status: "UNKNOWN", symbol: "003043.SZ", totalQuantity: null,
      }));
    });
    const protocol = createMonitorProtocol({ origin: "http://127.0.0.1:32109", fetchImplementation: rawFetch, validateHealth: isRuntimeHealth });
    const wrapper = mount(PlanInventoryPanel, { props: { symbol: "003043.SZ" }, global: { provide: { [apiFetchKey as symbol]: protocol.fetch } } });
    await wrapper.get('input[type="date"]').setValue("2026-09-14"); await flushPromises();
    const form = wrapper.get("form");
    await form.findAll("input")[0]!.setValue("100");
    await form.findAll("input")[1]!.setValue("100");
    await form.get('input[type="checkbox"]').setValue(true);
    await form.trigger("submit"); await flushPromises();
    expect(requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)).toEqual(["GET /api/v1/position-inventory", "GET /api/v1/health"]);
    expect(protocol.state).toBe("RELOAD_REQUIRED");
    wrapper.unmount();
  });
});
