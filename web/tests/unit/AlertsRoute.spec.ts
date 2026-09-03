import { createPinia, setActivePinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AlertPage } from "../../src/api/generated";
import { useMonitorStore } from "../../src/stores/monitor";
import type { AlertOperations } from "../../src/views/AlertsView.vue";
import AlertsRouteView from "../../src/views/AlertsRouteView.vue";

enableAutoUnmount(afterEach);

const emptyPage: AlertPage = {
  acknowledged: null,
  endAt: null,
  items: [],
  limit: 20,
  offset: 0,
  signalType: null,
  startAt: null,
  symbol: null,
  total: 0,
};

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("/alerts route", () => {
  it("loads the default authoritative page and passes only alert operations", async () => {
    const listAlerts = vi.fn(async () => emptyPage);
    const acknowledgeAlert = vi.fn();
    const wrapper = mount(AlertsRouteView, {
      props: { api: { acknowledgeAlert, listAlerts } },
    });

    await flushPromises();

    expect(listAlerts).toHaveBeenCalledWith({
      acknowledged: null,
      endAt: null,
      limit: 20,
      offset: 0,
      signalType: null,
      startAt: null,
      symbol: null,
    }, expect.any(Object));
    const view = wrapper.getComponent({ name: "AlertsView" });
    expect(view.props("initialPage")).toEqual(emptyPage);
    const operations = view.props("operations") as AlertOperations;
    await operations.listAlerts({
      acknowledged: null,
      endAt: null,
      limit: 20,
      offset: 20,
      signalType: null,
      startAt: null,
      symbol: null,
    });
    expect(listAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20 }));
  });

  it("forwards the latest validated monitor event as an invalidation hint", async () => {
    const store = useMonitorStore();
    store.applySnapshot({
      connectionStatus: "CONNECTED",
      counts: { actionable: 0, blocked: 0, lowZoneWatch: 0, normal: 0, risk: 0, stale: 0 },
      dataAgeSeconds: 0,
      marketIndexes: [],
      observedAt: "2026-08-24T10:05:00+08:00",
      sequence: 20,
      symbols: [],
    });
    const event = {
      aggregateId: "00000000-0000-4000-8000-000000000021",
      eventId: "00000000-0000-4000-8000-000000000021",
      occurredAt: "2026-08-24T10:05:05+08:00",
      payload: {
        entityId: "00000000-0000-4000-8000-000000000021",
        revision: 0,
        symbol: "003043.SZ",
      },
      schemaVersion: 1 as const,
      sequence: 21,
      type: "alert.created" as const,
    };
    expect(store.applyEvent(event)).toMatchObject({ status: "applied" });
    const wrapper = mount(AlertsRouteView, {
      props: {
        api: {
          acknowledgeAlert: vi.fn(),
          listAlerts: vi.fn(async () => emptyPage),
        },
      },
    });

    await flushPromises();

    expect(wrapper.getComponent({ name: "AlertsView" }).props("liveEvents")).toEqual([
      event,
    ]);
  });
});
