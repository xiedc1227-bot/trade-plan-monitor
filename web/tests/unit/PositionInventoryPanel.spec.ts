import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { PositionInventoryApi } from "../../src/api/positions";
import PositionInventoryPanel from "../../src/components/symbol/PositionInventoryPanel.vue";

const symbol = "003043.SZ";
const asOfTradeDate = "2026-08-24";
const openingBalanceId = "00000000-0000-4000-8000-000000000014";

describe("PositionInventoryPanel", () => {
  it("requires an explicit complete board-lot registration before writing independent inventory", async () => {
    const api = inventoryApi({
      asOfTradeDate,
      confirmationId: null,
      confirmedAt: null,
      cutoff: "2026-08-24T10:05:05.000000+08:00",
      includedLotIds: [],
      inventoryRevision: 0,
      missingReasons: ["POSITION_UNKNOWN"],
      openingBalances: [],
      sellableQuantity: null,
      status: "UNKNOWN",
      symbol,
      totalQuantity: null,
    });
    const wrapper = mount(PositionInventoryPanel, { props: { api, asOfTradeDate, symbol } });
    await flushPromises();

    const forms = wrapper.findAll("form");
    await forms[0]?.findAll("input")[0]?.setValue("200");
    await forms[0]?.findAll("input")[1]?.setValue("100");
    expect(forms[0]?.get("button").attributes("disabled")).toBeDefined();
    await forms[0]?.find('input[type="checkbox"]').setValue(true);
    expect(forms[0]?.get("button").attributes("disabled")).toBeUndefined();
    await forms[0]?.trigger("submit");
    await flushPromises();

    expect(api.confirmInventory).toHaveBeenCalledWith(expect.objectContaining({
      asOfTradeDate,
      completeRegistration: true,
      expectedRevision: 0,
      sellableQuantity: 100,
      symbol,
      totalQuantity: 200,
    }), expect.stringContaining("inventory-confirm-003043.SZ-0"));
  });

  it("records an actual opening-balance closure and refreshes inventory without using an alert", async () => {
    const known = {
      asOfTradeDate,
      confirmationId: "00000000-0000-4000-8000-000000000013",
      confirmedAt: "2026-08-24T10:05:05.000000+08:00",
      cutoff: "2026-08-24T10:05:05.000000+08:00",
      includedLotIds: [],
      inventoryRevision: 2,
      missingReasons: [],
      openingBalances: [{
        openingBalanceId,
        originalQuantity: 200,
        remainingQuantity: 200,
        revision: 0,
        sellableFrom: asOfTradeDate,
        symbol,
      }],
      sellableQuantity: 200,
      status: "KNOWN" as const,
      symbol,
      totalQuantity: 200,
    };
    const api = inventoryApi(known);
    const wrapper = mount(PositionInventoryPanel, { props: { api, asOfTradeDate, symbol } });
    await flushPromises();

    const forms = wrapper.findAll("form");
    await forms[1]?.find('input[inputmode="numeric"]').setValue("100");
    expect(forms[1]?.get("button").attributes("disabled")).toBeUndefined();
    await forms[1]?.trigger("submit");
    await flushPromises();

    expect(api.closeInventory).toHaveBeenCalledWith(expect.objectContaining({
      expectedRevision: 0,
      quantity: 100,
      sourceId: openingBalanceId,
      sourceType: "OPENING_BALANCE",
      tradeDate: asOfTradeDate,
    }), expect.stringContaining(`inventory-close-${openingBalanceId}-0-100`));
    expect(api.getInventory).toHaveBeenCalledTimes(2);
  });
});

function inventoryApi(inventory: Awaited<ReturnType<PositionInventoryApi["getInventory"]>>) {
  return {
    closeInventory: vi.fn().mockResolvedValue({
      afterRemainingQuantity: 100,
      appliedQuantity: 100,
      beforeRemainingQuantity: 200,
      revision: 1,
      sourceId: openingBalanceId,
      sourceType: "OPENING_BALANCE",
      symbol,
      tradeDate: asOfTradeDate,
    }),
    confirmInventory: vi.fn().mockResolvedValue({ ...inventory, inventoryRevision: inventory.inventoryRevision + 1, status: "KNOWN" }),
    getInventory: vi.fn().mockResolvedValue(inventory),
  } satisfies PositionInventoryApi;
}
