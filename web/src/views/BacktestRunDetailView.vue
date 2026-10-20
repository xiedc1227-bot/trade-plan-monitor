<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  shallowRef,
  watch,
} from "vue";
import {
  isNavigationFailure,
  NavigationFailureType,
  RouterLink,
  useRoute,
  useRouter,
  type LocationQueryRaw,
} from "vue-router";

import type { BacktestJobView } from "../api/generated";
import { createBacktestApi, type BacktestApi } from "../api/backtests";
import type { BacktestReviewApi } from "../api/backtestReview";
import { useBacktestReview } from "../composables/useBacktestReview";
import BacktestEvidencePanel from "../components/backtests/BacktestEvidencePanel.vue";
import BacktestOverview from "../components/backtests/BacktestOverview.vue";
import PlanExecutionDiagnostics from "../components/backtests/PlanExecutionDiagnostics.vue";
import BacktestDetailTable from "../components/backtests/BacktestDetailTable.vue";
import BacktestEquityTable from "../components/backtests/BacktestEquityTable.vue";
import BacktestFillTable from "../components/backtests/BacktestFillTable.vue";
import BacktestJobStatus from "../components/backtests/BacktestJobStatus.vue";
import BacktestMarketIndexPanel from "../components/backtests/BacktestMarketIndexPanel.vue";
import BacktestMetricsSummary from "../components/backtests/BacktestMetricsSummary.vue";
import BacktestProfitSummary from "../components/backtests/BacktestProfitSummary.vue";
import BacktestResultActions from "../components/backtests/BacktestResultActions.vue";
import MonitorLoopSummary from "../components/backtests/MonitorLoopSummary.vue";
import MonitorLoopTimeline from "../components/backtests/MonitorLoopTimeline.vue";
import { useBacktestJob } from "../composables/useBacktestJob";
import { useBacktestMarketIndexSeries } from "../composables/useMarketIndexSeries";
import {
  detailAvailability,
  useBacktestResults,
  type BacktestDetailKind,
  type BacktestResultTab,
} from "../composables/useBacktestResults";

interface Props {
  api?: BacktestApi;
  reviewApi?: BacktestReviewApi;
  createIdempotencyKey?: () => string;
}

interface ReadonlyResultPageFrame {
  readonly hasMore: boolean;
  readonly nextCursor: string | null;
}

const props = defineProps<Props>();
const BacktestEquityChart = defineAsyncComponent(
  () => import("../components/backtests/BacktestEquityChart.vue"),
);
const route = useRoute();
const router = useRouter();
const api = props.api ?? createBacktestApi();
const runtimeIdentityError = shallowRef<string | null>(null);
const resultUrlError = shallowRef<string | null>(null);
const completedJobAnnouncement = shallowRef("");
const announcedCompletedJobId = shallowRef<string | null>(null);
const announcedCompletedRunId = shallowRef<string | null>(null);

const RUN_ID_PATTERN = /^[0-9a-f]{64}$/;
const JOB_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;
const CURSOR_PATTERN = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const RESULT_TABS = new Set<BacktestResultTab>([
  "summary",
  "fills",
  "details",
  "equity",
  "market-index",
  "reasons",
  "provenance",
]);
const DETAIL_KIND_OPTIONS: readonly BacktestDetailKind[] = [
  "DECISION",
  "SIGNAL",
  "EXECUTION_OUTCOME",
] as const;
const DETAIL_KINDS = new Set<BacktestDetailKind>(DETAIL_KIND_OPTIONS);

let navigationGeneration = 0;

const runId = computed(() => {
  const value = route.params.runId;
  return typeof value === "string" && RUN_ID_PATTERN.test(value) ? value : null;
});
const hasJobIdentity = computed(() => route.query.jobId !== undefined);
const jobId = computed(() => {
  const value = route.query.jobId;
  return typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 128 &&
    JOB_ID_PATTERN.test(value)
    ? value
    : null;
});
const routeIdentityError = computed(() => {
  if (runId.value === null) return "运行标识无效，未读取任何回测结果";
  if (hasJobIdentity.value && jobId.value === null) {
    return "任务标识无效，未读取任何任务状态或回测结果";
  }
  return null;
});
const identityError = computed(
  () =>
    routeIdentityError.value ??
    runtimeIdentityError.value ??
    resultUrlError.value,
);
const requestedJobId = computed(() =>
  routeIdentityError.value === null &&
  runtimeIdentityError.value === null &&
  hasJobIdentity.value
    ? jobId.value
    : null,
);
function scalarResultQuery(key: "tab" | "kind" | "cursor"): string | null {
  const value = route.query[key];
  return typeof value === "string" ? value : null;
}

function validCursor(value: string): boolean {
  return value.length >= 3 && value.length <= 512 && CURSOR_PATTERN.test(value);
}

const selectedTab = computed<BacktestResultTab>(() => {
  const value = scalarResultQuery("tab");
  return value !== null && RESULT_TABS.has(value as BacktestResultTab)
    ? (value as BacktestResultTab)
    : "summary";
});
const selectedDetailKind = computed<BacktestDetailKind>(() => {
  const value = scalarResultQuery("kind");
  return value !== null && DETAIL_KINDS.has(value as BacktestDetailKind)
    ? (value as BacktestDetailKind)
    : "DECISION";
});
const selectedCursor = computed(() => {
  if (selectedTab.value !== "fills" && selectedTab.value !== "details") return null;
  const value = scalarResultQuery("cursor");
  return value !== null && validCursor(value) ? value : null;
});

function resultQuery(
  tab: BacktestResultTab,
  kind: BacktestDetailKind = selectedDetailKind.value,
  cursor: string | null = null,
): LocationQueryRaw {
  const query: LocationQueryRaw = { ...route.query, tab };
  delete query.jobId;
  delete query.kind;
  delete query.cursor;
  if (tab === "details") query.kind = kind;
  if ((tab === "fills" || tab === "details") && cursor !== null) query.cursor = cursor;
  return query;
}

const canonicalSelectedQuery = computed(() =>
  resultQuery(selectedTab.value, selectedDetailKind.value, selectedCursor.value),
);
const resultUrlCanonical = computed(() => {
  if (scalarResultQuery("tab") !== selectedTab.value) return false;
  if (
    selectedTab.value === "details" &&
    scalarResultQuery("kind") !== selectedDetailKind.value
  ) {
    return false;
  }
  if (selectedTab.value !== "details" && route.query.kind !== undefined) return false;
  if (
    selectedTab.value !== "fills" &&
    selectedTab.value !== "details" &&
    route.query.cursor !== undefined
  ) {
    return false;
  }
  if (
    (selectedTab.value === "fills" || selectedTab.value === "details") &&
    route.query.cursor !== undefined &&
    (typeof route.query.cursor !== "string" ||
      scalarResultQuery("cursor") !== selectedCursor.value)
  ) {
    return false;
  }
  return true;
});
const resultsEnabled = computed(
  () =>
    routeIdentityError.value === null &&
    runtimeIdentityError.value === null &&
    resultUrlError.value === null &&
    !hasJobIdentity.value &&
    resultUrlCanonical.value,
);

const jobState = useBacktestJob({
  api,
  ...(props.createIdempotencyKey === undefined
    ? {}
    : { createIdempotencyKey: props.createIdempotencyKey }),
  jobId: requestedJobId,
});
const results = useBacktestResults({
  api,
  cursor: selectedCursor,
  detailKind: selectedDetailKind,
  enabled: resultsEnabled,
  runId,
  selectedTab,
});
const loopRun = computed(() => results.summary.value !== null && "report" in results.summary.value ? results.summary.value : null);
const review = useBacktestReview({
  runId, enabled: () => resultsEnabled.value && loopRun.value !== null,
  ...(props.reviewApi ? { api: props.reviewApi } : {}),
});
const previousCursors = shallowRef<Record<string, string | null>>({});
const pageKey = (cursor: string | null) => `${runId.value}:${selectedTab.value}:${selectedDetailKind.value}:${cursor ?? ''}`;
const previousCursorKnown = computed(() => Object.hasOwn(previousCursors.value, pageKey(selectedCursor.value)));
const previousCursor = computed(() => previousCursors.value[pageKey(selectedCursor.value)] ?? null);
function rememberNextPage() {
  if (activePage.value?.nextCursor) previousCursors.value = {
    ...previousCursors.value, [pageKey(activePage.value.nextCursor)]: selectedCursor.value,
  };
}
async function navigateReviewTab(tab: "fills" | "reasons" | "provenance") {
  await router.push({ path: route.path, query: resultQuery(tab) });
}
const legacyRun = computed(() => results.summary.value !== null && !("report" in results.summary.value) ? results.summary.value : null);
const loopDetails = computed(() => results.detailPage.value?.items.filter(item => "event" in item) ?? []);
const marketIndexRequest = computed(() =>
  resultsEnabled.value &&
  results.summaryState.value === "READY" &&
  legacyRun.value !== null &&
  selectedTab.value === "market-index" &&
  runId.value !== null
    ? { limit: 512, runId: runId.value }
    : null,
);
const marketIndexSeries = useBacktestMarketIndexSeries({
  loader: ({ runId: requestedRunId, ...query }, signal) =>
    api.getMarketIndexSeries(requestedRunId, query, { signal }),
  query: marketIndexRequest,
});

async function openIndexDecisionDate(_tradeDate: string): Promise<void> {
  await router.push({
    path: route.path,
    query: resultQuery("details", "DECISION"),
  });
}

const activePage = computed<ReadonlyResultPageFrame | null>(() =>
  selectedTab.value === "fills"
    ? results.fillsPage.value
    : selectedTab.value === "details"
      ? results.detailPage.value
      : null,
);
const activeDetailAvailability = computed(() =>
  results.detailPage.value?.availability ??
  detailAvailability(results.summary.value, selectedDetailKind.value),
);
const detailAvailabilityCopy = computed(() => {
  if (activeDetailAvailability.value === "EXPIRED") {
    return "该明细已超过保留期，不能重建。";
  }
  if (activeDetailAvailability.value === "NOT_RECORDED") {
    return "本次运行未记录该明细，不会推测或补造。";
  }
  return "该明细可读取。";
});
const activeEquityAvailability = computed(
  () =>
    results.equitySeries.value?.availability ??
    results.summary.value?.availability.equitySeries ??
    null,
);
const equityAvailabilityCopy = computed(() => {
  if (activeEquityAvailability.value === "EXPIRED") {
    return "该权益序列已超过保留期，不能重建。";
  }
  if (activeEquityAvailability.value === "NOT_RECORDED") {
    return "本次运行未记录权益序列，不会推测或补造。";
  }
  return "该权益序列可读取。";
});

const matchingJob = computed<BacktestJobView | null>(() => {
  const current = jobState.job.value;
  return current !== null &&
    jobId.value !== null &&
    runId.value !== null &&
    current.jobId === jobId.value &&
    current.kind === "BACKTEST_RUN" &&
    current.runId === runId.value
    ? (current as unknown as BacktestJobView)
    : null;
});
const showJobStatus = computed(
  () =>
    routeIdentityError.value === null &&
    runtimeIdentityError.value === null &&
    hasJobIdentity.value,
);
const terminalRetryAvailable = computed(
  () =>
    matchingJob.value?.status === "FAILED" || matchingJob.value?.status === "CANCELLED",
);

function canonicalResultQuery(): LocationQueryRaw {
  const query = { ...route.query };
  delete query.jobId;
  return query;
}

async function canonicalizeCompletedJob(): Promise<void> {
  const activeGeneration = ++navigationGeneration;
  try {
    const failure = await router.replace({ path: route.path, query: canonicalResultQuery() });
    if (activeGeneration !== navigationGeneration) return;
    if (
      isNavigationFailure(failure) &&
      !isNavigationFailure(failure, NavigationFailureType.duplicated)
    ) {
      runtimeIdentityError.value =
        "无法切换到已完成结果，请返回运行记录后重新打开";
    }
  } catch {
    if (activeGeneration === navigationGeneration) {
      runtimeIdentityError.value =
        "无法切换到已完成结果，请返回运行记录后重新打开";
    }
  }
}

async function canonicalizeResultUrl(): Promise<void> {
  const activeGeneration = ++navigationGeneration;
  resultUrlError.value = null;
  try {
    const failure = await router.replace({
      path: route.path,
      query: canonicalSelectedQuery.value,
    });
    if (activeGeneration !== navigationGeneration) return;
    if (
      isNavigationFailure(failure) &&
      !isNavigationFailure(failure, NavigationFailureType.duplicated)
    ) {
      resultUrlError.value = "回测结果 URL 无法规范化，请返回运行记录后重新打开";
    }
  } catch {
    if (activeGeneration === navigationGeneration) {
      resultUrlError.value = "回测结果 URL 无法规范化，请返回运行记录后重新打开";
    }
  }
}

watch(
  [() => route.params.runId, () => route.query.jobId],
  () => {
    navigationGeneration += 1;
    runtimeIdentityError.value = null;
    resultUrlError.value = null;
    if (
      announcedCompletedRunId.value !== null &&
      (runId.value !== announcedCompletedRunId.value ||
        (jobId.value !== null && jobId.value !== announcedCompletedJobId.value))
    ) {
      completedJobAnnouncement.value = "";
      announcedCompletedJobId.value = null;
      announcedCompletedRunId.value = null;
    }
    reconcileJobIdentity(jobState.job.value);
  },
  { deep: true },
);

watch(
  () => route.query,
  () => {
    navigationGeneration += 1;
    resultUrlError.value = null;
    if (
      routeIdentityError.value === null &&
      runtimeIdentityError.value === null &&
      !hasJobIdentity.value &&
      !resultUrlCanonical.value
    ) {
      void canonicalizeResultUrl();
    }
  },
  { deep: true, immediate: true },
);

function reconcileJobIdentity(current: typeof jobState.job.value): void {
  const expectedJobId = jobId.value;
  const expectedRunId = runId.value;
  if (current === null || expectedJobId === null || expectedRunId === null) return;
  if (current.jobId !== expectedJobId) return;
  if (current.kind !== "BACKTEST_RUN" || current.runId !== expectedRunId) {
    runtimeIdentityError.value =
      "任务与运行标识不匹配，已停止读取任务状态和回测结果";
    return;
  }
  runtimeIdentityError.value = null;
  if (current.status === "COMPLETED") {
    if (
      announcedCompletedJobId.value !== current.jobId ||
      announcedCompletedRunId.value !== current.runId
    ) {
      completedJobAnnouncement.value = "任务已完成，已打开回测结果";
      announcedCompletedJobId.value = current.jobId;
      announcedCompletedRunId.value = current.runId;
    }
    void canonicalizeCompletedJob();
  }
}

watch(jobState.job, reconcileJobIdentity);

onBeforeUnmount(() => {
  navigationGeneration += 1;
});
</script>

<template>
  <div class="run-detail-view">
    <header class="run-detail-view__hero">
      <div>
        <h1>回测结果</h1>
        <p>仅展示服务端权威任务状态与已物化历史模拟结果。</p>
      </div>
    </header>

    <aside class="run-detail-view__boundary" aria-label="研究边界">
      本页仅供离线研究，不连接券商、不自动下单，也不复用实时监控状态。
    </aside>

    <p
      class="run-detail-view__visually-hidden"
      data-testid="completed-job-announcement"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {{ completedJobAnnouncement }}
    </p>

    <section
      v-if="identityError !== null"
      class="run-detail-view__error"
      data-testid="run-identity-error"
      role="alert"
      aria-labelledby="run-identity-error-title"
    >
      <h2 id="run-identity-error-title">无法确认运行身份</h2>
      <p>{{ identityError }}</p>
      <a href="/backtests" data-testid="back-to-run-history">返回运行记录</a>
    </section>

    <BacktestJobStatus
      v-else-if="showJobStatus"
      :cancellation-state="jobState.cancellationState.value"
      :error-message="jobState.errorMessage.value"
      :job="matchingJob"
      :request-state="jobState.requestState.value"
      @cancel="jobState.cancel"
      @refresh="jobState.refresh"
      @retry-cancellation="jobState.retryCancellation"
    />

    <p v-if="terminalRetryAvailable" class="run-detail-view__retry">
      本次任务未生成运行结果。
      <a href="/backtests/new">创建新的回测意图</a>
    </p>

    <div
      v-if="resultsEnabled && results.summaryState.value === 'LOADING'"
      class="run-detail-view__state"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      正在读取已物化回测结果…
    </div>

    <section
      v-else-if="resultsEnabled && results.summaryState.value === 'FAILED'"
      class="run-detail-view__error"
      role="alert"
      aria-labelledby="run-summary-error-title"
    >
      <h2 id="run-summary-error-title">回测结果读取失败</h2>
      <p>{{ results.summaryError.value }}</p>
      <button
        data-testid="refresh-run-summary"
        type="button"
        @click="results.refreshSummary"
      >
        重新读取回测结果
      </button>
    </section>

    <section
      v-else-if="
        resultsEnabled &&
        results.summaryState.value === 'READY' &&
        results.summary.value !== null
      "
      class="run-detail-view__results"
      aria-labelledby="result-review-title"
    >
      <BacktestProfitSummary :run="results.summary.value" />

      <div class="run-detail-view__results-heading">
        <div>
          <h2 id="result-review-title">结果审阅</h2>
        </div>
        <p>选择一笔成交或一条诊断，核对当时的计划要求、实际依据和执行结果。</p>
      </div>

      <nav class="run-detail-view__tabs" aria-label="回测结果资源">
        <RouterLink
          data-testid="result-tab-summary"
          :to="{ path: route.path, query: resultQuery('summary') }"
          :aria-current="selectedTab === 'summary' ? 'page' : undefined"
        >
          结果概览
        </RouterLink>
        <RouterLink
          data-testid="result-tab-fills"
          :to="{ path: route.path, query: resultQuery('fills') }"
          :aria-current="selectedTab === 'fills' ? 'page' : undefined"
        >
          成交与原因
        </RouterLink>
        <RouterLink
          data-testid="result-tab-details"
          :to="{ path: route.path, query: resultQuery('details') }"
          :aria-current="selectedTab === 'details' ? 'page' : undefined"
        >
          审计事件
        </RouterLink>
        <RouterLink v-if="loopRun" data-testid="result-tab-reasons"
          :to="{ path: route.path, query: resultQuery('reasons') }" :aria-current="selectedTab === 'reasons' ? 'page' : undefined">未成交原因</RouterLink>
        <RouterLink v-if="loopRun" data-testid="result-tab-provenance"
          :to="{ path: route.path, query: resultQuery('provenance') }" :aria-current="selectedTab === 'provenance' ? 'page' : undefined">计划与来源</RouterLink>
        <RouterLink
          data-testid="result-tab-equity"
          :to="{ path: route.path, query: resultQuery('equity') }"
          :aria-current="selectedTab === 'equity' ? 'page' : undefined"
        >
          权益序列
        </RouterLink>
        <RouterLink
          data-testid="result-tab-market-index"
          v-if="legacyRun !== null"
          :to="{ path: route.path, query: resultQuery('market-index') }"
          :aria-current="selectedTab === 'market-index' ? 'page' : undefined"
        >
          参考指数
        </RouterLink>
      </nav>

      <div class="run-detail-view__workspace" :class="{ 'run-detail-view__workspace--selected': review.selected.value }">
      <div class="run-detail-view__workspace-content">
      <BacktestOverview v-if="selectedTab === 'summary' && loopRun !== null" :run="loopRun" @navigate="navigateReviewTab" />
      <MonitorLoopSummary v-else-if="selectedTab === 'provenance' && loopRun !== null" :run="loopRun" :show-diagnostics="false" />
      <section v-else-if="selectedTab === 'reasons' && loopRun !== null" class="run-detail-view__resource" aria-label="未成交原因">
        <h3>未成交原因</h3>
        <PlanExecutionDiagnostics :diagnostics="loopRun.planDiagnostics ?? null" :response-mode="loopRun.response.mode" @select="review.open({ sequence: $event })" />
      </section>
      <BacktestMetricsSummary
        v-else-if="selectedTab === 'summary' && legacyRun !== null"
        :run="legacyRun"
      />

      <section
        v-else-if="selectedTab === 'fills'"
        class="run-detail-view__resource"
        aria-labelledby="fills-title"
      >
        <div class="run-detail-view__resource-heading">
          <div>
            <h3 id="fills-title">模拟成交（仅供研究）</h3>
            <p>服务端权威成交账本；不代表真实委托、成交或券商持仓。</p>
          </div>
          <button type="button" @click="results.refreshSelected">刷新当前页</button>
        </div>
        <p
          v-if="results.fillsState.value === 'LOADING'"
          class="run-detail-view__state"
          data-testid="result-resource-state"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          正在读取模拟成交…
        </p>
        <p
          v-else-if="results.fillsState.value === 'EMPTY'"
          class="run-detail-view__state"
          data-testid="result-resource-state"
        >
          当前页暂无模拟成交。
        </p>
        <div
          v-else-if="results.fillsState.value === 'FAILED'"
          class="run-detail-view__error"
          data-testid="result-resource-error"
          role="alert"
        >
          <p>{{ results.fillsError.value }}</p>
          <button type="button" @click="results.refreshSelected">重新读取当前页</button>
        </div>
        <BacktestFillTable
          v-else-if="results.fillsState.value === 'READY' && results.fillsPage.value !== null"
          :items="results.fillsPage.value.items"
          @select="review.open({ fillId: $event })"
        />
      </section>

      <section
        v-else-if="selectedTab === 'details'"
        class="run-detail-view__resource"
        aria-labelledby="details-title"
      >
        <div class="run-detail-view__resource-heading">
          <div>
            <h3 id="details-title">已物化结果明细</h3>
            <p>过期或运行时未记录的明细不会通过回放、推断或诊断内容补造。</p>
          </div>
          <button
            v-if="activeDetailAvailability === 'AVAILABLE'"
            data-testid="refresh-result-details"
            type="button"
            @click="results.refreshSelected"
          >
            刷新当前页
          </button>
        </div>

        <nav v-if="legacyRun !== null" class="run-detail-view__detail-kinds" aria-label="结果明细类型">
          <RouterLink
            v-for="kind in DETAIL_KIND_OPTIONS"
            :key="kind"
            :data-testid="`detail-kind-${kind}`"
            :to="{ path: route.path, query: resultQuery('details', kind) }"
            :aria-current="selectedDetailKind === kind ? 'page' : undefined"
          >
            {{ kind === "DECISION" ? "决策" : kind === "SIGNAL" ? "信号" : "执行结果" }}
          </RouterLink>
        </nav>

        <p
          v-if="activeDetailAvailability !== null"
          class="run-detail-view__availability"
          data-testid="detail-availability"
          :data-availability="activeDetailAvailability"
        >
          {{ detailAvailabilityCopy }}
        </p>
        <p
          v-if="results.detailState.value === 'LOADING'"
          class="run-detail-view__state"
          data-testid="result-resource-state"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          正在读取结果明细…
        </p>
        <p
          v-else-if="results.detailState.value === 'EMPTY'"
          class="run-detail-view__state"
          data-testid="result-resource-state"
        >
          当前页暂无该类型明细。
        </p>
        <div
          v-else-if="results.detailState.value === 'FAILED'"
          class="run-detail-view__error"
          data-testid="result-resource-error"
          role="alert"
        >
          <p>{{ results.detailError.value }}</p>
          <button type="button" @click="results.refreshSelected">重新读取当前页</button>
        </div>
        <MonitorLoopTimeline
          v-else-if="results.detailState.value === 'READY' && loopRun !== null"
          :items="loopDetails"
          @select="review.open({ eventId: $event })"
        />
        <BacktestDetailTable
          v-else-if="results.detailState.value === 'READY' && results.detailPage.value !== null"
          :items="results.detailPage.value.items"
          :kind="selectedDetailKind"
        />
      </section>

      <section
        v-else-if="selectedTab === 'market-index'"
        class="run-detail-view__resource"
        aria-labelledby="market-index-title"
      >
        <div class="run-detail-view__resource-heading">
          <div>
            <h3 id="market-index-title">冻结参考指数</h3>
            <p>共用指数数据与本计划条件结果分区展示；不提供整次运行的大盘强弱结论。</p>
          </div>
        </div>
        <p v-if="loopRun !== null">本次闭环运行未记录参考指数序列，不会补造。</p>
        <p
          v-if="marketIndexSeries.status.value === 'LOADING'"
          class="run-detail-view__state"
          data-testid="market-index-resource-state"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          正在读取冻结参考指数…
        </p>
        <div
          v-else-if="marketIndexSeries.status.value === 'ERROR'"
          class="run-detail-view__error"
          data-testid="market-index-resource-error"
          role="alert"
        >
          {{ marketIndexSeries.error.value }}
        </div>
        <BacktestMarketIndexPanel
          v-else-if="marketIndexSeries.series.value !== null"
          :series="marketIndexSeries.series.value"
          @select-date="openIndexDecisionDate"
        />
      </section>

      <section
        v-else
        class="run-detail-view__resource"
        aria-labelledby="equity-title"
      >
        <div class="run-detail-view__resource-heading">
          <div>
            <h3 id="equity-title">完整权益序列</h3>
            <p>趋势图仅使用安全派生展示数值；下方原生表格保留全部精确值。</p>
          </div>
          <button
            v-if="activeEquityAvailability === 'AVAILABLE'"
            data-testid="refresh-equity-series"
            type="button"
            @click="results.refreshSelected"
          >
            刷新权益序列
          </button>
        </div>

        <p
          v-if="activeEquityAvailability !== null"
          class="run-detail-view__availability"
          data-testid="equity-availability"
          :data-availability="activeEquityAvailability"
        >
          {{ equityAvailabilityCopy }}
        </p>
        <p
          v-if="results.equityState.value === 'LOADING'"
          class="run-detail-view__state"
          data-testid="result-resource-state"
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          正在读取权益序列…
        </p>
        <p
          v-else-if="results.equityState.value === 'EMPTY'"
          class="run-detail-view__state"
          data-testid="result-resource-state"
        >
          本次运行没有可展示的权益点。
        </p>
        <div
          v-else-if="results.equityState.value === 'FAILED'"
          class="run-detail-view__error"
          data-testid="result-resource-error"
          role="alert"
        >
          <p>{{ results.equityError.value }}</p>
          <button type="button" @click="results.refreshSelected">重新读取权益序列</button>
        </div>
        <div
          v-else-if="
            results.equityState.value === 'READY' &&
            results.equitySeries.value !== null
          "
          class="run-detail-view__equity"
        >
          <BacktestEquityChart :items="results.equitySeries.value.items" />
          <BacktestEquityTable :items="results.equitySeries.value.items" />
        </div>
      </section>

      </div>
      <BacktestEvidencePanel v-if="review.selected.value && loopRun" :context="review.context.value"
        :loading="review.loading.value" :error="review.error.value" :diagnostics="loopRun.planDiagnostics ?? null"
        @close="review.close" @retry="review.refresh" @next="review.nextPage" @relation="review.changeRelation"
        @select="review.open({ eventId: $event })" />
      </div>

      <nav
        v-if="selectedTab !== 'summary' && activePage !== null"
        class="run-detail-view__pagination"
        aria-label="当前结果资源分页"
      >
        <RouterLink
          v-if="previousCursorKnown"
          data-testid="previous-result-page"
          :to="{ path: route.path, query: resultQuery(selectedTab, selectedDetailKind, previousCursor) }"
        >上一页</RouterLink>
        <RouterLink
          v-if="selectedCursor !== null"
          data-testid="first-result-page"
          :to="{
            path: route.path,
            query: resultQuery(selectedTab, selectedDetailKind),
          }"
        >
          返回第一页
        </RouterLink>
        <RouterLink
          v-if="activePage.hasMore && activePage.nextCursor !== null"
          data-testid="next-result-page"
          @click="rememberNextPage"
          :to="{
            path: route.path,
            query: resultQuery(selectedTab, selectedDetailKind, activePage.nextCursor),
          }"
        >
          下一页
        </RouterLink>
        <span v-if="!activePage.hasMore">已到当前资源末页</span>
      </nav>
      <BacktestResultActions
        :api="api"
        :create-idempotency-key="props.createIdempotencyKey"
        :run="results.summary.value"
        @refresh="results.refreshSummary"
      />
    </section>
  </div>
</template>

<style scoped>
.run-detail-view__workspace { display: grid; gap: var(--space-4); min-width: 0; align-items: start; }
.run-detail-view__workspace-content { min-width: 0; }
@media (min-width: 64rem) {
  .run-detail-view__workspace--selected { grid-template-columns: minmax(0, 3fr) minmax(20rem, 2fr); }
}
.run-detail-view {
  display: grid;
  box-sizing: border-box;
  grid-template-columns: minmax(0, 1fr);
  width: min(100%, 90rem);
  gap: var(--space-6);
  margin-inline: auto;
  padding: 0;
  color: var(--color-text-mineral);
}

.run-detail-view__hero {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  align-items: flex-start;
  justify-content: space-between;
  padding-block: var(--space-4) var(--space-7);
  border-block-end: var(--border-technical);
}

.run-detail-view__hero h1,
.run-detail-view__hero p,
.run-detail-view__results-heading h2,
.run-detail-view__results-heading p,
.run-detail-view__resource-heading h3,
.run-detail-view__resource-heading p,
.run-detail-view__error h2,
.run-detail-view__error p,
.run-detail-view__retry,
.run-detail-view__state,
.run-detail-view__availability {
  margin: 0;
}

.run-detail-view__visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.run-detail-view a {
  color: var(--color-signal-info-cyan);
}

.run-detail-view__boundary,
.run-detail-view__state,
.run-detail-view__error,
.run-detail-view__retry,
.run-detail-view__availability,
.run-detail-view__results {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.run-detail-view__boundary {
  border-inline-start: 0.3rem solid var(--color-signal-watch-amber);
}

.run-detail-view__error {
  display: grid;
  gap: var(--space-3);
  border-inline-start: 0.3rem solid var(--color-signal-risk-vermilion);
}

.run-detail-view__retry {
  border-inline-start: 0.3rem solid var(--color-signal-watch-amber);
}

.run-detail-view__results,
.run-detail-view__resource,
.run-detail-view__equity {
  display: grid;
  min-width: 0;
  gap: var(--space-4);
}

.run-detail-view__results-heading,
.run-detail-view__resource-heading {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: flex-start;
  justify-content: space-between;
}

.run-detail-view__results-heading > p,
.run-detail-view__resource-heading p {
  min-width: 0;
  max-width: 52rem;
  color: var(--color-text-muted);
}

.run-detail-view__tabs,
.run-detail-view__detail-kinds,
.run-detail-view__pagination {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}

.run-detail-view__tabs a,
.run-detail-view__detail-kinds a,
.run-detail-view__pagination a {
  display: inline-flex;
  min-height: 2.75rem;
  padding-inline: var(--space-4);
  align-items: center;
  color: var(--color-text-mineral);
  text-decoration: none;
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.run-detail-view__tabs a[aria-current="page"],
.run-detail-view__detail-kinds a[aria-current="page"] {
  border-block-end: 0.25rem solid var(--color-signal-info-cyan);
}

.run-detail-view__availability {
  border-inline-start: 0.3rem solid var(--color-signal-watch-amber);
}

.run-detail-view__pagination span {
  color: var(--color-text-muted);
}

.run-detail-view button {
  width: fit-content;
  min-height: 2.75rem;
  padding-inline: var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.run-detail-view__error a,
.run-detail-view__retry a {
  display: inline-flex;
  width: fit-content;
  min-height: 2.75rem;
  align-items: center;
}

.run-detail-view :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 47.9375rem) {
  .run-detail-view {
    padding: 0;
  }

  .run-detail-view__results-heading,
  .run-detail-view__resource-heading {
    flex-direction: column;
  }
}

@media (max-width: 30rem) {
  .run-detail-view {
    padding-inline: 0;
  }

  .run-detail-view__results {
    padding-inline: var(--space-2);
  }
}

@media (prefers-reduced-motion: reduce) {
  .run-detail-view,
  .run-detail-view * {
    scroll-behavior: auto;
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
    transition-duration: 0.01ms;
  }
}
</style>
