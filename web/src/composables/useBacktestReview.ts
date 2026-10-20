import { computed, nextTick, onScopeDispose, shallowRef, toValue, watch, type MaybeRefOrGetter } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";
import type { BacktestReviewContext } from "../api/generated";
import { createBacktestReviewApi, validReviewCursor, validReviewSelection,
  type BacktestReviewApi, type ReviewRelation, type ReviewSelection } from "../api/backtestReview";

const selectionKeys = ["fillId", "eventId", "sequence"] as const;
const reviewKeys = [...selectionKeys, "relation", "reviewCursor"];

export function useBacktestReview(options: {
  runId: MaybeRefOrGetter<string | null>;
  enabled: MaybeRefOrGetter<boolean>;
  api?: BacktestReviewApi;
}) {
  const route = useRoute(), router = useRouter();
  const api = options.api ?? createBacktestReviewApi();
  const context = shallowRef<BacktestReviewContext | null>(null);
  const loading = shallowRef(false), error = shallowRef<string | null>(null);
  let controller: AbortController | null = null;
  let generation = 0;
  let trigger: HTMLElement | null = null;
  const selection = computed(() => {
    const keys = selectionKeys.filter(key => route.query[key] !== undefined);
    if (keys.length !== 1) return null;
    const key = keys[0]!;
    const raw = route.query[key];
    if (typeof raw !== "string" || key === "sequence" && !/^[1-9]\d*$/.test(raw)) return null;
    const value = { [key]: key === "sequence" ? Number(raw) : raw };
    return validReviewSelection(value) ? value : null;
  });
  const relation = computed<ReviewRelation>(() => route.query.relation === "EFFECTS" ? "EFFECTS" : "CAUSES");
  const cursor = computed(() => typeof route.query.reviewCursor === "string" ? route.query.reviewCursor : null);
  const selected = computed(() => reviewKeys.some(key => route.query[key] !== undefined));
  const urlError = computed(() => selected.value && (selection.value === null ||
    route.query.relation !== undefined && !["CAUSES", "EFFECTS"].includes(String(route.query.relation)) ||
    Array.isArray(route.query.relation) || route.query.reviewCursor !== undefined && !validReviewCursor(route.query.reviewCursor))
    ? "原因定位链接无效，请关闭后重新选择记录。" : null);

  function queryWithoutReview(): LocationQueryRaw {
    const query = { ...route.query };
    for (const key of reviewKeys) delete query[key];
    return query;
  }
  async function open(value: ReviewSelection) {
    trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    await router.push({ path: route.path, query: { ...queryWithoutReview(), ...value } });
  }
  async function close() {
    await router.push({ path: route.path, query: queryWithoutReview() });
    await nextTick();
    if (trigger?.isConnected) trigger.focus();
    else document.querySelector<HTMLElement>('[aria-label="回测结果资源"] a[aria-current="page"]')?.focus();
  }
  async function changeRelation(value: ReviewRelation) {
    if (!selection.value) return;
    await router.push({ path: route.path, query: { ...queryWithoutReview(), ...selection.value, relation: value } });
  }
  async function nextPage() {
    if (context.value?.nextCursor) await router.push({ path: route.path,
      query: { ...route.query, reviewCursor: context.value.nextCursor } });
  }
  async function load() {
    controller?.abort();
    const current = ++generation;
    context.value = null; error.value = null; loading.value = false;
    const runId = toValue(options.runId);
    if (!toValue(options.enabled) || !runId || !selection.value || urlError.value) return;
    const active = new AbortController(); controller = active;
    loading.value = true;
    try {
      const response = await api.getContext(runId, {
        selector: selection.value, relation: relation.value, limit: 20,
        ...(cursor.value ? { cursor: cursor.value } : {}),
      }, active.signal);
      if (current !== generation || active.signal.aborted) return;
      if (response.runId !== runId) throw new Error("review identity mismatch");
      context.value = response;
    } catch {
      if (current !== generation || active.signal.aborted) return;
      error.value = "无法读取这条记录的原因，请重试或重新选择记录。";
    } finally {
      if (current === generation) loading.value = false;
    }
  }
  watch([() => toValue(options.runId), () => toValue(options.enabled), () => JSON.stringify(selection.value),
    relation, cursor, urlError], load, { immediate: true });
  onScopeDispose(() => { generation++; controller?.abort(); });
  return { context, loading, error: computed(() => urlError.value ?? error.value), selected,
    open, close, changeRelation, nextPage, refresh: load };
}
