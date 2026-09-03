import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import { ApiClientError } from "../../src/api/transport";
import type { RuntimeHealthResponse } from "../../src/api/generated";
import { createHealthApi } from "../../src/api/health";
import SystemRouteView from "../../src/views/SystemRouteView.vue";

const degradedHealth = {
  cooldownUntil: null,
  database: {
    errorCode: null,
    lastBackupAt: null,
    lastCheckpointAt: null,
    status: "READY",
    walStatus: "READY",
  },
  delivery: {
    errorCode: null,
    failedCount: 0,
    lastDeliveredAt: null,
    nextRetryAt: null,
    pendingCount: 0,
    status: "READY",
  },
  executor: { activeCount: 0, maxWorkers: 2, waitingCount: 0 },
  gaps: [],
  lastCompletedMinute: null,
  lastCompletedMinuteAgeSeconds: null,
  latestEvaluationAgeSeconds: null,
  latestEvaluationAt: null,
  nextPollAt: null,
  nextRetryAt: null,
  observedAt: "2026-08-24T10:00:00+08:00",
  providers: [],
  readOnly: true,
  startedAt: "2026-08-24T09:00:00+08:00",
  status: "DEGRADED",
  stoppedAt: null,
} as const;

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("health API", () => {
  it("loads and strictly validates the backend RuntimeHealthResponse", async () => {
    const fetchImplementation = vi.fn(async () =>
      new Response(JSON.stringify(degradedHealth), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );

    const result = await createHealthApi(fetchImplementation).getHealth();

    expect(result).toEqual(degradedHealth);
    expect(fetchImplementation).toHaveBeenCalledWith(
      "/api/v1/health",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("rejects a health payload with unexpected fields", async () => {
    const fetchImplementation = vi.fn(async () =>
      new Response(JSON.stringify({ ...degradedHealth, token: "never-render" }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );

    await expect(createHealthApi(fetchImplementation).getHealth()).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
});

describe("/system route", () => {
  it("loads health on entry and explicitly refreshes from the backend", async () => {
    const getHealth = vi
      .fn()
      .mockResolvedValueOnce(degradedHealth)
      .mockResolvedValueOnce({ ...degradedHealth, observedAt: "2026-08-24T10:01:00+08:00" });
    const wrapper = mount(SystemRouteView, {
      attachTo: document.body,
      props: { api: { getHealth } },
    });

    await flushPromises();
    expect(getHealth).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="market-status-strip"]').attributes("data-status")).toBe(
      "DEGRADED",
    );
    expect(wrapper.text()).toContain("降级");

    await wrapper.get('[data-testid="refresh-system-health"]').trigger("click");
    await flushPromises();

    expect(getHealth).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("2026-08-24T10:01:00+08:00");
  });

  it("keeps the cached health snapshot and uses a fixed error message on refresh failure", async () => {
    const getHealth = vi.fn().mockResolvedValueOnce(degradedHealth).mockRejectedValueOnce(
      new ApiClientError({
        code: "SERVICE_UNAVAILABLE",
        message: "raw provider failure must not escape",
        status: 503,
      }),
    );
    const wrapper = mount(SystemRouteView, {
      attachTo: document.body,
      props: { api: { getHealth } },
    });

    await flushPromises();
    await wrapper.get('[data-testid="refresh-system-health"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("显示上一次安全快照");
    expect(wrapper.text()).not.toContain("raw provider failure");
    expect(wrapper.get('[data-testid="market-status-strip"]').attributes("data-status")).toBe(
      "DEGRADED",
    );
  });

  it("navigates gap links through the existing stock-detail named route", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: "/system", name: "system", component: SystemRouteView },
        { path: "/stocks/:symbol", name: "stock-detail", component: { template: "<p />" } },
      ],
    });
    await router.push("/system");
    await router.isReady();
    const routeHealth: RuntimeHealthResponse = {
      ...degradedHealth,
      gaps: [{ barEnd: "2026-08-24T09:59:00+08:00", symbol: "600000.SH" }],
      providers: [],
    };
    const wrapper = mount(SystemRouteView, {
      attachTo: document.body,
      global: { plugins: [router] },
      props: {
        api: {
          getHealth: vi.fn(async () => routeHealth),
        },
      },
    });

    await flushPromises();
    await wrapper.get('[data-testid="health-gap-link"]').trigger("click");
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe("stock-detail"));

    expect(router.currentRoute.value.name).toBe("stock-detail");
    expect(router.currentRoute.value.params.symbol).toBe("600000.SH");
  });
});
