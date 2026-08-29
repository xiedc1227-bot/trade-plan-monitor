<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";

import type { BacktestEquityPointView } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";

interface Props {
  items: DeepReadonly<BacktestEquityPointView[]>;
}

const props = defineProps<Props>();
const visibleItems = computed(() => props.items.slice(0, 2_000));

function visibleShanghaiTime(value: string): string {
  return `${value.slice(0, 10)} ${value.slice(11, 19)} +08:00`;
}
</script>

<template>
  <div
    class="equity-table__scroll"
    role="region"
    aria-label="完整权益序列表格"
    tabindex="0"
  >
    <table class="equity-table">
      <caption>完整权益序列；表格数值为精确值，趋势图仅作辅助展示</caption>
      <thead>
        <tr>
          <th scope="col">标记时间</th>
          <th scope="col">快照 ID</th>
          <th scope="col">股票</th>
          <th scope="col">权益（元）</th>
          <th scope="col">现金（元）</th>
          <th scope="col">市值（元）</th>
          <th scope="col">持仓数量</th>
          <th scope="col">标记价格（元）</th>
          <th scope="col">成本基础（元）</th>
          <th scope="col">已实现盈亏（元）</th>
          <th scope="col">未实现盈亏（元）</th>
          <th scope="col">累计成本（元）</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in visibleItems"
          :key="`${item.markedAt}\u0000${item.snapshotId}`"
          data-testid="backtest-equity-row"
        >
          <td>
            <time :datetime="item.markedAt">{{ visibleShanghaiTime(item.markedAt) }}</time>
          </td>
          <td>{{ item.snapshotId }}</td>
          <td>{{ item.symbol }}</td>
          <td>{{ formatFenAsYuan(item.equityFen) }}</td>
          <td>{{ formatFenAsYuan(item.cashFen) }}</td>
          <td>{{ formatFenAsYuan(item.marketValueFen) }}</td>
          <td>{{ item.positionQuantity }}</td>
          <td>{{ formatFenAsYuan(item.markPriceFen) }}</td>
          <td>{{ formatFenAsYuan(item.costBasisFen) }}</td>
          <td>{{ formatFenAsYuan(item.realizedPnlFen) }}</td>
          <td>{{ formatFenAsYuan(item.unrealizedPnlFen) }}</td>
          <td>{{ formatFenAsYuan(item.totalCostFen) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.equity-table__scroll {
  max-width: 100%;
  overflow-x: auto;
  border: var(--border-technical);
}

.equity-table {
  width: 100%;
  min-width: 88rem;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}

.equity-table caption {
  padding: var(--space-3);
  color: var(--color-text-muted);
  text-align: start;
}

.equity-table th,
.equity-table td {
  padding: var(--space-3);
  border-block-start: var(--border-technical);
  text-align: start;
  white-space: nowrap;
}

.equity-table th {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.equity-table td {
  font-family: var(--font-numeric);
}

.equity-table__scroll:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}
</style>
