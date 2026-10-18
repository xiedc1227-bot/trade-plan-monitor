import { computed, onBeforeUnmount, onMounted, readonly, shallowRef } from "vue";
import { createPlanLibraryApi, type PlanLibraryApi } from "../api/planLibrary";
import { ApiClientError } from "../api/transport";
import type { CollectionPreparationFrozenView, PreparedPlanCompositionInput, ReviewedPlanLibraryItem } from "../api/generated-runtime-status";

export function usePlanLibrary(api: PlanLibraryApi = createPlanLibraryApi()) {
  const items = shallowRef<ReviewedPlanLibraryItem[]>([]);
  const selected = shallowRef<string[]>([]);
  const baseId = shallowRef("");
  const baseChosen = shallowRef(false);
  const libraryReady = shallowRef(false);
  const error = shallowRef<string | null>(null);
  const loading = shallowRef(false);
  const saving = shallowRef(false);
  const uncertain = shallowRef(false);
  const composition = shallowRef<CollectionPreparationFrozenView | null>(null);
  let pending: { command: PreparedPlanCompositionInput; key: string } | null = null;
  let controller: AbortController | null = null;
  let disposed = false;
  const base = computed(() => items.value.find(item => item.preparationId === baseId.value));
  const reviewedBase = computed(() => base.value ? {
    preparation_id: base.value.preparationId, manifest_hash: base.value.manifestHash,
  } : null);
  const needsBase = computed(() => !libraryReady.value || !baseChosen.value || !!baseId.value && !base.value);
  const locked = computed(() => saving.value || uncertain.value);
  function chooseBase(id: string) {
    if (locked.value || loading.value) return;
    baseId.value = id; baseChosen.value = true;
  }
  function defaultBase() {
    if (baseChosen.value) return;
    if (!items.value.length) { baseId.value = ""; baseChosen.value = true; return; }
    if (new Set(items.value.map(item => item.symbol)).size !== 1) return;
    const newest = [...items.value].sort((a, b) => b.effectiveTradeDate.localeCompare(a.effectiveTradeDate));
    if (newest[1]?.effectiveTradeDate === newest[0]?.effectiveTradeDate) return;
    baseId.value = newest[0]!.preparationId; baseChosen.value = true;
  }
  async function prepareNext(preferredId?: string) {
    if (loading.value || locked.value) return;
    baseId.value = preferredId ?? ""; baseChosen.value = !!preferredId;
    await refresh();
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
        if (!page.items.length && offset < page.total) throw new Error("Incomplete library page");
        loaded.push(...page.items); offset += page.items.length;
        if (offset >= page.total) break;
      }
      if (new Set(loaded.map(item => item.preparationId)).size !== loaded.length) throw new Error("Duplicate library entries");
      items.value = loaded; libraryReady.value = true; error.value = null;
      defaultBase();
    } catch { if (!disposed) error.value = "无法读取已审核计划，请刷新重试。"; }
    finally { loading.value = false; }
  }
  function toggle(id: string) {
    if (locked.value) return;
    selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id];
    composition.value = null;
  }
  async function compose() {
    if (loading.value || saving.value || disposed) return;
    if (!pending) {
      if (!selected.value.length || selected.value.length > 256) return;
      const chosen = items.value.filter(item => selected.value.includes(item.preparationId));
      if (chosen.length !== selected.value.length) { error.value = "所选版本不可用，请刷新计划库。"; return; }
      pending = { key: crypto.randomUUID(), command: { preparation_id: crypto.randomUUID(), plans: chosen.map(item => ({ preparation_id: item.preparationId, manifest_hash: item.manifestHash })) } };
    }
    saving.value = true; error.value = null;
    const request = new AbortController(); controller = request;
    try {
      const value = await api.compose(pending.command, pending.key, request.signal);
      if (disposed) return;
      composition.value = value; pending = null; uncertain.value = false;
    } catch (failure) {
      if (disposed) return;
      if (failure instanceof ApiClientError && failure.status >= 400 && failure.status < 500) {
        pending = null; uncertain.value = false;
        error.value = failure.details.some(detail => detail.code === "REVIEWED_RISK_SCOPE_RECHECK_REQUIRED")
          ? "所选旧版本的风险退出范围需要重新提取核对，暂不能用于新回测。历史结果仍可查看，无需补填原文已有的信息。"
          : failure.details.some(detail => detail.code === "PREDECESSOR_SELECTION_REQUIRED")
          ? "请同时选中本份计划关联的上一份已审核版本，且该版本须是日期顺序中的前一份。"
          : "无法组合：请检查是否为同一标的、日期是否重复，以及前序版本是否一致。";
      } else { uncertain.value = true; error.value = "组合结果尚未确认，请使用同一请求安全重试。"; }
    } finally { saving.value = false; }
  }
  onMounted(refresh);
  onBeforeUnmount(() => { disposed = true; controller?.abort(); });
  return { items: readonly(items), selected: readonly(selected), baseId: readonly(baseId), reviewedBase, needsBase, chooseBase, prepareNext,
    error: readonly(error), loading: readonly(loading), saving: readonly(saving), uncertain: readonly(uncertain),
    locked, composition: readonly(composition), refresh, toggle, compose };
}
