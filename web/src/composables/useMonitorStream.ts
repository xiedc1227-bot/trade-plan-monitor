import { computed, onMounted, onUnmounted, shallowRef } from "vue";
import type { ComputedRef } from "vue";

import { createApiClient } from "../api/client";
import type { ApiClient } from "../api/client";
import { useMonitorStore } from "../stores/monitor";
import type { MonitorEventEnvelope } from "../stores/monitor";

const CONNECTION_TIMEOUT_MS = 20_000;
const HEARTBEAT_INTERVAL_MS = 20_000;
const HEARTBEAT_TIMEOUT_MS = HEARTBEAT_INTERVAL_MS * 2;
const SNAPSHOT_TIMEOUT_MS = 20_000;
const INITIAL_RECONNECT_DELAY_MS = 1_000;
const MAX_RECONNECT_DELAY_MS = 30_000;
const MAX_FRAME_CHARACTERS = 64 * 1024;
const NORMAL_CLOSE_CODE = 1000;
const SOCKET_CLOSING_STATE = 2;

export type MonitorStreamConnectionCode =
  | "CONNECTING"
  | "LIVE"
  | "STALE"
  | "DISCONNECTED";

export interface MonitorStreamConnectionState {
  readonly code: MonitorStreamConnectionCode;
  readonly label: string;
  readonly marker: string;
}

export interface UseMonitorStreamOptions {
  apiClient?: ApiClient;
  createSocket?: (url: string) => WebSocket;
  random?: () => number;
}

export interface UseMonitorStreamResult {
  connectionState: ComputedRef<MonitorStreamConnectionState>;
  recoverSnapshot(): void;
  start(): void;
  stop(): void;
}

const connectionStates = Object.freeze<Record<MonitorStreamConnectionCode, MonitorStreamConnectionState>>({
  CONNECTING: Object.freeze({ code: "CONNECTING", label: "正在同步实时数据", marker: "…" }),
  DISCONNECTED: Object.freeze({
    code: "DISCONNECTED",
    label: "连接中断，正在重试",
    marker: "×",
  }),
  LIVE: Object.freeze({ code: "LIVE", label: "实时连接", marker: "●" }),
  STALE: Object.freeze({
    code: "STALE",
    label: "数据可能已过期，正在恢复",
    marker: "!",
  }),
});

export function useMonitorStream(
  options: UseMonitorStreamOptions = {},
): UseMonitorStreamResult {
  const store = useMonitorStore();
  const apiClient = options.apiClient ?? createApiClient();
  const createSocket =
    options.createSocket ?? ((url: string) => new globalThis.WebSocket(url));
  const random = options.random ?? Math.random;
  const connectionCode = shallowRef<MonitorStreamConnectionCode>("CONNECTING");
  const connectionState = computed(() => connectionStates[connectionCode.value]);

  let activeSocket: WebSocket | null = null;
  let abortController: AbortController | null = null;
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let snapshotTimer: ReturnType<typeof setTimeout> | null = null;
  let retryAttempt = 0;
  let lifecycleRevision = 0;
  let started = false;

  function start(): void {
    if (started) {
      return;
    }
    started = true;
    lifecycleRevision += 1;
    connectionCode.value = "CONNECTING";
    beginSnapshot(lifecycleRevision);
  }

  function stop(): void {
    started = false;
    lifecycleRevision += 1;
    abortController?.abort();
    clearHeartbeatTimer();
    clearReconnectTimer();
    clearSnapshotTimer();
    closeActiveSocket();
    connectionCode.value = "DISCONNECTED";
  }

  function recoverSnapshot(): void {
    if (!started) {
      return;
    }
    lifecycleRevision += 1;
    connectionCode.value = store.hasSnapshot ? "STALE" : "CONNECTING";
    abortController?.abort();
    clearHeartbeatTimer();
    clearReconnectTimer();
    clearSnapshotTimer();
    closeActiveSocket();
    beginSnapshot(lifecycleRevision);
  }

  function beginSnapshot(revision: number): void {
    const controller = new AbortController();
    abortController = controller;
    clearSnapshotTimer();
    snapshotTimer = setTimeout(() => {
      snapshotTimer = null;
      if (!isCurrent(revision) || abortController !== controller) {
        return;
      }
      controller.abort();
      markUnavailable();
      scheduleReconnect("snapshot", revision);
    }, SNAPSHOT_TIMEOUT_MS);
    void apiClient
      .getDashboard({ signal: controller.signal })
      .then((snapshot) => {
        if (!isCurrent(revision) || controller.signal.aborted) {
          return;
        }
        clearSnapshotTimer();
        store.applySnapshot(snapshot);
        connect(store.sequence, revision);
      })
      .catch(() => {
        if (!isCurrent(revision) || controller.signal.aborted) {
          return;
        }
        clearSnapshotTimer();
        markUnavailable();
        scheduleReconnect("snapshot", revision);
      });
  }

  function connect(after: number, revision: number): void {
    if (!isCurrent(revision)) {
      return;
    }
    clearHeartbeatTimer();
    closeActiveSocket();
    connectionCode.value = "CONNECTING";
    let socket: WebSocket;
    try {
      socket = createSocket(monitorSocketUrl(after));
    } catch {
      markUnavailable();
      scheduleReconnect("socket", revision);
      return;
    }
    activeSocket = socket;

    socket.addEventListener("open", () => {
      if (!isActiveSocket(socket, revision)) {
        return;
      }
      connectionCode.value = "CONNECTING";
      armSocketTimeout(socket, revision, HEARTBEAT_TIMEOUT_MS);
    });
    socket.addEventListener("message", (message) => {
      if (!isActiveSocket(socket, revision)) {
        return;
      }
      handleMessage(socket, revision, message);
    });
    socket.addEventListener("error", () => disconnect(socket, revision));
    socket.addEventListener("close", () => disconnect(socket, revision));
    armSocketTimeout(socket, revision, CONNECTION_TIMEOUT_MS);
  }

  function handleMessage(socket: WebSocket, revision: number, message: MessageEvent): void {
    const frame = parseFrame(message.data);
    if (isHeartbeatFrame(frame)) {
      if (frame.sequence !== store.sequence) {
        store.requestSnapshotRecovery("SERVER_REQUIRED", frame.sequence);
        recoverSnapshot();
        return;
      }
      armSocketTimeout(socket, revision, HEARTBEAT_TIMEOUT_MS);
      retryAttempt = 0;
      connectionCode.value = store.connectionStatus === "CONNECTED" ? "LIVE" : "STALE";
      return;
    }
    if (isSnapshotRequiredFrame(frame)) {
      store.requestSnapshotRecovery("SERVER_REQUIRED", frame.sequence);
      recoverSnapshot();
      return;
    }
    if (frame === null) {
      store.requestSnapshotRecovery("INVALID_EVENT");
      recoverSnapshot();
      return;
    }

    let result;
    try {
      result = store.applyEvent(frame as unknown as MonitorEventEnvelope);
    } catch {
      store.requestSnapshotRecovery("INVALID_EVENT");
      recoverSnapshot();
      return;
    }
    if (result.status === "rejected") {
      return;
    }
    recoverSnapshot();
  }

  function disconnect(socket: WebSocket, revision: number): void {
    if (!isActiveSocket(socket, revision)) {
      return;
    }
    activeSocket = null;
    clearHeartbeatTimer();
    markUnavailable();
    scheduleReconnect("socket", revision);
  }

  function armSocketTimeout(socket: WebSocket, revision: number, timeoutMs: number): void {
    clearHeartbeatTimer();
    heartbeatTimer = setTimeout(() => {
      heartbeatTimer = null;
      if (!isActiveSocket(socket, revision)) {
        return;
      }
      activeSocket = null;
      socket.close(NORMAL_CLOSE_CODE);
      markUnavailable();
      scheduleReconnect("socket", revision);
    }, timeoutMs);
  }

  function scheduleReconnect(kind: "snapshot" | "socket", revision: number): void {
    if (!isCurrent(revision) || reconnectTimer !== null) {
      return;
    }
    const delay = reconnectDelay(retryAttempt, random());
    retryAttempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (!isCurrent(revision)) {
        return;
      }
      if (kind === "snapshot") {
        lifecycleRevision += 1;
        beginSnapshot(lifecycleRevision);
        return;
      }
      connect(store.sequence, revision);
    }, delay);
  }

  function markUnavailable(): void {
    connectionCode.value = store.hasSnapshot ? "STALE" : "DISCONNECTED";
  }

  function isCurrent(revision: number): boolean {
    return started && revision === lifecycleRevision;
  }

  function isActiveSocket(socket: WebSocket, revision: number): boolean {
    return isCurrent(revision) && activeSocket === socket;
  }

  function closeActiveSocket(): void {
    const socket = activeSocket;
    activeSocket = null;
    if (socket !== null && socket.readyState < SOCKET_CLOSING_STATE) {
      socket.close(NORMAL_CLOSE_CODE);
    }
  }

  function clearHeartbeatTimer(): void {
    if (heartbeatTimer !== null) {
      clearTimeout(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function clearReconnectTimer(): void {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function clearSnapshotTimer(): void {
    if (snapshotTimer !== null) {
      clearTimeout(snapshotTimer);
      snapshotTimer = null;
    }
  }

  onMounted(start);
  onUnmounted(stop);

  return Object.freeze({ connectionState, recoverSnapshot, start, stop });
}

function monitorSocketUrl(after: number): string {
  const url = new URL("/ws/v1/monitor", globalThis.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("after", String(after));
  return url.toString();
}

function reconnectDelay(attempt: number, randomValue: number): number {
  const exponential = Math.min(
    MAX_RECONNECT_DELAY_MS,
    INITIAL_RECONNECT_DELAY_MS * 2 ** Math.min(attempt, 10),
  );
  const boundedRandom = Number.isFinite(randomValue)
    ? Math.min(1, Math.max(0, randomValue))
    : 0.5;
  const jitter = 0.8 + boundedRandom * 0.4;
  return Math.min(MAX_RECONNECT_DELAY_MS, Math.round(exponential * jitter));
}

function parseFrame(value: unknown): Record<string, unknown> | null {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > MAX_FRAME_CHARACTERS
  ) {
    return null;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isHeartbeatFrame(value: Record<string, unknown> | null): value is {
  sequence: number;
  type: "heartbeat";
} {
  return (
    value !== null &&
    hasExactKeys(value, ["sequence", "type"]) &&
    value.type === "heartbeat" &&
    isSafeSequence(value.sequence)
  );
}

function isSnapshotRequiredFrame(value: Record<string, unknown> | null): value is {
  reason: "REPLAY_UNAVAILABLE";
  sequence: number;
  type: "snapshot.required";
} {
  return (
    value !== null &&
    hasExactKeys(value, ["reason", "sequence", "type"]) &&
    value.type === "snapshot.required" &&
    value.reason === "REPLAY_UNAVAILABLE" &&
    isSafeSequence(value.sequence)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key));
}

function isSafeSequence(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
