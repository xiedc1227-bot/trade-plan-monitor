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
const completedFrom = shallowRef("");
const completedTo = shallowRef("");
const eventEndFrom = shallowRef("");
const eventEndTo = shallowRef("");
const pinned = shallowRef("");
const errors = shallowRef<Partial<RunFilterErrors>>({});

watch(
  () => props.filters,
  (filters) => {
    symbol.value = filters.symbol ?? "";
    completedFrom.value = filters.completedFrom ?? "";
    completedTo.value = filters.completedTo ?? "";
    eventEndFrom.value = filters.eventEndFrom ?? "";
    eventEndTo.value = filters.eventEndTo ?? "";
    pinned.value = filters.pinned === null ? "" : filters.pinned ? "true" : "false";
    errors.value = {};
  },
  { deep: true, immediate: true },
);

async function apply(): Promise<void> {
  const draft: RunFilterDraft = {
    eventEndFrom: eventEndFrom.value,
    eventEndTo: eventEndTo.value,
    completedFrom: completedFrom.value,
    completedTo: completedTo.value,
    pinned: pinned.value,
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
    eventEndFrom: "run-filter-end-from",
    eventEndTo: "run-filter-end-to",
    completedFrom: "run-filter-completed-from",
    completedTo: "run-filter-completed-to",
    pinned: "run-filter-pinned",
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
        <h2 id="run-filters-title">运行记录筛选</h2>
      </div>
      <p>组合筛选条件，找到需要核对的回测记录。</p>
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

    <p class="run-filters__hint">日期统一按回测覆盖的截止日筛选，不是程序实际完成运行的日期。</p>
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
        <label for="run-filter-end-from">回测截止日期从 <span>可选，包含当天</span></label>
        <input
          type="date"
          id="run-filter-end-from"
          v-model="eventEndFrom"
          :aria-invalid="fieldError('eventEndFrom') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('eventEndFrom') === undefined ? undefined : 'run-filter-end-from-error'"
          autocomplete="off"
        />
        <p
          v-if="fieldError('eventEndFrom')"
          id="run-filter-end-from-error"
          class="run-filters__field-error"
        >
          {{ fieldError("eventEndFrom") }}
        </p>
      </div>
      <div class="run-filters__field">
        <label for="run-filter-end-to">回测截止日期至 <span>可选，包含当天</span></label>
        <input
          type="date"
          id="run-filter-end-to"
          v-model="eventEndTo"
          :aria-invalid="fieldError('eventEndTo') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('eventEndTo') === undefined ? undefined : 'run-filter-end-to-error'"
          autocomplete="off"
        />
        <p
          v-if="fieldError('eventEndTo')"
          id="run-filter-end-to-error"
          class="run-filters__field-error"
        >
          {{ fieldError("eventEndTo") }}
        </p>
      </div>
      <div class="run-filters__field">
        <label for="run-filter-pinned">保留状态 <span>可选，已保留记录的明细不会被常规过期清理。</span></label>
        <select
          id="run-filter-pinned"
          v-model="pinned"
          :aria-invalid="fieldError('pinned') === undefined ? undefined : 'true'"
          :aria-describedby="fieldError('pinned') === undefined ? undefined : 'run-filter-pinned-error'"
        >
          <option value="">全部</option>
          <option value="true">仅已保留</option>
          <option value="false">仅未保留</option>
        </select>
        <p v-if="fieldError('pinned')" id="run-filter-pinned-error" class="run-filters__field-error">
          {{ fieldError("pinned") }}
        </p>
      </div>

      <details v-if="props.filters.completedFrom || props.filters.completedTo" class="run-filters__extra" data-testid="legacy-run-filters" open>
        <summary>旧链接时间条件</summary>
        <div v-if="props.filters.completedFrom || props.filters.completedTo" class="run-filters__legacy-times">
          <p>当前链接保留旧结果时间条件。连续回测的旧结果时间是证据截止时间，不是实际完成时间；可清空后改用上方日期。</p>
          <div class="run-filters__field">
            <label for="run-filter-completed-from">旧结果时间从 <span>可选，RFC 3339 +08:00</span></label>
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
            <label for="run-filter-completed-to">旧结果时间至 <span>可选，RFC 3339 +08:00</span></label>
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
        </div>
      </details>
      <div class="run-filters__footer">
        <p>按结果时间倒序显示。连续回测的结果时间为证据截止时间，不代表程序实际完成时间。</p>
        <button data-testid="apply-run-filters" type="submit">查询</button>
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
  border-radius: var(--radius-panel);
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

.run-filters__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}

.run-filters__header p {
  color: var(--color-text-muted);
  font-size: .875rem;
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

.run-filters__hint { margin: 0; color: var(--color-text-muted); font-size: .875rem; }
.run-filters__extra, .run-filters__footer { grid-column: 1 / -1; }
.run-filters__extra { border-top: var(--border-technical); padding-top: var(--space-3); }
.run-filters__extra summary { cursor: pointer; min-height: 2.75rem; }
.run-filters__extra p, .run-filters__footer p { color: var(--color-text-muted); font-size: .875rem; }
.run-filters__extra .run-filters__field { max-width: 40rem; margin-top: var(--space-3); }
.run-filters__footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); }
.run-filters__footer p { flex: 1 1 18rem; margin: 0; }

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
