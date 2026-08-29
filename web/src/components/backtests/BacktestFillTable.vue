<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";

import type { BacktestFillView } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";

interface Props {
  items: DeepReadonly<BacktestFillView[]>;
}

const props = defineProps<Props>();
const visibleItems = computed(() => props.items.slice(0, 100));

function visibleShanghaiTime(value: string): string {
  return `${value.slice(0, 10)} ${value.slice(11, 19)} +08:00`;
}

function visibleFen(value: string | null): string {
  return value === null ? "—" : formatFenAsYuan(value);
}
</script>

<template>
  <div
    class="fill-table__scroll"
    role="region"
    aria-label="模拟成交分页表格"
    tabindex="0"
  >
    <table class="fill-table">
      <caption>当前页模拟成交（仅供研究）</caption>
      <thead>
        <tr>
          <th scope="col">性质</th>
          <th scope="col">成交时间</th>
          <th scope="col">成交 ID</th>
          <th scope="col">股票</th>
          <th scope="col">方向</th>
          <th scope="col">仓位</th>
          <th scope="col">数量</th>
          <th scope="col">价格（元）</th>
          <th scope="col">名义金额（元）</th>
          <th scope="col">佣金（元）</th>
          <th scope="col">印花税（元）</th>
          <th scope="col">过户费（元）</th>
          <th scope="col">总费用（元）</th>
          <th scope="col">现金变动（元）</th>
          <th scope="col">释放成本（元）</th>
          <th scope="col">已实现盈亏（元）</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in visibleItems"
          :key="item.fillId"
          data-testid="backtest-fill-row"
        >
          <td>模拟成交（仅供研究）</td>
          <td>
            <time :datetime="item.filledAt">{{ visibleShanghaiTime(item.filledAt) }}</time>
          </td>
          <td>{{ item.fillId }}</td>
          <td>{{ item.symbol }}</td>
          <td>{{ item.side }}</td>
          <td>{{ item.bucket }}</td>
          <td>{{ item.quantity }} / {{ item.requestedQuantity }}</td>
          <td>{{ formatFenAsYuan(item.priceFen) }}</td>
          <td>{{ formatFenAsYuan(item.notionalFen) }}</td>
          <td>{{ formatFenAsYuan(item.fees.commissionFen) }}</td>
          <td>{{ formatFenAsYuan(item.fees.stampDutyFen) }}</td>
          <td>{{ formatFenAsYuan(item.fees.transferFeeFen) }}</td>
          <td>{{ formatFenAsYuan(item.fees.totalFen) }}</td>
          <td>{{ formatFenAsYuan(item.cashDeltaFen) }}</td>
          <td>{{ formatFenAsYuan(item.costBasisReleasedFen) }}</td>
          <td>{{ visibleFen(item.realizedPnlFen) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.fill-table__scroll {
  max-width: 100%;
  overflow-x: auto;
  border: var(--border-technical);
}

.fill-table {
  width: 100%;
  min-width: 96rem;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}

.fill-table caption {
  padding: var(--space-3);
  color: var(--color-text-muted);
  text-align: start;
}

.fill-table th,
.fill-table td {
  padding: var(--space-3);
  border-block-start: var(--border-technical);
  text-align: start;
  white-space: nowrap;
}

.fill-table th {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.fill-table td {
  font-family: var(--font-numeric);
}

.fill-table__scroll:focus-visible {
  outline: 0.1875rem solid var(--color-focus-ring);
  outline-offset: 0.1875rem;
}
</style>
