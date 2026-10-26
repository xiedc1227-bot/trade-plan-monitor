<script setup lang="ts">
import { computed } from "vue";
import type { Json } from "./planSchema";
const props = defineProps<{ candidate: Json }>();
function record(value: Json | undefined): Record<string, Json> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}
const plan = computed(() => record(props.candidate));
const limit = computed(() => record(record(plan.value.position).limit));
const policy = computed(() => record(limit.value.capital_policy));
const costs = computed(() => record(policy.value.buy_cost_schedule));
const provenance = computed(() => record(costs.value.provenance));
const amount = computed(() => Number.isSafeInteger(policy.value.cap_fen) && Number(policy.value.cap_fen) > 0
  ? `${(Number(policy.value.cap_fen) / 100).toFixed(2)} 元` : "缺少明确金额，审核受阻");
</script>
<template>
  <section v-if="plan.schema_version === 9" class="capital-policy" aria-label="金额上限政策审核">
    <h3>金额上限政策审核</h3>
    <p>{{ limit.mode === 'CAPITAL_ONLY' ? '仅金额上限，不设股数上限' : limit.mode === 'QUANTITY_AND_CAPITAL' ? `股数与金额同时限制：最多 ${limit.max_qty ?? '待确认'} 股` : '缺少明确限制方式，审核受阻' }}。</p>
    <p>单只证券 CORE 与 TACTICAL 合计上限：{{ amount }}；仅用于模拟持仓。</p>
    <template v-if="policy.mode === 'OPEN_COST_CAP'">
      <h4>持仓成本占用上限</h4>
      <p>保留持仓的历史成本，加上本次买入金额、明确估算的费用和滑点，不得超过上限。卖出仅释放对应批次的历史成本，卖出盈利不会增加预算。</p>
      <p>费用版本 {{ costs.version ?? '缺少来源版本' }}；适用日期 {{ costs.effective_from ?? '待确认' }} 至 {{ costs.effective_through ?? '待确认' }}；来源 {{ provenance.source ?? '缺少来源' }}。</p>
      <p>已有持仓须单独确认完整批次成本。计划审核、启用和费用模式选择都不会自动补成本。</p>
    </template>
    <template v-else-if="policy.mode === 'MARKET_VALUE_CAP'">
      <h4>持仓市值上限</h4>
      <p>使用当前核实报价计算买入后全部持仓市值。此口径不需要开仓成本，价格变化后重新检查。</p>
    </template>
    <p v-else role="status">缺少明确金额口径。仅写“总投入预算”不能确定为成本、市值或累计买入，须补充原文或人工定义。</p>
    <p>先按波动、大盘及已批准的例外规则确定数量，再整笔检查金额。超限不会自动缩量，不从预算反推基础量。</p>
    <p>逐次批准与模拟执行分开；预览不预占预算。技术风险卖出不受买入金额条件阻断。</p>
  </section>
</template>
<style scoped>
.capital-policy { display: grid; gap: var(--space-3); min-width: 0; overflow-wrap: anywhere; border: var(--border-technical); padding: var(--space-3); }
</style>
