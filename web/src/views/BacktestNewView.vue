<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef } from "vue";
import { isNavigationFailure, useRouter } from "vue-router";

import type { BacktestJobReceipt } from "../api/generated";
import type { BacktestApi } from "../api/backtests";
import type { PlanApi } from "../api/plans";
import BacktestRunForm from "../components/backtests/BacktestRunForm.vue";
import BacktestReferenceMarketCoveragePanel from "../components/backtests/BacktestReferenceMarketCoveragePanel.vue";
import { useBacktestPlanVersions } from "../composables/useBacktestPlanVersions";
import { useBacktestRunForm } from "../composables/useBacktestRunForm";
import type { PreparationApi } from "../api/preparations";
import type { ReviewChoice } from "../api/preparationReview";
import { usePlanPreparation } from "../composables/usePlanPreparation";
import PlanPreparationSourceForm from "../components/backtests/PlanPreparationSourceForm.vue";
import PlanPreparationProgress from "../components/backtests/PlanPreparationProgress.vue";
import PlanPreparationReview from "../components/backtests/PlanPreparationReview.vue";

interface Props {
  api?: BacktestApi;
  createIdempotencyKey?: () => string;
  planApi?: PlanApi;
  preparationApi?: PreparationApi;
  initialPreparationId?: string;
}

const props = defineProps<Props>();
const router = useRouter();
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

const form = useBacktestRunForm({
  ...(props.api === undefined ? {} : { api: props.api }),
  ...(props.createIdempotencyKey === undefined
    ? {}
    : { createIdempotencyKey: props.createIdempotencyKey }),
  onAccepted: navigateToAcceptedRun,
});
const plans = useBacktestPlanVersions({
  ...(props.planApi === undefined ? {} : { api: props.planApi }),
});
const preparation = usePlanPreparation({
  ...(props.preparationApi === undefined ? {} : { api: props.preparationApi }),
  ...(props.initialPreparationId === undefined ? {} : { initialPreparationId: props.initialPreparationId }),
});
const mode = ref<"LEGACY" | "PREPARED">(props.initialPreparationId ? "PREPARED" : "LEGACY");
const modeLocked = computed(() => preparation.isBusy.value || ["SUBMITTING", "UNCERTAIN", "ACCEPTED"].includes(form.submissionState.value));
function chooseMode(value: "LEGACY" | "PREPARED"): void {
  if (!modeLocked.value) mode.value = value;
}
function reviewPrepared(value: { evidence: string; choices: ReviewChoice[]; unknownConfirmed: boolean }): void {
  void preparation.review(value.evidence, value.choices, value.unknownConfirmed);
}

function selectPlanVersion(versionId: string): void {
  const selected = plans.selectVersion(versionId);
  form.updateField("planVersionId", selected?.id ?? "");
}

onMounted(() => {
  document.title = "创建回测 · Trade Plan Monitor";
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
        <p class="workspace-eyebrow">05 / NEW EXPERIMENT</p>
        <h1 ref="pageTitle" tabindex="-1">创建回测</h1>
        <p>选择不可变计划版本与已验证数据集，提交可复现的回测运行。</p>
      </div>
      <a href="/backtests">返回回测研究台</a>
    </header>

    <aside class="backtest-new-view__boundary" aria-label="研究边界">
      仅供研究与回放，不连接券商、不自动下单。浏览器不推断计划资格、交易日历、T+1、成交或指标。
    </aside>

    <section class="backtest-new-view__mode" aria-label="选择准备方式">
      <button type="button" data-testid="choose-legacy-plan" :aria-pressed="mode === 'LEGACY'" :disabled="modeLocked" @click="chooseMode('LEGACY')">使用已有计划版本</button>
      <button type="button" data-testid="choose-prepared-plan" :aria-pressed="mode === 'PREPARED'" :disabled="modeLocked" @click="chooseMode('PREPARED')">从原文准备新计划</button>
      <p v-if="modeLocked" role="status">当前任务或操作未结束，完成前不能切换准备方式或开启其他任务。</p>
    </section>

    <section v-if="mode === 'PREPARED'" class="backtest-new-view__preparation" aria-label="单份计划准备">
      <PlanPreparationSourceForm :source="preparation.draft.value" :disabled="!preparation.canSubmitSource.value"
        @update:source="preparation.updateSource" @submit="preparation.submitSource" />
      <PlanPreparationProgress :preparation="preparation.preparation.value" :request-state="preparation.requestState.value"
        :mutation-state="preparation.mutationState.value" :can-extract="preparation.canExtract.value"
        :can-cancel="preparation.canCancel.value" :can-recover="preparation.canRecover.value"
        :can-retry-mutation="preparation.canRetryMutation.value" :error-message="preparation.errorMessage.value"
        @extract="preparation.extract" @cancel="preparation.cancel" @recover="preparation.recover"
        @retry-mutation="preparation.retryMutation" @refresh="preparation.refresh" />
      <PlanPreparationReview v-if="preparation.preparation.value?.candidate" :preparation="preparation.preparation.value"
        :can-review="preparation.canReview.value" :source-dirty="preparation.sourceDirty.value"
        :reviewed="preparation.canUsePrepared.value" @review="reviewPrepared" />
    </section>

    <BacktestRunForm
      v-if="mode === 'LEGACY'"
      :draft="form.draft.value"
      :error-revision="form.errorRevision.value"
      :errors="form.errors.value"
      :plan-version-error="plans.errorMessage.value"
      :plan-version-page="plans.page.value"
      :plan-version-state="plans.state.value"
      :selected-plan-version="plans.selectedVersion.value"
      :submission-state="form.submissionState.value"
      @add-lot="form.addLot"
      @next-plan-version-page="plans.nextPage"
      @previous-plan-version-page="plans.previousPage"
      @remove-lot="form.removeLot"
      @retry-plan-versions="plans.retry"
      @select-plan-version="selectPlanVersion"
      @submit="form.submit"
      @update-field="form.updateField"
      @update-lot="form.updateLot"
    />

    <BacktestReferenceMarketCoveragePanel
      v-if="mode === 'LEGACY'"
      :coverage="form.referenceMarketCoverage.value"
      :error="form.referenceMarketCoverageError.value"
      :state="form.referenceMarketCoverageState.value"
    />

    <section
      v-if="form.submissionState.value !== 'IDLE'"
      class="backtest-new-view__submission"
      :role="form.submissionErrorMessage.value === null ? 'status' : 'alert'"
      aria-live="polite"
    >
      <p v-if="form.submissionState.value === 'SUBMITTING'">正在提交回测运行</p>
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
    </section>
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
