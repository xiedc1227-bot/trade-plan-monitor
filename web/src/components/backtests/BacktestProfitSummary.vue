<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";
import type { BacktestRunResult } from "../../api/backtests";
import { formatFenAsYuan } from "../../api/backtestValues";
import { formatDisplayDateTime } from "../../formatters/dateTime";

const props = defineProps<{ run: DeepReadonly<BacktestRunResult> }>();
const amounts = computed(() => {
  const { metrics } = props.run;
  if ("cost_pnl_fen" in metrics) return {
    total: metrics.cost_pnl_fen, realized: metrics.realized_pnl_fen, floating: metrics.unrealized_pnl_fen,
  };
  if ("realizedPnlFen" in metrics) return {
    total: BigInt(metrics.realizedPnlFen) + BigInt(metrics.unrealizedPnlFen),
    realized: metrics.realizedPnlFen, floating: metrics.unrealizedPnlFen,
  };
  return { total: null, realized: null, floating: null };
});
const cards = computed(() => [
  { key: "total", label: "总盈亏", value: amounts.value.total },
  { key: "realized", label: "已实现盈亏", value: amounts.value.realized },
  { key: "floating", label: "浮动盈亏", value: amounts.value.floating },
]);
const incomplete = computed(() => cards.value.some(card => card.value === null));
const evidenceCutoff = computed(() => "report" in props.run ? props.run.report.boundary.evidence_cutoff : null);
function money(value: string | number | bigint | null): string {
  if (value === null) return "暂不可用";
  const fen = BigInt(value);
  return `${fen > 0n ? "+" : ""}${formatFenAsYuan(fen)} 元`;
}
</script>

<template>
  <section class="profit-summary" aria-labelledby="profit-summary-title" data-testid="backtest-profit-summary">
    <h2 id="profit-summary-title" class="profit-summary__title">收益汇总</h2>
    <dl class="profit-summary__cards">
      <div v-for="card in cards" :key="card.key" class="profit-summary__card" :class="{ 'profit-summary__card--total': card.key === 'total' }">
        <dt class="profit-summary__label">{{ card.label }}</dt>
        <dd class="profit-summary__value" :data-testid="`profit-${card.key}`">{{ money(card.value) }}</dd>
      </div>
      <div class="profit-summary__card">
        <dt class="profit-summary__label">回测截止日期</dt>
        <dd class="profit-summary__value profit-summary__value--date" data-testid="profit-cutoff">
          <time :datetime="run.eventEnd">{{ run.eventEnd }}</time>
        </dd>
      </div>
    </dl>
    <p class="profit-summary__note">总盈亏为已实现盈亏与浮动盈亏的合计，沿用已计入成交费用的成本口径；统计截至回测结束，不是实时收益。</p>
    <p v-if="evidenceCutoff" class="profit-summary__note">实际证据截止（上海时间）：{{ formatDisplayDateTime(evidenceCutoff) }}</p>
    <p v-if="incomplete" class="profit-summary__note">部分盈亏数据尚不完整，缺失项不会按 0 元处理。</p>
  </section>
</template>

<style scoped>
.profit-summary { display: grid; gap: var(--space-3); min-width: 0; padding: var(--space-5); border: var(--border-technical); border-radius: var(--radius-panel); background: var(--color-surface-raised); }
.profit-summary__title { margin: 0; font-size: 1.2rem; }
.profit-summary__cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-3); margin: 0; }
.profit-summary__card { min-width: 0; padding: var(--space-4); border: var(--border-technical); border-radius: var(--radius-control); background: var(--color-surface-graphite); }
.profit-summary__card--total { border-color: var(--color-signal-watch-amber); }
.profit-summary__label { color: var(--color-text-muted); }
.profit-summary__value { margin: var(--space-2) 0 0; font-family: var(--font-numeric); font-size: clamp(1.1rem, 1.8vw, 1.7rem); font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.profit-summary__card--total .profit-summary__value { color: var(--color-signal-watch-amber); }
.profit-summary__value--date { font-size: clamp(1rem, 1.6vw, 1.4rem); }
.profit-summary__note { margin: 0; color: var(--color-text-muted); overflow-wrap: anywhere; }
@media (max-width: 64rem) { .profit-summary__cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 26rem) { .profit-summary { padding: var(--space-3); } .profit-summary__cards { grid-template-columns: minmax(0, 1fr); } }
</style>
