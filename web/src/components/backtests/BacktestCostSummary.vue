<script setup lang="ts">
import { computed, type DeepReadonly } from "vue";
import type { BacktestExecutionConfigView, LoopCosts } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";

const props = defineProps<{ costs: DeepReadonly<LoopCosts | BacktestExecutionConfigView> }>();

// Shift validated decimal text exactly; display must not round historical rates.
function percentage(value: string, shift: 2 | -2): string {
  const [integer = "0", fraction = ""] = value.split(".");
  const digits = integer + fraction;
  const point = integer.length + shift;
  const whole = (point > 0 ? digits.slice(0, point).padEnd(point, "0") : "0").replace(/^0+(?=\d)/, "");
  const decimal = (point < 0 ? "0".repeat(-point) + digits : digits.slice(point)).replace(/0+$/, "");
  return `${whole}${decimal ? `.${decimal}` : ""}%`;
}

const costRows = computed(() => {
  const costs = props.costs;
  const config = "commission_rate" in costs ? {
    commissionRate: costs.commission_rate, minimumCommissionFen: String(costs.minimum_commission_fen),
    stampDutyRate: costs.stamp_duty_rate, transferFeeRate: costs.transfer_fee_rate,
  } : costs;
  return [
    ["佣金率", percentage(config.commissionRate, 2)],
    ["最低佣金", `${formatFenAsYuan(config.minimumCommissionFen)} 元/笔`],
    ["印花税率（仅卖出）", percentage(config.stampDutyRate, 2)],
    ["过户费率", percentage(config.transferFeeRate, 2)],
    ["买入滑点", "buy_slippage_fen" in costs ? `${formatFenAsYuan(String(costs.buy_slippage_fen))} 元/股` : `${percentage(costs.buySlippageBps, -2)}（价格比例）`],
    ["卖出滑点", "sell_slippage_fen" in costs ? `${formatFenAsYuan(String(costs.sell_slippage_fen))} 元/股` : `${percentage(costs.sellSlippageBps, -2)}（价格比例）`],
  ];
});
</script>

<template>
  <section class="cost-summary" aria-label="本次回测费用参数">
    <h4 class="cost-summary__title">本次回测费用参数</h4>
    <p class="cost-summary__note">以下为本次回测保存的参数，不受新建回测默认值影响。</p>
    <dl class="cost-summary__values">
      <template v-for="[title, value] in costRows" :key="title">
        <dt class="cost-summary__label">{{ title }}</dt><dd class="cost-summary__value">{{ value }}</dd>
      </template>
    </dl>
    <p class="cost-summary__note">佣金按成交金额和费率计算，不足最低佣金时按最低佣金收取；滑点表示模拟成交价格的偏移。</p>
  </section>
</template>

<style scoped>
.cost-summary { display: grid; gap: var(--space-3); min-width: 0; }
.cost-summary__title, .cost-summary__note { margin: 0; overflow-wrap: anywhere; }
.cost-summary__values { display: grid; grid-template-columns: minmax(8rem, 1fr) minmax(0, 3fr); gap: var(--space-2) var(--space-4); margin: 0; }
.cost-summary__label { color: var(--color-text-silt); }
.cost-summary__value { margin: 0; overflow-wrap: anywhere; }
@media (max-width: 36rem) { .cost-summary__values { grid-template-columns: minmax(0, 1fr); } .cost-summary__value { margin-block-end: var(--space-2); } }
</style>
