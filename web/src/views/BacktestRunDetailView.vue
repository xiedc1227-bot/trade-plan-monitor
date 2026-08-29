<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  shallowRef,
  watch,
} from "vue";
import {
  isNavigationFailure,
  NavigationFailureType,
  useRoute,
  useRouter,
  type LocationQueryRaw,
} from "vue-router";

import type { BacktestJobView } from "../api/generated";
import { createBacktestApi, type BacktestApi } from "../api/backtests";
import BacktestJobStatus from "../components/backtests/BacktestJobStatus.vue";
import BacktestMetricsSummary from "../components/backtests/BacktestMetricsSummary.vue";
import { useBacktestJob } from "../composables/useBacktestJob";
import { useBacktestResults } from "../composables/useBacktestResults";

interface Props {
  api?: BacktestApi;
  createIdempotencyKey?: () => string;
}

const props = defineProps<Props>();
const route = useRoute();
const router = useRouter();
const api = props.api ?? createBacktestApi();
const runtimeIdentityError = shallowRef<string | null>(null);

const RUN_ID_PATTERN = /^[0-9a-f]{64}$/;
const JOB_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;

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
  () => routeIdentityError.value ?? runtimeIdentityError.value,
);
const requestedJobId = computed(() =>
  routeIdentityError.value === null &&
  runtimeIdentityError.value === null &&
  hasJobIdentity.value
    ? jobId.value
    : null,
);
const resultsEnabled = computed(
  () =>
    routeIdentityError.value === null &&
    runtimeIdentityError.value === null &&
    !hasJobIdentity.value,
);

const jobState = useBacktestJob({
  api,
  ...(props.createIdempotencyKey === undefined
    ? {}
    : { createIdempotencyKey: props.createIdempotencyKey }),
  jobId: requestedJobId,
});
const results = useBacktestResults({ api, enabled: resultsEnabled, runId });

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

watch(
  [() => route.params.runId, () => route.query.jobId],
  () => {
    navigationGeneration += 1;
    runtimeIdentityError.value = null;
    reconcileJobIdentity(jobState.job.value);
  },
  { deep: true },
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
  if (current.status === "COMPLETED") void canonicalizeCompletedJob();
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
        <p class="run-detail-view__eyebrow">OFFLINE RESEARCH RESULT</p>
        <h1>回测结果</h1>
        <p>仅展示服务端权威任务状态与已物化历史模拟结果。</p>
      </div>
    </header>

    <aside class="run-detail-view__boundary" aria-label="研究边界">
      本页仅供离线研究，不连接券商、不自动下单，也不复用实时监控状态。
    </aside>

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

    <BacktestMetricsSummary
      v-else-if="
        resultsEnabled &&
        results.summaryState.value === 'READY' &&
        results.summary.value !== null
      "
      :run="results.summary.value"
    />
  </div>
</template>

<style scoped>
.run-detail-view {
  display: grid;
  width: min(100%, 90rem);
  gap: var(--space-6);
  margin-inline: auto;
  padding: var(--space-6);
  color: var(--color-text-mineral);
}

.run-detail-view__hero {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  align-items: flex-start;
  justify-content: space-between;
}

.run-detail-view__hero h1,
.run-detail-view__hero p,
.run-detail-view__error h2,
.run-detail-view__error p,
.run-detail-view__retry,
.run-detail-view__state {
  margin: 0;
}

.run-detail-view__eyebrow {
  color: var(--color-signal-info-cyan);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.run-detail-view a {
  color: var(--color-signal-info-cyan);
}

.run-detail-view__boundary,
.run-detail-view__state,
.run-detail-view__error,
.run-detail-view__retry {
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

.run-detail-view button {
  width: fit-content;
  min-height: 2.75rem;
  padding-inline: var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.run-detail-view :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 47.9375rem) {
  .run-detail-view {
    padding: var(--space-4);
  }
}
</style>
