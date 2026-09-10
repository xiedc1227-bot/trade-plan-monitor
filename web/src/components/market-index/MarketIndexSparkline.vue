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

interface Props {
  ariaLabel: string;
  bars: readonly MarketIndexBarView[];
  displayName: string;
  priorClosePoints: string | null;
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
  () => [props.bars, props.priorClosePoints] as const,
  () => renderSeries(),
);

onMounted(() => {
  if (container.value === null || container.value.clientWidth === 0) return;
  chart.value = init(container.value);
  resizeObserver.value = new ResizeObserver(resizeChart);
  resizeObserver.value.observe(container.value);
  window.addEventListener("resize", resizeChart);
  renderSeries();
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart);
  resizeObserver.value?.disconnect();
  resizeObserver.value = null;
  chart.value?.dispose();
  chart.value = null;
});

function renderSeries(): void {
  chart.value?.setOption(buildOption(props.bars, props.priorClosePoints), { notMerge: true });
}

function resizeChart(): void {
  chart.value?.resize();
}

function buildOption(
  bars: readonly MarketIndexBarView[],
  priorClosePoints: string | null,
): EChartsCoreOption {
  const visibleBars = bars.filter((bar) => Number.isFinite(Number(bar.closePoints)));
  const priorClose = priorClosePoints === null ? null : Number(priorClosePoints);
  return {
    animation: false,
    aria: { enabled: true },
    grid: { bottom: 30, left: 48, right: 16, top: 14 },
    series: [
      {
        areaStyle: { opacity: 0.1 },
        data: visibleBars.map((bar) => Number(bar.closePoints)),
        lineStyle: { width: 2 },
        markLine: Number.isFinite(priorClose)
          ? {
              data: [{ label: { formatter: "昨收" }, yAxis: priorClose }],
              lineStyle: { type: "dashed" },
              silent: true,
              symbol: ["none", "none"],
            }
          : undefined,
        markPoint: visibleBars.length === 0
          ? undefined
          : {
              data: [{ coord: [visibleBars.length - 1, Number(visibleBars.at(-1)?.closePoints)], name: "最新" }],
              symbolSize: 8,
            },
        name: props.displayName,
        showSymbol: false,
        type: "line",
      },
    ],
    tooltip: { renderMode: "richText", trigger: "axis" },
    xAxis: {
      axisLabel: { formatter: (value: string) => value.slice(11, 16) },
      data: visibleBars.map((bar) => bar.barAt),
      type: "category",
    },
    yAxis: { scale: true, type: "value" },
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
.market-index-sparkline { width: 100%; min-height: 12rem; }
</style>
