<script setup lang="ts">
import { nextTick, shallowRef, useTemplateRef, watch } from "vue";

import type {
  BacktestRunSort,
  RunFilterDraft,
  RunFilterErrors,
  RunUrlFilters,
} from "../../composables/useBacktestRuns";
import { validateRunFilterDraft } from "../../composables/useBacktestRuns";

interface Props {
  filters: RunUrlFilters;
  sort: BacktestRunSort;
}

interface Emits {
  apply: [filters: RunUrlFilters];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();
const errorSummary = useTemplateRef<HTMLDivElement>("errorSummary");

const symbol = shallowRef("");
const planVersionId = shallowRef("");
const datasetHash = shallowRef("");
const completedFrom = shallowRef("");
const completedTo = shallowRef("");
const pinned = shallowRef("");
const errors = shallowRef<Partial<RunFilterErrors>>({});

watch(
  () => props.filters,
  (filters) => {
    symbol.value = filters.symbol ?? "";
    planVersionId.value = filters.planVersionId ?? "";
    datasetHash.value = filters.datasetHash ?? "";
    completedFrom.value = filters.completedFrom ?? "";
    completedTo.value = filters.completedTo ?? "";
    pinned.value = filters.pinned === null ? "" : filters.pinned ? "true" : "false";
    errors.value = {};
  },
  { deep: true, immediate: true },
);

async function apply(): Promise<void> {
  const draft: RunFilterDraft = {
    completedFrom: completedFrom.value,
    completedTo: completedTo.value,
    datasetHash: datasetHash.value,
    pinned: pinned.value,
    planVersionId: planVersionId.value,
    symbol: symbol.value,
  };
  const validation = validateRunFilterDraft(draft);
  errors.value = validation.errors;
  if (Object.keys(validation.errors).length > 0) {
    await nextTick();
    errorSummary.value?.focus();
    return;
  }
  emit("apply", validation.filters);
}

function errorTarget(field: string): string {
  const targets: Record<string, string> = {
    completedFrom: "run-filter-completed-from",
    completedTo: "run-filter-completed-to",
    datasetHash: "run-filter-dataset-hash",
    pinned: "run-filter-pinned",
    planVersionId: "run-filter-plan-version",
    range: "run-filter-completed-from",
    symbol: "run-filter-symbol",
  };
  return targets[field] ?? "run-filter-symbol";
}

function fieldError(field: keyof RunFilterDraft): string | undefined {
  if (field === "completedFrom") return errors.value.completedFrom ?? errors.value.range;
  return errors.value[field];
}
</script>

<template>
  <section class="run-filters" aria-labelledby="run-filters-title">
    <header class="run-filters__header">
      <div>
        <p class="run-filters__eyebrow">URL FILTERS</p>
        <h2 id="run-filters-title">运行记录筛选</h2>
      </div>
      <p>筛选、排序、页码与游标始终写入当前 URL。</p>
    </header>

    <div
      v-if="Object.keys(errors).length > 0"
      ref="errorSummary"
      class="run-filters__errors"
      data-testid="run-filter-errors"
      role="alert"
      tabindex="-1"
    >
      <h3>请修正以下筛选条件</h3>
      <ul>
        <li v-for="(message, field) in errors" :key="field">
          <a :href="`#${errorTarget(field)}`">{{ message }}</a>
        </li>
      </ul>
    </div>

    <form class="run-filters__grid" @submit.prevent="apply">
      <div class="run-filters__field">
        <label for="run-filter-symbol">股票代码 <span>可选，例如 000001.SZ</span></label>
        <input
          id="run-filter-symbol"
          v-model="symbol"
          :aria-invalid="fieldError('symbol') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('symbol') === undefined ? undefined : 'run-filter-symbol-error'"
          autocomplete="off"
        />
        <p v-if="fieldError('symbol')" id="run-filter-symbol-error" class="run-filters__field-error">
          {{ fieldError("symbol") }}
        </p>
      </div>
      <div class="run-filters__field">
        <label for="run-filter-plan-version">计划版本 ID <span>可选，RFC 4122 UUID</span></label>
        <input
          id="run-filter-plan-version"
          v-model="planVersionId"
          :aria-invalid="fieldError('planVersionId') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('planVersionId') === undefined ? undefined : 'run-filter-plan-version-error'"
          autocomplete="off"
        />
        <p
          v-if="fieldError('planVersionId')"
          id="run-filter-plan-version-error"
          class="run-filters__field-error"
        >
          {{ fieldError("planVersionId") }}
        </p>
      </div>
      <div class="run-filters__field">
        <label for="run-filter-dataset-hash">数据集哈希 <span>可选，64 位 SHA-256</span></label>
        <input
          id="run-filter-dataset-hash"
          v-model="datasetHash"
          :aria-invalid="fieldError('datasetHash') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('datasetHash') === undefined ? undefined : 'run-filter-dataset-hash-error'"
          autocomplete="off"
        />
        <p
          v-if="fieldError('datasetHash')"
          id="run-filter-dataset-hash-error"
          class="run-filters__field-error"
        >
          {{ fieldError("datasetHash") }}
        </p>
      </div>
      <div class="run-filters__field">
        <label for="run-filter-completed-from">完成开始时间 <span>可选，RFC 3339 +08:00</span></label>
        <input
          id="run-filter-completed-from"
          v-model="completedFrom"
          :aria-invalid="fieldError('completedFrom') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('completedFrom') === undefined ? undefined : 'run-filter-completed-from-error'"
          autocomplete="off"
        />
        <p
          v-if="fieldError('completedFrom')"
          id="run-filter-completed-from-error"
          class="run-filters__field-error"
        >
          {{ fieldError("completedFrom") }}
        </p>
      </div>
      <div class="run-filters__field">
        <label for="run-filter-completed-to">完成结束时间 <span>可选，RFC 3339 +08:00</span></label>
        <input
          id="run-filter-completed-to"
          v-model="completedTo"
          :aria-invalid="fieldError('completedTo') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('completedTo') === undefined ? undefined : 'run-filter-completed-to-error'"
          autocomplete="off"
        />
        <p
          v-if="fieldError('completedTo')"
          id="run-filter-completed-to-error"
          class="run-filters__field-error"
        >
          {{ fieldError("completedTo") }}
        </p>
      </div>
      <div class="run-filters__field">
        <label for="run-filter-pinned">固定状态 <span>可选，服务端成员关系筛选</span></label>
        <select
          id="run-filter-pinned"
          v-model="pinned"
          :aria-invalid="fieldError('pinned') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('pinned') === undefined ? undefined : 'run-filter-pinned-error'"
        >
          <option value="">全部</option>
          <option value="true">仅已固定</option>
          <option value="false">仅未固定</option>
        </select>
        <p v-if="fieldError('pinned')" id="run-filter-pinned-error" class="run-filters__field-error">
          {{ fieldError("pinned") }}
        </p>
      </div>
      <div class="run-filters__field">
        <label for="run-filter-sort">排序 <span>服务端固定顺序</span></label>
        <select id="run-filter-sort" :value="sort" disabled>
          <option value="completedAt_desc">完成时间降序</option>
        </select>
      </div>
      <div class="run-filters__actions">
        <button data-testid="apply-run-filters" type="button" @click="apply">应用筛选</button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.run-filters {
  display: grid;
  gap: var(--space-5);
  padding: var(--space-6);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
}

.run-filters__header,
.run-filters__actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.run-filters__header h2,
.run-filters__header p,
.run-filters__errors h3 {
  margin: 0;
}

.run-filters__eyebrow {
  color: var(--color-signal-info-cyan);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.run-filters__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.run-filters__field {
  display: grid;
  min-width: 0;
  gap: var(--space-2);
}

.run-filters__field label {
  display: grid;
  gap: var(--space-1);
  font-weight: 700;
}

.run-filters__field label span {
  color: var(--color-text-muted);
  font-size: 0.875rem;
  font-weight: 400;
}

.run-filters input,
.run-filters select {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
}

.run-filters input,
.run-filters select,
.run-filters button {
  min-height: 2.75rem;
  padding: 0 var(--space-3);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
}

.run-filters button {
  cursor: pointer;
}

.run-filters select:disabled {
  opacity: 0.75;
}

.run-filters__actions {
  align-items: end;
}

.run-filters__errors {
  padding: var(--space-4);
  border-inline-start: 0.3rem solid var(--color-signal-risk-vermilion);
  background: rgb(228 93 67 / 12%);
  color: var(--color-signal-risk-vermilion);
}

.run-filters__errors a,
.run-filters__field-error {
  color: var(--color-signal-risk-vermilion);
}

.run-filters__field-error {
  margin: 0;
  font-size: 0.875rem;
}

.run-filters :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 70rem) {
  .run-filters__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 47.9375rem) {
  .run-filters {
    padding: var(--space-4);
  }

  .run-filters__header,
  .run-filters__actions {
    flex-direction: column;
  }

  .run-filters__grid {
    grid-template-columns: 1fr;
  }
}
</style>
