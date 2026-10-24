<script setup lang="ts">
import { computed } from "vue";
import type { Json } from "./planSchema";
const props = defineProps<{ candidate: Json }>();
function record(value: Json | undefined): { [key: string]: Json } {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}
const rules = computed(() => {
  const plan = record(props.candidate);
  if (plan.schema_version !== 7 || !Array.isArray(plan.ordinary_rules)) return [];
  return plan.ordinary_rules.filter(rule => "market_policy" in record(rule)).map((rule, index) => ({
    name: String(record(rule).rule_id ?? `买入规则 ${index + 1}`),
    routes: record(record(record(rule).market_policy).exception_routes),
  }));
});
function permission(value: Json | undefined) {
  return value === "PER_OCCURRENCE" ? "允许逐次申请" : value === "DISABLED" ? "不允许申请" : "缺少许可，阻断审核与执行";
}
</script>
<template>
  <section v-if="rules.length" aria-label="例外路径的计划许可" class="exception-permissions">
    <h3>例外路径的计划许可</h3>
    <p>原文许可、计划审核和启用均不等于逐次批准。每个独立信号还需人工批准一次；批准不执行模拟交易。</p>
    <article v-for="rule in rules" :key="rule.name">
      <h4>{{ rule.name }}</h4>
      <p>偏弱市场最小量例外：{{ permission(rule.routes.weak_minimum) }}。要求大盘偏弱、个股相对强势、S1 满足且无更高优先级风险。</p>
      <p>仅当 0.5 × Q0 &lt; 官方最小量 ≤ Q0，才可申请恰好官方最小量；该最小量须为 100 股整数倍且整笔容量足够。不向上凑量、不缩量。</p>
      <p>破位市场强势例外：{{ permission(rule.routes.broken_strong) }}。要求大盘明显破位、个股相对强势、S2 满足且无更高优先级风险。</p>
      <p>Qe 必须人工填写，可低于或高于半量；0 &lt; Qe ≤ Q0，符合官方数量规则与 100 股整数倍，并有整笔容量。无半量或全量默认值。</p>
    </article>
    <p>批准后数量冻结，仅下一交易日有效。拒绝、撤销、失效、过期或已消耗的同一独立信号不能重新批准；复制计划不会恢复机会。</p>
  </section>
</template>
<style scoped>
.exception-permissions { display: grid; gap: var(--space-3); border: var(--border-technical); padding: var(--space-3); overflow-wrap: anywhere; }
</style>
