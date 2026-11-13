<script setup lang="ts">
import { computed, useId } from "vue";
import type { ReadinessContext } from "../../api/planReadiness";
import type { InventoryRequirements, ReadinessObservation, RuleReadinessFacts } from "../../api/generated-runtime-status";
import { usePlanReadiness } from "../../composables/usePlanReadiness";

const props = defineProps<{ context: ReadinessContext | null; locations: Readonly<Record<string, string>>; unavailableReason?: string }>();
const emit = defineEmits<{ revealField: [path: string]; revealSource: [] }>();
const { phase, assessment, error, refresh } = usePlanReadiness(() => props.context);
const titleId = useId();
const labels: Readonly<Record<string, string>> = {
  READY_FOR_MONITORING: "监控已就绪", WAITING_EXPECTED_CONFIRMATION: "正常等待官方确认", WAITING_REQUIRED_SERVICE: "等待所需服务",
  NEEDS_REVIEW: "需要核对来源与审核", BLOCKED: "存在阻断", UNKNOWN: "尚未确定", PASS: "通过", WAIT: "等待",
  NOT_APPLICABLE: "不适用", CONDITION_TRUE: "条件已成立", CONDITION_FALSE: "条件未成立（已完成检查）",
  WAITING_OFFICIAL_CONFIRMATION: "正常等待官方确认", AWAITING_FIRST_EVALUATION: "等待首次评估", MISSING_INPUT: "缺少必需输入",
  SOURCE_COVERAGE: "来源覆盖", REVIEW_ACTIVATION: "审核与启用", RUNTIME_OWNERSHIP: "当前运行进程", DATA_EVALUATION: "数据与评估",
  INVENTORY_CAPITAL: "适用库存与金额输入", NOTIFICATION_DELIVERY: "通知服务", ORDINARY_RULE: "普通规则", ALERT_RULE: "提醒规则", RISK_BRANCH: "独立风险",
  ALERT_ONLY: "仅提醒", TRADE_RULES: "交易规则", MIXED: "交易规则与提醒", CLEAR: "未触发", PENDING: "等待后续确认", OBSERVATION: "继续观察",
  CONFIRMED: "已确认", FULFILLED: "已完成", IN_APP: "站内通知", CONSOLE: "控制台", WEBHOOK: "Webhook",
  HOLD: "暂缓", ELIGIBLE: "当时符合资格", SUPPRESS: "已抑制", CLAIMED: "已领取，尚未确认送达", RETRY_PENDING: "等待重试", FAILED: "发送失败", DELIVERED: "已送达",
  FAIL: "未通过", NONE: "不计算", OPEN: "开放", CLOSED: "已关闭",
  MISSING_DATA: "缺少必需数据", STALE_DATA: "数据已过期", SOURCE_REVIEW_REQUIRED: "需要重新核对来源与审核",
  HUMAN_EVIDENCE_REQUIRED: "需要明确的人工核验证据", UNDEFINED_RULE: "规则定义待澄清", EXPECTED_CONFIRMATION: "等待确认周期",
  AUTHORITY_UNAVAILABLE: "当前运行依据不可用", DEPENDENCY_UNVERIFIED: "所需依据尚未验证", DELIVERY_UNVERIFIED: "通知交付尚未验证",
  UPGRADE_REQUIRED: "需要升级后才能验证", CONTEXT_CHANGED: "读取上下文已变化", EVIDENCE_EXPIRED: "证据已过期",
  TARGET_MISMATCH: "评估目标不一致", SERVICE_PENDING: "服务尚在等待", SAFETY_BLOCKED: "安全条件阻断", CONFIGURATION_BLOCKED: "配置条件阻断",
  CURRENT_SESSION: "当日交易时段", NEXT_EXCHANGE_SESSION_ONLY: "仅下一交易日",
};
const label = (value: string | null | undefined) => value == null ? "未验证" : labels[value] ?? value;
const yesNo = (value: boolean | null | undefined) => value == null ? "未验证" : value ? "是" : "否";
// Keep the original offset and precision; these are evidence times, not local clock conversions.
const when = (value: string | null | undefined) => value?.replace("T", " ") ?? "未提供";
function targetText(target: RuleReadinessFacts["expectedTarget"]) {
  if (!target) return "未提供";
  return target.kind === "INTRADAY" ? `5分钟确认 · 分段结束 ${when(target.bucket_end)}` : `官方收盘 · 交易日期 ${target.trade_date}`;
}
const availabilityLabels = { CURRENT: "当前读取", CACHED: "缓存记录", UNAVAILABLE: "当前不可用", PERSISTED_ONLY: "仅有持久化记录" };
function observationText(observation: Readonly<Pick<ReadinessObservation, "availability" | "asOf" | "observedAt" | "expiresAt">> | null | undefined, scope = "") {
  if (!observation) return `${scope}观察依据：未提供`;
  const expiry = observation.expiresAt ? `原有效期至：${when(observation.expiresAt)}` : "原有效期：未提供，不表示长期有效";
  return `${scope}观察来源：${availabilityLabels[observation.availability]} · 数据截至：${when(observation.asOf)} · 观察时间：${when(observation.observedAt)} · ${expiry}`;
}
const inputLabels: Readonly<Record<keyof InventoryRequirements, string>> = {
  inventory: "模拟库存", sellability: "可卖数量", quote: "行情报价", simulationBook: "模拟账本",
  costBasis: "持仓成本", fees: "费用", economics: "收益测算",
};
function requiredInputs(requirements: InventoryRequirements) {
  return (Object.keys(inputLabels) as (keyof InventoryRequirements)[]).filter(key => requirements[key] === true)
    .map(key => inputLabels[key]).join("、") || "未要求库存或金额输入";
}
const nextSteps: Readonly<Record<string, string>> = {
  MISSING_DATA: "查看所需输入的数据状态，等待缺失数据补齐后重新读取。",
  STALE_DATA: "等待数据更新后重新读取；过期依据不能用于当前判断。",
  EVIDENCE_EXPIRED: "等待依据更新后重新读取。",
  SOURCE_REVIEW_REQUIRED: "查看原文核对区及对应来源字段，按现有流程核对来源与审核。",
  UNDEFINED_RULE: "查看对应来源字段，澄清未定义的规则参数。",
  HUMAN_EVIDENCE_REQUIRED: "在现有人工事实录入中填写核验证据与实际结论。",
  EXPECTED_CONFIRMATION: "等待所列目标的官方确认，再重新读取。",
  AWAITING_FIRST_EVALUATION: "等待首次评估完成后重新读取。",
  SERVICE_PENDING: "等待所需服务完成当前处理后重新读取。",
  AUTHORITY_UNAVAILABLE: "查看当前运行状态，待运行依据可用后重新读取。",
  CONTEXT_CHANGED: "重新读取当前保存版本及其匹配依据。",
  TARGET_MISMATCH: "核对预期目标与实际已评估目标，等待对应目标完成评估。",
  DELIVERY_UNVERIFIED: "查看现有通知配置与历史发送记录，送达记录不代表当前发送资格。",
  CONFIGURATION_BLOCKED: "查看现有配置中的阻断说明，按现有配置流程处理。",
  UPGRADE_REQUIRED: "查看当前版本的兼容性说明，再按既有升级流程处理。",
};
const nextStep = (reason: string | null | undefined) => reason ? nextSteps[reason] : undefined;
const summary = computed(() => assessment.value?.summary === "READY_FOR_MONITORING" && phase.value !== "CURRENT"
  ? "尚未建立持续新鲜期" : label(assessment.value?.summary));
const rows = computed(() => assessment.value?.rules.map(rule => ({ ...rule,
  key: `${rule.facts.ownerKind}:${rule.facts.ownerId}`,
  location: props.locations[`${rule.facts.ownerKind}:${rule.facts.ownerId}`],
})) ?? []);
function locate(path: string | undefined) { if (path) emit("revealField", path); else emit("revealSource"); }
</script>

<template>
  <section class="plan-readiness" :aria-labelledby="titleId" :aria-busy="phase === 'LOADING'">
    <header><h2 :id="titleId">逐规则监控就绪</h2><p>就绪说明不代表交易批准。数据、执行窗口与通知结果分别核对。</p></header>
    <p v-if="phase === 'IDLE'" role="status">{{ unavailableReason || '请先保存当前编辑，或打开已保存的计划版本。' }}</p>
    <p v-else-if="phase === 'LOADING'" role="status">正在读取当前监控依据…</p>
    <p v-else-if="phase === 'STALE'" role="status">本次监控依据已过期，请重新读取。</p>
    <p v-else-if="phase === 'ERROR'" role="alert">{{ error }}</p>
    <template v-if="assessment">
      <p role="status" aria-live="polite">{{ summary }}</p>
      <p v-if="phase === 'OBSERVED'">尚未建立持续新鲜期；以下为读取时观察，不能作为当前就绪声明。</p>
      <p>范围：{{ label(assessment.snapshot.scope) }} · 计算时间：{{ when(assessment.snapshot.computedAt) }}</p>
      <ul class="plan-readiness__axes" aria-label="监控依赖"><li v-for="axis in assessment.axes" :key="axis.axis">
        <strong>{{ label(axis.axis) }}：{{ label(axis.state) }}</strong><span v-if="axis.reason"> · {{ label(axis.reason) }}</span>
        <p v-if="axis.observation">{{ observationText(axis.observation) }}</p>
        <p v-if="nextStep(axis.reason)">下一步：{{ nextStep(axis.reason) }}</p>
      </li></ul>
      <ol class="plan-readiness__rules" aria-label="逐规则监控结果"><li v-for="row in rows" :key="row.key">
        <h3>{{ label(row.facts.ownerKind) }} · {{ row.facts.ownerId }}</h3>
        <p>{{ label(row.state) }}<span v-if="row.reason"> · {{ label(row.reason) }}</span></p>
        <p>预期目标：{{ targetText(row.facts.expectedTarget) }}</p>
        <p>实际已评估目标：{{ targetText(row.facts.evaluatedTarget) }}</p>
        <p v-if="row.facts.evaluatedAt">实际上次比较：{{ when(row.facts.evaluatedAt) }}</p>
        <p>{{ observationText(row.facts.observation, '规则') }}</p>
        <template v-if="row.facts.expectedConfirmation">
          <p>预计确认：{{ when(row.facts.expectedConfirmation.expectedAt) }} · 待确认目标：{{ targetText(row.facts.expectedConfirmation.target) }}</p>
          <p>{{ observationText(row.facts.expectedConfirmation.observation, '确认日历') }}</p>
        </template>
        <p>所需输入：{{ requiredInputs(row.facts.requirements) }}</p>
        <p v-if="nextStep(row.reason)">下一步：{{ nextStep(row.reason) }}</p>
        <ul v-if="row.facts.leaves.length"><li v-for="leaf in row.facts.leaves" :key="leaf.conditionPath">
          <code>{{ leaf.conditionPath }}</code>：{{ label(leaf.state) }}<span v-if="leaf.reason"> · {{ label(leaf.reason) }}</span>
          <p v-if="nextStep(leaf.reason)">下一步：{{ nextStep(leaf.reason) }}</p>
        </li></ul>
        <template v-if="row.facts.risk">
          <p v-if="!row.facts.risk.current && row.facts.risk.maintenance.state === 'PASS'">本轮义务维护通过，未作新的条件比较。</p>
          <p v-else>风险义务维护：{{ label(row.facts.risk.maintenance.state) }}</p>
          <p v-if="row.facts.risk.maintenance.observation">{{ observationText(row.facts.risk.maintenance.observation, '风险维护') }}</p>
          <p v-if="row.facts.risk.obligation">风险义务：{{ label(row.facts.risk.obligation.status) }}</p>
          <p v-if="row.facts.risk.origin">原属版本：{{ row.facts.risk.origin.planVersionId }} · 原确认依据时间：{{ when(row.facts.risk.origin.evaluatedAt) }}</p>
          <p v-else>原属依据未验证。</p>
        </template>
        <template v-if="row.facts.execution">
          <p>原执行窗口：{{ label(row.facts.execution.executionWindow) }} · 原执行日期：{{ row.facts.execution.executionDate ?? '未提供' }}</p>
          <p>原批准数量：{{ row.facts.execution.approvedQuantity ?? '未验证' }}；已消耗：{{ yesNo(row.facts.execution.consumed) }}；执行窗口：{{ label(row.facts.execution.windowState) }}。交易资格：{{ row.facts.execution.eligible == null ? '未验证' : row.facts.execution.eligible ? '符合' : '不符合' }}。</p>
          <p>{{ observationText(row.facts.execution.observation, '执行') }}</p>
        </template>
        <template v-if="row.facts.money">
          <p>金额所需输入：{{ label(row.facts.money.inputs.state) }}</p>
          <p v-if="row.facts.money.inputs.observation">{{ observationText(row.facts.money.inputs.observation, '金额输入') }}</p>
          <p v-if="nextStep(row.facts.money.inputs.reason)">下一步：{{ nextStep(row.facts.money.inputs.reason) }}</p>
          <p v-if="row.facts.money.capital">资本检查：{{ label(row.facts.money.capital.outcome) }}；被检查数量：{{ row.facts.money.capital.quantity ?? '未知' }}（不是批准数量）。</p>
          <p v-if="row.facts.money.economics">费用收益检查：{{ label(row.facts.money.economics.outcome) }}；被检查数量：{{ row.facts.money.economics.quantity ?? '未知' }}。</p>
        </template>
        <template v-if="row.facts.notification">
          <p>历史通知目标：{{ targetText(row.facts.notification.target ?? null) }}</p>
          <p v-if="row.facts.notification.createdAt">原通知创建：{{ when(row.facts.notification.createdAt) }}</p>
          <p>{{ observationText(row.facts.notification.observation, '通知') }}</p>
          <ul><li v-for="channel in row.facts.notification.channels ?? []" :key="channel.channel">
            <p>{{ label(channel.channel) }} · 已配置：{{ yesNo(channel.configured) }} · 开关启用：{{ yesNo(channel.enabled) }}</p>
            <p>当前发送资格：{{ channel.eligible == null ? '未验证' : channel.eligible ? '符合' : '不符合' }}</p>
            <p>历史分类：{{ label(channel.historicalStatus) }}</p>
            <p v-if="channel.historicalUpdatedAt">历史分类更新时间：{{ when(channel.historicalUpdatedAt) }}</p>
            <p>历史发送结果：{{ label(channel.latestAttempt?.status) }}<span v-if="channel.latestAttempt?.deliveredAt"> · {{ when(channel.latestAttempt.deliveredAt) }}</span><span v-if="channel.latestAttempt?.nextRetryAt"> · 重试时间 {{ when(channel.latestAttempt.nextRetryAt) }}</span></p>
          </li></ul>
        </template>
        <button class="plan-readiness__button" data-action="source" type="button" @click="locate(row.location)">{{ row.location ? '定位规则来源字段' : '查看原文核对区' }}</button>
      </li></ol>
    </template>
    <button class="plan-readiness__button" data-action="refresh" type="button" :disabled="!context || phase === 'LOADING'" @click="refresh">重新读取监控就绪状态</button>
  </section>
</template>

<style scoped>
.plan-readiness { display: grid; gap: var(--space-3); min-width: 0; overflow-wrap: anywhere; }
.plan-readiness__axes, .plan-readiness__rules { display: grid; gap: var(--space-3); padding-inline-start: 1.5rem; min-width: 0; }
.plan-readiness__button { min-height: 2.75rem; max-width: 100%; padding: var(--space-2) var(--space-3); }
</style>
