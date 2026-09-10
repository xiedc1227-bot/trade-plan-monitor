<script setup lang="ts">
import { RouterLink } from "vue-router";

import type {
  DataHealthStatus,
  DecisionZone,
  SignalType,
  SymbolSummaryView,
} from "../../api/generated";
import ConditionProgress from "./ConditionProgress.vue";
import IndexConditionProgress from "../market-index/IndexConditionProgress.vue";
import type { WatchlistViewMode } from "./WatchlistToolbar.vue";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  density: WatchlistViewMode;
  rows: readonly SymbolSummaryView[];
}

interface Emits {
  selectSymbol: [symbol: string];
}

defineProps<Props>();
const emit = defineEmits<Emits>();

const zoneLabels: Readonly<Record<DecisionZone, string>> = {
  BELOW_RISK: "风险线下",
  LOW_BUY: "低吸区",
  OBSERVATION: "观察区",
  OUTSIDE: "区间外",
  PRESSURE: "压力区",
  UNKNOWN: "区间未知",
};

const signalLabels: Readonly<Record<SignalType, string>> = {
  BLOCKED_DATA: "数据阻断",
  BLOCKED_RISK: "风险阻断",
  BUY_CORE_READY: "核心买入就绪",
  BUY_TACTICAL_READY: "机动买入就绪",
  LOW_ZONE_WATCH: "低吸观察",
  PRESSURE_REDUCE_READY: "压力减仓就绪",
  RISK_BREACH: "风险线跌破",
  RISK_EXIT_PENDING_SETTLEMENT: "风险退出待交收",
  RISK_EXIT_READY: "风险退出就绪",
  RISK_RECOVERED: "风险已恢复",
  WAIT: "等待",
};

const healthLabels: Readonly<Record<DataHealthStatus, string>> = {
  BLOCKED: "阻断",
  CLOSE_PENDING: "收盘待确认",
  DEGRADED: "降级",
  GAPPED: "缺口",
  LIVE: "实时",
  STALE: "陈旧",
  STARTING: "启动中",
};

function formatFen(value: number | null): string {
  return value === null ? "—" : `${(value / 100).toFixed(2)} 元`;
}

function formatRiskDistance(value: number | null): string {
  if (value === null) {
    return "—";
  }
  const yuan = value / 100;
  return `${yuan > 0 ? "+" : ""}${yuan.toFixed(2)} 元`;
}

function isBlocked(signal: SignalType): boolean {
  return signal === "BLOCKED_DATA" || signal === "BLOCKED_RISK";
}
</script>

<template>
  <div class="watchlist-table__scroller" tabindex="0" aria-label="监控股票表格，可横向滚动">
    <table class="watchlist-table" :data-density="density">
      <caption class="watchlist-table__caption">最多十只股票的权威监控摘要</caption>
      <thead class="watchlist-table__head">
        <tr class="watchlist-table__row">
          <th class="watchlist-table__cell" scope="col">股票</th>
          <th class="watchlist-table__cell" scope="col">价格 / 区间</th>
          <th class="watchlist-table__cell" scope="col">条件进度</th>
          <th class="watchlist-table__cell" scope="col">参考指数</th>
          <th class="watchlist-table__cell" scope="col">计划指数条件</th>
          <th class="watchlist-table__cell" scope="col">信号</th>
          <th class="watchlist-table__cell" scope="col">持仓</th>
          <th class="watchlist-table__cell" scope="col">风险距离</th>
          <th class="watchlist-table__cell" scope="col">行情时间</th>
          <th class="watchlist-table__cell" scope="col">健康</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.symbol"
          class="watchlist-table__row"
          data-testid="watchlist-row"
        >
          <th class="watchlist-table__cell" scope="row">
            <RouterLink
              class="watchlist-table__link"
              :to="`/stocks/${row.symbol}`"
              @click="emit('selectSymbol', row.symbol)"
            >
              {{ row.symbol }}
            </RouterLink>
            <span class="watchlist-table__name">{{ row.name }}</span>
          </th>
          <td class="watchlist-table__cell">
            <strong class="watchlist-table__numeric">{{ formatFen(row.decision.priceFen) }}</strong>
            <span>{{ zoneLabels[row.decision.zone] }}</span>
          </td>
          <td class="watchlist-table__cell">
            <ConditionProgress
              :blocked="isBlocked(row.decision.signalType)"
              :satisfied-count="row.satisfiedConditionCount"
              :total-count="row.totalConditionCount"
            />
          </td>
          <td class="watchlist-table__cell">
            <template v-if="row.referenceMarket">
              <strong>{{ row.referenceMarket.displayName }}</strong>
              <span>{{ row.referenceMarket.indexCode }}</span>
              <span>{{ row.referenceMarket.health }}</span>
            </template>
            <span v-else>未迁移（Schema v1）</span>
          </td>
          <td class="watchlist-table__cell">
            <IndexConditionProgress
              v-if="row.referenceMarket"
              :progress="row.referenceMarket.conditionProgress"
            />
            <span v-else>计划未使用</span>
          </td>
          <td class="watchlist-table__cell">
            <span :data-signal="row.decision.signalType">
              {{ signalLabels[row.decision.signalType] }}
            </span>
          </td>
          <td class="watchlist-table__cell watchlist-table__position">
            <span>总计 {{ row.decision.position.totalQuantity }}</span>
            <span>底仓 {{ row.decision.position.coreQuantity }}</span>
            <span>机动 {{ row.decision.position.tacticalQuantity }}</span>
          </td>
          <td class="watchlist-table__cell watchlist-table__numeric">
            风险距离 {{ formatRiskDistance(row.riskDistanceFen) }}
          </td>
          <td class="watchlist-table__cell">
            <time
              class="watchlist-table__time"
              :datetime="row.decision.marketDataAt ?? row.observedAt"
            >
              {{ formatDisplayDateTime(row.decision.marketDataAt ?? row.observedAt) }}
            </time>
          </td>
          <td class="watchlist-table__cell">
            <strong :data-health="row.decision.dataHealth.status">
              {{ healthLabels[row.decision.dataHealth.status] }}
            </strong>
            <span>{{ row.connected ? "已连接" : "已断开" }}</span>
            <span>
              {{ row.decision.dataAgeSeconds === null ? "年龄未知" : `${row.decision.dataAgeSeconds} 秒` }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.watchlist-table__scroller {
  overflow-x: auto;
  border: var(--border-technical);
}

.watchlist-table {
  width: 100%;
  min-width: 72rem;
  border-collapse: collapse;
  background: var(--color-surface-graphite);
}

.watchlist-table__caption {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.watchlist-table__cell {
  padding: var(--space-3);
  vertical-align: top;
  text-align: start;
  border-block-end: var(--border-technical);
}

.watchlist-table[data-density="COMPACT"] .watchlist-table__cell {
  padding-block: var(--space-2);
}

.watchlist-table__head {
  color: var(--color-signal-info-cyan);
  background: var(--color-surface-raised);
}

.watchlist-table__row:hover,
.watchlist-table__row:focus-within {
  background: var(--color-surface-raised);
}

.watchlist-table th > span,
.watchlist-table td > span,
.watchlist-table td > strong,
.watchlist-table td > time {
  display: block;
}

.watchlist-table__link {
  color: var(--color-signal-info-cyan);
  text-underline-offset: 0.2em;
}

.watchlist-table__name,
.watchlist-table__position {
  color: var(--color-text-muted);
}

.watchlist-table__numeric,
.watchlist-table__time {
  font-family: var(--font-numeric);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

[data-signal="RISK_BREACH"],
[data-signal="RISK_EXIT_READY"],
[data-signal="RISK_EXIT_PENDING_SETTLEMENT"],
[data-health="BLOCKED"],
[data-health="GAPPED"],
[data-health="DEGRADED"] {
  color: var(--color-signal-risk-vermilion);
}
</style>
