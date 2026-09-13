<script setup lang="ts">
import { computed } from "vue";

import type { PlanVersionPage, PlanVersionSummary } from "../../api/generated";
import type { BacktestPlanVersionState } from "../../composables/useBacktestPlanVersions";

interface Props {
  disabled: boolean;
  error: string | null;
  fieldError?: string | undefined;
  page: PlanVersionPage | null;
  selectedId: string;
  selectedVersion: PlanVersionSummary | null;
  state: BacktestPlanVersionState;
}

interface Emits {
  nextPage: [];
  previousPage: [];
  retry: [];
  select: [versionId: string];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const items = computed(() => props.page?.items ?? []);
const selectedOutsidePage = computed(
  () =>
    props.selectedVersion !== null &&
    !items.value.some((item) => item.id === props.selectedVersion?.id),
);
const pageNumber = computed(() =>
  props.page === null ? 1 : Math.floor(props.page.offset / props.page.limit) + 1,
);
const pageCount = computed(() =>
  props.page === null ? 1 : Math.max(1, Math.ceil(props.page.total / props.page.limit)),
);
const previousDisabled = computed(
  () => props.disabled || props.state === "LOADING" || (props.page?.offset ?? 0) === 0,
);
const nextDisabled = computed(
  () =>
    props.disabled ||
    props.state === "LOADING" ||
    props.page === null ||
    props.page.offset + props.page.limit >= props.page.total,
);
const describedBy = computed(() =>
  props.fieldError === undefined
    ? "plan-version-id-help plan-version-status"
    : "plan-version-id-help plan-version-status plan-version-id-error",
);

function selectedValue(event: Event): string {
  return (event.currentTarget as HTMLSelectElement).value;
}

function optionLabel(version: PlanVersionSummary): string {
  return `${version.symbol} · ${version.planId} · v${version.version} · ${version.status} · ${version.planHash.slice(0, 12)}`;
}
</script>

<template>
  <div class="plan-version-selector">
    <label for="plan-version-id">计划版本（必填）</label>
    <select
      id="plan-version-id"
      :aria-describedby="describedBy"
      :aria-invalid="fieldError === undefined ? undefined : 'true'"
      :disabled="disabled"
      :value="selectedId"
      @change="emit('select', selectedValue($event))"
    >
      <option value="">请选择后端允许用于回测的计划版本</option>
      <option
        v-if="selectedOutsidePage && selectedVersion !== null"
        :value="selectedVersion.id"
      >
        {{ optionLabel(selectedVersion) }} · 已选择
      </option>
      <option v-for="version in items" :key="version.id" :value="version.id">
        {{ optionLabel(version) }}
      </option>
    </select>
    <p id="plan-version-id-help" class="plan-version-selector__help">
      仅列出后端判定可用于回测（canActivate=true）的真实不可变版本；计划无需已经启用。
      提交时冻结所选版本，之后保存新版本不会改变旧回测。
    </p>
    <p
      id="plan-version-status"
      class="plan-version-selector__status"
      data-testid="plan-version-status"
      role="status"
      aria-live="polite"
    >
      <template v-if="state === 'LOADING'">正在加载计划版本</template>
      <template v-else-if="state === 'FAILED'">{{ error }}</template>
      <template v-else-if="state === 'EMPTY'">暂无后端允许用于回测的计划版本，请先保存并完成审核。</template>
      <template v-else-if="page !== null">共 {{ page.total }} 个可用版本</template>
      <template v-else>等待加载计划版本</template>
    </p>
    <p v-if="fieldError" id="plan-version-id-error" class="plan-version-selector__error">
      {{ fieldError }}
    </p>
    <div class="plan-version-selector__pagination" aria-label="计划版本分页">
      <button
        data-testid="previous-plan-version-page"
        type="button"
        :disabled="previousDisabled"
        @click="emit('previousPage')"
      >
        上一页
      </button>
      <span data-testid="plan-version-page-number" aria-current="page">
        {{ pageNumber }} / {{ pageCount }}
      </span>
      <button
        data-testid="next-plan-version-page"
        type="button"
        :disabled="nextDisabled"
        @click="emit('nextPage')"
      >
        下一页
      </button>
      <button
        v-if="state === 'FAILED'"
        data-testid="retry-plan-version-page"
        type="button"
        :disabled="disabled"
        @click="emit('retry')"
      >
        重试
      </button>
    </div>
  </div>
</template>

<style scoped>
.plan-version-selector {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  gap: var(--space-2);
  padding: var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-raised);
}

.plan-version-selector label {
  font-weight: 700;
}

.plan-version-selector select,
.plan-version-selector button {
  min-height: 2.75rem;
  border: var(--border-technical);
  background: var(--color-surface-graphite);
  color: var(--color-text-mineral);
}

.plan-version-selector select {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding-inline: var(--space-3);
}

.plan-version-selector button {
  min-width: 5.5rem;
  padding-inline: var(--space-3);
}

.plan-version-selector__help,
.plan-version-selector__status,
.plan-version-selector__error {
  margin: 0;
  font-size: 0.875rem;
  overflow-wrap: anywhere;
}

.plan-version-selector__help,
.plan-version-selector__status {
  color: var(--color-text-muted);
}

.plan-version-selector__error {
  color: var(--color-signal-risk-vermilion);
}

.plan-version-selector__pagination {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.plan-version-selector :disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.plan-version-selector :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 47.9375rem) {
  .plan-version-selector__pagination button {
    flex: 1 1 7rem;
    min-width: 0;
    overflow-wrap: anywhere;
  }
}

@media (max-width: 30rem) {
  .plan-version-selector {
    padding-inline: var(--space-2);
  }
}

@media (prefers-reduced-motion: reduce) {
  .plan-version-selector,
  .plan-version-selector * {
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
    transition-duration: 0.01ms;
  }
}
</style>
