import { computed, onBeforeUnmount, onMounted, shallowReadonly, shallowRef } from "vue";
import { createBacktestServiceApi, type BacktestServiceApi } from "../api/backtestService";
import { createBacktestApi, type BacktestApi } from "../api/backtests";
import { resolveApiFetch } from "../api/context";
import type { BacktestJobView, BacktestServiceRecoveryCommand, BacktestServiceStopCommand, BacktestServiceView } from "../api/generated";
import { ApiClientError } from "../api/transport";

export function useBacktestService(options: { api?: BacktestServiceApi; jobApi?: Pick<BacktestApi, "listJobs">; createKey?: () => string } = {}) {
  const api = options.api ?? createBacktestServiceApi();
  const jobs = options.jobApi ?? createBacktestApi(resolveApiFetch());
  const view = shallowRef<BacktestServiceView | null>(null);
  const pendingJob = shallowRef<BacktestJobView | null>(null);
  const selectionLoaded = shallowRef(false);
  const commandMessage = shallowRef<string | null>(null);
  const readMessage = shallowRef<string | null>(null);
  const pendingMessage = shallowRef<string | null>(null);
  const message = computed(() => commandMessage.value ?? readMessage.value ?? pendingMessage.value);
  const busy = shallowRef(false);
  const uncertain = shallowRef(false);
  const lastChecked = shallowRef<string | null>(null);
  let mounted = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let read: AbortController | null = null;
  let mutation: AbortController | null = null;
  let jobRead: AbortController | null = null;
  let generation = 0;
  let checkedPendingIdentity: string | null = null;
  let intent: { key: string; command: BacktestServiceRecoveryCommand | BacktestServiceStopCommand; stop: boolean } | null = null;
  const pendingIdentity = (value: BacktestServiceView) => JSON.stringify([value.epoch, value.revision, value.generation, value.state, value.authorizedJobIds]);
  const canRepair = computed(() => !busy.value && !uncertain.value && view.value?.epoch !== null && view.value?.physicallyDrained === true && ["DEGRADED", "STOPPED"].includes(view.value?.state ?? ""));
  function schedule() {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (!mounted || ["DISABLED", "STOPPED"].includes(view.value?.state ?? "")) return;
    const wait = view.value?.state === "DEGRADED" ? 30000 : ["STARTING", "RECOVERING", "STOPPING"].includes(view.value?.state ?? "") ? 1000 : 10000;
    timer = setTimeout(() => { timer = null; void refresh(); }, wait);
  }
  async function refresh() {
    if (!mounted || read !== null) return;
    const active = ++generation;
    const controller = new AbortController(); read = controller;
    try {
      const value = await api.getStatus({ signal: controller.signal });
      if (!mounted || controller.signal.aborted || active !== generation) return;
      view.value = value; readMessage.value = null; lastChecked.value = new Date().toLocaleTimeString("zh-CN");
      if (!value.canRead || value.authorizedJobIds.length > 0) {
        pendingJob.value = null; pendingMessage.value = null;
      }
      if (value.canRead && value.authorizedJobIds.length === 0 && !["STOPPING", "STOPPED"].includes(value.state) && checkedPendingIdentity !== pendingIdentity(value)) void loadPending(false);
    } catch {
      if (mounted && !controller.signal.aborted && active === generation) readMessage.value = "回测服务状态暂不可用，已保留当前页面；可返回监控页面。";
    } finally { if (read === controller) read = null; schedule(); }
  }
  async function loadPending(manual = true) {
    if (!mounted || jobRead !== null || busy.value || uncertain.value || !view.value?.canRead) return;
    const snapshot = view.value;
    const identity = pendingIdentity(snapshot);
    const controller = new AbortController(); jobRead = controller;
    try {
      const result = await jobs.listJobs({ status: ["QUEUED", "RUNNING", "CANCEL_REQUESTED"], limit: 1 }, { signal: controller.signal });
      if (!mounted || controller.signal.aborted || !view.value || pendingIdentity(view.value) !== identity) return;
      pendingJob.value = result.items.find(job => !snapshot.authorizedJobIds.includes(job.jobId)) ?? null;
      selectionLoaded.value = manual; pendingMessage.value = null; checkedPendingIdentity = identity;
    } catch (error) {
      // Metadata reads share a bounded slot; a passive check can wait for the next status poll.
      if (!manual && error instanceof ApiClientError && error.status === 503 && error.code === "SERVICE_UNAVAILABLE") return;
      if (mounted && !controller.signal.aborted && view.value && pendingIdentity(view.value) === identity) pendingMessage.value = "待恢复任务暂不可读取，请稍后重试查看；当前任务与输入已保留。";
    }
    finally { if (jobRead === controller) jobRead = null; }
  }
  async function send() {
    const saved = intent;
    if (!mounted || busy.value || saved === null) return;
    busy.value = true; commandMessage.value = null;
    const controller = new AbortController(); mutation = controller;
    try {
      if (saved.stop) await api.stop(saved.command, saved.key, { signal: controller.signal });
      else await api.recover(saved.command as BacktestServiceRecoveryCommand, saved.key, { signal: controller.signal });
      if (!mounted || controller.signal.aborted) return;
      intent = null; uncertain.value = false;
      commandMessage.value = "服务控制已接受，正在读取状态；需要重试原操作时，请使用原页面按钮。";
      pendingJob.value = null; selectionLoaded.value = false;
      await refresh();
    } catch (error) {
      if (!mounted || controller.signal.aborted) return;
      if (!(error instanceof ApiClientError) || error.status === 0 || error.status >= 500 || error.code === "INVALID_RESPONSE") {
        uncertain.value = true; commandMessage.value = "控制结果尚未确认，请使用同一请求安全重试。";
      } else { intent = null; uncertain.value = false; commandMessage.value = "服务状态已变化或请求未接受，请刷新状态后重新选择。"; await refresh(); }
    } finally { if (mutation === controller) mutation = null; busy.value = false; }
  }
  function begin(action: "STOP" | "RETRY_PREPARATION" | "RESUME_JOBS", selected?: string) {
    const value = view.value;
    if (busy.value || uncertain.value || value?.epoch == null || action === "RETRY_PREPARATION" && !canRepair.value ||
      action === "RESUME_JOBS" && (selected === undefined || selected !== pendingJob.value?.jobId)) return Promise.resolve();
    jobRead?.abort();
    const common = { epoch: value.epoch, expectedRevision: value.revision };
    const ids: string[] = action === "RESUME_JOBS" ? [selected!] : [];
    Object.freeze(ids);
    intent = { key: (options.createKey ?? (() => crypto.randomUUID()))(), stop: action === "STOP",
      command: action === "STOP" ? Object.freeze(common) : Object.freeze({ ...common, action, resumeJobIds: ids }) };
    return send();
  }
  onMounted(() => { mounted = true; void refresh(); });
  onBeforeUnmount(() => { mounted = false; generation += 1; if (timer !== null) clearTimeout(timer); read?.abort(); mutation?.abort(); jobRead?.abort(); });
  return { view: shallowReadonly(view), pendingJob: shallowReadonly(pendingJob), selectionLoaded: shallowReadonly(selectionLoaded),
    message: shallowReadonly(message), lastChecked: shallowReadonly(lastChecked), busy: shallowReadonly(busy), uncertain: shallowReadonly(uncertain),
    canRepair, refresh, loadPending, retryControl: send, retryPreparation: () => begin("RETRY_PREPARATION"),
    stop: () => begin("STOP"), resume: (selected: string) => begin("RESUME_JOBS", selected) };
}
