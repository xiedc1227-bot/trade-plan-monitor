<script setup lang="ts">
import type { BacktestRunPage } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";
import type { BacktestRunsQueryState } from "../../composables/useBacktestRuns";
import { backtestPercent } from "../../composables/backtestNavigation";
import { formatDisplayDateTime } from "../../formatters/dateTime";
const props = defineProps<{ errorMessage: string | null; hasMore: boolean; hasPrevious?: boolean; hasFilters?: boolean;
  items: readonly BacktestRunPage["items"][number][]; pageNumber: number; queryState: BacktestRunsQueryState; refreshing?: boolean }>();
const emit = defineEmits<{ firstPage: []; nextPage: []; previousPage: []; refresh: []; open: [runId: string, event: MouseEvent] }>();
function metrics(run: BacktestRunPage["items"][number]) {
  if ("schemaVersion" in run) return { pnl: run.metrics.cost_pnl_fen, fees: run.metrics.paid_fees_fen, ratio: run.metrics.interval_return, equity: run.metrics.final_equity_fen };
  return { pnl: "realizedPnlFen" in run.metrics ? run.metrics.realizedPnlFen : null, fees: run.metrics.totalCostFen, ratio: run.metrics.totalReturn, equity: run.metrics.finalEquityFen };
}
const money = (v: number | string | null) => v === null ? "不可用" : `${formatFenAsYuan(String(v))} 元`;
</script>
<template>
  <section class="run-table" aria-labelledby="run-table-title" :aria-busy="refreshing || queryState === 'LOADING'">
    <header class="run-table__header"><h2 id="run-table-title">已完成运行 <small v-if="items.length">本页 {{ items.length }} 条</small></h2>
      <button data-testid="refresh-run-list" type="button" :disabled="refreshing || queryState === 'LOADING'" @click="emit('refresh')">刷新当前页</button></header>
    <p v-if="queryState === 'LOADING'" data-testid="run-list-state" role="status">正在读取运行记录…</p>
    <div v-if="queryState === 'FAILED'" class="run-table__error" role="alert"><p>{{ errorMessage }}</p><p v-if="items.length">以下为上次读取的数据。</p><button @click="emit('refresh')">重新读取运行记录</button></div>
    <div v-else-if="queryState === 'EMPTY'" data-testid="run-list-state"><p>{{ hasFilters ? '没有符合当前筛选条件的运行记录，请清空筛选后查看。' : '暂无回测运行' }}</p><a v-if="!hasFilters" href="/backtests/new">新建回测</a></div>
    <div v-if="items.length" class="run-table__scroll" role="region" aria-label="回测运行记录，可横向滚动" tabindex="0">
      <table><caption>按结果时间倒序排列；结果时间不代表程序实际完成时间。</caption>
        <thead><tr><th scope="col" aria-sort="descending">股票与区间／结果时间</th><th scope="col">结果摘要</th><th scope="col">成交数</th><th scope="col">保留状态</th><th scope="col">操作</th></tr></thead>
        <tbody><tr v-for="run in items" :key="run.runId" data-testid="backtest-run-row">
          <td><strong>{{ run.symbol }}</strong><p>{{ run.eventStart }} 至 {{ run.eventEnd }}</p><details><summary>运行 {{ run.runId.slice(-8) }} · 查看标识</summary><p class="run-table__identity">{{ run.runId }}</p><p>结果时间 <time :datetime="run.completedAt">{{ formatDisplayDateTime(run.completedAt) }}</time></p></details></td>
          <td><strong v-if="metrics(run).pnl !== null">{{ 'schemaVersion' in run ? '成本口径损益' : '已实现损益' }} {{ money(metrics(run).pnl) }}</strong><strong v-else>最终权益 {{ money(metrics(run).equity) }}</strong><p>费用 {{ money(metrics(run).fees) }}</p><p v-if="metrics(run).ratio !== null">收益率 {{ backtestPercent(metrics(run).ratio) }}</p><p v-else class="run-table__hint">收益率不可用，资金或估值口径详见结果。</p><details><summary>更多指标</summary><p>最终权益 {{ money(metrics(run).equity) }}</p><p>收益率原始比例 {{ metrics(run).ratio ?? "不可用" }}</p></details></td>
          <td>{{ run.fillCount }}</td><td>{{ run.pinned ? '已保留' : '未保留' }}</td>
          <td><a :href="`/backtests/${run.runId}`" :data-run-id="run.runId" data-testid="run-detail-link" @click="emit('open', run.runId, $event)" :aria-label="`查看 ${run.symbol} ${run.eventStart} 至 ${run.eventEnd} 的结果，运行 ${run.runId.slice(-8)}`">查看结果</a></td>
        </tr></tbody>
      </table>
    </div>
    <nav class="run-table__pagination" aria-label="运行记录分页">
      <button type="button" :disabled="pageNumber === 1 || queryState === 'LOADING' || refreshing" @click="emit('firstPage')">返回第一页</button>
      <button type="button" data-testid="previous-run-page" :disabled="!hasPrevious || queryState === 'LOADING' || refreshing" @click="emit('previousPage')">上一页</button>
      <span data-testid="run-page-number" aria-current="page" aria-live="polite">第 {{ pageNumber }} 页</span>
      <button data-testid="next-run-page" type="button" :disabled="!hasMore || queryState === 'LOADING' || refreshing" @click="emit('nextPage')">下一页</button>
    </nav>
  </section>
</template>
<style scoped>
.run-table { display: grid; gap: var(--space-3); padding: var(--space-4); border: var(--border-technical); background: var(--color-surface-graphite); min-width: 0; }
.run-table__header, .run-table__pagination { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.run-table__header { justify-content: space-between; }
.run-table h2, .run-table p { margin: 0; }
.run-table h2 { font-size: 1.1rem; } .run-table small, .run-table__hint { color: var(--color-text-muted); font-size: .8125rem; font-weight: 400; }
.run-table__scroll { overflow-x: auto; min-width: 0; }
.run-table table { width: 100%; min-width: 46rem; border-collapse: collapse; }
.run-table th, .run-table td { padding: var(--space-3); text-align: start; border-bottom: var(--border-technical); vertical-align: top; }
.run-table th, .run-table caption { color: var(--color-text-muted); font-size: .8125rem; text-align: start; }
.run-table td p { margin-top: var(--space-1); font-size: .875rem; }
.run-table__identity { overflow-wrap: anywhere; max-width: 22rem; }
.run-table button, .run-table a, .run-table summary { min-height: 2.75rem; display: inline-flex; align-items: center; }
.run-table button, .run-table a { color: inherit; padding: var(--space-2) var(--space-3); background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); cursor: pointer; }
.run-table summary { cursor: pointer; color: var(--color-text-muted); font-size: .8125rem; }
.run-table :focus-visible { outline: 3px solid var(--color-focus-ring); outline-offset: 3px; }
.run-table button:disabled { opacity: .55; cursor: not-allowed; }
.run-table__error { border-inline-start: 3px solid var(--color-signal-risk-vermilion); padding: var(--space-3); }
@media (max-width: 47.9375rem) { .run-table { padding: var(--space-3); } }
@media (prefers-reduced-motion: reduce) { .run-table * { scroll-behavior: auto; } }
.run-table__pagination { flex-wrap: wrap; justify-content: flex-start; }
</style>
