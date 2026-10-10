<script setup lang="ts">
import { computed } from "vue";

import type { ConnectionStatus, MarketIndexSnapshotView, MarketIndexOverviewItem, MarketSessionView } from "../../api/generated";
import { overviewItemSnapshot } from "../../api/marketIndexOverview";
import type { CanonicalMarketIndexIdentity } from "../../api/marketIndexIdentity";
import type { DashboardMarketIndexTrend } from "../../composables/useDashboardMarketIndexTrends";
import { marketIndexDirection, marketIndexValueDirection } from "./marketIndexChartOptions";
import MarketIndexSparkline from "./MarketIndexSparkline.vue";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  connectionStatus: ConnectionStatus;
  identity: CanonicalMarketIndexIdentity & {
    readonly indexCode: MarketIndexSnapshotView["indexCode"];
  };
  summary: MarketIndexSnapshotView | null;
  trend: DashboardMarketIndexTrend;
  item?: MarketIndexOverviewItem | null | undefined;
  marketSession?: MarketSessionView | undefined;
  cached?: boolean | undefined;
}

const props = defineProps<Props>();
const summary = computed(() => props.item === undefined ? props.summary : overviewItemSnapshot(props.item));
const bars = computed(() => props.item === undefined ? props.trend.page?.items ?? [] : props.item?.data?.bars ?? []);
const lastValidBarAt = computed(() => bars.value.at(-1)?.barAt ?? null);
const highPoints = computed(() => props.item === undefined ? extrema("highPoints", Math.max) : props.item?.data?.highPoints ?? null);
const lowPoints = computed(() => props.item === undefined ? extrema("lowPoints", Math.min) : props.item?.data?.lowPoints ?? null);
const currentDirection = computed(() => marketIndexValueDirection(
  summary.value?.closePoints,
  summary.value?.priorClosePoints,
));
const highDirection = computed(() => marketIndexValueDirection(
  highPoints.value,
  summary.value?.priorClosePoints,
));
const lowDirection = computed(() => marketIndexValueDirection(
  lowPoints.value,
  summary.value?.priorClosePoints,
));
const turnover = computed(() => {
  if (props.item !== undefined) {
    const amount = props.item?.data?.amount;
    return amount == null ? "—" : `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(Number(amount) / 100_000_000)}亿`;
  }
  const amounts = bars.value
    .map((bar) => bar.amount === null ? Number.NaN : Number(bar.amount))
    .filter(Number.isFinite);
  if (amounts.length === 0) return "—";
  const totalYi = amounts.reduce((sum, value) => sum + value, 0) / 100_000_000;
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(totalYi)}亿`;
});
const healthLabels = Object.freeze({
  BLOCKED: "阻断",
  GAPPED: "缺口",
  LIVE: "实时",
  STALE: "陈旧",
} as const);
const healthSymbols = Object.freeze({
  BLOCKED: "×",
  CACHED: "○",
  GAPPED: "!",
  LIVE: "●",
  NONE: "",
  STALE: "!",
} as const);
const displayedHealthState = computed<keyof typeof healthSymbols>(() => {
  if (props.item !== undefined) {
    if (!props.item?.data) return "NONE";
    if (props.cached || props.connectionStatus !== "CONNECTED" || props.item.dataStatus === "CACHED") return "CACHED";
    return props.item.dataStatus === "CURRENT" ? "LIVE" : "STALE";
  }
  if (summary.value === null) return "NONE";
  if (summary.value.health === "LIVE" && props.connectionStatus !== "CONNECTED") {
    return "CACHED";
  }
  return summary.value.health;
});
const displayedHealth = computed(() => {
  if (props.item !== undefined) {
    const phase = props.marketSession?.phase;
    const prefix = phase === "CLOSED" ? "已收市" : phase === "BREAK" ? "午间休市" : phase === "PREOPEN" ? "未开市" : phase === "UNKNOWN" ? "时段待确认" : "";
    const status = !props.item?.data ? "暂无行情" : displayedHealthState.value === "CACHED" ? "已缓存"
      : props.item.dataStatus === "UNVERIFIED" ? "数据待核验" : props.item.dataStatus === "INCOMPLETE"
        ? prefix ? "数据待补齐" : "数据待更新" : prefix ? "" : "实时";
    return [prefix, status].filter(Boolean).join(" · ");
  }
  if (summary.value === null) return "暂无快照";
  if (displayedHealthState.value === "CACHED") return "已缓存";
  return healthLabels[summary.value.health];
});
const displayedHealthSymbol = computed(() => healthSymbols[displayedHealthState.value]);
const shouldPulseLive = computed(() => displayedHealthState.value === "LIVE" && (props.item === undefined || props.marketSession?.phase === "OPEN"));
const healthSymbolKey = computed(() => {
  if (shouldPulseLive.value) return summary.value?.snapshotHash ?? "live";
  return displayedHealthState.value;
});
const chartLabel = computed(() => {
  const day = props.item === undefined ? "当日" : props.marketSession?.displayTradeDate ?? "所示日期";
  return `${props.identity.displayName}${day}五分钟指数走势，最新点位 ${summary.value?.closePoints ?? "未知"}，涨跌 ${formatSessionChange(summary.value?.sessionChangeRatio ?? null)}，数据截止 ${formatDisplayDateTime(summary.value?.completedBucketAt ?? null, "未知")}，${displayedHealth.value}，虚线为昨收点位`;
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

</script>

<template>
  <article
    class="market-index-trend-card"
    data-testid="market-index-trend-card"
    :data-health="displayedHealthState"
    :data-direction="currentDirection"
  >
    <header class="market-index-trend-card__header">
      <div>
        <h3>{{ identity.displayName }}</h3>
        <code>{{ identity.indexCode }}</code>
      </div>
      <strong
        class="market-index-trend-card__health"
        data-testid="market-index-health"
        :data-health="displayedHealthState"
      >
        <span>{{ displayedHealth }}</span>
        <span
          v-if="displayedHealthSymbol"
          :key="healthSymbolKey"
          aria-hidden="true"
          class="market-index-trend-card__health-symbol"
          :class="{ 'market-index-trend-card__health-symbol--live': shouldPulseLive }"
          data-testid="market-index-health-symbol"
        >{{ displayedHealthSymbol }}</span>
      </strong>
    </header>
    <dl class="market-index-trend-card__market-facts">
      <div class="market-index-trend-card__primary-fact">
        <dt>当前</dt><dd :data-direction="currentDirection">{{ formatPoints(summary?.closePoints ?? null) }}</dd>
      </div>
      <div><dt>最高</dt><dd class="market-index-trend-card__high" :data-direction="highDirection">{{ formatPoints(highPoints) }}</dd></div>
      <div><dt>最低</dt><dd class="market-index-trend-card__low" :data-direction="lowDirection">{{ formatPoints(lowPoints) }}</dd></div>
      <div><dt>成交额</dt><dd>{{ turnover }}</dd></div>
    </dl>
    <div class="market-index-trend-card__plot">
      <MarketIndexSparkline
        :ariaLabel="chartLabel"
        :bars="bars"
        :display-name="identity.displayName"
        :prior-close-points="summary?.priorClosePoints ?? null"
        :session-change-ratio="summary?.sessionChangeRatio ?? null"
      />
      <div v-if="bars.length === 0" class="market-index-trend-card__plot-empty">
        <span aria-hidden="true">— / —</span>
        <p>{{ item !== undefined ? '所示日期走势尚未就绪' : trend.status === 'LOADING' ? '正在加载当日走势' : '当日走势尚未就绪' }}</p>
        <small>已存点位与数据截止时间见下方</small>
      </div>
    </div>
    <p
      v-if="item?.latestAcquisition?.health === 'BLOCKED'"
      class="market-index-trend-card__status"
      role="status"
    >最近更新失败{{ item.data ? '，保留已取得行情' : '，暂无已取得行情' }}。
      <template v-if="item.latestAcquisition.nextRetryAt">下次补查 {{ formatDisplayDateTime(item.latestAcquisition.nextRetryAt) }}。</template>
      问题：{{ item.latestAcquisition.issues.join('、') }}
    </p>
    <p
      v-if="summary?.health === 'BLOCKED' && summary.issues.includes('PROVIDER_UNAVAILABLE')"
      class="market-index-trend-card__status"
      role="status"
    >
      指数数据暂不可用。
      <template v-if="summary?.nextRetryAt !== null && summary?.nextRetryAt !== undefined">
        系统将于 {{ formatDisplayDateTime(summary.nextRetryAt, "未知") }}
        执行第 {{ (summary.recoveryAttempts ?? 0) + 1 }}/3 次恢复。
      </template>
      <template v-else>等待下一次计划采集。</template>
      图表仅供参考，数据截至
      {{ formatDisplayDateTime(lastValidBarAt, "不可用") }}。
    </p>
    <p
      v-if="trend.status === 'LOADING'"
      class="market-index-trend-card__status"
      role="status"
    >
      正在加载当日五分钟走势…
    </p>
    <p
      v-else-if="bars.length === 0 && trend.status === 'EMPTY'"
      class="market-index-trend-card__status"
    >
      当前时段暂无已完成的五分钟数据。
    </p>
    <p v-else-if="bars.length === 0 && trend.status !== 'ERROR'" class="market-index-trend-card__status">{{ item !== undefined ? '所示日期暂无五分钟数据。' : '当前暂无当日五分钟数据。' }}</p>
    <dl class="market-index-trend-card__facts">
      <div>
        <dt>涨跌</dt>
        <dd
          class="market-index-trend-card__change"
          :data-direction="marketIndexDirection(summary?.sessionChangeRatio ?? null)"
        >{{ formatSessionChange(summary?.sessionChangeRatio ?? null) }}</dd>
      </div>
      <div><dt>昨收点位</dt><dd>{{ formatPoints(summary?.priorClosePoints ?? null) }}</dd></div>
      <div><dt>数据截止</dt><dd>{{ formatDisplayDateTime(summary?.completedBucketAt ?? null, "不可用") }}</dd></div>
    </dl>
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
  padding: var(--space-5) var(--space-6) var(--space-4);
  background: var(--color-surface-graphite);
}

.market-index-trend-card > *, .market-index-trend-card__header > *, .market-index-trend-card__facts > div { min-width: 0; }
.market-index-trend-card__header { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-4); align-items: baseline; justify-content: space-between; }
.market-index-trend-card__header h3 { display: inline; margin-inline-end: var(--space-2); }
.market-index-trend-card__header code { font-size: .6875rem; color: var(--color-text-muted); }
.market-index-trend-card__health { font-size: .6875rem; }
.market-index-trend-card__health { display: inline-flex; gap: var(--space-1); align-items: center; }
.market-index-trend-card__health[data-health="LIVE"] { color: var(--color-signal-live-sea-glass); }
.market-index-trend-card__health[data-health="BLOCKED"],
.market-index-trend-card__health[data-health="GAPPED"] { color: var(--color-signal-risk-vermilion); }
.market-index-trend-card__health[data-health="STALE"] { color: var(--color-signal-watch-amber); }
.market-index-trend-card__health[data-health="CACHED"],
.market-index-trend-card__health[data-health="NONE"] { color: var(--color-text-muted); }
.market-index-trend-card__health-symbol { display: inline-block; }
.market-index-trend-card__health-symbol--live {
  transform-origin: center;
  animation: market-index-live-pulse 600ms ease-out 1;
}
.market-index-trend-card__header h3, .market-index-trend-card__header code, .market-index-trend-card__status, .market-index-trend-card__issues, .market-index-trend-card__facts dd { overflow-wrap: anywhere; }
.market-index-trend-card__status, .market-index-trend-card__issues { margin: 0; color: var(--color-text-muted); font-size: .75rem; }
.market-index-trend-card__market-facts,
.market-index-trend-card__facts { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-6); margin: 0; }
.market-index-trend-card__market-facts div,
.market-index-trend-card__facts div { display: flex; gap: var(--space-2); align-items: baseline; min-width: 0; }
.market-index-trend-card__market-facts dt,
.market-index-trend-card__facts dt { color: var(--color-text-muted); }
.market-index-trend-card__market-facts dd,
.market-index-trend-card__facts dd { margin: 0; font-family: var(--font-numeric); }
.market-index-trend-card__primary-fact dd { font-size: 1.75rem; font-weight: 500; letter-spacing: -.03em; }
.market-index-trend-card__facts { padding-block-start: var(--space-3); border-block-start: var(--border-technical); font-size: .6875rem; }
.market-index-trend-card__market-facts { font-size: .75rem; }
.market-index-trend-card__plot { position: relative; min-width: 0; }
.market-index-trend-card__plot-empty { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); pointer-events: none; }
.market-index-trend-card__plot-empty > span { color: var(--color-signal-watch-amber); font: 1.125rem var(--font-numeric); letter-spacing: .15em; }
.market-index-trend-card__plot-empty p { margin: 0; padding: var(--space-1) var(--space-3); background: var(--color-surface-graphite); color: var(--color-text-muted); font-size: .8125rem; }
.market-index-trend-card__plot-empty small { padding-inline: var(--space-3); color: var(--color-text-muted); background: var(--color-surface-graphite); font-size: .6875rem; }
.market-index-trend-card__market-facts dd[data-direction="up"],
.market-index-trend-card__change[data-direction="up"] { color: var(--color-signal-risk-vermilion); }
.market-index-trend-card__market-facts dd[data-direction="down"],
.market-index-trend-card__change[data-direction="down"] { color: var(--color-signal-live-sea-glass); }
.market-index-trend-card__market-facts dd[data-direction="flat"],
.market-index-trend-card__change[data-direction="flat"] { color: var(--color-text-mineral); }
@keyframes market-index-live-pulse {
  0% { opacity: .45; transform: scale(.75); }
  45% { opacity: 1; transform: scale(1.35); }
  100% { opacity: 1; transform: scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .market-index-trend-card__health-symbol--live { animation: none; }
}
@media (max-width: 39.999rem) {
  .market-index-trend-card { padding-inline: var(--space-3); }
  .market-index-trend-card__market-facts,
  .market-index-trend-card__facts { gap-inline: var(--space-4); }
}
</style>
