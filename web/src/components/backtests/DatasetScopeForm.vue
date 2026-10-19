<script setup lang="ts">
import { shallowRef, watch } from "vue";
import { isCalendarDate } from "../../api/shanghaiTime";
import type { DatasetUrlFilters } from "../../composables/useBacktestData";

const props = defineProps<{ filters: DatasetUrlFilters }>();
const emit = defineEmits<{ applyFilters: [filters: DatasetUrlFilters] }>();
const symbol = shallowRef("");
const start = shallowRef("");
const end = shallowRef("");
const error = shallowRef<string | null>(null);
watch(() => props.filters, filters => {
  symbol.value = filters.symbol ?? "";
  start.value = filters.startOnOrAfter ?? "";
  end.value = filters.endOnOrBefore ?? "";
  error.value = null;
}, { immediate: true });

function applyFilters() {
  const code = symbol.value.trim().toUpperCase();
  const from = start.value.trim(), to = end.value.trim();
  if (code && !/^[0-9]{6}\.(?:SH|SZ)$/.test(code)) { error.value = "筛选代码必须是 .SH 或 .SZ A 股代码"; return; }
  if (from && !isCalendarDate(from) || to && !isCalendarDate(to)) { error.value = "筛选日期必须是有效的 YYYY-MM-DD"; return; }
  if (from && to && from > to) { error.value = "筛选开始日期不得晚于结束日期"; return; }
  error.value = null;
  emit("applyFilters", { symbol: code || null, startOnOrAfter: from || null, endOnOrBefore: to || null });
}
</script>

<template>
  <section class="dataset-filters">
    <p>开始回测后，程序会自动检查本地行情、补齐缺失历史数据并验证，无需在此准备数据。</p>
    <form aria-labelledby="dataset-filter-title" @submit.prevent="applyFilters">
      <h2 id="dataset-filter-title">已验证数据集筛选</h2>
      <div class="dataset-filters__fields">
        <label>股票代码<input v-model="symbol" autocomplete="off" placeholder="000001.SZ" /></label>
        <label>开始不早于<input v-model="start" inputmode="numeric" placeholder="YYYY-MM-DD" /></label>
        <label>结束不晚于<input v-model="end" inputmode="numeric" placeholder="YYYY-MM-DD" /></label>
        <button type="submit" data-testid="apply-dataset-filters">查询</button>
      </div>
      <p v-if="error" role="alert">{{ error }}</p>
    </form>
  </section>
</template>

<style scoped>
.dataset-filters { padding: var(--space-6); border: var(--border-technical); background: var(--color-surface-graphite); }
.dataset-filters__fields { display: flex; align-items: end; flex-wrap: wrap; gap: var(--space-3); }
.dataset-filters__fields label { display: grid; gap: var(--space-2); min-width: 0; flex: 1 1 12rem; }
.dataset-filters__fields input, .dataset-filters__fields button { min-height: 2.75rem; box-sizing: border-box; max-width: 100%; padding: var(--space-2) var(--space-3); border: var(--border-technical); background: var(--color-surface-raised); color: var(--color-text-mineral); }
.dataset-filters__fields input { min-width: 0; width: 100%; }
.dataset-filters :focus-visible { outline: 3px solid var(--color-focus-ring); outline-offset: 2px; }
</style>
