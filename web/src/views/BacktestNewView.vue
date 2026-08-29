<script setup lang="ts">
import { onBeforeUnmount, onMounted, useTemplateRef } from "vue";
import { isNavigationFailure, useRouter } from "vue-router";

import type { BacktestJobReceipt } from "../api/generated";
import type { BacktestApi } from "../api/backtests";
import BacktestRunForm from "../components/backtests/BacktestRunForm.vue";
import { useBacktestRunForm } from "../composables/useBacktestRunForm";

interface Props {
  api?: BacktestApi;
  createIdempotencyKey?: () => string;
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
        <p class="backtest-new-view__eyebrow">OFFLINE RESEARCH RUN</p>
        <h1 ref="pageTitle" tabindex="-1">创建回测</h1>
        <p>选择不可变计划版本与已验证数据集，提交可复现的回测运行。</p>
      </div>
      <a href="/backtests">返回回测研究台</a>
    </header>

    <aside class="backtest-new-view__boundary" aria-label="研究边界">
      仅供研究与回放，不连接券商、不自动下单。浏览器不推断计划资格、交易日历、T+1、成交或指标。
    </aside>

    <BacktestRunForm
      :draft="form.draft.value"
      :error-revision="form.errorRevision.value"
      :errors="form.errors.value"
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
  gap: var(--space-6);
  width: min(100%, 90rem);
  margin-inline: auto;
  padding: var(--space-6);
  color: var(--color-text-mineral);
}

.backtest-new-view__hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.backtest-new-view__hero h1,
.backtest-new-view__hero p,
.backtest-new-view__submission p {
  margin: 0;
}

.backtest-new-view__hero h1 {
  font-size: clamp(2rem, 5vw, 4rem);
  line-height: 1;
}

.backtest-new-view__eyebrow {
  color: var(--color-signal-info-cyan);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.backtest-new-view__hero a,
.backtest-new-view__submission button {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
}

.backtest-new-view__boundary,
.backtest-new-view__submission {
  padding: var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
}

.backtest-new-view__boundary {
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
    padding: var(--space-4);
  }

  .backtest-new-view__hero {
    flex-direction: column;
  }
}
</style>
