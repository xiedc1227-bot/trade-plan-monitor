<script setup lang="ts">
import type { CapitalAssessment } from "../../api/generated";
defineProps<{ assessment: CapitalAssessment; historical?: boolean }>();
const reasons: Record<string, string> = {
  CAPITAL_BASE_UNKNOWN: "当前完整批次成本未知，需单独核对并确认",
  CAPITAL_POSITION_UNKNOWN: "模拟库存未知，需先明确初始化",
  CAPITAL_QUANTITY_UNKNOWN: "本次数量尚未明确",
  CAPITAL_QUOTE_UNKNOWN: "当前核实报价不足",
  CAPITAL_OVERFLOW: "金额超出可精确计算范围",
  CAPITAL_LIMIT_EXCEEDED: "买入后超过金额上限，整笔暂停",
  MAX_QUANTITY_CAPACITY: "股数容量不足，整笔暂停",
  ECONOMICS_SCHEDULE_NOT_APPLICABLE: "明确费用表不适用于当前证券或日期",
};
const money = (value: number | null) => value == null ? "待核验" : `${(value / 100).toFixed(2)} 元`;
</script>
<template>
  <section class="capital-assessment" aria-label="整笔金额评估">
    <h4>{{ assessment.phase === 'CONFIRMATION' ? '确认时金额依据' : assessment.phase === 'EXECUTION' ? '当前执行金额复核' : '当前只读金额预览' }}</h4>
    <p>{{ assessment.mode === 'OPEN_COST_CAP' ? '持仓成本占用上限' : '持仓市值上限' }} · {{ assessment.outcome === 'PASS' ? '本次整笔金额通过' : assessment.outcome === 'FAIL' ? '本次整笔暂停' : '依据不足，暂停买入' }}。</p>
    <p v-if="historical">历史依据，当前需重新核验。</p>
    <p>检查数量 {{ assessment.quantity ?? '尚未填写' }} 股；参考报价 {{ money(assessment.price_fen) }}；合计持仓 {{ assessment.total_qty ?? '未知' }} 股。</p>
    <dl class="capital-assessment__values"><dt>金额上限</dt><dd>{{ money(assessment.cap_fen) }}</dd>
      <dt>买入前占用 / 买入后占用</dt><dd>{{ money(assessment.before_fen) }} / {{ money(assessment.after_fen) }}</dd>
      <dt>整笔买入后剩余金额</dt><dd>{{ money(assessment.remaining_fen) }}</dd>
      <dt>股数容量</dt><dd>{{ assessment.share_capacity.mode === 'UNBOUNDED' ? '不设股数上限' : assessment.share_capacity.mode === 'UNKNOWN' ? '库存未知' : `${assessment.share_capacity.remaining_qty} 股` }}</dd>
      <dt>库存修订 / 预算修订</dt><dd>{{ assessment.inventory_revision ?? '未知' }} / {{ assessment.book_revision ?? '尚未建账或不需要成本' }}</dd></dl>
    <p v-for="code in assessment.blockers" :key="code">{{ reasons[code] ?? '当前金额依据未满足要求，请核对来源和适用费用后刷新' }}</p>
    <p>按已确定的整笔数量检查，超限不缩量。预览不预占预算、不授予买入权限，也不阻断技术风险卖出。</p>
  </section>
</template>
<style scoped>
.capital-assessment { display: grid; gap: var(--space-2); min-width: 0; overflow-wrap: anywhere; border: var(--border-technical); padding: var(--space-3); }
.capital-assessment__values { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); gap: var(--space-2); margin: 0; }
.capital-assessment__values dd { margin: 0; }
</style>
