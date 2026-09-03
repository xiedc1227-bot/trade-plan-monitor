import { isShallow, nextTick, shallowRef } from "vue";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PositionLotPage,
  PositionPrefillView,
  SymbolDetailResponse,
  components,
} from "../../src/api/generated";
import PositionLots from "../../src/components/symbol/PositionLots.vue";
import type { PositionOperations } from "../../src/composables/usePositions";
import { usePositions } from "../../src/composables/usePositions";
import SymbolDetailView from "../../src/views/SymbolDetailView.vue";

type PositionLot =
  components["schemas"]["trade_plan_monitor__web__routers__positions__PositionLotView"];

const symbol = "003043.SZ";
const asOfTradeDate = "2026-08-24";
const alertId = "00000000-0000-4000-8000-000000000021";

const coreLot: PositionLot = Object.freeze({
  acquiredTradeDate: "2026-08-21",
  bucket: "CORE",
  closedAt: null,
  costFen: 6_400,
  lotId: "00000000-0000-4000-8000-000000000011",
  quantity: 200,
  relatedAlertId: null,
  remainingQuantity: 100,
  revision: 1,
  sellableQuantity: 100,
  symbol,
});

const tacticalLot: PositionLot = Object.freeze({
  acquiredTradeDate: asOfTradeDate,
  bucket: "TACTICAL",
  closedAt: null,
  costFen: 6_500,
  lotId: "00000000-0000-4000-8000-000000000012",
  quantity: 100,
  relatedAlertId: alertId,
  remainingQuantity: 100,
  revision: 0,
  sellableQuantity: 0,
  symbol,
});

const page = Object.freeze({
  asOfTradeDate,
  items: Object.freeze([coreLot, tacticalLot]),
  limit: 20,
  offset: 0,
  symbol,
  total: 2,
}) as unknown as PositionLotPage;

const refreshedPage = Object.freeze({
  ...page,
  items: Object.freeze([
    Object.freeze({
      ...coreLot,
      closedAt: "2026-08-24T10:30:00+08:00",
      remainingQuantity: 0,
      revision: 2,
      sellableQuantity: 0,
    }),
    tacticalLot,
  ]),
}) as unknown as PositionLotPage;

const buyPrefill: PositionPrefillView = Object.freeze({
  action: "BUY",
  bucket: "TACTICAL",
  quantity: 100,
  relatedAlertId: alertId,
  symbol,
  targetLotId: null,
});

const closePrefill: PositionPrefillView = Object.freeze({
  action: "CLOSE",
  bucket: "CORE",
  quantity: 100,
  relatedAlertId: alertId,
  symbol,
  targetLotId: coreLot.lotId,
});

function positionOperations(overrides: Partial<PositionOperations> = {}): PositionOperations {
  let createdLot: PositionLot | null = null;
  const defaults: PositionOperations = {
    closePosition: vi.fn(async () => ({
      afterRemainingQuantity: 0,
      appliedQuantity: 100,
      beforeRemainingQuantity: 100,
      lot: refreshedPage.items?.[0] as PositionLot,
      tradeDate: asOfTradeDate,
    })),
    createPosition: vi.fn(async (request) => {
      createdLot = Object.freeze({
        acquiredTradeDate: request.command.acquiredTradeDate,
        bucket: request.command.bucket,
        closedAt: null,
        costFen: request.command.costFen,
        lotId: "00000000-0000-4000-8000-000000000013",
        quantity: request.command.quantity,
        relatedAlertId: request.command.relatedAlertId,
        remainingQuantity: request.command.quantity,
        revision: 0,
        sellableQuantity: 0,
        symbol: request.command.symbol,
      });
      return createdLot;
    }),
    listPositions: vi.fn(async () =>
      createdLot === null
        ? refreshedPage
        : ({
            ...page,
            items: [...(page.items ?? []), createdLot],
            total: page.total + 1,
          } satisfies PositionLotPage),
    ),
  };
  return {
    ...defaults,
    ...overrides,
  };
}

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

describe("usePositions", () => {
  it("accepts reactive inputs, submits an explicit creation, then refreshes authoritative lots", async () => {
    const pageSource = shallowRef<PositionLotPage | null>(page);
    const operations = positionOperations();
    const positions = usePositions({
      asOfTradeDate,
      createIdempotencyKey: () => "position-create-test",
      initialPage: pageSource,
      operations,
      prefill: null,
      summaryLots: [],
      symbol: () => symbol,
    });

    expect(isShallow(positions.page)).toBe(true);
    expect(Object.isFrozen(positions.page.value?.items)).toBe(true);
    const succeeded = await positions.recordPosition({
      acquiredTradeDate: "2026-08-24",
      bucket: "CORE",
      costFen: 6_600,
      quantity: 100,
      relatedAlertId: null,
    });

    expect(succeeded).toBe(true);
    expect(operations.createPosition).toHaveBeenCalledWith({
      command: {
        acquiredTradeDate: "2026-08-24",
        bucket: "CORE",
        costFen: 6_600,
        expectedRevision: 0,
        quantity: 100,
        relatedAlertId: null,
        symbol,
      },
      idempotencyKey: "position-create-test",
    });
    expect(operations.listPositions).toHaveBeenCalledWith({
      asOfTradeDate,
      limit: 100,
      offset: 0,
      symbol,
    });
    expect(positions.page.value?.total).toBe(3);
    expect(positions.page.value?.items).toContainEqual(
      expect.objectContaining({
        lotId: "00000000-0000-4000-8000-000000000013",
        revision: 0,
      }),
    );

    expect(
      positions.validateCreation({
        acquiredTradeDate: asOfTradeDate,
        bucket: "CORE",
        costFen: 6_600,
        quantity: 100,
        relatedAlertId: null,
      }),
    ).toEqual([]);
  });

  it("refreshes on a 409 without leaking the rejected error", async () => {
    const operations = positionOperations({
      closePosition: vi.fn(async () => {
        throw Object.assign(new Error("storage revision secret"), { status: 409 });
      }),
    });
    const positions = usePositions({
      asOfTradeDate,
      createIdempotencyKey: () => "position-close-test",
      initialPage: page,
      operations,
      prefill: null,
      summaryLots: [],
      symbol,
    });

    const succeeded = await positions.reducePosition({
      expectedRevision: coreLot.revision,
      lotId: coreLot.lotId,
      quantity: 100,
    });

    expect(succeeded).toBe(false);
    expect(operations.closePosition).toHaveBeenCalledWith({
      command: {
        expectedRevision: coreLot.revision,
        lotId: coreLot.lotId,
        quantity: 100,
        tradeDate: asOfTradeDate,
      },
      idempotencyKey: "position-close-test",
    });
    expect(operations.listPositions).toHaveBeenCalledTimes(1);
    expect(positions.page.value).toEqual(refreshedPage);
    expect(positions.error.value).toBe(
      "后端拒绝了持仓操作，请核对最新批次和计划规则后重试",
    );
    expect(positions.error.value).not.toContain("secret");
  });

  it("fails closed when the authoritative refresh identity drifts", async () => {
    const operations = positionOperations({
      listPositions: vi.fn(async () => ({
        ...refreshedPage,
        symbol: "600000.SH",
      })),
    });
    const positions = usePositions({
      asOfTradeDate,
      initialPage: page,
      operations,
      prefill: null,
      summaryLots: [],
      symbol,
    });

    const succeeded = await positions.recordPosition({
      acquiredTradeDate: asOfTradeDate,
      bucket: "CORE",
      costFen: 6_600,
      quantity: 100,
      relatedAlertId: null,
    });

    expect(succeeded).toBe(false);
    expect(positions.page.value).toBeNull();
    expect(positions.error.value).toBe(
      "持仓操作可能已成功，但响应身份不一致，请重新加载核对",
    );
  });

  it("does not refresh a different symbol after an in-flight mutation completes", async () => {
    const symbolSource = shallowRef(symbol);
    let resolveCreation: ((lot: PositionLot) => void) | undefined;
    const operations = positionOperations({
      createPosition: vi.fn(
        async () =>
          await new Promise<PositionLot>((resolve) => {
            resolveCreation = resolve;
          }),
      ),
    });
    const positions = usePositions({
      asOfTradeDate,
      initialPage: page,
      operations,
      prefill: null,
      summaryLots: [],
      symbol: symbolSource,
    });

    const pending = positions.recordPosition({
      acquiredTradeDate: asOfTradeDate,
      bucket: "CORE",
      costFen: 6_600,
      quantity: 100,
      relatedAlertId: null,
    });
    symbolSource.value = "600000.SH";
    await nextTick();
    resolveCreation?.(coreLot);

    expect(await pending).toBe(false);
    expect(operations.listPositions).not.toHaveBeenCalled();
    expect(positions.error.value).toContain("页面已切换");
  });

  it("uses a fixed safe message when a post-mutation refresh fails", async () => {
    const operations = positionOperations({
      listPositions: vi.fn(async () => {
        throw new Error("database address secret");
      }),
    });
    const positions = usePositions({
      asOfTradeDate,
      initialPage: page,
      operations,
      prefill: null,
      summaryLots: [],
      symbol,
    });

    expect(
      await positions.recordPosition({
        acquiredTradeDate: asOfTradeDate,
        bucket: "CORE",
        costFen: 6_600,
        quantity: 100,
        relatedAlertId: null,
      }),
    ).toBe(false);
    expect(positions.error.value).toBe(
      "持仓操作可能已成功，但刷新失败，请重新加载核对",
    );
    expect(positions.error.value).not.toContain("secret");
  });

  it("reuses the same idempotency key when an identical mutation outcome is unknown", async () => {
    const createdLot: PositionLot = {
      ...tacticalLot,
      bucket: "CORE",
      costFen: 6_600,
      lotId: "00000000-0000-4000-8000-000000000014",
      relatedAlertId: null,
    };
    const createPosition = vi
      .fn()
      .mockRejectedValueOnce(new Error("connection ended after commit"))
      .mockResolvedValueOnce(createdLot);
    const listPositions = vi.fn(async () => ({
      ...page,
      items: [...(page.items ?? []), createdLot],
      total: page.total + 1,
    }));
    const createIdempotencyKey = vi
      .fn()
      .mockReturnValueOnce("position-unknown-1")
      .mockReturnValueOnce("position-unknown-2");
    const positions = usePositions({
      asOfTradeDate,
      createIdempotencyKey,
      initialPage: page,
      operations: positionOperations({ createPosition, listPositions }),
      prefill: null,
      summaryLots: [],
      symbol,
    });
    const draft = {
      acquiredTradeDate: asOfTradeDate,
      bucket: "CORE" as const,
      costFen: 6_600,
      quantity: 100,
      relatedAlertId: null,
    };

    expect(await positions.recordPosition(draft)).toBe(false);
    expect(await positions.recordPosition(draft)).toBe(true);
    expect(createIdempotencyKey).toHaveBeenCalledTimes(1);
    expect(createPosition.mock.calls.map(([request]) => request.idempotencyKey)).toEqual([
      "position-unknown-1",
      "position-unknown-1",
    ]);
  });

  it("rejects a creation receipt that does not match the submitted command", async () => {
    const operations = positionOperations({
      createPosition: vi.fn(async () => ({
        ...coreLot,
        lotId: "00000000-0000-4000-8000-000000000099",
        quantity: 100,
        remainingQuantity: 100,
        symbol: "600000.SH",
      })),
    });
    const positions = usePositions({
      asOfTradeDate,
      initialPage: page,
      operations,
      prefill: null,
      summaryLots: [],
      symbol,
    });

    expect(
      await positions.recordPosition({
        acquiredTradeDate: asOfTradeDate,
        bucket: "CORE",
        costFen: 6_600,
        quantity: 100,
        relatedAlertId: null,
      }),
    ).toBe(false);
    expect(positions.error.value).toBe(
      "建仓操作可能已成功，但回执不一致，请重新加载核对",
    );
  });

  it("rejects a closure receipt with the wrong quantity or revision transition", async () => {
    const operations = positionOperations({
      closePosition: vi.fn(async () => ({
        afterRemainingQuantity: 50,
        appliedQuantity: 50,
        beforeRemainingQuantity: 100,
        lot: { ...coreLot, remainingQuantity: 50, revision: coreLot.revision },
        tradeDate: asOfTradeDate,
      })),
    });
    const positions = usePositions({
      asOfTradeDate,
      initialPage: page,
      operations,
      prefill: null,
      summaryLots: [],
      symbol,
    });

    expect(
      await positions.reducePosition({
        expectedRevision: coreLot.revision,
        lotId: coreLot.lotId,
        quantity: 100,
      }),
    ).toBe(false);
    expect(positions.error.value).toBe(
      "减仓操作可能已成功，但回执不一致，请重新加载核对",
    );
  });

  it("accepts the backend revision increment for a multi-board-lot reduction", async () => {
    const largeLot: PositionLot = {
      ...coreLot,
      quantity: 400,
      remainingQuantity: 300,
      sellableQuantity: 300,
    };
    const closedLot: PositionLot = {
      ...largeLot,
      remainingQuantity: 100,
      revision: largeLot.revision + 2,
      sellableQuantity: 100,
    };
    const resultPage: PositionLotPage = {
      ...page,
      items: [closedLot, tacticalLot],
    };
    const operations = positionOperations({
      closePosition: vi.fn(async () => ({
        afterRemainingQuantity: 100,
        appliedQuantity: 200,
        beforeRemainingQuantity: 300,
        lot: closedLot,
        tradeDate: asOfTradeDate,
      })),
      listPositions: vi.fn(async () => resultPage),
    });
    const positions = usePositions({
      asOfTradeDate,
      initialPage: { ...page, items: [largeLot, tacticalLot] },
      operations,
      prefill: null,
      summaryLots: [],
      symbol,
    });

    expect(
      await positions.reducePosition({
        expectedRevision: largeLot.revision,
        lotId: largeLot.lotId,
        quantity: 200,
      }),
    ).toBe(true);
    expect(positions.page.value?.items?.[0]?.revision).toBe(3);
  });

  it("ignores an older refresh response that completes after a newer one", async () => {
    let resolveFirst: ((value: PositionLotPage) => void) | undefined;
    let resolveSecond: ((value: PositionLotPage) => void) | undefined;
    const listPositions = vi
      .fn()
      .mockImplementationOnce(
        async () =>
          await new Promise<PositionLotPage>((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockImplementationOnce(
        async () =>
          await new Promise<PositionLotPage>((resolve) => {
            resolveSecond = resolve;
          }),
      );
    const positions = usePositions({
      asOfTradeDate,
      initialPage: page,
      operations: positionOperations({ listPositions }),
      prefill: null,
      summaryLots: [],
      symbol,
    });

    const first = positions.refresh();
    const second = positions.refresh();
    resolveSecond?.(refreshedPage);
    expect(await second).toBe(true);
    resolveFirst?.(page);
    expect(await first).toBe(false);
    expect(positions.page.value).toEqual(refreshedPage);
  });

  it("never calculates a maximum from an incomplete position page", () => {
    const incompletePage: PositionLotPage = { ...page, total: page.total + 1 };
    const positions = usePositions({
      asOfTradeDate,
      initialPage: incompletePage,
      operations: positionOperations(),
      prefill: null,
      summaryLots: [],
      symbol,
    });

    expect(
      positions.validateCreation({
        acquiredTradeDate: asOfTradeDate,
        bucket: "CORE",
        costFen: 6_600,
        quantity: 100,
        relatedAlertId: null,
      }),
    ).toEqual([]);
  });

  it("submits reduction policy conflicts to the backend authority", async () => {
    const operations = positionOperations({
      closePosition: vi.fn(async () => {
        throw Object.assign(new Error("backend policy detail"), { status: 409 });
      }),
    });
    const positions = usePositions({
      asOfTradeDate,
      initialPage: page,
      operations,
      prefill: null,
      summaryLots: [],
      symbol,
    });
    const draft = {
      expectedRevision: tacticalLot.revision,
      lotId: tacticalLot.lotId,
      quantity: 200,
    };

    expect(positions.validateReduction(draft)).toEqual([]);
    expect(await positions.reducePosition(draft)).toBe(false);
    expect(operations.closePosition).toHaveBeenCalledTimes(1);
    expect(positions.error.value).toBe(
      "后端拒绝了持仓操作，请核对最新批次和计划规则后重试",
    );
    expect(positions.error.value).not.toContain("backend policy detail");
  });

  it("keeps the stronger error and clears stale lots when a 409 refresh fails", async () => {
    const operations = positionOperations({
      closePosition: vi.fn(async () => {
        throw Object.assign(new Error("revision secret"), { status: 409 });
      }),
      listPositions: vi.fn(async () => {
        throw new Error("refresh secret");
      }),
    });
    const positions = usePositions({
      asOfTradeDate,
      initialPage: page,
      operations,
      prefill: null,
      summaryLots: [],
      symbol,
    });

    expect(
      await positions.reducePosition({
        expectedRevision: coreLot.revision,
        lotId: coreLot.lotId,
        quantity: 100,
      }),
    ).toBe(false);
    expect(positions.page.value).toBeNull();
    expect(positions.error.value).toBe(
      "持仓冲突后未能刷新权威批次，请重新加载后核对",
    );
    expect(positions.error.value).not.toContain("secret");
  });
});

describe("PositionLots", () => {
  it("renders backend T+1 facts while leaving position policy to the backend", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: null,
        summaryLots: [],
        symbol,
      },
    });

    expect(wrapper.text()).toContain("底仓");
    expect(wrapper.text()).toContain("机动仓");
    expect(wrapper.text()).toContain("T+1 / 当前日期不可卖");
    expect(wrapper.get(`[data-testid="reduce-${tacticalLot.lotId}"]`).attributes()).not.toHaveProperty(
      "disabled",
    );

    await wrapper.get('input[name="createQuantity"]').setValue("50");
    await wrapper.get('[data-testid="position-create-form"]').trigger("submit");
    expect(wrapper.get('[data-testid="create-errors"]').text()).toContain("100 股整手");
    expect(operations.createPosition).not.toHaveBeenCalled();

    await wrapper.get('input[name="createQuantity"]').setValue("100");
    await wrapper.get('input[name="createCostFen"]').setValue("6600");
    await wrapper.get('[data-testid="position-create-form"]').trigger("submit");
    expect(wrapper.get('[data-testid="position-confirmation"]').attributes()).toHaveProperty(
      "open",
    );
    expect(wrapper.text()).not.toContain("计划上限");
    expect(operations.createPosition).not.toHaveBeenCalled();
  });

  it("applies an alert prefill without submitting or treating acknowledgement as a fill", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: buyPrefill,
        summaryLots: [],
        symbol,
      },
    });
    await nextTick();

    expect((wrapper.get('select[name="createBucket"]').element as HTMLSelectElement).value).toBe(
      "TACTICAL",
    );
    expect((wrapper.get('input[name="createQuantity"]').element as HTMLInputElement).value).toBe(
      "100",
    );
    expect(wrapper.text()).toContain("提醒仅预填表单，仍需明确确认");
    expect(wrapper.text()).toContain("确认提醒不等于成交");
    expect(operations.createPosition).not.toHaveBeenCalled();
    expect(operations.closePosition).not.toHaveBeenCalled();

    await wrapper.get('input[name="createCostFen"]').setValue("6600");
    await wrapper.get('input[name="createAcquiredTradeDate"]').setValue(asOfTradeDate);
    await wrapper.get('[data-testid="position-create-form"]').trigger("submit");
    expect(wrapper.get('[data-testid="position-confirmation"]').attributes()).toHaveProperty(
      "open",
    );
    expect(operations.createPosition).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="confirm-position"]').trigger("click");
    await flushPromises();
    expect(operations.createPosition).toHaveBeenCalledTimes(1);
    expect(operations.listPositions).toHaveBeenCalledTimes(1);
  });

  it("requires a separate reduction review and submits a revision-bound command", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: null,
        summaryLots: [],
        symbol,
      },
    });

    await wrapper.get(`[data-testid="reduce-${coreLot.lotId}"]`).trigger("click");
    await wrapper.get('input[name="reductionQuantity"]').setValue("100");
    await wrapper.get('[data-testid="position-reduction-form"]').trigger("submit");
    expect(wrapper.get('[data-testid="position-confirmation"]').text()).toContain("减仓 100 股");
    expect(operations.closePosition).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="confirm-position"]').trigger("click");
    await flushPromises();
    expect(operations.closePosition).toHaveBeenCalledWith(
      expect.objectContaining({
        command: {
          expectedRevision: coreLot.revision,
          lotId: coreLot.lotId,
          quantity: 100,
          tradeDate: asOfTradeDate,
        },
      }),
    );
    expect(operations.listPositions).toHaveBeenCalledTimes(1);
  });

  it("prefills a CLOSE reminder without reducing until a separate confirmation", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: closePrefill,
        summaryLots: [],
        symbol,
      },
    });
    await nextTick();

    expect(wrapper.find('[data-testid="position-reduction-form"]').exists()).toBe(true);
    expect((wrapper.get('input[name="reductionQuantity"]').element as HTMLInputElement).value).toBe(
      "100",
    );
    expect(operations.closePosition).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="position-reduction-form"]').trigger("submit");
    expect(operations.closePosition).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="confirm-position"]').trigger("click");
    await flushPromises();
    expect(operations.closePosition).toHaveBeenCalledTimes(1);
  });

  it("prevents duplicate confirmation while a position command is in flight", async () => {
    let resolveCreation: ((lot: PositionLot) => void) | undefined;
    const operations = positionOperations({
      createPosition: vi.fn(
        async () =>
          await new Promise<PositionLot>((resolve) => {
            resolveCreation = resolve;
          }),
      ),
    });
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: null,
        summaryLots: [],
        symbol,
      },
    });
    await wrapper.get('input[name="createCostFen"]').setValue("6600");
    await wrapper.get('input[name="createAcquiredTradeDate"]').setValue(asOfTradeDate);
    await wrapper.get('[data-testid="position-create-form"]').trigger("submit");

    const confirm = wrapper.get('[data-testid="confirm-position"]');
    void confirm.trigger("click");
    await confirm.trigger("click");
    expect(operations.createPosition).toHaveBeenCalledTimes(1);
    resolveCreation?.(coreLot);
    await flushPromises();
    expect(operations.listPositions).toHaveBeenCalledTimes(1);
  });

  it("cancels stale confirmation state when the symbol changes", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: buyPrefill,
        summaryLots: [],
        symbol,
      },
    });
    await wrapper.get('input[name="createCostFen"]').setValue("6600");
    await wrapper.get('[data-testid="position-create-form"]').trigger("submit");
    expect(wrapper.get('[data-testid="position-confirmation"]').attributes()).toHaveProperty(
      "open",
    );

    await wrapper.setProps({ symbol: "600000.SH" });
    expect(wrapper.get('[data-testid="position-confirmation"]').attributes()).not.toHaveProperty(
      "open",
    );
    expect((wrapper.get('select[name="createBucket"]').element as HTMLSelectElement).value).toBe(
      "CORE",
    );
    expect(operations.createPosition).not.toHaveBeenCalled();
  });

  it("clears stale BUY provenance when its prefill is removed", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: buyPrefill,
        summaryLots: [],
        symbol,
      },
    });
    await wrapper.setProps({ prefill: null });
    await wrapper.get('input[name="createCostFen"]').setValue("6600");
    await wrapper.get('[data-testid="position-create-form"]').trigger("submit");
    await wrapper.get('[data-testid="confirm-position"]').trigger("click");
    await flushPromises();

    expect(operations.createPosition).toHaveBeenCalledWith(
      expect.objectContaining({
        command: expect.objectContaining({ relatedAlertId: null }),
      }),
    );
    expect(wrapper.text()).not.toContain("提醒仅预填表单");
  });

  it("invalidates an open confirmation when its alert prefill is withdrawn", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: buyPrefill,
        summaryLots: [],
        symbol,
      },
    });
    await wrapper.get('input[name="createCostFen"]').setValue("6600");
    await wrapper.get('[data-testid="position-create-form"]').trigger("submit");
    expect(wrapper.get('[data-testid="position-confirmation"]').attributes()).toHaveProperty(
      "open",
    );

    await wrapper.setProps({ prefill: null });
    expect(wrapper.get('[data-testid="position-confirmation"]').attributes()).not.toHaveProperty(
      "open",
    );
    await wrapper.get('[data-testid="confirm-position"]').trigger("click");
    await flushPromises();
    expect(operations.createPosition).not.toHaveBeenCalled();
  });

  it("clears only fields owned by the changed prefill action", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: null,
        summaryLots: [],
        symbol,
      },
    });
    await wrapper.get(`[data-testid="reduce-${coreLot.lotId}"]`).trigger("click");
    await wrapper.setProps({ prefill: buyPrefill });
    expect(wrapper.find('[data-testid="position-reduction-form"]').exists()).toBe(true);
    await wrapper.setProps({ prefill: null });
    expect(wrapper.find('[data-testid="position-reduction-form"]').exists()).toBe(true);

    await wrapper.get('input[name="createQuantity"]').setValue("200");
    await wrapper.setProps({ prefill: closePrefill });
    await wrapper.setProps({ prefill: null });
    expect((wrapper.get('input[name="createQuantity"]').element as HTMLInputElement).value).toBe(
      "200",
    );
  });

  it("withdraws a CLOSE notice even when its target lot has not loaded", async () => {
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: null,
        operations: positionOperations(),
        prefill: closePrefill,
        summaryLots: [],
        symbol,
      },
    });
    expect(wrapper.text()).toContain("提醒仅预填表单");

    await wrapper.setProps({ prefill: null });
    expect(wrapper.text()).not.toContain("提醒仅预填表单");
  });

  it("requires a new reduction review when the selected lot revision changes", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: null,
        summaryLots: [],
        symbol,
      },
    });
    await wrapper.get(`[data-testid="reduce-${coreLot.lotId}"]`).trigger("click");
    await wrapper.get('[data-testid="position-reduction-form"]').trigger("submit");
    await wrapper.setProps({
      initialPage: {
        ...page,
        items: (page.items ?? []).map((lot) =>
          lot.lotId === coreLot.lotId ? { ...lot, revision: lot.revision + 1 } : lot,
        ),
      },
    });

    await wrapper.get('[data-testid="confirm-position"]').trigger("click");
    await flushPromises();
    expect(operations.closePosition).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("持仓批次已更新，请重新复核减仓");
  });

  it("restores focus to the lot-row trigger after cancelling or completing reduction", async () => {
    const operations = positionOperations();
    const wrapper = mount(PositionLots, {
      attachTo: document.body,
      props: {
        asOfTradeDate,
        initialPage: page,
        operations,
        prefill: null,
        summaryLots: [],
        symbol,
      },
    });
    const trigger = wrapper.get(`[data-testid="reduce-${coreLot.lotId}"]`);
    await trigger.trigger("click");
    await wrapper.get('[data-testid="cancel-reduction"]').trigger("click");
    await nextTick();
    expect(document.activeElement).toBe(trigger.element);

    await trigger.trigger("click");
    await wrapper.get('[data-testid="position-reduction-form"]').trigger("submit");
    await wrapper.get('[data-testid="confirm-position"]').trigger("click");
    await flushPromises();
    expect(document.activeElement).toBe(trigger.element);
  });
});

describe("SymbolDetailView position composition", () => {
  it("composes position operations without moving them into chart or evidence state", () => {
    const detail = {
      positionLots: [],
      summary: {
        connected: true,
        decision: {
          dataAgeSeconds: 5,
          dataHealth: { fresh: true, status: "LIVE" },
          episodeLowFen: null,
          evaluatedAt: "2026-08-24T10:05:00+08:00",
          evidence: [],
          marketDataAt: "2026-08-24T10:05:00+08:00",
          planVersion: 3,
          priceFen: 6_500,
          signalType: "WAIT",
        },
        name: "华亚智能",
        observedAt: "2026-08-24T10:05:00+08:00",
        symbol,
      },
    } as unknown as SymbolDetailResponse;
    const operations = positionOperations();
    const wrapper = mount(SymbolDetailView, {
      global: {
        stubs: { EpisodeTimeline: true, PriceChart: true },
      },
      props: {
        bars: [],
        detail,
        events: [],
        positionAsOfTradeDate: asOfTradeDate,
        positionOperations: operations,
        positionPage: page,
        positionPrefill: buyPrefill,
      },
    });

    expect(wrapper.getComponent(PositionLots).props("symbol")).toBe(symbol);
    expect(wrapper.getComponent(PositionLots).props("initialPage")).toEqual(page);
    expect(wrapper.text()).toContain("人工持仓批次");
  });
});
