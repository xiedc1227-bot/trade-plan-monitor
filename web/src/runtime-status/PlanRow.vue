<script setup lang="ts">
import { RouterLink } from "vue-router";
import { computed } from "vue";
import ExplicitConditionEvidence from "../components/plans/ExplicitConditionEvidence.vue";
import { useRuntimeContext } from "./context";
import { displayTime, reasonLabel } from "./presentation";
import type { PlanEntry } from "./store";
const props = defineProps<{ row: PlanEntry; detail?: boolean }>();
const { store } = useRuntimeContext();
const actions = { BUY: "买入", SELL: "卖出", RISK_ALERT: "风险提醒" };
const outcomes = computed(() => props.row.availability !== "UNAVAILABLE" && props.row.planFamily === "EXPLICIT_RULES"
  ? new Map(props.row.explicitRuntime.ruleOutcomes.map(outcome => [outcome.ruleId, outcome])) : new Map());
function actionable(ruleId?: string): boolean {
  const row = props.row; const installed = store.snapshot?.symbols.find(item => item.symbol === row.symbol);
  if (row.availability !== "CURRENT" || !installed || installed.availability !== "CURRENT" || row.planFamily !== installed.planFamily) return false;
  if (row.planFamily === "EXPLICIT_RULES" && installed.planFamily === "EXPLICIT_RULES" && row.resultHash !== installed.resultHash) return false;
  if (row.planFamily === "LEGACY_LOW_BUY" && installed.planFamily === "LEGACY_LOW_BUY" && row.decision.resultHash !== installed.decision.resultHash) return false;
  return store.isActionable(row, ruleId);
}
</script>

<template>
  <article class="runtime-panel" :data-symbol="row.symbol" :data-availability="row.availability">
    <header class="runtime-heading">
      <h2><RouterLink :to="`/stocks/${row.symbol}`">{{ row.name }} · {{ row.symbol }}</RouterLink></h2>
      <span>{{ row.planFamily === 'CONDITION_PLAN' ? '条件计划' : row.planFamily === 'EXPLICIT_RULES' ? '明确规则历史' : '旧低吸计划历史' }} · {{ row.availability }}</span>
    </header>
    <p>启用修订 {{ row.activationRevision }} · {{ row.scope.status }} · {{ reasonLabel(row.scope.reasonCode) }}</p>
    <p v-if="row.availability === 'UNAVAILABLE'" role="status">暂无判断 · {{ reasonLabel(row.reasonCode) }}</p>
    <template v-else-if="row.planFamily === 'EXPLICIT_RULES'">
      <p>结果周期：{{ displayTime(row.explicitRuntime.targetBucketEnd) }}；评估时间：{{ displayTime(row.explicitRuntime.evaluatedAt) }}</p>
      <p v-if="row.availability === 'CACHED'">历史缓存；以下结果保留原始周期，不具备当前提醒资格。</p>
      <ul class="runtime-rules" aria-label="逐规则判断与当前资格">
        <li v-for="rule in row.ruleEligibility" :key="rule.ruleId" :data-rule-id="rule.ruleId" :data-actionable="actionable(rule.ruleId)">
          <strong>{{ rule.ruleId }} · {{ actions[rule.action] }}</strong>
          <p>{{ actionable(rule.ruleId) ? '当前提醒有效' : '当前提醒无效' }} · {{ reasonLabel(rule.reasonCode) }}</p>
          <p v-if="rule.currentActionable && !actionable(rule.ruleId)">当前展示已撤销，等待新的权威快照。</p>
          <p v-if="rule.actionableUntil">有效期限：{{ displayTime(rule.actionableUntil) }}</p>
          <template v-if="rule.sourceAlert">
            <p>原始提醒评估：{{ displayTime(rule.sourceAlert.evaluatedAt) }}；原始数据截止：{{ displayTime(rule.sourceAlert.dataCutoff) }}</p>
            <p class="runtime-hash">原始结果：{{ rule.sourceAlert.resultHash }}</p>
          </template>
          <template v-if="detail">
            <template v-for="outcome in outcomes.has(rule.ruleId) ? [outcomes.get(rule.ruleId)!] : []" :key="outcome.ruleId">
              <p>条件 {{ outcome.conditionCode }} · {{ outcome.outcome }} · {{ outcome.suppressionReason ?? '—' }}</p>
              <p v-if="outcome.missingInputs?.length || outcome.blockers?.length">缺少：{{ outcome.missingInputs?.join('、') || '—' }}；阻断：{{ outcome.blockers?.join('、') || '—' }}</p>
              <ExplicitConditionEvidence v-if="outcome.conditionEvidence" :evidence="outcome.conditionEvidence" />
            </template>
          </template>
        </li>
      </ul>
    </template>
    <template v-else-if="row.planFamily === 'CONDITION_PLAN'">
      <p>评估时间：{{ displayTime(row.planRuntime.evaluatedAt) }}</p>
      <p v-if="row.availability === 'CACHED'">历史缓存，等待当前权威输入。</p>
      <p :data-actionable="actionable()">{{ actionable() ? '当前提醒有效' : '当前提醒无效' }}</p>
      <ul><li v-for="signal in row.planRuntime.signals" :key="signal.signalId">{{ signal.side === 'BUY' ? '买入' : '卖出' }} · {{ signal.state }} · 计划{{ signal.plannedQty }}股 · 已模拟{{ signal.simulatedQty }}股</li></ul>
      <ul v-if="row.planRuntime.dataBlockers.length"><li v-for="blocker in row.planRuntime.dataBlockers" :key="blocker">{{ blocker }}</li></ul>
      <RouterLink :to="`/plans/${row.planVersionId}`">核对条件证据与模拟交易</RouterLink>
    </template>
    <template v-else>
      <p>行情截止：{{ displayTime(row.decision.marketDataAt) }}；评估时间：{{ displayTime(row.decision.evaluatedAt) }}</p>
      <p v-if="row.availability === 'CACHED'">历史缓存；保留原始行情截止，不具备当前提醒资格。</p>
      <p>{{ row.decision.signalType }} · {{ row.decision.zone }} · 风险 {{ row.decision.riskStatus }}</p>
      <p v-if="row.decision.riskBreachTradeDate">风险触发日期：{{ row.decision.riskBreachTradeDate }}</p>
      <p :data-actionable="actionable()">{{ actionable() ? '当前提醒有效' : '当前提醒无效' }}</p>
      <p v-if="row.currentActionable && !actionable()">当前展示已撤销，等待新的权威快照。</p>
      <p v-if="row.actionableUntil">有效期限：{{ displayTime(row.actionableUntil) }}</p>
      <p>价格 {{ row.decision.priceFen === null ? '—' : (row.decision.priceFen / 100).toFixed(2) }}；条件 {{ row.satisfiedConditionCount }} / {{ row.totalConditionCount }}；仓位 {{ row.decision.position.totalQuantity }}</p>
      <p>下一步：{{ row.decision.nextStep.code }}</p>
    </template>
    <p class="runtime-hash">计划 {{ row.planVersionId }} · {{ row.planHash }}</p>
  </article>
</template>
