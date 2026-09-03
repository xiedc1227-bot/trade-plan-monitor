<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";

import type { BacktestDetailPage, BacktestDetailView } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";

interface Props {
  items: DeepReadonly<BacktestDetailView[]>;
  kind: BacktestDetailPage["kind"];
}

const props = defineProps<Props>();
const visibleItems = computed(() =>
  props.items.filter((item) => item.kind === props.kind).slice(0, 100),
);

const captions: Record<BacktestDetailPage["kind"], string> = {
  DECISION: "当前页决策明细",
  EXECUTION_OUTCOME: "当前页执行结果明细",
  SIGNAL: "当前页信号明细",
};

function visibleShanghaiTime(value: string): string {
  return `${value.slice(0, 10)} ${value.slice(11, 19)} +08:00`;
}

function optional(value: string | number | null): string | number {
  return value === null ? "—" : value;
}
</script>

<template>
  <div
    class="detail-table__scroll"
    role="region"
    :aria-label="`${captions[kind]}分页表格`"
    tabindex="0"
  >
    <table class="detail-table">
      <caption>{{ captions[kind] }}</caption>
      <thead v-if="kind === 'DECISION'">
        <tr>
          <th scope="col">事件时间</th>
          <th scope="col">明细 ID</th>
          <th scope="col">股票</th>
          <th scope="col">决策信号</th>
          <th scope="col">区域</th>
          <th scope="col">价格（元）</th>
          <th scope="col">风险状态</th>
          <th scope="col">下一步</th>
          <th scope="col">参考指数条件证据</th>
        </tr>
      </thead>
      <thead v-else-if="kind === 'SIGNAL'">
        <tr>
          <th scope="col">事件时间</th>
          <th scope="col">明细 ID</th>
          <th scope="col">股票</th>
          <th scope="col">信号</th>
          <th scope="col">仓位</th>
          <th scope="col">数量</th>
          <th scope="col">目标批次</th>
          <th scope="col">原因 ID</th>
        </tr>
      </thead>
      <thead v-else>
        <tr>
          <th scope="col">事件时间</th>
          <th scope="col">明细 ID</th>
          <th scope="col">状态</th>
          <th scope="col">原因</th>
          <th scope="col">信号 ID</th>
          <th scope="col">订单 ID</th>
          <th scope="col">成交 ID</th>
          <th scope="col">来源 Bar ID</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="item in visibleItems" :key="item.detailId">
          <tr
            v-if="item.kind === 'DECISION'"
            data-testid="backtest-detail-row"
          >
            <td><time :datetime="item.eventAt">{{ visibleShanghaiTime(item.eventAt) }}</time></td>
            <td>{{ item.detailId }}</td>
            <td>{{ item.decision.symbol }}</td>
            <td>{{ item.decision.signalType }}</td>
            <td>{{ item.decision.zone }}</td>
            <td>{{ item.decision.priceFen === null ? "—" : formatFenAsYuan(item.decision.priceFen) }}</td>
            <td>{{ item.decision.riskStatus }}</td>
            <td>{{ item.decision.nextStep.code }}</td>
            <td class="detail-table__evidence">
              <span v-if="item.decision.referenceMarket == null">—</span>
              <template v-else>
                <p>
                  <code>{{ item.decision.referenceMarket.indexCode }}</code> ·
                  {{ item.decision.referenceMarket.health }} ·
                  <time v-if="item.decision.referenceMarket.dataAt !== null" :datetime="item.decision.referenceMarket.dataAt">
                    {{ visibleShanghaiTime(item.decision.referenceMarket.dataAt) }}
                  </time>
                </p>
                <ul>
                  <li v-for="evidence in item.decision.referenceMarket.evidence" :key="evidence.planPath">
                    <code>{{ evidence.planPath }}</code> ·
                    <code>{{ evidence.conditionType }}</code> · {{ evidence.outcome }}；
                    实际 {{ optional(evidence.actualValue) }} / 对比 {{ optional(evidence.comparisonValue) }} {{ evidence.unit }}；
                    数据截止 {{ optional(evidence.dataCutoff) }}
                    <span v-if="(evidence.missingInputs ?? []).length > 0">
                      ；缺失 {{ (evidence.missingInputs ?? []).join("、") }}
                    </span>
                  </li>
                </ul>
              </template>
            </td>
          </tr>
          <tr
            v-else-if="item.kind === 'SIGNAL'"
            data-testid="backtest-detail-row"
          >
            <td><time :datetime="item.eventAt">{{ visibleShanghaiTime(item.eventAt) }}</time></td>
            <td>{{ item.detailId }}</td>
            <td>{{ item.symbol }}</td>
            <td>{{ item.signalType }}</td>
            <td>{{ optional(item.bucket) }}</td>
            <td>{{ optional(item.quantity) }}</td>
            <td>{{ optional(item.targetLotId) }}</td>
            <td>{{ item.causeId }}</td>
          </tr>
          <tr
            v-else
            data-testid="backtest-detail-row"
          >
            <td><time :datetime="item.eventAt">{{ visibleShanghaiTime(item.eventAt) }}</time></td>
            <td>{{ item.detailId }}</td>
            <td>{{ item.status }}</td>
            <td>{{ optional(item.reason) }}</td>
            <td>{{ item.signalId }}</td>
            <td>{{ optional(item.orderId) }}</td>
            <td>{{ optional(item.fillId) }}</td>
            <td>{{ optional(item.sourceBarId) }}</td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.detail-table__scroll {
  max-width: 100%;
  overflow-x: auto;
  border: var(--border-technical);
}

.detail-table {
  width: 100%;
  min-width: 62rem;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}

.detail-table caption {
  padding: var(--space-3);
  color: var(--color-text-muted);
  text-align: start;
}

.detail-table th,
.detail-table td {
  padding: var(--space-3);
  border-block-start: var(--border-technical);
  text-align: start;
  white-space: nowrap;
}

.detail-table th {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.detail-table td {
  font-family: var(--font-numeric);
}

.detail-table td.detail-table__evidence {
  min-width: 34rem;
  white-space: normal;
}

.detail-table__evidence p,
.detail-table__evidence ul {
  margin-block: 0 var(--space-2);
}

.detail-table__scroll:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}
</style>
