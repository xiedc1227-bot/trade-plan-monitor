<script setup lang="ts">
import { computed, useId } from "vue";
import type { ReadinessContext } from "../../api/planReadiness";
import { usePlanReadiness } from "../../composables/usePlanReadiness";
import { formatDisplayDateTime } from "../../formatters/dateTime";

const props = defineProps<{ context: ReadinessContext | null; locations: Readonly<Record<string, string>> }>();
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
  AUTHORITY_UNAVAILABLE: "当前权威不可用", DEPENDENCY_UNVERIFIED: "所需依据尚未验证", DELIVERY_UNVERIFIED: "通知交付尚未验证",
  UPGRADE_REQUIRED: "需要升级后才能验证", CONTEXT_CHANGED: "读取上下文已变化", EVIDENCE_EXPIRED: "证据已过期",
  TARGET_MISMATCH: "评估目标不一致", SERVICE_PENDING: "服务尚在等待", SAFETY_BLOCKED: "安全条件阻断", CONFIGURATION_BLOCKED: "配置条件阻断",
};
const label = (value: string | null | undefined) => value == null ? "未验证" : labels[value] ?? value;
const yesNo = (value: boolean | null | undefined) => value == null ? "未验证" : value ? "是" : "否";
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
    <p v-if="phase === 'IDLE'" role="status">请先保存当前编辑，或打开已保存的计划版本。</p>
    <p v-else-if="phase === 'LOADING'" role="status">正在读取当前监控依据…</p>
    <p v-else-if="phase === 'STALE'" role="status">本次监控依据已过期，请重新读取。</p>
    <p v-else-if="phase === 'ERROR'" role="alert">{{ error }}</p>
    <template v-if="assessment">
      <p role="status" aria-live="polite">{{ summary }}</p>
      <p v-if="phase === 'OBSERVED'">尚未建立持续新鲜期；以下为读取时观察，不能作为当前就绪声明。</p>
      <p>范围：{{ label(assessment.snapshot.scope) }} · 计算时间：{{ formatDisplayDateTime(assessment.snapshot.computedAt) }}</p>
      <ul class="plan-readiness__axes" aria-label="监控依赖"><li v-for="axis in assessment.axes" :key="axis.axis">
        <strong>{{ label(axis.axis) }}：{{ label(axis.state) }}</strong><span v-if="axis.reason"> · {{ label(axis.reason) }}</span>
      </li></ul>
      <ol class="plan-readiness__rules" aria-label="逐规则监控结果"><li v-for="row in rows" :key="row.key">
        <h3>{{ label(row.facts.ownerKind) }} · {{ row.facts.ownerId }}</h3>
        <p>{{ label(row.state) }}<span v-if="row.reason"> · {{ label(row.reason) }}</span></p>
        <p v-if="row.facts.evaluatedAt">实际上次比较：{{ formatDisplayDateTime(row.facts.evaluatedAt) }}</p>
        <p v-if="row.facts.expectedConfirmation">预计确认：{{ formatDisplayDateTime(row.facts.expectedConfirmation.expectedAt) }}</p>
        <ul v-if="row.facts.leaves.length"><li v-for="leaf in row.facts.leaves" :key="leaf.conditionPath">
          <code>{{ leaf.conditionPath }}</code>：{{ label(leaf.state) }}<span v-if="leaf.reason"> · {{ label(leaf.reason) }}</span>
        </li></ul>
        <template v-if="row.facts.risk">
          <p v-if="!row.facts.risk.current && row.facts.risk.maintenance.state === 'PASS'">本轮义务维护通过，未作新的条件比较。</p>
          <p v-else>风险义务维护：{{ label(row.facts.risk.maintenance.state) }}</p>
          <p v-if="row.facts.risk.obligation">风险义务：{{ label(row.facts.risk.obligation.status) }}</p>
          <p v-if="row.facts.risk.origin">原属版本：{{ row.facts.risk.origin.planVersionId }} · 原确认依据时间：{{ formatDisplayDateTime(row.facts.risk.origin.evaluatedAt) }}</p>
          <p v-else>原属依据未验证。</p>
        </template>
        <p v-if="row.facts.execution">原批准数量：{{ row.facts.execution.approvedQuantity ?? '未验证' }}；已消耗：{{ yesNo(row.facts.execution.consumed) }}；执行窗口：{{ label(row.facts.execution.windowState) }}。交易资格：{{ row.facts.execution.eligible == null ? '未验证' : row.facts.execution.eligible ? '符合' : '不符合' }}。</p>
        <template v-if="row.facts.money">
          <p>金额所需输入：{{ label(row.facts.money.inputs.state) }}</p>
          <p v-if="row.facts.money.capital">资本检查：{{ label(row.facts.money.capital.outcome) }}；被检查数量：{{ row.facts.money.capital.quantity ?? '未知' }}（不是批准数量）。</p>
          <p v-if="row.facts.money.economics">费用收益检查：{{ label(row.facts.money.economics.outcome) }}；被检查数量：{{ row.facts.money.economics.quantity ?? '未知' }}。</p>
        </template>
        <template v-if="row.facts.notification">
          <p v-if="row.facts.notification.createdAt">原通知创建：{{ formatDisplayDateTime(row.facts.notification.createdAt) }}</p>
          <ul><li v-for="channel in row.facts.notification.channels ?? []" :key="channel.channel">
            <p>{{ label(channel.channel) }} · 已配置：{{ yesNo(channel.configured) }} · 开关启用：{{ yesNo(channel.enabled) }}</p>
            <p>当前发送资格：{{ channel.eligible == null ? '未验证' : channel.eligible ? '符合' : '不符合' }}</p>
            <p>历史分类：{{ label(channel.historicalStatus) }}</p>
            <p>历史发送结果：{{ label(channel.latestAttempt?.status) }}<span v-if="channel.latestAttempt?.deliveredAt"> · {{ formatDisplayDateTime(channel.latestAttempt.deliveredAt) }}</span><span v-if="channel.latestAttempt?.nextRetryAt"> · 重试时间 {{ formatDisplayDateTime(channel.latestAttempt.nextRetryAt) }}</span></p>
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
