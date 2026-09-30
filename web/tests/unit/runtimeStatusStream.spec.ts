import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRuntimeMonitor } from "../../src/runtime-status/stream";
import { createMonitorProtocol } from "../../src/runtime-status/protocol";
import { useRuntimeMonitorStore } from "../../src/runtime-status/store";
import { isRuntimeDashboard, isRuntimeHealth, isHeartbeat } from "../../src/runtime-status/validators";
import { emptyDashboard, explicitDashboard } from "../fixtures/runtimeStatus";

class Socket extends EventTarget {
  readyState = 0;
  constructor(readonly url: string) { super(); }
  open() { this.readyState = 1; this.dispatchEvent(new Event("open")); }
  receive(frame: unknown) { this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(frame) })); }
  close(code = 1000, reason = "") { this.readyState = 3; this.dispatchEvent(new CloseEvent("close", { code, reason })); }
}
function valid(value = emptyDashboard()) { if (!isRuntimeDashboard(value)) throw new Error("invalid test snapshot"); return value; }
function setup(value = valid()) {
  const api = { getDashboard: vi.fn(async () => structuredClone(value)) };
  const sockets: Socket[] = [];
  const protocol = createMonitorProtocol({ origin: "http://127.0.0.1:32109", validateHealth: isRuntimeHealth, fetchImplementation: vi.fn() });
  const store = useRuntimeMonitorStore();
  const monitor = createRuntimeMonitor({ api, protocol, store, origin: "http://127.0.0.1:32109", random: () => 0.5,
    createSocket: (url) => { const socket = new Socket(url); sockets.push(socket); return socket as unknown as WebSocket; }, now: () => performance.now() });
  const heartbeat = (at = "2026-09-14T10:10:16.000000+08:00") => ({ type: "heartbeat", monitorContractVersion: 2, sequence: value.sequence,
    runtimeGeneration: value.runtimeGeneration, observedAt: at, runtimeStatus: value.runtimeStatus });
  return { api, store, sockets, protocol, monitor, heartbeat };
}
beforeEach(() => { vi.useFakeTimers(); setActivePinia(createPinia()); });
afterEach(() => { vi.useRealTimers(); });

describe("v2 transport and authoritative refresh", () => {
  it.each(["STOPPING", "RUNTIME_FAULT", "STORAGE_UNAVAILABLE"] as const)("withdraws all current presentation immediately for %s while a fresh projection is pending", async reason => {
    const h = setup(valid(explicitDashboard())); h.monitor.start(); await flushPromises();
    const socket = h.sockets[0]!; socket.open(); socket.receive(h.heartbeat()); await flushPromises();
    const row = h.store.snapshot!.symbols[0]!; expect(h.store.isActionable(row, "risk")).toBe(true);
    h.api.getDashboard.mockImplementation(() => new Promise(() => {}));
    const frame = h.heartbeat("2026-09-14T10:10:17+08:00"); frame.runtimeStatus.mode = "BLOCKED";
    frame.runtimeStatus.reasonCode = reason === "STOPPING" ? "RUNTIME_STOPPING" : reason;
    if (reason === "STOPPING") frame.runtimeStatus.lifecycle = "STOPPING";
    for (const scope of frame.runtimeStatus.scopes) if (scope.kind === "PLAN") scope.readOnly = true;
    expect(isHeartbeat(frame)).toBe(true); socket.receive(frame);
    expect(h.store.isActionable(row, "risk")).toBe(false); expect(h.api.getDashboard).toHaveBeenCalledTimes(3);
    h.monitor.stop();
  });
  it("refreshes a readOnly-only standby transition without expiring proven state risk", async () => {
    const h = setup(valid(explicitDashboard())); h.monitor.start(); await flushPromises();
    const socket = h.sockets[0]!; socket.open(); socket.receive(h.heartbeat()); await flushPromises();
    const row = h.store.snapshot!.symbols[0]!;
    h.api.getDashboard.mockImplementation(() => new Promise(() => {}));
    const frame = h.heartbeat("2026-09-14T10:10:17+08:00"); frame.runtimeStatus.mode = "STANDBY"; frame.runtimeStatus.reasonCode = "SESSION_BREAK";
    for (const scope of frame.runtimeStatus.scopes) if (scope.kind === "PLAN") scope.readOnly = true;
    expect(isHeartbeat(frame)).toBe(true); socket.receive(frame);
    expect(h.api.getDashboard).toHaveBeenCalledTimes(3); expect(h.store.isActionable(row, "risk")).toBe(true);
    h.monitor.stop();
  });
  it("loads a validated snapshot before opening its exact replay cursor", async () => {
    const h = setup(); h.monitor.start(); expect(h.sockets).toHaveLength(0); await flushPromises();
    expect(h.sockets[0]?.url).toBe("ws://127.0.0.1:32109/ws/v1/monitor?after=7&monitorContractVersion=2");
    h.sockets[0]!.open(); h.sockets[0]!.receive(h.heartbeat()); expect(h.store.transport).toBe("LIVE");
    h.monitor.stop();
  });
  it("updates standby mode/progress in place without reconnecting or changing decision data", async () => {
    const h = setup(); h.monitor.start(); await flushPromises(); const snapshot = h.store.snapshot;
    const frame = h.heartbeat(); frame.runtimeStatus.reasonCode = "SESSION_BREAK";
    h.sockets[0]!.open(); h.sockets[0]!.receive(frame); await flushPromises();
    expect(h.store.runtimeStatus?.reasonCode).toBe("SESSION_BREAK"); expect(h.store.snapshot).toBe(snapshot);
    expect(h.api.getDashboard).toHaveBeenCalledTimes(1); expect(h.sockets).toHaveLength(1); h.monitor.stop();
  });
  it("does not let duplicate heartbeats extend the 40-second transport deadline", async () => {
    const h = setup(); h.monitor.start(); await flushPromises(); const socket = h.sockets[0]!; socket.open(); socket.receive(h.heartbeat());
    await vi.advanceTimersByTimeAsync(20_000); socket.receive(h.heartbeat()); await vi.advanceTimersByTimeAsync(20_000);
    expect(h.store.transport).not.toBe("LIVE"); expect(socket.readyState).toBe(3); h.monitor.stop();
  });
  it("refreshes state-risk validity on a new heartbeat while retaining the compatible socket", async () => {
    const h = setup(valid(explicitDashboard())); h.monitor.start(); await flushPromises(); const socket = h.sockets[0]!; socket.open();
    const updated = valid(explicitDashboard()); updated.observedAt = "2026-09-14T10:10:16.000000+08:00"; updated.symbols[0]!.observedAt = updated.observedAt;
    h.api.getDashboard.mockResolvedValueOnce(updated); socket.receive(h.heartbeat()); await flushPromises();
    expect(h.api.getDashboard).toHaveBeenCalledTimes(2); expect(h.sockets).toHaveLength(1); expect(socket.readyState).toBe(1); h.monitor.stop();
  });
  it("replaces generation only through a fresh snapshot and cancels protocol epoch", async () => {
    const h = setup(); h.monitor.start(); await flushPromises(); const epoch = h.protocol.epoch;
    const updated = valid(); updated.runtimeGeneration = "00000000-0000-4000-8000-000000000009";
    h.api.getDashboard.mockResolvedValueOnce(updated);
    h.sockets[0]!.receive({ ...h.heartbeat(), runtimeGeneration: updated.runtimeGeneration }); await flushPromises();
    expect(h.protocol.epoch).toBeGreaterThan(epoch); expect(h.store.snapshot?.runtimeGeneration).toBe(updated.runtimeGeneration); expect(h.sockets).toHaveLength(2); h.monitor.stop();
  });
  it("rejects protocol mismatch as terminal without reconnecting", async () => {
    const h = setup(); h.monitor.start(); await flushPromises(); h.sockets[0]!.close(1008, "MONITOR_CONTRACT_MISMATCH");
    await vi.advanceTimersByTimeAsync(120_000); expect(h.store.transport).toBe("RELOAD_REQUIRED"); expect(h.api.getDashboard).toHaveBeenCalledTimes(1); h.monitor.stop();
  });
  it("recovers a backward observation through a new snapshot time baseline", async () => {
    const h = setup(); h.monitor.start(); await flushPromises(); h.sockets[0]!.open(); h.sockets[0]!.receive(h.heartbeat());
    const updated = valid(); updated.observedAt = "2026-09-14T10:10:10.000000+08:00"; h.api.getDashboard.mockResolvedValueOnce(updated);
    h.sockets[0]!.receive(h.heartbeat(updated.observedAt)); await flushPromises();
    expect(h.store.observedAt).toBe(updated.observedAt); expect(h.sockets).toHaveLength(2); h.monitor.stop();
  });
  it("bounds a pending snapshot to 20 seconds and aborts it", async () => {
    const h = setup(); let signal: AbortSignal | undefined;
    h.api.getDashboard.mockImplementationOnce((...args: unknown[]) => { signal = args[0] as AbortSignal; return new Promise(() => {}); });
    h.monitor.start(); await vi.advanceTimersByTimeAsync(20_000); expect(signal?.aborted).toBe(true); expect(h.store.transport).not.toBe("LIVE"); h.monitor.stop();
  });
});
