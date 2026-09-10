<script setup lang="ts">
import type { BacktestMarketIndexPointView, MarketIndexBarView } from "../../api/generated";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  bars?: readonly MarketIndexBarView[];
  error?: string | null;
  loading?: boolean;
  points?: readonly BacktestMarketIndexPointView[];
  snapshotHash?: string | null;
}

withDefaults(defineProps<Props>(), {
  bars: () => [],
  error: null,
  loading: false,
  points: () => [],
  snapshotHash: null,
});

const emit = defineEmits<{
  "select-date": [tradeDate: string];
}>();
</script>

<template>
  <section class="index-chart" aria-labelledby="index-chart-title">
    <h2 id="index-chart-title">板块指数历史</h2>
    <p v-if="snapshotHash" class="index-chart__identity">
      后端历史快照 {{ snapshotHash }}
    </p>
    <p v-if="loading" class="index-chart__status" role="status" aria-live="polite">
      正在刷新共享指数历史；已有后端点位会继续显示。
    </p>
    <p v-if="error" class="index-chart__error" role="alert">
      {{ error }}；{{ bars.length > 0 || points.length > 0 ? "已缓存后端点位继续显示。" : "不会补造指数点位。" }}
    </p>
    <p
      v-if="!loading && !error && bars.length === 0 && points.length === 0"
      role="status"
    >
      暂无后端指数历史数据。
    </p>
    <div
      v-if="bars.length > 0 || points.length > 0"
      class="index-chart__scroller"
      tabindex="0"
      aria-label="板块指数历史表，可横向滚动"
    >
      <table v-if="points.length > 0">
        <caption>回测板块指数点位与后端指标事实（POINTS）</caption>
        <thead>
          <tr><th scope="col">交易日</th><th scope="col">截止时间</th><th scope="col">收盘点位</th><th scope="col">指标事实</th><th scope="col">健康</th></tr>
        </thead>
        <tbody>
          <tr v-for="point in points" :key="`${point.tradeDate}:${point.dataAt}`">
            <th scope="row">
              <button type="button" :data-trade-date="point.tradeDate" @click="emit('select-date', point.tradeDate)">{{ point.tradeDate }}</button>
            </th>
            <td><time :datetime="point.dataAt">{{ formatDisplayDateTime(point.dataAt) }}</time></td>
            <td>{{ point.closePoints }}</td>
            <td>
              <ul>
                <li v-for="fact in point.indicatorFacts" :key="`${fact.formulaId}:${fact.sourceBarHash}`">
                  {{ fact.formulaId }}
                  <span v-if="'period' in fact"> {{ fact.period }}</span>：{{ fact.value }} {{ fact.unit }}
                  <span v-if="'comparisonValue' in fact">；对比 {{ fact.comparisonValue }} {{ fact.unit }}</span>
                  <span v-if="'window' in fact">；{{ fact.window }} / {{ fact.windowSize }}</span>
                </li>
              </ul>
            </td>
            <td>{{ point.health }}<span v-if="point.issues.length > 0">（{{ point.issues.join("、") }}）</span></td>
          </tr>
        </tbody>
      </table>
      <table v-else>
        <caption>板块指数点位（与后端返回精度一致）</caption>
        <thead>
          <tr><th scope="col">时间</th><th scope="col">开</th><th scope="col">高</th><th scope="col">低</th><th scope="col">收</th><th scope="col">来源</th></tr>
        </thead>
        <tbody>
          <tr v-for="bar in bars" :key="`${bar.indexCode}:${bar.interval}:${bar.barAt}`">
            <th scope="row"><time :datetime="bar.barAt">{{ formatDisplayDateTime(bar.barAt) }}</time></th>
            <td>{{ bar.openPoints }}</td><td>{{ bar.highPoints }}</td><td>{{ bar.lowPoints }}</td><td>{{ bar.closePoints }}</td><td>{{ bar.sourceKind }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.index-chart {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.index-chart__scroller {
  overflow-x: auto;
}

.index-chart__identity,
.index-chart__status,
.index-chart__error {
  overflow-wrap: anywhere;
}

.index-chart__identity {
  font-family: var(--font-numeric);
}

.index-chart__error {
  padding-inline-start: var(--space-3);
  border-inline-start: 0.25rem solid var(--color-signal-risk-vermilion);
}

.index-chart table {
  width: 100%;
  min-width: 42rem;
  border-collapse: collapse;
  font-family: var(--font-numeric);
}

.index-chart th,
.index-chart td {
  padding: var(--space-2);
  text-align: start;
  border-block-end: var(--border-technical);
}
</style>
