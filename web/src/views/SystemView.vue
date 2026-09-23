<script setup lang="ts">
import { computed } from "vue";

import type { RuntimeHealthResponse } from "../api/generated";
import type { LegacyPlanApi } from "../api/legacyPlans";
import HealthMatrix from "../components/health/HealthMatrix.vue";
import LegacyPlanInvalidationPanel from "../components/health/LegacyPlanInvalidationPanel.vue";
import MarketStatusStrip from "../components/health/MarketStatusStrip.vue";

interface Props {
  error?: string | null;
  health?: RuntimeHealthResponse | null;
  loading?: boolean;
  legacyApi?: LegacyPlanApi;
}

interface Emits {
  refresh: [];
  selectSymbol: [symbol: string];
}

const props = withDefaults(defineProps<Props>(), {
  error: null,
  health: null,
  loading: false,
});
const emit = defineEmits<Emits>();

const availableHealth = computed(() => props.health);
const hasError = computed(() => props.error !== null && props.error !== undefined);
const errorMessage = computed(() =>
  availableHealth.value === null
    ? "系统健康状态暂不可用。请稍后重试。"
    : "系统健康刷新失败，正在显示上一次安全快照。",
);
</script>

<template>
  <section class="system-view" aria-labelledby="system-view-title">
    <header class="system-view__header">
      <div>
        <p class="system-view__eyebrow">本地运行诊断</p>
        <h1 id="system-view-title" class="system-view__title">系统健康</h1>
        <p class="system-view__description">
          展示后端提供的运行状态、能力探测和资源事实；不显示密钥或供应商原始错误。
        </p>
      </div>
      <button
        class="system-view__refresh"
        data-testid="refresh-system-health"
        type="button"
        :disabled="props.loading"
        @click="emit('refresh')"
      >
        {{ props.loading ? "刷新中" : "刷新健康状态" }}
      </button>
    </header>

    <p v-if="hasError" class="system-view__error" role="alert">
      {{ errorMessage }}
    </p>
    <p
      v-if="props.loading"
      class="system-view__loading"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      正在读取系统健康状态。
    </p>

    <template v-if="availableHealth !== null">
      <LegacyPlanInvalidationPanel
        v-if="availableHealth.status === 'BLOCKED' &&
          availableHealth.blockReason === 'LEGACY_PLANS_REQUIRE_REVIEW'"
        :api="props.legacyApi"
        @completed="emit('refresh')"
      />
      <MarketStatusStrip :health="availableHealth" />
      <HealthMatrix
        :health="availableHealth"
        @select-symbol="emit('selectSymbol', $event)"
      />
    </template>
    <p
      v-else-if="!props.loading && !hasError"
      class="system-view__empty"
      data-testid="system-empty"
    >
      尚无系统健康快照。
    </p>
  </section>
</template>

<style scoped>
.system-view {
  display: grid;
  gap: var(--space-6);
  min-width: 0;
  color: var(--color-text-mineral);
}

.system-view__header {
  display: grid;
  gap: var(--space-4);
  align-items: end;
}

.system-view__eyebrow,
.system-view__title,
.system-view__description,
.system-view__error,
.system-view__loading,
.system-view__empty {
  margin: 0;
}

.system-view__eyebrow {
  color: var(--color-signal-info-cyan);
  font-family: var(--font-numeric);
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.system-view__title {
  margin-block-start: var(--space-2);
  font-size: clamp(1.6rem, 5vw, 2.25rem);
}

.system-view__description {
  max-width: 52rem;
  margin-block-start: var(--space-2);
  color: var(--color-text-muted);
  line-height: 1.6;
}

.system-view__refresh {
  min-width: 2.75rem;
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-4);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
  transition: border-color 150ms ease, background-color 150ms ease;
}

.system-view__refresh:disabled {
  color: var(--color-text-muted);
  cursor: wait;
}

.system-view__refresh:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

.system-view__error,
.system-view__loading,
.system-view__empty {
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: var(--border-technical);
  border-inline-start: 0.3rem solid var(--color-signal-info-cyan);
}

.system-view__error {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.system-view__loading,
.system-view__empty {
  border-inline-start-color: var(--color-signal-watch-amber);
}

@media (min-width: 20rem) {
  .system-view {
    padding-inline: 0;
  }
}

@media (min-width: 48rem) {
  .system-view__header {
    grid-template-columns: minmax(0, 1fr) auto;
  }
}

@media (min-width: 64rem) {
  .system-view {
    gap: 2rem;
  }
}

@media (min-width: 90rem) {
  .system-view {
    max-width: 88rem;
    margin-inline: auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .system-view,
  .system-view *,
  .system-view *::before,
  .system-view *::after {
    scroll-behavior: auto;
    transition-duration: 0.01ms;
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
  }
}
</style>
