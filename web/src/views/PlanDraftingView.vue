<script setup lang="ts">
import { computed, shallowRef, watch } from "vue";

import type { AIPlanApi } from "../api/ai";
import type { PlanApi } from "../api/plans";
import ExtractedPlanReview from "../components/plans/ExtractedPlanReview.vue";
import PlanCreationSwitcher, {
  type PlanCreationMode,
} from "../components/plans/PlanCreationSwitcher.vue";
import PlanImportForm from "../components/plans/PlanImportForm.vue";
import PlanWorkbench from "../components/plans/PlanWorkbench.vue";
import type { PlanExportIntent } from "../components/plans/StructuredPlanEditor.vue";
import { usePlanDrafting } from "../composables/usePlanDrafting";
import { usePlans, type ExtractedPlanDraftIntent } from "../composables/usePlans";
import PlansView from "./PlansView.vue";

interface Props {
  api?: AIPlanApi;
  createIdempotencyKey?: () => string;
  createPlanIdempotencyKey?: () => string;
  planApi?: PlanApi;
  planVersionId?: string;
  pollIntervalMs?: number;
}

const props = defineProps<Props>();
const drafting = usePlanDrafting({
  ...(props.api === undefined ? {} : { api: props.api }),
  ...(props.createIdempotencyKey === undefined
    ? {}
    : { createIdempotencyKey: props.createIdempotencyKey }),
  ...(props.pollIntervalMs === undefined ? {} : { pollIntervalMs: props.pollIntervalMs }),
});
const plans = usePlans({
  ...(props.planApi === undefined ? {} : { api: props.planApi }),
  ...(props.createPlanIdempotencyKey === undefined
    ? {}
    : { createIdempotencyKey: props.createPlanIdempotencyKey }),
  ...(props.planVersionId === undefined ? {} : { initialPlanVersionId: props.planVersionId }),
});
const savedExtractionId = shallowRef<string | null>(null);
const creationMode = shallowRef<PlanCreationMode>("AI");
const configuredProviders = computed(() => {
  const runtime = drafting.runtime.value;
  if (runtime === null) return [];
  return [runtime, ...(runtime.alternativeProviders ?? [])];
});

watch(
  () => props.planVersionId,
  (planVersionId, previousPlanVersionId) => {
    if (planVersionId !== previousPlanVersionId) {
      void plans.openPlan(planVersionId ?? null);
    }
  },
);

function exportPlan(intent: PlanExportIntent): void {
  if (typeof URL.createObjectURL !== "function") return;
  const extension = intent.format === "JSON" ? "json" : "yaml";
  const mimeType =
    intent.format === "JSON" ? "application/json;charset=utf-8" : "application/yaml;charset=utf-8";
  const objectUrl = URL.createObjectURL(new Blob([intent.planJson], { type: mimeType }));
  const anchor = document.createElement("a");
  anchor.download = `trade-plan-${intent.planVersionId}.${extension}`;
  anchor.href = objectUrl;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

async function saveExtractedDraft(intent: ExtractedPlanDraftIntent): Promise<void> {
  const extractionId = drafting.extraction.value?.id ?? null;
  if (extractionId === null) return;
  if (await plans.saveExtractedDraft(intent)) {
    savedExtractionId.value = extractionId;
  }
}
</script>

<template>
  <section class="plan-drafting-view" aria-labelledby="plan-workspace-title">
    <header class="plan-drafting-view__header">
      <p class="plan-drafting-view__eyebrow">PLAN VERSION WORKSPACE</p>
      <h1 id="plan-workspace-title">计划工作台</h1>
      <p class="plan-drafting-view__description">
        创建、审核和管理交易计划版本。浏览器只提交操作意图，后端负责解析、校验与状态决策。
      </p>
    </header>

    <PlanCreationSwitcher v-model="creationMode">
      <template #import>
        <p v-if="plans.loading.value" class="plan-drafting-view__notice" role="status">
          正在读取持久计划版本
        </p>
        <p v-if="plans.errorMessage.value" class="plan-drafting-view__error" role="alert">
          {{ plans.errorMessage.value }}
        </p>
        <button
          v-if="plans.errorMessage.value && !plans.loading.value"
          class="plan-drafting-view__retry"
          type="button"
          @click="plans.refresh"
        >
          重新读取计划
        </button>
        <PlanImportForm
          v-if="!plans.loading.value && !plans.errorMessage.value"
          :busy="plans.busy.value"
          :expected-revision="0"
          @import-plan="plans.importPlan"
        />
      </template>

      <template #ai>
        <p v-if="drafting.loading.value" class="plan-drafting-view__notice" role="status">
          正在读取 AI 配置
        </p>
        <p
          v-else-if="drafting.errorMessage.value && !drafting.runtime.value"
          class="plan-drafting-view__error"
          role="alert"
        >
          {{ drafting.errorMessage.value }}
        </p>
        <template v-else-if="drafting.runtime.value">
          <p
            v-if="drafting.errorMessage.value"
            class="plan-drafting-view__error"
            role="alert"
          >
            {{ drafting.errorMessage.value }}
          </p>
          <p
            v-if="drafting.stoppedMessage.value"
            class="plan-drafting-view__notice"
            role="status"
          >
            {{ drafting.stoppedMessage.value }}
          </p>
          <PlanWorkbench
            :extraction="drafting.extraction.value"
            :initial-provider-id="drafting.runtime.value.providerId"
            :providers="configuredProviders"
            :submitting="drafting.submitting.value"
            @stop-waiting="drafting.stopWaiting"
            @submit-extraction="drafting.submitExtraction"
          >
            <template #extractedDraft="{ extraction, resolvedIssueKeys, sourceText }">
              <ExtractedPlanReview
                :busy="plans.busy.value"
                :extraction="extraction"
                :resolved-issue-keys="resolvedIssueKeys"
                :saved="savedExtractionId === extraction.id"
                :source-text="sourceText"
                @save-draft="saveExtractedDraft"
              />
            </template>
          </PlanWorkbench>
        </template>
      </template>
    </PlanCreationSwitcher>

    <section class="plan-drafting-view__persistence" aria-label="持久计划版本">
      <PlansView
        v-if="plans.versions.value.length > 0"
        :active-plan="plans.activePlan.value"
        :active-state="plans.activeState.value"
        :busy="plans.busy.value"
        :selected-plan="plans.selectedPlan.value"
        :selected-plan-id="plans.selectedPlanId.value"
        :versions="plans.versions.value"
        @activate-plan="plans.activatePlan"
        @confirm-plan-review="plans.confirmPlanReview"
        @deactivate-plan="plans.deactivatePlan"
        @export-plan="exportPlan"
        @import-plan="plans.importPlan"
        @save-draft="plans.saveDraft"
        @select-plan="plans.selectPlan"
      />
    </section>

  </section>
</template>

<style scoped>
.plan-drafting-view {
  display: grid;
  gap: var(--space-7);
  box-sizing: border-box;
  width: 100%;
  padding: var(--space-6);
  color: var(--color-text-mineral);
}

.plan-drafting-view__persistence {
  display: grid;
  gap: var(--space-4);
}

.plan-drafting-view__notice,
.plan-drafting-view__error {
  width: min(100%, 90rem);
  box-sizing: border-box;
  margin: 0 auto var(--space-5);
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.plan-drafting-view__header {
  width: min(100%, 90rem);
  margin: 0 auto var(--space-5);
}

.plan-drafting-view__header h1,
.plan-drafting-view__header p {
  margin: 0;
}

.plan-drafting-view__eyebrow {
  color: var(--color-signal-info-cyan);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
}

.plan-drafting-view__header h1 {
  font-size: clamp(1.75rem, 4vw, 3rem);
  line-height: 1.1;
}

.plan-drafting-view__description {
  max-width: 58rem;
  margin-block-start: var(--space-2) !important;
  color: var(--color-text-muted);
}

.plan-drafting-view__notice {
  border-inline-start: 0.25rem solid var(--color-signal-info-cyan);
}

.plan-drafting-view__error {
  border-inline-start: 0.25rem solid var(--color-signal-risk-vermilion);
}

.plan-drafting-view__retry {
  width: fit-content;
  min-height: 2.75rem;
  margin: 0 auto;
  padding: var(--space-2) var(--space-4);
  color: var(--color-surface-ink);
  font-weight: 700;
  background: var(--color-signal-info-cyan);
  border: 0;
  border-radius: var(--radius-control);
}

@media (max-width: 47.999rem) {
  .plan-drafting-view {
    padding: var(--space-4);
  }
}
</style>
