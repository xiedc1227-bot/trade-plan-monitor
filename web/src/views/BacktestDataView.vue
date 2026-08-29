<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, shallowRef, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";

import type {
  BacktestDatasetScopeInput,
  BacktestDatasetVerificationJobResultView,
  BacktestJobView,
} from "../api/generated";
import { createBacktestApi, type BacktestApi } from "../api/backtests";
import BacktestJobStatus from "../components/backtests/BacktestJobStatus.vue";
import DatasetCoveragePanel from "../components/backtests/DatasetCoveragePanel.vue";
import DatasetScopeForm from "../components/backtests/DatasetScopeForm.vue";
import { useBacktestData } from "../composables/useBacktestData";
import { useBacktestJob } from "../composables/useBacktestJob";

interface Props {
  api?: BacktestApi;
  createIdempotencyKey?: () => string;
}

const props = defineProps<Props>();
const route = useRoute();
const router = useRouter();
const api = props.api ?? createBacktestApi();
const previousTitle = document.title;
const identityError = shallowRef<string | null>(null);

function replaceQuery(query: LocationQueryRaw): Promise<unknown> {
  return router.replace({ path: route.path, query });
}

function pushQuery(query: LocationQueryRaw): Promise<unknown> {
  return router.push({ path: route.path, query });
}

const data = useBacktestData({
  api,
  ...(props.createIdempotencyKey === undefined
    ? {}
    : { createIdempotencyKey: props.createIdempotencyKey }),
  pushQuery,
  query: () => route.query,
  replaceQuery,
});

const jobState = useBacktestJob({
  api,
  initialRetryAfterSeconds: data.retryAfterSeconds,
  jobId: data.jobId,
});

const matchingJob = computed<BacktestJobView | null>(() => {
  const current = jobState.job.value;
  const expectedId = data.jobId.value;
  return current !== null &&
    expectedId !== null &&
    current.jobId === expectedId &&
    (current.kind === "DATA_SYNC" || current.kind === "DATASET_VERIFY")
    ? (current as unknown as BacktestJobView)
    : null;
});

const verification = computed<BacktestDatasetVerificationJobResultView | null>(() => {
  const result = matchingJob.value?.result;
  return result?.kind === "DATASET_VERIFY"
    ? (result as unknown as BacktestDatasetVerificationJobResultView)
    : null;
});

watch(
  data.jobIdentityError,
  (message) => {
    if (message !== null) identityError.value = message;
  },
  { immediate: true },
);

watch(data.jobId, (jobId) => {
  if (jobId !== null) identityError.value = null;
});

watch(jobState.job, (job) => {
  const expectedId = data.jobId.value;
  if (job === null || expectedId === null) return;
  if (
    job.jobId === expectedId &&
    (job.kind === "DATA_SYNC" || job.kind === "DATASET_VERIFY")
  ) {
    return;
  }
  identityError.value = "任务不属于历史数据任务，已停止读取该任务状态";
  const query = { ...route.query };
  delete query.jobId;
  void replaceQuery(query);
});

function sameScope(
  left: BacktestDatasetScopeInput | null,
  right: BacktestDatasetScopeInput,
): boolean {
  return (
    left !== null &&
    left.adjustmentPolicy === right.adjustmentPolicy &&
    left.historicalProfile === right.historicalProfile &&
    left.warmupStart === right.warmupStart &&
    left.start === right.start &&
    left.end === right.end &&
    left.symbols.join(",") === right.symbols.join(",")
  );
}

async function ensureScope(scope: BacktestDatasetScopeInput): Promise<void> {
  if (!sameScope(data.scope.value, scope)) await data.applyScope(scope);
}

async function requestSync(scope: BacktestDatasetScopeInput, refresh: boolean): Promise<void> {
  await ensureScope(scope);
  await data.sync(scope, refresh);
}

async function requestVerification(scope: BacktestDatasetScopeInput): Promise<void> {
  await ensureScope(scope);
  await data.verify(scope);
}

onMounted(() => {
  document.title = "历史数据管理 · Trade Plan Monitor";
});

onBeforeUnmount(() => {
  document.title = previousTitle;
});
</script>

<template>
  <div class="backtest-data-view">
    <header class="backtest-data-view__hero">
      <div>
        <p class="backtest-data-view__eyebrow">OFFLINE RESEARCH DATA</p>
        <h1>历史数据管理</h1>
        <p>管理回测数据范围、查看服务端覆盖事实，并以显式授权启动联网同步。</p>
      </div>
      <a href="/backtests">返回回测研究台</a>
    </header>

    <aside class="backtest-data-view__boundary" aria-label="研究边界">
      仅供研究与回放，不连接券商、不自动下单。除经确认的同步外，数据验证保持离线。
    </aside>

    <DatasetScopeForm
      :filters="data.filters.value"
      :scope="data.scope.value"
      :submission-state="data.submissionState.value"
      @apply-filters="data.applyFilters"
      @apply-scope="data.applyScope"
      @request-sync="requestSync"
      @request-verify="requestVerification"
    />

    <section
      v-if="data.submissionState.value !== 'IDLE'"
      class="backtest-data-view__submission"
      :role="data.submissionErrorMessage.value === null ? 'status' : 'alert'"
      aria-live="polite"
    >
      <p v-if="data.submissionState.value === 'SUBMITTING'">正在提交数据任务</p>
      <p v-else-if="data.submissionState.value === 'ACCEPTED'">数据任务已由服务端接受</p>
      <p v-if="data.submissionErrorMessage.value !== null">
        {{ data.submissionErrorMessage.value }}
      </p>
      <button
        v-if="data.submissionState.value === 'UNCERTAIN'"
        data-testid="retry-dataset-submission"
        type="button"
        @click="data.retrySubmission"
      >
        使用同一请求安全重试
      </button>
    </section>

    <p
      v-if="identityError !== null"
      class="backtest-data-view__identity-error"
      data-testid="job-identity-error"
      role="alert"
    >
      {{ identityError }}
    </p>

    <BacktestJobStatus
      v-if="matchingJob !== null"
      :cancellation-state="jobState.cancellationState.value"
      :error-message="jobState.errorMessage.value"
      :job="matchingJob"
      :request-state="jobState.requestState.value"
      @cancel="jobState.cancel"
      @refresh="jobState.refresh"
      @retry-cancellation="jobState.retryCancellation"
    />

    <DatasetCoveragePanel
      :datasets="data.datasets.value"
      :error-message="data.queryErrorMessage.value"
      :has-more="data.hasMore.value"
      :query-state="data.queryState.value"
      :verification="verification"
      @next-page="data.nextPage"
      @refresh="data.refreshDatasets"
    />
  </div>
</template>

<style scoped>
.backtest-data-view {
  display: grid;
  gap: var(--space-6);
  width: min(100%, 90rem);
  margin-inline: auto;
  padding: var(--space-6);
  color: var(--color-text-mineral);
}

.backtest-data-view__hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.backtest-data-view__hero h1,
.backtest-data-view__hero p,
.backtest-data-view__submission p,
.backtest-data-view__identity-error {
  margin: 0;
}

.backtest-data-view__hero h1 {
  font-size: clamp(2rem, 5vw, 4rem);
  line-height: 1;
}

.backtest-data-view__eyebrow {
  color: var(--color-signal-info-cyan);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.backtest-data-view__hero a,
.backtest-data-view__submission button {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

.backtest-data-view__boundary,
.backtest-data-view__submission,
.backtest-data-view__identity-error {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.backtest-data-view__boundary {
  border-inline-start: 0.3rem solid var(--color-signal-watch-amber);
}

.backtest-data-view__submission,
.backtest-data-view__identity-error {
  border-inline-start: 0.3rem solid var(--color-signal-risk-vermilion);
}

.backtest-data-view__submission {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.backtest-data-view :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 47.9375rem) {
  .backtest-data-view {
    padding: var(--space-4);
  }

  .backtest-data-view__hero {
    flex-direction: column;
  }
}
</style>
