<script setup lang="ts">
import type { DeepReadonly } from "vue";

import type { BacktestRunView } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  run: DeepReadonly<BacktestRunView>;
}

defineProps<Props>();

const availabilityLabels = {
  AVAILABLE: "可读取",
  EXPIRED: "明细已过保留期",
  NOT_RECORDED: "运行时未记录",
} as const;

const limitationDescriptions: Readonly<Record<string, string>> = Object.freeze({
  BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR:
    "每次评估仅使用有界的 512 根五分钟线、499 根历史日线和 512 个日历日上下文。",
  CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE:
    "涨跌停锁定采用开盘价或滑点后价格的保守判定。",
  DAILY_EQUITY_DRAWDOWN_SAMPLING: "最大回撤按每日权益点采样，不是分钟级连续采样。",
  FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME:
    "成交数量未按分钟成交量参与率封顶，不能用于推断真实市场容量。",
  HISTORICAL_MINUTES_DO_NOT_VERIFY_REALTIME:
    "历史分钟数据不能验证实时行情接口或实时数据契约。",
  METRIC_DECIMAL_PRECISION_28_HALF_EVEN:
    "指标使用 28 位十进制精度与 ROUND_HALF_EVEN 舍入。",
  SIMULATED_EXECUTION_NO_BROKER:
    "模拟执行不连接券商，所有成交均为模拟成交（仅供研究）。",
  UNADJUSTED_PRICES_NO_CORPORATE_ACTIONS:
    "价格未复权，不支持公司行动建模，包括分红、送转、拆股或合股。",
  WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP:
    "胜率按卖出成交笔数统计，不等同于完整往返交易胜率。",
  ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY:
    "零成交量分钟仅作为不可交易代理，不是停牌事实证明。",
});

function limitationDescription(token: string): string {
  return limitationDescriptions[token] ?? "服务端声明的研究局限；本页保留原始 token。";
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
        <dd><time :datetime="run.completedAt">{{ formatDisplayDateTime(run.completedAt) }}</time></dd>
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
        <div><dt>初始现金（元）</dt><dd>{{ formatFenAsYuan(run.metrics.initialCashFen) }}</dd></div>
        <div><dt>初始权益（元）</dt><dd>{{ formatFenAsYuan(run.metrics.initialEquityFen) }}</dd></div>
        <div><dt>最终权益（元）</dt><dd>{{ formatFenAsYuan(run.metrics.finalEquityFen) }}</dd></div>
        <div><dt>最终现金（元）</dt><dd>{{ formatFenAsYuan(run.metrics.finalCashFen) }}</dd></div>
        <div><dt>已实现盈亏（元）</dt><dd>{{ formatFenAsYuan(run.metrics.realizedPnlFen) }}</dd></div>
        <div><dt>未实现盈亏（元）</dt><dd>{{ formatFenAsYuan(run.metrics.unrealizedPnlFen) }}</dd></div>
        <div><dt>成交额（元）</dt><dd>{{ formatFenAsYuan(run.metrics.turnoverFen) }}</dd></div>
        <div><dt>总交易成本（元）</dt><dd>{{ formatFenAsYuan(run.metrics.totalCostFen) }}</dd></div>
        <div><dt>总收益率</dt><dd>{{ run.metrics.totalReturn }}</dd></div>
        <div><dt>最大回撤</dt><dd>{{ run.metrics.maximumDrawdown }}</dd></div>
        <div><dt>胜率</dt><dd>{{ run.metrics.winRate }}</dd></div>
        <div><dt>盈利卖出成交数</dt><dd>{{ run.metrics.winningSellCount }}</dd></div>
        <div><dt>成交数</dt><dd>{{ run.metrics.tradeCount }}</dd></div>
        <div><dt>阻断 / 跳过</dt><dd>{{ run.metrics.blockedCount }} / {{ run.metrics.skippedCount }}</dd></div>
      </dl>
      <ul class="metrics-summary__definitions" aria-label="指标定义">
        <li>总收益率 =（最终权益 − 初始权益）÷ 初始权益。</li>
        <li>最大回撤 = 每日权益点相对此前峰值的最大跌幅；不代表分钟级日内最低点。</li>
        <li>胜率 = 已实现盈利的卖出成交数 ÷ 全部卖出成交数；没有卖出成交时为 0。</li>
        <li>成交数统计全部模拟成交；成交额为每笔模拟成交名义金额之和。</li>
      </ul>
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

    <section class="metrics-summary__section" aria-labelledby="assumptions-title">
      <h3 id="assumptions-title">输入假设与执行成本</h3>
      <aside class="metrics-summary__boundary" aria-label="价格与研究边界">
        <strong>价格口径：{{ run.assumptions.priceAdjustmentPolicy }}（未复权）。</strong>
        不支持公司行动建模；分红、送转、拆股或合股可能使历史比较失真。所有结果均为模拟成交（仅供研究），不代表真实委托、成交或未来收益。
      </aside>
      <dl class="metrics-summary__grid">
        <div><dt>事件风险假设</dt><dd>{{ run.assumptions.eventRiskAssumption }}</dd></div>
        <div><dt>历史数据标签契约</dt><dd>{{ run.assumptions.historicalProfile }}</dd></div>
        <div><dt>价格调整策略</dt><dd>{{ run.assumptions.priceAdjustmentPolicy }}（未复权）</dd></div>
        <div><dt>执行配置哈希</dt><dd>{{ run.assumptions.executionConfigHash }}</dd></div>
        <div><dt>佣金率</dt><dd>{{ run.assumptions.executionConfig.commissionRate }}</dd></div>
        <div><dt>最低佣金（元）</dt><dd>{{ formatFenAsYuan(run.assumptions.executionConfig.minimumCommissionFen) }}</dd></div>
        <div><dt>印花税率</dt><dd>{{ run.assumptions.executionConfig.stampDutyRate }}</dd></div>
        <div><dt>过户费率</dt><dd>{{ run.assumptions.executionConfig.transferFeeRate }}</dd></div>
        <div><dt>买入滑点（bps）</dt><dd>{{ run.assumptions.executionConfig.buySlippageBps }}</dd></div>
        <div><dt>卖出滑点（bps）</dt><dd>{{ run.assumptions.executionConfig.sellSlippageBps }}</dd></div>
      </dl>
    </section>

    <section class="metrics-summary__section" aria-labelledby="formula-versions-title">
      <h3 id="formula-versions-title">公式与报告版本</h3>
      <dl class="metrics-summary__grid">
        <div><dt>运行公式</dt><dd>{{ run.formulaVersions.runFormulaVersion }}</dd></div>
        <div><dt>执行公式</dt><dd>{{ run.formulaVersions.executionFormulaVersion }}</dd></div>
        <div><dt>指标公式</dt><dd>{{ run.formulaVersions.metricFormulaVersion }}</dd></div>
        <div><dt>报告结构</dt><dd>{{ run.formulaVersions.reportSchemaVersion }}</dd></div>
      </dl>
    </section>

    <section class="metrics-summary__section" aria-labelledby="limitations-title">
      <h3 id="limitations-title">研究局限</h3>
      <p>以下每项均来自服务端已物化报告；颜色不承载局限含义。</p>
      <ul class="metrics-summary__limitations">
        <li v-for="limitation in run.limitations" :key="limitation">
          <code>{{ limitation }}</code>
          <span>{{ limitationDescription(limitation) }}</span>
        </li>
      </ul>
    </section>

  </article>
</template>

<style scoped>
.metrics-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
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
  overflow-wrap: anywhere;
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
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-3);
}

.metrics-summary__section h3 {
  font-size: 1rem;
}

.metrics-summary__boundary {
  padding: var(--space-3);
  color: var(--color-text-mineral);
  border-inline-start: 0.25rem solid var(--color-signal-warning-amber);
}

.metrics-summary__limitations {
  display: grid;
  gap: var(--space-3);
  padding: 0;
  margin: 0;
  list-style: none;
}

.metrics-summary__definitions {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding-inline-start: var(--space-5);
  color: var(--color-text-muted);
}

.metrics-summary__limitations li {
  display: grid;
  gap: var(--space-1);
  padding-block-end: var(--space-2);
  border-block-end: var(--border-technical);
}

.metrics-summary__limitations code {
  overflow-wrap: anywhere;
}

@media (min-width: 48rem) {
  .metrics-summary__identity,
  .metrics-summary__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 30rem) {
  .metrics-summary {
    padding-inline: var(--space-2);
  }
}
</style>
