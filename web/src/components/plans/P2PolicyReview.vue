<script setup lang="ts">
import { computed } from "vue";
import type { Json } from "./planSchema";
const props = defineProps<{ candidate: Json }>();
function record(value: Json | undefined): Record<string, Json> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}
const rules = computed(() => {
  const plan = record(props.candidate);
  if (plan.schema_version !== 8 || !Array.isArray(plan.ordinary_rules)) return [];
  return plan.ordinary_rules.filter(r => "pretrade_policy" in record(r)).map(r => {
    const rule = record(r), policy = record(rule.pretrade_policy);
    return { id: String(rule.rule_id), sizing: record(policy.sizing), economics: record(policy.economics),
      evidence: Array.isArray(policy.level_evidence) ? policy.level_evidence : [] };
  });
});
const modes: Record<string, string> = { NONE: "不计算费用", PREVIEW_ONLY: "研究估算，不阻断买入", REQUIRED: "明确数值买入门槛" };
</script>
<template>
  <section v-if="rules.length" aria-label="波动数量与费用政策审核" class="p2-review">
    <h3>波动数量与费用政策审核</h3>
    <p>先按波动分档得到基础量 Q0，再按大盘状态处理。确认后冻结数量；费用采用执行时的当前报价重新检查。</p>
    <article v-for="rule in rules" :key="rule.id">
      <h4>{{ rule.id }}</h4>
      <p>{{ rule.sizing.mode === 'ATR_RATIO_TIERS' ? 'ATR14 / 收盘价分档' : '固定基础量 Q0' }}；费用模式：{{ modes[String(rule.economics.mode)] ?? '缺少明确模式' }}。</p>
      <p v-if="rule.economics.mode !== 'NONE' && !rule.evidence.length">缺少来源维度证据，审核不能通过。</p>
      <p>压力位和风险位分别需要价格结构及另一独立维度；MA20 与布林中轨属于同一趋势维度。</p>
    </article>
    <p>费用版本、适用证券、有效日期及包含关系必须逐项核对。研究估算不代表实际盈亏；未明确的门槛不会自动补充。</p>
    <p>两条例外路径仍需逐次批准，破位路径数量必须人工填写；批准后还需单独确认整笔模拟交易。风险退出不受买入费用门槛阻断。</p>
  </section>
</template>
<style scoped>
.p2-review { display: grid; gap: var(--space-3); border: var(--border-technical); padding: var(--space-3); overflow-wrap: anywhere; }
</style>
