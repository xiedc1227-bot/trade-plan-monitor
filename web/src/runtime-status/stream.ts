import type { RuntimeHeartbeatFrame, RuntimeStatusView } from "../api/generated-runtime-status";
import { shanghaiDateTimeKey } from "../api/shanghaiTime";
import { isMonitorEventEnvelope } from "../stores/monitor";
import type { RuntimeApi } from "./client";
import type { MonitorProtocol } from "./protocol";
import type { useRuntimeMonitorStore } from "./store";
import { equalJson, isRecord } from "./values";
import { isHeartbeat, isSnapshotRequired } from "./validators";

interface Options {
  api: Pick<RuntimeApi, "getDashboard">;
  protocol: MonitorProtocol;
  store: ReturnType<typeof useRuntimeMonitorStore>;
  origin: string;
  createSocket?: (url: string) => WebSocket;
  now?: () => number;
  random?: () => number;
}

export function createRuntimeMonitor({ api, protocol, store, origin, createSocket = (url) => new WebSocket(url), now = () => performance.now(), random = Math.random }: Options) {
  const timers: Partial<Record<"socket" | "snapshot" | "retry" | "expiry", ReturnType<typeof setTimeout>>> = {};
  let running = false;
  let socket: WebSocket | null = null;
  let pending: AbortController | null = null;
  let requestRevision = 0;
  let reconnectAttempt = 0;
  let lastHeartbeat: RuntimeHeartbeatFrame | null = null;
  let lastResume = now();
  let silenceDueAt: number | null = null;

  function clearTimer(kind: keyof typeof timers): void { if (timers[kind] !== undefined) clearTimeout(timers[kind]); delete timers[kind]; }
  function closeSocket(): void { const previous = socket; socket = null; silenceDueAt = null; clearTimer("socket"); lastHeartbeat = null; previous?.close(1000); }
  function cancelSnapshot(): void { requestRevision += 1; pending?.abort(); pending = null; clearTimer("snapshot"); }
  function active(): boolean { return running && protocol.state !== "RELOAD_REQUIRED"; }

  function start(): void {
    if (running || protocol.state === "RELOAD_REQUIRED") return;
    running = true; store.setTransport("CONNECTING");
    window.addEventListener("pageshow", resume); document.addEventListener("visibilitychange", resume);
    refresh();
  }

  function stop(): void {
    running = false; cancelSnapshot(); closeSocket(); clearTimer("retry"); clearTimer("expiry");
    protocol.invalidate(); store.invalidatePresentation();
    if (protocol.state !== "RELOAD_REQUIRED") store.setTransport("DISCONNECTED");
    window.removeEventListener("pageshow", resume); document.removeEventListener("visibilitychange", resume);
  }

  function reloadRequired(): void {
    protocol.requireReload(); stop(); store.setTransport("RELOAD_REQUIRED"); store.setError("应用版本已变化，请重新加载页面。");
  }

  function recover(resetObservation = false): void {
    if (!active()) return;
    store.invalidatePresentation(); protocol.invalidate(); cancelSnapshot(); closeSocket(); clearTimer("retry");
    store.setTransport("RECONNECTING"); refresh(resetObservation);
  }

  function scheduleRetry(): void {
    if (!active() || timers.retry !== undefined) return;
    const delay = Math.min(30_000, 1000 * 2 ** Math.min(reconnectAttempt++, 5)) * (0.75 + Math.max(0, Math.min(1, random())) * 0.25);
    timers.retry = setTimeout(() => { delete timers.retry; refresh(); }, delay);
  }

  function refresh(resetObservation = false): void {
    if (!active() || pending !== null) return;
    const controller = new AbortController(); pending = controller;
    const revision = ++requestRevision; const sentAt = now();
    timers.snapshot = setTimeout(() => {
      if (revision !== requestRevision) return;
      cancelSnapshot(); closeSocket(); protocol.invalidate(); store.invalidatePresentation(); store.setTransport("RECONNECTING");
      store.setError("监控快照读取超时，正在重新连接。"); scheduleRetry();
    }, 20_000);
    void api.getDashboard(controller.signal).then((value) => {
      if (!active() || revision !== requestRevision || controller.signal.aborted) return;
      const previous = store.snapshot;
      const changedStream = previous !== null && (previous.sequence !== value.sequence || previous.runtimeGeneration !== value.runtimeGeneration);
      if (!store.applySnapshot(value, sentAt, now(), resetObservation)) { scheduleRetry(); return; }
      if (changedStream) { protocol.invalidate(); closeSocket(); }
      clearTimer("retry"); reconnectAttempt = 0;
      armExpiry();
      if (socket === null) connect();
    }).catch(() => {
      if (protocol.state === "RELOAD_REQUIRED") { reloadRequired(); return; }
      if (!active() || revision !== requestRevision || controller.signal.aborted) return;
      store.invalidatePresentation(); store.setError("监控快照暂不可用，已撤销当前提醒展示。");
      if (socket === null) store.setTransport("RECONNECTING");
      scheduleRetry();
    }).finally(() => {
      if (revision === requestRevision) { pending = null; clearTimer("snapshot"); }
    });
  }

  function connect(): void {
    if (!active() || !store.snapshot) return;
    const url = new URL("/ws/v1/monitor", origin); url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("after", String(store.snapshot.sequence)); url.searchParams.set("monitorContractVersion", "2");
    store.setTransport("CONNECTING");
    let candidate: WebSocket;
    try { candidate = createSocket(url.toString()); } catch { store.setTransport("DISCONNECTED"); scheduleRetry(); return; }
    socket = candidate; lastHeartbeat = null;
    candidate.addEventListener("open", () => { if (candidate === socket) armSilence(candidate, 40_000); });
    candidate.addEventListener("message", (event) => { if (active() && candidate === socket) receive(event.data); });
    candidate.addEventListener("close", (event) => {
      if (candidate !== socket) return;
      if (event.code === 1008 && event.reason === "MONITOR_CONTRACT_MISMATCH") { reloadRequired(); return; }
      disconnect();
    });
    candidate.addEventListener("error", () => { if (candidate === socket) disconnect(); });
    armSilence(candidate, 20_000);
  }

  function armSilence(candidate: WebSocket, duration: number): void {
    silenceDueAt = now() + duration;
    clearTimer("socket"); timers.socket = setTimeout(() => { if (candidate === socket) disconnect(); }, duration);
  }

  function disconnect(): void {
    closeSocket(); cancelSnapshot(); protocol.invalidate(); store.invalidatePresentation(); store.setTransport("RECONNECTING"); scheduleRetry();
  }

  function receive(raw: unknown): void {
    let frame: unknown;
    try { if (typeof raw !== "string" || raw.length > 64 * 1024) throw new Error(); frame = JSON.parse(raw); }
    catch { recover(); return; }
    if (isRecord(frame) && (frame.type === "heartbeat" || frame.type === "snapshot.required") && frame.monitorContractVersion !== 2) { reloadRequired(); return; }
    if (isHeartbeat(frame)) { acceptHeartbeat(frame); return; }
    if (isSnapshotRequired(frame)) { recover(); return; }
    if (!isMonitorEventEnvelope(frame) || !isRecord(frame)) { recover(); return; }
    const sequence = frame.sequence as number;
    if (sequence <= (store.snapshot?.sequence ?? 0)) return;
    recover();
  }

  function acceptHeartbeat(frame: RuntimeHeartbeatFrame): void {
    const snapshot = store.snapshot;
    if (!snapshot || frame.sequence !== snapshot.sequence || frame.runtimeGeneration !== snapshot.runtimeGeneration) { recover(); return; }
    if (store.observedAt !== null && shanghaiDateTimeKey(frame.observedAt) < shanghaiDateTimeKey(store.observedAt)) { recover(true); return; }
    if (lastHeartbeat && equalJson(lastHeartbeat, frame)) return;
    const previousStatus = store.runtimeStatus;
    lastHeartbeat = frame; if (socket) armSilence(socket, 40_000); store.setTransport("LIVE"); reconnectAttempt = 0;
    store.applyObservation(frame);
    const affected = changedPlans(previousStatus, frame.runtimeStatus);
    if (frame.runtimeStatus.lifecycle !== "RUNNING" || ["RUNTIME_FAULT", "STORAGE_UNAVAILABLE"].includes(frame.runtimeStatus.reasonCode ?? "") ||
      ["STARTING", "STALLED", "STOPPED"].includes(frame.runtimeStatus.coordinator.state)) {
      store.invalidatePresentation(); refresh();
    } else if (affected.length) { store.invalidatePresentation(affected); refresh(); }
    else if (planReadOnlyChanged(previousStatus, frame.runtimeStatus)) refresh();
    else if (snapshot.symbols.some((row) => row.availability === "CURRENT" && (row.planFamily === "LEGACY_LOW_BUY"
      ? row.currentActionable && row.actionableUntil === null
      : row.planFamily === "CONDITION_PLAN" ? row.currentActionable : row.ruleEligibility.some((rule) => rule.currentActionable && rule.action === "RISK_ALERT")))) refresh();
    armExpiry();
  }

  function armExpiry(): void {
    clearTimer("expiry");
    const deadline = store.nextDeadline;
    if (deadline === null || !active()) return;
    timers.expiry = setTimeout(() => {
      delete timers.expiry; if (store.expire(now())) refresh(); armExpiry();
    }, Math.min(2_147_483_647, Math.max(0, deadline - now())));
  }

  function resume(): void {
    if (!active()) return;
    const current = now();
    if (current < lastResume) { store.invalidatePresentation(); recover(true); }
    else if (silenceDueAt !== null && current >= silenceDueAt) disconnect();
    else if (store.expire(current)) refresh();
    lastResume = current; armExpiry();
  }

  function navigation(): void { protocol.invalidate(); cancelSnapshot(); store.invalidatePresentation(); if (active()) refresh(); }
  return { start, stop, refresh: () => refresh(), recover, reloadRequired, resume, navigation };
}

function changedPlans(previous: RuntimeStatusView | null, next: RuntimeStatusView): string[] {
  if (previous === null) return [];
  const prior = new Map(previous.scopes.filter((scope) => scope.kind === "PLAN").map((scope) => [scope.symbol, scope]));
  const changed = new Set<string>();
  for (const scope of next.scopes) {
    if (scope.kind !== "PLAN") continue;
    const old = prior.get(scope.symbol); prior.delete(scope.symbol);
    if (!old || !equalJson([old.planVersionId, old.planHash, old.activationRevision, old.status, old.reasonCode, old.requiredTarget, old.progress],
      [scope.planVersionId, scope.planHash, scope.activationRevision, scope.status, scope.reasonCode, scope.requiredTarget, scope.progress])) changed.add(scope.symbol);
  }
  for (const symbol of prior.keys()) changed.add(symbol);
  return [...changed];
}

function planReadOnlyChanged(previous: RuntimeStatusView | null, next: RuntimeStatusView): boolean {
  const prior = new Map(previous?.scopes.filter(scope => scope.kind === "PLAN").map(scope => [scope.scopeKey, scope.readOnly]));
  return next.scopes.some(scope => scope.kind === "PLAN" && prior.get(scope.scopeKey) !== scope.readOnly);
}
