<script setup lang="ts">
import { computed } from "vue";
import type { EconomicsResult } from "../../api/generated";
const props = defineProps<{ result: EconomicsResult }>();
const labels = { NONE: "不计算费用", PASS: "估算条件满足", FAIL: "买入门槛未满足", UNKNOWN: "必要依据不足" };
const reasons: Record<string, string> = {
  FEE_SCHEDULE_NOT_APPLICABLE: "费用表不适用于当前证券或日期，请核对有效期。",
  ECONOMICS_INPUT_UNKNOWN: "尚缺完整数量或合格报价，暂时无法估算。",
  ECONOMICS_PRICE_ORDER: "当前买价须高于风险价、低于目标价。",
  ECONOMICS_SLIPPAGE_PRICE: "扣除卖出滑点后的价格无效，请复核费用假设。",
  ECONOMICS_OVERFLOW: "估算金额超出可精确表示的范围。",
  ECONOMICS_RISK_UNDEFINED: "计划风险损失须大于零，暂时无法比较收益风险。",
  ECONOMICS_GATE_UNMET: "当前估算未达到原文明确的买入门槛。",
};
const explanations = computed(() => [...new Set([props.result.reason, ...(props.result.blockers ?? [])])]
  .filter((code): code is string => Boolean(code)).map(code => reasons[code] ?? "当前费用依据尚不满足，请刷新并复核。"));
const feeGroups = computed(() => [
  { label: "买入", values: props.result.entry_fees },
  { label: "目标卖出", values: props.result.target_fees },
  { label: "风险卖出", values: props.result.risk_fees },
]);
const money = (value: number | null | undefined) => value == null ? "未知" : `${(value / 100).toFixed(2)} 元`;
</script>
<template>
  <div class="p2-economics" role="status">
    <p>{{ labels[result.outcome] }}；数量 {{ result.quantity ?? '尚未指定' }} 股。</p>
    <dl v-if="result.outcome !== 'NONE'" class="p2-economics__values">
      <dt>买入支出估算</dt><dd>{{ money(result.entry_debit_fen) }}</dd>
      <dt>目标净回报估算</dt><dd>{{ money(result.net_reward_fen) }}</dd>
      <dt>计划风险损失估算</dt><dd>{{ money(result.planned_loss_fen) }}</dd>
      <dt>往返费用与滑点</dt><dd>{{ money(result.total_cost_fen) }}</dd>
      <dt>每股打平价差（分）</dt><dd>{{ result.spread_numerator ?? '未知' }} / {{ result.spread_denominator ?? '未知' }}</dd>
    </dl>
    <p v-for="explanation in explanations" :key="explanation">{{ explanation }}</p>
    <details v-if="result.entry_fees"><summary>费用分项（分）</summary>
      <div v-for="group in feeGroups" :key="group.label">
        <h5>{{ group.label }}</h5>
        <dl class="p2-economics__values">
          <template v-for="(amount, name) in group.values" :key="name">
            <dt>{{ name === 'COMMISSION' ? '佣金' : name }}</dt><dd>{{ amount }} 分</dd>
          </template>
        </dl>
      </div>
    </details>
    <p>研究估算，不是实际盈亏、买入批准或模拟成交。</p>
  </div>
</template>
<style scoped>
.p2-economics__values { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-2); }
.p2-economics { overflow-wrap: anywhere; min-width: 0; }
</style>
