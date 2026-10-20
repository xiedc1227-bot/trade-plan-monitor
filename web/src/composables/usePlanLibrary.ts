import { computed, onBeforeUnmount, onMounted, readonly, shallowRef } from "vue";
import { createPlanLibraryApi, type PlanLibraryApi } from "../api/planLibrary";
import { ApiClientError } from "../api/transport";
import type { CollectionPreparationFrozenView, PreparedPlanCompositionInput, ReviewedPlanLibraryItem } from "../api/generated-runtime-status";
import { planTimelinePath } from "../components/backtests/planLibraryPresentation";

/** Explicit timeline endpoint; composition is an internal new-run snapshot only. */
export function usePlanLibrary(api: PlanLibraryApi = createPlanLibraryApi()) {
  const items = shallowRef<ReviewedPlanLibraryItem[]>([]);
  const endpointId = shallowRef("");
  const libraryReady = shallowRef(false);
  const error = shallowRef<string | null>(null);
  const loading = shallowRef(false);
  const saving = shallowRef(false);
  const uncertain = shallowRef(false);
  const composition = shallowRef<CollectionPreparationFrozenView | null>(null);
  let pending: { command: PreparedPlanCompositionInput; key: string } | null = null;
  let frozenPath = "";
  let controller: AbortController | null = null;
  let disposed = false;
  const path = computed(() => planTimelinePath(items.value, endpointId.value));
  const endpoint = computed(() => items.value.find(item => item.preparationId === endpointId.value));
  const reviewedBase = computed(() => endpoint.value ? {
    preparation_id: endpoint.value.preparationId, manifest_hash: endpoint.value.manifestHash,
  } : null);
  const needsBase = computed(() => !libraryReady.value || !!endpointId.value && !!path.value.error);
  const locked = computed(() => saving.value || uncertain.value);
  function chooseEndpoint(id: string): boolean {
    if (locked.value || loading.value) return false;
    if (id) {
      const candidate = planTimelinePath(items.value, id);
      if (candidate.error) { error.value = candidate.error; return false; }
    }
    if (endpointId.value !== id) { composition.value = null; frozenPath = ""; }
    endpointId.value = id; error.value = null;
    return true;
  }
  async function refresh() {
    if (loading.value || locked.value || disposed) return;
    loading.value = true;
    const request = new AbortController(); controller = request;
    try {
      const loaded: ReviewedPlanLibraryItem[] = [];
      let offset = 0;
      for (;;) {
        const page = await api.list(offset, request.signal);
        if (disposed || request.signal.aborted) return;
        if (page.offset !== offset || !page.items.length && offset < page.total) throw new Error("Incomplete library page");
        loaded.push(...page.items); offset += page.items.length;
        if (offset >= page.total) break;
      }
      if (new Set(loaded.map(item => item.preparationId)).size !== loaded.length) throw new Error("Duplicate library entries");
      items.value = loaded; libraryReady.value = true; error.value = null;
    } catch { if (!disposed) error.value = "无法读取已审核计划，请刷新重试。"; }
    finally { loading.value = false; }
  }
  async function compose(): Promise<CollectionPreparationFrozenView | null> {
    if (loading.value || saving.value || disposed) return null;
    if (!pending) {
      if (path.value.error) { error.value = path.value.error; return null; }
      const plans = path.value.items.map(item => ({ preparation_id: item.preparationId, manifest_hash: item.manifestHash }));
      if (composition.value && frozenPath === JSON.stringify(plans)) return composition.value;
      pending = { key: crypto.randomUUID(), command: { preparation_id: crypto.randomUUID(), plans } };
    }
    saving.value = true; error.value = null;
    const request = new AbortController(); controller = request;
    try {
      const value = await api.compose(pending.command, pending.key, request.signal);
      if (disposed) return null;
      frozenPath = JSON.stringify(pending.command.plans);
      composition.value = value; pending = null; uncertain.value = false;
      return value;
    } catch (failure) {
      if (disposed) return null;
      if (failure instanceof ApiClientError && failure.status >= 400 && failure.status < 500) {
        pending = null; uncertain.value = false;
        error.value = failure.details.some(detail => detail.code === "REVIEWED_RISK_SCOPE_RECHECK_REQUIRED")
          ? "所选旧版本的风险退出范围需要重新提取核对，暂不能用于新回测。历史结果仍可查看，无需补填原文已有的信息。"
          : failure.details.some(detail => detail.code === "PREDECESSOR_SELECTION_REQUIRED")
          ? "时间线的上一份已审核版本无法核对，请刷新后检查前序关系。"
          : "无法准备回测：请检查时间线是否为同一股票、日期是否递增，以及前序版本是否一致。";
      } else { uncertain.value = true; error.value = "回测准备结果尚未确认，请使用同一请求安全重试。"; }
      return null;
    } finally { saving.value = false; }
  }
  onMounted(refresh);
  onBeforeUnmount(() => { disposed = true; controller?.abort(); });
  return { items: readonly(items), endpointId: readonly(endpointId), endpoint, path, reviewedBase, needsBase, chooseEndpoint,
    error: readonly(error), loading: readonly(loading), saving: readonly(saving), uncertain: readonly(uncertain),
    locked, composition: readonly(composition), refresh, compose };
}
