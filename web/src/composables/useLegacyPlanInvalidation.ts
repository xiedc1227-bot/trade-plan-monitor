import { computed, onMounted, onUnmounted, shallowReadonly, shallowRef } from "vue";

import type { LegacyPlanApi } from "../api/legacyPlans";
import type { LegacyPlanPreviewResponse } from "../api/generated";

export function useLegacyPlanInvalidation(api: LegacyPlanApi, onCompleted: () => void) {
  const preview = shallowRef<LegacyPlanPreviewResponse | null>(null);
  const loading = shallowRef(false);
  const submitting = shallowRef(false);
  const confirming = shallowRef(false);
  const acknowledged = shallowRef(false);
  const completed = shallowRef(false);
  const error = shallowRef<string | null>(null);
  const canSubmit = computed(() => confirming.value && acknowledged.value && !submitting.value);
  let requestGeneration = 0;
  let controller: AbortController | null = null;

  async function refresh(): Promise<void> {
    controller?.abort();
    const activeController = new AbortController();
    controller = activeController;
    const generation = ++requestGeneration;
    loading.value = true;
    error.value = null;
    confirming.value = false;
    acknowledged.value = false;
    try {
      const response = await api.getPreview({ signal: activeController.signal });
      if (generation !== requestGeneration || activeController.signal.aborted) return;
      preview.value = response;
    } catch {
      if (generation !== requestGeneration || activeController.signal.aborted) return;
      preview.value = null;
      error.value = "无法读取旧计划清单，请刷新后重试。";
    } finally {
      if (generation === requestGeneration && !activeController.signal.aborted) loading.value = false;
    }
  }

  function openConfirmation(): void {
    if (!preview.value?.available || completed.value) return;
    confirming.value = true;
    acknowledged.value = false;
  }

  function cancelConfirmation(): void {
    confirming.value = false;
    acknowledged.value = false;
  }

  async function confirm(): Promise<void> {
    const fingerprint = preview.value?.fingerprint;
    if (!canSubmit.value || typeof fingerprint !== "string") return;
    submitting.value = true;
    error.value = null;
    try {
      await api.invalidate(fingerprint);
      completed.value = true;
      confirming.value = false;
      preview.value = null;
      onCompleted();
    } catch {
      await refresh();
      error.value = preview.value?.available === false
        ? "当前已无待作废计划；请求可能已完成。请重启监控核对状态。"
        : "无法确认作废结果。请重新核对清单后再确认。";
    } finally {
      submitting.value = false;
    }
  }

  onMounted(() => { void refresh(); });
  onUnmounted(() => { controller?.abort(); });

  return {
    preview: shallowReadonly(preview),
    loading: shallowReadonly(loading),
    submitting: shallowReadonly(submitting),
    confirming: shallowReadonly(confirming),
    acknowledged,
    completed: shallowReadonly(completed),
    error: shallowReadonly(error),
    canSubmit,
    refresh,
    openConfirmation,
    cancelConfirmation,
    confirm,
  };
}
