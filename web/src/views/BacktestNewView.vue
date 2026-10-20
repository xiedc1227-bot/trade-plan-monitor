<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch, type DeepReadonly } from "vue";
import { isNavigationFailure, useRoute, useRouter } from "vue-router";

import type { BacktestJobReceipt, PreparationFrozenView, CollectionPreparationFrozenView } from "../api/generated";
import type { BacktestApi } from "../api/backtests";
import type { PlanApi } from "../api/plans";
import BacktestRunForm from "../components/backtests/BacktestRunForm.vue";
import BacktestJobStatus from "../components/backtests/BacktestJobStatus.vue";
import WorkbenchPlanReplay from "../components/backtests/WorkbenchPlanReplay.vue";
import { useBacktestRunForm } from "../composables/useBacktestRunForm";
import type { PreparationApi } from "../api/preparations";
import type { ReviewChoice } from "../api/preparationReview";
import { usePlanPreparation } from "../composables/usePlanPreparation";
import PlanPreparationSourceForm from "../components/backtests/PlanPreparationSourceForm.vue";
import PlanPreparationProgress from "../components/backtests/PlanPreparationProgress.vue";
import ReviewedPlanLibrary from "../components/backtests/ReviewedPlanLibrary.vue";
import { usePlanLibrary } from "../composables/usePlanLibrary";
import PlanPreparationReview from "../components/backtests/PlanPreparationReview.vue";

import type { PlanSelectionApi } from "../api/planSelections";
import { ApiClientError } from "../api/transport";

interface Props {
  selectionApi?: PlanSelectionApi;
  api?: BacktestApi;
  createIdempotencyKey?: () => string;
  planApi?: PlanApi;
  preparationApi?: PreparationApi;
  initialPreparationId?: string;
}

const props = defineProps<Props>();
const router = useRouter();
const route = useRoute();
const inspecting = computed(() => route.query.inspect === "1");
const pageTitle = useTemplateRef<HTMLHeadingElement>("pageTitle");
const previousTitle = document.title;

async function navigateToAcceptedRun(receipt: BacktestJobReceipt): Promise<void> {
  if (receipt.runId === null) return Promise.resolve();
  const failure = await router.push({
    path: `/backtests/${receipt.runId}`,
    ...(receipt.status === "COMPLETED" ? {} : { query: { jobId: receipt.jobId } }),
  });
  if (isNavigationFailure(failure)) throw new Error("accepted run navigation failed");
}

const library = usePlanLibrary();
const preparation = usePlanPreparation({
  singleMode: true, reviewedBase: () => library.reviewedBase.value,
  ...(props.preparationApi === undefined ? {} : { api: props.preparationApi }),
  ...(props.initialPreparationId === undefined ? {} : { initialPreparationId: props.initialPreparationId }),
});
const mode = ref<"LEGACY" | "PREPARED">(props.initialPreparationId ? "PREPARED" : "LEGACY");
watch(() => preparation.preparationId.value, (identity) => {
  if (identity && route.path === "/backtests/new" && route.query.preparationId !== identity) {
    void router.replace({ path: route.path, query: { ...route.query, preparationId: identity } });
  } else if (!identity && route.path === "/backtests/new" && route.query.preparationId) {
    const { preparationId: _previous, ...query } = route.query;
    void router.replace({ path: route.path, query });
  }
});
const reviewedPrepared = computed<DeepReadonly<PreparationFrozenView | CollectionPreparationFrozenView> | null>(() => {
  if (inspecting.value || !preparation.canUsePrepared.value || preparation.sourceDirty.value) return null;
  const chain = preparation.collection.value;
  if (chain) return chain.workflow !== "SINGLE" ||
    library.endpointId.value === chain.preparationId && !library.path.value.error ? chain.frozen : null;
  const value = preparation.preparation.value;
  if (!preparation.canUsePrepared.value || value?.candidate?.kind !== "FROZEN") return null;
  return { preparationId: value.preparationId, manifestHash: value.candidate.candidateHash,
    frozen: value.candidate.frozen };
});
const form = useBacktestRunForm({
  ...(props.api === undefined ? {} : { api: props.api }),
  ...(props.createIdempotencyKey === undefined
    ? {}
    : { createIdempotencyKey: props.createIdempotencyKey }),
  onAccepted: navigateToAcceptedRun,
  prepared: () => reviewedPrepared.value,
  preparedMode: () => mode.value === "PREPARED",
  async prepareScheduled(command) {
    if (preparation.collection.value?.workflow !== "SINGLE") return command;
    if (command.preparationId !== library.endpoint.value?.preparationId || command.manifestHash !== library.endpoint.value.manifestHash) {
      throw new ApiClientError({ code: "CONFLICT", status: 409, message: "时间线版本已变化，请核对后重新开始。" });
    }
    const frozen = await library.compose();
    if (!frozen) throw new ApiClientError({ code: library.uncertain.value ? "NETWORK_ERROR" : "CONFLICT",
      status: library.uncertain.value ? 0 : 409, message: library.error.value ?? "无法准备计划时间线。" });
    return frozen;
  },
});
const dataPhaseText = computed(() => ({
  IDLE: "", CHECKING: "正在检查本地历史数据", SYNCING: "正在自动补齐历史数据",
  VERIFYING: "正在验证回测数据", READY: "数据已就绪，正在提交回测",
  FAILED: "数据准备未完成", CANCELLED: "回测已取消",
})[form.automaticData.phase.value]);
const preparingData = computed(() => ["CHECKING", "SYNCING", "VERIFYING"].includes(form.automaticData.phase.value));
const workbenchLocked = ref(false);
const runLocked = computed(() => inspecting.value || ["SUBMITTING", "UNCERTAIN", "ACCEPTED"].includes(form.submissionState.value));
const modeLocked = computed(() => preparation.isBusy.value || library.locked.value || runLocked.value || workbenchLocked.value);
watch(() => preparation.canUsePrepared.value, (ready) => {
  if (!ready) return;
  const frozen = preparation.collection.value?.frozen;
  void library.refresh(frozen ? { preparation_id: frozen.preparationId, manifest_hash: frozen.manifestHash } : undefined);
});
watch([() => preparation.canUsePrepared.value, () => preparation.preparationId.value, library.items], ([ready, id]) => {
  if (!inspecting.value && ready && id && preparation.collection.value?.workflow === "SINGLE" && library.items.value.some(item => item.preparationId === id)) {
    library.chooseEndpoint(id);
  }
});
async function openTimeline(id: string): Promise<void> {
  if (library.loading.value || modeLocked.value || preparation.sourceDirty.value) return;
  if (library.chooseEndpoint(id)) await preparation.open(id);
}
function prepareNext(id: string): void {
  if (library.loading.value || modeLocked.value || preparation.sourceDirty.value) return;
  if (!library.chooseEndpoint(id)) return;
  preparation.newSource();
}
function newTimeline(): void {
  if (library.loading.value || modeLocked.value || preparation.sourceDirty.value || !library.chooseEndpoint("")) return;
  preparation.newSource();
}
watch(() => props.initialPreparationId, (id) => {
  if (id && id !== preparation.preparationId.value) void openTimeline(id);
});
function chooseMode(value: "LEGACY" | "PREPARED"): void {
  if (modeLocked.value || mode.value === value) return;
  mode.value = value;
  const { selectionId: _previousSelection, preparationId: _previousPreparation, ...query } = route.query;
  void router.replace({ path: route.path, query: {
    ...query, ...(value === "PREPARED" && preparation.preparationId.value
      ? { preparationId: preparation.preparationId.value } : {}),
  } });
}
function reviewPrepared(value: { evidence: string; choices: ReviewChoice[]; unknownConfirmed: boolean }): void {
  if (!runLocked.value) void preparation.review(value.evidence, value.choices, value.unknownConfirmed);
}


onMounted(() => {
  document.title = `${inspecting.value ? "查看历史计划" : "创建回测"} · Trade Plan Monitor`;
  pageTitle.value?.focus();
});

onBeforeUnmount(() => {
  document.title = previousTitle;
});
</script>

<template>
  <div class="backtest-new-view">
    <header class="backtest-new-view__hero">
      <div>
        <h1 ref="pageTitle" tabindex="-1">{{ inspecting ? '只读查看历史计划' : '创建回测' }}</h1>
        <p>选择已审核计划并开始回测；程序自动检查、补齐和验证历史数据。</p>
      </div>
      <a href="/backtests">返回回测研究台</a>
    </header>

    <aside class="backtest-new-view__boundary" aria-label="研究边界">
      仅供研究与回放，不连接券商、不自动下单。浏览器不推断计划资格、交易日历、T+1、成交或指标。
    </aside>

    <section class="backtest-new-view__mode" aria-label="选择已审核计划来源">
      <button type="button" data-testid="choose-legacy-plan" :aria-pressed="mode === 'LEGACY'" :disabled="modeLocked" @click="chooseMode('LEGACY')">工作台已审核计划</button>
      <button type="button" data-testid="choose-prepared-plan" :aria-pressed="mode === 'PREPARED'" :disabled="modeLocked" @click="chooseMode('PREPARED')">计划更新时间线与原文准备</button>
      <p v-if="modeLocked && !inspecting" role="status">当前任务或操作未结束，完成前不能切换准备方式或开启其他任务。</p>
    </section>

    <section v-if="mode === 'PREPARED'" class="backtest-new-view__preparation" aria-label="计划原文准备">
      <p v-if="inspecting" role="status">此页面只读展示历史原文与审核规则，不改变原页面的时间线选择和回测设置。</p>
      <ReviewedPlanLibrary v-if="!inspecting" :items="library.items.value" :endpoint-id="library.endpointId.value"
        :disabled="modeLocked" :loading="library.loading.value"
        :pending="library.locked.value" :uncertain="library.uncertain.value" :error="library.error.value" :can-start="!preparation.sourceDirty.value"
        @open="openTimeline" @update="prepareNext" @refresh="library.refresh" @new="newTimeline" />
      <p v-if="!preparation.preparationId.value && library.endpoint.value" role="status">正在更新 {{ library.endpoint.value.name }}（{{ library.endpoint.value.symbol }}）的计划时间线，前序生效日为 {{ library.endpoint.value.effectiveTradeDate }}。新计划审核通过后才会追加。</p>
      <p v-if="preparation.collection.value?.workflow === 'SINGLE' && preparation.collection.value.itemCount > 1">前序版本已审核并锁定，只能编辑和提取当前这一份原文。</p>
      <PlanPreparationSourceForm :source="preparation.draft.value" :disabled="runLocked || library.locked.value || !preparation.canSubmitSource.value || (!preparation.preparationId.value && (library.loading.value || library.needsBase.value))"
        @update:source="preparation.updateSource" @submit="!library.needsBase.value && preparation.submitSource()" />
      <PlanPreparationProgress :preparation="preparation.preparation.value" :collection="preparation.collection.value" :request-state="preparation.requestState.value"
        :items="preparation.items.value" :extraction-blockers="preparation.extractionBlockers.value"
        :mutation-state="preparation.mutationState.value" :can-extract="!runLocked && preparation.canExtract.value"
        :can-cancel="!runLocked && preparation.canCancel.value" :can-recover="!runLocked && preparation.canRecover.value"
        :can-retry-mutation="!runLocked && preparation.canRetryMutation.value" :error-message="preparation.errorMessage.value"
        @extract="preparation.extract" @cancel="preparation.cancel" @recover="preparation.recover"
        @retry-mutation="preparation.retryMutation" @refresh="preparation.refresh" @select-source="preparation.selectSource" />
      <PlanPreparationReview v-if="preparation.preparation.value?.candidate" :preparation="preparation.preparation.value"
        :can-review="!runLocked && preparation.canReview.value" :source-dirty="preparation.sourceDirty.value"
        :reviewed="preparation.canUsePrepared.value" @review="reviewPrepared" />
      <PlanPreparationReview v-if="preparation.collection.value" :collection="preparation.collection.value" :items="preparation.items.value"
        :can-review="!runLocked && preparation.canReview.value" :can-correct="!runLocked && !preparation.isBusy.value"
        :source-dirty="preparation.sourceDirty.value" :reviewed="preparation.canUsePrepared.value"
        @review-collection="!runLocked && preparation.reviewCollection($event.evidence, $event.unknownConfirmed, $event.account)"
        @correct-item="!runLocked && preparation.correctItem($event.sourceId, $event.evidence, $event.changes)" />
    </section>

    <WorkbenchPlanReplay v-if="mode === 'LEGACY'" :api="api" :plan-api="planApi" :selection-api="selectionApi" :create-idempotency-key="createIdempotencyKey" :on-accepted="navigateToAcceptedRun" @locked="workbenchLocked = $event" />
    <BacktestRunForm
      v-if="mode === 'PREPARED' && reviewedPrepared !== null"
      :prepared-mode="mode === 'PREPARED'"
      :prepared="reviewedPrepared"
      :draft="form.draft.value"
      :error-revision="form.errorRevision.value"
      :errors="form.errors.value"
      :plan-version-error="null"
      :plan-version-page="null"
      plan-version-state="IDLE"
      :selected-plan-version="null"
      :submission-state="form.submissionState.value"
      @add-lot="form.addLot"
      @remove-lot="form.removeLot"
      @submit="form.submit"
      @update-field="form.updateField"
      @update-lot="form.updateLot"
    />

    <section
      v-if="form.submissionState.value !== 'IDLE'"
      class="backtest-new-view__submission"
      :role="form.submissionErrorMessage.value === null ? 'status' : 'alert'"
      aria-live="polite"
    >
      <p v-if="form.submissionState.value === 'SUBMITTING'">{{ preparingData ? dataPhaseText : '正在提交回测运行' }}</p>
      <p v-else-if="form.submissionState.value === 'ACCEPTED'">回测运行已由服务端接受</p>
      <p v-if="form.submissionErrorMessage.value !== null">
        {{ form.submissionErrorMessage.value }}
      </p>
      <button
        v-if="form.submissionState.value === 'UNCERTAIN'"
        data-testid="retry-run-submission"
        type="button"
        @click="form.retrySubmission"
      >
        使用同一请求安全重试
      </button>
      <button v-if="preparingData" type="button" data-testid="cancel-automatic-data"
        :disabled="form.automaticData.cancellationRequested.value" @click="form.automaticData.cancel">
        {{ form.automaticData.cancellationRequested.value ? '正在取消，等待任务确认' : '取消回测' }}
      </button>
    </section>
    <BacktestJobStatus v-if="form.automaticData.jobState.job.value"
      :job="form.automaticData.jobState.job.value"
      :request-state="form.automaticData.jobState.requestState.value"
      :cancellation-state="form.automaticData.jobState.cancellationState.value"
      :error-message="form.automaticData.jobState.errorMessage.value"
      @cancel="form.automaticData.cancel"
      @refresh="form.automaticData.jobState.refresh"
      @retry-cancellation="form.automaticData.jobState.retryCancellation" />
    <a v-if="form.automaticData.jobId.value" :href="`/backtests/data?jobId=${form.automaticData.jobId.value}`">查看数据任务记录</a>
  </div>
</template>

<style scoped>
.backtest-new-view {
  display: grid;
  box-sizing: border-box;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-6);
  width: min(100%, 90rem);
  margin-inline: auto;
  padding: 0;
  color: var(--color-text-mineral);
}

.backtest-new-view__mode { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.backtest-new-view__mode button { min-height: 2.75rem; max-width: 100%; padding: var(--space-2) var(--space-4); border: var(--border-technical); border-radius: var(--radius-control); background: var(--color-surface-raised); color: inherit; font: inherit; }
.backtest-new-view__mode button[aria-pressed="true"] { border-color: var(--color-signal-watch-amber); }
.backtest-new-view__mode button:disabled { opacity: .65; }
.backtest-new-view__mode p { width: 100%; margin: 0; }
.backtest-new-view__preparation { display: grid; min-width: 0; gap: var(--space-6); }

.backtest-new-view__hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  padding-block: var(--space-4) var(--space-7);
  border-block-end: var(--border-technical);
}

.backtest-new-view__hero h1,
.backtest-new-view__hero p,
.backtest-new-view__submission p {
  margin: 0;
}

.backtest-new-view__hero h1 {
  font-size: clamp(1.875rem, 3vw, 2.75rem);
  line-height: 1.3;
}

.backtest-new-view__hero a,
.backtest-new-view__submission button {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
  border-radius: var(--radius-control);
  text-decoration: none;
}

.backtest-new-view__boundary,
.backtest-new-view__submission {
  padding: var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
}

.backtest-new-view__boundary {
  border-radius: var(--radius-control);
  font-size: .8125rem;
  border-inline-start: 0.3rem solid var(--color-signal-watch-amber);
}

.backtest-new-view__submission {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  border-inline-start: 0.3rem solid var(--color-signal-risk-vermilion);
}

.backtest-new-view :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 47.9375rem) {
  .backtest-new-view {
    padding: 0;
  }

  .backtest-new-view__hero {
    flex-direction: column;
  }
}

@media (max-width: 30rem) {
  .backtest-new-view {
    padding-inline: 0;
  }
}
</style>
