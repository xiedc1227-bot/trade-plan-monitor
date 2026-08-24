import { flushPromises, mount } from "@vue/test-utils";
import { createPinia } from "pinia";
import { defineComponent, h } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "../../src/api/client";
import type { DashboardResponse } from "../../src/api/generated";
import { useMonitorStream } from "../../src/composables/useMonitorStream";
import type { UseMonitorStreamResult } from "../../src/composables/useMonitorStream";
import { useMonitorStore } from "../../src/stores/monitor";

const snapshot: DashboardResponse = {
  connectionStatus: "CONNECTED",
  counts: {
    actionable: 0,
    blocked: 0,
    lowZoneWatch: 0,
    normal: 0,
    risk: 0,
    stale: 0,
  },
  dataAgeSeconds: 0,
  observedAt: "2026-08-24T10:30:00+08:00",
  sequence: 7,
  symbols: [],
};

class FakeWebSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  readonly url: string;
  readyState = FakeWebSocket.CONNECTING;
  readonly close = vi.fn((code?: number) => {
    if (this.readyState === FakeWebSocket.CLOSED) {
      return;
    }
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatchEvent(new CloseEvent("close", { code: code ?? 1000 }));
  });

  constructor(url: string) {
    super();
    this.url = url;
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatchEvent(new Event("open"));
  }

  receive(value: unknown) {
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(value) }));
  }

  serverClose(code = 1006) {
    if (this.readyState === FakeWebSocket.CLOSED) {
      return;
    }
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatchEvent(new CloseEvent("close", { code }));
  }
}

function deferred<Value>() {
  let resolve!: (value: Value) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<Value>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function createHarness(options: {
  apiClient: ApiClient;
  createSocket: (url: string) => WebSocket;
  random?: () => number;
}) {
  let stream!: UseMonitorStreamResult;
  const Harness = defineComponent({
    setup() {
      stream = useMonitorStream(options);
      return () => h("p", stream.connectionState.value.label);
    },
  });
  const pinia = createPinia();
  const wrapper = mount(Harness, { global: { plugins: [pinia] } });
  return { pinia, stream, wrapper };
}

function socketFactory() {
  const sockets: FakeWebSocket[] = [];
  const createSocket = vi.fn((url: string) => {
    const socket = new FakeWebSocket(url);
    sockets.push(socket);
    return socket as unknown as WebSocket;
  });
  return { createSocket, sockets };
}

function event(sequence: number) {
  return {
    aggregateId: "003043.SZ",
    eventId: "00000000-0000-0000-0000-000000000001",
    occurredAt: "2026-08-24T10:31:00+08:00",
    payload: {
      entityId: "003043.SZ",
      resultHash: "c".repeat(64),
      symbol: "003043.SZ",
    },
    schemaVersion: 1,
    sequence,
    type: "symbol.snapshot.updated",
  } as const;
}

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

describe("useMonitorStream", () => {
  it("loads an authoritative REST snapshot before opening the replay cursor", async () => {
    const pendingSnapshot = deferred<DashboardResponse>();
    const apiClient: ApiClient = { getDashboard: vi.fn(() => pendingSnapshot.promise) };
    const sockets = socketFactory();
    const { stream, wrapper } = createHarness({
      apiClient,
      createSocket: sockets.createSocket,
      random: () => 0.5,
    });

    expect(apiClient.getDashboard).toHaveBeenCalledTimes(1);
    expect(sockets.createSocket).not.toHaveBeenCalled();
    expect(stream.connectionState.value.code).toBe("CONNECTING");

    pendingSnapshot.resolve(snapshot);
    await flushPromises();

    expect(sockets.createSocket).toHaveBeenCalledWith(
      "ws://localhost:3000/ws/v1/monitor?after=7",
    );
    wrapper.unmount();
  });

  it("becomes live only after a matching heartbeat confirms replay is current", async () => {
    vi.useFakeTimers();
    const apiClient: ApiClient = { getDashboard: vi.fn(async () => snapshot) };
    const sockets = socketFactory();
    const { stream, wrapper } = createHarness({ apiClient, createSocket: sockets.createSocket });
    await flushPromises();
    const socket = sockets.sockets[0];
    if (socket === undefined) throw new Error("expected one socket");

    socket.open();
    expect(stream.connectionState.value).toMatchObject({
      code: "CONNECTING",
      label: expect.stringContaining("同步"),
    });

    socket.receive({ type: "heartbeat", sequence: 7 });
    expect(stream.connectionState.value).toEqual({
      code: "LIVE",
      label: "实时连接",
      marker: "●",
    });
    wrapper.unmount();
  });

  it.each(["DISCONNECTED", "UNKNOWN"] as const)(
    "never presents a %s authoritative snapshot as live",
    async (connectionStatus) => {
      vi.useFakeTimers();
      const apiClient: ApiClient = {
        getDashboard: vi.fn(async () => ({ ...snapshot, connectionStatus })),
      };
      const sockets = socketFactory();
      const { stream, wrapper } = createHarness({
        apiClient,
        createSocket: sockets.createSocket,
      });
      await flushPromises();
      const socket = sockets.sockets[0];
      if (socket === undefined) throw new Error("expected one socket");
      socket.open();
      socket.receive({ type: "heartbeat", sequence: 7 });

      expect(stream.connectionState.value).toEqual({
        code: "STALE",
        label: "数据可能已过期，正在恢复",
        marker: "!",
      });
      wrapper.unmount();
    },
  );

  it("refreshes the authoritative snapshot when an ordered invalidation arrives", async () => {
    vi.useFakeTimers();
    const apiClient: ApiClient = {
      getDashboard: vi
        .fn()
        .mockResolvedValueOnce(snapshot)
        .mockResolvedValueOnce({ ...snapshot, sequence: 8 }),
    };
    const sockets = socketFactory();
    const { pinia, stream, wrapper } = createHarness({
      apiClient,
      createSocket: sockets.createSocket,
    });
    await flushPromises();
    const firstSocket = sockets.sockets[0];
    if (firstSocket === undefined) throw new Error("expected one socket");
    firstSocket.open();
    firstSocket.receive({ type: "heartbeat", sequence: 7 });

    firstSocket.receive(event(8));
    await flushPromises();

    expect(firstSocket.close).toHaveBeenCalled();
    expect(apiClient.getDashboard).toHaveBeenCalledTimes(2);
    expect(useMonitorStore(pinia).sequence).toBe(8);
    expect(sockets.sockets[1]?.url).toBe("ws://localhost:3000/ws/v1/monitor?after=8");
    expect(stream.connectionState.value.code).toBe("CONNECTING");
    wrapper.unmount();
  });

  it("uses a fresh snapshot for sequence gaps and snapshot-required control frames", async () => {
    vi.useFakeTimers();
    const apiClient: ApiClient = {
      getDashboard: vi
        .fn()
        .mockResolvedValueOnce(snapshot)
        .mockResolvedValueOnce({ ...snapshot, sequence: 9 })
        .mockResolvedValueOnce({ ...snapshot, sequence: 12 }),
    };
    const sockets = socketFactory();
    const { pinia, wrapper } = createHarness({ apiClient, createSocket: sockets.createSocket });
    await flushPromises();
    const firstSocket = sockets.sockets[0];
    if (firstSocket === undefined) throw new Error("expected first socket");

    firstSocket.receive(event(9));
    await flushPromises();
    expect(useMonitorStore(pinia).sequence).toBe(9);
    expect(sockets.sockets[1]?.url).toContain("after=9");

    const secondSocket = sockets.sockets[1];
    if (secondSocket === undefined) throw new Error("expected second socket");
    secondSocket.receive({
      reason: "REPLAY_UNAVAILABLE",
      sequence: 12,
      type: "snapshot.required",
    });
    await flushPromises();

    expect(apiClient.getDashboard).toHaveBeenCalledTimes(3);
    expect(useMonitorStore(pinia).sequence).toBe(12);
    expect(sockets.sockets[2]?.url).toContain("after=12");
    wrapper.unmount();
  });

  it("accepts a server heartbeat emitted at the exact 20-second interval", async () => {
    vi.useFakeTimers();
    const apiClient: ApiClient = { getDashboard: vi.fn(async () => snapshot) };
    const sockets = socketFactory();
    const { stream, wrapper } = createHarness({ apiClient, createSocket: sockets.createSocket });
    await flushPromises();
    const socket = sockets.sockets[0];
    if (socket === undefined) throw new Error("expected one socket");
    socket.open();
    setTimeout(() => socket.receive({ type: "heartbeat", sequence: 7 }), 20_000);

    await vi.advanceTimersByTimeAsync(20_000);

    expect(socket.close).not.toHaveBeenCalled();
    expect(stream.connectionState.value.code).toBe("LIVE");
    wrapper.unmount();
  });

  it("times out a silent open connection after two missed heartbeat intervals", async () => {
    vi.useFakeTimers();
    const apiClient: ApiClient = { getDashboard: vi.fn(async () => snapshot) };
    const sockets = socketFactory();
    const { stream, wrapper } = createHarness({ apiClient, createSocket: sockets.createSocket });
    await flushPromises();
    const socket = sockets.sockets[0];
    if (socket === undefined) throw new Error("expected one socket");
    socket.open();

    await vi.advanceTimersByTimeAsync(39_999);
    expect(socket.close).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);

    expect(socket.close).toHaveBeenCalled();
    expect(stream.connectionState.value).toMatchObject({
      code: "STALE",
      label: expect.stringContaining("过期"),
    });
    wrapper.unmount();
  });

  it("times out a socket that never leaves the connecting state", async () => {
    vi.useFakeTimers();
    const apiClient: ApiClient = { getDashboard: vi.fn(async () => snapshot) };
    const sockets = socketFactory();
    const { stream, wrapper } = createHarness({ apiClient, createSocket: sockets.createSocket });
    await flushPromises();
    const socket = sockets.sockets[0];
    if (socket === undefined) throw new Error("expected one socket");

    await vi.advanceTimersByTimeAsync(20_000);

    expect(socket.close).toHaveBeenCalled();
    expect(stream.connectionState.value.code).toBe("STALE");
    wrapper.unmount();
  });

  it("reconnects with cursor-preserving capped exponential backoff and jitter", async () => {
    vi.useFakeTimers();
    const apiClient: ApiClient = { getDashboard: vi.fn(async () => snapshot) };
    const sockets = socketFactory();
    const { wrapper } = createHarness({
      apiClient,
      createSocket: sockets.createSocket,
      random: () => 0.5,
    });
    await flushPromises();

    const delays = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000];
    for (const [index, delay] of delays.entries()) {
      const socket = sockets.sockets[index];
      if (socket === undefined) throw new Error(`expected socket ${index}`);
      socket.serverClose();
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(sockets.sockets).toHaveLength(index + 1);
      await vi.advanceTimersByTimeAsync(1);
      expect(sockets.sockets).toHaveLength(index + 2);
      expect(sockets.sockets[index + 1]?.url).toContain("after=7");
    }
    wrapper.unmount();
  });

  it("shows a disconnected label when no snapshot exists and retries safely", async () => {
    vi.useFakeTimers();
    const apiClient: ApiClient = {
      getDashboard: vi.fn().mockRejectedValue(new Error("raw transport detail")),
    };
    const sockets = socketFactory();
    const { stream, wrapper } = createHarness({ apiClient, createSocket: sockets.createSocket });
    await flushPromises();

    expect(stream.connectionState.value).toEqual({
      code: "DISCONNECTED",
      label: "连接中断，正在重试",
      marker: "×",
    });
    expect(sockets.sockets).toHaveLength(0);
    wrapper.unmount();
  });

  it("aborts a half-open snapshot request and retries it after bounded backoff", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const apiClient: ApiClient = {
      getDashboard: vi.fn((options) => {
        if (options?.signal !== undefined) signals.push(options.signal);
        return new Promise<DashboardResponse>(() => undefined);
      }),
    };
    const sockets = socketFactory();
    const { stream, wrapper } = createHarness({
      apiClient,
      createSocket: sockets.createSocket,
      random: () => 0.5,
    });

    await vi.advanceTimersByTimeAsync(20_000);

    expect(signals[0]?.aborted).toBe(true);
    expect(stream.connectionState.value.code).toBe("DISCONNECTED");
    expect(apiClient.getDashboard).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(999);
    expect(apiClient.getDashboard).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(apiClient.getDashboard).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("retains jitter after exponential backoff reaches its cap", async () => {
    vi.useFakeTimers();

    async function cappedDelay(random: () => number): Promise<number | undefined> {
      const apiClient: ApiClient = { getDashboard: vi.fn(async () => snapshot) };
      const sockets = socketFactory();
      const timeoutSpy = vi.spyOn(globalThis, "setTimeout");
      const { wrapper } = createHarness({
        apiClient,
        createSocket: sockets.createSocket,
        random,
      });
      await flushPromises();
      for (let index = 0; index < 6; index += 1) {
        const socket = sockets.sockets[index];
        if (socket === undefined) throw new Error(`expected socket ${index}`);
        socket.serverClose();
        await vi.runOnlyPendingTimersAsync();
      }
      const cappedSocket = sockets.sockets[6];
      if (cappedSocket === undefined) throw new Error("expected capped socket");
      timeoutSpy.mockClear();
      cappedSocket.serverClose();
      const delay = timeoutSpy.mock.calls.at(-1)?.[1];
      wrapper.unmount();
      timeoutSpy.mockRestore();
      vi.clearAllTimers();
      return typeof delay === "number" ? delay : undefined;
    }

    await expect(cappedDelay(() => 0)).resolves.toBe(24_000);
    await expect(cappedDelay(() => 1)).resolves.toBe(30_000);
  });

  it("aborts REST and closes every timer and socket when its owner unmounts", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    const apiClient: ApiClient = {
      getDashboard: vi.fn(async (options) => {
        signal = options?.signal;
        return snapshot;
      }),
    };
    const sockets = socketFactory();
    const { wrapper } = createHarness({ apiClient, createSocket: sockets.createSocket });
    await flushPromises();
    const socket = sockets.sockets[0];
    if (socket === undefined) throw new Error("expected one socket");
    socket.open();

    wrapper.unmount();

    expect(signal?.aborted).toBe(true);
    expect(socket.close).toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
