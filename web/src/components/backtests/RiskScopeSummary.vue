<script setup lang="ts">
import { computed } from "vue";
import type { PlanChange } from "../../api/generated";
import { formatFenAsYuan } from "../../api/backtestValues";

const props = defineProps<{ changes: readonly Readonly<Pick<PlanChange, "target" | "rule_id" | "after">>[] }>();
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const risks = computed(() => {
  const levels = props.changes.find(c => c.target === "levels")?.after;
  return props.changes.filter(c => c.target === "risk_branches" && record(c.after)).map(change => {
    const value = change.after as Record<string, unknown>;
    const scope = record(value.holding_scope) ? value.holding_scope : null;
    const oldOnly = scope?.mode === "BEFORE_TRADE_DATE";
    const newOnly = scope?.mode === "FROM_TRADE_DATE";
    const price = value.kind === "ORDINARY_TECHNICAL"
      ? value.risk_line_fen ?? (record(levels) ? levels.risk_line_fen : null) : null;
    return { id: change.rule_id, kind: value.kind === "ORDINARY_TECHNICAL" ? "普通技术风险退出" : "严重技术风险退出",
      oldOnly, newOnly, date: String(scope?.trade_date ?? ""), end: scope?.end_trade_date,
      price: typeof price === "number" ? `${formatFenAsYuan(String(price))} 元` : null,
      involvesCore: value.involves_core === true,
      fullExit: value.involves_core === true && value.target_core_qty === 0 && value.target_tactical_qty === 0,
      core: value.target_core_qty, tactical: value.target_tactical_qty,
      confirmation: value.evidence_mode === "TWO_OFFICIAL_CLOSES" ? "两次完整收盘确认" : "按已审核的严重风险条件确认" };
  });
});
const onlyOldProtection = computed(() => risks.value.length > 0 && risks.value.every(r => r.oldOnly));
</script>

<template>
  <section class="risk-scopes" aria-label="风险退出适用持仓" data-testid="risk-scope-summary">
    <h6>风险退出适用持仓</h6>
    <p v-if="!risks.length">本份冻结策略没有风险退出规则。</p>
    <div v-for="risk in risks" :key="risk.id ?? risk.kind">
      <p v-if="risk.oldOnly">旧仓保护继续保留：仅适用于 {{ risk.date }} 前取得的持仓；{{ risk.date }} 起买入的新仓不适用此规则。</p>
      <p v-else-if="risk.newOnly">新仓规则：仅适用于 {{ risk.date }} 起买入的持仓<span v-if="risk.end">，截至 {{ risk.end }} 前取得的批次</span>。</p>
      <p v-else>本条适用于整类持仓，冻结策略未按开仓日期区分范围。</p>
      <p>{{ risk.kind }}<template v-if="risk.price"> · 风险线 {{ risk.price }}</template> · {{ risk.confirmation }} · <template v-if="risk.fullExit">范围内持仓全部退出</template><template v-else>范围内退出后目标：<template v-if="risk.involvesCore">核心 {{ risk.core }} 股／</template>机动 {{ risk.tactical }} 股<template v-if="!risk.involvesCore">；不涉及核心仓</template></template>。</p>
    </div>
    <p v-if="onlyOldProtection">本份未明确新仓止损，旧仓止损不会套用于新仓；新仓按本份已审核的交易条件处理。</p>
    <p v-if="risks.some(r => r.oldOnly || r.newOnly)">风险执行只扣减适用批次，仍遵守 T+1 和可卖数量；不可卖的旧仓不会由新仓代替卖出。</p>
  </section>
</template>

<style scoped>
.risk-scopes { padding: var(--space-3); border: var(--border-technical); border-radius: var(--radius-control); }
h6 { font-size: 1rem; margin: 0 0 var(--space-2); }
p { margin: var(--space-2) 0; overflow-wrap: anywhere; }
</style>
