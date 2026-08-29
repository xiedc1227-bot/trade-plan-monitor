import {
  onBeforeUnmount,
  onMounted,
  readonly,
  shallowRef,
  toValue,
  watch,
  type MaybeRefOrGetter,
} from "vue";

import type { BacktestRunView } from "../api/generated";
import { createBacktestApi, type BacktestApi } from "../api/backtests";

export type BacktestSummaryRequestState = "IDLE" | "LOADING" | "READY" | "FAILED";

export interface UseBacktestResultsOptions {
  readonly api?: BacktestApi;
  readonly enabled: MaybeRefOrGetter<boolean>;
  readonly runId: MaybeRefOrGetter<string | null>;
}

export function useBacktestResults(options: UseBacktestResultsOptions) {
  const api = options.api ?? createBacktestApi();
  const summary = shallowRef<BacktestRunView | null>(null);
  const summaryState = shallowRef<BacktestSummaryRequestState>("IDLE");
  const summaryError = shallowRef<string | null>(null);

  let summaryController: AbortController | null = null;
  let summaryGeneration = 0;
  let mounted = false;

  function abortSummary(): void {
    summaryGeneration += 1;
    summaryController?.abort();
    summaryController = null;
  }

  async function loadSummary(): Promise<void> {
    const runId = toValue(options.runId);
    if (!mounted || !toValue(options.enabled) || runId === null) return;
    abortSummary();
    const activeGeneration = summaryGeneration;
    const controller = new AbortController();
    summaryController = controller;
    summary.value = null;
    summaryState.value = "LOADING";
    summaryError.value = null;
    try {
      const response = await api.getRun(runId, { signal: controller.signal });
      if (
        !mounted ||
        controller.signal.aborted ||
        activeGeneration !== summaryGeneration
      ) {
        return;
      }
      if (response.runId !== runId) throw new Error("run identity mismatch");
      summary.value = response;
      summaryState.value = "READY";
    } catch {
      if (
        !mounted ||
        controller.signal.aborted ||
        activeGeneration !== summaryGeneration
      ) {
        return;
      }
      summary.value = null;
      summaryState.value = "FAILED";
      summaryError.value = "回测结果暂不可用，请稍后重试";
    } finally {
      if (summaryController === controller) summaryController = null;
    }
  }

  function reconcileIdentity(): void {
    abortSummary();
    summary.value = null;
    summaryError.value = null;
    summaryState.value =
      toValue(options.enabled) && toValue(options.runId) !== null ? "LOADING" : "IDLE";
    if (summaryState.value === "LOADING") void loadSummary();
  }

  watch(
    [() => toValue(options.runId), () => toValue(options.enabled)],
    ([nextRunId, nextEnabled], [previousRunId, previousEnabled]) => {
      if (
        mounted &&
        (nextRunId !== previousRunId || nextEnabled !== previousEnabled)
      ) {
        reconcileIdentity();
      }
    },
  );

  onMounted(() => {
    mounted = true;
    reconcileIdentity();
  });

  onBeforeUnmount(() => {
    mounted = false;
    abortSummary();
  });

  return {
    refreshSummary: loadSummary,
    summary: readonly(summary),
    summaryError: readonly(summaryError),
    summaryState: readonly(summaryState),
  } as const;
}
