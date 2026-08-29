import {
  onBeforeUnmount,
  onMounted,
  readonly,
  shallowRef,
  toValue,
  watch,
  type DeepReadonly,
  type MaybeRefOrGetter,
} from "vue";

import type {
  BacktestDetailPage,
  BacktestEquitySeries,
  BacktestFillPage,
  BacktestResultAvailabilityView,
  BacktestRunView,
} from "../api/generated";
import { createBacktestApi, type BacktestApi } from "../api/backtests";

export type BacktestSummaryRequestState = "IDLE" | "LOADING" | "READY" | "FAILED";
export type BacktestResultRequestState =
  | "IDLE"
  | "LOADING"
  | "READY"
  | "EMPTY"
  | "UNAVAILABLE"
  | "FAILED";
export type BacktestResultTab = "summary" | "fills" | "details" | "equity";
export type BacktestDetailKind = BacktestDetailPage["kind"];

export interface UseBacktestResultsOptions {
  readonly api?: BacktestApi;
  readonly cursor: MaybeRefOrGetter<string | null>;
  readonly detailKind: MaybeRefOrGetter<BacktestDetailKind>;
  readonly enabled: MaybeRefOrGetter<boolean>;
  readonly runId: MaybeRefOrGetter<string | null>;
  readonly selectedTab: MaybeRefOrGetter<BacktestResultTab>;
}

const RESULT_PAGE_LIMIT = 100;
const EQUITY_POINT_LIMIT = 2_000;

export function useBacktestResults(options: UseBacktestResultsOptions) {
  const api = options.api ?? createBacktestApi();
  const summary = shallowRef<BacktestRunView | null>(null);
  const summaryState = shallowRef<BacktestSummaryRequestState>("IDLE");
  const summaryError = shallowRef<string | null>(null);
  const fillsPage = shallowRef<BacktestFillPage | null>(null);
  const fillsState = shallowRef<BacktestResultRequestState>("IDLE");
  const fillsError = shallowRef<string | null>(null);
  const detailPage = shallowRef<BacktestDetailPage | null>(null);
  const detailState = shallowRef<BacktestResultRequestState>("IDLE");
  const detailError = shallowRef<string | null>(null);
  const equitySeries = shallowRef<BacktestEquitySeries | null>(null);
  const equityState = shallowRef<BacktestResultRequestState>("IDLE");
  const equityError = shallowRef<string | null>(null);

  let summaryController: AbortController | null = null;
  let fillsController: AbortController | null = null;
  let detailController: AbortController | null = null;
  let equityController: AbortController | null = null;
  let summaryGeneration = 0;
  let fillsGeneration = 0;
  let detailGeneration = 0;
  let equityGeneration = 0;
  let mounted = false;

  function abortSummary(): void {
    summaryGeneration += 1;
    summaryController?.abort();
    summaryController = null;
  }

  function abortFills(): void {
    fillsGeneration += 1;
    fillsController?.abort();
    fillsController = null;
  }

  function abortDetails(): void {
    detailGeneration += 1;
    detailController?.abort();
    detailController = null;
  }

  function abortEquity(): void {
    equityGeneration += 1;
    equityController?.abort();
    equityController = null;
  }

  function clearFills(): void {
    abortFills();
    fillsPage.value = null;
    fillsState.value = "IDLE";
    fillsError.value = null;
  }

  function clearDetails(): void {
    abortDetails();
    detailPage.value = null;
    detailState.value = "IDLE";
    detailError.value = null;
  }

  function clearEquity(): void {
    abortEquity();
    equitySeries.value = null;
    equityState.value = "IDLE";
    equityError.value = null;
  }

  function clearSelectedResources(): void {
    clearFills();
    clearDetails();
    clearEquity();
  }

  async function loadSummary(): Promise<void> {
    const runId = toValue(options.runId);
    if (!mounted || !toValue(options.enabled) || runId === null) return;
    abortSummary();
    clearSelectedResources();
    const activeGeneration = summaryGeneration;
    const controller = new AbortController();
    summaryController = controller;
    summary.value = null;
    summaryState.value = "LOADING";
    summaryError.value = null;
    try {
      const response = await api.getRun(runId, { signal: controller.signal });
      if (!currentSummaryRequest(controller, activeGeneration)) return;
      if (response.runId !== runId) throw new Error("run identity mismatch");
      summary.value = response;
      summaryState.value = "READY";
    } catch {
      if (!currentSummaryRequest(controller, activeGeneration)) return;
      summary.value = null;
      summaryState.value = "FAILED";
      summaryError.value = "回测结果暂不可用，请稍后重试";
    } finally {
      if (summaryController === controller) summaryController = null;
    }
  }

  async function loadFills(): Promise<void> {
    const runId = toValue(options.runId);
    if (!readyFor("fills") || runId === null) return;
    abortFills();
    const activeGeneration = fillsGeneration;
    const controller = new AbortController();
    fillsController = controller;
    fillsPage.value = null;
    fillsState.value = "LOADING";
    fillsError.value = null;
    const cursor = toValue(options.cursor);
    try {
      const response = await api.listFills(
        runId,
        { ...(cursor === null ? {} : { cursor }), limit: RESULT_PAGE_LIMIT },
        { signal: controller.signal },
      );
      if (!currentFillsRequest(controller, activeGeneration)) return;
      if (response.items.some((item) => item.runId !== runId)) {
        throw new Error("fill identity mismatch");
      }
      fillsPage.value = response;
      fillsState.value = response.items.length === 0 ? "EMPTY" : "READY";
    } catch {
      if (!currentFillsRequest(controller, activeGeneration)) return;
      fillsPage.value = null;
      fillsState.value = "FAILED";
      fillsError.value = "模拟成交暂不可用，请稍后重试";
    } finally {
      if (fillsController === controller) fillsController = null;
    }
  }

  async function loadDetails(): Promise<void> {
    const runId = toValue(options.runId);
    const kind = toValue(options.detailKind);
    if (!readyFor("details") || runId === null) return;
    const summaryAvailability = detailAvailability(summary.value, kind);
    if (summaryAvailability !== "AVAILABLE") {
      detailState.value = "UNAVAILABLE";
      return;
    }
    abortDetails();
    const activeGeneration = detailGeneration;
    const controller = new AbortController();
    detailController = controller;
    detailPage.value = null;
    detailState.value = "LOADING";
    detailError.value = null;
    const cursor = toValue(options.cursor);
    try {
      const response = await api.listDetails(
        runId,
        {
          ...(cursor === null ? {} : { cursor }),
          kind,
          limit: RESULT_PAGE_LIMIT,
        },
        { signal: controller.signal },
      );
      if (!currentDetailRequest(controller, activeGeneration)) return;
      if (
        response.kind !== kind ||
        response.filters.kind !== kind ||
        response.items.some((item) => item.runId !== runId || item.kind !== kind)
      ) {
        throw new Error("detail identity mismatch");
      }
      detailPage.value = response;
      detailState.value =
        response.availability !== "AVAILABLE"
          ? "UNAVAILABLE"
          : response.items.length === 0
            ? "EMPTY"
            : "READY";
    } catch {
      if (!currentDetailRequest(controller, activeGeneration)) return;
      detailPage.value = null;
      detailState.value = "FAILED";
      detailError.value = "结果明细暂不可用，请稍后重试";
    } finally {
      if (detailController === controller) detailController = null;
    }
  }

  async function loadEquity(): Promise<void> {
    const runId = toValue(options.runId);
    if (!readyFor("equity") || runId === null) return;
    if (summary.value?.availability.equitySeries !== "AVAILABLE") {
      equityState.value = "UNAVAILABLE";
      return;
    }
    abortEquity();
    const activeGeneration = equityGeneration;
    const controller = new AbortController();
    equityController = controller;
    equitySeries.value = null;
    equityState.value = "LOADING";
    equityError.value = null;
    try {
      const response = await api.getEquitySeries(runId, { signal: controller.signal });
      if (!currentEquityRequest(controller, activeGeneration)) return;
      if (
        response.items.length > EQUITY_POINT_LIMIT ||
        response.items.some((item) => item.runId !== runId)
      ) {
        throw new Error("equity identity mismatch");
      }
      equitySeries.value = response;
      equityState.value =
        response.availability !== "AVAILABLE"
          ? "UNAVAILABLE"
          : response.items.length === 0
            ? "EMPTY"
            : "READY";
    } catch {
      if (!currentEquityRequest(controller, activeGeneration)) return;
      equitySeries.value = null;
      equityState.value = "FAILED";
      equityError.value = "权益序列暂不可用，请稍后重试";
    } finally {
      if (equityController === controller) equityController = null;
    }
  }

  function currentSummaryRequest(
    controller: AbortController,
    generation: number,
  ): boolean {
    return mounted && !controller.signal.aborted && generation === summaryGeneration;
  }

  function currentFillsRequest(
    controller: AbortController,
    generation: number,
  ): boolean {
    return (
      mounted &&
      !controller.signal.aborted &&
      generation === fillsGeneration &&
      readyFor("fills")
    );
  }

  function currentDetailRequest(
    controller: AbortController,
    generation: number,
  ): boolean {
    return (
      mounted &&
      !controller.signal.aborted &&
      generation === detailGeneration &&
      readyFor("details")
    );
  }

  function currentEquityRequest(
    controller: AbortController,
    generation: number,
  ): boolean {
    return (
      mounted &&
      !controller.signal.aborted &&
      generation === equityGeneration &&
      readyFor("equity")
    );
  }

  function readyFor(tab: Exclude<BacktestResultTab, "summary">): boolean {
    return (
      mounted &&
      toValue(options.enabled) &&
      toValue(options.runId) !== null &&
      summaryState.value === "READY" &&
      summary.value !== null &&
      toValue(options.selectedTab) === tab
    );
  }

  function reconcileSelectedResource(): void {
    clearSelectedResources();
    if (summaryState.value !== "READY" || summary.value === null) return;
    if (toValue(options.selectedTab) === "fills") void loadFills();
    else if (toValue(options.selectedTab) === "details") void loadDetails();
    else if (toValue(options.selectedTab) === "equity") void loadEquity();
  }

  function reconcileIdentity(): void {
    abortSummary();
    clearSelectedResources();
    summary.value = null;
    summaryError.value = null;
    summaryState.value =
      toValue(options.enabled) && toValue(options.runId) !== null ? "LOADING" : "IDLE";
    if (summaryState.value === "LOADING") void loadSummary();
  }

  watch(
    [() => toValue(options.runId), () => toValue(options.enabled)],
    ([nextRunId, nextEnabled], [previousRunId, previousEnabled]) => {
      if (mounted && (nextRunId !== previousRunId || nextEnabled !== previousEnabled)) {
        reconcileIdentity();
      }
    },
  );

  watch(
    [
      summaryState,
      () => toValue(options.selectedTab),
      () => toValue(options.detailKind),
      () => toValue(options.cursor),
    ],
    () => {
      if (mounted) reconcileSelectedResource();
    },
  );

  onMounted(() => {
    mounted = true;
    reconcileIdentity();
  });

  onBeforeUnmount(() => {
    mounted = false;
    abortSummary();
    clearSelectedResources();
  });

  return {
    detailError: readonly(detailError),
    detailPage: readonly(detailPage),
    detailState: readonly(detailState),
    equityError: readonly(equityError),
    equitySeries: readonly(equitySeries),
    equityState: readonly(equityState),
    fillsError: readonly(fillsError),
    fillsPage: readonly(fillsPage),
    fillsState: readonly(fillsState),
    refreshSelected: reconcileSelectedResource,
    refreshSummary: loadSummary,
    summary: readonly(summary),
    summaryError: readonly(summaryError),
    summaryState: readonly(summaryState),
  } as const;
}

export function detailAvailability(
  summary: DeepReadonly<BacktestRunView> | null,
  kind: BacktestDetailKind,
): BacktestResultAvailabilityView[keyof BacktestResultAvailabilityView] | null {
  if (summary === null) return null;
  if (kind === "DECISION") return summary.availability.decisionDetails;
  if (kind === "SIGNAL") return summary.availability.signalDetails;
  return summary.availability.executionOutcomeDetails;
}
