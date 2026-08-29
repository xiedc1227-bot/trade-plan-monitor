<script setup lang="ts">
import type { BacktestRunSummaryView } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";
import type { BacktestRunsQueryState } from "../../composables/useBacktestRuns";

interface Props {
  errorMessage: string | null;
  hasMore: boolean;
  items: readonly BacktestRunSummaryView[];
  pageNumber: number;
  queryState: BacktestRunsQueryState;
}

interface Emits {
  firstPage: [];
  nextPage: [];
  refresh: [];
}

defineProps<Props>();
const emit = defineEmits<Emits>();

function visibleShanghaiTime(value: string): string {
  return `${value.slice(0, 10)} ${value.slice(11, 19)}`;
}
</script>

<template>
  <section class="run-table" aria-labelledby="run-table-title">
    <header class="run-table__header">
      <div>
        <p class="run-table__eyebrow">MATERIALIZED RESEARCH RUNS</p>
        <h2 id="run-table-title">已完成运行</h2>
      </div>
      <button data-testid="refresh-run-list" type="button" @click="emit('refresh')">
        刷新当前页
      </button>
    </header>

    <div
      v-if="queryState === 'LOADING'"
      class="run-table__state"
      data-testid="run-list-state"
      role="status"
      aria-live="polite"
    >
      正在读取运行记录…
    </div>
    <div
      v-else-if="queryState === 'EMPTY'"
      class="run-table__state"
      data-testid="run-list-state"
      role="status"
    >
      暂无回测运行
    </div>
    <div
      v-else-if="queryState === 'FAILED'"
      class="run-table__state run-table__state--error"
      role="alert"
    >
      {{ errorMessage }}
    </div>

    <div
      v-else-if="queryState === 'READY'"
      class="run-table__scroll"
      role="region"
      aria-label="回测运行记录，可横向滚动"
      tabindex="0"
    >
      <table>
        <thead>
          <tr>
            <th scope="col" aria-sort="descending">完成时间</th>
            <th scope="col">股票</th>
            <th scope="col">运行 ID</th>
            <th scope="col">区间</th>
            <th scope="col">最终权益（元）</th>
            <th scope="col">总收益率</th>
            <th scope="col">成交数</th>
            <th scope="col">固定</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in items" :key="run.runId" data-testid="backtest-run-row">
            <td>
              <time :datetime="run.completedAt">{{ visibleShanghaiTime(run.completedAt) }}</time>
            </td>
            <td>{{ run.symbol }}</td>
            <td>
              <a
                :href="`/backtests/${run.runId}`"
                class="run-table__run-link"
                data-testid="run-detail-link"
              >
                {{ run.runId }}
              </a>
            </td>
            <td>{{ run.eventStart }} 至 {{ run.eventEnd }}</td>
            <td class="run-table__number">{{ formatFenAsYuan(run.metrics.finalEquityFen) }}</td>
            <td class="run-table__number">{{ run.metrics.totalReturn }}</td>
            <td class="run-table__number">{{ run.fillCount }}</td>
            <td>{{ run.pinned ? "已固定" : "未固定" }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav class="run-table__pagination" aria-label="运行记录分页">
      <button
        type="button"
        :disabled="pageNumber === 1 || queryState === 'LOADING'"
        @click="emit('firstPage')"
      >
        返回第一页
      </button>
      <span aria-live="polite">第 {{ pageNumber }} 页</span>
      <button
        data-testid="next-run-page"
        type="button"
        :disabled="!hasMore || queryState === 'LOADING'"
        @click="emit('nextPage')"
      >
        下一页
      </button>
    </nav>
  </section>
</template>

<style scoped>
.run-table {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-6);
  border: var(--border-technical);
  background: var(--color-surface-graphite);
}

.run-table__header,
.run-table__pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.run-table__header h2,
.run-table__header p,
.run-table__state {
  margin: 0;
}

.run-table__eyebrow {
  color: var(--color-signal-watch-amber);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.run-table__scroll {
  overflow-x: auto;
}

.run-table table {
  width: 100%;
  min-width: 72rem;
  border-collapse: collapse;
}

.run-table th,
.run-table td {
  padding: var(--space-3);
  border-block-end: var(--border-technical);
  text-align: start;
  vertical-align: top;
}

.run-table th {
  color: var(--color-text-muted);
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.run-table__run-link {
  display: inline-block;
  max-width: 18rem;
  overflow-wrap: anywhere;
  color: var(--color-signal-info-cyan);
}

.run-table__number {
  font-variant-numeric: tabular-nums;
}

.run-table__state {
  padding: var(--space-5);
  border: var(--border-technical);
  color: var(--color-text-muted);
}

.run-table__state--error {
  border-inline-start: 0.3rem solid var(--color-signal-risk-vermilion);
  color: var(--color-signal-risk-vermilion);
}

.run-table button {
  min-height: 2.75rem;
  padding: 0 var(--space-4);
  border: var(--border-technical);
  background: var(--color-surface-raised);
  color: var(--color-text-mineral);
  cursor: pointer;
}

.run-table button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.run-table :focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}

@media (max-width: 47.9375rem) {
  .run-table {
    padding: var(--space-4);
  }

  .run-table__header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
