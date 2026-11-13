import { computed, onScopeDispose, readonly, shallowRef, toValue, watch, type MaybeRefOrGetter } from "vue";
import { ApiClientError } from "../api/transport";
import { createPlanReadinessApi, type ReadinessAssessment, type ReadinessContext } from "../api/planReadiness";

export function usePlanReadiness(input: MaybeRefOrGetter<ReadinessContext | null>) {
  const api = createPlanReadinessApi();
  const phase = shallowRef<"IDLE" | "LOADING" | "CURRENT" | "OBSERVED" | "STALE" | "ERROR">("IDLE");
  const assessment = shallowRef<ReadinessAssessment | null>(null);
  const error = shallowRef("");
  let generation = 0, stopped = false;
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let monotonicDeadline: number | null = null;
  const key = () => JSON.stringify(toValue(input));
  function clear() {
    generation++; controller?.abort(); controller = null;
    clearTimeout(timer); timer = undefined; monotonicDeadline = null; assessment.value = null; error.value = "";
  }
  function expire() { clear(); phase.value = "STALE"; }
  function checkExpiry() {
    const value = assessment.value;
    if (value?.freshUntil && (Date.parse(value.freshUntil) <= Date.now() ||
        monotonicDeadline !== null && performance.now() >= monotonicDeadline)) {
      expire();
    }
  }
  function resumed() { checkExpiry(); }
  async function refresh() {
    if (stopped) return;
    clear();
    const context = toValue(input);
    if (!context) { phase.value = "IDLE"; return; }
    const captured = { ...context }, expectedKey = key(), expectedGeneration = generation;
    const requestStarted = performance.now();
    const active = new AbortController(); controller = active; phase.value = "LOADING";
    const current = () => !stopped && expectedGeneration === generation && !active.signal.aborted && expectedKey === key();
    try {
      const value = await api.get(captured.planVersionId, active.signal);
      if (!current()) return;
      const actual = value.snapshot.context;
      if (actual.contentHash !== captured.contentHash || actual.sourceHash !== captured.sourceHash ||
          actual.reviewReceiptHash !== captured.reviewReceiptHash ||
          captured.coverageHash !== undefined && actual.coverageHash !== captured.coverageHash) {
        throw new Error("BINDING_CHANGED");
      }
      assessment.value = value;
      if (value.freshUntil === null) phase.value = "OBSERVED";
      else {
        const budget = Math.min(Date.parse(value.freshUntil) - Date.now(),
          Date.parse(value.freshUntil) - Date.parse(value.snapshot.computedAt) - (performance.now() - requestStarted));
        monotonicDeadline = performance.now() + Math.max(0, budget);
        phase.value = "CURRENT"; checkExpiry();
        // This original elapsed-time budget cannot be extended by a wall-clock rollback.
        if (assessment.value) timer = setTimeout(() => { if (current()) expire(); },
          Math.min(2_147_483_647, Math.max(0, budget)));
      }
    } catch (cause) {
      if (!current()) return;
      assessment.value = null; phase.value = "ERROR";
      error.value = cause instanceof Error && cause.message === "BINDING_CHANGED"
        ? "当前保存版本或审核依据已变化，请重新加载计划。"
        : cause instanceof ApiClientError && cause.code === "NOT_FOUND"
          ? "此计划版本已不存在，请重新加载计划。" : "暂时无法读取监控就绪状态，请重试。";
    } finally { if (current()) controller = null; }
  }
  watch(key, () => { void refresh(); }, { immediate: true, flush: "sync" });
  document.addEventListener("visibilitychange", resumed); window.addEventListener("pageshow", resumed);
  onScopeDispose(() => {
    stopped = true; clear(); document.removeEventListener("visibilitychange", resumed); window.removeEventListener("pageshow", resumed);
  });
  return { phase: readonly(phase), assessment: readonly(assessment), error: readonly(error),
    current: computed(() => phase.value === "CURRENT"), refresh };
}
