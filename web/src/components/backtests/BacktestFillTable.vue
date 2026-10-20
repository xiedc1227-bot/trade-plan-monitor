<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";

import type { BacktestFillPage } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";
import { formatDisplayDateTime } from "../../formatters/dateTime";

interface Props {
  items: DeepReadonly<BacktestFillPage["items"]>;
}

const props = defineProps<Props>();
const emit = defineEmits<{ select: [fillId: string] }>();
const visibleItems = computed(() => props.items.slice(0, 100).map((item) => {
  if (!("receipt" in item)) return item;
  const receipt = item.receipt;
  const settlement = receipt.settlement;
  return {
    fillId: item.fillId,
    eventId: item.eventId,
    filledAt: item.filledAt,
    symbol: receipt.authority_receipt.inventory.symbol,
    side: receipt.authority_receipt.side,
    bucket: "—",
    quantity: receipt.authority_receipt.quantity,
    requestedQuantity: receipt.command.quantity,
    priceFen: String(settlement.fill_price_fen),
    notionalFen: String(settlement.notional_fen),
    fees: {
      commissionFen: String(settlement.commission_fen),
      stampDutyFen: String(settlement.stamp_duty_fen),
      transferFeeFen: String(settlement.transfer_fee_fen),
      totalFen: String(settlement.total_fees_fen),
    },
    cashDeltaFen: null,
    costBasisReleasedFen: receipt.released_cost_fen === null ? null : String(receipt.released_cost_fen),
    realizedPnlFen: null,
  };
}));

function visibleFen(value: string | null): string {
  return value === null ? "—" : formatFenAsYuan(value);
}
</script>

<template>
  <div class="fill-table__scroll" role="region" aria-label="模拟成交分页表格" tabindex="0">
    <table class="fill-table">
      <caption>当前页模拟成交（仅供研究）· 点击查看原因可追溯记录依据</caption>
      <thead><tr>
        <th scope="col">成交时间</th><th scope="col">方向</th><th scope="col">数量（股）</th>
        <th scope="col">价格（元）</th><th scope="col">费用（元）</th><th scope="col">结果</th>
        <th scope="col">原因与详情</th>
      </tr></thead>
      <tbody><tr v-for="item in visibleItems" :key="item.fillId" data-testid="backtest-fill-row">
        <td data-label="成交时间"><time :datetime="item.filledAt">{{ formatDisplayDateTime(item.filledAt) }}</time></td>
        <td data-label="方向">{{ item.side === 'BUY' ? '买入' : '卖出' }}</td>
        <td data-label="数量（股）">{{ item.quantity }} / {{ item.requestedQuantity }}</td>
        <td data-label="价格（元）">{{ formatFenAsYuan(item.priceFen) }}</td>
        <td data-label="费用（元）">{{ formatFenAsYuan(item.fees.totalFen) }}</td>
        <td data-label="结果">已模拟成交<span class="fill-table__sr-only">（仅供研究）</span></td>
        <td data-label="原因"><button v-if="'eventId' in item" type="button" data-testid="review-fill"
          :aria-label="`查看 ${formatDisplayDateTime(item.filledAt)} ${item.side === 'BUY' ? '买入' : '卖出'} ${item.quantity} 股的原因`"
          @click="emit('select', item.fillId)">查看原因</button><details><summary>成交详情</summary><dl>
          <dt>成交 ID</dt><dd>{{ item.fillId }}</dd><dt>股票</dt><dd>{{ item.symbol }}</dd><dt>仓位</dt><dd>{{ item.bucket }}</dd>
          <dt>名义金额（元）</dt><dd>{{ formatFenAsYuan(item.notionalFen) }}</dd>
          <dt>佣金（元）</dt><dd>{{ formatFenAsYuan(item.fees.commissionFen) }}</dd>
          <dt>印花税（元）</dt><dd>{{ formatFenAsYuan(item.fees.stampDutyFen) }}</dd>
          <dt>过户费（元）</dt><dd>{{ formatFenAsYuan(item.fees.transferFeeFen) }}</dd>
          <dt>现金变动（元）</dt><dd>{{ visibleFen(item.cashDeltaFen) }}</dd>
          <dt>释放成本（元）</dt><dd>{{ visibleFen(item.costBasisReleasedFen) }}</dd>
          <template v-if="!('eventId' in item)"><dt>本笔已实现盈亏（元）</dt><dd>{{ visibleFen(item.realizedPnlFen) }}</dd></template>
        </dl></details></td>
      </tr></tbody>
    </table>
  </div>
</template>

<style scoped>
.fill-table__scroll { max-width: 100%; overflow-x: auto; border: var(--border-technical); }
.fill-table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.fill-table caption { padding: var(--space-3); color: var(--color-text-silt); text-align: start; }
.fill-table th, .fill-table td { padding: var(--space-3); border-block-start: var(--border-technical); text-align: start; vertical-align: top; }
.fill-table th { color: var(--color-text-silt); font-size: .8rem; }
.fill-table th, .fill-table td:nth-child(2), .fill-table td:nth-child(3), .fill-table td:nth-child(6), button { white-space: nowrap; }
.fill-table__sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.fill-table td { font-family: var(--font-numeric); }
button, summary { min-height: 2.75rem; cursor: pointer; }
button { padding: var(--space-2) var(--space-3); color: inherit; background: var(--color-surface-raised); border: var(--border-technical); border-radius: var(--radius-control); }
dl { min-width: 10rem; margin: 0; font-size: .8125rem; } dt { color: var(--color-text-silt); } dd { margin: 0 0 var(--space-2); overflow-wrap: anywhere; }
:focus-visible { outline: .1875rem solid var(--color-focus-ring); outline-offset: .1875rem; }
@media(max-width:48rem) {
  .fill-table, tbody, tr, td, caption { display: block; width: auto; }
  thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  .fill-table td { display: grid; grid-template-columns: minmax(6rem, 1fr) minmax(0, 2fr); gap: var(--space-2); border: 0; padding-block: var(--space-2); overflow-wrap: anywhere; }
  .fill-table td::before { content: attr(data-label); color: var(--color-text-silt); font-size: .8125rem; }
  tr { border-block-start: var(--border-technical); padding-block: var(--space-3); }
}
</style>
