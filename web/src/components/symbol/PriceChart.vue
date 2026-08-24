<script setup lang="ts">
import { onBeforeUnmount, onMounted, shallowRef, useTemplateRef, watch } from "vue";
import type { ECharts, EChartsOption } from "echarts";
import * as echarts from "echarts";

import type { ChartSeries } from "../../composables/useChartSeries";

export interface ChartRange {
  endPercent: number;
  startPercent: number;
}

interface Props {
  series: ChartSeries;
  stale: boolean;
}

interface Emits {
  rangeChange: [range: ChartRange];
}

interface DataZoomPayload {
  batch?: Array<{ end?: number; start?: number }>;
  end?: number;
  start?: number;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();
const container = useTemplateRef<HTMLDivElement>("container");
const chart = shallowRef<ECharts | null>(null);

watch(
  () => props.series,
  () => renderSeries(),
);

onMounted(() => {
  if (container.value === null) {
    return;
  }
  chart.value = echarts.init(container.value);
  chart.value.on("datazoom", handleDataZoom);
  window.addEventListener("resize", resizeChart);
  renderSeries();
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart);
  chart.value?.off("datazoom", handleDataZoom);
  chart.value?.dispose();
  chart.value = null;
});

function renderSeries(): void {
  chart.value?.setOption(buildOption(props.series), { notMerge: true });
}

function resizeChart(): void {
  chart.value?.resize();
}

function handleDataZoom(...args: unknown[]): void {
  const payload = asDataZoomPayload(args[0]);
  if (payload === null) {
    return;
  }
  const range = payload.batch?.[0] ?? payload;
  if (
    typeof range.start !== "number" ||
    !Number.isFinite(range.start) ||
    typeof range.end !== "number" ||
    !Number.isFinite(range.end)
  ) {
    return;
  }
  emit("rangeChange", {
    endPercent: clampPercent(range.end),
    startPercent: clampPercent(range.start),
  });
}

function asDataZoomPayload(value: unknown): DataZoomPayload | null {
  return typeof value === "object" && value !== null ? (value as DataZoomPayload) : null;
}

function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value));
}

function buildOption(series: ChartSeries): EChartsOption {
  const markLineData = series.priceLevels.map((level) => ({
    label: { formatter: `${level.label} ${level.valueYuan.toFixed(2)}` },
    name: level.label,
    yAxis: level.valueYuan,
  }));
  if (series.episodeLow !== null) {
    markLineData.push({
      label: {
        formatter: `${series.episodeLow.label} ${series.episodeLow.valueYuan.toFixed(2)}`,
      },
      name: series.episodeLow.label,
      yAxis: series.episodeLow.valueYuan,
    });
  }
  return {
    animation: false,
    aria: { enabled: true },
    dataZoom: [{ end: 100, start: 0, type: "inside" }, { end: 100, start: 0 }],
    grid: { bottom: 72, left: 64, right: 28, top: 32 },
    legend: { data: ["K 线", "指标证据", "提醒"] },
    series: [
      {
        data: series.candles.map((candle) => [
          candle.openYuan,
          candle.closeYuan,
          candle.lowYuan,
          candle.highYuan,
        ]),
        markLine: {
          data: markLineData,
          silent: true,
          symbol: ["none", "none"],
        },
        name: "K 线",
        type: "candlestick",
      },
      {
        data: series.indicators.flatMap((indicator) =>
          indicator.plotTime === null || indicator.value === null
            ? []
            : [{ name: indicator.label, value: [indicator.plotTime, indicator.value] }],
        ),
        name: "指标证据",
        symbol: "diamond",
        symbolSize: 9,
        type: "scatter",
      },
      {
        data: series.alertMarkers.flatMap((marker) =>
          marker.plotTime === null || marker.valueYuan === null
            ? []
            : [{ name: marker.label, value: [marker.plotTime, marker.valueYuan] }],
        ),
        name: "提醒",
        symbol: "pin",
        symbolSize: 14,
        type: "scatter",
      },
    ],
    tooltip: { renderMode: "richText", trigger: "axis" },
    xAxis: {
      data: series.candles.map((candle) => candle.time),
      type: "category",
    },
    yAxis: {
      name: "价格（元）",
      scale: true,
      type: "value",
    },
  };
}
</script>

<template>
  <div class="price-chart">
    <p v-if="stale" class="price-chart__status">陈旧数据图表</p>
    <div
      ref="container"
      class="price-chart__canvas"
      data-testid="price-chart"
      role="img"
      :aria-label="stale ? '个股价格图表，当前数据陈旧' : '个股价格图表'"
    />
  </div>
</template>

<style scoped>
.price-chart {
  position: relative;
  min-width: 0;
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.price-chart__canvas {
  width: 100%;
  min-height: 28rem;
}

.price-chart__status {
  position: absolute;
  z-index: 1;
  inset-block-start: var(--space-2);
  inset-inline-end: var(--space-2);
  margin: 0;
  padding: var(--space-1) var(--space-2);
  color: var(--color-text-mineral);
  background: var(--color-surface-raised);
  border: var(--border-technical);
}

@media (max-width: 39.999rem) {
  .price-chart__canvas {
    min-height: 20rem;
  }
}
</style>
