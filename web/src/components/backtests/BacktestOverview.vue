<script setup lang="ts">
import type { DeepReadonly } from "vue";
import type { BacktestLoopRunView, BacktestScheduledRunView, WorkbenchBacktestRunView } from "../../api/generated";
import { formatDisplayDateTime } from "../../formatters/dateTime";
import { formatFenAsYuan } from "../../api/backtestValues";
import BacktestCostSummary from "./BacktestCostSummary.vue";
defineProps<{ run: DeepReadonly<BacktestLoopRunView | BacktestScheduledRunView | WorkbenchBacktestRunView> }>();
const emit = defineEmits<{ navigate: [tab: "fills" | "reasons" | "provenance"] }>();
</script>

<template>
  <section class="review-overview" aria-label="回测结果概览" data-testid="backtest-overview">
    <h3>{{ run.symbol }} · {{ run.report.boundary.started_at.slice(0, 10) }} 至 {{ run.report.boundary.resolved_end_date }}</h3>
    <dl class="review-overview__facts">
      <div><dt>已模拟成交</dt><dd>{{ run.report.cycle.fills }} 笔</dd></div>
      <div><dt>未成交响应意图</dt><dd>{{ run.report.cycle.unfilled_intents }} 个</dd></div>
      <div><dt>期末持仓</dt><dd>{{ run.report.final_inventory.total_qty ?? '未知' }} 股</dd></div>
      <div><dt>累计费用</dt><dd>{{ formatFenAsYuan(String(run.metrics.paid_fees_fen)) }} 元</dd></div>
    </dl>
    <p v-if="run.openingAccount.cash.kind === 'POSITION_LIMIT_ONLY'">本次不限制现金，买入受授权及最大持仓限制。损益按成交成本核算，不计算本金收益率和净值回撤。</p>
    <dl v-else class="review-overview__facts">
      <div><dt>期末权益</dt><dd>{{ run.metrics.final_equity_fen === null ? '未知 / 不可用' : `${formatFenAsYuan(String(run.metrics.final_equity_fen))} 元` }}</dd></div>
      <div><dt>区间收益率（比例）</dt><dd>{{ run.metrics.interval_return ?? '未知 / 不可用' }}</dd></div>
    </dl>
    <p v-if="run.response.mode === 'OBSERVE_ONLY'">本次仅观察提醒，不会自动模拟成交。</p>
    <p v-else>响应方式：{{ run.response.mode === 'FOLLOW_REMINDERS' ? '跟随有效提醒' : '按记录动作' }} · 延迟 {{ run.response.response_delay_seconds ?? 0 }} 秒</p>
    <p class="review-overview__boundary">实际证据截止（上海时间）：<time :datetime="run.report.boundary.evidence_cutoff">{{ formatDisplayDateTime(run.report.boundary.evidence_cutoff) }}</time></p>
    <div class="review-overview__actions">
      <button type="button" @click="emit('navigate', 'fills')">查看成交与原因</button>
      <button type="button" @click="emit('navigate', 'reasons')">查看未成交原因</button>
      <button type="button" @click="emit('navigate', 'provenance')">核对计划与来源</button>
    </div>
    <details><summary>查看模拟费用设置</summary><BacktestCostSummary :costs="run.costs" /></details>
  </section>
</template>

<style scoped>
.review-overview { display: grid; gap: var(--space-4); min-width: 0; }
h3, p { margin: 0; line-height: 1.6; overflow-wrap: anywhere; }
.review-overview__facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-4); margin: 0; }
.review-overview__facts div { border-block-end: var(--border-technical); padding-block: var(--space-3); }
dt, .review-overview__boundary { color: var(--color-text-silt); font-size: .875rem; } dd { margin: var(--space-2) 0 0; font-size: 1.3rem; font-family: var(--font-numeric); }
.review-overview__actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
button, summary { min-height: 2.75rem; cursor: pointer; } button { padding: var(--space-2) var(--space-3); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); }
:focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
@media(max-width:48rem) { .review-overview__facts { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
