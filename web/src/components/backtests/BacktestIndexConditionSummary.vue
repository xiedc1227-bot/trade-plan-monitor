<script setup lang="ts">
import type { BacktestIndexConditionSummaryView } from "../../api/generated";

interface Props {
  summaries: readonly BacktestIndexConditionSummaryView[];
}

defineProps<Props>();
</script>

<template>
  <section class="condition-summary" aria-labelledby="backtest-index-condition-title">
    <h2 id="backtest-index-condition-title">计划指数条件结果</h2>
    <p v-if="summaries.length === 0" role="status">计划未使用指数条件。</p>
    <div v-else class="condition-summary__scroller" tabindex="0" aria-label="计划指数条件结果表，可横向滚动">
      <table>
        <caption>后端按交易计划路径汇总的条件结果</caption>
        <thead>
          <tr>
            <th scope="col">计划路径</th>
            <th scope="col">条件</th>
            <th scope="col">公式与参数</th>
            <th scope="col">结果数量</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="summary in summaries" :key="summary.planPath">
            <th scope="row"><code>{{ summary.planPath }}</code></th>
            <td><code>{{ summary.conditionType }}</code></td>
            <td>
              <code>{{ summary.formulaId }}</code>
              <span v-if="'period' in summary.parameters"> · period {{ summary.parameters.period }}</span>
              <span v-if="'lookback' in summary.parameters"> · lookback {{ summary.parameters.lookback }}</span>
              <span v-if="'window' in summary.parameters"> · {{ summary.parameters.window }}</span>
              <span v-if="'windowSize' in summary.parameters"> · windowSize {{ summary.parameters.windowSize }}</span>
              <span v-if="'thresholdRatio' in summary.parameters"> · threshold {{ summary.parameters.thresholdRatio }}</span>
            </td>
            <td>
              满足 {{ summary.satisfiedCount }} · 未满足 {{ summary.unsatisfiedCount }} ·
              缺失 {{ summary.missingCount }} · 适用分支 {{ summary.applicableBranchCount }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.condition-summary {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.condition-summary__scroller {
  overflow-x: auto;
}

table {
  width: 100%;
  min-width: 54rem;
  border-collapse: collapse;
}

th,
td {
  padding: var(--space-2);
  text-align: start;
  vertical-align: top;
  border-block-end: var(--border-technical);
}

code {
  font-family: var(--font-numeric);
  overflow-wrap: anywhere;
}
</style>
