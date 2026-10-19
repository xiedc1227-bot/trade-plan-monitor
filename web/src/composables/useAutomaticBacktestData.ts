import { onBeforeUnmount, readonly, shallowRef, watch, type DeepReadonly } from "vue";
import type { BacktestApi } from "../api/backtests";
import type { BacktestDataSyncCommand, BacktestJobView, PreparedBacktestRunCommand,
  ScheduledPreparedBacktestRunCommand } from "../api/generated";
import { ApiClientError } from "../api/transport";
import { useBacktestJob } from "./useBacktestJob";

type PreparedCommand = PreparedBacktestRunCommand | ScheduledPreparedBacktestRunCommand;
type Phase = "IDLE" | "CHECKING" | "SYNCING" | "VERIFYING" | "READY" | "FAILED" | "CANCELLED";

/** One explicit start owns this sequence; reads and remounts never start downloads. */
export function useAutomaticBacktestData(options: { api: BacktestApi; createIdempotencyKey: () => string }) {
  const phase = shallowRef<Phase>("IDLE");
  const jobId = shallowRef<string | null>(null);
  const cancellationRequested = shallowRef(false);
  const jobState = useBacktestJob({ api: options.api, jobId });
  let controller: AbortController | null = null;
  let mounted = true;
  let cancelSent = false;
  let pendingSync: { command: BacktestDataSyncCommand; key: string } | null = null;

  function stopped() { return new DOMException("回测已取消，未继续提交回测。", "AbortError"); }
  function assertActive(signal: AbortSignal) {
    if (!mounted || signal.aborted || cancellationRequested.value) throw stopped();
  }

  watch([jobState.canCancel, cancellationRequested], ([available, requested]) => {
    if (available && requested && !cancelSent) { cancelSent = true; void jobState.cancel(); }
  });

  function waitForJob(signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      const finish = (error?: Error) => { stop(); signal.removeEventListener("abort", abort); error ? reject(error) : resolve(); };
      const abort = () => finish(stopped());
      const inspect = (job: DeepReadonly<BacktestJobView> | null) => {
        if (!job) return;
        if (job.jobId !== jobId.value || job.kind !== "DATA_SYNC") { finish(new Error("数据任务身份不匹配")); return; }
        if (!["COMPLETED", "FAILED", "CANCELLED"].includes(job.status)) return;
        if (cancellationRequested.value || job.status === "CANCELLED") { finish(stopped()); return; }
        if (job.status === "FAILED") { finish(new Error("历史数据自动补齐失败，请检查任务错误后重试回测。")); return; }
        finish();
      };
      const stop = watch(jobState.job, inspect);
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) abort(); else inspect(jobState.job.value);
    });
  }

  async function synchronize(signal: AbortSignal) {
    phase.value = "SYNCING";
    const intent = pendingSync!;
    let receipt;
    try { receipt = await options.api.syncData(intent.command, intent.key, { signal }); }
    catch (error) {
      if (!(error instanceof ApiClientError) || !["NETWORK_ERROR", "INVALID_RESPONSE", "SERVICE_UNAVAILABLE"].includes(error.code)) pendingSync = null;
      throw error;
    }
    if (!mounted || signal.aborted) throw stopped();
    pendingSync = null;
    jobId.value = receipt.body.jobId;
    await waitForJob(signal);
    assertActive(signal);
  }

  async function prepare(command: PreparedCommand): Promise<void> {
    const active = new AbortController(); controller = active;
    if (!pendingSync) cancellationRequested.value = false;
    cancelSent = false;
    try {
      // A lost mutation receipt must be reconciled with its original body/key first.
      if (pendingSync) await synchronize(active.signal);
      else {
        jobId.value = null;
        phase.value = "CHECKING";
        const check = await options.api.checkPreparedData(command, { signal: active.signal });
        assertActive(active.signal);
        if (!check.ready) {
          if (!check.syncScope) throw new Error(`历史数据暂不可用：${check.blockers.join("；")}`);
          pendingSync = { command: { scope: structuredClone(check.syncScope), refresh: false, allowNetwork: true },
            key: options.createIdempotencyKey() };
          await synchronize(active.signal);
        } else { phase.value = "READY"; return; }
      }
      assertActive(active.signal);
      phase.value = "VERIFYING";
      const verified = await options.api.checkPreparedData(command, { signal: active.signal });
      assertActive(active.signal);
      if (!verified.ready) throw new Error(`补齐后仍未通过数据验证：${verified.blockers.join("；")}`);
      phase.value = "READY";
    } catch (error) {
      phase.value = cancellationRequested.value || active.signal.aborted || error instanceof DOMException && error.name === "AbortError" ? "CANCELLED" : "FAILED";
      throw error;
    } finally { if (controller === active) controller = null; }
  }

  function cancel() {
    cancellationRequested.value = true;
    if (phase.value === "SYNCING" && jobState.canCancel.value && cancelSent) void jobState.cancel();
    if (phase.value !== "SYNCING") controller?.abort();
  }

  onBeforeUnmount(() => { mounted = false; controller?.abort(); });
  return { phase: readonly(phase), jobId: readonly(jobId), jobState, prepare, cancel,
    cancellationRequested: readonly(cancellationRequested) };
}
