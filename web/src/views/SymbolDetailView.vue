<script setup lang="ts">
import { computed, defineAsyncComponent, shallowRef } from "vue";

import type {
  BarView,
  DataHealthStatus,
  EvidenceFactView,
  MarketIndexBarView,
  PositionLotPage,
  PositionPrefillView,
  SymbolDetailResponse,
  SymbolDetailUnavailableResponse,
  SymbolEventView,
} from "../api/generated";
import type { ManualEventRiskApi } from "../api/manualEventRisk";
import type { PositionInventoryApi } from "../api/positions";
import EpisodeTimeline from "../components/symbol/EpisodeTimeline.vue";
import MarketIndexChart from "../components/market-index/MarketIndexChart.vue";
import ReferenceMarketPanel from "../components/market-index/ReferenceMarketPanel.vue";
import PositionLots from "../components/symbol/PositionLots.vue";
import PositionInventoryPanel from "../components/symbol/PositionInventoryPanel.vue";
import ManualEventRiskPanel from "../components/symbol/ManualEventRiskPanel.vue";
import type { ChartRange } from "../components/symbol/PriceChart.vue";
import { useChartSeries } from "../composables/useChartSeries";
import type { PositionOperations } from "../composables/usePositions";
import { formatDisplayDateTime, formatDisplayFactValue } from "../formatters/dateTime";

interface Props {
  bars: readonly BarView[];
  detail: SymbolDetailResponse | null;
  error?: string | null;
  events: readonly SymbolEventView[];
  loading?: boolean;
  manualEventRiskApi?: ManualEventRiskApi | null;
  indexBars?: readonly MarketIndexBarView[];
  indexHistoryError?: string | null;
  indexHistoryLoading?: boolean;
  indexHistorySnapshotHash?: string | null;
  positionAsOfTradeDate?: string | null;
  positionApi?: PositionInventoryApi | null;
  positionOperations?: PositionOperations | null;
  positionPage?: PositionLotPage | null;
  positionPrefill?: PositionPrefillView | null;
  stale?: boolean;
  unavailable?: SymbolDetailUnavailableResponse | null;
}

interface Emits {
  rangeChange: [range: ChartRange];
  selectTime: [occurredAt: string];
}

const props = withDefaults(defineProps<Props>(), {
  error: null,
  loading: false,
  manualEventRiskApi: null,
  indexBars: () => [],
  indexHistoryError: null,
  indexHistoryLoading: false,
  indexHistorySnapshotHash: null,
  positionAsOfTradeDate: null,
  positionApi: null,
  positionOperations: null,
  positionPage: null,
  positionPrefill: null,
  stale: false,
  unavailable: null,
});
const emit = defineEmits<Emits>();
const PriceChart = defineAsyncComponent(() => import("../components/symbol/PriceChart.vue"));
const selectedAt = shallowRef<string | null>(null);
const referenceMarket = computed(
  () => props.detail?.referenceMarket ?? props.detail?.summary.referenceMarket ?? null,
);
const indexConditionEvidence = computed(
  () => props.detail?.indexConditionEvidence ?? [],
);
const { series } = useChartSeries({
  bars: () => props.bars,
  decision: () => props.detail?.summary.decision ?? null,
  events: () => props.events,
});

const healthLabels: Readonly<Record<DataHealthStatus, string>> = Object.freeze({
  BLOCKED: "阻断",
  CLOSE_PENDING: "收盘待确认",
  DEGRADED: "降级",
  GAPPED: "缺口",
  LIVE: "实时",
  STALE: "陈旧",
  STARTING: "启动中",
});

const visiblyStale = computed(() => {
  const summary = props.detail?.summary;
  return (
    props.stale ||
    (summary !== undefined &&
      (!summary.connected ||
        summary.decision.dataHealth.status !== "LIVE" ||
        !summary.decision.dataHealth.fresh))
  );
});

interface AccessibleOverlayRow {
  id: string;
  kind: string;
  label: string;
  time: string;
  value: string;
}

const overlayRows = computed<readonly AccessibleOverlayRow[]>(() => {
  const rows: AccessibleOverlayRow[] = [
    ...series.value.priceLevels.map((level) => ({
      id: level.id,
      kind: "价格线",
      label: level.label,
      time: formatDisplayDateTime(props.detail?.summary.decision.marketDataAt),
      value: `${level.valueYuan.toFixed(2)} 元`,
    })),
    ...series.value.indicators.map((indicator) => ({
      id: indicator.id,
      kind: "指标证据",
      label: indicator.label,
      time: formatDisplayDateTime(indicator.time, "未知"),
      value: `${indicator.valueText} 元`,
    })),
    ...series.value.alertMarkers.map((marker) => ({
      id: marker.eventId,
      kind: "提醒标记",
      label: marker.signalType ?? "提醒",
      time: formatDisplayDateTime(marker.time),
      value: marker.messageText ?? marker.label,
    })),
  ];
  if (series.value.episodeLow !== null) {
    rows.push({
      id: `episode-low:${series.value.episodeLow.time}`,
      kind: "阶段事实",
      label: series.value.episodeLow.label,
      time: "未知",
      value: `${series.value.episodeLow.valueYuan.toFixed(2)} 元`,
    });
  }
  return Object.freeze(rows);
});

function selectTimelineTime(occurredAt: string): void {
  selectedAt.value = occurredAt;
  emit("selectTime", occurredAt);
}

function evidenceLabel(depth: number, code: string): string {
  return `${"— ".repeat(depth)}${code}`;
}

function formatFact(fact: EvidenceFactView): string {
  return `${fact.key}=${formatDisplayFactValue(fact.value, fact.unit)} ${fact.unit}`;
}

function forwardRange(range: ChartRange): void {
  emit("rangeChange", range);
}

function formatHealth(detailValue: SymbolDetailResponse): string {
  return healthLabels[detailValue.summary.decision.dataHealth.status];
}
</script>

<template>
  <section class="symbol-detail" aria-labelledby="symbol-detail-title">
    <header class="symbol-detail__header">
      <div>
        <h1 id="symbol-detail-title">
          {{ detail === null ? "个股详情" : `${detail.summary.name} · ${detail.summary.symbol}` }}
        </h1>
      </div>
      <dl v-if="detail !== null" class="symbol-detail__meta">
        <div class="symbol-detail__meta-item">
          <dt>计划版本</dt>
          <dd class="symbol-detail__meta-value">{{ detail.summary.decision.planVersion }}</dd>
        </div>
        <div class="symbol-detail__meta-item">
          <dt>当前判断</dt>
          <dd class="symbol-detail__meta-value">{{ detail.summary.decision.signalType }}</dd>
        </div>
        <div class="symbol-detail__meta-item">
          <dt>数据健康</dt>
          <dd class="symbol-detail__meta-value">{{ formatHealth(detail) }}</dd>
        </div>
        <div class="symbol-detail__meta-item">
          <dt>连接</dt>
          <dd class="symbol-detail__meta-value">
            {{ detail.summary.connected ? "已连接" : "已断开" }}
          </dd>
        </div>
        <div class="symbol-detail__meta-item">
          <dt>行情时间</dt>
          <dd class="symbol-detail__meta-value">
            {{ formatDisplayDateTime(detail.summary.decision.marketDataAt, "未知") }}
          </dd>
        </div>
        <div class="symbol-detail__meta-item">
          <dt>数据年龄</dt>
          <dd class="symbol-detail__meta-value">
            {{
              detail.summary.decision.dataAgeSeconds === null
                ? "数据年龄未知"
                : `数据年龄 ${detail.summary.decision.dataAgeSeconds} 秒`
            }}
          </dd>
        </div>
      </dl>
    </header>

    <p v-if="error" class="symbol-detail__error" role="alert">{{ error }}</p>
    <p v-if="loading" class="symbol-detail__loading" role="status" aria-live="polite">
      正在加载个股权威详情；已有内容会继续显示。
    </p>
    <p
      v-if="detail !== null && visiblyStale"
      class="symbol-detail__stale"
      role="status"
      aria-live="polite"
    >
      陈旧 / 降级：当前事实保留供审阅，但不得视为实时数据。
    </p>

    <p
      v-if="unavailable !== null"
      class="symbol-detail__unavailable"
      data-testid="detail-unavailable"
      role="status"
      aria-live="polite"
    >
      该股票的权威监控投影尚未就绪（{{ unavailable.reason }}，序列 {{ unavailable.sequence }}）。
    </p>

    <p
      v-if="unavailable === null && detail === null && !loading && !error"
      class="symbol-detail__empty"
      data-testid="detail-empty"
    >
      暂无个股详情。
    </p>

    <template v-if="detail !== null">
      <ReferenceMarketPanel
        :reference="referenceMarket"
        :evidence="indexConditionEvidence"
        :plan="detail.summary.decision"
      />

      <MarketIndexChart
        v-if="referenceMarket"
        :bars="indexBars"
        :error="indexHistoryError"
        :loading="indexHistoryLoading"
        :snapshot-hash="indexHistorySnapshotHash"
      />

      <PriceChart :series="series" :stale="visiblyStale" @range-change="forwardRange" />

      <details class="symbol-detail__panel" open>
        <summary class="symbol-detail__summary">图表数据表格替代</summary>
        <p v-if="series.candles.length === 0" class="symbol-detail__empty" data-testid="bars-empty">
          暂无 K 线数据；不会根据其他字段补造价格历史。
        </p>
        <div class="symbol-detail__table-scroller" tabindex="0" aria-label="K 线数据表，可横向滚动">
          <table class="symbol-detail__table" data-testid="bar-table">
            <caption class="symbol-detail__caption">与价格图表相同的后端 OHLC 事实</caption>
            <thead class="symbol-detail__table-head">
              <tr>
                <th class="symbol-detail__cell" scope="col">时间</th>
                <th class="symbol-detail__cell" scope="col">开</th>
                <th class="symbol-detail__cell" scope="col">高</th>
                <th class="symbol-detail__cell" scope="col">低</th>
                <th class="symbol-detail__cell" scope="col">收</th>
                <th class="symbol-detail__cell" scope="col">成交量</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="candle in series.candles" :key="candle.time" data-testid="bar-row">
                <th class="symbol-detail__cell" scope="row">
                  <time :datetime="candle.time">{{ formatDisplayDateTime(candle.time) }}</time>
                </th>
                <td class="symbol-detail__cell">{{ candle.openYuan.toFixed(2) }}</td>
                <td class="symbol-detail__cell">{{ candle.highYuan.toFixed(2) }}</td>
                <td class="symbol-detail__cell">{{ candle.lowYuan.toFixed(2) }}</td>
                <td class="symbol-detail__cell">{{ candle.closeYuan.toFixed(2) }}</td>
                <td class="symbol-detail__cell">{{ candle.volumeShares }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div
          class="symbol-detail__table-scroller"
          tabindex="0"
          aria-label="图表叠加事实表，可横向滚动"
        >
          <table class="symbol-detail__table" data-testid="overlay-table">
            <caption class="symbol-detail__caption">与图表相同的后端叠加事实和事件</caption>
            <thead class="symbol-detail__table-head">
              <tr>
                <th class="symbol-detail__cell" scope="col">类型</th>
                <th class="symbol-detail__cell" scope="col">标签</th>
                <th class="symbol-detail__cell" scope="col">值</th>
                <th class="symbol-detail__cell" scope="col">时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in overlayRows" :key="row.id">
                <td class="symbol-detail__cell">{{ row.kind }}</td>
                <th class="symbol-detail__cell" scope="row">{{ row.label }}</th>
                <td class="symbol-detail__cell symbol-detail__wrap">{{ row.value }}</td>
                <td class="symbol-detail__cell">{{ row.time }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>

      <section class="symbol-detail__panel" aria-labelledby="evidence-title">
        <h2 id="evidence-title">判断证据与阻断</h2>
        <div
          class="symbol-detail__table-scroller"
          tabindex="0"
          aria-label="判断证据表，可横向滚动"
        >
          <table class="symbol-detail__table" data-testid="evidence-table">
            <caption class="symbol-detail__caption">后端权威判断证据、结果、事实及缺失输入</caption>
            <thead class="symbol-detail__table-head">
              <tr>
                <th class="symbol-detail__cell" scope="col">证据</th>
                <th class="symbol-detail__cell" scope="col">种类</th>
                <th class="symbol-detail__cell" scope="col">结果</th>
                <th class="symbol-detail__cell" scope="col">数值事实</th>
                <th class="symbol-detail__cell" scope="col">缺失输入</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in series.evidenceRows" :key="row.id">
                <th class="symbol-detail__cell" scope="row">
                  {{ evidenceLabel(row.depth, row.code) }}
                </th>
                <td class="symbol-detail__cell">{{ row.kind }}</td>
                <td class="symbol-detail__cell">{{ row.outcome }}</td>
                <td class="symbol-detail__cell symbol-detail__wrap">
                  <span v-for="fact in row.facts" :key="fact.key" class="symbol-detail__fact">
                    {{ formatFact(fact) }}
                  </span>
                  <span v-if="row.facts.length === 0">—</span>
                </td>
                <td class="symbol-detail__cell symbol-detail__wrap">
                  {{ row.missingInputs.length === 0 ? "—" : row.missingInputs.join("、") }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <PositionLots
        :symbol="detail.summary.symbol"
        :as-of-trade-date="positionAsOfTradeDate ?? detail.summary.observedAt.slice(0, 10)"
        :initial-page="positionPage"
        :operations="positionOperations"
        :prefill="positionPrefill"
        :summary-lots="detail.positionLots ?? []"
      />

      <PositionInventoryPanel
        v-if="positionApi !== null"
        :api="positionApi"
        :as-of-trade-date="positionAsOfTradeDate ?? detail.summary.observedAt.slice(0, 10)"
        :symbol="detail.summary.symbol"
      />

      <ManualEventRiskPanel
        :api="manualEventRiskApi"
        :symbol="detail.summary.symbol"
      />

      <EpisodeTimeline
        :events="events"
        :selected-at="selectedAt"
        @select-time="selectTimelineTime"
      />
    </template>
  </section>
</template>

<style scoped>
.symbol-detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  width: 100%;
  min-width: 0;
  max-width: 100rem;
  margin: 0 auto;
  gap: var(--space-5);
}

.symbol-detail > * {
  min-width: 0;
  max-width: 100%;
}

.symbol-detail__header {
  display: flex;
  gap: var(--space-4);
  align-items: end;
  justify-content: space-between;
  border-block-end: var(--border-technical);
}

.symbol-detail__header h1 {
  overflow-wrap: anywhere;
}

.symbol-detail__meta {
  display: flex;
  gap: var(--space-4);
}

.symbol-detail__meta-item {
  display: grid;
  gap: var(--space-1);
}

.symbol-detail__meta-value {
  margin: 0;
  font-family: var(--font-numeric);
}

.symbol-detail__error,
.symbol-detail__unavailable,
.symbol-detail__loading,
.symbol-detail__stale,
.symbol-detail__empty {
  margin: 0;
  padding: var(--space-4);
  overflow-wrap: anywhere;
  background: var(--color-surface-raised);
  border-inline-start: 0.25rem solid var(--color-signal-watch-amber);
}

.symbol-detail__error,
.symbol-detail__stale {
  border-inline-start-color: var(--color-signal-risk-vermilion);
}

.symbol-detail__panel {
  padding: var(--space-4);
  background: var(--color-surface-graphite);
  border: var(--border-technical);
}

.symbol-detail__summary {
  cursor: pointer;
  font-weight: 700;
}

.symbol-detail__table-scroller {
  margin-block-start: var(--space-4);
  overflow-x: auto;
  border: var(--border-technical);
}

.symbol-detail__table {
  width: 100%;
  min-width: 48rem;
  border-collapse: collapse;
  font-family: var(--font-numeric);
}

.symbol-detail__caption {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.symbol-detail__table-head {
  color: var(--color-signal-info-cyan);
  background: var(--color-surface-raised);
}

.symbol-detail__cell {
  padding: var(--space-2) var(--space-3);
  text-align: start;
  vertical-align: top;
  border-block-end: var(--border-technical);
}

.symbol-detail__wrap,
.symbol-detail__fact {
  overflow-wrap: anywhere;
}

.symbol-detail__fact {
  display: block;
}

@media (max-width: 47.999rem) {
  .symbol-detail__header,
  .symbol-detail__meta {
    align-items: start;
    flex-direction: column;
  }
}
</style>
