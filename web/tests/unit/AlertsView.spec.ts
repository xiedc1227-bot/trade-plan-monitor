import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlertPage, AlertView } from "../../src/api/generated";
import type { MonitorEventEnvelope } from "../../src/stores/monitor";
import AlertsView from "../../src/views/AlertsView.vue";
import type { AlertOperations } from "../../src/views/AlertsView.vue";

enableAutoUnmount(afterEach);

const firstId = "00000000-0000-4000-8000-000000000021";
const secondId = "00000000-0000-4000-8000-000000000022";
const marketTime = "2026-08-24T10:05:00+08:00";

function alert(
  eventId: string,
  sequence: number,
  overrides: Partial<AlertView> = {},
): AlertView {
  return {
    acknowledgedAt: null,
    blockers: [
      {
        children: [],
        code: "MANUAL_EVENT_RISK_CLEAR",
        facts: [{ key: "risk_code", unit: "CODE", value: "待人工复核" }],
        kind: "CONDITION",
        missingInputs: ["MANUAL_EVENT_RISK"],
        outcome: "MISSING_INPUT",
      },
    ],
    bucket: "CORE",
    causeId: `episode-${sequence}`,
    createdAt: "2026-08-24T10:05:05+08:00",
    currentActionable: true,
    dataAgeSeconds: 5,
    dedupKey: sequence.toString(16).padStart(64, "0"),
    evaluatedAt: marketTime,
    eventId,
    marketDataAt: marketTime,
    matchedConditions: [
      {
        children: [],
        code: "PRICE_IN_ZONE",
        facts: [{ key: "current_price_fen", unit: "FEN", value: 6420 }],
        kind: "CONDITION",
        missingInputs: [],
        outcome: "SATISFIED",
      },
    ],
    messageText: "<img src=x onerror=alert(1)>服务端提醒",
    name: "华亚智能",
    nextStep: { code: "RECORD_CONFIRMED_FILL", requiredInputs: [] },
    planHash: "b".repeat(64),
    planId: "huaya-smart",
    planVersion: 1,
    positionPrefill: {
      action: "BUY",
      bucket: "CORE",
      quantity: 100,
      relatedAlertId: eventId,
      symbol: "003043.SZ",
      targetLotId: null,
    },
    priceFen: 6420,
    quantity: 100,
    relevantZone: {
      highFen: 6450,
      includeHigh: true,
      includeLow: true,
      lowFen: 6300,
      zone: "LOW_BUY",
    },
    revision: 0,
    riskLineFen: 6080,
    satisfiedConditions: [],
    sequence,
    severity: "ACTION",
    signalType: "BUY_CORE_READY",
    symbol: "003043.SZ",
    targetLotId: null,
    tradingDate: "2026-08-24",
    unmetConditions: [],
    zone: "LOW_BUY",
    ...overrides,
  };
}

function page(items: AlertView[], overrides: Partial<AlertPage> = {}): AlertPage {
  return {
    acknowledged: null,
    endAt: null,
    items,
    limit: 20,
    offset: 0,
    signalType: null,
    startAt: null,
    symbol: null,
    total: items.length,
    ...overrides,
  };
}

function operations(overrides: Partial<AlertOperations> = {}): AlertOperations {
  return {
    acknowledgeAlert: vi.fn(async ({ command }) =>
      alert(command.alertId, 21, {
        acknowledgedAt: "2026-08-24T10:06:00+08:00",
        revision: 1,
      }),
    ),
    listAlerts: vi.fn(async () => page([alert(firstId, 21)])),
    ...overrides,
  };
}

function streamEvent(
  type: "alert.created" | "alert.acknowledged",
  sequence: number,
  aggregateId: string,
): MonitorEventEnvelope {
  return {
    aggregateId,
    eventId:
      type === "alert.created"
        ? aggregateId
        : `00000000-0000-4000-8000-${sequence.toString().padStart(12, "0")}`,
    occurredAt: "2026-08-24T10:06:00+08:00",
    payload: {
      entityId: aggregateId,
      revision: type === "alert.created" ? 0 : 1,
      symbol: "003043.SZ",
    },
    schemaVersion: 1,
    sequence,
    type,
  };
}

describe("AlertsView", () => {
  it("renders safe authoritative text, expandable evidence, event identity and chart-time links", async () => {
    const item = alert(firstId, 21, {
      satisfiedConditions: [
        {
          children: [],
          code: "AUTHORITATIVE_SATISFIED",
          facts: [],
          kind: "RULE",
          missingInputs: [],
          outcome: "SATISFIED",
        },
      ],
      unmetConditions: [
        {
          children: [],
          code: "AUTHORITATIVE_UNMET",
          facts: [],
          kind: "CONDITION",
          missingInputs: ["COMPLETE_5M_BAR"],
          outcome: "MISSING_INPUT",
        },
      ],
    });
    const wrapper = mount(AlertsView, {
      attachTo: document.body,
      props: {
        initialPage: page([item]),
        operations: operations(),
      },
    });

    expect(wrapper.text()).toContain("<img src=x onerror=alert(1)>服务端提醒");
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.text()).toContain(firstId);
    expect(wrapper.text()).toContain("2026-08-24 10:05:05");
    expect(wrapper.get('a[aria-label="在图表中查看华亚智能提醒时间"]').attributes("href")).toBe(
      "/stocks/003043.SZ?at=2026-08-24T10%3A05%3A00%2B08%3A00",
    );

    await wrapper.get(`button[aria-controls="alert-evidence-${firstId}"]`).trigger("click");
    expect(wrapper.text()).toContain("PRICE_IN_ZONE");
    expect(wrapper.text()).toContain("MANUAL_EVENT_RISK_CLEAR");
    expect(wrapper.text()).toContain("risk_code=待人工复核 CODE");
    expect(wrapper.text()).toContain("AUTHORITATIVE_SATISFIED");
    expect(wrapper.text()).toContain("AUTHORITATIVE_UNMET");
    expect(wrapper.text()).toContain("缺失输入：COMPLETE_5M_BAR");
  });

  it("retains an expired alert as history without presenting it as current", () => {
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([
          alert(firstId, 21, {
            currentActionable: false,
            positionPrefill: null,
          }),
        ]),
        operations: operations(),
      },
    });

    expect(wrapper.text()).toContain("历史提醒 · 当前不可操作");
    expect(wrapper.text()).toContain("服务端提醒");
  });

  it("issues pagination and symbol/type/time/acknowledgement filters as an authoritative query", async () => {
    const gateway = operations({
      listAlerts: vi.fn(async (query) => page([], { ...query, total: 42 })),
    });
    const wrapper = mount(AlertsView, {
      props: { initialPage: page([alert(firstId, 21)], { total: 42 }), operations: gateway },
    });

    await wrapper.get('input[name="alert-symbol"]').setValue("003043.SZ");
    await wrapper.get('select[name="alert-signal-type"]').setValue("RISK_BREACH");
    await wrapper.get('select[name="alert-acknowledged"]').setValue("false");
    await wrapper.get('input[name="alert-start-at"]').setValue("2026-08-24T09:30");
    await wrapper.get('input[name="alert-end-at"]').setValue("2026-08-24T15:00");
    await wrapper.get('button[type="submit"]').trigger("submit");
    await flushPromises();

    expect(gateway.listAlerts).toHaveBeenLastCalledWith({
      acknowledged: false,
      endAt: "2026-08-24T15:00:00+08:00",
      limit: 20,
      offset: 0,
      signalType: "RISK_BREACH",
      startAt: "2026-08-24T09:30:00+08:00",
      symbol: "003043.SZ",
    });

    await wrapper.get('button[aria-label="下一页提醒"]').trigger("click");
    await flushPromises();
    expect(gateway.listAlerts).toHaveBeenLastCalledWith(
      expect.objectContaining({ limit: 20, offset: 20 }),
    );
  });

  it("sends one idempotent acknowledgement and explicitly keeps acknowledgement separate from a fill", async () => {
    let resolveAcknowledgement!: (value: AlertView) => void;
    const acknowledgement = new Promise<AlertView>((resolve) => {
      resolveAcknowledgement = resolve;
    });
    const acknowledgedAlert = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:06:00+08:00",
      revision: 1,
    });
    const gateway = operations({
      acknowledgeAlert: vi.fn(() => acknowledgement),
      listAlerts: vi.fn(async () => page([acknowledgedAlert])),
    });
    const displayedPosition = { totalQuantity: 300 };
    const wrapper = mount(AlertsView, {
      attachTo: document.body,
      props: {
        createIdempotencyKey: () => "alert-ack-test",
        initialPage: page([alert(firstId, 21)]),
        operations: gateway,
      },
    });

    const button = wrapper.get(`button[data-acknowledge="${firstId}"]`);
    (button.element as HTMLElement).focus();
    await button.trigger("click");
    await button.trigger("click");
    expect(gateway.acknowledgeAlert).toHaveBeenCalledTimes(1);
    expect(gateway.acknowledgeAlert).toHaveBeenCalledWith({
      command: { alertId: firstId, expectedRevision: 0 },
      idempotencyKey: "alert-ack-test",
    });

    resolveAcknowledgement(acknowledgedAlert);
    await flushPromises();
    expect(wrapper.text()).toContain("已确认；确认提醒不代表成交，也不会修改持仓");
    expect(document.activeElement).toBe(
      wrapper.get(`button[data-acknowledge="${firstId}"]`).element,
    );
    expect(displayedPosition.totalQuantity).toBe(300);
  });

  it("refreshes once for unique live created/acknowledged invalidations and never duplicates snapshot rows", async () => {
    const first = alert(firstId, 21);
    const second = alert(secondId, 22);
    const acknowledged = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:07:00+08:00",
      revision: 1,
    });
    const listAlerts = vi
      .fn<AlertOperations["listAlerts"]>()
      .mockResolvedValueOnce(page([first, second]))
      .mockResolvedValueOnce(page([acknowledged, second]));
    const wrapper = mount(AlertsView, {
      props: { initialPage: page([first]), liveEvents: [], operations: operations({ listAlerts }) },
    });
    const created = streamEvent("alert.created", 22, secondId);

    await wrapper.setProps({ liveEvents: [created, created] });
    await flushPromises();
    expect(listAlerts).toHaveBeenCalledTimes(1);
    expect(wrapper.findAll(`[data-alert-id="${secondId}"]`)).toHaveLength(1);
    expect(wrapper.text()).toContain("已同步 1 条实时提醒更新");

    await wrapper.setProps({
      liveEvents: [created, created, streamEvent("alert.acknowledged", 23, firstId)],
    });
    await flushPromises();
    expect(listAlerts).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll(`[data-alert-id="${firstId}"]`)).toHaveLength(1);
    expect(wrapper.text()).toContain("已确认；确认提醒不代表成交，也不会修改持仓");
  });

  it("rejects duplicate event IDs or sequences and keeps failures secret-safe", async () => {
    const rawError = new Error("authorization=secret-token storage payload");
    const gateway = operations({ listAlerts: vi.fn(async () => Promise.reject(rawError)) });
    const duplicate = alert(secondId, 21);
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21), duplicate]),
        operations: gateway,
      },
    });

    expect(wrapper.findAll("[data-alert-id]")).toHaveLength(0);
    expect(wrapper.get('[role="alert"]').text()).toBe("提醒数据无效，请重新加载。");
    expect(wrapper.get('[role="status"]').text()).toBe("");
    expect(wrapper.text()).not.toContain("secret-token");

    await wrapper.get('button[data-retry-alerts="true"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("提醒加载失败，请稍后重试。");
    expect(wrapper.text()).not.toContain("authorization");
  });

  it("refreshes authoritative state after a revision conflict without leaking the rejected error", async () => {
    const acknowledged = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:08:00+08:00",
      revision: 1,
    });
    const listAlerts = vi.fn(async () => page([acknowledged]));
    const gateway = operations({
      acknowledgeAlert: vi.fn(async () => {
        throw Object.assign(new Error("secret revision payload"), { status: 409 });
      }),
      listAlerts,
    });
    const wrapper = mount(AlertsView, {
      props: { initialPage: page([alert(firstId, 21)]), operations: gateway },
    });

    const acknowledgementButton = wrapper.get(`button[data-acknowledge="${firstId}"]`);
    (acknowledgementButton.element as HTMLElement).focus();
    await acknowledgementButton.trigger("click");
    await flushPromises();

    expect(gateway.acknowledgeAlert).toHaveBeenCalledTimes(1);
    expect(listAlerts).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[role="alert"]').text()).toBe("提醒状态已更新，请核对最新状态。");
    expect(wrapper.text()).toContain("已确认；确认提醒不代表成交，也不会修改持仓");
    expect(wrapper.text()).not.toContain("secret revision payload");
  });

  it("requires paired time filters before issuing a query", async () => {
    const gateway = operations();
    const wrapper = mount(AlertsView, {
      props: { initialPage: page([alert(firstId, 21)]), operations: gateway },
    });

    await wrapper.get('input[name="alert-start-at"]').setValue("2026-08-24T09:30");
    await wrapper.get('button[type="submit"]').trigger("submit");

    expect(gateway.listAlerts).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toBe("开始时间和结束时间必须同时填写。");
  });

  it("retries an uncommitted live invalidation after refresh failure before marking it synchronized", async () => {
    const second = alert(secondId, 22);
    const listAlerts = vi
      .fn<AlertOperations["listAlerts"]>()
      .mockRejectedValueOnce(new Error("secret transport response"))
      .mockResolvedValueOnce(page([alert(firstId, 21), second]));
    const created = streamEvent("alert.created", 22, secondId);
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        liveEvents: [],
        operations: operations({ listAlerts }),
      },
    });

    await wrapper.setProps({ liveEvents: [created] });
    await flushPromises();
    expect(wrapper.text()).toContain("提醒加载失败，请稍后重试。");
    expect(wrapper.text()).toContain("尚无新的实时提醒更新");
    expect(wrapper.get('button[data-retry-alerts="true"]')).toBeDefined();

    await wrapper.get('button[data-retry-alerts="true"]').trigger("click");
    await flushPromises();
    expect(listAlerts).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll(`[data-alert-id="${secondId}"]`)).toHaveLength(1);
    expect(wrapper.text()).toContain("已同步 1 条实时提醒更新");
  });

  it("removes an acknowledged row from an unacknowledged filter through an authoritative refresh", async () => {
    const unacknowledgedPage = page([alert(firstId, 21)], {
      acknowledged: false,
      total: 1,
    });
    const acknowledgedReceipt = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:09:00+08:00",
      messageText: "tampered receipt text",
      revision: 1,
    });
    const listAlerts = vi.fn(async (query) => page([], { ...query, total: 0 }));
    const wrapper = mount(AlertsView, {
      attachTo: document.body,
      props: {
        initialPage: unacknowledgedPage,
        operations: operations({
          acknowledgeAlert: vi.fn(async () => acknowledgedReceipt),
          listAlerts,
        }),
      },
    });

    const acknowledgementButton = wrapper.get(`button[data-acknowledge="${firstId}"]`);
    (acknowledgementButton.element as HTMLElement).focus();
    await acknowledgementButton.trigger("click");
    await flushPromises();

    expect(listAlerts).toHaveBeenCalledWith(
      expect.objectContaining({ acknowledged: false, offset: 0 }),
    );
    expect(wrapper.find(`[data-alert-id="${firstId}"]`).exists()).toBe(false);
    expect(wrapper.text()).not.toContain("tampered receipt text");
    expect(wrapper.text()).toContain("当前筛选条件下暂无提醒");
    expect(wrapper.get('[role="status"]').text()).toContain(
      "提醒已确认；确认提醒不代表成交，也不会修改持仓",
    );
    expect(document.activeElement).toBe(wrapper.get('[role="status"]').element);
  });

  it("prevents an older list response from overwriting acknowledgement recovery", async () => {
    let resolveOldList!: (value: AlertPage) => void;
    let resolveRecovery!: (value: AlertPage) => void;
    const oldList = new Promise<AlertPage>((resolve) => {
      resolveOldList = resolve;
    });
    const recovery = new Promise<AlertPage>((resolve) => {
      resolveRecovery = resolve;
    });
    const acknowledged = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:10:00+08:00",
      revision: 1,
    });
    const listAlerts = vi
      .fn<AlertOperations["listAlerts"]>()
      .mockImplementationOnce(() => oldList)
      .mockImplementationOnce(() => recovery);
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        operations: operations({ listAlerts }),
      },
    });

    await wrapper.get('button[type="submit"]').trigger("submit");
    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await flushPromises();
    resolveOldList(page([alert(firstId, 21)]));
    await flushPromises();
    resolveRecovery(page([acknowledged]));
    await flushPromises();

    expect(wrapper.text()).toContain("已确认；确认提醒不代表成交，也不会修改持仓");
    expect(wrapper.get(`button[data-acknowledge="${firstId}"]`).attributes("aria-disabled")).toBe(
      "true",
    );
  });

  it("does not strand a live invalidation when acknowledgement supersedes its in-flight refresh", async () => {
    let resolveLiveRead!: (value: AlertPage) => void;
    const liveRead = new Promise<AlertPage>((resolve) => {
      resolveLiveRead = resolve;
    });
    const second = alert(secondId, 22);
    const acknowledged = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:11:00+08:00",
      revision: 1,
    });
    const listAlerts = vi
      .fn<AlertOperations["listAlerts"]>()
      .mockImplementationOnce(() => liveRead)
      .mockResolvedValueOnce(page([acknowledged, second]));
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        liveEvents: [],
        operations: operations({ listAlerts }),
      },
    });

    await wrapper.setProps({ liveEvents: [streamEvent("alert.created", 22, secondId)] });
    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.findAll(`[data-alert-id="${secondId}"]`)).toHaveLength(1);
    expect(wrapper.text()).toContain("已同步 1 条实时提醒更新");

    resolveLiveRead(page([alert(firstId, 21)]));
    await flushPromises();
    expect(listAlerts).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("已确认；确认提醒不代表成交，也不会修改持仓");
    expect(wrapper.findAll(`[data-alert-id="${secondId}"]`)).toHaveLength(1);
  });

  it("does not claim a successful conflict refresh when the authoritative read fails", async () => {
    const gateway = operations({
      acknowledgeAlert: vi.fn(async () => {
        throw Object.assign(new Error("secret conflict"), { status: 409 });
      }),
      listAlerts: vi.fn(async () => {
        throw new Error("secret refresh");
      }),
    });
    const wrapper = mount(AlertsView, {
      props: { initialPage: page([alert(firstId, 21)]), operations: gateway },
    });

    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("提醒加载失败，请稍后重试。");
    expect(wrapper.text()).not.toContain("最新状态");
    expect(wrapper.text()).not.toContain("secret");
  });

  it("contains hostile conflict accessors behind a fixed acknowledgement error", async () => {
    const hostile = new Proxy(
      {},
      {
        get() {
          throw new Error("secret getter");
        },
      },
    );
    const acknowledgeAlert = vi.fn(async () => Promise.reject(hostile));
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        operations: operations({ acknowledgeAlert }),
      },
    });

    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe("提醒确认失败，请稍后重试。");
    expect(wrapper.text()).not.toContain("secret getter");
    expect(wrapper.get(`button[data-acknowledge="${firstId}"]`).attributes("disabled")).toBeUndefined();

    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await flushPromises();
    expect(acknowledgeAlert).toHaveBeenCalledTimes(2);
  });

  it("synchronizes filter controls when a new authoritative page changes the query", async () => {
    const wrapper = mount(AlertsView, {
      props: { initialPage: page([alert(firstId, 21)]), operations: operations() },
    });

    await wrapper.setProps({
      initialPage: page([], {
        acknowledged: true,
        signalType: "RISK_BREACH",
        symbol: "600000.SH",
      }),
    });
    expect(wrapper.get<HTMLInputElement>('input[name="alert-symbol"]').element.value).toBe(
      "600000.SH",
    );
    expect(wrapper.get<HTMLSelectElement>('select[name="alert-signal-type"]').element.value).toBe(
      "RISK_BREACH",
    );
    expect(wrapper.get<HTMLSelectElement>('select[name="alert-acknowledged"]').element.value).toBe(
      "true",
    );
  });

  it("keeps the latest user filter when acknowledgement recovery supersedes its pending read", async () => {
    let resolveAcknowledgement!: (value: AlertView) => void;
    let resolveFilterRead!: (value: AlertPage) => void;
    const acknowledgement = new Promise<AlertView>((resolve) => {
      resolveAcknowledgement = resolve;
    });
    const filterRead = new Promise<AlertPage>((resolve) => {
      resolveFilterRead = resolve;
    });
    const listAlerts = vi
      .fn<AlertOperations["listAlerts"]>()
      .mockImplementationOnce(() => filterRead)
      .mockImplementationOnce(async (query) => page([], { ...query, total: 0 }));
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        operations: operations({
          acknowledgeAlert: vi.fn(() => acknowledgement),
          listAlerts,
        }),
      },
    });

    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await wrapper.get('input[name="alert-symbol"]').setValue("600000.SH");
    await wrapper.get('form[aria-label="筛选提醒"]').trigger("submit");
    resolveAcknowledgement(
      alert(firstId, 21, {
        acknowledgedAt: "2026-08-24T10:12:00+08:00",
        revision: 1,
      }),
    );
    await flushPromises();
    resolveFilterRead(page([], { symbol: "600000.SH", total: 0 }));
    await flushPromises();

    expect(listAlerts).toHaveBeenCalledTimes(2);
    expect(listAlerts.mock.calls[1]?.[0]).toEqual(
      expect.objectContaining({ symbol: "600000.SH" }),
    );
    expect(wrapper.get<HTMLInputElement>('input[name="alert-symbol"]').element.value).toBe(
      "600000.SH",
    );
  });

  it("preserves an unsubmitted filter draft across a same-query live refresh", async () => {
    const listAlerts = vi.fn(async () => page([alert(firstId, 21), alert(secondId, 22)]));
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        liveEvents: [],
        operations: operations({ listAlerts }),
      },
    });

    await wrapper.get('input[name="alert-symbol"]').setValue("600000.SH");
    await wrapper.setProps({
      liveEvents: [streamEvent("alert.created", 22, secondId)],
    });
    await flushPromises();

    expect(listAlerts).toHaveBeenCalledTimes(1);
    expect(wrapper.get<HTMLInputElement>('input[name="alert-symbol"]').element.value).toBe(
      "600000.SH",
    );
  });

  it("settles acknowledgement from a newer filter read that supersedes its recovery read", async () => {
    let resolveRecovery!: (value: AlertPage) => void;
    const recovery = new Promise<AlertPage>((resolve) => {
      resolveRecovery = resolve;
    });
    const receipt = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:13:00+08:00",
      revision: 1,
    });
    const listAlerts = vi
      .fn<AlertOperations["listAlerts"]>()
      .mockImplementationOnce(() => recovery)
      .mockImplementationOnce(async (query) => page([], { ...query, total: 0 }));
    const wrapper = mount(AlertsView, {
      attachTo: document.body,
      props: {
        initialPage: page([alert(firstId, 21)]),
        operations: operations({
          acknowledgeAlert: vi.fn(async () => receipt),
          listAlerts,
        }),
      },
    });
    const button = wrapper.get(`button[data-acknowledge="${firstId}"]`);
    (button.element as HTMLElement).focus();
    await button.trigger("click");
    await flushPromises();

    await wrapper.get('input[name="alert-symbol"]').setValue("600000.SH");
    await wrapper.get('form[aria-label="筛选提醒"]').trigger("submit");
    await flushPromises();
    resolveRecovery(page([alert(firstId, 21)]));
    await flushPromises();

    expect(listAlerts).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[role="status"]').text()).toContain("提醒已确认；确认提醒不代表成交");
    expect(document.activeElement).toBe(wrapper.get('[role="status"]').element);
    expect(wrapper.get<HTMLInputElement>('input[name="alert-symbol"]').element.value).toBe(
      "600000.SH",
    );
  });

  it("restores focus when an invalid receipt is followed by a page that removes the row", async () => {
    const invalidReceipt = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:14:00+08:00",
      revision: 1,
      sequence: 999,
    });
    const wrapper = mount(AlertsView, {
      attachTo: document.body,
      props: {
        initialPage: page([alert(firstId, 21)], { acknowledged: false }),
        operations: operations({
          acknowledgeAlert: vi.fn(async () => invalidReceipt),
          listAlerts: vi.fn(async (query) => page([], { ...query, total: 0 })),
        }),
      },
    });
    const button = wrapper.get(`button[data-acknowledge="${firstId}"]`);
    (button.element as HTMLElement).focus();
    await button.trigger("click");
    await flushPromises();

    expect(wrapper.get('[role="status"]').text()).toContain("提醒确认回执无效");
    expect(document.activeElement).toBe(wrapper.get('[role="status"]').element);
  });

  it("reports authoritative acknowledgement after an uncertain command error proves success", async () => {
    const acknowledged = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:15:00+08:00",
      revision: 1,
    });
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        operations: operations({
          acknowledgeAlert: vi.fn(async () => {
            throw new Error("secret uncertain response");
          }),
          listAlerts: vi.fn(async () => page([acknowledged])),
        }),
      },
    });

    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toContain("提醒已确认；确认提醒不代表成交");
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("secret uncertain response");
  });

  it("settles a retained acknowledgement context when a later retry loads authoritative success", async () => {
    const acknowledged = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:16:00+08:00",
      revision: 1,
    });
    const listAlerts = vi
      .fn<AlertOperations["listAlerts"]>()
      .mockRejectedValueOnce(new Error("secret first refresh"))
      .mockResolvedValueOnce(page([acknowledged]));
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        operations: operations({ listAlerts }),
      },
    });

    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toContain("权威状态尚未同步");
    expect(wrapper.get(`button[data-acknowledge="${firstId}"]`).attributes("disabled")).toBeDefined();

    await wrapper.get('button[data-retry-alerts="true"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toContain("提醒已确认；确认提醒不代表成交");
    expect(wrapper.get(`button[data-acknowledge="${firstId}"]`).attributes("aria-disabled")).toBe(
      "true",
    );
  });

  it("lets an external authoritative page settle a superseded acknowledgement recovery", async () => {
    let resolveRecovery!: (value: AlertPage) => void;
    const recovery = new Promise<AlertPage>((resolve) => {
      resolveRecovery = resolve;
    });
    const acknowledged = alert(firstId, 21, {
      acknowledgedAt: "2026-08-24T10:17:00+08:00",
      revision: 1,
    });
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([alert(firstId, 21)]),
        operations: operations({ listAlerts: vi.fn(() => recovery) }),
      },
    });

    await wrapper.get(`button[data-acknowledge="${firstId}"]`).trigger("click");
    await flushPromises();
    await wrapper.setProps({ initialPage: page([acknowledged]) });
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toContain("提醒已确认；确认提醒不代表成交");

    resolveRecovery(page([alert(firstId, 21)]));
    await flushPromises();
    expect(wrapper.get(`button[data-acknowledge="${firstId}"]`).attributes("aria-disabled")).toBe(
      "true",
    );
    expect(wrapper.get('[role="status"]').text()).toContain("提醒已确认；确认提醒不代表成交");
  });

  it("reserves the bounded acknowledgement capacity before a slow gateway settles", async () => {
    const neverSettles = new Promise<AlertView>(() => undefined);
    const acknowledgeAlert = vi.fn(() => neverSettles);
    const event = (index: number): AlertView =>
      alert(`00000000-0000-4000-8000-${(index + 1).toString().padStart(12, "0")}`, index + 1);
    const wrapper = mount(AlertsView, {
      props: {
        initialPage: page([event(0)]),
        operations: operations({ acknowledgeAlert }),
      },
    });

    for (let index = 0; index <= 256; index += 1) {
      if (index > 0) {
        await wrapper.setProps({ initialPage: page([event(index)]) });
      }
      await wrapper
        .get(`button[data-acknowledge="${event(index).eventId}"]`)
        .trigger("click");
    }

    expect(acknowledgeAlert).toHaveBeenCalledTimes(256);
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "待确认状态过多，请先重新加载权威提醒。",
    );
  });
});
