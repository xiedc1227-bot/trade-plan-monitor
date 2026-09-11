<script setup lang="ts">
import { LineChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components";
import { init, use } from "echarts/core";
import type { ECharts, EChartsCoreOption } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { onBeforeUnmount, onMounted, shallowRef, useTemplateRef, watch } from "vue";

import type { MarketIndexBarView } from "../../api/generated";
import {
  calculateIndexAxisBounds,
  marketIndexDirectionColor,
  marketIndexShowSymbol,
} from "./marketIndexChartOptions";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  ariaLabel: string;
  bars: readonly MarketIndexBarView[];
  displayName: string;
  priorClosePoints: string | null;
  sessionChangeRatio: string | null;
}

const props = defineProps<Props>();
const container = useTemplateRef<HTMLDivElement>("container");
const chart = shallowRef<ECharts | null>(null);
const resizeObserver = shallowRef<ResizeObserver | null>(null);

use([
  AriaComponent,
  CanvasRenderer,
  GridComponent,
  LineChart,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
]);

watch(
  () => [props.bars, props.priorClosePoints, props.sessionChangeRatio] as const,
  () => renderSeries(),
);

onMounted(() => {
  if (container.value === null) return;
  if (typeof ResizeObserver !== "undefined") {
    resizeObserver.value = new ResizeObserver(ensureChart);
    resizeObserver.value.observe(container.value);
  }
  window.addEventListener("resize", resizeChart);
  ensureChart();
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart);
  resizeObserver.value?.disconnect();
  resizeObserver.value = null;
  chart.value?.dispose();
  chart.value = null;
});

function renderSeries(): void {
  chart.value?.setOption(
    buildOption(props.bars, props.priorClosePoints, props.sessionChangeRatio),
    { notMerge: true },
  );
}

function resizeChart(): void {
  ensureChart();
  chart.value?.resize();
}

function ensureChart(): void {
  const element = container.value;
  if (element === null || element.clientWidth === 0 || chart.value !== null) return;
  chart.value = init(element);
  renderSeries();
}

function buildOption(
  bars: readonly MarketIndexBarView[],
  priorClosePoints: string | null,
  sessionChangeRatio: string | null,
): EChartsCoreOption {
  const visibleBars = bars.filter((bar) => Number.isFinite(Number(bar.closePoints)));
  const priorClose = priorClosePoints === null ? null : Number(priorClosePoints);
  const values = visibleBars.map((bar) => Number(bar.closePoints));
  const bounds = calculateIndexAxisBounds(values, Number.isFinite(priorClose) ? priorClose : null);
  const trendColor = marketIndexDirectionColor(sessionChangeRatio);
  return {
    animation: false,
    aria: { enabled: true },
    grid: { bottom: 28, left: 12, right: 72, top: 14 },
    series: [
      {
        areaStyle: { color: trendColor, opacity: 0.08 },
        data: values,
        endLabel: {
          backgroundColor: trendColor,
          borderRadius: 2,
          color: "#0b1114",
          formatter: (parameters: { value: number }) => Number(parameters.value).toFixed(2),
          padding: [2, 4],
          show: visibleBars.length > 0,
        },
        emphasis: { disabled: true },
        lineStyle: { color: trendColor, width: 2 },
        markLine: Number.isFinite(priorClose)
          ? {
              data: [{ label: { formatter: "昨收", position: "insideEndTop" }, yAxis: priorClose }],
              label: { color: "#a8b4b3" },
              lineStyle: { color: "#a8b4b3", opacity: 0.8, type: "dashed" },
              silent: true,
              symbol: ["none", "none"],
            }
          : undefined,
        name: props.displayName,
        showSymbol: marketIndexShowSymbol(visibleBars.length),
        symbolSize: 6,
        type: "line",
      },
    ],
    tooltip: {
      axisPointer: {
        label: {
          formatter: (parameters: { value: string | number }) =>
            formatDisplayDateTime(String(parameters.value)),
        },
        lineStyle: { color: "#62b7d1", type: "dashed" },
        type: "line",
      },
      backgroundColor: "#1c282d",
      borderColor: "#405158",
      renderMode: "richText",
      textStyle: { color: "#eef1e8" },
      trigger: "axis",
      valueFormatter: (value: unknown) => Number(value).toFixed(2),
    },
    xAxis: {
      axisLabel: { color: "#a8b4b3", formatter: (value: string) => value.slice(11, 16) },
      axisLine: { lineStyle: { color: "#405158" } },
      axisTick: { show: false },
      boundaryGap: false,
      data: visibleBars.map((bar) => bar.barAt),
      type: "category",
    },
    yAxis: {
      axisLabel: { color: "#a8b4b3", formatter: (value: number) => value.toFixed(2) },
      axisLine: { show: false },
      axisTick: { show: false },
      max: bounds?.maximum,
      min: bounds?.minimum,
      position: "right",
      scale: true,
      splitLine: { lineStyle: { color: "rgba(151, 171, 176, 0.12)" } },
      splitNumber: 4,
      type: "value",
    },
  };
}
</script>

<template>
  <div
    ref="container"
    class="market-index-sparkline"
    data-testid="market-index-sparkline"
    role="img"
    :aria-label="ariaLabel"
  />
</template>

<style scoped>
.market-index-sparkline { width: 100%; min-height: 18rem; }

@media (max-width: 39.999rem) {
  .market-index-sparkline { min-height: 14rem; }
}
</style>
