<script setup lang="ts">
import type { DeepReadonly } from "vue";

import type { BacktestRunView } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";

interface Props {
  run: DeepReadonly<BacktestRunView>;
}

defineProps<Props>();

const availabilityLabels = {
  AVAILABLE: "可读取",
  EXPIRED: "明细已过保留期",
  NOT_RECORDED: "运行时未记录",
} as const;

function visibleShanghaiTime(value: string): string {
  return `${value.slice(0, 10)} ${value.slice(11, 19)} +08:00`;
}
</script>

<template>
  <article
    class="metrics-summary"
    data-testid="backtest-metrics-summary"
    aria-labelledby="metrics-summary-title"
  >
    <header class="metrics-summary__header">
      <div>
        <p class="metrics-summary__eyebrow">MATERIALIZED RESEARCH RESULT</p>
        <h2 id="metrics-summary-title">已物化回测结果</h2>
      </div>
      <p class="metrics-summary__status"><span aria-hidden="true">●</span> 已完成</p>
    </header>

    <dl class="metrics-summary__identity">
      <div>
        <dt>股票</dt>
        <dd>{{ run.symbol }}</dd>
      </div>
      <div>
        <dt>运行 ID</dt>
        <dd>{{ run.runId }}</dd>
      </div>
      <div>
        <dt>事件区间</dt>
        <dd>{{ run.eventStart }} 至 {{ run.eventEnd }}</dd>
      </div>
      <div>
        <dt>完成时间</dt>
        <dd><time :datetime="run.completedAt">{{ visibleShanghaiTime(run.completedAt) }}</time></dd>
      </div>
      <div>
        <dt>数据集哈希</dt>
        <dd>{{ run.datasetHash }}</dd>
      </div>
      <div>
        <dt>报告哈希</dt>
        <dd>{{ run.reportHash }}</dd>
      </div>
    </dl>

    <section class="metrics-summary__section" aria-labelledby="metrics-values-title">
      <h3 id="metrics-values-title">精确指标</h3>
      <dl class="metrics-summary__grid">
        <div><dt>初始权益（元）</dt><dd>{{ formatFenAsYuan(run.metrics.initialEquityFen) }}</dd></div>
        <div><dt>最终权益（元）</dt><dd>{{ formatFenAsYuan(run.metrics.finalEquityFen) }}</dd></div>
        <div><dt>最终现金（元）</dt><dd>{{ formatFenAsYuan(run.metrics.finalCashFen) }}</dd></div>
        <div><dt>已实现盈亏（元）</dt><dd>{{ formatFenAsYuan(run.metrics.realizedPnlFen) }}</dd></div>
        <div><dt>未实现盈亏（元）</dt><dd>{{ formatFenAsYuan(run.metrics.unrealizedPnlFen) }}</dd></div>
        <div><dt>总收益率</dt><dd>{{ run.metrics.totalReturn }}</dd></div>
        <div><dt>最大回撤</dt><dd>{{ run.metrics.maximumDrawdown }}</dd></div>
        <div><dt>胜率</dt><dd>{{ run.metrics.winRate }}</dd></div>
        <div><dt>成交数</dt><dd>{{ run.metrics.tradeCount }}</dd></div>
        <div><dt>阻断 / 跳过</dt><dd>{{ run.metrics.blockedCount }} / {{ run.metrics.skippedCount }}</dd></div>
      </dl>
    </section>

    <section class="metrics-summary__section" aria-labelledby="availability-title">
      <h3 id="availability-title">结果资源状态</h3>
      <dl class="metrics-summary__grid">
        <div><dt>权益序列</dt><dd>{{ availabilityLabels[run.availability.equitySeries] }}</dd></div>
        <div><dt>决策明细</dt><dd>{{ availabilityLabels[run.availability.decisionDetails] }}</dd></div>
        <div><dt>信号明细</dt><dd>{{ availabilityLabels[run.availability.signalDetails] }}</dd></div>
        <div><dt>执行结果明细</dt><dd>{{ availabilityLabels[run.availability.executionOutcomeDetails] }}</dd></div>
      </dl>
    </section>

  </article>
</template>

<style scoped>
.metrics-summary {
  display: grid;
  gap: var(--space-5);
  padding: var(--space-6);
  color: var(--color-text-mineral);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
  border-inline-start: 0.3rem solid var(--color-signal-live-sea-glass);
}

.metrics-summary__header,
.metrics-summary__status {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
  justify-content: space-between;
}

.metrics-summary__header h2,
.metrics-summary__header p,
.metrics-summary__status,
.metrics-summary__section h3,
.metrics-summary__identity,
.metrics-summary__identity dd,
.metrics-summary__grid,
.metrics-summary__grid dd {
  margin: 0;
}

.metrics-summary__eyebrow {
  color: var(--color-signal-live-sea-glass);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.metrics-summary__status {
  justify-content: flex-start;
  font-weight: 700;
}

.metrics-summary__identity,
.metrics-summary__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-3);
}

.metrics-summary__identity div,
.metrics-summary__grid div {
  min-width: 0;
  padding-block-end: var(--space-2);
  border-block-end: var(--border-technical);
}

.metrics-summary dt {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.metrics-summary dd {
  overflow-wrap: anywhere;
  font-family: var(--font-numeric);
  font-variant-numeric: tabular-nums;
}

.metrics-summary__section {
  display: grid;
  gap: var(--space-3);
}

.metrics-summary__section h3 {
  font-size: 1rem;
}

@media (min-width: 48rem) {
  .metrics-summary__identity,
  .metrics-summary__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
