<script setup lang="ts">
import { computed } from "vue";
import type { MarketExceptionDecision, MarketLinkageDecision, UnifiedConditionEvidence } from "../../api/generated";
import { formatDisplayDateTime } from "../../formatters/dateTime";
import { choiceLabels } from "./planSchema";
const props = defineProps<{ decision: MarketLinkageDecision | MarketExceptionDecision; stale?: boolean }>();
const labels: Record<string, string> = {
  NORMAL_TRANSITION: "正常或过渡", WEAK: "偏弱", BROKEN: "明显破位", UNKNOWN: "证据不足",
  STRONG: "相对强势", NOT_STRONG: "不满足相对强势", SATISFIED: "满足", UNSATISFIED: "不满足", MISSING_INPUT: "缺少输入",
  P1_EXCEPTION_REQUIRED: "需要例外授权；当前阶段保持阻断", MARKET_BROKEN: "大盘明显破位，暂停普通买入",
  MARKET_INPUT_UNKNOWN: "大盘必要输入不足，暂停买入", MARKET_RULES_UNKNOWN: "适用官方数量规则未核实",
  CAPACITY_INSUFFICIENT: "仓位容量不足，整笔阻断", INVENTORY_UNKNOWN: "模拟持仓未知",
  CONDITION_UNSATISFIED: "所选确认条件未满足", CONDITION_UNKNOWN: "所选确认条件输入不足",
  RISK_BLOCKED: "更高优先级风险阻断", RISK_UNKNOWN: "风险输入尚未核实",
  CONFIRMATION_UNKNOWN: "所选确认条件输入不足", CONFIRMATION_UNMET: "所选确认条件未满足",
  HIGHER_PRIORITY_RISK: "更高优先级风险阻断", RISK_INPUT_UNKNOWN: "风险输入尚未核实",
  POSITION_UNKNOWN: "模拟持仓未知", MAX_QUANTITY_CAPACITY: "仓位容量不足，整笔阻断",
  MARKET_QUANTITY_INCOMPATIBLE: "市场数量单位与模拟交易单位没有合法交集",
  MARKET_QUANTITY_BELOW_MINIMUM: "候选数量低于市场最小买入量，暂停普通买入",
};
const facts = computed(() => props.decision.market.facts);
const sizing = computed(() => props.decision.calculation);
const conditionLabels: Record<string, string> = {
  ALL: "全部满足", ANY: "任一满足", REVIEWED_FACT: "人工核验条件",
  DAILY_PRICE_COMPARE: "日线价格比较", DAILY_PRICE_IN_RANGE: "日线价格区间",
  DAILY_VOLUME_RATIO: "日线量比", DAILY_CANDLE_RATIO: "日线蜡烛比例",
  DAILY_INDICATOR_COMPARE: "日线指标比较", DAILY_CLOSE_SEQUENCE: "连续收盘条件",
  DAILY_PRIOR_CLOSE: "先行完整收盘条件",
};
const confirmationRows = computed(() => {
  const rows: { path: string; proof: UnifiedConditionEvidence }[] = [];
  function visit(proofs: UnifiedConditionEvidence[], parent = "") {
    proofs.forEach((proof, i) => {
      const path = parent ? `${parent}.${i + 1}` : String(i + 1);
      rows.push({ path, proof });
      visit(proof.children ?? [], path);
    });
  }
  visit(props.decision.confirmation);
  return rows;
});
function shown(value: string | number | null | undefined) { return value ?? "待核验"; }
function ratio(value: string | null | undefined) { return value == null ? "待核验" : `${(Number(value) * 100).toFixed(2)}%`; }
</script>

<template>
  <section class="linkage-evidence" aria-label="大盘联动判断">
    <h4>大盘联动 · {{ labels[decision.market.regime] }} · {{ decision.decision_session }}</h4>
    <p v-if="stale" role="status">历史判断，当前不可据此执行。</p>
    <p>参考指数 {{ facts.reference_market.index_code }}；确认组 {{ decision.selection.group ?? '待定' }}。</p>
    <p>证据截止（上海时间）：<time :datetime="decision.evidence_cutoff">{{ formatDisplayDateTime(decision.evidence_cutoff) }}</time>。</p>
    <dl class="linkage-evidence__values">
      <dt>指数收盘 / MA20 / MA60</dt><dd>{{ shown(facts.close) }} / {{ shown(facts.ma20) }} / {{ shown(facts.ma60) }}</dd>
      <dt>5 个交易日前 MA20 / 前 20 日最低价（不含当日）</dt><dd>{{ shown(facts.ma20_5) }} / {{ shown(facts.low20) }}</dd>
      <dt>基础数量 × 系数 → 合法候选量</dt><dd>{{ sizing.base_quantity }} × {{ shown(sizing.factor) }} → {{ shown(sizing.candidate_quantity) }} 股</dd>
      <dt>可用容量 / 本次评估授权量</dt><dd>{{ shown(sizing.capacity) }} / {{ sizing.authorized_quantity }} 股</dd>
      <dt>市场最小量 / 递增单位</dt><dd>{{ shown(sizing.minimum) }} / {{ shown(sizing.increment) }} 股；模拟交易仍按 100 股整数倍</dd>
    </dl>
    <p>确认后冻结整笔数量；容量不足时不缩量，下一交易日收盘后失效。</p>
    <template v-if="decision.strength">
      <p>相对强势：{{ labels[decision.strength.strength] }}；比较日期 {{ decision.strength.endpoint_dates?.join(' / ') ?? '待核验' }}。</p>
      <p>5 日收益（个股 / 指数）：{{ ratio(decision.strength.stock_return5) }} / {{ ratio(decision.strength.index_return5) }}；差额 {{ ratio(decision.strength.difference5) }}。</p>
      <p>20 日收益（个股 / 指数）：{{ ratio(decision.strength.stock_return20) }} / {{ ratio(decision.strength.index_return20) }}；差额 {{ ratio(decision.strength.difference20) }}。</p>
      <p>个股收盘 / MA20：{{ shown(decision.strength.stock_close) }} / {{ shown(decision.strength.stock_ma20) }}（分）；复权口径 {{ decision.strength.basis_id ?? '待核验' }}。</p>
    </template>
    <p v-else>本路径无需相对强势条件。</p>
    <ul v-if="sizing.blockers.length" aria-label="买入阻断原因"><li v-for="reason in sizing.blockers" :key="reason">{{ labels[reason] ?? reason }}</li></ul>
    <details><summary>查看确认条件与官方数量依据</summary>
      <ul aria-label="逐项确认依据"><li v-for="{ path, proof } in confirmationRows" :key="path">
        {{ path }} · {{ conditionLabels[proof.condition.type] ?? proof.condition.type }} · {{ labels[proof.outcome] ?? proof.outcome }}
        <span v-if="'comparator' in proof.condition && proof.condition.comparator"> · {{ proof.condition.comparator }}</span>
        <span v-if="proof.operands?.length"> · {{ proof.operands.join(' / ') }}</span>
        <span v-if="proof.session_dates?.length"> · 日期 {{ proof.session_dates.join(' / ') }}</span>
        <p v-if="proof.condition.type === 'REVIEWED_FACT'">{{ choiceLabels[proof.condition.fact_kind] ?? proof.condition.fact_kind }}：{{ proof.condition.evidence_requirement }}</p>
      </li></ul>
      <p v-if="decision.quantity_rules">官方规则自 {{ decision.quantity_rules.effective_from }} 生效；{{ decision.quantity_rules.article }}。<a :href="decision.quantity_rules.source_url" target="_blank" rel="noopener noreferrer">查看交易所规则</a></p>
    </details>
  </section>
</template>

<style scoped>
.linkage-evidence { display: grid; gap: var(--space-3); border: var(--border-technical); padding: var(--space-3); min-width: 0; overflow-wrap: anywhere; }
.linkage-evidence__values { display: grid; grid-template-columns: minmax(8rem, 1fr) 1fr; gap: var(--space-2); }
@media (max-width: 48rem) { .linkage-evidence__values { grid-template-columns: 1fr; } }
</style>
