<script setup lang="ts">
import {
  onBeforeUnmount,
  onMounted,
  shallowRef,
  useTemplateRef,
  watch,
  type DeepReadonly,
} from "vue";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

import type { BacktestEquityPointView, ResearchEquityView } from "../../api/generated";
import { formatFenAsYuan, parseFenText } from "../../api/backtestValues";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  items: DeepReadonly<(BacktestEquityPointView | ResearchEquityView)[]>;
}

interface ChartInstance {
  dispose(): void;
  resize(): void;
  setOption(option: unknown): void;
}

const showEquity = shallowRef(true), showCash = shallowRef(true), showMarketValue = shallowRef(true);
const range = shallowRef("100");
watch([showEquity, showCash, showMarketValue, range], () => renderChart());

const MAX_SAFE_FEN = 9_007_199_254_740_991n;
const props = defineProps<Props>();
const chartHost = useTemplateRef<HTMLDivElement>("chartHost");
const chart = shallowRef<ChartInstance | null>(null);
const visibleItems = shallowRef<readonly DeepReadonly<BacktestEquityPointView | ResearchEquityView>[]>([]);
const loadState = shallowRef<"LOADING" | "READY" | "FAILED">("LOADING");

let mounted = false;
watch(
  () => props.items,
  (items) => {
    visibleItems.value = Object.freeze(items.slice(0, 2_000));
    renderChart();
  },
  { immediate: true },
);

onMounted(() => {
  mounted = true;
  window.addEventListener("resize", resizeChart);
  loadChart();
});

onBeforeUnmount(() => {
  mounted = false;
  window.removeEventListener("resize", resizeChart);
  chart.value?.dispose();
  chart.value = null;
});

function loadChart(): void {
  loadState.value = "LOADING";
  try {
    if (!mounted || chartHost.value === null) return;
    use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer]);
    chart.value = init(chartHost.value) as ChartInstance;
    loadState.value = "READY";
    renderChart();
  } catch {
    if (!mounted) return;
    loadState.value = "FAILED";
  }
}

function renderChart(): void {
  if (chart.value === null) return;
  const labels = visibleItems.value.map((item) => formatDisplayDateTime(item.markedAt));
  chart.value.setOption({
    animation: false,
    grid: { containLabel: true, left: 12, right: 16, top: 42, bottom: 45 },
    legend: {
      selectedMode: false,
      textStyle: { color: "#b8c1b8" },
      selected: { "权益": showEquity.value, "现金": showCash.value, "市值": showMarketValue.value },
    },
    dataZoom: [{ type: "inside", start: 100 - Number(range.value), end: 100 }, { type: "slider", start: 100 - Number(range.value), end: 100, bottom: 0 }],
    series: [
      {
        data: visibleItems.value.map((item) => safeChartYuan(item.equityFen)),
        name: "权益",
        showSymbol: false,
        type: "line",
      },
      {
        data: visibleItems.value.map((item) => safeChartYuan(item.cashFen)),
        name: "现金",
        showSymbol: false,
        type: "line",
      },
      {
        data: visibleItems.value.map((item) => safeChartYuan(item.marketValueFen)),
        name: "市值",
        showSymbol: false,
        type: "line",
      },
    ],
    tooltip: { trigger: "axis" },
    xAxis: { data: labels, type: "category" },
    yAxis: { name: "元（派生展示）", scale: true, type: "value" },
  });
}

function resizeChart(): void {
  chart.value?.resize();
}

function safeChartYuan(value: string | null): number | null {
  if (value === null) return null;
  const fen = parseFenText(value);
  if (fen === null || fen < -MAX_SAFE_FEN || fen > MAX_SAFE_FEN) return null;
  return Number.parseFloat(formatFenAsYuan(fen));
}

</script>

<template>
  <div class="equity-chart">
    <fieldset class="equity-chart__controls"><legend>趋势图显示</legend><label><input v-model="showEquity" type="checkbox">权益</label><label><input v-model="showCash" type="checkbox">现金</label><label><input v-model="showMarketValue" type="checkbox">市值</label><label>展示范围<select v-model="range"><option value="100">全部记录</option><option value="50">最近一半记录</option><option value="25">最近四分之一记录</option></select></label></fieldset>
    <p v-if="loadState === 'LOADING'" class="equity-chart__state" role="status">
      正在加载趋势图…
    </p>
    <p v-else-if="loadState === 'FAILED'" class="equity-chart__state">
      趋势图暂不可用；下方完整精确表格不受影响。
    </p>
    <div
      ref="chartHost"
      class="equity-chart__canvas"
      data-testid="backtest-equity-chart"
      role="img"
      aria-label="权益、现金与市值趋势图；精确数值见下方完整表格"
    ></div>
  </div>
</template>

<style scoped>
.equity-chart__controls { display: flex; flex-wrap: wrap; gap: var(--space-3); border: var(--border-technical); }
.equity-chart__controls label { display: inline-flex; align-items: center; gap: var(--space-2); min-height: 44px; }
.equity-chart__controls select { min-height: 44px; color: inherit; background: var(--color-surface-raised); }
.equity-chart__controls :focus-visible { outline: 3px solid var(--color-focus-ring); }
.equity-chart {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
}

.equity-chart__state {
  margin: 0;
  color: var(--color-text-muted);
}

.equity-chart__canvas {
  width: 100%;
  min-height: 22rem;
  border: var(--border-technical);
}

@media (prefers-reduced-motion: reduce) {
  .equity-chart__canvas {
    scroll-behavior: auto;
  }
}
</style>
