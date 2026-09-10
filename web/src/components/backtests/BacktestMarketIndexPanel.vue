<script setup lang="ts">
import type { BacktestMarketIndexSeriesView } from "../../api/generated";
import MarketIndexChart from "../market-index/MarketIndexChart.vue";
import BacktestIndexConditionSummary from "./BacktestIndexConditionSummary.vue";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  series: BacktestMarketIndexSeriesView;
}

defineProps<Props>();
const emit = defineEmits<{
  "select-date": [tradeDate: string];
}>();
</script>

<template>
  <div class="backtest-index-panel">
    <section class="backtest-index-panel__identity" aria-labelledby="backtest-index-data-title">
      <h2 id="backtest-index-data-title">共用指数数据</h2>
      <p v-if="series.referenceMarket === null" role="status">
        本次运行没有冻结的参考指数数据；旧运行或未使用指数条件的计划不会补造历史。
      </p>
      <template v-else>
        <dl class="backtest-index-panel__facts">
          <div><dt>参考指数</dt><dd>{{ series.referenceMarket.binding.displayName }}（{{ series.referenceMarket.binding.indexCode }}）</dd></div>
          <div><dt>板块</dt><dd>{{ series.referenceMarket.binding.board }}</dd></div>
          <div><dt>映射</dt><dd><code>{{ series.referenceMarket.binding.mappingVersion }}</code></dd></div>
          <div><dt>覆盖状态</dt><dd>{{ series.referenceMarket.coverageStatus }}</dd></div>
          <div><dt>预热起点</dt><dd>{{ series.referenceMarket.warmupStart }}</dd></div>
          <div><dt>指数数据哈希</dt><dd><code>{{ series.referenceMarket.marketIndexDataHash }}</code></dd></div>
          <div><dt>指数要求哈希</dt><dd><code>{{ series.referenceMarket.indexRequirementHash }}</code></dd></div>
          <div><dt>公式定义哈希</dt><dd><code>{{ series.referenceMarket.formulaDefinitionHash }}</code></dd></div>
        </dl>
        <p v-if="series.referenceMarket.blockers.length > 0" role="alert">
          阻断：{{ series.referenceMarket.blockers.join("、") }}
        </p>
        <section class="backtest-index-panel__health" aria-labelledby="backtest-index-health-title">
          <h3 id="backtest-index-health-title">指数数据健康时间线</h3>
          <p v-if="series.healthTimeline.length === 0" role="status">没有保留健康时间点。</p>
          <ul v-else>
            <li v-for="point in series.healthTimeline" :key="point.dataAt">
              <time :datetime="point.dataAt">{{ formatDisplayDateTime(point.dataAt) }}</time>：{{ point.health }}
              <span v-if="point.issues.length > 0">（{{ point.issues.join("、") }}）</span>
            </li>
          </ul>
        </section>
        <MarketIndexChart :points="series.items" @select-date="emit('select-date', $event)" />
      </template>
    </section>

    <BacktestIndexConditionSummary :summaries="series.conditionSummaries" />
  </div>
</template>

<style scoped>
.backtest-index-panel {
  display: grid;
  gap: var(--space-4);
}

.backtest-index-panel__identity,
.backtest-index-panel__health {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.backtest-index-panel__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
  gap: var(--space-3);
}

.backtest-index-panel__facts div {
  min-width: 0;
}

.backtest-index-panel__facts dt {
  color: var(--color-text-muted);
}

.backtest-index-panel__facts dd {
  margin: var(--space-1) 0 0;
  overflow-wrap: anywhere;
}

code {
  font-family: var(--font-numeric);
}
</style>
