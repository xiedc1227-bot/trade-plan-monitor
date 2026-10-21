import { computed, onBeforeUnmount, onMounted, readonly, shallowRef, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import type { BacktestApi } from "../api/backtests";
import type { BacktestJobPage, BacktestJobView } from "../api/generated";
import { useBacktestReadFeedback } from "./useBacktestReadFeedback";
import { previousBacktestPage, rememberBacktestPage } from "./backtestNavigation";

const statuses: BacktestJobView["status"][] = ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "COMPLETED", "FAILED", "CANCELLED"];
const kinds: BacktestJobView["kind"][] = ["DATA_SYNC", "DATASET_VERIFY", "BACKTEST_RUN"];
export function useBacktestTasks(api: BacktestApi) {
  const route = useRoute(), router = useRouter();
  const page = shallowRef<BacktestJobPage | null>(null);
  const activeJobs = shallowRef<BacktestJobView[]>([]);
  const loading = shallowRef(false), error = shallowRef<string | null>(null);
  const feedback = useBacktestReadFeedback();
  const status = computed(() => statuses.find(s => s === route.query.status) ?? null);
  const kind = computed(() => kinds.find(k => k === route.query.kind) ?? null);
  const cursor = computed(() => typeof route.query.cursor === "string" ? route.query.cursor : null);
  const jobId = computed(() => typeof route.query.jobId === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(route.query.jobId) ? route.query.jobId : null);
  const scope = () => `jobs:${status.value}:${kind.value}`;
  const previous = computed(() => previousBacktestPage(scope(), cursor.value));
  let controller: AbortController | null = null, generation = 0, lastKey = "";
  async function refresh() {
    const query = { limit: 20, ...(status.value ? { status: [status.value] } : {}), ...(kind.value ? { kind: [kind.value] } : {}), ...(cursor.value ? { cursor: cursor.value } : {}) };
    const key = JSON.stringify(query), same = key === lastKey;
    lastKey = key; controller?.abort(); controller = new AbortController();
    const active = controller, current = ++generation;
    if (!same) page.value = null;
    loading.value = true; error.value = null;
    try {
      const [response, activePage] = await feedback.read(active.signal, signal => Promise.all([api.listJobs(query, { signal }), api.listJobs({ limit: 5, status: ["QUEUED", "RUNNING", "CANCEL_REQUESTED"] }, { signal })]));
      if (current === generation && !active.signal.aborted) { page.value = response; activeJobs.value = activePage.items; }
    } catch {
      if (current === generation && !active.signal.aborted) error.value = "任务记录读取失败，请重新读取；已有任务不会因此重新执行。";
    } finally { if (current === generation) loading.value = false; }
  }
  function navigate(extra: Record<string, string | null>) {
    const next = { ...route.query, view: "tasks", ...extra };
    return router.push({ path: "/backtests", query: next });
  }
  function nextPage() {
    if (!page.value?.nextCursor) return;
    rememberBacktestPage(scope(), cursor.value, page.value.nextCursor);
    return navigate({ cursor: page.value.nextCursor });
  }
  function previousPage() { if (previous.value !== undefined) return navigate({ cursor: previous.value }); }
  watch([status, kind, cursor], () => void refresh());
  onMounted(() => void refresh());
  onBeforeUnmount(() => { generation += 1; controller?.abort(); });
  return { activeJobs: readonly(activeJobs), page: readonly(page), loading: readonly(loading), error: readonly(error), feedback,
    status, kind, statuses, kinds, jobId, cursor, refresh, nextPage, previousPage,
    hasPrevious: computed(() => previous.value !== undefined), firstPage: () => navigate({ cursor: null }),
    filter: (status: string, kind: string) => navigate({ status: status || null, kind: kind || null, cursor: null }),
    select: (id: string | null) => navigate({ jobId: id }) };
}
