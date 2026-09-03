import { onBeforeUnmount, onMounted, shallowReadonly, shallowRef } from "vue";

import type { PlanVersionPage, PlanVersionSummary } from "../api/generated";
import { createPlanApi, type PlanApi } from "../api/plans";

export type BacktestPlanVersionState = "IDLE" | "LOADING" | "READY" | "EMPTY" | "FAILED";

export interface UseBacktestPlanVersionsOptions {
  readonly api?: PlanApi;
}

const PAGE_LIMIT = 20;

export function useBacktestPlanVersions(options: UseBacktestPlanVersionsOptions = {}) {
  const api = options.api ?? createPlanApi();
  const page = shallowRef<PlanVersionPage | null>(null);
  const selectedVersion = shallowRef<PlanVersionSummary | null>(null);
  const state = shallowRef<BacktestPlanVersionState>("IDLE");
  const errorMessage = shallowRef<string | null>(null);

  let mounted = false;
  let requestController: AbortController | null = null;
  let requestGeneration = 0;

  async function load(offset: number): Promise<void> {
    requestGeneration += 1;
    const generation = requestGeneration;
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    state.value = "LOADING";
    errorMessage.value = null;
    try {
      const response = await api.listPlanVersions(
        { canActivate: true, limit: PAGE_LIMIT, offset },
        { signal: controller.signal },
      );
      if (!mounted || controller.signal.aborted || generation !== requestGeneration) return;
      page.value = response;
      if (selectedVersion.value !== null) {
        selectedVersion.value =
          response.items?.find((item) => item.id === selectedVersion.value?.id) ??
          selectedVersion.value;
      }
      state.value = (response.items?.length ?? 0) === 0 && response.total === 0 ? "EMPTY" : "READY";
    } catch {
      if (!mounted || controller.signal.aborted || generation !== requestGeneration) return;
      state.value = "FAILED";
      errorMessage.value = "计划版本暂不可用，请稍后重试。";
    } finally {
      if (requestController === controller) requestController = null;
    }
  }

  function selectVersion(versionId: string): PlanVersionSummary | null {
    if (versionId.length === 0) {
      selectedVersion.value = null;
      return null;
    }
    const selected = page.value?.items?.find((item) => item.id === versionId) ?? null;
    if (selected !== null) selectedVersion.value = selected;
    return selected;
  }

  function nextPage(): Promise<void> {
    const current = page.value;
    if (
      state.value === "LOADING" ||
      current === null ||
      current.offset + current.limit >= current.total
    ) {
      return Promise.resolve();
    }
    return load(current.offset + current.limit);
  }

  function previousPage(): Promise<void> {
    const current = page.value;
    if (state.value === "LOADING" || current === null || current.offset === 0) {
      return Promise.resolve();
    }
    return load(Math.max(0, current.offset - current.limit));
  }

  function retry(): Promise<void> {
    return state.value === "LOADING" ? Promise.resolve() : load(page.value?.offset ?? 0);
  }

  onMounted(() => {
    mounted = true;
    void load(0);
  });

  onBeforeUnmount(() => {
    mounted = false;
    requestGeneration += 1;
    requestController?.abort();
    requestController = null;
  });

  return {
    errorMessage: shallowReadonly(errorMessage),
    nextPage,
    page: shallowReadonly(page),
    previousPage,
    retry,
    selectVersion,
    selectedVersion: shallowReadonly(selectedVersion),
    state: shallowReadonly(state),
  } as const;
}
