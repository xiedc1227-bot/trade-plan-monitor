<script setup lang="ts">
import type { AIPlanApi } from "../api/ai";
import PlanWorkbench from "../components/plans/PlanWorkbench.vue";
import { usePlanDrafting } from "../composables/usePlanDrafting";

interface Props {
  api?: AIPlanApi;
  createIdempotencyKey?: () => string;
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
</script>

<template>
  <main class="plan-drafting-view">
    <header class="plan-drafting-view__header">
      <p>CONFIG-DRIVEN AI DRAFTING</p>
      <h1>计划工作台</h1>
    </header>
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
        :providers="[drafting.runtime.value]"
        :submitting="drafting.submitting.value"
        @stop-waiting="drafting.stopWaiting"
        @submit-extraction="drafting.submitExtraction"
      >
        <template #extractedDraft="{ extraction }">
          <section class="plan-drafting-view__draft" aria-labelledby="extracted-draft-title">
            <h2 id="extracted-draft-title">待审核计划草稿</h2>
            <pre>{{ extraction.draftPlanJson }}</pre>
          </section>
        </template>
      </PlanWorkbench>
    </template>
  </main>
</template>

<style scoped>
.plan-drafting-view {
  box-sizing: border-box;
  width: 100%;
  padding: var(--space-6);
  color: var(--color-text-mineral);
}

.plan-drafting-view__notice,
.plan-drafting-view__error,
.plan-drafting-view__draft {
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

.plan-drafting-view__header p {
  color: var(--color-signal-info-cyan);
  font-family: var(--font-numeric);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
}

.plan-drafting-view__notice {
  border-inline-start: 0.25rem solid var(--color-signal-info-cyan);
}

.plan-drafting-view__error {
  border-inline-start: 0.25rem solid var(--color-signal-risk-vermilion);
}

.plan-drafting-view__draft pre {
  max-height: 32rem;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

@media (max-width: 47.999rem) {
  .plan-drafting-view {
    padding: var(--space-4);
  }
}
</style>
