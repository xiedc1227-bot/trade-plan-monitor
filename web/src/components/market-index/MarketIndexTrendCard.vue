<script setup lang="ts">
import { computed } from "vue";

import type { ConnectionStatus, MarketIndexSnapshotView } from "../../api/generated";
import type { CanonicalMarketIndexIdentity } from "../../api/marketIndexIdentity";
import type { DashboardMarketIndexTrend } from "../../composables/useDashboardMarketIndexTrends";
import MarketIndexSparkline from "./MarketIndexSparkline.vue";

interface Props {
  connectionStatus: ConnectionStatus;
  identity: CanonicalMarketIndexIdentity & {
    readonly indexCode: MarketIndexSnapshotView["indexCode"];
  };
  summary: MarketIndexSnapshotView | null;
  trend: DashboardMarketIndexTrend;
}

interface Emits {
  retry: [indexCode: MarketIndexSnapshotView["indexCode"]];
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();
const bars = computed(() => props.trend.page?.items ?? []);
const highPoints = computed(() => extrema("highPoints", Math.max));
const lowPoints = computed(() => extrema("lowPoints", Math.min));
const turnover = computed(() => {
  const amounts = bars.value
    .map((bar) => bar.amount === null ? Number.NaN : Number(bar.amount))
    .filter(Number.isFinite);
  if (amounts.length === 0) return "—";
  const totalYi = amounts.reduce((sum, value) => sum + value, 0) / 100_000_000;
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(totalYi)}亿`;
});
const healthLabels = Object.freeze({
  BLOCKED: "阻断 ×",
  GAPPED: "缺口 !",
  LIVE: "实时 ●",
  STALE: "陈旧 !",
} as const);
const displayedHealth = computed(() => {
  if (props.summary === null) return "暂无快照";
  if (props.summary.health === "LIVE" && props.connectionStatus !== "CONNECTED") {
    return "已缓存";
  }
  return healthLabels[props.summary.health];
});
const chartLabel = computed(() => {
  return `${props.identity.displayName}当日五分钟指数走势，最新点位 ${props.summary?.closePoints ?? "未知"}，会话涨跌 ${formatSessionChange(props.summary?.sessionChangeRatio ?? null)}，数据截止 ${props.summary?.completedBucketAt ?? "未知"}，${displayedHealth.value}，虚线为昨收点位`;
});

function formatSessionChange(value: string | null): string {
  if (value === null || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    style: "percent",
  }).format(Number(value));
}

function formatPoints(value: string | null): string {
  if (value === null || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
    useGrouping: false,
  }).format(Number(value));
}

function extrema(
  field: "highPoints" | "lowPoints",
  reducer: (...values: number[]) => number,
): string | null {
  const values = bars.value.map((bar) => Number(bar[field])).filter(Number.isFinite);
  return values.length === 0 ? null : String(reducer(...values));
}

function trendDirection(value: string | null): "down" | "flat" | "up" {
  const ratio = Number(value);
  if (!Number.isFinite(ratio) || ratio === 0) return "flat";
  return ratio > 0 ? "up" : "down";
}
</script>

<template>
  <article
    class="market-index-trend-card"
    data-testid="market-index-trend-card"
    :data-health="summary?.health ?? 'BLOCKED'"
    :data-direction="trendDirection(summary?.sessionChangeRatio ?? null)"
  >
    <header class="market-index-trend-card__header">
      <div>
        <h3>{{ identity.displayName }}</h3>
        <code>{{ identity.indexCode }}</code>
      </div>
      <strong>{{ displayedHealth }}</strong>
    </header>
    <dl class="market-index-trend-card__market-facts">
      <div class="market-index-trend-card__primary-fact">
        <dt>当前</dt><dd>{{ formatPoints(summary?.closePoints ?? null) }}</dd>
      </div>
      <div><dt>最高</dt><dd>{{ formatPoints(highPoints) }}</dd></div>
      <div><dt>最低</dt><dd>{{ formatPoints(lowPoints) }}</dd></div>
      <div><dt>成交额</dt><dd>{{ turnover }}</dd></div>
    </dl>
    <MarketIndexSparkline
      :ariaLabel="chartLabel"
      :bars="bars"
      :display-name="identity.displayName"
      :prior-close-points="summary?.priorClosePoints ?? null"
      :session-change-ratio="summary?.sessionChangeRatio ?? null"
    />
    <p
      v-if="trend.status === 'LOADING'"
      class="market-index-trend-card__status"
      role="status"
    >
      正在加载当日五分钟走势…
    </p>
    <p v-else-if="trend.status === 'ERROR'" class="market-index-trend-card__status" role="alert">
      {{ trend.error }} <button type="button" @click="emit('retry', identity.indexCode)">重试</button>
    </p>
    <p
      v-else-if="bars.length === 0 && trend.status === 'EMPTY'"
      class="market-index-trend-card__status"
    >
      当前时段暂无已完成的五分钟数据。
    </p>
    <p v-else-if="bars.length === 0" class="market-index-trend-card__status">当前暂无当日五分钟数据。</p>
    <dl class="market-index-trend-card__facts">
      <div>
        <dt>会话涨跌</dt>
        <dd>{{ formatSessionChange(summary?.sessionChangeRatio ?? null) }}</dd>
      </div>
      <div><dt>昨收点位</dt><dd>{{ formatPoints(summary?.priorClosePoints ?? null) }}</dd></div>
      <div><dt>数据截止</dt><dd>{{ summary?.completedBucketAt ?? "不可用" }}</dd></div>
    </dl>
    <details v-if="bars.length > 0" class="market-index-trend-card__table">
      <summary>查看当日点位数据</summary>
      <table>
        <caption>{{ identity.displayName }}已完成五分钟点位</caption>
        <thead><tr><th scope="col">时间</th><th scope="col">收盘点位</th></tr></thead>
        <tbody>
          <tr v-for="bar in bars" :key="bar.barAt"><td>{{ bar.barAt }}</td><td>{{ bar.closePoints }}</td></tr>
        </tbody>
      </table>
    </details>
    <p v-if="(summary?.issues ?? []).length > 0" class="market-index-trend-card__issues">
      问题：{{ summary?.issues.join("、") }}
    </p>
  </article>
</template>

<style scoped>
.market-index-trend-card {
  display: grid;
  gap: var(--space-3);
  min-width: 0;
  padding: var(--space-4) var(--space-6) var(--space-3);
  background: var(--color-surface-graphite);
  border-inline-start: .25rem solid var(--color-signal-live-sea-glass);
}

.market-index-trend-card[data-health="BLOCKED"],
.market-index-trend-card[data-health="GAPPED"] { border-inline-start-color: var(--color-signal-risk-vermilion); }
.market-index-trend-card[data-health="STALE"] { border-inline-start-color: var(--color-signal-watch-amber); }
.market-index-trend-card > *, .market-index-trend-card__header > *, .market-index-trend-card__facts > div { min-width: 0; }
.market-index-trend-card__header { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-4); align-items: baseline; justify-content: space-between; }
.market-index-trend-card__header h3 { display: inline; margin-inline-end: var(--space-2); }
.market-index-trend-card__header h3, .market-index-trend-card__header code, .market-index-trend-card__status, .market-index-trend-card__issues, .market-index-trend-card__facts dd { overflow-wrap: anywhere; }
.market-index-trend-card__status, .market-index-trend-card__issues { margin: 0; color: var(--color-text-muted); }
.market-index-trend-card__status button { margin-inline-start: var(--space-2); }
.market-index-trend-card__market-facts,
.market-index-trend-card__facts { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-6); margin: 0; }
.market-index-trend-card__market-facts div,
.market-index-trend-card__facts div { display: flex; gap: var(--space-2); align-items: baseline; min-width: 0; }
.market-index-trend-card__market-facts dt,
.market-index-trend-card__facts dt { color: var(--color-text-muted); }
.market-index-trend-card__market-facts dd,
.market-index-trend-card__facts dd { margin: 0; font-family: var(--font-numeric); }
.market-index-trend-card__primary-fact dd { font-size: 1.2rem; font-weight: 700; }
.market-index-trend-card[data-direction="down"] .market-index-trend-card__primary-fact dd { color: var(--color-signal-live-sea-glass); }
.market-index-trend-card[data-direction="up"] .market-index-trend-card__primary-fact dd { color: var(--color-signal-risk-vermilion); }
.market-index-trend-card__table { min-width: 0; }
.market-index-trend-card__table table {
  width: 100%;
  margin-block-start: var(--space-2);
  border-collapse: collapse;
  table-layout: fixed;
  font-family: var(--font-numeric);
}

.market-index-trend-card__table th,
.market-index-trend-card__table td {
  padding: var(--space-1);
  overflow-wrap: anywhere;
  text-align: start;
  border-block-start: var(--border-technical);
}

@media (max-width: 39.999rem) {
  .market-index-trend-card { padding-inline: var(--space-3); }
  .market-index-trend-card__market-facts,
  .market-index-trend-card__facts { gap-inline: var(--space-4); }
}
</style>
