import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts", () => ({
  init: () => ({
    dispose: vi.fn(),
    off: vi.fn(),
    on: vi.fn(),
    resize: vi.fn(),
    setOption: vi.fn(),
  }),
}));

import type {
  BarPage,
  PositionLotPage,
  SymbolDetailResponse,
  SymbolEventPage,
} from "../../src/api/generated";
import { createSymbolApi } from "../../src/api/symbols";
import type { PositionOperations } from "../../src/composables/usePositions";
import SymbolDetailRouteView from "../../src/views/SymbolDetailRouteView.vue";

const symbol = "003043.SZ";
const observedAt = "2026-08-24T10:05:05.000000+08:00";
const initialRange = Object.freeze({
  endAt: observedAt,
  startAt: "2026-08-24T00:00:00.000000+08:00",
});

const detail = {
  positionLots: [],
  summary: {
    connected: false,
    decision: {
      dataAgeSeconds: null,
      dataHealth: {
        dataAgeSeconds: null,
        fresh: false,
        latestBarEnd: null,
        requiredDataComplete: false,
        status: "DEGRADED",
      },
      episodeLowFen: null,
      episodeStatus: null,
      evaluatedAt: observedAt,
      marketDataAt: null,
      nextStep: { code: "WAIT_FOR_REQUIRED_DATA" },
      planHash: "a".repeat(64),
      planId: "plan-1",
      planVersion: 1,
      position: {
        coreQuantity: 0,
        sellableCoreQuantity: 0,
        sellableTacticalQuantity: 0,
        tacticalQuantity: 0,
        totalQuantity: 0,
      },
      priceFen: null,
      resultHash: "b".repeat(64),
      riskBreachTradeDate: null,
      riskStatus: "CLEAR",
      signalType: "WAIT",
      symbol,
      zone: "UNKNOWN",
    },
    name: "华亚智能",
    observedAt,
    riskDistanceFen: null,
    satisfiedConditionCount: 0,
    symbol,
    totalConditionCount: 0,
  },
} as SymbolDetailResponse;

function positionPage(
  targetSymbol = symbol,
  targetAsOfTradeDate = observedAt.slice(0, 10),
): PositionLotPage {
  return {
    asOfTradeDate: targetAsOfTradeDate,
    items: [],
    limit: 100,
    offset: 0,
    symbol: targetSymbol,
    total: 0,
  };
}

function barsPage(range: Readonly<{ startAt: string; endAt: string }>): BarPage {
  return {
    endAt: range.endAt,
    items: [],
    limit: 100,
    offset: 0,
    startAt: range.startAt,
    total: 0,
  };
}

function eventsPage(range: Readonly<{ startAt: string; endAt: string }>): SymbolEventPage {
  return {
    endAt: range.endAt,
    items: [],
    limit: 100,
    offset: 0,
    startAt: range.startAt,
    total: 0,
  };
}

enableAutoUnmount(afterEach);

afterEach(() => {
  vi.restoreAllMocks();
});

describe("/stocks/:symbol route", () => {
  it("rejects unexpected fields from the symbol-detail response before rendering", async () => {
    const fetchImplementation = vi.fn(async () =>
      new Response(JSON.stringify({ ...detail, token: "never-render" }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );

    await expect(createSymbolApi(fetchImplementation).getSymbol(symbol)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("loads authoritative detail then queries bars and events for the observed Shanghai day", async () => {
    const getBars = vi.fn(async (_symbol: string, query: typeof initialRange) => barsPage(query));
    const getEvents = vi.fn(async (_symbol: string, query: typeof initialRange) => eventsPage(query));
    const wrapper = mount(SymbolDetailRouteView, {
      attachTo: document.body,
      props: {
        api: {
          getBars,
          getEvents,
          getSymbol: vi.fn(async () => detail),
        },
        symbol,
      },
    });

    await flushPromises();

    expect(wrapper.text()).toContain("华亚智能 · 003043.SZ");
    expect(getBars).toHaveBeenCalledWith(symbol, {
      ...initialRange,
      interval: "FIVE_MINUTES",
      limit: 100,
      offset: 0,
    }, expect.any(Object));
    expect(getEvents).toHaveBeenCalledWith(symbol, {
      ...initialRange,
      limit: 100,
      offset: 0,
    }, expect.any(Object));
  });

  it("loads the authoritative position page for the observed trade date and passes its gateway through", async () => {
    const getBars = vi.fn(async (_symbol: string, query: typeof initialRange) => barsPage(query));
    const getEvents = vi.fn(async (_symbol: string, query: typeof initialRange) => eventsPage(query));
    const listPositions = vi.fn(async () => positionPage());
    const positionApi = {
      closePosition: vi.fn(),
      createPosition: vi.fn(),
      listPositions,
    };
    const wrapper = mount(SymbolDetailRouteView, {
      attachTo: document.body,
      props: {
        api: {
          getBars,
          getEvents,
          getSymbol: vi.fn(async () => detail),
        },
        positionApi,
        symbol,
      },
    });

    await flushPromises();

    expect(listPositions).toHaveBeenCalledWith({
      asOfTradeDate: "2026-08-24",
      limit: 100,
      offset: 0,
      symbol,
    }, expect.any(Object));
    const detailView = wrapper.getComponent({ name: "SymbolDetailView" });
    expect(detailView.props("positionAsOfTradeDate")).toBe("2026-08-24");
    expect(detailView.props("positionPage")).toEqual(positionPage());
    expect(detailView.props("positionOperations")).toMatchObject({
      closePosition: expect.any(Function),
      createPosition: expect.any(Function),
      listPositions: expect.any(Function),
    });
  });

  it("submits an explicit canonical Shanghai range without inventing bars or events", async () => {
    const getBars = vi.fn(async (_symbol: string, query: typeof initialRange) => barsPage(query));
    const getEvents = vi.fn(async (_symbol: string, query: typeof initialRange) => eventsPage(query));
    const wrapper = mount(SymbolDetailRouteView, {
      attachTo: document.body,
      props: {
        api: {
          getBars,
          getEvents,
          getSymbol: vi.fn(async () => detail),
        },
        symbol,
      },
    });
    await flushPromises();

    const startAt = "2026-08-22T09:30:00.000000+08:00";
    const endAt = "2026-08-22T15:00:00.000000+08:00";
    await wrapper.get<HTMLInputElement>("#symbol-history-start-at").setValue(startAt);
    await wrapper.get<HTMLInputElement>("#symbol-history-end-at").setValue(endAt);
    await wrapper.get("[data-testid=\"submit-symbol-history-range\"]").trigger("submit");
    await flushPromises();

    expect(getBars).toHaveBeenLastCalledWith(symbol, {
      endAt,
      interval: "FIVE_MINUTES",
      limit: 100,
      offset: 0,
      startAt,
    }, expect.any(Object));
    expect(getEvents).toHaveBeenLastCalledWith(symbol, {
      endAt,
      limit: 100,
      offset: 0,
      startAt,
    }, expect.any(Object));
  });

  it("rejects an invalid range locally without sending another request", async () => {
    const getBars = vi.fn(async (_symbol: string, query: typeof initialRange) => barsPage(query));
    const getEvents = vi.fn(async (_symbol: string, query: typeof initialRange) => eventsPage(query));
    const wrapper = mount(SymbolDetailRouteView, {
      attachTo: document.body,
      props: {
        api: {
          getBars,
          getEvents,
          getSymbol: vi.fn(async () => detail),
        },
        symbol,
      },
    });
    await flushPromises();
    const initialCalls = getBars.mock.calls.length;

    await wrapper
      .get<HTMLInputElement>("#symbol-history-start-at")
      .setValue("2026-08-25T09:30:00.000000+08:00");
    await wrapper
      .get<HTMLInputElement>("#symbol-history-end-at")
      .setValue("2026-08-24T15:00:00.000000+08:00");
    await wrapper.get("[data-testid=\"submit-symbol-history-range\"]").trigger("submit");
    await flushPromises();

    expect(getBars).toHaveBeenCalledTimes(initialCalls);
    expect(wrapper.get("[role=alert]").text()).toContain("时间范围必须使用有效且递增的上海时间");
  });

  it("does not let an obsolete symbol-detail response replace the latest route", async () => {
    const laterSymbol = "600000.SH";
    const laterDetail: SymbolDetailResponse = {
      ...detail,
      summary: {
        ...detail.summary,
        decision: { ...detail.summary.decision, symbol: laterSymbol },
        symbol: laterSymbol,
      },
    };
    let resolveFirst: ((value: SymbolDetailResponse) => void) | undefined;
    const getSymbol = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<SymbolDetailResponse>((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce(laterDetail);
    const api = {
      getBars: vi.fn(async (_symbol: string, query: typeof initialRange) => barsPage(query)),
      getEvents: vi.fn(async (_symbol: string, query: typeof initialRange) => eventsPage(query)),
      getSymbol,
    };
    const wrapper = mount(SymbolDetailRouteView, {
      attachTo: document.body,
      global: {
        stubs: {
          SymbolDetailView: {
            props: ["detail"],
            template: "<h1>{{ detail === null ? '个股详情' : `${detail.summary.name} · ${detail.summary.symbol}` }}</h1>",
          },
        },
      },
      props: { api, symbol },
    });

    await wrapper.setProps({ symbol: laterSymbol });
    await flushPromises();
    resolveFirst?.(detail);
    await flushPromises();

    expect(wrapper.text()).toContain(`华亚智能 · ${laterSymbol}`);
    expect(wrapper.text()).not.toContain(`华亚智能 · ${symbol}`);
  });

  it("does not let a late position page for an old symbol replace the latest authority", async () => {
    const laterSymbol = "600000.SH";
    const laterObservedAt = "2026-08-25T10:05:05.000000+08:00";
    const laterDetail: SymbolDetailResponse = {
      ...detail,
      summary: {
        ...detail.summary,
        decision: { ...detail.summary.decision, symbol: laterSymbol },
        observedAt: laterObservedAt,
        symbol: laterSymbol,
      },
    };
    let resolveFirstPage: ((value: PositionLotPage) => void) | undefined;
    const listPositions = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<PositionLotPage>((resolve) => {
            resolveFirstPage = resolve;
          }),
      )
      .mockResolvedValueOnce(positionPage(laterSymbol, "2026-08-25"));
    const wrapper = mount(SymbolDetailRouteView, {
      attachTo: document.body,
      props: {
        api: {
          getBars: vi.fn(async (_symbol: string, query: typeof initialRange) => barsPage(query)),
          getEvents: vi.fn(async (_symbol: string, query: typeof initialRange) => eventsPage(query)),
          getSymbol: vi
            .fn()
            .mockResolvedValueOnce(detail)
            .mockResolvedValueOnce(laterDetail),
        },
        positionApi: {
          closePosition: vi.fn(),
          createPosition: vi.fn(),
          listPositions,
        },
        symbol,
      },
    });

    await flushPromises();
    await wrapper.setProps({ symbol: laterSymbol });
    await flushPromises();
    resolveFirstPage?.(positionPage());
    await flushPromises();

    const detailView = wrapper.getComponent({ name: "SymbolDetailView" });
    expect(detailView.props("positionPage")).toEqual(
      positionPage(laterSymbol, "2026-08-25"),
    );
    expect(listPositions).toHaveBeenLastCalledWith({
      asOfTradeDate: "2026-08-25",
      limit: 100,
      offset: 0,
      symbol: laterSymbol,
    }, expect.any(Object));
  });

  it("invalidates a pending parent read before a mutation-owned refresh", async () => {
    let resolveInitial: ((value: PositionLotPage) => void) | undefined;
    let initialSignal: AbortSignal | undefined;
    const mutationPage = { ...positionPage(), total: 1 };
    const listPositions = vi
      .fn()
      .mockImplementationOnce(
        (_request, options: { signal?: AbortSignal } | undefined) => {
          initialSignal = options?.signal;
          return new Promise<PositionLotPage>((resolve) => {
            resolveInitial = resolve;
          });
        },
      )
      .mockResolvedValueOnce(mutationPage);
    const wrapper = mount(SymbolDetailRouteView, {
      attachTo: document.body,
      props: {
        api: {
          getBars: vi.fn(async (_symbol: string, query: typeof initialRange) => barsPage(query)),
          getEvents: vi.fn(async (_symbol: string, query: typeof initialRange) => eventsPage(query)),
          getSymbol: vi.fn(async () => detail),
        },
        positionApi: {
          closePosition: vi.fn(),
          createPosition: vi.fn(),
          listPositions,
        },
        symbol,
      },
    });
    await flushPromises();
    const detailView = wrapper.getComponent({ name: "SymbolDetailView" });
    const operations = detailView.props("positionOperations") as PositionOperations;

    await expect(
      operations.listPositions({
        asOfTradeDate: "2026-08-24",
        limit: 100,
        offset: 0,
        symbol,
      }),
    ).resolves.toEqual(mutationPage);
    expect(initialSignal?.aborted).toBe(true);
    resolveInitial?.(positionPage());
    await flushPromises();
    expect(detailView.props("positionPage")).toBeNull();
  });
});
